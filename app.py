
import os
import re
import requests

from flask import (
    Flask,
    render_template,
    session,
    request,
    redirect,
    url_for,
    flash,
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


# =========================================================
# 2. FUNCIONES AUXILIARES
# =========================================================

CARGOS_PERFIL = {
    "SST": "trabajador",
    "Operario": "trabajador",
    "Coordinador": "coordinador",
    "Administrador": "administrador",
}


def texto_formulario(campo):
    return (request.form.get(campo) or "").strip()


def obtener_persona(persona_id):
    resultado = (
        supabase.table("trabajadores")
        .select("id, nombre, identificacion, cargo, perfil, estado, auth_user_id")
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
        try:
            cuerpo = respuesta.json()
            detalle = (
                cuerpo.get("msg")
                or cuerpo.get("message")
                or cuerpo.get("error_description")
                or cuerpo.get("error")
                or "Error de autenticación no especificado."
            )
        except (ValueError, AttributeError):
            detalle = "Respuesta no disponible."

        # No registrar contraseñas ni tokens.
        app.logger.warning(
            "Error de autenticación Supabase: HTTP %s - %s",
            respuesta.status_code,
            detalle,
        )

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
            flash("Estado actualizado. El acceso se comprobará con este estado en el próximo inicio de sesión; la cuenta de Supabase Auth no se elimina ni se desactiva aquí.")
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
    app.run(debug=True)
