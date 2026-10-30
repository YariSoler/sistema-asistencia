
import os
import re
import math
import uuid
import secrets
import hmac
import hashlib
import json
import csv
from datetime import datetime, date, time, timedelta, timezone
from copy import deepcopy
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import requests
import io
import base64
import qrcode

from flask import (
    Flask,
    render_template,
    session,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    abort,
    Response,
)
from dotenv import load_dotenv
from supabase import create_client


# =========================================================
# 1. CONFIGURACIÓN
# =========================================================

load_dotenv()

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
SUPABASE_KEY = (os.getenv("SUPABASE_KEY") or "").strip()
SUPABASE_SERVICE_ROLE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
).strip()
FLASK_SECRET_KEY = (os.getenv("FLASK_SECRET_KEY") or "").strip()

if not all((
    SUPABASE_URL,
    SUPABASE_KEY,
    SUPABASE_SERVICE_ROLE_KEY,
    FLASK_SECRET_KEY,
)):
    raise RuntimeError(
        "Falta configurar SUPABASE_URL, SUPABASE_KEY, "
        "SUPABASE_SERVICE_ROLE_KEY o FLASK_SECRET_KEY en .env."
    )

# Cliente del servidor para consultar la base de datos.
supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY


def csrf_token():
    """Devuelve el token de la sesión y crea uno cuando aún no existe."""
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.context_processor
def exponer_csrf_token():
    return {"csrf_token": csrf_token}


@app.before_request
def proteger_solicitudes_con_csrf():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    esperado = session.get("_csrf_token")
    recibido = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    valido = (
        isinstance(esperado, str)
        and isinstance(recibido, str)
        and hmac.compare_digest(esperado, recibido)
    )
    if valido:
        return None
    if request.path.startswith("/api/") or request.is_json:
        return jsonify(error="La solicitud no tiene un token CSRF válido. Recarga la página e inténtalo de nuevo."), 400
    abort(400, description="La solicitud no tiene un token CSRF válido. Recarga la página e inténtalo de nuevo.")


# =========================================================
# 2. FUNCIONES AUXILIARES
# =========================================================

CARGOS_PERFIL = {
    "SST": "trabajador",
    "Operario": "trabajador",
    "Coordinador": "coordinador",
    "Administrador": "administrador",
}

NOVEDADES_TIPOS = {
    "permiso": ("Permiso", "orange"),
    "vacaciones": ("Vacaciones", "purple"),
    "incapacidad": ("Incapacidad", "red"),
    "inasistencia_injustificada": ("Ausencia injustificada", "red"),
}

NOVEDADES_HISTORICAS = {
    "inasistencia_justificada": ("Histórica · Inasistencia justificada", "yellow"),
    "llegada_tarde": ("Histórica · Llegada tarde", "coral"),
    "salida_anticipada": ("Histórica · Salida anticipada", "coral"),
    "horas_extras": ("Histórica · Horas extras", "green"),
    "otra_justificada": ("Histórica · Otra justificada", "blue"),
}
NOVEDADES_TIPOS_PARA_FILTRO = NOVEDADES_TIPOS
_DASHBOARD_CACHE = None


def fecha_actual_bogota(ahora=None):
    """Devuelve fecha local Bogotá; usa UTC-5 fijo si falta la base tzdata del sistema."""
    try:
        zona = ZoneInfo("America/Bogota")
    except ZoneInfoNotFoundError:
        zona = timezone(timedelta(hours=-5))
    instante = ahora or datetime.now(timezone.utc)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(zona).date()


def zona_horaria_bogota():
    try:
        return ZoneInfo("America/Bogota")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-5))


def formatear_hora_bogota(valor):
    """Convierte una marca timestamptz de Supabase a hora legible de Colombia."""
    if not valor:
        return "—"
    try:
        instante = valor if isinstance(valor, datetime) else datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return instante.astimezone(zona_horaria_bogota()).strftime("%d/%m/%Y %H:%M:%S")
    except (TypeError, ValueError, OverflowError):
        return "—"


def etiqueta_novedad(tipo):
    return NOVEDADES_TIPOS.get(tipo) or NOVEDADES_HISTORICAS.get(tipo) or (tipo or "Novedad", "blue")


def generar_codigo_qr():
    """Genera un código QR aleatorio y difícil de adivinar."""
    return secrets.token_urlsafe(32)


def generar_codigo_qr_unico(intentos=5):
    """Comprueba que el código aleatorio no exista antes de guardarlo."""
    for _ in range(intentos):
        codigo = generar_codigo_qr()
        existentes = (
            supabase.table("trabajadores")
            .select("id")
            .eq("qr", codigo)
            .limit(1)
            .execute()
        ).data
        if not existentes:
            return codigo
    raise RuntimeError("No fue posible generar un código QR único.")


def imagen_qr_base64(codigo):
    """Genera la imagen QR como una cadena Base64 para mostrarla en HTML."""
    imagen = qrcode.make(codigo)
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def diagnostico_error_supabase(exc):
    """Obtiene solo código/mensaje controlado del error para diagnóstico local."""
    codigo = getattr(exc, "code", None)
    mensaje = getattr(exc, "message", None)
    if not isinstance(mensaje, str):
        mensaje = ""
    mensaje = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~-]+", "Bearer [REDACTED]", mensaje)
    mensaje = re.sub(
        r"(?i)(service[_ -]?role[_ -]?key|api[_ -]?key|password)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        mensaje,
    )
    return codigo or "sin_sqlstate", mensaje[:300]


def texto_formulario(campo):
    return (request.form.get(campo) or "").strip()


def obtener_persona(persona_id):
    resultado = (
        supabase.table("trabajadores")
        .select("id, nombre, identificacion, cargo, perfil, estado, auth_user_id, qr")
        .eq("id", persona_id)
        .limit(1)
        .execute()
    )
    return resultado.data[0] if resultado.data else None


def auth_admin_headers():
    """Encabezados privilegiados para llamadas servidor a servidor."""
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def crear_cuenta_auth(correo, contrasena):
    """Crea una cuenta en Supabase Auth sin exponer la clave privilegiada."""
    try:
        respuesta = requests.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=auth_admin_headers(),
            json={"email": correo, "password": contrasena, "email_confirm": True},
            timeout=20,
        )
    except requests.RequestException:
        app.logger.exception("No fue posible comunicarse con Supabase Auth al crear una cuenta.")
        return None, "No fue posible conectar con el servicio de usuarios."

    if respuesta.status_code not in (200, 201):
        # La respuesta del proveedor puede contener datos personales; no se registra.
        app.logger.warning("Supabase Auth rechazó la creación de una cuenta (HTTP %s).", respuesta.status_code)
        if respuesta.status_code in (409, 422):
            return None, "No se pudo crear la cuenta. Verifica que el correo no esté registrado y que la contraseña cumpla la política de Supabase."
        return None, "Supabase Auth no pudo crear la cuenta. Revisa su configuración y vuelve a intentarlo."

    try:
        user_id = respuesta.json()["id"]
    except (ValueError, KeyError, TypeError):
        app.logger.error("Supabase Auth respondió sin el identificador de la cuenta creada.")
        return None, "Supabase Auth devolvió una respuesta inesperada. Revisa Usuarios en Supabase antes de reintentar."
    return user_id, None


def eliminar_cuenta_auth(user_id):
    """Elimina una cuenta Auth; 404 significa que ya no existe."""
    try:
        respuesta = requests.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers=auth_admin_headers(),
            timeout=20,
        )
        if respuesta.status_code in (200, 204, 404):
            return True
        app.logger.error("No se pudo compensar el alta de Auth (HTTP %s).", respuesta.status_code)
    except requests.RequestException:
        app.logger.exception("No se pudo conectar para compensar un alta parcial de Auth.")
    return False


def validar_datos_persona(persona_id=None):
    identificacion = texto_formulario("identificacion")
    nombre = texto_formulario("nombre")
    cargo = texto_formulario("cargo")
    estado = texto_formulario("estado").lower()

    if not identificacion or not nombre:
        return None, "La identificación y el nombre son obligatorios."
    if cargo not in CARGOS_PERFIL:
        return None, "Selecciona un cargo válido."
    if estado not in ("activo", "inactivo"):
        return None, "Selecciona un estado válido."

    # Una identificación debe corresponder a una sola persona.
    consulta = (
        supabase.table("trabajadores")
        .select("id")
        .eq("identificacion", identificacion)
    )
    if persona_id is not None:
        consulta = consulta.neq("id", persona_id)
    if consulta.limit(1).execute().data:
        return None, "Ya existe una persona con esa identificación."

    return {
        "identificacion": identificacion,
        "nombre": nombre,
        "cargo": cargo,
        "perfil": CARGOS_PERFIL[cargo],
        "estado": estado,
    }, None

def requiere_perfil(*perfiles_requeridos):
    """Comprueba en Supabase que la sesión siga activa y autorizada."""

    if "usuario_id" not in session:
        return redirect(url_for("login"))

    try:
        perfiles = consultar_perfil(session["usuario_id"])
    except Exception:
        app.logger.exception("No fue posible verificar el perfil de la sesión.")
        session.clear()
        flash("No fue posible verificar tu acceso. Inicia sesión de nuevo.")
        return redirect(url_for("login"))

    if len(perfiles) != 1:
        session.clear()
        flash("La cuenta ya no tiene un registro de trabajador válido.")
        return redirect(url_for("login"))

    persona = perfiles[0]
    perfil_real = (persona.get("perfil") or "").strip().lower()
    estado_real = (persona.get("estado") or "").strip().lower()
    if estado_real != "activo" or perfil_real not in ("administrador", "coordinador"):
        session.clear()
        flash("Tu cuenta está inactiva o ya no tiene un perfil de acceso.")
        return redirect(url_for("login"))

    # La base de datos es la autoridad; la sesión nunca conserva un rol obsoleto.
    session["perfil"] = perfil_real
    session["trabajador_id"] = persona["id"]
    if perfil_real not in perfiles_requeridos:
        flash("No tienes permisos para acceder a esa sección.")
        return redirect(url_for("panel"))

    return None


def consultar_perfil(usuario_id):
    """Busca el registro asociado al usuario autenticado."""

    resultado = (
        supabase.table("trabajadores")
        .select("id, nombre, perfil, estado, auth_user_id")
        .eq("auth_user_id", usuario_id)
        .execute()
    )

    return resultado.data


def verificar_coordinador_api():
    """Valida el rol actual contra Supabase y devuelve JSON en caso de rechazo."""
    if "usuario_id" not in session:
        return None, (jsonify(error="Inicia sesión para continuar."), 401)

    try:
        perfiles = consultar_perfil(session["usuario_id"])
    except Exception as exc:
        app.logger.warning("Fallo verificando sesión de API (%s).", type(exc).__name__)
        session.clear()
        return None, (jsonify(error="No fue posible verificar la sesión."), 503)

    if len(perfiles) != 1:
        session.clear()
        return None, (jsonify(error="La sesión no tiene un registro válido."), 401)

    persona = perfiles[0]
    if (persona.get("perfil") or "").strip().lower() != "coordinador":
        return None, (jsonify(error="Solo un coordinador puede registrar asistencia y visitas."), 403)
    if (persona.get("estado") or "").strip().lower() != "activo":
        session.clear()
        return None, (jsonify(error="La cuenta está inactiva."), 401)

    session["perfil"] = "coordinador"
    session["trabajador_id"] = persona["id"]
    return persona, None


def persona_por_qr(valor_qr, permitir_inactivo=False):
    """Resuelve QRs operativos de trabajadores o coordinadores."""
    if not isinstance(valor_qr, str) or not valor_qr.strip() or len(valor_qr) > 2048:
        return None, (jsonify(error="El código QR está vacío o no es válido."), 400)

    try:
        respuesta = (
            supabase.table("trabajadores")
            .select("id, nombre, cargo, perfil, estado, qr")
            .eq("qr", valor_qr.strip())
            .limit(2)
            .execute()
        )
    except Exception as exc:
        app.logger.warning("Fallo consultando QR (%s).", type(exc).__name__)
        return None, (jsonify(error="No fue posible consultar el trabajador."), 503)

    if not respuesta.data:
        return None, (jsonify(error="No hay un trabajador asociado a ese QR."), 404)
    if len(respuesta.data) > 1:
        return None, (jsonify(error="El QR está asociado a varios registros. Corrige la asignación antes de usarlo."), 409)

    persona = respuesta.data[0]
    if (persona.get("perfil") or "").strip().lower() not in ("trabajador", "coordinador"):
        return None, (jsonify(error="Ese QR no pertenece a un perfil operativo autorizado."), 409)
    if not permitir_inactivo and (persona.get("estado") or "").strip().lower() != "activo":
        return None, (jsonify(error="El trabajador está inactivo."), 409)
    return persona, None


def persona_por_id_asistencia(valor_id, permitir_inactivo=False):
    """Resuelve un ID ya seleccionado en el servidor; no autentica al usuario."""
    try:
        persona_id = int(valor_id)
        if persona_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return None, (jsonify(error="La persona seleccionada no es válida."), 400)
    try:
        respuesta = (
            supabase.table("trabajadores")
            .select("id, nombre, cargo, perfil, estado, qr")
            .eq("id", persona_id)
            .limit(2)
            .execute()
        )
    except Exception as exc:
        app.logger.warning("Fallo consultando persona para asistencia (%s).", type(exc).__name__)
        return None, (jsonify(error="No fue posible consultar la persona."), 503)
    if not respuesta.data:
        return None, (jsonify(error="No se encontró la persona seleccionada."), 404)
    if len(respuesta.data) > 1:
        return None, (jsonify(error="El identificador interno no es único."), 409)
    persona = respuesta.data[0]
    if (persona.get("perfil") or "").strip().lower() != "trabajador":
        return None, (jsonify(error="La búsqueda por identificación solo admite trabajadores operativos."), 409)
    if not permitir_inactivo and (persona.get("estado") or "").strip().lower() != "activo":
        return None, (jsonify(error="El trabajador está inactivo."), 409)
    return persona, None


def resolver_persona_asistencia(datos, permitir_inactivo=False):
    if "trabajador_id" in datos:
        return persona_por_id_asistencia(datos.get("trabajador_id"), permitir_inactivo)
    return persona_por_qr(datos.get("qr"), permitir_inactivo)


def lista_paginada(query, tamano=1000):
    """Lee todas las páginas de una consulta PostgREST sin ampliar columnas."""
    filas = []
    inicio = 0
    while True:
        pagina = query.range(inicio, inicio + tamano - 1).execute().data or []
        filas.extend(pagina)
        if len(pagina) < tamano:
            return filas
        inicio += tamano


def validar_evento_offline(datos, tipo, coordinador_id, persona_id=None, cot=None, proyecto=None):
    """Valida/normaliza el evento y calcula un hash estable del cuerpo autorizado."""
    try:
        operacion_id = str(uuid.UUID(str(datos.get("operacion_id", ""))))
        ocurrio = datetime.fromisoformat(str(datos.get("ocurrio_en", "")).replace("Z", "+00:00"))
        if ocurrio.tzinfo is None:
            raise ValueError("timezone required")
        ocurrio = ocurrio.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError):
        return None, (jsonify(error="La operación necesita un UUID y una fecha con zona horaria válidos."), 400)

    estado_ubicacion = datos.get("ubicacion_estado")
    latitud = longitud = precision = None
    if estado_ubicacion == "obtenida":
        try:
            latitud = float(datos.get("latitud"))
            longitud = float(datos.get("longitud"))
            precision = float(datos["precision_m"]) if datos.get("precision_m") is not None else None
        except (TypeError, ValueError, KeyError):
            return None, (jsonify(error="La ubicación marcada como obtenida no tiene datos válidos."), 400)
        if (not math.isfinite(latitud) or not math.isfinite(longitud)
                or latitud < -90 or latitud > 90 or longitud < -180 or longitud > 180
                or (precision is not None and (not math.isfinite(precision) or precision < 0))):
            return None, (jsonify(error="Las coordenadas o la precisión GPS están fuera de rango."), 400)
    elif estado_ubicacion != "no_disponible":
        return None, (jsonify(error="Indica si la ubicación se obtuvo o no estuvo disponible."), 400)

    nota = datos.get("observaciones")
    if nota is not None and not isinstance(nota, str):
        return None, (jsonify(error="Las observaciones deben ser texto."), 400)
    nota = nota.strip() if isinstance(nota, str) else ""
    if len(nota) > 1000:
        return None, (jsonify(error="Las observaciones del tramo no pueden superar 1000 caracteres."), 400)

    canonico = {
        "tipo": tipo,
        "coordinador_id": coordinador_id,
        "persona_id": persona_id,
        "cot": cot,
        "proyecto": proyecto,
        "ocurrio_en": ocurrio.isoformat(),
        "ubicacion_estado": estado_ubicacion,
        "latitud": latitud,
        "longitud": longitud,
        "precision_m": precision,
    }
    if nota:
        # Preserve the hash of queued ACT06 operations that have no note.
        canonico["observaciones"] = nota
    payload_hash = hashlib.sha256(
        json.dumps(canonico, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "operacion_id": operacion_id,
        "ocurrio_en": ocurrio.isoformat(),
        "latitud": latitud,
        "longitud": longitud,
        "precision_m": precision,
        "ubicacion_obtenida": estado_ubicacion == "obtenida",
        "observaciones": nota or None,
        "payload_hash": payload_hash,
    }, None


def buscar_operario_visita_por_identificacion(identificacion):
    """Busca un operario activo y devuelve solo los datos necesarios para elegirlo."""
    if not isinstance(identificacion, str):
        return None, (jsonify(error="Ingresa el número de identificación del operario."), 400)
    identificacion = identificacion.strip()
    if not identificacion or len(identificacion) > 80:
        return None, (jsonify(error="El número de identificación no es válido."), 400)
    try:
        resultado = (
            supabase.table("trabajadores")
            .select("id, nombre, cargo, perfil, estado")
            .eq("identificacion", identificacion)
            .limit(2)
            .execute()
        )
    except Exception as exc:
        app.logger.warning("Falló la búsqueda del participante de visita (%s).", type(exc).__name__)
        return None, (jsonify(error="No fue posible buscar al operario ahora."), 503)
    if not resultado.data:
        return None, (jsonify(error="No se encontró un operario con esa identificación."), 404)
    if len(resultado.data) != 1:
        return None, (jsonify(error="La identificación no es única. Solicita revisión al administrador."), 409)
    persona = resultado.data[0]
    if (persona.get("perfil") or "").strip().lower() != "trabajador":
        return None, (jsonify(error="La identificación no corresponde a un operario."), 409)
    if (persona.get("estado") or "").strip().lower() != "activo":
        return None, (jsonify(error="El operario está inactivo."), 409)
    return {key: persona.get(key) for key in ("id", "nombre", "cargo")}, None


# =========================================================
# 3. PÁGINA INICIAL
# =========================================================

@app.route("/")
def inicio():
    if session.get("usuario_id"):
        return redirect(url_for("panel"))
    return render_template("login.html")


# =========================================================
# 4. INICIO DE SESIÓN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "GET":
        if session.get("usuario_id"):
            return redirect(url_for("panel"))
        return render_template("login.html")

    correo = request.form.get("correo", "").strip()
    contrasena = request.form.get("contrasena", "")
    rol_solicitado = request.form.get("rol", "").strip().lower()

    if rol_solicitado not in ("administrador", "coordinador"):
        flash("Selecciona un rol válido.")
        return redirect(url_for("login"))

    if not correo or not contrasena:
        flash("Ingresa tu correo y contraseña.")
        return redirect(url_for("login"))

    # PASO 1: autenticar las credenciales con Supabase Auth.
    # Se usa SUPABASE_KEY para la autenticación.
    try:
        respuesta = requests.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={
                "apikey": SUPABASE_KEY,
                "Content-Type": "application/json",
            },
            json={
                "email": correo,
                "password": contrasena,
            },
            timeout=15,
        )

    except requests.RequestException:
        app.logger.exception(
            "No fue posible conectar con Supabase Auth."
        )
        flash("No fue posible conectar con el servicio de autenticación.")
        return redirect(url_for("login"))

    if respuesta.status_code != 200:
        # El proveedor puede incluir datos sensibles en el cuerpo de error.
        app.logger.warning("Error de autenticación Supabase (HTTP %s).", respuesta.status_code)

        flash(
            "No se pudo iniciar sesión. "
            "Revisa las credenciales y la confirmación del correo."
        )
        return redirect(url_for("login"))

    # PASO 2: obtener la identidad autenticada.
    try:
        datos = respuesta.json()
        usuario = datos["user"]
        usuario_id = usuario["id"]

    except (ValueError, KeyError, TypeError):
        app.logger.exception(
            "Supabase Auth devolvió una respuesta inesperada."
        )
        flash("No fue posible validar la respuesta de autenticación.")
        return redirect(url_for("login"))

    # PASO 3: buscar el perfil vinculado.
    try:
        perfiles = consultar_perfil(usuario_id)

    except Exception:
        app.logger.exception(
            "Error consultando el perfil en la tabla trabajadores."
        )
        flash(
            "La autenticación funcionó, pero no fue posible "
            "consultar tu perfil. Revisa la configuración de Supabase."
        )
        return redirect(url_for("login"))

    # PASO 4: comprobar si existe el vínculo.
    if not perfiles:
        app.logger.warning(
            "No se encontró vínculo para el UID autenticado: %s",
            usuario_id,
        )

        flash(
            "Tu cuenta de acceso existe, pero no está vinculada "
            "a un registro de trabajadores."
        )
        return redirect(url_for("login"))

    persona = perfiles[0]

    perfil_real = (persona.get("perfil") or "").strip().lower()
    estado = (persona.get("estado") or "").strip().lower()

    # PASO 5: validar estado y permisos.
    if estado != "activo":
        flash("Tu cuenta está inactiva. Contacta al administrador.")
        return redirect(url_for("login"))

    if perfil_real not in ("administrador", "coordinador"):
        flash("Tu perfil no tiene permiso para iniciar sesión.")
        return redirect(url_for("login"))

    if perfil_real != rol_solicitado:
        flash("El rol seleccionado no corresponde a tu cuenta.")
        return redirect(url_for("login"))

    # PASO 6: crear la sesión.
    session.clear()
    session["usuario_id"] = usuario_id
    session["trabajador_id"] = persona["id"]
    session["correo"] = usuario.get("email", correo)
    session["perfil"] = perfil_real

    # PASO 7: redirigir según el perfil.
    if perfil_real == "administrador":
        return redirect(url_for("dashboard_admin"))

    return redirect(url_for("registro_coordinador"))


# =========================================================
# 5. REDIRECCIÓN DEL PANEL
# =========================================================

@app.route("/panel")
def panel():

    acceso = requiere_perfil("administrador", "coordinador")
    if acceso:
        return acceso

    perfil = session.get("perfil")

    if perfil == "administrador":
        return redirect(url_for("dashboard_admin"))

    if perfil == "coordinador":
        return redirect(url_for("registro_coordinador"))

    session.clear()
    flash("Tu sesión no tiene un perfil válido.")
    return redirect(url_for("login"))


# =========================================================
# 6. ÁREA DEL ADMINISTRADOR
# =========================================================

def dashboard_desde_tablas_existentes(hoy):
    """Fallback para instalaciones donde aún no existe la RPC agregada del dashboard."""
    zona = zona_horaria_bogota()
    inicio_local = datetime.combine(hoy, time.min, tzinfo=zona)
    fin_local = datetime.combine(hoy + timedelta(days=1), time.min, tzinfo=zona)
    inicio_utc = inicio_local.astimezone(timezone.utc).isoformat()
    fin_utc = fin_local.astimezone(timezone.utc).isoformat()

    personas_activas = lista_paginada(
        supabase.table("trabajadores").select("id,nombre", count="exact")
        .eq("perfil", "trabajador").eq("estado", "activo").order("id")
    )
    nombres = {fila["id"]: fila.get("nombre", "Trabajador") for fila in personas_activas}
    ids_activos = set(nombres)

    entradas_hoy = lista_paginada(
        supabase.table("registros_asistencia")
        .select("trabajador_id,cot,proyecto,fecha_entrada,fecha_salida")
        .gte("fecha_entrada", inicio_utc).lt("fecha_entrada", fin_utc)
        .order("fecha_entrada", desc=True)
    )
    turnos_abiertos = lista_paginada(
        supabase.table("registros_asistencia")
        .select("trabajador_id,cot,proyecto,fecha_entrada,fecha_salida")
        .lt("fecha_entrada", inicio_utc).is_("fecha_salida", "null")
    )
    presentes_ids = {
        fila.get("trabajador_id") for fila in entradas_hoy + turnos_abiertos
        if fila.get("trabajador_id") in ids_activos
    }

    novedades_dia = lista_paginada(
        supabase.table("novedades")
        .select("id,tipo,trabajador_id,fecha_inicio,fecha_fin,proyecto,cot,motivo,observaciones,creado_en,estado")
        .eq("estado", "registrada").lte("fecha_inicio", hoy.isoformat())
        .gte("fecha_fin", hoy.isoformat()).order("creado_en", desc=True)
    )
    ausentes_reportados = {
        fila.get("trabajador_id") for fila in novedades_dia
        if fila.get("tipo") == "inasistencia_injustificada" and fila.get("trabajador_id") in ids_activos
    }
    recientes = (
        supabase.table("novedades")
        .select("id,tipo,trabajador_id,fecha_inicio,fecha_fin,proyecto,cot,motivo,observaciones,creado_en,estado")
        .eq("estado", "registrada").order("creado_en", desc=True)
        .range(0, 4).execute().data or []
    )

    resumen = {}
    for fila in entradas_hoy:
        clave = (fila.get("cot") or "", fila.get("proyecto") or "")
        grupo = resumen.setdefault(clave, {"cot": clave[0], "proyecto": clave[1], "tramos": 0, "abiertos": 0})
        grupo["tramos"] += 1
        if fila.get("fecha_salida") is None:
            grupo["abiertos"] += 1

    ids_recientes = {fila.get("trabajador_id") for fila in recientes} - set(nombres)
    if ids_recientes:
        encontrados = supabase.table("trabajadores").select("id,nombre").in_("id", sorted(ids_recientes)).execute().data or []
        nombres.update({fila["id"]: fila.get("nombre", "Trabajador") for fila in encontrados})
    for fila in recientes:
        fila["trabajador_nombre"] = nombres.get(fila.get("trabajador_id"), "Trabajador")

    return {
        "metricas": {
            "trabajadores_activos": len(ids_activos),
            "presentes": len(presentes_ids),
            "ausencias_injustificadas": len(ausentes_reportados),
            "novedades_vigentes": len(novedades_dia),
        },
        "proyectos": sorted(resumen.values(), key=lambda fila: (fila["cot"], fila["proyecto"])),
        "novedades_recientes": recientes,
    }


def consultar_dashboard(hoy):
    """Prefiere el agregado SQL y usa las tablas conocidas si falta esa función."""
    try:
        respuesta = supabase.rpc("dashboard_admin_act07", {"p_dia": hoy.isoformat()}).execute()
        datos = respuesta.data
        if isinstance(datos, list) and len(datos) == 1 and isinstance(datos[0], dict):
            datos = datos[0]
        if not isinstance(datos, dict):
            raise ValueError("La consulta agregada no devolvió datos válidos.")
        return {
            "metricas": {key: datos.get(key) for key in (
                "trabajadores_activos", "presentes", "ausencias_injustificadas", "novedades_vigentes"
            )},
            "proyectos": datos.get("proyectos") or [],
            "novedades_recientes": datos.get("novedades_recientes") or [],
            "origen": "agregado",
        }
    except Exception as rpc_exc:
        app.logger.info("El agregado del dashboard no está disponible (%s); se consultan tablas existentes.", type(rpc_exc).__name__)
        datos = dashboard_desde_tablas_existentes(hoy)
        datos["origen"] = "tablas"
        return datos

@app.route("/admin/dashboard")
def dashboard_admin():
    global _DASHBOARD_CACHE

    acceso = requiere_perfil("administrador")

    if acceso:
        return acceso

    hoy = fecha_actual_bogota()
    errores = []
    try:
        datos = consultar_dashboard(hoy)
        actualizado_en = datetime.now(timezone.utc).astimezone(zona_horaria_bogota()).strftime("%d/%m/%Y %H:%M:%S · Colombia")
        metricas_recibidas = datos.get("metricas") or datos
        _DASHBOARD_CACHE = {
            "fecha": hoy.isoformat(),
            "actualizado_en": actualizado_en,
            "metricas": {
                "trabajadores_activos": metricas_recibidas.get("trabajadores_activos"),
                "presentes": metricas_recibidas.get("presentes"),
                "ausencias_injustificadas": metricas_recibidas.get("ausencias_injustificadas"),
                "novedades_vigentes": metricas_recibidas.get("novedades_vigentes"),
            },
            "proyectos": datos.get("proyectos") or [],
        }
        metricas = deepcopy(_DASHBOARD_CACHE["metricas"])
        proyectos = deepcopy(_DASHBOARD_CACHE["proyectos"])
        novedades_recientes = datos.get("novedades_recientes") or []
        novedades_disponibles = True
    except Exception as exc:
        app.logger.warning("No se pudo cargar el dashboard agregado (%s).", type(exc).__name__)
        errores.append("No se pudieron actualizar los indicadores. Se muestran los últimos datos confirmados, si existen.")
        if _DASHBOARD_CACHE:
            metricas = deepcopy(_DASHBOARD_CACHE["metricas"])
            proyectos = deepcopy(_DASHBOARD_CACHE["proyectos"])
            ultima_actualizacion = _DASHBOARD_CACHE["actualizado_en"]
        else:
            metricas = {
                "trabajadores_activos": None, "presentes": None,
                "ausencias_injustificadas": None, "novedades_vigentes": None,
            }
            proyectos = []
            ultima_actualizacion = None
        novedades_recientes = []
        novedades_disponibles = False
    else:
        ultima_actualizacion = _DASHBOARD_CACHE["actualizado_en"]

    for novedad in novedades_recientes:
        novedad["tipo_etiqueta"], novedad["color"] = etiqueta_novedad(novedad.get("tipo"))
        novedad["creado_en_local"] = formatear_hora_bogota(novedad.get("creado_en"))
    return render_template(
        "administrador/dashboard.html", correo=session.get("correo", ""), hoy=hoy.isoformat(),
        metricas=metricas, proyectos=proyectos, novedades_recientes=novedades_recientes,
        novedades_disponibles=novedades_disponibles,
        errores=errores, ultima_actualizacion=ultima_actualizacion,
        fecha_datos=_DASHBOARD_CACHE.get("fecha") if _DASHBOARD_CACHE else None,
        datos_desactualizados=bool(errores),
    )


def consultar_filas_reporte(desde, hasta, trabajador_id=None):
    zona = zona_horaria_bogota()
    inicio_local = datetime.combine(desde, time.min, tzinfo=zona)
    fin_local = datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=zona)
    consulta = (
        supabase.table("registros_asistencia")
        .select("id,trabajador_id,cot,proyecto,fecha_entrada,fecha_salida")
        .gte("fecha_entrada", inicio_local.astimezone(timezone.utc).isoformat())
        .lt("fecha_entrada", fin_local.astimezone(timezone.utc).isoformat())
        .order("fecha_entrada", desc=True)
    )
    if trabajador_id:
        consulta = consulta.eq("trabajador_id", trabajador_id)
    return consulta


@app.route("/reportes")
def reportes_admin():
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    hoy = fecha_actual_bogota()
    try:
        desde = date.fromisoformat(request.args.get("desde") or date(hoy.year, hoy.month, 1).isoformat())
        hasta = date.fromisoformat(request.args.get("hasta") or hoy.isoformat())
    except ValueError:
        return render_template(
            "administrador/reportes.html", correo=session.get("correo", ""), trabajadores=[],
            registros=[], pagina=1, hay_siguiente=False, desde="", hasta="",
            error="Indica un rango de fechas válido.",
        ), 400
    if hasta < desde:
        flash("La fecha final no puede ser anterior a la inicial.", "error")
        return redirect(url_for("reportes_admin"))

    identificacion = (request.args.get("trabajador_id") or "").strip()
    trabajador_id = None
    if identificacion:
        try:
            trabajador_id = int(identificacion)
            if trabajador_id <= 0:
                raise ValueError
        except ValueError:
            return render_template(
                "administrador/reportes.html", correo=session.get("correo", ""), trabajadores=[],
                registros=[], pagina=1, hay_siguiente=False, desde=desde.isoformat(),
                hasta=hasta.isoformat(), trabajador_id=identificacion,
                error="Selecciona un trabajador válido.",
            ), 400

    try:
        trabajadores = lista_paginada(
            supabase.table("trabajadores").select("id,nombre,identificacion,cargo")
            .eq("perfil", "trabajador").order("nombre")
        )
        consulta = consultar_filas_reporte(desde, hasta, trabajador_id)
        if request.args.get("formato") == "csv":
            filas = []
            inicio = 0
            while True:
                lote = consulta.range(inicio, inicio + 999).execute().data or []
                filas.extend(lote)
                if len(filas) > 50000:
                    raise ValueError("El rango supera 50.000 filas; descarga por periodos más cortos.")
                if len(lote) < 1000:
                    break
                inicio += 1000
            nombres = {fila["id"]: fila.get("nombre", "Trabajador") for fila in trabajadores}
            salida = io.StringIO(newline="")
            escritor = csv.writer(salida)
            escritor.writerow(["Fecha", "Trabajador", "COT", "Proyecto", "Entrada (Colombia)", "Salida (Colombia)"])
            def celda_csv(valor):
                texto = "" if valor is None else str(valor)
                return "'" + texto if texto.startswith(("=", "+", "-", "@")) else texto
            for fila in filas:
                escritor.writerow([
                    formatear_hora_bogota(fila.get("fecha_entrada")), celda_csv(nombres.get(fila.get("trabajador_id"), "Trabajador")),
                    celda_csv(fila.get("cot")), celda_csv(fila.get("proyecto")),
                    formatear_hora_bogota(fila.get("fecha_entrada")), formatear_hora_bogota(fila.get("fecha_salida")),
                ])
            contenido = "\ufeff" + salida.getvalue()
            return Response(
                contenido, mimetype="text/csv; charset=utf-8",
                headers={"Content-Disposition": f"attachment; filename=asistencia-{desde.isoformat()}-{hasta.isoformat()}.csv"},
            )

        pagina = max(1, min(int(request.args.get("pagina", "1")), 100000))
        respuesta = consulta.range((pagina - 1) * 100, pagina * 100).execute().data or []
        hay_siguiente = len(respuesta) > 100
        registros = respuesta[:100]
        nombres = {fila["id"]: fila.get("nombre", "Trabajador") for fila in trabajadores}
        for fila in registros:
            fila["trabajador_nombre"] = nombres.get(fila.get("trabajador_id"), "Trabajador")
            fila["entrada_local"] = formatear_hora_bogota(fila.get("fecha_entrada"))
            fila["salida_local"] = formatear_hora_bogota(fila.get("fecha_salida"))
        error = None
    except ValueError as exc:
        registros, trabajadores, pagina, hay_siguiente = [], [], 1, False
        error = str(exc)
    except Exception as exc:
        app.logger.warning("No se pudo generar el informe de asistencia (%s).", type(exc).__name__)
        registros, trabajadores, pagina, hay_siguiente = [], [], 1, False
        error = "No fue posible consultar los registros para este periodo."
    return render_template(
        "administrador/reportes.html", correo=session.get("correo", ""), trabajadores=trabajadores,
        registros=registros, pagina=pagina, hay_siguiente=hay_siguiente,
        desde=desde.isoformat(), hasta=hasta.isoformat(), trabajador_id=identificacion, error=error,
    )


def validar_datos_novedad(datos):
    """Valida los valores del formulario antes de enviar un INSERT a Supabase."""
    try:
        trabajador_id = int(datos.get("trabajador_id", ""))
        if trabajador_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return None, "Selecciona un trabajador válido."

    tipo = (datos.get("tipo") or "").strip()
    if tipo not in NOVEDADES_TIPOS:
        return None, "Selecciona un tipo de novedad válido."

    try:
        fecha_inicio = date.fromisoformat((datos.get("fecha_inicio") or "").strip())
        fecha_fin = date.fromisoformat((datos.get("fecha_fin") or "").strip())
    except (TypeError, ValueError):
        return None, "Indica fechas inicial y final válidas."
    if fecha_fin < fecha_inicio:
        return None, "La fecha final no puede ser anterior a la inicial."

    def leer_hora(nombre):
        texto = (datos.get(nombre) or "").strip()
        if not texto:
            return None, None
        try:
            return time.fromisoformat(texto).strftime("%H:%M:%S"), None
        except ValueError:
            return None, f"La hora {nombre.replace('_', ' ')} no es válida."

    hora_inicio, error = leer_hora("hora_inicio")
    if error:
        return None, error
    hora_fin, error = leer_hora("hora_fin")
    if error:
        return None, error
    if fecha_inicio == fecha_fin and hora_inicio and hora_fin and hora_fin <= hora_inicio:
        return None, "La hora final debe ser posterior a la inicial para el mismo día."

    cot = (datos.get("cot") or "").strip()
    proyecto = (datos.get("proyecto") or "").strip()
    motivo = (datos.get("motivo") or "").strip()
    observaciones = (datos.get("observaciones") or "").strip()
    if len(cot) > 200 or len(proyecto) > 300:
        return None, "El COT no puede superar 200 caracteres y el proyecto 300."
    if not motivo or len(motivo) > 1000:
        return None, "El motivo es obligatorio y no puede superar 1000 caracteres."
    if len(observaciones) > 2000:
        return None, "Las observaciones no pueden superar 2000 caracteres."
    return {
        "trabajador_id": trabajador_id,
        "tipo": tipo,
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": fecha_fin.isoformat(),
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "cot": cot or None,
        "proyecto": proyecto or None,
        "motivo": motivo,
        "observaciones": observaciones or None,
    }, None


def clave_dedupe_novedad(datos):
    canonico = json.dumps(datos, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def renderizar_novedades(filtros=None, form_data=None):
    filtros = filtros or {}
    trabajadores = []
    novedades = []
    errores = []
    try:
        trabajadores = lista_paginada(
            supabase.table("trabajadores")
            .select("id,nombre,cargo,estado,perfil")
            .eq("perfil", "trabajador")
            .order("nombre")
        )
    except Exception as exc:
        app.logger.warning("No se pudo cargar el personal para novedades (%s).", type(exc).__name__)
        errores.append("No se pudo cargar la lista de trabajadores.")

    try:
        pagina = max(1, min(int(filtros.get("pagina", 1)), 100000))
        consulta = supabase.table("novedades").select(
            "id,trabajador_id,tipo,fecha_inicio,fecha_fin,hora_inicio,hora_fin,cot,proyecto,motivo,observaciones,responsable_id,creado_en,estado"
        ).eq("estado", "registrada").order("fecha_inicio", desc=True).order("creado_en", desc=True)
        desde = (filtros.get("desde") or "").strip()
        hasta = (filtros.get("hasta") or "").strip()
        if desde:
            consulta = consulta.gte("fecha_fin", desde)
        if hasta:
            consulta = consulta.lte("fecha_inicio", hasta)
        trabajador_id = (filtros.get("trabajador_id") or "").strip()
        if trabajador_id:
            consulta = consulta.eq("trabajador_id", int(trabajador_id))
        tipo = (filtros.get("tipo") or "").strip()
        if tipo:
            consulta = consulta.eq("tipo", tipo)
        novedades = consulta.range((pagina - 1) * 100, pagina * 100).execute().data or []
        hay_siguiente = len(novedades) > 100
        novedades = novedades[:100]
        ids = sorted({fila["trabajador_id"] for fila in novedades if fila.get("trabajador_id") is not None})
        nombres = {}
        if ids:
            filas_personas = supabase.table("trabajadores").select("id,nombre").in_("id", ids).execute().data or []
            nombres = {fila["id"]: fila.get("nombre", "Trabajador") for fila in filas_personas}
        for fila in novedades:
            fila["trabajador_nombre"] = nombres.get(fila.get("trabajador_id"), "Trabajador")
            fila["tipo_etiqueta"], fila["color"] = etiqueta_novedad(fila.get("tipo"))
    except (TypeError, ValueError):
        errores.append("El identificador de trabajador del filtro no es válido.")
    except Exception as exc:
        app.logger.warning("No se pudo consultar el módulo de novedades (%s).", type(exc).__name__)
        errores.append("No se pudieron consultar las novedades. Comprueba la conexión con la base de datos.")

    return render_template(
        "administrador/novedades.html", correo=session.get("correo", ""), trabajadores=trabajadores,
        novedades=novedades, tipos_novedad=NOVEDADES_TIPOS,
        tipos_filtro=NOVEDADES_TIPOS_PARA_FILTRO, filtros=filtros,
        pagina=pagina, hay_siguiente=hay_siguiente,
        form_data=form_data or {}, errores=errores,
    )


@app.route("/novedades", methods=["GET", "POST"])
def novedades_admin():
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    if request.method == "POST":
        datos, error = validar_datos_novedad(request.form)
        if error:
            flash(error, "error")
            return renderizar_novedades(form_data=request.form)

        try:
            trabajador = (
                supabase.table("trabajadores")
                .select("id,perfil")
                .eq("id", datos["trabajador_id"])
                .limit(1)
                .execute().data
            )
        except Exception as exc:
            app.logger.warning("No se pudo validar persona al crear novedad (%s).", type(exc).__name__)
            flash("No fue posible validar el trabajador. La novedad no se envió.", "error")
            return renderizar_novedades(form_data=request.form)
        if not trabajador or (trabajador[0].get("perfil") or "").lower() != "trabajador":
            flash("El registro seleccionado no corresponde a un trabajador.", "error")
            return renderizar_novedades(form_data=request.form)

        datos["responsable_id"] = session.get("trabajador_id")
        datos["dedupe_key"] = clave_dedupe_novedad(datos)
        try:
            respuesta = supabase.table("novedades").insert(datos).select("id").execute()
            if not respuesta.data:
                flash("El servidor no confirmó la creación. Verifica la lista antes de volver a enviar.", "error")
                return renderizar_novedades(form_data=request.form)
        except Exception as exc:
            codigo, mensaje = diagnostico_error_supabase(exc)
            if codigo == "23505" or "novedades_dedupe_key" in mensaje:
                flash("Ya existe una novedad con los mismos datos. Revisa la lista antes de crear otra.", "error")
            else:
                app.logger.warning("No se pudo guardar novedad; tipo=%s código=%s.", type(exc).__name__, codigo)
                flash("No se pudo guardar la novedad. No se confirmó el registro; verifica Supabase antes de reintentar.", "error")
            return renderizar_novedades(form_data=request.form)
        flash("Novedad registrada correctamente.", "success")
        return redirect(url_for("novedades_admin"))

    filtros = {key: request.args.get(key, "").strip() for key in ("desde", "hasta", "trabajador_id", "tipo", "pagina")}
    for key in ("desde", "hasta"):
        if filtros[key]:
            try:
                date.fromisoformat(filtros[key])
            except ValueError:
                flash("El filtro de fechas no tiene un formato válido.", "error")
                filtros[key] = ""
    if filtros["tipo"] and filtros["tipo"] not in NOVEDADES_TIPOS_PARA_FILTRO:
        flash("El filtro de tipo no es válido.", "error")
        filtros["tipo"] = ""
    try:
        filtros["pagina"] = str(max(1, int(filtros["pagina"] or "1")))
    except ValueError:
        filtros["pagina"] = "1"
    return renderizar_novedades(filtros=filtros)


def contar_todas_las_novedades():
    respuesta = supabase.table("novedades").select("id", count="exact").limit(1).execute()
    cantidad = getattr(respuesta, "count", None)
    if cantidad is None:
        raise RuntimeError("La base de datos no devolvió el conteo de novedades.")
    return int(cantidad)


def renderizar_confirmacion_eliminar_novedades(error=None, mensaje=None):
    cantidad = None
    if not error:
        try:
            cantidad = contar_todas_las_novedades()
        except Exception as exc:
            app.logger.warning("No se pudo contar novedades para depuración (%s).", type(exc).__name__)
            error = "No se pudo consultar el total de novedades. No se eliminó información."
    return render_template(
        "administrador/eliminar_novedades.html", correo=session.get("correo", ""),
        cantidad=cantidad, error=error, mensaje=mensaje,
    )


@app.route("/novedades/eliminar-todas", methods=["GET", "POST"])
def eliminar_todas_novedades_admin():
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso
    if request.method == "GET":
        return renderizar_confirmacion_eliminar_novedades()

    if request.form.get("confirmacion_texto", "").strip() != "ELIMINAR":
        return renderizar_confirmacion_eliminar_novedades(
            error="Escribe ELIMINAR para confirmar. No se borró ninguna novedad."
        ), 400
    try:
        cantidad_antes = contar_todas_las_novedades()
        if cantidad_antes == 0:
            return renderizar_confirmacion_eliminar_novedades(mensaje="No había novedades para eliminar.")
        # El filtro solo afecta la clave primaria de novedades. No toca otras tablas.
        supabase.table("novedades").delete().not_.is_("id", "null").execute()
        restantes = contar_todas_las_novedades()
        if restantes != 0:
            return renderizar_confirmacion_eliminar_novedades(
                error=f"La base aún reporta {restantes} novedades. Revisa el listado antes de repetir la acción."
            ), 503
    except Exception as exc:
        app.logger.warning("No se pudo eliminar el conjunto de novedades (%s).", type(exc).__name__)
        return renderizar_confirmacion_eliminar_novedades(
            error="No se pudo confirmar la eliminación. Revisa el listado antes de volver a intentarlo."
        ), 503
    flash(f"Se eliminaron {cantidad_antes} novedades.", "success")
    return redirect(url_for("novedades_admin"))


def renderizar_archivo_novedades(fecha_limite="", mensaje_error=None, mensaje=None, pagina=1):
    cantidad = None
    archivadas = []
    hay_archivadas_siguiente = False
    errores = [mensaje_error] if mensaje_error else []
    if fecha_limite:
        try:
            resultado = supabase.rpc("previsualizar_archivo_novedades", {
                "p_fecha_limite": fecha_limite,
            }).execute().data
            if isinstance(resultado, list) and len(resultado) == 1:
                resultado = resultado[0]
            cantidad = int(resultado)
        except Exception as exc:
            app.logger.warning("No se pudo previsualizar archivo de novedades (%s).", type(exc).__name__)
            errores.append("No se pudo obtener la vista previa del archivo. Comprueba la conexión con la base de datos.")
    try:
        archivadas = supabase.table("novedades").select(
            "id,trabajador_id,tipo,fecha_inicio,fecha_fin,proyecto,cot,motivo,observaciones,archivado_en"
        ).eq("estado", "archivada").order("archivado_en", desc=True).range(
            (pagina - 1) * 50, pagina * 50
        ).execute().data or []
        hay_archivadas_siguiente = len(archivadas) > 50
        archivadas = archivadas[:50]
        ids = sorted({item["trabajador_id"] for item in archivadas if item.get("trabajador_id") is not None})
        nombres = {}
        if ids:
            personas = supabase.table("trabajadores").select("id,nombre").in_("id", ids).execute().data or []
            nombres = {persona["id"]: persona.get("nombre", "Trabajador") for persona in personas}
        for item in archivadas:
            item["trabajador_nombre"] = nombres.get(item.get("trabajador_id"), "Trabajador")
            item["tipo_etiqueta"], item["color"] = etiqueta_novedad(item.get("tipo"))
    except Exception as exc:
        app.logger.warning("No se pudo consultar novedades archivadas (%s).", type(exc).__name__)
        errores.append("No se pudo consultar el archivo de novedades.")
    return render_template(
        "administrador/novedades_archivo.html", correo=session.get("correo", ""),
        fecha_limite=fecha_limite, cantidad=cantidad, archivadas=archivadas,
        errores=errores, mensaje=mensaje, pagina=pagina,
        hay_archivadas_siguiente=hay_archivadas_siguiente,
    )


@app.route("/novedades/archivo", methods=["GET", "POST"])
def archivo_novedades_admin():
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    try:
        pagina = max(1, min(int(request.values.get("pagina", "1") or "1"), 100000))
    except ValueError:
        pagina = 1
    if request.method == "POST":
        accion = (request.form.get("accion") or "").strip()
        if accion == "archivar":
            fecha_limite_texto = (request.form.get("fecha_limite") or "").strip()
            try:
                fecha_limite = date.fromisoformat(fecha_limite_texto)
            except ValueError:
                return renderizar_archivo_novedades(mensaje_error="Selecciona una fecha límite válida.", pagina=pagina)
            if request.form.get("confirmar") != "si":
                return renderizar_archivo_novedades(
                    fecha_limite.isoformat(), "Confirma expresamente la operación para archivar las novedades.", pagina=pagina
                )
            try:
                cantidad_previsualizada = int(request.form.get("cantidad_previsualizada", ""))
                if cantidad_previsualizada <= 0:
                    raise ValueError
            except ValueError:
                return renderizar_archivo_novedades(
                    fecha_limite.isoformat(), "La vista previa no es válida. Vuelve a calcularla antes de confirmar.", pagina=pagina
                )
            try:
                resultado = supabase.rpc("archivar_novedades_anteriores", {
                    "p_fecha_limite": fecha_limite.isoformat(),
                    "p_cantidad_esperada": cantidad_previsualizada,
                }).execute().data
                if isinstance(resultado, list) and len(resultado) == 1:
                    resultado = resultado[0]
                cantidad = int(resultado)
            except Exception as exc:
                codigo, _ = diagnostico_error_supabase(exc)
                app.logger.warning("Falló archivo de novedades; tipo=%s código=%s.", type(exc).__name__, codigo)
                mensaje_error = "La cantidad cambió desde la vista previa; vuelve a calcularla." if "ARCHIVO_CANTIDAD_CAMBIO" in str(exc) else "No se confirmó el archivo. No se borró información; revisa el estado antes de reintentar."
                return renderizar_archivo_novedades(
                    fecha_limite.isoformat(), mensaje_error, pagina=pagina
                )
            return renderizar_archivo_novedades(
                fecha_limite.isoformat(), mensaje=f"Se archivaron {cantidad} novedades. Pueden consultarse y restaurarse en esta página.", pagina=pagina
            )
        if accion == "restaurar":
            try:
                novedad_id = int(request.form.get("novedad_id", ""))
                if novedad_id <= 0:
                    raise ValueError
                resultado = supabase.rpc("restaurar_novedad_archivada", {
                    "p_novedad_id": novedad_id,
                }).execute().data
                if isinstance(resultado, list) and resultado:
                    resultado = resultado[0]
                if not isinstance(resultado, dict) or resultado.get("id") != novedad_id or resultado.get("estado") != "registrada":
                    raise RuntimeError("RESTORE_NOT_CONFIRMED")
            except ValueError:
                return renderizar_archivo_novedades(mensaje_error="La novedad indicada no es válida.", pagina=pagina)
            except Exception as exc:
                codigo, _ = diagnostico_error_supabase(exc)
                app.logger.warning("No se pudo confirmar restauración de novedad; tipo=%s código=%s.", type(exc).__name__, codigo)
                return renderizar_archivo_novedades(mensaje_error="No se confirmó la restauración; verifica el estado del registro.", pagina=pagina)
            return renderizar_archivo_novedades(mensaje="Novedad restaurada.", pagina=pagina)
        return renderizar_archivo_novedades(mensaje_error="La acción solicitada no es válida.", pagina=pagina)

    fecha_limite = (request.args.get("fecha_limite") or "").strip()
    if fecha_limite:
        try:
            fecha_limite = date.fromisoformat(fecha_limite).isoformat()
        except ValueError:
            return renderizar_archivo_novedades(mensaje_error="Selecciona una fecha límite válida.", pagina=pagina)
    return renderizar_archivo_novedades(fecha_limite=fecha_limite, pagina=pagina)


# =========================================================
# 7. ÁREA DEL COORDINADOR
# =========================================================

@app.route("/coordinador/registro")
def registro_coordinador():

    acceso = requiere_perfil("coordinador")

    if acceso:
        return acceso

    return render_template(
        "coordinador/registro.html",
        correo=session.get("correo", ""),
    )


@app.route("/service-worker.js")
def service_worker():
    response = app.send_static_file("service-worker.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


# =========================================================
# 8. REGISTRO DE ASISTENCIA Y VISITAS (ACT06)
# =========================================================

@app.route("/api/asistencia/qr", methods=["POST"])
def consultar_qr_asistencia():
    coordinador, error = verificar_coordinador_api()
    if error:
        return error

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(
            error="El cuerpo de la solicitud debe ser un objeto JSON válido."
        ), 400

    persona, error = persona_por_qr(
        datos.get("qr"), permitir_inactivo=True
    )
    if error:
        return error

    perfil_persona = (persona.get("perfil") or "").strip().lower()
    if perfil_persona == "coordinador" and persona.get("id") != coordinador.get("id"):
        return jsonify(error="Un coordinador solo puede registrar su propia asistencia con su QR."), 403

    try:
        abiertos = (
            supabase.table("registros_asistencia")
            .select("id, cot, proyecto, fecha_entrada")
            .eq("trabajador_id", persona["id"])
            .is_("fecha_salida", "null")
            .limit(1)
            .execute()
        ).data
    except Exception as exc:
        app.logger.warning("No se pudo consultar el turno abierto (%s).", type(exc).__name__)
        return jsonify(error="No se pudo consultar asistencia. Revisa la conexión e inténtalo de nuevo."), 503

    abierto = abiertos[0] if abiertos else None
    if (persona.get("estado") or "").strip().lower() != "activo" and not abierto:
        return jsonify(error="El trabajador está inactivo y no tiene una entrada abierta."), 409
    return jsonify(
        trabajador={"id": persona["id"], "nombre": persona["nombre"], "cargo": persona["cargo"], "perfil": perfil_persona},
        accion="salida" if abierto else "entrada",
        registro_abierto=abierto,
    )


@app.route("/api/asistencia/csrf", methods=["GET"])
def obtener_csrf_asistencia():
    _, error = verificar_coordinador_api()
    if error:
        return error
    response = jsonify(csrf_token=csrf_token())
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/asistencia/buscar-identificacion", methods=["POST"])
def buscar_trabajador_por_identificacion():
    _, error = verificar_coordinador_api()
    if error:
        return error
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="El cuerpo de la solicitud debe ser un objeto JSON válido."), 400
    identificacion = datos.get("identificacion")
    if not isinstance(identificacion, str):
        return jsonify(error="Ingresa el número de identificación."), 400
    identificacion = identificacion.strip()
    if not identificacion or len(identificacion) > 80:
        return jsonify(error="El número de identificación no es válido."), 400
    try:
        resultado = (
            supabase.table("trabajadores")
            .select("id, nombre, cargo, perfil, estado")
            .eq("identificacion", identificacion)
            .limit(2)
            .execute()
        )
    except Exception as exc:
        app.logger.warning("Falló la búsqueda por identificación (%s).", type(exc).__name__)
        return jsonify(error="No fue posible buscar el trabajador ahora."), 503
    if not resultado.data:
        return jsonify(error="No se encontró un trabajador con esa identificación."), 404
    if len(resultado.data) != 1:
        return jsonify(error="La identificación no es única. Solicita revisión al administrador."), 409
    persona = resultado.data[0]
    if (persona.get("perfil") or "").strip().lower() != "trabajador":
        return jsonify(error="La identificación no corresponde a un trabajador operativo."), 409
    if (persona.get("estado") or "").strip().lower() != "activo":
        return jsonify(error="El trabajador está inactivo y no puede iniciar una entrada."), 409
    try:
        abiertos = (
            supabase.table("registros_asistencia")
            .select("id, cot, proyecto, fecha_entrada")
            .eq("trabajador_id", persona["id"])
            .is_("fecha_salida", "null")
            .limit(1)
            .execute()
        ).data
    except Exception as exc:
        app.logger.warning("Falló la consulta del turno durante búsqueda (%s).", type(exc).__name__)
        return jsonify(error="No fue posible consultar el turno del trabajador."), 503
    # No retorna la cédula ni datos de Auth; la búsqueda no da acceso al sistema.
    return jsonify(
        trabajador={"id": persona["id"], "nombre": persona["nombre"], "cargo": persona.get("cargo")},
        accion="salida" if abiertos else "entrada",
        registro_abierto=abiertos[0] if abiertos else None,
    )


@app.route("/api/asistencia/directorio-offline", methods=["GET"])
def descargar_directorio_offline():
    coordinador, error = verificar_coordinador_api()
    if error:
        return error
    try:
        personas = lista_paginada(
            supabase.table("trabajadores")
            .select("id, identificacion, nombre, cargo, perfil, estado, qr")
            .eq("perfil", "trabajador")
            .eq("estado", "activo")
            .order("id")
        )
        abiertos = lista_paginada(
            supabase.table("registros_asistencia")
            .select("trabajador_id, cot, proyecto, fecha_entrada")
            .is_("fecha_salida", "null")
        )
        cuenta_coordinador = (
            supabase.table("trabajadores")
            .select("id, nombre, qr, perfil, estado")
            .eq("id", coordinador["id"])
            .limit(1)
            .execute()
            .data
        )
    except Exception as exc:
        app.logger.warning("Falló la descarga de directorio de campo (%s).", type(exc).__name__)
        return jsonify(error="No se pudo actualizar el directorio offline."), 503
    abiertos_por_persona = {fila["trabajador_id"]: fila for fila in abiertos}
    directorio = []
    for persona in personas:
        # No se descarga correo, auth_user_id, dirección ni otra información.
        directorio.append({
            "id": persona["id"],
            "identificacion": persona.get("identificacion"),
            "nombre": persona.get("nombre"),
            "cargo": persona.get("cargo"),
            "qr": persona.get("qr"),
            "registro_abierto": abiertos_por_persona.get(persona["id"]),
        })
    coordinador_local = cuenta_coordinador[0] if cuenta_coordinador else {}
    coordinador_local["registro_abierto"] = abiertos_por_persona.get(coordinador_local.get("id"))
    response = jsonify(
        actualizado_en=datetime.now(timezone.utc).isoformat(),
        trabajadores=directorio,
        coordinador={
            "id": coordinador_local.get("id"), "nombre": coordinador_local.get("nombre"),
            "qr": coordinador_local.get("qr"), "registro_abierto": coordinador_local.get("registro_abierto"),
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/asistencia/entrada", methods=["POST"])
def registrar_entrada_asistencia():
    coordinador, error = verificar_coordinador_api()
    if error:
        return error

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="El cuerpo de la solicitud debe ser un objeto JSON válido."), 400
    persona, error = resolver_persona_asistencia(datos)
    if error:
        return error
    if persona.get("perfil") == "coordinador" and persona.get("id") != coordinador.get("id"):
        return jsonify(error="Un coordinador solo puede registrar su propia asistencia con su QR."), 403

    cot = datos.get("cot")
    proyecto = datos.get("proyecto")
    if not isinstance(cot, str) or not cot.strip() or not isinstance(proyecto, str) or not proyecto.strip():
        return jsonify(error="Ingresa el COT y el proyecto antes de registrar la entrada."), 400
    cot, proyecto = cot.strip(), proyecto.strip()
    evento, error = validar_evento_offline(
        datos, "entrada", coordinador["id"], persona["id"], cot, proyecto
    )
    if error:
        return error

    try:
        argumentos = {
            "p_trabajador_id": persona["id"],
            "p_coordinador_id": coordinador["id"],
            "p_cot": cot,
            "p_proyecto": proyecto,
            "p_ocurrio_en": evento["ocurrio_en"],
            "p_latitud": evento["latitud"],
            "p_longitud": evento["longitud"],
            "p_precision_m": evento["precision_m"],
            "p_ubicacion_obtenida": evento["ubicacion_obtenida"],
            "p_operacion_id": evento["operacion_id"],
            "p_payload_hash": evento["payload_hash"],
        }
        if evento["observaciones"]:
            argumentos["p_observaciones"] = evento["observaciones"]
            funcion = "registrar_entrada_asistencia_act07"
        else:
            # Conserva compatibilidad con el RPC ACT06 si la nota está vacía.
            funcion = "registrar_entrada_asistencia_offline"
        respuesta = supabase.rpc(funcion, argumentos).execute()
    except Exception as exc:
        codigo = getattr(exc, "code", "")
        if codigo == "23505" or "23505" in str(exc):
            return jsonify(error="El trabajador ya tiene una entrada abierta. Registra primero su salida."), 409
        if "PERSONA_NO_AUTORIZADA_PARA_ENTRADA" in str(exc):
            return jsonify(error="El trabajador ya no está activo o no está autorizado para iniciar una entrada. La operación queda pendiente de revisión."), 409
        sqlstate, mensaje = diagnostico_error_supabase(exc)
        app.logger.warning(
            "Falló registrar_entrada_asistencia; tipo=%s SQLSTATE=%s mensaje=%r",
            type(exc).__name__, sqlstate, mensaje,
        )
        return jsonify(error="No se pudo guardar la entrada. Revisa la conexión e inténtalo de nuevo."), 503

    return jsonify(mensaje="Entrada guardada.", registro=respuesta.data, operacion_id=evento["operacion_id"]), 201


@app.route("/api/asistencia/salida", methods=["POST"])
def registrar_salida_asistencia():
    coordinador, error = verificar_coordinador_api()
    if error:
        return error

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="El cuerpo de la solicitud debe ser un objeto JSON válido."), 400
    persona, error = resolver_persona_asistencia(datos, permitir_inactivo=True)
    if error:
        return error
    if persona.get("perfil") == "coordinador" and persona.get("id") != coordinador.get("id"):
        return jsonify(error="Un coordinador solo puede cerrar su propia asistencia con su QR."), 403
    evento, error = validar_evento_offline(datos, "salida", coordinador["id"], persona["id"])
    if error:
        return error

    try:
        argumentos = {
            "p_trabajador_id": persona["id"], "p_coordinador_id": coordinador["id"],
            "p_ocurrio_en": evento["ocurrio_en"], "p_latitud": evento["latitud"],
            "p_longitud": evento["longitud"], "p_precision_m": evento["precision_m"],
            "p_ubicacion_obtenida": evento["ubicacion_obtenida"],
            "p_operacion_id": evento["operacion_id"], "p_payload_hash": evento["payload_hash"],
        }
        if evento["observaciones"]:
            argumentos["p_observaciones"] = evento["observaciones"]
            funcion = "registrar_salida_asistencia_act07"
        else:
            funcion = "registrar_salida_asistencia_offline"
        respuesta = supabase.rpc(funcion, argumentos).execute()
    except Exception as exc:
        if "NO_HAY_ENTRADA_ABIERTA" in str(exc):
            return jsonify(error="El trabajador no tiene una entrada abierta para cerrar."), 409
        if "SALIDA_ANTERIOR_A_ENTRADA" in str(exc):
            return jsonify(error="La hora de salida es anterior a la entrada. La operación queda pendiente de revisión."), 409
        app.logger.warning("No se pudo registrar la salida (%s).", type(exc).__name__)
        return jsonify(error="No se pudo guardar la salida. Revisa la conexión e inténtalo de nuevo."), 503

    return jsonify(mensaje="Salida guardada.", registro=respuesta.data, operacion_id=evento["operacion_id"]), 200


@app.route("/api/visitas-tecnicas/verificar-coordinador", methods=["POST"])
def verificar_qr_coordinador_visita():
    coordinador, error = verificar_coordinador_api()
    if error:
        return error
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="El cuerpo de la solicitud debe ser un objeto JSON válido."), 400
    persona, error = persona_por_qr(datos.get("qr"))
    if error:
        return error
    if persona.get("perfil") != "coordinador" or persona.get("id") != coordinador.get("id"):
        return jsonify(error="El QR no corresponde al coordinador de esta sesión."), 403
    session["visita_coordinador_verificado_id"] = coordinador["id"]
    return jsonify(coordinador={"id": coordinador["id"], "nombre": persona["nombre"], "cargo": persona.get("cargo")})


@app.route("/api/visitas-tecnicas/verificar-coordinador-identificacion", methods=["POST"])
def verificar_identificacion_coordinador_visita():
    coordinador, error = verificar_coordinador_api()
    if error:
        return error
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="El cuerpo de la solicitud debe ser un objeto JSON válido."), 400
    identificacion = datos.get("identificacion")
    if not isinstance(identificacion, str) or not identificacion.strip() or len(identificacion.strip()) > 80:
        return jsonify(error="El número de identificación no es válido."), 400
    try:
        resultado = (
            supabase.table("trabajadores")
            .select("id, nombre, identificacion")
            .eq("id", coordinador["id"])
            .limit(2)
            .execute()
        )
    except Exception as exc:
        app.logger.warning("Falló la verificación de identificación de visita (%s).", type(exc).__name__)
        return jsonify(error="No fue posible verificar la identificación ahora."), 503
    if len(resultado.data or []) != 1:
        return jsonify(error="No fue posible comprobar el perfil del coordinador."), 409
    titular = resultado.data[0]
    if str(titular.get("identificacion") or "").strip() != identificacion.strip():
        return jsonify(error="La identificación no corresponde al coordinador autenticado."), 403
    session["visita_coordinador_verificado_id"] = coordinador["id"]
    return jsonify(coordinador={"id": coordinador["id"], "nombre": titular.get("nombre")})


@app.route("/api/visitas-tecnicas/buscar-operario", methods=["POST"])
def buscar_operario_visita():
    _, error = verificar_coordinador_api()
    if error:
        return error
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="El cuerpo de la solicitud debe ser un objeto JSON válido."), 400
    if datos.get("qr"):
        persona, error = persona_por_qr(datos.get("qr"))
        if error:
            return error
        if (persona.get("perfil") or "").strip().lower() != "trabajador":
            return jsonify(error="El QR no corresponde a un operario."), 409
        return jsonify(operario={key: persona.get(key) for key in ("id", "nombre", "cargo")})
    operario, error = buscar_operario_visita_por_identificacion(datos.get("identificacion"))
    if error:
        return error
    return jsonify(operario=operario)


@app.route("/api/visitas-tecnicas", methods=["POST"])
def registrar_visita_tecnica():
    coordinador, error = verificar_coordinador_api()
    if error:
        return error

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="El cuerpo de la solicitud debe ser un objeto JSON válido."), 400
    qr = datos.get("qr")
    if qr:
        persona, error = persona_por_qr(qr)
        if error:
            return error
        if persona.get("perfil") != "coordinador" or persona.get("id") != coordinador.get("id"):
            return jsonify(error="El QR no corresponde al coordinador de esta sesión."), 403
    elif (datos.get("coordinador_id") != coordinador.get("id")
          or session.get("visita_coordinador_verificado_id") != coordinador.get("id")):
        return jsonify(error="Identifica al coordinador de esta sesión mediante QR o identificación validada."), 403

    proyecto = datos.get("proyecto")
    if not isinstance(proyecto, str) or not proyecto.strip() or len(proyecto.strip()) > 300:
        return jsonify(error="Ingresa el nombre del proyecto o lugar de la visita (máximo 300 caracteres)."), 400
    proyecto = proyecto.strip()
    participante_id = datos.get("trabajador_id")
    if participante_id is not None:
        operario, error = persona_por_id_asistencia(participante_id)
        if error:
            return error
        participante_id = operario["id"]
    evento, error = validar_evento_offline(
        datos, "visita", coordinador["id"], participante_id, proyecto=proyecto
    )
    if error:
        return error

    try:
        respuesta = supabase.rpc(
            "registrar_visita_tecnica_offline",
            {
                "p_coordinador_id": coordinador["id"],
                "p_latitud": evento["latitud"],
                "p_longitud": evento["longitud"],
                "p_precision_m": evento["precision_m"],
                "p_ubicacion_obtenida": evento["ubicacion_obtenida"],
                "p_ocurrio_en": evento["ocurrio_en"],
                "p_operacion_id": evento["operacion_id"],
                "p_payload_hash": evento["payload_hash"],
                "p_proyecto": proyecto,
                "p_trabajador_id": participante_id,
            },
        ).execute()
    except Exception as exc:
        if "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA" in str(exc):
            return jsonify(error="La clave de idempotencia ya se usó con datos diferentes. Genera una clave nueva para esta visita."), 409
        sqlstate, mensaje = diagnostico_error_supabase(exc)
        app.logger.warning(
            "Falló registrar_visita_tecnica_offline; tipo=%s código=%s mensaje=%r",
            type(exc).__name__, sqlstate, mensaje,
        )
        return jsonify(error="No se pudo guardar la visita. Revisa la conexión e inténtalo de nuevo."), 503

    return jsonify(mensaje="Visita técnica guardada.", registro=respuesta.data, operacion_id=evento["operacion_id"]), 201


# =========================================================
# 8. GESTIÓN DE PERSONAS
# =========================================================

@app.route("/personas")
def personas():

    acceso = requiere_perfil("administrador")

    if acceso:
        return acceso

    try:
        pagina = max(1, min(int(request.args.get("pagina", "1")), 100000))
        consulta = (
            supabase.table("trabajadores")
            .select("id, nombre, identificacion, cargo, perfil, estado, auth_user_id, qr", count="exact")
            .neq("nombre", "Persona eliminada")
            .order("id")
        )
        termino = re.sub(r"[^0-9A-Za-zÀ-ÿ\s._-]", "", (request.args.get("q") or "").strip())
        if termino:
            patron = f"%{termino}%"
            consulta = consulta.or_(
                f"nombre.ilike.{patron},identificacion.ilike.{patron},cargo.ilike.{patron},perfil.ilike.{patron}"
            )
        respuesta = consulta.range((pagina - 1) * 50, pagina * 50 - 1).execute()

    except Exception:
        app.logger.exception(
            "Error consultando la lista de trabajadores."
        )
        flash("No fue posible cargar la lista de trabajadores.")
        return redirect(url_for("dashboard_admin"))

    total_personas = getattr(respuesta, "count", None)
    total_paginas = max(1, (total_personas + 49) // 50) if total_personas is not None else None

    return render_template(
        "personas.html",
        personas=respuesta.data or [], pagina=pagina, total_paginas=total_paginas,
        termino=request.args.get("q", ""),
    )


@app.route("/personas/<int:persona_id>/qr", methods=["GET"])
def ver_qr_persona(persona_id):
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    try:
        persona = obtener_persona(persona_id)
    except Exception as exc:
        app.logger.warning("No se pudo consultar el QR de una persona (%s).", type(exc).__name__)
        flash("No fue posible consultar el registro del QR.")
        return redirect(url_for("personas"))

    if not persona or persona.get("perfil") not in ("trabajador", "coordinador"):
        flash("Solo trabajadores y coordinadores tienen un QR de asistencia.")
        return redirect(url_for("personas"))
    if not persona.get("qr"):
        flash("Este trabajador todavía no tiene un QR asignado.")
        return redirect(url_for("personas"))

    return render_template(
        "persona_qr.html",
        persona=persona,
        qr_imagen=imagen_qr_base64(persona["qr"]),
    )


@app.route("/personas/<int:persona_id>/qr/generar", methods=["POST"])
def generar_qr_persona(persona_id):
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    try:
        persona = obtener_persona(persona_id)
        if not persona:
            flash("El registro solicitado no existe.")
        elif persona.get("perfil") not in ("trabajador", "coordinador"):
            flash("Solo trabajadores y coordinadores tienen un QR de asistencia.")
        elif persona.get("qr"):
            flash("El trabajador ya tiene un QR asignado.")
        else:
            codigo = generar_codigo_qr_unico()
            actualizacion = (
                supabase.table("trabajadores")
                .update({"qr": codigo})
                .eq("id", persona_id)
            )
            if persona.get("qr") is None:
                actualizacion = actualizacion.is_("qr", "null")
            else:
                actualizacion = actualizacion.eq("qr", persona["qr"])
            resultado = actualizacion.select("id, qr").execute()
            if resultado.data:
                flash("QR asignado. Ya puedes abrirlo e imprimirlo.")
            else:
                flash("Otro administrador asignó el QR primero. Recarga el listado para abrirlo.")
    except Exception as exc:
        app.logger.warning("No se pudo asignar un QR (%s).", type(exc).__name__)
        flash("No fue posible asignar el QR. Revisa la conexión e inténtalo de nuevo.")
    return redirect(url_for("personas"))


@app.route("/usuarios")
def usuarios():
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    try:
        pagina = max(1, min(int(request.args.get("pagina", "1")), 100000))
        respuesta_personas = (
            supabase.table("trabajadores")
            .select("id, nombre, cargo, identificacion, perfil, estado, auth_user_id", count="exact")
            .in_("perfil", ["coordinador", "administrador"])
            .not_.is_("auth_user_id", "null")
            .neq("nombre", "Persona eliminada")
            .order("id")
            .range((pagina - 1) * 50, pagina * 50 - 1)
            .execute()
        )
        vinculados = respuesta_personas.data or []
        uids_solicitados = {persona["auth_user_id"] for persona in vinculados if persona.get("auth_user_id")}
        correos_por_uid = {}
        if uids_solicitados:
            for pagina_auth in range(1, 101):
                respuesta = requests.get(
                    f"{SUPABASE_URL}/auth/v1/admin/users",
                    headers=auth_admin_headers(),
                    params={"page": pagina_auth, "per_page": 100},
                    timeout=20,
                )
                if respuesta.status_code != 200:
                    app.logger.warning("No se pudo consultar Supabase Auth Users (HTTP %s).", respuesta.status_code)
                    raise RuntimeError("No se pudo consultar la lista de cuentas.")
                cuentas = respuesta.json().get("users", [])
                for cuenta in cuentas:
                    if cuenta.get("id") in uids_solicitados:
                        correos_por_uid[cuenta["id"]] = cuenta.get("email", "")
                if len(cuentas) < 100 or uids_solicitados.issubset(correos_por_uid):
                    break
    except Exception:
        app.logger.exception("Error cargando las cuentas de acceso.")
        flash("No fue posible cargar las cuentas. Revisa la conexión con Supabase Auth.")
        return redirect(url_for("dashboard_admin"))

    for persona in vinculados:
        persona["correo"] = correos_por_uid.get(persona["auth_user_id"], "Cuenta Auth no encontrada")
    total_usuarios = getattr(respuesta_personas, "count", None)
    total_paginas = max(1, (total_usuarios + 49) // 50) if total_usuarios is not None else None
    return render_template("usuarios.html", usuarios=vinculados, pagina=pagina, total_paginas=total_paginas)


@app.route("/personas/nueva", methods=["GET", "POST"])
def nueva_persona():
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    if request.method == "POST":
        try:
            datos, error = validar_datos_persona()
            if error:
                flash(error)
                return render_template("persona_form.html", persona=None)
        except Exception:
            app.logger.exception("Error validando el registro de una persona.")
            flash("No fue posible validar los datos. Inténtalo de nuevo.")
            return render_template("persona_form.html", persona=None)

        if datos["perfil"] in ("trabajador", "coordinador"):
            try:
                datos["qr"] = generar_codigo_qr_unico()
            except Exception as exc:
                app.logger.warning("No se pudo generar el QR del trabajador (%s).", type(exc).__name__)
                flash("No fue posible generar un QR único. No se guardó el registro; inténtalo de nuevo.")
                return render_template("persona_form.html", persona=None)

        user_id = None
        cargo_con_acceso = datos["cargo"] in ("Coordinador", "Administrador")
        if cargo_con_acceso:
            correo = texto_formulario("correo").lower()
            contrasena = request.form.get("contrasena", "")
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", correo):
                flash("Ingresa un correo electrónico válido para la cuenta de acceso.")
                return render_template("persona_form.html", persona=None)
            if not contrasena:
                flash("Ingresa una contraseña inicial para la cuenta. Supabase validará su política.")
                return render_template("persona_form.html", persona=None)

            user_id, error_auth = crear_cuenta_auth(correo, contrasena)
            # Eliminar pronto la referencia para no retener la contraseña en variables locales.
            contrasena = None
            if error_auth:
                flash(error_auth)
                return render_template("persona_form.html", persona=None)
            datos["auth_user_id"] = user_id

        try:
            supabase.table("trabajadores").insert(datos).execute()
        except Exception:
            app.logger.exception("Error guardando el registro de una persona.")
            if user_id:
                try:
                    vinculo = (
                        supabase.table("trabajadores")
                        .select("id")
                        .eq("auth_user_id", user_id)
                        .limit(1)
                        .execute()
                    )
                except Exception:
                    app.logger.exception("No se pudo verificar el resultado de un alta vinculada.")
                    flash("No se pudo confirmar el guardado. Revisa Auth y trabajadores en Supabase antes de reintentar; la cuenta no se eliminó automáticamente.")
                    return redirect(url_for("personas"))

                if vinculo.data:
                    # El servidor pudo guardar y perder la respuesta; conservar ambos lados.
                    flash("La persona quedó guardada y vinculada correctamente.")
                    return redirect(url_for("personas"))
                if not eliminar_cuenta_auth(user_id):
                    flash("Falló el guardado y no se pudo eliminar la cuenta Auth creada. Elimina esa cuenta desde Supabase Auth > Users antes de reintentar.")
                    return redirect(url_for("personas"))
            flash("No fue posible guardar el registro. Revisa los datos e inténtalo de nuevo.")
            return render_template("persona_form.html", persona=None)

        flash("Persona registrada correctamente." if not user_id else "Persona y cuenta de acceso registradas correctamente.")
        return redirect(url_for("personas"))

    return render_template("persona_form.html", persona=None)


@app.route("/personas/<int:persona_id>/editar", methods=["GET", "POST"])
def editar_persona(persona_id):
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    try:
        persona = obtener_persona(persona_id)
    except Exception:
        app.logger.exception("Error consultando un trabajador para edición.")
        flash("No fue posible consultar el registro.")
        return redirect(url_for("personas"))
    if not persona:
        flash("El registro solicitado no existe.")
        return redirect(url_for("personas"))

    if request.method == "POST":
        try:
            datos, error = validar_datos_persona(persona_id)
            if error:
                flash(error)
                return render_template("persona_form.html", persona=persona)
            cargo_actual = persona.get("cargo")
            cargo_nuevo = datos["cargo"]
            if persona.get("auth_user_id") and cargo_nuevo != cargo_actual:
                flash("No se puede cambiar el cargo de una cuenta vinculada desde esta pantalla.")
                return render_template("persona_form.html", persona=persona)
            if cargo_nuevo in ("Coordinador", "Administrador") and not persona.get("auth_user_id"):
                flash("El cargo requiere una cuenta vinculada de Supabase Auth.")
                return render_template("persona_form.html", persona=persona)

            supabase.table("trabajadores").update(datos).eq("id", persona_id).execute()
        except Exception:
            app.logger.exception("Error actualizando un trabajador.")
            flash("No fue posible actualizar el registro. Revisa los datos e inténtalo de nuevo.")
            return render_template("persona_form.html", persona=persona)

        flash("Registro actualizado correctamente.")
        return redirect(url_for("personas"))

    return render_template("persona_form.html", persona=persona)


@app.route("/personas/<int:persona_id>/estado", methods=["POST"])
def cambiar_estado_persona(persona_id):
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    estado = (request.form.get("estado") or "").strip().lower()
    if estado not in ("activo", "inactivo"):
        flash("El estado solicitado no es válido.")
        return redirect(url_for("personas"))
    if request.form.get("confirmar_estado") != "si":
        flash("Confirma la acción en el cuadro de diálogo.", "error")
        return redirect(url_for("personas"))
    try:
        persona = obtener_persona(persona_id)
        if not persona:
            flash("El trabajador solicitado no existe.", "error")
            return redirect(url_for("personas"))
        perfil_objetivo = (persona.get("perfil") or "").strip().lower()
        cargo_objetivo = (persona.get("cargo") or "").strip().lower()
        if perfil_objetivo == "trabajador" or cargo_objetivo in {"operario", "sst"}:
            estado_actual = persona.get("estado") or ""
            if estado_actual.strip().lower() == estado:
                flash(f"El trabajador ya está {'activo' if estado == 'activo' else 'inactivo'}.", "error")
                return redirect(url_for("personas"))
            cambio = (
                supabase.table("trabajadores").update({"estado": estado})
                .eq("id", persona_id).eq("estado", estado_actual)
                .select("id,estado").execute()
            )
            if not cambio.data or cambio.data[0].get("estado") != estado:
                flash("No se confirmó el cambio. Actualiza la lista y vuelve a intentarlo.", "error")
            else:
                flash(f"Trabajador {'activado' if estado == 'activo' else 'desactivado'} correctamente.", "success")
            return redirect(url_for("personas"))

        # Las cuentas de acceso conservan la regla transaccional de la base de datos.
        respuesta = supabase.rpc("cambiar_estado_persona_act07", {
            "p_persona_id": persona_id,
            "p_estado": estado,
            "p_solicitante_id": session.get("trabajador_id"),
        }).execute()
        dato = respuesta.data
        if isinstance(dato, list) and dato:
            dato = dato[0]
        if not isinstance(dato, dict) or dato.get("id") != persona_id or dato.get("estado") != estado:
            flash("El servidor no confirmó el cambio de estado. Actualiza la lista antes de reintentar.", "error")
        else:
            flash("Estado actualizado. Las rutas protegidas comprobarán el nuevo estado incluso con una sesión abierta; la cuenta Auth y el historial no se eliminan.", "success")
    except Exception as exc:
        codigo, mensaje = diagnostico_error_supabase(exc)
        if "ULTIMO_ADMIN_ACTIVO" in mensaje:
            flash("No puedes desactivar la última cuenta administradora activa.", "error")
        elif "AUTODESACTIVACION_NO_PERMITIDA" in mensaje:
            flash("No puedes desactivar la cuenta administrativa que estás usando.", "error")
        elif "PERSONA_NO_ENCONTRADA" in mensaje:
            flash("El registro solicitado no existe.", "error")
        else:
            app.logger.warning("No se pudo cambiar estado de persona; tipo=%s código=%s.", type(exc).__name__, codigo)
            flash("No se pudo actualizar el estado. Comprueba la conexión e inténtalo de nuevo.", "error")
    return redirect(url_for("personas"))


@app.route("/personas/<int:persona_id>/eliminar", methods=["POST"])
def eliminar_persona(persona_id):
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso
    if request.form.get("confirmar_eliminacion") != "si":
        flash("Confirma la eliminación en el cuadro de diálogo.", "error")
        return redirect(url_for("personas"))

    try:
        persona = obtener_persona(persona_id)
        if not persona:
            flash("El registro ya no existe.", "error")
            return redirect(url_for("personas"))
        if persona_id == session.get("trabajador_id"):
            flash("No puedes eliminar la cuenta que estás utilizando.", "error")
            return redirect(url_for("personas"))
        if persona.get("nombre") == "Persona eliminada":
            flash("Esta persona ya fue eliminada de la lista; su historial permanece anonimizado.", "error")
            return redirect(url_for("personas"))

        perfil = (persona.get("perfil") or "").lower()
        estado_actual = (persona.get("estado") or "").lower()
        if perfil == "administrador" and estado_actual == "activo":
            admins_activos = supabase.table("trabajadores").select("id", count="exact").eq(
                "perfil", "administrador"
            ).eq("estado", "activo").execute()
            if (admins_activos.count or 0) <= 1:
                flash("No puedes eliminar al último administrador activo.", "error")
                return redirect(url_for("personas"))

        # Se desactiva primero para que una sesión abierta deje de tener acceso.
        if estado_actual != "inactivo":
            desactivacion = supabase.table("trabajadores").update({"estado": "inactivo"}).eq(
                "id", persona_id
            ).eq("estado", persona.get("estado")).select("id").execute()
            if not desactivacion.data:
                flash("No se pudo desactivar la persona. Actualiza la lista e inténtalo de nuevo.", "error")
                return redirect(url_for("personas"))

        # Supabase Auth y Postgres son servicios separados. Si falla Auth,
        # la persona queda inactiva y puede reintentarse sin perder historial.
        auth_user_id = persona.get("auth_user_id")
        if auth_user_id and not eliminar_cuenta_auth(auth_user_id):
            flash("No se pudo eliminar la cuenta de acceso. La persona quedó desactivada y su historial intacto; reintenta.", "error")
            return redirect(url_for("personas"))

        # Las filas históricas conservan su FK, pero ya no contienen datos
        # personales para identificar a la persona eliminada.
        resultado = supabase.table("trabajadores").update({
            "nombre": "Persona eliminada",
            "identificacion": None,
            "cargo": "Eliminado",
            "estado": "inactivo",
            "auth_user_id": None,
            "qr": None,
        }).eq("id", persona_id).select("id").execute()
        if not resultado.data:
            app.logger.error("No se confirmó la anonimización de la persona después de eliminar su acceso.")
            flash("El acceso quedó eliminado, pero no se confirmó la anonimización. Revisa el registro e inténtalo de nuevo.", "error")
        else:
            flash("Persona eliminada de la lista. Sus asistencias, visitas y novedades se conservaron sin datos personales.", "success")
    except Exception as exc:
        app.logger.warning("No se pudo eliminar una persona (%s).", type(exc).__name__)
        flash("No se pudo completar la eliminación. La persona quedó protegida contra nuevos accesos; revisa la conexión y vuelve a intentarlo.", "error")
    return redirect(url_for("personas"))


# =========================================================
# 9. PRUEBA DE CONEXIÓN A LA BASE DE DATOS
# =========================================================

@app.route("/prueba-supabase")
def prueba_supabase():

    acceso = requiere_perfil("administrador")

    if acceso:
        return acceso

    try:
        respuesta = (
            supabase.table("trabajadores")
            .select("id, nombre, perfil, estado")
            .execute()
        )

        return respuesta.data

    except Exception:
        app.logger.exception(
            "Error al probar la conexión con Supabase."
        )
        return {"error": "No fue posible consultar Supabase."}, 500


# =========================================================
# 10. CERRAR SESIÓN
# =========================================================

@app.route("/cerrar-sesion", methods=["POST"])
def cerrar_sesion():
    session.clear()
    return redirect(url_for("login"))


# =========================================================
# 11. EJECUTAR APLICACIÓN
# =========================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
