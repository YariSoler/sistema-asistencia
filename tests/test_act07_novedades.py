import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("FLASK_SECRET_KEY", "test-flask-secret")

try:
    import qrcode  # noqa: F401
except ImportError:
    # The ACT07 tests do not generate QR images; keep the import isolated when
    # the optional image dependency is unavailable in a minimal test runtime.
    sys.modules["qrcode"] = types.ModuleType("qrcode")

import app as asistencia_app  # noqa: E402


class ValidacionNovedadTests(unittest.TestCase):
    def datos_validos(self):
        return {
            "trabajador_id": "12", "tipo": "permiso", "fecha_inicio": "2026-10-28",
            "fecha_fin": "2026-10-29", "hora_inicio": "", "hora_fin": "",
            "cot": "COT-3", "proyecto": "Obra norte", "motivo": "Cita médica",
            "observaciones": "Avisó al coordinador",
        }

    def test_normaliza_novedad_y_conserva_rango_motivo_y_proyecto(self):
        datos, error = asistencia_app.validar_datos_novedad(self.datos_validos())
        self.assertIsNone(error)
        self.assertEqual(datos["fecha_fin"], "2026-10-29")
        self.assertEqual(datos["motivo"], "Cita médica")
        self.assertEqual(datos["proyecto"], "Obra norte")

    def test_rechaza_rango_invertido_y_tipos_retirados(self):
        entrada = self.datos_validos()
        entrada["fecha_inicio"], entrada["fecha_fin"] = "2026-10-30", "2026-10-29"
        self.assertIn("anterior", asistencia_app.validar_datos_novedad(entrada)[1])
        tarde = self.datos_validos()
        tarde.update(tipo="llegada_tarde")
        self.assertIn("tipo de novedad", asistencia_app.validar_datos_novedad(tarde)[1])
        extras = self.datos_validos()
        extras.update(tipo="horas_extras")
        self.assertIn("tipo de novedad", asistencia_app.validar_datos_novedad(extras)[1])

    def test_clave_duplicada_es_determinista_y_cambia_con_el_motivo(self):
        first, error = asistencia_app.validar_datos_novedad(self.datos_validos())
        self.assertIsNone(error)
        second, error = asistencia_app.validar_datos_novedad(self.datos_validos())
        self.assertIsNone(error)
        self.assertEqual(asistencia_app.clave_dedupe_novedad(first), asistencia_app.clave_dedupe_novedad(second))
        second["motivo"] = "Motivo diferente"
        self.assertNotEqual(asistencia_app.clave_dedupe_novedad(first), asistencia_app.clave_dedupe_novedad(second))

    def test_hash_asistencia_antigua_sin_nota_se_conserva_y_nota_se_vincula_al_evento(self):
        evento = {
            "operacion_id": "12345678-1234-4234-8234-123456789abc",
            "ocurrio_en": "2026-10-28T12:00:00Z", "ubicacion_estado": "no_disponible",
        }
        original, error = asistencia_app.validar_evento_offline(evento, "entrada", 5, 12, "COT-3", "Proyecto")
        vacio, error_vacio = asistencia_app.validar_evento_offline(
            {**evento, "observaciones": "  "}, "entrada", 5, 12, "COT-3", "Proyecto"
        )
        con_nota, error_nota = asistencia_app.validar_evento_offline(
            {**evento, "observaciones": "Cambio de turno"}, "entrada", 5, 12, "COT-3", "Proyecto"
        )
        self.assertIsNone(error)
        self.assertIsNone(error_vacio)
        self.assertIsNone(error_nota)
        self.assertEqual(original["payload_hash"], vacio["payload_hash"])
        self.assertNotEqual(original["payload_hash"], con_nota["payload_hash"])


class RutasNovedadTests(unittest.TestCase):
    def setUp(self):
        asistencia_app.app.config.update(TESTING=True)
        asistencia_app._DASHBOARD_CACHE = None
        self.client = asistencia_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["_csrf_token"] = "csrf-act07"
            sess["trabajador_id"] = 5
        self.headers = {"csrf_token": "csrf-act07"}

    def test_coordinador_no_puede_consultar_novedades(self):
        with patch.object(asistencia_app, "requiere_perfil", return_value=asistencia_app.redirect("/panel")):
            response = self.client.get("/novedades")
        self.assertEqual(response.status_code, 302)

    def test_estado_persona_usa_rpc_protegida_y_solicitante_de_sesion(self):
        rpc = MagicMock()
        rpc.execute.return_value = SimpleNamespace(data={"id": 12, "estado": "inactivo"})
        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app.supabase, "rpc", return_value=rpc
        ) as llamada, patch.object(asistencia_app, "obtener_persona", return_value={
            "id": 12, "perfil": "administrador", "estado": "activo", "auth_user_id": "auth-12",
        }):
            response = self.client.post("/personas/12/estado", data={
                **self.headers, "estado": "inactivo", "confirmar_estado": "si",
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(llamada.call_args.args[0], "cambiar_estado_persona_act07")
        self.assertEqual(llamada.call_args.args[1]["p_solicitante_id"], 5)

    def test_cambio_estado_exige_confirmacion_explicita(self):
        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app.supabase, "rpc"
        ) as llamada:
            response = self.client.post("/personas/12/estado", data={
                **self.headers, "estado": "inactivo",
            })
        self.assertEqual(response.status_code, 302)
        llamada.assert_not_called()

    def test_cambio_estado_rechaza_csrf_antes_de_la_escritura(self):
        with patch.object(asistencia_app.supabase, "rpc") as llamada:
            response = self.client.post("/personas/12/estado", data={"estado": "inactivo"})
        self.assertEqual(response.status_code, 400)
        llamada.assert_not_called()

    def test_desactivar_trabajador_no_depende_de_la_rpc_de_migracion(self):
        persona = {"id": 12, "perfil": "trabajador", "estado": "activo", "auth_user_id": None}
        query = MagicMock()
        query.update.return_value = query
        query.eq.return_value = query
        query.select.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{"id": 12, "estado": "inactivo"}])
        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app, "obtener_persona", return_value=persona
        ), patch.object(asistencia_app.supabase, "table", return_value=query), patch.object(
            asistencia_app.supabase, "rpc"
        ) as rpc:
            response = self.client.post("/personas/12/estado", data={
                **self.headers, "estado": "inactivo", "confirmar_estado": "si",
            })
        self.assertEqual(response.status_code, 302)
        query.update.assert_called_once_with({"estado": "inactivo"})
        rpc.assert_not_called()

    def test_dashboard_usa_fallback_y_hora_de_colombia_si_falta_rpc(self):
        datos = {
            "metricas": {"trabajadores_activos": 5, "presentes": 3,
                         "ausencias_injustificadas": 1, "novedades_vigentes": 2},
            "proyectos": [], "novedades_recientes": [],
        }
        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app.supabase, "rpc", side_effect=RuntimeError("function missing")
        ), patch.object(asistencia_app, "dashboard_desde_tablas_existentes", return_value=datos):
            response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b">5<", response.data)
        self.assertIn(b"Colombia", response.data)
        self.assertNotIn(b"ACT07", response.data)

    def test_reporte_consulta_asistencia_y_muestra_hora_bogota(self):
        trabajadores = [{"id": 12, "nombre": "Prueba", "identificacion": "P-12", "cargo": "Operario"}]
        registros = [{"id": 4, "trabajador_id": 12, "cot": "COT-1", "proyecto": "Obra",
                      "fecha_entrada": "2026-10-28T17:30:00+00:00", "fecha_salida": None}]
        consulta = MagicMock()
        consulta.range.return_value.execute.return_value.data = registros
        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app, "lista_paginada", return_value=trabajadores
        ), patch.object(asistencia_app, "consultar_filas_reporte", return_value=consulta):
            response = self.client.get("/reportes?desde=2026-10-28&hasta=2026-10-28")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Prueba", response.data)
        self.assertIn(b"12:30:00", response.data)

    def test_exportacion_csv_usa_hora_local_y_filtros_del_reporte(self):
        trabajadores = [{"id": 12, "nombre": "Prueba", "identificacion": "P-12", "cargo": "Operario"}]
        registro = {"id": 4, "trabajador_id": 12, "cot": "COT-1", "proyecto": "Obra",
                    "fecha_entrada": "2026-10-28T17:30:00+00:00", "fecha_salida": None}
        consulta = MagicMock()
        consulta.range.return_value.execute.return_value.data = [registro]
        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app, "lista_paginada", return_value=trabajadores
        ), patch.object(asistencia_app, "consultar_filas_reporte", return_value=consulta):
            response = self.client.get("/reportes?desde=2026-10-28&hasta=2026-10-28&formato=csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("12:30:00", response.get_data(as_text=True))

    def test_hora_de_supabase_se_convierte_a_hora_bogota(self):
        self.assertEqual(
            asistencia_app.formatear_hora_bogota("2026-10-28T17:30:00+00:00"),
            "28/10/2026 12:30:00",
        )

    def test_elimina_persona_activa_y_anominiza_sin_borrar_historial(self):
        persona = {"id": 12, "perfil": "trabajador", "estado": "activo", "auth_user_id": None}
        actualizaciones = []
        tablas_consultadas = []

        class Query:
            def __init__(self): self.cambios = None
            def update(self, cambios): self.cambios = cambios; actualizaciones.append(cambios); return self
            def select(self, *_args, **_kwargs): return self
            def eq(self, *_args, **_kwargs): return self
            def execute(self): return SimpleNamespace(data=[{"id": 12}])

        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app, "obtener_persona", return_value=persona
        ), patch.object(asistencia_app, "eliminar_cuenta_auth") as borrar_auth, patch.object(
            asistencia_app.supabase, "table", side_effect=lambda tabla: (tablas_consultadas.append(tabla), Query())[1]
        ):
            response = self.client.post("/personas/12/eliminar", data={
                **self.headers, "confirmar_eliminacion": "si",
            })
        self.assertEqual(response.status_code, 302)
        borrar_auth.assert_not_called()
        self.assertEqual(actualizaciones[0], {"estado": "inactivo"})
        self.assertEqual(actualizaciones[1]["nombre"], "Persona eliminada")
        self.assertIsNone(actualizaciones[1]["identificacion"])
        self.assertIsNone(actualizaciones[1]["qr"])
        self.assertEqual(actualizaciones[1]["estado"], "inactivo")
        self.assertEqual(tablas_consultadas, ["trabajadores", "trabajadores"])

    def test_elimina_cuenta_auth_para_persona_vinculada_y_conserva_historial(self):
        persona = {"id": 12, "perfil": "coordinador", "estado": "inactivo", "auth_user_id": "auth-12"}
        actualizaciones = []

        class Query:
            def update(self, cambios): actualizaciones.append(cambios); return self
            def select(self, *_args, **_kwargs): return self
            def eq(self, *_args, **_kwargs): return self
            def execute(self): return SimpleNamespace(data=[{"id": 12}])

        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app, "obtener_persona", return_value=persona
        ), patch.object(asistencia_app, "eliminar_cuenta_auth", return_value=True) as borrar_auth, patch.object(
            asistencia_app.supabase, "table", side_effect=lambda _tabla: Query()
        ):
            response = self.client.post("/personas/12/eliminar", data={
                **self.headers, "confirmar_eliminacion": "si",
            })
        self.assertEqual(response.status_code, 302)
        borrar_auth.assert_called_once_with("auth-12")
        self.assertEqual(actualizaciones[-1]["nombre"], "Persona eliminada")
        self.assertIsNone(actualizaciones[-1]["auth_user_id"])

    def test_plantillas_de_personas_no_muestran_checkbox_confirmar(self):
        personas = (ROOT / "templates/personas.html").read_text(encoding="utf-8")
        usuarios = (ROOT / "templates/usuarios.html").read_text(encoding="utf-8")
        self.assertNotIn('type="checkbox" name="confirmar_estado"', personas + usuarios)
        self.assertIn("Eliminar</button>", personas)
        self.assertIn("Eliminar</button>", usuarios)
        self.assertIn("Editar</a>", personas)

    def test_archivo_exige_confirmacion_y_solo_invoca_rpc_de_novedades(self):
        class Query:
            def select(self, *_args, **_kwargs): return self
            def eq(self, *_args, **_kwargs): return self
            def order(self, *_args, **_kwargs): return self
            def range(self, *_args, **_kwargs): return self
            def execute(self): return SimpleNamespace(data=[])

        llamadas = []
        def rpc(nombre, argumentos):
            llamadas.append((nombre, argumentos))
            salida = {"previsualizar_archivo_novedades": 2, "archivar_novedades_anteriores": 2}[nombre]
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=salida))

        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app.supabase, "rpc", side_effect=rpc
        ), patch.object(asistencia_app.supabase, "table", return_value=Query()):
            vista_previa = self.client.get("/novedades/archivo?fecha_limite=2025-01-01")
            sin_confirmacion = self.client.post("/novedades/archivo", data={
                **self.headers, "accion": "archivar", "fecha_limite": "2025-01-01",
            })
            confirmado = self.client.post("/novedades/archivo", data={
                **self.headers, "accion": "archivar", "fecha_limite": "2025-01-01",
                "cantidad_previsualizada": "2", "confirmar": "si",
            })
        self.assertIn(b">2<", vista_previa.data)
        self.assertIn(b"Confirma expresamente", sin_confirmacion.data)
        self.assertIn(b"Se archivaron 2 novedades", confirmado.data)
        self.assertEqual([name for name, _ in llamadas], [
            "previsualizar_archivo_novedades", "previsualizar_archivo_novedades",
            "archivar_novedades_anteriores", "previsualizar_archivo_novedades",
        ])

    def test_eliminar_todas_novedades_exige_frase_y_solo_borra_esa_tabla(self):
        estado = {"cantidad": 3, "eliminado": False}
        tablas = []

        class Query:
            def __init__(self): self.borrado = False
            def select(self, *_args, **_kwargs): return self
            def limit(self, *_args, **_kwargs): return self
            def delete(self): self.borrado = True; return self
            @property
            def not_(self): return self
            def is_(self, *_args, **_kwargs): return self
            def execute(self):
                if self.borrado:
                    estado["cantidad"] = 0
                    estado["eliminado"] = True
                    return SimpleNamespace(data=[])
                return SimpleNamespace(data=[], count=estado["cantidad"])

        def table(nombre):
            tablas.append(nombre)
            return Query()

        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app.supabase, "table", side_effect=table
        ):
            vista = self.client.get("/novedades/eliminar-todas")
            rechazo = self.client.post("/novedades/eliminar-todas", data={
                **self.headers, "confirmacion_texto": "borrar",
            })
            confirmada = self.client.post("/novedades/eliminar-todas", data={
                **self.headers, "confirmacion_texto": "ELIMINAR",
            })
        self.assertIn(b"3", vista.data)
        self.assertEqual(rechazo.status_code, 400)
        self.assertEqual(confirmada.status_code, 302)
        self.assertTrue(estado["eliminado"])
        self.assertEqual(estado["cantidad"], 0)
        self.assertEqual(set(tablas), {"novedades"})

    def test_migracion_nueva_archiva_reversible_sin_borrar_y_actualiza_dashboard_agregado(self):
        sql = (ROOT / "supabase/migrations/20261029_act07_dashboard_archivo_y_seguridad.sql").read_text(encoding="utf-8").lower()
        self.assertIn("estado = 'archivada'", sql)
        self.assertIn("restaurar_novedad_archivada", sql)
        self.assertIn("dashboard_admin_act07", sql)
        self.assertIn("pg_advisory_xact_lock", sql)
        self.assertIn("ultimo_admin_activo", sql)
        self.assertIn("autodesactivacion_no_permitida", sql)
        self.assertIn("daterange(n.fecha_inicio, n.fecha_fin, '[]') @> p_dia", sql)
        self.assertNotIn("delete from", sql)
        inicio = sql.index("create or replace function public.archivar_novedades_anteriores")
        fin = sql.index("create or replace function public.restaurar_novedad_archivada")
        bloque_archivo = sql[inicio:fin]
        self.assertIn("update public.novedades", bloque_archivo)
        self.assertNotIn("update public.trabajadores", bloque_archivo)
        self.assertIn("p_cantidad_esperada", bloque_archivo)

    def test_dashboard_refresca_con_intervalo_moderado(self):
        template = (ROOT / "templates/administrador/dashboard.html").read_text(encoding="utf-8")
        sql = (ROOT / "supabase/migrations/20261029_act07_dashboard_archivo_y_seguridad.sql").read_text(encoding="utf-8").lower()
        self.assertIn("5 * 60 * 1000", template)
        self.assertIn("a.fecha_entrada >= inicio_dia and a.fecha_entrada < fin_dia", sql)
        self.assertIn("a.fecha_entrada < inicio_dia and a.fecha_salida is null", sql)
        self.assertIn("union", sql)

    def test_get_novedades_renderiza_formulario_y_filtros(self):
        class Query:
            def select(self, *_args, **_kwargs): return self
            def eq(self, *_args, **_kwargs): return self
            def order(self, *_args, **_kwargs): return self
            def gte(self, *_args, **_kwargs): return self
            def lte(self, *_args, **_kwargs): return self
            def ilike(self, *_args, **_kwargs): return self
            def range(self, *_args, **_kwargs): return self
            def execute(self): return SimpleNamespace(data=[])

        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app.supabase, "table", return_value=Query()
        ):
            response = self.client.get("/novedades")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Registrar novedad", response.data)
        self.assertIn(b"Aplicar filtros", response.data)
        self.assertNotIn(b"novedad-cot", response.data)
        self.assertNotIn(b"novedad-proyecto", response.data)

    def test_dashboard_usa_un_agregado_diario_y_no_carga_historial(self):
        datos = {
            "trabajadores_activos": 8, "presentes": 5,
            "ausencias_injustificadas": 1, "novedades_vigentes": 2,
            "proyectos": [{"cot": "COT-3", "proyecto": "Obra norte", "tramos": 5, "abiertos": 2}],
            "novedades_recientes": [{"id": 31, "tipo": "permiso", "trabajador_id": 12,
                "trabajador_nombre": "Trabajadora de prueba", "fecha_inicio": "2026-10-28",
                "fecha_fin": "2026-10-28", "proyecto": "Obra norte", "cot": "COT-3",
                "motivo": "Cita", "observaciones": None, "creado_en": "2026-10-28T12:00:00Z", "estado": "registrada"}],
        }
        rpc = MagicMock()
        rpc.execute.return_value = SimpleNamespace(data=datos)
        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app.supabase, "rpc", return_value=rpc
        ) as llamada_rpc, patch.object(asistencia_app.supabase, "table") as tabla:
            response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"TRABAJADORES ACTIVOS", response.data)
        self.assertIn(b"Trabajadora de prueba", response.data)
        self.assertIn(b"COT-3", response.data)
        self.assertNotIn(b">120<", response.data)
        llamada_rpc.assert_called_once()
        self.assertEqual(llamada_rpc.call_args.args[0], "dashboard_admin_act07")
        tabla.assert_not_called()

    def test_dashboard_sin_lectura_ni_cache_muestra_error_y_no_inventa_cifras(self):
        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app.supabase, "rpc", side_effect=RuntimeError("offline")
        ), patch.object(asistencia_app, "dashboard_desde_tablas_existentes", side_effect=RuntimeError("offline")):
            response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No se pudieron actualizar los indicadores", response.data)
        self.assertIn(b"Sin actualizaci\xc3\xb3n confirmada", response.data)
        self.assertNotIn(b">0<", response.data)

    def test_fecha_bogota_convierte_el_cambio_de_dia_desde_utc(self):
        instante = asistencia_app.datetime(2026, 10, 29, 4, 30, tzinfo=asistencia_app.timezone.utc)
        self.assertEqual(asistencia_app.fecha_actual_bogota(instante).isoformat(), "2026-10-28")

    def test_entrada_con_observacion_usa_wrapper_act07_y_conserva_el_uuid(self):
        rpc = MagicMock()
        rpc.execute.return_value = SimpleNamespace(data={"id": 21, "trabajador_id": 12})
        trabajador = {"id": 12, "nombre": "Prueba", "perfil": "trabajador", "estado": "activo"}
        with patch.object(asistencia_app, "verificar_coordinador_api", return_value=({"id": 5}, None)), patch.object(
            asistencia_app, "resolver_persona_asistencia", return_value=(trabajador, None)
        ), patch.object(asistencia_app.supabase, "rpc", return_value=rpc) as llamada_rpc:
            response = self.client.post("/api/asistencia/entrada", json={
                "trabajador_id": 12, "cot": "COT-3", "proyecto": "Proyecto Norte",
                "observaciones": "Cambio de turno", "ubicacion_estado": "no_disponible",
                "ocurrio_en": "2026-10-28T12:00:00Z", "operacion_id": "12345678-1234-4234-8234-123456789abc",
            }, headers={"X-CSRF-Token": "csrf-act07"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(llamada_rpc.call_args.args[0], "registrar_entrada_asistencia_act07")
        self.assertEqual(llamada_rpc.call_args.args[1]["p_observaciones"], "Cambio de turno")
        self.assertEqual(response.get_json()["operacion_id"], "12345678-1234-4234-8234-123456789abc")

    def test_salida_con_observacion_usa_wrapper_act07_y_conserva_el_uuid(self):
        rpc = MagicMock()
        rpc.execute.return_value = SimpleNamespace(data={"id": 21, "trabajador_id": 12})
        trabajador = {"id": 12, "nombre": "Prueba", "perfil": "trabajador", "estado": "activo"}
        with patch.object(asistencia_app, "verificar_coordinador_api", return_value=({"id": 5}, None)), patch.object(
            asistencia_app, "resolver_persona_asistencia", return_value=(trabajador, None)
        ), patch.object(asistencia_app.supabase, "rpc", return_value=rpc) as llamada_rpc:
            response = self.client.post("/api/asistencia/salida", json={
                "trabajador_id": 12, "observaciones": "Fin de turno en obra",
                "ubicacion_estado": "no_disponible", "ocurrio_en": "2026-10-28T20:00:00Z",
                "operacion_id": "12345678-1234-4234-8234-123456789abd",
            }, headers={"X-CSRF-Token": "csrf-act07"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(llamada_rpc.call_args.args[0], "registrar_salida_asistencia_act07")
        self.assertEqual(llamada_rpc.call_args.args[1]["p_observaciones"], "Fin de turno en obra")
        self.assertEqual(response.get_json()["operacion_id"], "12345678-1234-4234-8234-123456789abd")

    def test_crea_novedad_con_responsable_servidor_y_clave_deduplicacion(self):
        persona_q = MagicMock()
        persona_q.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{"id": 12, "perfil": "trabajador"}]
        )
        novedades_q = MagicMock()
        novedades_q.insert.return_value.select.return_value.execute.return_value = SimpleNamespace(data=[{"id": 91}])

        def table(name):
            return persona_q if name == "trabajadores" else novedades_q

        with patch.object(asistencia_app, "requiere_perfil", return_value=None), patch.object(
            asistencia_app.supabase, "table", side_effect=table
        ):
            response = self.client.post("/novedades", data={
                **self.headers, "trabajador_id": "12", "tipo": "permiso",
                "fecha_inicio": "2026-10-28", "fecha_fin": "2026-10-28",
                "hora_inicio": "", "hora_fin": "", "cot": "COT-3", "proyecto": "Obra norte",
                "motivo": "Cita médica", "observaciones": "Avisó",
            })
        self.assertEqual(response.status_code, 302)
        payload = novedades_q.insert.call_args.args[0]
        self.assertEqual(payload["responsable_id"], 5)
        self.assertEqual(len(payload["dedupe_key"]), 64)
        self.assertTrue(response.headers["Location"].endswith("/novedades"))

    def test_migracion_act07_es_aditiva_y_no_recrea_historial(self):
        sql = (ROOT / "supabase/migrations/20261028_act07_novedades_y_tramos.sql").read_text(encoding="utf-8").lower()
        self.assertIn("create table if not exists public.novedades", sql)
        self.assertIn("add column if not exists observaciones_entrada", sql)
        self.assertIn("add column if not exists observaciones_salida", sql)
        self.assertIn("registrar_entrada_asistencia_offline", sql)
        self.assertIn("registrar_salida_asistencia_offline", sql)
        self.assertIn("dedupe_key text not null unique", sql)
        self.assertNotIn("drop table", sql)
        self.assertNotIn("delete from", sql)

    def test_categorias_legadas_se_conservan_como_historicas(self):
        etiqueta, color = asistencia_app.etiqueta_novedad("llegada_tarde")
        self.assertTrue(etiqueta.startswith("Histórica"))
        self.assertEqual(color, "coral")
        self.assertEqual(set(asistencia_app.NOVEDADES_TIPOS), {
            "permiso", "vacaciones", "incapacidad", "inasistencia_injustificada",
        })
        self.assertEqual(asistencia_app.etiqueta_novedad("inasistencia_injustificada")[0], "Ausencia injustificada")
        self.assertNotIn("llegada_tarde", asistencia_app.NOVEDADES_TIPOS)
        self.assertNotIn("llegada_tarde", asistencia_app.NOVEDADES_TIPOS_PARA_FILTRO)

    def test_modelo_act06_permite_tramos_sucesivos_sin_sobrescribir(self):
        sql = (ROOT / "backups/act06-field-improvements-20261023/supabase/migrations/20261022_act06_asistencia_visitas.sql").read_text(encoding="utf-8").lower()
        self.assertIn("create table if not exists public.registros_asistencia", sql)
        self.assertIn("fecha_entrada timestamptz", sql)
        self.assertIn("fecha_salida timestamptz", sql)
        self.assertIn("on public.registros_asistencia (trabajador_id)", sql)
        self.assertIn("where fecha_salida is null", sql)


if __name__ == "__main__":
    unittest.main()
