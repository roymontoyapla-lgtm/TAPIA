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
        assert "sueno"     in df.columns
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
        assert pd.api.types.is_numeric_dtype(df["sueno"])


# ---------------------------------------------------------------------------
# Tests: flujo de la pagina "Plan de salud" (sin UI)
# ---------------------------------------------------------------------------

@pytest.fixture
def lifestyle_db(tmp_path, monkeypatch):
    """Base de datos temporal aislada para el flujo del plan."""
    import tapia.db.database as database_module
    monkeypatch.setattr(database_module, "_DB_PATH", tmp_path / "test_lifestyle.db")
    database_module.init_db()
    return database_module


class TestLifestylePageFlow:
    """Simula lo que hace page_lifestyle.run() internamente."""

    def _seed(self, db, steps=3500, ex_min=8, sleep=5.4):
        patient_id = db.get_or_create_patient("Luis Prueba", 58, "M")
        db.import_wearable_records(patient_id, _make_records(40, sleep=sleep, steps=steps, hr=72))
        db.save_lab_result(
            patient_id,
            raw_json='{"bioquimica": {"glucosa_mg_dl": 132, "colesterol_ldl_mg_dl": 172}}',
            fecha="2026-01-15",
        )
        db.save_anthropometry(
            patient_id, weight_kg=101.0, height_cm=176.0, waist_cm=114.0,
            bmi=32.6, bmi_category="Obesidad grado I", waist_category="Riesgo muy aumentado",
        )
        return patient_id

    def _plan_for(self, db, patient_id):
        from tapia.core.lifestyle import build_lifestyle_plan
        from tapia.ui.streamlit_pages.page_lifestyle import _wearable_summary

        w30, _ = _wearable_summary(patient_id, days=30)
        anthro  = db.get_latest_anthropometry(patient_id)
        lab     = db.get_latest_lab(patient_id)
        return build_lifestyle_plan(
            patient={"name": "Luis Prueba", "age": 58, "sex": "M"},
            q={"diet_style": "mediterranea", "other_notes": "hipertension",
               "exercise_days_last_weeks": 1},
            anthro=anthro,
            w30=w30,
            lab_data=(lab or {}).get("data"),
            final_bucket="7_dias",
        ), w30

    def test_wearable_summary_from_db(self, lifestyle_db):
        patient_id = self._seed(lifestyle_db)
        from tapia.ui.streamlit_pages.page_lifestyle import _wearable_summary
        w30, total = _wearable_summary(patient_id, days=30)
        assert total == 40
        assert w30 is not None and w30.days <= 31
        assert w30.avg_steps == pytest.approx(3500, abs=1)

    def test_sin_wearable_devuelve_none(self, lifestyle_db):
        patient_id = lifestyle_db.get_or_create_patient("Sin Datos", 40, "F")
        from tapia.ui.streamlit_pages.page_lifestyle import _wearable_summary
        w30, total = _wearable_summary(patient_id, days=30)
        assert (w30, total) == (None, 0)

    def test_plan_usa_wearable_antropometria_y_analisis(self, lifestyle_db):
        patient_id = self._seed(lifestyle_db)
        plan, w30 = self._plan_for(lifestyle_db, patient_id)

        assert plan.nutrition.energy.objective == "perder_peso"
        assert plan.exercise.baseline_steps == pytest.approx(3500, abs=1)
        assert any("diabetic" in p.lower() for p in plan.nutrition.priorities)
        assert any("colesterol" in p.lower() for p in plan.nutrition.priorities)
        assert any("hipertension" in r.lower() for r in plan.exercise.restrictions)

    def test_plan_se_guarda_y_se_recupera(self, lifestyle_db):
        from tapia.core.lifestyle import render_plan_text
        patient_id = self._seed(lifestyle_db)
        plan, _ = self._plan_for(lifestyle_db, patient_id)

        lifestyle_db.save_lifestyle_plan(
            patient_id=patient_id,
            plan_text=render_plan_text(plan),
            objective=plan.nutrition.energy.objective,
            target_kcal=plan.nutrition.energy.target_kcal,
            weekly_min=plan.exercise.weekly_min_target,
            steps_goal=plan.exercise.steps_goal,
            clearance=plan.medical_clearance,
        )
        saved = lifestyle_db.get_latest_lifestyle_plan(patient_id)
        assert saved["objective"] == "perder_peso"
        assert saved["target_kcal"] == plan.nutrition.energy.target_kcal
        assert "PLAN DE ALIMENTACION Y EJERCICIO" in saved["plan_text"]


# ---------------------------------------------------------------------------
# Tests: boton de carga desde Dropbox (sin UI real)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_st(monkeypatch):
    """
    Sustituye streamlit dentro de page_triage para poder ejecutar la funcion
    de la pagina. Sin esto, un fallo tonto (una variable sin definir) solo
    aparece al abrir la aplicacion.
    """
    from unittest.mock import MagicMock
    from tapia.ui.streamlit_pages import page_triage

    st = MagicMock()
    st.columns.return_value = (MagicMock(), MagicMock())
    st.button.return_value = False
    st.checkbox.return_value = False
    monkeypatch.setattr(page_triage, "st", st)
    return st


def _fake_dropbox(monkeypatch, configurado=True):
    from unittest.mock import MagicMock
    from tapia.ui.streamlit_pages import page_triage

    source = MagicMock()
    source.NAME = "dropbox"
    source.is_configured.return_value = configurado
    source.missing_config.return_value = [] if configurado else ["DROPBOX_APP_KEY"]
    monkeypatch.setattr(page_triage, "DropboxSource", lambda **kw: source)
    return source


class TestBotonDropbox:

    def _patient(self, nombre="Luis Prueba"):
        return PatientInfo(name=nombre, age=58, sex="M")

    def test_sin_configurar_solo_explica_como_hacerlo(self, fake_st, monkeypatch):
        from tapia.ui.streamlit_pages import page_triage
        llamadas = []
        monkeypatch.setattr(page_triage, "sync_patient",
                            lambda *a, **k: llamadas.append(a))
        _fake_dropbox(monkeypatch, configurado=False)

        page_triage._section_cloud_sync(self._patient(), None)

        fake_st.expander.assert_called_once()
        fake_st.button.assert_not_called()
        assert llamadas == []

    def test_sin_nombre_de_paciente_el_boton_esta_deshabilitado(self, fake_st, monkeypatch):
        from tapia.ui.streamlit_pages import page_triage
        _fake_dropbox(monkeypatch)

        page_triage._section_cloud_sync(self._patient(nombre=""), None)

        assert fake_st.button.call_args.kwargs["disabled"] is True

    def test_con_nombre_el_boton_esta_activo(self, fake_st, monkeypatch):
        from tapia.ui.streamlit_pages import page_triage
        _fake_dropbox(monkeypatch)

        page_triage._section_cloud_sync(self._patient(), 7)

        assert fake_st.button.call_args.kwargs["disabled"] is False

    def test_al_pulsar_sincroniza_ese_paciente(self, fake_st, monkeypatch):
        from unittest.mock import MagicMock
        from tapia.ui.streamlit_pages import page_triage
        from tapia.wearables.sync import SyncResult

        source = _fake_dropbox(monkeypatch)
        fake_st.button.return_value = True
        monkeypatch.setattr(page_triage.db, "get_sync_state", lambda *a, **k: None)
        monkeypatch.setattr(page_triage, "log", MagicMock())

        recogido = {}

        def _sync(pid, **kwargs):
            recogido["pid"] = pid
            recogido.update(kwargs)
            return SyncResult(files_seen=1, files_imported=1, days_inserted=3)

        monkeypatch.setattr(page_triage, "sync_patient", _sync)

        page_triage._section_cloud_sync(self._patient(), 7)

        assert recogido["pid"] == 7
        assert recogido["source"] is source
        assert recogido["full"] is False
        fake_st.rerun.assert_called_once()
