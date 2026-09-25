from flask import Flask, render_template #"Esta línea importa desde Flask las herramientas que necesitamos para crear nuestra aplicación y para mostrar las páginas HTML.
from dotenv import load_dotenv
import os
from supabase import create_client


load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


app = Flask(__name__)#Aquí creamos nuestra aplicación Flask y la guardamos en la variable app, que será la que utilizaremos para configurar y ejecutar nuestra aplicación

@app.route("/")#Esta línea define la ruta principal de nuestra aplicación. Cuando alguien entra a la dirección /, Flask sabe qué función debe ejecutar
def inicio(): #es una funcion
    return render_template('index.html') #"Aquí la función devuelve la página index.html, que Flask busca dentro de la carpeta templates para mostrarla en el navegador

 
@app.route("/prueba-supabase")
def prueba_supabase():
    respuesta = supabase.table("trabajadores").select("*").execute()
    return respuesta.data


app.run()