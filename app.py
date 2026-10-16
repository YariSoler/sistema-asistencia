
import os
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
    """Comprueba que exista una sesión y tenga el perfil requerido."""

    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if session.get("perfil") not in perfiles_requeridos:
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

    app.logger.warning(
        "Diagnóstico de perfil: usuario_id=%s; filas encontradas=%s",
        usuario_id,
        len(resultado.data),
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

    if "usuario_id" not in session:
        return redirect(url_for("login"))

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
            if datos["cargo"] in ("Coordinador", "Administrador"):
                flash("Las cuentas de coordinadores y administradores se crearán desde la gestión de usuarios.")
                return render_template("persona_form.html", persona=None)

            supabase.table("trabajadores").insert(datos).execute()
        except Exception:
            app.logger.exception("Error registrando un trabajador.")
            flash("No fue posible guardar el trabajador. Revisa los datos e inténtalo de nuevo.")
            return render_template("persona_form.html", persona=None)

        flash("Trabajador registrado correctamente.")
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
