"""Tests de la lógica de triaje (core.triage)."""

import pytest

from tapia.core.models import PatientInfo, Questionnaire, WearableSummary
from tapia.core.triage import (
    URGENCY_ORDER,
    merge_buckets,
    triage_ap_vs_specialist,
    urgency_score_and_bucket,
)


# ===========================================================================
# merge_buckets
# ===========================================================================

class TestMergeBuckets:
    def test_local_wins_when_more_urgent(self):
        assert merge_buckets("urgente", "2_semanas") == "urgente"

    def test_ai_wins_when_more_urgent(self):
        assert merge_buckets("2_semanas", "urgente") == "urgente"

    def test_equal(self):
        assert merge_buckets("7_dias", "7_dias") == "7_dias"


# ===========================================================================
# triage_ap_vs_specialist
# ===========================================================================

class TestTriageAPSpecialist:

    def test_healthy_patient_goes_to_ap(
        self, questionnaire_healthy, wearable_normal
    ):
        rec, spec, reasons = triage_ap_vs_specialist(
            questionnaire_healthy, wearable_normal, wearable_normal
        )
        assert rec == "Médico de cabecera"
        assert spec == "-"

    def test_high_hr_suggests_cardiology(
        self, questionnaire_healthy, wearable_high_hr, wearable_normal
    ):
        rec, spec, reasons = triage_ap_vs_specialist(
            questionnaire_healthy, wearable_high_hr, wearable_normal
        )
        assert rec == "Posible especialista"
        assert "Cardiología" in spec

    def test_fever_adds_reason(
        self, questionnaire_severe, wearable_normal
    ):
        _, _, reasons = triage_ap_vs_specialist(
            questionnaire_severe, wearable_normal, wearable_normal
        )
        assert any("fiebre" in r.lower() for r in reasons)

    def test_bad_sleep_adds_reason(
        self, questionnaire_healthy, wearable_bad_sleep
    ):
        _, _, reasons = triage_ap_vs_specialist(
            questionnaire_healthy, wearable_bad_sleep, wearable_bad_sleep
        )
        assert any("sueño" in r.lower() for r in reasons)

    def test_chronic_disease_added_to_reasons(
        self, wearable_normal
    ):
        q = Questionnaire(
            headache_last_month=False, fever=False,
            general_feeling=4, diet_style="",
            rested_enough=4, exercise_days_last_weeks=4,
            other_notes="Hipertensión",
        )
        _, _, reasons = triage_ap_vs_specialist(q, wearable_normal, wearable_normal)
        assert any("Hipertensión" in r for r in reasons)

    def test_no_data_wearable(self, questionnaire_healthy, wearable_empty):
        rec, spec, reasons = triage_ap_vs_specialist(
            questionnaire_healthy, wearable_empty, wearable_empty
        )
        assert isinstance(rec, str)
        assert isinstance(reasons, list)


# ===========================================================================
# urgency_score_and_bucket
# ===========================================================================

class TestUrgencyScore:

    def test_healthy_young_is_two_weeks(
        self, patient_young, questionnaire_healthy, wearable_normal
    ):
        bucket, score, _ = urgency_score_and_bucket(
            patient_young, questionnaire_healthy, wearable_normal, wearable_normal
        )
        assert bucket == "2_semanas"
        assert score < 5

    def test_elderly_severe_is_urgent(
        self, patient_elderly, questionnaire_severe, wearable_high_hr
    ):
        bucket, score, _ = urgency_score_and_bucket(
            patient_elderly, questionnaire_severe, wearable_high_hr, wearable_high_hr
        )
        assert bucket == "urgente"
        assert score >= 9

    def test_fever_plus_bad_general_bonus(
        self, patient_young, wearable_normal
    ):
        q_fever_bad = Questionnaire(
            headache_last_month=False, fever=True,
            general_feeling=1, diet_style="",
            rested_enough=3, exercise_days_last_weeks=3,
            other_notes="",
        )
        _, score, motivos = urgency_score_and_bucket(
            patient_young, q_fever_bad, wearable_normal, wearable_normal
        )
        assert any("bonus" in m.lower() or "fiebre + mal" in m.lower() for m in motivos)

    def test_age_75_adds_max_age_score(
        self, questionnaire_healthy, wearable_normal
    ):
        p75 = PatientInfo(name="Test", age=75, sex="M")
        _, score_75, _ = urgency_score_and_bucket(
            p75, questionnaire_healthy, wearable_normal, wearable_normal
        )
        p64 = PatientInfo(name="Test", age=64, sex="M")
        _, score_64, _ = urgency_score_and_bucket(
            p64, questionnaire_healthy, wearable_normal, wearable_normal
        )
        assert score_75 > score_64

    def test_high_hr_days_pushes_to_urgent(
        self, patient_young, questionnaire_healthy, wearable_high_hr
    ):
        # wearable_high_hr tiene high_resting_hr_days=6 → +4 puntos
        bucket, score, _ = urgency_score_and_bucket(
            patient_young, questionnaire_healthy, wearable_high_hr, wearable_high_hr
        )
        assert score >= 4

    def test_score_includes_total_in_motivos(
        self, patient_young, questionnaire_healthy, wearable_normal
    ):
        _, score, motivos = urgency_score_and_bucket(
            patient_young, questionnaire_healthy, wearable_normal, wearable_normal
        )
        assert any(str(score) in m for m in motivos)

    def test_empty_wearable_still_works(
        self, patient_young, questionnaire_mild, wearable_empty
    ):
        bucket, score, motivos = urgency_score_and_bucket(
            patient_young, questionnaire_mild, wearable_empty, wearable_empty
        )
        assert bucket in ("urgente", "7_dias", "2_semanas")
        assert isinstance(score, int)

    @pytest.mark.parametrize("age,expected_min_score", [
        (30, 0),
        (50, 1),
        (65, 2),
        (75, 3),
    ])
    def test_age_scoring_thresholds(
        self, age, expected_min_score, questionnaire_healthy, wearable_normal
    ):
        patient = PatientInfo(name="Test", age=age, sex="M")
        _, score, _ = urgency_score_and_bucket(
            patient, questionnaire_healthy, wearable_normal, wearable_normal
        )
        assert score >= expected_min_score
