import os
import base64
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ["SUPABASE_URL"] = "http://127.0.0.1:54321"
os.environ["SUPABASE_KEY"] = "test-anon-key"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-service-role-key"
os.environ["FLASK_SECRET_KEY"] = "test-flask-secret"

import app as asistencia_app  # noqa: E402


class ProteccionCsrfTests(unittest.TestCase):
    def setUp(self):
        asistencia_app.app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
        self.client = asistencia_app.app.test_client()

    def test_api_rechaza_token_ausente_o_invalido(self):
        self.assertEqual(self.client.post("/api/asistencia/qr", json={"qr": "x"}).status_code, 400)
        with self.client.session_transaction() as user_session:
            user_session["_csrf_token"] = "token-valido"
        response = self.client.post(
            "/api/asistencia/qr",
            json={"qr": "x"},
            headers={"X-CSRF-Token": "token-distinto"},
        )
        self.assertEqual(response.status_code, 400)

    def test_api_con_token_valido_llega_a_la_validacion_de_sesion(self):
        with self.client.session_transaction() as user_session:
            user_session["_csrf_token"] = "token-valido"
        response = self.client.post(
            "/api/asistencia/qr",
            json={"qr": "x"},
            headers={"X-CSRF-Token": "token-valido"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("Inicia sesión", response.get_json()["error"])

    def test_api_rechaza_json_que_no_sea_un_objeto(self):
        with self.client.session_transaction() as user_session:
            user_session["_csrf_token"] = "token-valido"
            user_session["usuario_id"] = "uid-coordinador"
        with patch.object(asistencia_app, "consultar_perfil", return_value=[
            {"id": 7, "perfil": "coordinador", "estado": "activo"}
        ]):
            response = self.client.post(
                "/api/asistencia/qr",
                json=["no", "es", "objeto"],
                headers={"X-CSRF-Token": "token-valido"},
            )
        self.assertEqual(response.status_code, 400)

    def test_sesion_abierta_de_persona_inactiva_se_rechaza_en_ruta_protegida(self):
        with self.client.session_transaction() as user_session:
            user_session["usuario_id"] = "uid-coordinador"
        with patch.object(asistencia_app, "consultar_perfil", return_value=[
            {"id": 7, "perfil": "coordinador", "estado": "inactivo"}
        ]):
            response = self.client.get("/coordinador/registro")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_formulario_login_exige_token(self):
        self.assertEqual(self.client.post("/login", data={}).status_code, 400)
        with self.client.session_transaction() as user_session:
            user_session["_csrf_token"] = "token-valido"
        response = self.client.post("/login", data={"csrf_token": "token-valido"})
        self.assertEqual(response.status_code, 302)

    def test_plantilla_coordinador_entrega_token_a_formulario_y_javascript(self):
        with self.client.session_transaction() as user_session:
            user_session["usuario_id"] = "uid-coordinador"
        with patch.object(asistencia_app, "consultar_perfil", return_value=[
            {"id": 7, "perfil": "coordinador", "estado": "activo"}
        ]):
            response = self.client.get("/coordinador/registro")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="csrf-token" content="', response.data)
        self.assertIn(b'name="csrf_token" value="', response.data)
        self.assertIn(b"static/js/asistencia.js", response.data)


class ReglasAct06Tests(unittest.TestCase):
    def test_clave_privilegiada_no_aparece_en_recursos_publicos(self):
        public_roots = [PROJECT_ROOT / "templates", PROJECT_ROOT / "static"]
        for root in public_roots:
            for path in root.rglob("*"):
                if path.is_file():
                    self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", path.read_text(encoding="utf-8"))

    def test_migracion_define_turno_unico_y_rechazo_idempotente(self):
        sql = (PROJECT_ROOT / "supabase/migrations/20261022_act06_asistencia_visitas.sql").read_text(encoding="utf-8")
        self.assertIn("trabajadores_qr_uidx", sql)
        self.assertIn("WHERE fecha_salida IS NULL", sql)
        self.assertIn("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA", sql)
        self.assertIn("precision_m IS NOT DISTINCT FROM EXCLUDED.precision_m", sql)

    def test_migracion_solo_permite_asistencia_del_coordinador_para_si_mismo(self):
        sql = (PROJECT_ROOT / "supabase/migrations/20261022_act06_asistencia_visitas.sql").read_text(encoding="utf-8")
        self.assertIn("perfil = 'coordinador' AND id = p_coordinador_id", sql)
        self.assertIn("PERSONA_NO_AUTORIZADA_PARA_ENTRADA", sql)
        self.assertIn("PERSONA_NO_AUTORIZADA_PARA_SALIDA", sql)

    def test_regla_de_salida_para_persona_inactiva_esta_documentada(self):
        docs = (PROJECT_ROOT / "docs/ACT06-seguridad-y-reglas.md").read_text(encoding="utf-8")
        self.assertIn("Puede escanearse su QR únicamente para cerrar esa entrada pendiente", docs)
        self.assertIn("No se borran ni se reescriben filas históricas", docs)


class RutasAct06Tests(unittest.TestCase):
    def setUp(self):
        asistencia_app.app.config.update(TESTING=True)
        self.client = asistencia_app.app.test_client()

        with self.client.session_transaction() as user_session:
            user_session["_csrf_token"] = "token-prueba"

        self.headers = {"X-CSRF-Token": "token-prueba"}

        self.coordinador = {"id": 7}
        self.trabajador = {
            "id": 15,
            "nombre": "Trabajador de prueba",
            "cargo": "Operario",
            "perfil": "trabajador",
            "estado": "activo",
            "qr": "QR-PRUEBA",
        }

    def preparar_autorizacion(self):
        return (
            patch.object(
                asistencia_app,
                "verificar_coordinador_api",
                return_value=(self.coordinador, None),
            ),
            patch.object(
                asistencia_app,
                "persona_por_qr",
                return_value=(self.trabajador, None),
            ),
        )

    def test_entrada_valida_devuelve_201(self):
        rpc = MagicMock()
        rpc.execute.return_value = SimpleNamespace(
            data={"id": 101, "trabajador_id": 15}
        )

        auth, qr = self.preparar_autorizacion()
        with auth, qr, patch.object(
            asistencia_app.supabase, "rpc", return_value=rpc
        ) as llamada_rpc:
            response = self.client.post(
                "/api/asistencia/entrada",
                json={
                    "qr": "QR-PRUEBA",
                    "cot": "COT-123",
                    "proyecto": "Proyecto de prueba",
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 201)
        llamada_rpc.assert_called_once_with(
            "registrar_entrada_asistencia",
            {
                "p_trabajador_id": 15,
                "p_coordinador_id": 7,
                "p_cot": "COT-123",
                "p_proyecto": "Proyecto de prueba",
            },
        )

    def test_entrada_duplicada_devuelve_409(self):
        rpc = MagicMock()
        rpc.execute.side_effect = Exception(
            "23505 unique_violation"
        )

        auth, qr = self.preparar_autorizacion()
        with auth, qr, patch.object(
            asistencia_app.supabase, "rpc", return_value=rpc
        ):
            response = self.client.post(
                "/api/asistencia/entrada",
                json={
                    "qr": "QR-PRUEBA",
                    "cot": "COT-123",
                    "proyecto": "Proyecto de prueba",
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 409)


class CicloQrTests(unittest.TestCase):
    def setUp(self):
        asistencia_app.app.config.update(TESTING=True)
        self.client = asistencia_app.app.test_client()
        with self.client.session_transaction() as user_session:
            user_session["_csrf_token"] = "token-qr-prueba"
        self.headers = {"X-CSRF-Token": "token-qr-prueba"}
        self.coordinador = {"id": 7}
        self.trabajador = {
            "id": 15,
            "nombre": "Operaria de prueba",
            "cargo": "Operario",
            "perfil": "trabajador",
            "estado": "activo",
            "qr": "QR-PRUEBA",
        }
        self.persona = {
            "id": 15,
            "nombre": "Operaria de prueba",
            "identificacion": "ID-PRUEBA",
            "cargo": "Operario",
            "perfil": "trabajador",
            "estado": "activo",
            "qr": "QR-PRUEBA-UNICO",
            "auth_user_id": None,
        }

    def preparar_autorizacion(self):
        return (
            patch.object(
                asistencia_app,
                "verificar_coordinador_api",
                return_value=(self.coordinador, None),
            ),
            patch.object(
                asistencia_app,
                "persona_por_qr",
                return_value=(self.trabajador, None),
            ),
        )

    def test_registro_operativo_genera_y_guarda_qr_sin_crear_cuenta_auth(self):
        datos = {
            "identificacion": "ID-PRUEBA",
            "nombre": "Operaria de prueba",
            "cargo": "Operario",
            "perfil": "trabajador",
            "estado": "activo",
        }
        tabla = MagicMock()
        with (
            patch.object(asistencia_app, "requiere_perfil", return_value=None),
            patch.object(asistencia_app, "validar_datos_persona", return_value=(datos.copy(), None)),
            patch.object(asistencia_app, "generar_codigo_qr_unico", return_value="QR-GENERADO"),
            patch.object(asistencia_app, "crear_cuenta_auth") as crear_auth,
            patch.object(asistencia_app.supabase, "table", return_value=tabla),
        ):
            response = self.client.post(
                "/personas/nueva",
                data={"csrf_token": "token-qr-prueba"},
            )

        self.assertEqual(response.status_code, 302)
        tabla.insert.assert_called_once_with({**datos, "qr": "QR-GENERADO"})
        crear_auth.assert_not_called()

    def test_registro_coordinador_genera_almacena_qr_y_lo_vincula_a_auth(self):
        datos = {
            "identificacion": "COORD-PRUEBA", "nombre": "Coord. Prueba",
            "cargo": "Coordinador", "perfil": "coordinador", "estado": "activo",
        }
        tabla = MagicMock()
        with (
            patch.object(asistencia_app, "requiere_perfil", return_value=None),
            patch.object(asistencia_app, "validar_datos_persona", return_value=(datos.copy(), None)),
            patch.object(asistencia_app, "generar_codigo_qr_unico", return_value="QR-COORD"),
            patch.object(asistencia_app, "crear_cuenta_auth", return_value=("auth-uid", None)),
            patch.object(asistencia_app.supabase, "table", return_value=tabla),
        ):
            response = self.client.post(
                "/personas/nueva",
                data={"csrf_token": "token-qr-prueba", "correo": "coord@example.test", "contrasena": "clave-prueba"},
            )
        self.assertEqual(response.status_code, 302)
        tabla.insert.assert_called_once_with({**datos, "qr": "QR-COORD", "auth_user_id": "auth-uid"})

    def test_admin_puede_ver_qr_de_coordinador(self):
        coordinador = {**self.persona, "id": 7, "perfil": "coordinador", "qr": "QR-COORD"}
        with (
            patch.object(asistencia_app, "requiere_perfil", return_value=None),
            patch.object(asistencia_app, "obtener_persona", return_value=coordinador),
            patch.object(asistencia_app, "imagen_qr_base64", return_value="cG5n"),
        ):
            response = self.client.get("/personas/7/qr")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"data:image/png;base64,cG5n", response.data)

    def test_generador_reintenta_colision_y_retorna_codigo_disponible(self):
        tabla = MagicMock()
        consulta = tabla.select.return_value.eq.return_value.limit.return_value
        consulta.execute.side_effect = [
            SimpleNamespace(data=[{"id": 3}]),
            SimpleNamespace(data=[]),
        ]
        with (
            patch.object(asistencia_app, "generar_codigo_qr", side_effect=["QR-OCUPADO", "QR-LIBRE"]),
            patch.object(asistencia_app.supabase, "table", return_value=tabla),
        ):
            resultado = asistencia_app.generar_codigo_qr_unico()
        self.assertEqual(resultado, "QR-LIBRE")
        self.assertEqual(consulta.execute.call_count, 2)

    def test_qr_existente_se_muestra_como_imagen_y_ofrece_impresion(self):
        with (
            patch.object(asistencia_app, "requiere_perfil", return_value=None),
            patch.object(asistencia_app, "obtener_persona", return_value=self.persona),
            patch.object(asistencia_app, "imagen_qr_base64", return_value="cG5nLWJhc2U2NA==") as imagen,
        ):
            response = self.client.get("/personas/15/qr")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"data:image/png;base64,cG5nLWJhc2U2NA==", response.data)
        self.assertIn(b"Imprimir QR", response.data)
        self.assertIn(b"window.print()", response.data)
        imagen.assert_called_once_with("QR-PRUEBA-UNICO")

    def test_listado_admin_muestra_enlace_al_qr_sin_exponer_el_codigo(self):
        tabla = MagicMock()
        tabla.select.return_value.order.return_value.execute.return_value = SimpleNamespace(
            data=[self.persona]
        )
        with (
            patch.object(asistencia_app, "requiere_perfil", return_value=None),
            patch.object(asistencia_app.supabase, "table", return_value=tabla),
        ):
            response = self.client.get("/personas")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Ver / imprimir QR", response.data)
        self.assertIn(b"/personas/15/qr", response.data)
        self.assertNotIn(b"QR-PRUEBA-UNICO", response.data)

    def test_listado_admin_ofrece_generar_qr_si_falta(self):
        persona_sin_qr = {**self.persona, "qr": None}
        tabla = MagicMock()
        tabla.update.return_value.eq.return_value.is_.return_value.select.return_value.execute.return_value = SimpleNamespace(
            data=[{"id": 15, "qr": "QR-RECUPERADO"}]
        )
        tabla.select.return_value.order.return_value.execute.return_value = SimpleNamespace(
            data=[persona_sin_qr]
        )
        with (
            patch.object(asistencia_app, "requiere_perfil", return_value=None),
            patch.object(asistencia_app.supabase, "table", return_value=tabla),
        ):
            response = self.client.get("/personas")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Generar QR", response.data)
        self.assertIn(b"/personas/15/qr/generar", response.data)
        self.assertIn(b'name="csrf_token"', response.data)

    def test_administrador_puede_generar_qr_para_trabajador_antiguo(self):
        persona_sin_qr = {**self.persona, "qr": None}
        tabla = MagicMock()
        with (
            patch.object(asistencia_app, "requiere_perfil", return_value=None),
            patch.object(asistencia_app, "obtener_persona", return_value=persona_sin_qr),
            patch.object(asistencia_app, "generar_codigo_qr_unico", return_value="QR-RECUPERADO"),
            patch.object(asistencia_app.supabase, "table", return_value=tabla),
        ):
            response = self.client.post(
                "/personas/15/qr/generar",
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 302)
        tabla.update.assert_called_once_with({"qr": "QR-RECUPERADO"})
        tabla.update.return_value.eq.assert_called_once_with("id", 15)
        tabla.update.return_value.eq.return_value.is_.assert_called_once_with("qr", "null")

    def test_imagen_qr_real_es_png_decodificable(self):
        contenido = base64.b64decode(asistencia_app.imagen_qr_base64("QR-PRUEBA-UNICO"))
        self.assertTrue(contenido.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_salida_sin_turno_abierto_devuelve_409(self):
        rpc = MagicMock()
        rpc.execute.side_effect = Exception(
            "NO_HAY_ENTRADA_ABIERTA"
        )

        auth, qr = self.preparar_autorizacion()
        with auth, qr, patch.object(
            asistencia_app.supabase, "rpc", return_value=rpc
        ):
            response = self.client.post(
                "/api/asistencia/salida",
                json={"qr": "QR-PRUEBA"},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 409)

    def test_coordinador_puede_consultar_su_qr_para_asistencia(self):
        coordinador = {"id": 7, "nombre": "Coordinador", "cargo": "Coordinador", "perfil": "coordinador", "estado": "activo", "qr": "QR-COORD"}
        auth = patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None))
        qr = patch.object(asistencia_app, "persona_por_qr", return_value=(coordinador, None))
        tabla = MagicMock()
        tabla.select.return_value.eq.return_value.is_.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])
        with auth, qr, patch.object(asistencia_app.supabase, "table", return_value=tabla):
            response = self.client.post("/api/asistencia/qr", json={"qr": "QR-COORD"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["accion"], "entrada")

    def test_coordinador_puede_registrar_su_propia_entrada_con_qr(self):
        coordinador = {"id": 7, "nombre": "Coordinador", "cargo": "Coordinador", "perfil": "coordinador", "estado": "activo", "qr": "QR-COORD"}
        auth = patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None))
        qr = patch.object(asistencia_app, "persona_por_qr", return_value=(coordinador, None))
        rpc = MagicMock()
        rpc.execute.return_value = SimpleNamespace(data={"trabajador_id": 7})
        with auth, qr, patch.object(asistencia_app.supabase, "rpc", return_value=rpc) as llamada_rpc:
            response = self.client.post("/api/asistencia/entrada", json={
                "qr": "QR-COORD", "cot": "COT-COORD", "proyecto": "Proyecto coordinador",
            }, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(llamada_rpc.call_args.args[1]["p_trabajador_id"], 7)
        self.assertEqual(llamada_rpc.call_args.args[1]["p_coordinador_id"], 7)

    def test_coordinador_no_puede_registrar_asistencia_con_qr_de_otro_coordinador(self):
        otro = {"id": 8, "nombre": "Otro", "cargo": "Coordinador", "perfil": "coordinador", "estado": "activo", "qr": "QR-OTRO"}
        auth = patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None))
        qr = patch.object(asistencia_app, "persona_por_qr", return_value=(otro, None))
        with auth, qr, patch.object(asistencia_app.supabase, "rpc") as llamada_rpc:
            response = self.client.post("/api/asistencia/entrada", json={
                "qr": "QR-OTRO", "cot": "COT-X", "proyecto": "Proyecto X",
            }, headers=self.headers)
        self.assertEqual(response.status_code, 403)
        llamada_rpc.assert_not_called()

    def test_visita_exige_qr_de_coordinador_de_la_sesion(self):
        auth = patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None))
        qr = patch.object(asistencia_app, "persona_por_qr", return_value=(self.trabajador, None))
        with auth, qr, patch.object(asistencia_app.supabase, "rpc") as llamada_rpc:
            response = self.client.post("/api/visitas-tecnicas", json={
                "qr": "QR-PRUEBA", "latitud": 4.7, "longitud": -74.1,
                "precision_m": 10, "idempotency_key": "12345678-1234-4234-8234-123456789abc",
            }, headers=self.headers)
        self.assertEqual(response.status_code, 403)
        llamada_rpc.assert_not_called()

    def test_verificacion_de_qr_visita_rechaza_otro_coordinador(self):
        otro = {"id": 8, "nombre": "Otro", "cargo": "Coordinador", "perfil": "coordinador", "estado": "activo", "qr": "QR-OTRO"}
        auth = patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None))
        qr = patch.object(asistencia_app, "persona_por_qr", return_value=(otro, None))
        with auth, qr:
            response = self.client.post("/api/visitas-tecnicas/verificar-coordinador", json={"qr": "QR-OTRO"}, headers=self.headers)
        self.assertEqual(response.status_code, 403)

    def test_visita_rechaza_coordenadas_fuera_de_rango(self):
        coordinador_qr = {"id": 7, "nombre": "Coordinador", "cargo": "Coordinador", "perfil": "coordinador", "estado": "activo", "qr": "QR-COORD"}
        auth = patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None))
        with auth, patch.object(
            asistencia_app, "persona_por_qr", return_value=(coordinador_qr, None)
        ), patch.object(
            asistencia_app.supabase, "rpc"
        ) as llamada_rpc:
            response = self.client.post(
                "/api/visitas-tecnicas",
                json={
                    "qr": "QR-COORD", "latitud": 100,
                    "longitud": -74,
                    "precision_m": 10,
                    "idempotency_key":
                        "12345678-1234-4234-8234-123456789abc",
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 400)
        llamada_rpc.assert_not_called()

    def test_visita_con_clave_reutilizada_devuelve_409(self):
        rpc = MagicMock()
        rpc.execute.side_effect = Exception(
            "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA"
        )

        coordinador_qr = {"id": 7, "nombre": "Coordinador", "cargo": "Coordinador", "perfil": "coordinador", "estado": "activo", "qr": "QR-COORD"}
        auth = patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None))
        with auth, patch.object(asistencia_app, "persona_por_qr", return_value=(coordinador_qr, None)), patch.object(
            asistencia_app.supabase, "rpc", return_value=rpc
        ):
            response = self.client.post(
                "/api/visitas-tecnicas",
                json={
                    "qr": "QR-COORD", "latitud": 4.7,
                    "longitud": -74.1,
                    "precision_m": 10,
                    "idempotency_key":
                        "12345678-1234-4234-8234-123456789abc",
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 409)

    def test_visita_valida_asocia_coordinador_de_sesion_y_envia_rpc(self):
        coordinador_qr = {"id": 7, "nombre": "Coordinador", "cargo": "Coordinador", "perfil": "coordinador", "estado": "activo", "qr": "QR-COORD"}
        auth = patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None))
        rpc = MagicMock()
        rpc.execute.return_value = SimpleNamespace(data={"id": 9, "registrado_en": "2026-10-22T12:00:00Z"})
        with auth, patch.object(asistencia_app, "persona_por_qr", return_value=(coordinador_qr, None)), patch.object(
            asistencia_app.supabase, "rpc", return_value=rpc
        ) as llamada_rpc:
            response = self.client.post("/api/visitas-tecnicas", json={
                "qr": "QR-COORD", "latitud": 4.7, "longitud": -74.1,
                "precision_m": 10, "idempotency_key": "12345678-1234-4234-8234-123456789abc",
            }, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(llamada_rpc.call_args.args[1]["p_coordinador_id"], 7)

if __name__ == "__main__":
    unittest.main()
