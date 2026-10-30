import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("FLASK_SECRET_KEY", "test-flask-secret")

try:
    import qrcode  # noqa: F401
except ImportError:
    sys.modules["qrcode"] = types.ModuleType("qrcode")

import app as asistencia_app  # noqa: E402


class InicioLoginTests(unittest.TestCase):
    def setUp(self):
        asistencia_app.app.config.update(TESTING=True)
        self.client = asistencia_app.app.test_client()

    def test_inicio_sin_sesion_entrega_login_directamente(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Acceso para coordinadores y administradores", response.data)
        self.assertIn(b'name="csrf_token"', response.data)
        self.assertNotIn(b"Sistema de Control de Asistencia</h1>", response.data)

    def test_inicio_con_sesion_admin_redirige_a_panel_y_dashboard(self):
        with self.client.session_transaction() as user_session:
            user_session["usuario_id"] = "uid-admin"
        perfil = [{"id": 1, "perfil": "administrador", "estado": "activo"}]
        with patch.object(asistencia_app, "consultar_perfil", return_value=perfil):
            first = self.client.get("/")
            second = self.client.get(first.headers["Location"])
        self.assertEqual(first.headers["Location"], "/panel")
        self.assertEqual(second.headers["Location"], "/admin/dashboard")

    def test_inicio_con_sesion_coordinador_redirige_a_registro(self):
        with self.client.session_transaction() as user_session:
            user_session["usuario_id"] = "uid-coordinador"
        perfil = [{"id": 2, "perfil": "coordinador", "estado": "activo"}]
        with patch.object(asistencia_app, "consultar_perfil", return_value=perfil):
            first = self.client.get("/")
            second = self.client.get(first.headers["Location"])
        self.assertEqual(first.headers["Location"], "/panel")
        self.assertEqual(second.headers["Location"], "/coordinador/registro")

    def test_login_no_crea_bucle_si_la_sesion_ya_no_es_valida(self):
        with self.client.session_transaction() as user_session:
            user_session["usuario_id"] = "uid-inactivo"
        perfil = [{"id": 3, "perfil": "coordinador", "estado": "inactivo"}]
        with patch.object(asistencia_app, "consultar_perfil", return_value=perfil):
            response = self.client.get("/panel")
        self.assertEqual(response.headers["Location"], "/login")
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_cerrar_sesion_devuelve_al_login_y_la_raiz(self):
        with self.client.session_transaction() as user_session:
            user_session["_csrf_token"] = "csrf-login-home"
            user_session["usuario_id"] = "uid-admin"
        response = self.client.post("/cerrar-sesion", data={"csrf_token": "csrf-login-home"})
        self.assertEqual(response.headers["Location"], "/login")
        with self.client.session_transaction() as user_session:
            self.assertNotIn("usuario_id", user_session)
        self.assertEqual(self.client.get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
