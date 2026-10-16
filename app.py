
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
import os
import requests

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

# Verificar la configuración necesaria
if not SUPABASE_URL or not SUPABASE_KEY or not FLASK_SECRET_KEY:
    raise RuntimeError(
        "Falta configurar SUPABASE_URL, SUPABASE_KEY "
        "o FLASK_SECRET_KEY en el archivo .env."
    )

# Conexión con Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Crear aplicación Flask
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY


@app.route("/")
def inicio():
    return render_template("index.html")


def requiere_perfil(*perfiles_requeridos):
    """Verifica la sesión y el perfil necesario."""

    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if session.get("perfil") not in perfiles_requeridos:
        flash("No tienes permisos para acceder a esa sección.")
        return redirect(url_for("panel"))

    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form.get("correo", "").strip()
        contrasena = request.form.get("contrasena", "")
        rol_solicitado = request.form.get("rol", "").strip().lower()

        if rol_solicitado not in ("administrador", "coordinador"):
            flash("Selecciona un rol válido.")
            return redirect(url_for("login"))

        if not correo or not contrasena:
            flash("Ingresa tu correo y contraseña.")
            return redirect(url_for("login"))

        # PASO 1: autenticar con Supabase Auth
        try:
            respuesta = requests.post(
                f"{SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password",
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
            # No registrar contraseñas ni tokens
            try:
                detalle = respuesta.json().get("msg") or respuesta.json().get("message")
            except (ValueError, AttributeError):
                detalle = "Respuesta no disponible"

            app.logger.warning(
                "Error de autenticación Supabase: HTTP %s - %s",
                respuesta.status_code,
                detalle,
            )
            flash(
                "No se pudo iniciar sesión. "
                "Revisa el terminal de VS Code para conocer el error."
            )
            return redirect(url_for("login"))

        # PASO 2: obtener la identidad autenticada
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

        # PASO 3: consultar el perfil en trabajadores
        try:
            resultado = (
                supabase.table("trabajadores")
                .select("id, nombre, perfil, estado")
                .eq("auth_user_id", usuario_id)
                .execute()
            )
        except Exception:
            app.logger.exception(
                "Error consultando el perfil en trabajadores."
            )
            flash(
                "La autenticación funcionó, pero no fue posible "
                "consultar tu perfil."
            )
            return redirect(url_for("login"))

        if not resultado.data:
            app.logger.warning(
                "Usuario autenticado sin perfil vinculado en trabajadores."
            )
            flash("Tu cuenta no tiene un perfil autorizado.")
            return redirect(url_for("login"))

        persona = resultado.data[0]
        perfil_real = (persona.get("perfil") or "").strip().lower()
        estado = (persona.get("estado") or "").strip().lower()

        # PASO 4: validar estado y permisos
        if estado != "activo":
            flash("Tu cuenta está inactiva. Contacta al administrador.")
            return redirect(url_for("login"))

        if perfil_real not in ("administrador", "coordinador"):
            flash("Tu perfil no tiene permiso para iniciar sesión.")
            return redirect(url_for("login"))

        if perfil_real != rol_solicitado:
            flash("El rol seleccionado no corresponde a tu cuenta.")
            return redirect(url_for("login"))

        # PASO 5: guardar los datos de sesión
        session.clear()
        session["usuario_id"] = usuario_id
        session["trabajador_id"] = persona["id"]
        session["correo"] = usuario["email"]
        session["perfil"] = perfil_real

        # PASO 6: dirigir al área correspondiente
        if perfil_real == "administrador":
            return redirect(url_for("dashboard_admin"))

        return redirect(url_for("registro_coordinador"))

    return render_template("login.html")


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


@app.route("/admin/dashboard")
def dashboard_admin():
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    return render_template(
        "administrador/dashboard.html",
        correo=session.get("correo", ""),
    )


@app.route("/coordinador/registro")
def registro_coordinador():
    acceso = requiere_perfil("coordinador")
    if acceso:
        return acceso

    return render_template(
        "coordinador/registro.html",
        correo=session.get("correo", ""),
    )


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

    return render_template("personas.html", personas=respuesta.data)


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
        app.logger.exception("Error al probar la conexión con Supabase.")
        return {"error": "No fue posible consultar Supabase."}, 500


@app.route("/cerrar-sesion", methods=["POST"])
def cerrar_sesion():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
