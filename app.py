from flask import Flask, render_template #"Esta línea importa desde Flask las herramientas que necesitamos para crear nuestra aplicación y para mostrar las páginas HTML.
from dotenv import load_dotenv
import os
from supabase import create_client
from flask import session, request, redirect, url_for, flash
import requests


load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


app = Flask(__name__)#Aquí creamos nuestra aplicación Flask y la guardamos en la variable app, que será la que utilizaremos para configurar y ejecutar nuestra aplicación
app.secret_key = os.getenv("FLASK_SECRET_KEY")

@app.route("/")#Esta línea define la ruta principal de nuestra aplicación. Cuando alguien entra a la dirección /, Flask sabe qué función debe ejecutar
def inicio(): #es una funcion
    return render_template('index.html') #"Aquí la función devuelve la página index.html, que Flask busca dentro de la carpeta templates para mostrarla en el navegador
 

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form.get("correo", "").strip()
        contrasena = request.form.get("contrasena", "")
        rol_solicitado = request.form.get("rol", "").strip().lower()

        if rol_solicitado not in ("administrador", "coordinador"):
            flash("Selecciona un rol válido.")
            return redirect(url_for("login"))

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

            if respuesta.status_code != 200:
                flash("No se pudo iniciar sesión. Verifica tus credenciales y tu correo.")
                return redirect(url_for("login"))

            datos = respuesta.json()
            usuario = datos["user"]
            usuario_id = usuario["id"]

            resultado = (
                supabase.table("trabajadores")
                .select("id, nombre, perfil, estado")
                .eq("auth_user_id", usuario_id)
                .execute()
            )

            if not resultado.data:
                flash("Tu cuenta no tiene un perfil autorizado.")
                return redirect(url_for("login"))

            persona = resultado.data[0]
            perfil_real = (persona.get("perfil") or "").strip().lower()
            estado = (persona.get("estado") or "").strip().lower()

            if estado != "activo":
                flash("Tu cuenta está inactiva. Contacta al administrador.")
                return redirect(url_for("login"))

            if perfil_real not in ("administrador", "coordinador"):
                flash("Tu perfil no tiene permiso para iniciar sesión.")
                return redirect(url_for("login"))

            if perfil_real != rol_solicitado:
                flash("El rol seleccionado no corresponde a tu cuenta.")
                return redirect(url_for("login"))

            session.clear()
            session["usuario_id"] = usuario_id
            session["trabajador_id"] = persona["id"]
            session["correo"] = usuario["email"]
            session["perfil"] = perfil_real

            if perfil_real == "administrador":
                return redirect(url_for("dashboard_admin"))

            return redirect(url_for("registro_coordinador"))

        except requests.RequestException:
            flash("No fue posible conectar con el servicio de autenticación.")
        except Exception:
            app.logger.exception("Error al validar el perfil del usuario.")
            flash("Ocurrió un error al validar tu cuenta.")

    return render_template("login.html")


def requiere_perfil(perfil_requerido):
    """Comprueba que exista una sesión y que tenga el perfil requerido."""
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if session.get("perfil") != perfil_requerido:
        flash("No tienes permisos para acceder a esa sección.")
        return redirect(url_for("panel"))

    return None


@app.route("/panel")
def panel():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if session.get("perfil") == "administrador":
        return redirect(url_for("dashboard_admin"))

    if session.get("perfil") == "coordinador":
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
        correo=session.get("correo", "")
    )


@app.route("/coordinador/registro")
def registro_coordinador():
    acceso = requiere_perfil("coordinador")
    if acceso:
        return acceso

    return render_template(
        "coordinador/registro.html",
        correo=session.get("correo", "")
    )

@app.route("/personas")
def personas():
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    respuesta = (
        supabase.table("trabajadores")
        .select("id, nombre, identificacion, cargo, perfil, estado, qr")
        .order("id")
        .execute()
    )

    return render_template(
        "personas.html",
        personas=respuesta.data
    )


@app.route("/cerrar-sesion", methods=["POST"])
def cerrar_sesion():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)


@app.route("/prueba-supabase")
def prueba_supabase():
    acceso = requiere_perfil("administrador")
    if acceso:
        return acceso

    respuesta = (
        supabase.table("trabajadores")
        .select("id, nombre, perfil, estado")
        .execute()
    )

    return respuesta.data


app.run()