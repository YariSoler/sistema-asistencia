import re
import os
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("FLASK_SECRET_KEY", "test-flask-secret")

import app as asistencia_app


ROOT = Path(__file__).resolve().parents[1]


class TestDirectorioYBusquedaOffline(unittest.TestCase):
    def setUp(self):
        asistencia_app.app.config.update(TESTING=True)
        self.client = asistencia_app.app.test_client()
        with self.client.session_transaction() as session:
            session["_csrf_token"] = "offline-test-token"
        self.headers = {"X-CSRF-Token": "offline-test-token"}
        self.coordinador = {"id": 7, "nombre": "Coordinadora"}

    def test_busqueda_por_identificacion_devuelve_minimo_y_no_autentica(self):
        persona = {"id": 15, "nombre": "Operario de prueba", "cargo": "Operario", "perfil": "trabajador", "estado": "activo"}
        persona_query = MagicMock()
        persona_query.select.return_value = persona_query
        persona_query.eq.return_value = persona_query
        persona_query.limit.return_value = persona_query
        persona_query.execute.return_value = SimpleNamespace(data=[persona])
        attendance_query = MagicMock()
        attendance_query.select.return_value = attendance_query
        attendance_query.eq.return_value = attendance_query
        attendance_query.is_.return_value = attendance_query
        attendance_query.limit.return_value = attendance_query
        attendance_query.execute.return_value = SimpleNamespace(data=[])

        with patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None)), \
             patch.object(asistencia_app.supabase, "table", side_effect=[persona_query, attendance_query]):
            response = self.client.post(
                "/api/asistencia/buscar-identificacion",
                json={"identificacion": "  12345  "}, headers=self.headers,
            )

        assert response.status_code == 200
        assert response.get_json()["trabajador"] == {"id": 15, "nombre": "Operario de prueba", "cargo": "Operario"}
        assert "identificacion" not in response.get_json()["trabajador"]
        assert "auth_user_id" not in response.get_json()["trabajador"]

    def test_busqueda_rechaza_persona_inactiva(self):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.limit.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{
            "id": 15, "nombre": "Operario", "cargo": "Operario", "perfil": "trabajador", "estado": "inactivo",
        }])
        with patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None)), \
             patch.object(asistencia_app.supabase, "table", return_value=query):
            response = self.client.post("/api/asistencia/buscar-identificacion", json={"identificacion": "12345"}, headers=self.headers)
        assert response.status_code == 409

    def test_directorio_solo_entrega_operarios_activos_y_estado_de_turno(self):
        abierto = {"trabajador_id": 15, "cot": "COT-1", "proyecto": "Obra", "fecha_entrada": "2026-10-23T10:00:00+00:00"}
        coordinador_query = MagicMock()
        coordinador_query.select.return_value = coordinador_query
        coordinador_query.eq.return_value = coordinador_query
        coordinador_query.limit.return_value = coordinador_query
        coordinador_query.execute.return_value = SimpleNamespace(data=[{"id": 7, "nombre": "Coordinadora", "qr": "QR-C", "perfil": "coordinador", "estado": "activo"}])
        with patch.object(asistencia_app, "verificar_coordinador_api", return_value=(self.coordinador, None)), \
             patch.object(asistencia_app, "lista_paginada", side_effect=[[
                 {"id": 15, "identificacion": "12345", "nombre": "Operario", "cargo": "Operario", "qr": "QR-O"}
             ], [abierto]]), \
             patch.object(asistencia_app.supabase, "table", return_value=coordinador_query):
            response = self.client.get("/api/asistencia/directorio-offline")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["trabajadores"]) == 1
        assert data["trabajadores"][0]["identificacion"] == "12345"
        assert data["trabajadores"][0]["registro_abierto"] == abierto
        assert "auth_user_id" not in data["trabajadores"][0]
        assert data["coordinador"]["registro_abierto"] is None


class TestColaYValidacionOffline(unittest.TestCase):
    def test_gps_denegado_se_valida_con_estado_explicito_y_sin_coordenadas(self):
        event, error = asistencia_app.validar_evento_offline({
            "operacion_id": str(uuid.uuid4()),
            "ocurrio_en": "2026-10-23T15:00:00Z",
            "ubicacion_estado": "no_disponible",
        }, "entrada", 7, 15, "COT-1", "Obra")
        assert error is None
        assert event["ubicacion_obtenida"] is False
        assert event["latitud"] is None and event["longitud"] is None
        assert re.fullmatch(r"[0-9a-f]{64}", event["payload_hash"])

    def test_entrada_offline_envia_id_estable_hash_y_gps_opcional_al_rpc(self):
        client = asistencia_app.app.test_client()
        with client.session_transaction() as session:
            session["_csrf_token"] = "offline-test-token"
        op_id = str(uuid.uuid4())
        rpc = MagicMock()
        rpc.execute.return_value = SimpleNamespace(data={"id": 88, "operacion_id": op_id})
        with patch.object(asistencia_app, "verificar_coordinador_api", return_value=({"id": 7}, None)), \
             patch.object(asistencia_app, "resolver_persona_asistencia", return_value=({
                 "id": 15, "perfil": "trabajador", "estado": "activo", "nombre": "Operario", "cargo": "Operario",
             }, None)), \
             patch.object(asistencia_app.supabase, "rpc", return_value=rpc) as rpc_call:
            response = client.post("/api/asistencia/entrada", json={
                "trabajador_id": 15, "cot": "COT-1", "proyecto": "Obra", "operacion_id": op_id,
                "ocurrio_en": "2026-10-23T15:00:00Z", "ubicacion_estado": "no_disponible",
            }, headers={"X-CSRF-Token": "offline-test-token"})
        assert response.status_code == 201
        args = rpc_call.call_args.args
        assert args[0] == "registrar_entrada_asistencia_offline"
        assert args[1]["p_operacion_id"] == op_id
        assert args[1]["p_ubicacion_obtenida"] is False
        assert args[1]["p_latitud"] is None
        assert response.get_json()["operacion_id"] == op_id

    def test_codigo_cliente_conserva_reintento_y_exige_confirmacion_del_servidor(self):
        js = (ROOT / "static/js/asistencia.js").read_text(encoding="utf-8")
        coordinator = (ROOT / "templates/coordinador/registro.html").read_text(encoding="utf-8")
        shell = (ROOT / "static/offline-shell.html").read_text(encoding="utf-8")
        assert 'indexedDB.open("asistencia-act06"' in js
        assert 'window.addEventListener("online"' in js
        assert "cachedWorkerByIdentification(identificacion)" in js
        assert 'operacion_id: createIdempotencyKey()' in js
        assert 'operacion_id: item.operacion_id' in js
        assert 'result.operacion_id !== item.operacion_id || !result.registro' in js
        assert 'item.estado = "confirmada"' in js
        assert 'item.estado = "pendiente"' in js
        assert '"necesita_revision"].includes(item.estado)' in js
        assert 'window.addEventListener("pageshow"' in js
        assert 'document.addEventListener("visibilitychange"' in js
        assert "2 ** retryAttempt" in js
        assert 'error?.kind === "network"' in js
        assert 'error?.name === "TypeError"' not in js
        assert 'async function fetchFromServer(url, options)' in js
        assert 'function logClientDiagnostic(error' in js
        assert 'const requiredIds = [' in js
        assert len(re.findall(r'\.textContent\s*=', js)) == 1
        assert 'registration.sync.register("act06-sync")' in js
        service_worker = (ROOT / "static/service-worker.js").read_text(encoding="utf-8")
        assert 'self.addEventListener("sync"' in service_worker
        assert 'const CACHE_NAME = "act06-offline-v7"' in service_worker
        assert "Network first prevents a stale JavaScript bundle" in service_worker
        assert "qr-scanner-worker.min.js" in service_worker
        assert "pending-count" not in re.search(r'const requiredIds = \[(.*?)\];', js, re.DOTALL).group(1)
        assert "cdnjs.cloudflare.com/ajax/libs/qr-scanner/1.4.2/qr-scanner.umd.min.js" in coordinator
        assert "integrity=\"sha512-Fb3L5w+k6OMng6v8gWYr7fuO//kwaC0PfMReI2pYIRYHRfkjvrsNHoGkiVCvjNkrXX3+Ve9Ag+COx98AZlvR7w==\"" in coordinator
        assert "async function ensureVisitQrScanner()" in js
        assert "cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner.umd.min.js" in js
        assert "window.QrScanner" in js
        assert 'verificar_coordinador_api()' in (ROOT / "app.py").read_text(encoding="utf-8")
        selectors = set(re.findall(r'\$\("([^\"]+)"\)', js))
        for page in (coordinator, shell):
            ids = set(re.findall(r'id="([^\"]+)"', page))
            assert selectors <= ids, f"DOM IDs missing from page: {sorted(selectors - ids)}"
            assert "manual-qr-form" not in page
            assert 'name="qr"' not in page
        assert "O ingresa el contenido del QR" not in coordinator
        for page in (coordinator, shell):
            choice = re.search(r'<section id="flow-choice".*?</section>', page, re.DOTALL).group(0)
            assert "offline-tools" not in choice
            assert "Con conexión" not in choice
            assert "Actualizar operarios" not in choice
            assert "Sincronizar pendientes" not in choice
            assert 'id="offline-flow"' in page
            assert 'id="pending-operations"' in page

    def test_migracion_valida_clave_idempotente_y_orden_cronologico(self):
        sql = (ROOT / "supabase/migrations/20261023_act06_gps_offline.sql").read_text(encoding="utf-8")
        assert "act06_operaciones" in sql
        assert "act06_sheets_outbox" in sql
        assert "ON CONFLICT (operacion_id) DO NOTHING" in sql
        assert "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA" in sql
        assert sql.count("RETURN existente.resultado") == 3
        assert "fecha_entrada <= p_ocurrio_en" in sql
        assert "SALIDA_ANTERIOR_A_ENTRADA" in sql
