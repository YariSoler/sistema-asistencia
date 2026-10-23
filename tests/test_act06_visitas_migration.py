from pathlib import Path
import re
import unittest


MIGRATION = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "20261023_act06_visitas_proyecto_participante.sql"


class MigrationVisitasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_migration_es_aditiva_y_conserva_historial(self):
        self.assertIn("add column if not exists proyecto text", self.sql)
        self.assertIn("add column if not exists trabajador_id bigint", self.sql)
        self.assertIn("references public.trabajadores(id)", self.sql)
        self.assertNotRegex(self.sql, r"\b(drop table|truncate|delete from)\b")

    def test_funcion_incluye_proyecto_y_participante_en_la_operacion(self):
        signature = re.search(r"create or replace function public\.registrar_visita_tecnica_offline\((.*?)\)\s*returns", self.sql, re.S)
        self.assertIsNotNone(signature)
        self.assertIn("p_proyecto text", signature.group(1))
        self.assertIn("p_trabajador_id bigint", signature.group(1))
        self.assertIn("visitas_tecnicas (\n        coordinador_id", self.sql)
        self.assertIn("payload_hash", self.sql)

    def test_reintento_mismo_payload_y_conflicto_diferente_payload(self):
        self.assertIn("on conflict (idempotency_key) do update", self.sql)
        self.assertIn("visitas_tecnicas.proyecto is not distinct from excluded.proyecto", self.sql)
        self.assertIn("visitas_tecnicas.trabajador_id is not distinct from excluded.trabajador_id", self.sql)
        self.assertIn("idempotency_key_reused_with_different_data", self.sql)

    def test_ejecucion_remota_restringida_a_service_role(self):
        self.assertIn("from public, anon, authenticated", self.sql)
        self.assertIn(") to service_role", self.sql)


if __name__ == "__main__":
    unittest.main()
