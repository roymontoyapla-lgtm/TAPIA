"""Tests del constructor de informes (core.report)."""

from tapia.core.report import build_report


def _base_ai():
    return {"urgency": "2_semanas", "justification": "Test.", "red_flags": []}


class TestBuildReport:

    def test_contains_patient_name(
        self, patient_young, questionnaire_healthy, wearable_normal
    ):
        report = build_report(
            patient_young, questionnaire_healthy,
            wearable_normal, wearable_normal,
            "Médico de cabecera", "-", ["Puntuación orientativa → AP: 0, Especialista: 0."],
            "2_semanas", 0, ["Score total: 0"],
            _base_ai(), "2_semanas",
        )
        assert patient_young.name in report

    def test_contains_urgency_label(
        self, patient_young, questionnaire_healthy, wearable_normal
    ):
        report = build_report(
            patient_young, questionnaire_healthy,
            wearable_normal, wearable_normal,
            "Médico de cabecera", "-", [],
            "urgente", 12, ["Score total: 12"],
            _base_ai(), "urgente",
        )
        assert "URGENTE" in report

    def test_disclaimer_present(
        self, patient_young, questionnaire_healthy, wearable_normal
    ):
        report = build_report(
            patient_young, questionnaire_healthy,
            wearable_normal, wearable_normal,
            "Médico de cabecera", "-", [],
            "2_semanas", 2, ["Score total: 2"],
            _base_ai(), "2_semanas",
        )
        assert "orientativo" in report.lower()

    def test_ai_red_flags_included(
        self, patient_young, questionnaire_healthy, wearable_normal
    ):
        ai = {
            "urgency": "urgente",
            "justification": "Bandera roja detectada.",
            "red_flags": ["FC reposo elevada persistente"],
            "_model_used": "gpt-4o-mini",
        }
        report = build_report(
            patient_young, questionnaire_healthy,
            wearable_normal, wearable_normal,
            "Médico de cabecera", "-", [],
            "7_dias", 6, [],
            ai, "urgente",
        )
        assert "FC reposo elevada persistente" in report

    def test_returns_string(
        self, patient_young, questionnaire_healthy, wearable_normal
    ):
        result = build_report(
            patient_young, questionnaire_healthy,
            wearable_normal, wearable_normal,
            "Médico de cabecera", "-", [],
            "2_semanas", 1, [],
            _base_ai(), "2_semanas",
        )
        assert isinstance(result, str)
        assert len(result) > 100
