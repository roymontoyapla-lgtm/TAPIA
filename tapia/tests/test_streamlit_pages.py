"""
Tests de integración de las páginas Streamlit.
No levantan un navegador: verifican que la lógica subyacente funciona
correctamente antes de llegar a la capa de UI.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from tapia.core.models import PatientInfo, Questionnaire, WearableSummary
from tapia.core.report import build_report
from tapia.core.triage import merge_buckets, triage_ap_vs_specialist, urgency_score_and_bucket
from tapia.core.wearable import filter_by_days, summarize


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_records(n: int, sleep: float = 7.0, steps: int = 6000, hr: int = 65) -> list:
    today = date.today()
    return [
        {
            "fecha":                       (today - timedelta(days=i)).isoformat(),
            "sueno_asleep_horas":          sleep,
            "pasos":                       steps,
            "pulso_reposo_bpm_media":      hr,
            "min_ejercicio":               30,
            "respiraciones_por_min_media": 15,
            "hrv_sdnn_ms_media":           40,
        }
        for i in range(n)
    ]


def _ai_ok() -> Dict[str, Any]:
    return {"urgency": "7_dias", "justification": "Test IA.", "red_flags": [], "_model_used": "gpt-4o-mini"}


def _ai_fallback() -> Dict[str, Any]:
    return {"urgency": "2_semanas", "justification": "IA no disponible.", "red_flags": []}


# ---------------------------------------------------------------------------
# Tests: flujo completo de triaje (sin UI)
# ---------------------------------------------------------------------------

class TestFullTriageFlow:
    """Simula exactamente lo que hace page_triage.run() internamente."""

    def _run(self, patient, q, records):
        w30 = summarize(filter_by_days(records, 30))
        w56 = summarize(filter_by_days(records, 56))
        rec, spec, reasons = triage_ap_vs_specialist(q, w30, w56)
        local_bucket, local_score, local_motivos = urgency_score_and_bucket(patient, q, w30, w56)
        pre = build_report(
            patient, q, w30, w56, rec, spec, reasons,
            local_bucket, local_score, local_motivos,
            {"urgency": "2_semanas", "justification": "", "red_flags": []},
            local_bucket,
        )
        ai = _ai_fallback()
        final_bucket = merge_buckets(local_bucket, ai.get("urgency", "2_semanas"))
        report = build_report(
            patient, q, w30, w56, rec, spec, reasons,
            local_bucket, local_score, local_motivos,
            ai, final_bucket,
        )
        return report, local_bucket, final_bucket, w30, w56

    def test_healthy_patient_full_flow(self, patient_young, questionnaire_healthy):
        records = _make_records(40)
        report, local_bucket, final_bucket, w30, w56 = self._run(
            patient_young, questionnaire_healthy, records
        )
        assert isinstance(report, str)
        assert len(report) > 200
        assert final_bucket in ("urgente", "7_dias", "2_semanas")
        assert w30.days == 31   # hoy + 30 días atrás
        assert w56.days == 40   # todos los registros (ventana 56d > 40 disponibles)

    def test_severe_patient_urgent(self, patient_elderly, questionnaire_severe):
        records = _make_records(35, sleep=4.5, hr=95)
        report, local_bucket, final_bucket, _, _ = self._run(
            patient_elderly, questionnaire_severe, records
        )
        assert local_bucket == "urgente"
        assert final_bucket == "urgente"
        assert "URGENTE" in report

    def test_ai_escalates_priority(self, patient_young, questionnaire_mild):
        """Si la IA devuelve urgente y el local es 2_semanas, el final es urgente."""
        records = _make_records(35)
        w30 = summarize(filter_by_days(records, 30))
        w56 = summarize(filter_by_days(records, 56))
        rec, spec, reasons = triage_ap_vs_specialist(questionnaire_mild, w30, w56)
        local_bucket, local_score, local_motivos = urgency_score_and_bucket(
            patient_young, questionnaire_mild, w30, w56
        )
        # Forzamos que la IA diga urgente
        ai = {"urgency": "urgente", "justification": "IA detectó algo grave.", "red_flags": ["FC alta"]}
        final_bucket = merge_buckets(local_bucket, ai["urgency"])
        assert final_bucket == "urgente"

    def test_report_contains_patient_data(self, patient_young, questionnaire_healthy):
        records = _make_records(35)
        report, *_ = self._run(patient_young, questionnaire_healthy, records)
        assert patient_young.name in report
        assert str(patient_young.age) in report

    def test_empty_wearable_does_not_crash(self, patient_young, questionnaire_healthy):
        report, local_bucket, final_bucket, w30, w56 = self._run(
            patient_young, questionnaire_healthy, []
        )
        assert isinstance(report, str)
        assert w30.days == 0
        assert final_bucket in ("urgente", "7_dias", "2_semanas")


# ---------------------------------------------------------------------------
# Tests: session state helpers
# ---------------------------------------------------------------------------

class TestSession:
    """Tests del módulo ui.session (sin Streamlit real)."""

    def test_triage_record_creation(self, patient_young, questionnaire_healthy, wearable_normal):
        from tapia.ui.session import TriageRecord
        rec = TriageRecord(
            timestamp="2024-03-15 10:00",
            patient_name=patient_young.name,
            patient_age=patient_young.age,
            patient_sex=patient_young.sex,
            local_bucket="2_semanas",
            local_score=3,
            final_bucket="2_semanas",
            ai_bucket="2_semanas",
            ai_model="gpt-4o-mini",
            rec="Médico de cabecera",
            spec="-",
            report_text="Informe de prueba",
            wearable_days=30,
        )
        assert rec.patient_name == patient_young.name
        assert rec.final_bucket == "2_semanas"
        assert rec.local_score == 3


# ---------------------------------------------------------------------------
# Tests: gráficas (solo la lógica de transformación de datos)
# ---------------------------------------------------------------------------

class TestChartData:
    """Verifica que los datos del wearable se transforman correctamente para plotly."""

    def test_dataframe_has_expected_columns(self):
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas no instalado")

        from tapia.ui.streamlit_pages.page_history import _build_dataframe
        records = _make_records(10, sleep=6.5, steps=7000, hr=65)
        df = _build_dataframe(records)
        assert "fecha"     in df.columns
        assert "fc"        in df.columns
        assert "pasos"     in df.columns
        assert "sueño"     in df.columns
        assert "ejercicio" in df.columns
        assert len(df) == 10

    def test_dataframe_sorts_by_date(self):
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas no instalado")

        from tapia.ui.streamlit_pages.page_history import _build_dataframe
        records = _make_records(15)
        df = _build_dataframe(records)
        assert list(df["fecha"]) == sorted(df["fecha"].tolist())

    def test_invalid_records_skipped(self):
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas no instalado")

        from tapia.ui.streamlit_pages.page_history import _build_dataframe
        bad = [{"sin_fecha": True, "pasos": 5000}]
        good = _make_records(5)
        df = _build_dataframe(bad + good)
        assert len(df) == 5

    def test_numeric_conversion(self):
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas no instalado")

        from tapia.ui.streamlit_pages.page_history import _build_dataframe
        records = _make_records(5)
        df = _build_dataframe(records)
        assert pd.api.types.is_numeric_dtype(df["fc"])
        assert pd.api.types.is_numeric_dtype(df["pasos"])
        assert pd.api.types.is_numeric_dtype(df["sueño"])
