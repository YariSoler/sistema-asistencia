
import os
import re
import math
import uuid
import secrets
import hmac
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
    """Compensa un alta parcial cuando falla el guardado del trabajador."""
    try:
        respuesta = requests.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers=auth_admin_headers(),
            timeout=20,
        )
        if respuesta.status_code in (200, 204):
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


# =========================================================
# 3. PÁGINA INICIAL
# =========================================================

@app.route("/")
def inicio():
    return render_template("index.html")


# =========================================================
# 4. INICIO DE SESIÓN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "GET":
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

@app.route("/admin/dashboard")
def dashboard_admin():

    acceso = requiere_perfil("administrador")

    if acceso:
        return acceso

    return render_template(
        "administrador/dashboard.html",
        correo=session.get("correo", ""),
    )


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
        return jsonify(error="No se pudo consultar asistencia. Confirma que la migración ACT06 esté aplicada."), 503

    abierto = abiertos[0] if abiertos else None
    if (persona.get("estado") or "").strip().lower() != "activo" and not abierto:
        return jsonify(error="El trabajador está inactivo y no tiene una entrada abierta."), 409
    return jsonify(
        trabajador={"id": persona["id"], "nombre": persona["nombre"], "cargo": persona["cargo"]},
        accion="salida" if abierto else "entrada",
        registro_abierto=abierto,
    )


@app.route("/api/asistencia/entrada", methods=["POST"])
def registrar_entrada_asistencia():
    coordinador, error = verificar_coordinador_api()
    if error:
        return error

    datos = request.get_json(silent=True) or {}
    persona, error = persona_por_qr(datos.get("qr"))
    if error:
        return error
    if persona.get("perfil") == "coordinador" and persona.get("id") != coordinador.get("id"):
        return jsonify(error="Un coordinador solo puede registrar su propia asistencia con su QR."), 403

    cot = datos.get("cot")
    proyecto = datos.get("proyecto")
    if not isinstance(cot, str) or not cot.strip() or not isinstance(proyecto, str) or not proyecto.strip():
        return jsonify(error="Ingresa el COT y el proyecto antes de registrar la entrada."), 400

    try:
        respuesta = supabase.rpc(
            "registrar_entrada_asistencia",
            {
                "p_trabajador_id": persona["id"],
                "p_coordinador_id": coordinador["id"],
                "p_cot": cot.strip(),
                "p_proyecto": proyecto.strip(),
            },
        ).execute()
    except Exception as exc:
        codigo = getattr(exc, "code", "")
        if codigo == "23505" or "23505" in str(exc):
            return jsonify(error="El trabajador ya tiene una entrada abierta. Registra primero su salida."), 409
        sqlstate, mensaje = diagnostico_error_supabase(exc)
        app.logger.warning(
            "Falló registrar_entrada_asistencia; tipo=%s SQLSTATE=%s mensaje=%r",
            type(exc).__name__, sqlstate, mensaje,
        )
        return jsonify(error="No se pudo guardar la entrada. Confirma que la migración ACT06 esté aplicada."), 503

    return jsonify(mensaje="Entrada guardada.", registro=respuesta.data), 201


@app.route("/api/asistencia/salida", methods=["POST"])
def registrar_salida_asistencia():
    coordinador, error = verificar_coordinador_api()
    if error:
        return error

    datos = request.get_json(silent=True) or {}
    persona, error = persona_por_qr(datos.get("qr"), permitir_inactivo=True)
    if error:
        return error
    if persona.get("perfil") == "coordinador" and persona.get("id") != coordinador.get("id"):
        return jsonify(error="Un coordinador solo puede cerrar su propia asistencia con su QR."), 403

    try:
        respuesta = supabase.rpc(
            "registrar_salida_asistencia",
            {"p_trabajador_id": persona["id"], "p_coordinador_id": coordinador["id"]},
        ).execute()
    except Exception as exc:
        if "NO_HAY_ENTRADA_ABIERTA" in str(exc):
            return jsonify(error="El trabajador no tiene una entrada abierta para cerrar."), 409
        app.logger.warning("No se pudo registrar la salida (%s).", type(exc).__name__)
        return jsonify(error="No se pudo guardar la salida. Confirma que la migración ACT06 esté aplicada."), 503

    return jsonify(mensaje="Salida guardada.", registro=respuesta.data), 200


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
    return jsonify(coordinador={"nombre": persona["nombre"], "cargo": persona.get("cargo")})


@app.route("/api/visitas-tecnicas", methods=["POST"])
def registrar_visita_tecnica():
    coordinador, error = verificar_coordinador_api()
    if error:
        return error

    datos = request.get_json(silent=True) or {}
    persona, error = persona_por_qr(datos.get("qr"))
    if error:
        return error
    if persona.get("perfil") != "coordinador" or persona.get("id") != coordinador.get("id"):
        return jsonify(error="El QR no corresponde al coordinador de esta sesión."), 403
    try:
        latitud = float(datos.get("latitud"))
        longitud = float(datos.get("longitud"))
        precision = float(datos.get("precision_m")) if datos.get("precision_m") is not None else None
        llave_idempotencia = str(uuid.UUID(str(datos.get("idempotency_key", ""))))
    except (TypeError, ValueError, AttributeError):
        return jsonify(error="La ubicación o el identificador de envío no son válidos."), 400

    if not math.isfinite(latitud) or not math.isfinite(longitud):
        return jsonify(error="La ubicación no contiene coordenadas válidas."), 400
    if latitud < -90 or latitud > 90 or longitud < -180 or longitud > 180:
        return jsonify(error="Las coordenadas están fuera de rango."), 400
    if precision is not None and (not math.isfinite(precision) or precision < 0):
        return jsonify(error="La precisión del GPS no es válida."), 400

    try:
        respuesta = supabase.rpc(
            "registrar_visita_tecnica",
            {
                "p_coordinador_id": coordinador["id"],
                "p_latitud": latitud,
                "p_longitud": longitud,
                "p_precision_m": precision,
                "p_idempotency_key": llave_idempotencia,
            },
        ).execute()
    except Exception as exc:
        if "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA" in str(exc):
            return jsonify(error="La clave de idempotencia ya se usó con datos diferentes. Genera una clave nueva para esta visita."), 409
        app.logger.warning("No se pudo registrar la visita técnica (%s).", type(exc).__name__)
        return jsonify(error="No se pudo guardar la visita. Confirma que la migración ACT06 esté aplicada."), 503

    return jsonify(mensaje="Visita técnica guardada.", registro=respuesta.data), 201


# =========================================================
# 8. GESTIÓN DE PERSONAS
# =========================================================

@app.route("/personas")
def personas():

    acceso = requiere_perfil("administrador")

    if acceso:
        return acceso

    try:
        respuesta = (
            supabase.table("trabajadores")
            .select(
                "id, nombre, identificacion, cargo, perfil, estado, qr"
            )
            .order("id")
            .execute()
        )

    except Exception:
        app.logger.exception(
            "Error consultando la lista de trabajadores."
        )
        flash("No fue posible cargar la lista de trabajadores.")
        return redirect(url_for("dashboard_admin"))

    return render_template(
        "personas.html",
        personas=respuesta.data,
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
        registros = (
            supabase.table("trabajadores")
            .select("id, nombre, cargo, identificacion, perfil, estado, auth_user_id")
            .execute()
            .data
        )
        vinculados = [
            persona for persona in registros
            if persona.get("perfil") in ("coordinador", "administrador")
            and persona.get("auth_user_id")
        ]
        correos_por_uid = {}
        for pagina in range(1, 101):
            respuesta = requests.get(
                f"{SUPABASE_URL}/auth/v1/admin/users",
                headers=auth_admin_headers(),
                params={"page": pagina, "per_page": 100},
                timeout=20,
            )
            if respuesta.status_code != 200:
                app.logger.warning("No se pudo consultar Supabase Auth Users (HTTP %s).", respuesta.status_code)
                raise RuntimeError("No se pudo consultar la lista de cuentas.")
            cuentas = respuesta.json().get("users", [])
            for cuenta in cuentas:
                if cuenta.get("id"):
                    correos_por_uid[cuenta["id"]] = cuenta.get("email", "")
            if len(cuentas) < 100:
                break
    except Exception:
        app.logger.exception("Error cargando las cuentas de acceso.")
        flash("No fue posible cargar las cuentas. Revisa la conexión con Supabase Auth.")
        return redirect(url_for("dashboard_admin"))

    for persona in vinculados:
        persona["correo"] = correos_por_uid.get(persona["auth_user_id"], "Cuenta Auth no encontrada")
    return render_template("usuarios.html", usuarios=vinculados)


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
    try:
        persona = obtener_persona(persona_id)
        if not persona:
            flash("El registro solicitado no existe.")
        else:
            supabase.table("trabajadores").update({"estado": estado}).eq("id", persona_id).execute()
            flash("Estado actualizado. Las rutas protegidas comprobarán el nuevo estado incluso en sesiones abiertas; esta acción no elimina la cuenta de Supabase Auth.")
    except Exception:
        app.logger.exception("Error cambiando el estado de un trabajador.")
        flash("No fue posible cambiar el estado del registro.")
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
