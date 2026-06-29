"""Fixtures compartidas para los tests de TAPIA."""

import json
import os
import tempfile
from datetime import date, timedelta

import pytest

from tapia.core.models import PatientInfo, Questionnaire, WearableSummary


# ---------------------------------------------------------------------------
# Pacientes tipo
# ---------------------------------------------------------------------------

@pytest.fixture
def patient_young():
    return PatientInfo(name="Ana García", age=35, sex="F")

@pytest.fixture
def patient_elderly():
    return PatientInfo(name="José Martínez", age=78, sex="M")


# ---------------------------------------------------------------------------
# Cuestionarios tipo
# ---------------------------------------------------------------------------

@pytest.fixture
def questionnaire_healthy():
    return Questionnaire(
        headache_last_month=False,
        fever=False,
        general_feeling=4,
        diet_style="mediterránea",
        rested_enough=4,
        exercise_days_last_weeks=4,
        other_notes="",
    )

@pytest.fixture
def questionnaire_mild():
    return Questionnaire(
        headache_last_month=True,
        fever=False,
        general_feeling=3,
        diet_style="",
        rested_enough=3,
        exercise_days_last_weeks=2,
        other_notes="",
    )

@pytest.fixture
def questionnaire_severe():
    return Questionnaire(
        headache_last_month=True,
        fever=True,
        general_feeling=1,
        diet_style="",
        rested_enough=1,
        exercise_days_last_weeks=0,
        other_notes="Diabetes tipo 2",
    )


# ---------------------------------------------------------------------------
# Resúmenes de wearable tipo
# ---------------------------------------------------------------------------

@pytest.fixture
def wearable_normal():
    return WearableSummary(
        days=30, range="2024-03-01 a 2024-03-30",
        avg_resting_hr=62.0, avg_steps=7500.0,
        avg_exercise_min=35.0, avg_sleep_h=7.2,
        avg_resp=15.0, avg_hrv=45.0,
        low_sleep_days=2,
        very_low_activity_days=1,
        high_resting_hr_days=0,
    )

@pytest.fixture
def wearable_bad_sleep():
    return WearableSummary(
        days=30, range="2024-03-01 a 2024-03-30",
        avg_resting_hr=68.0, avg_steps=5000.0,
        avg_exercise_min=20.0, avg_sleep_h=5.1,
        avg_resp=16.0, avg_hrv=38.0,
        low_sleep_days=18,
        very_low_activity_days=5,
        high_resting_hr_days=0,
    )

@pytest.fixture
def wearable_high_hr():
    return WearableSummary(
        days=30, range="2024-03-01 a 2024-03-30",
        avg_resting_hr=96.0, avg_steps=3500.0,
        avg_exercise_min=10.0, avg_sleep_h=6.8,
        avg_resp=18.0, avg_hrv=28.0,
        low_sleep_days=4,
        very_low_activity_days=8,
        high_resting_hr_days=6,
    )

@pytest.fixture
def wearable_empty():
    return WearableSummary(
        days=0, range="N/D",
        avg_resting_hr=None, avg_steps=None,
        avg_exercise_min=None, avg_sleep_h=None,
        avg_resp=None, avg_hrv=None,
        low_sleep_days=0,
        very_low_activity_days=0,
        high_resting_hr_days=0,
    )


# ---------------------------------------------------------------------------
# Fixture de fichero JSON temporal
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_json_file(tmp_path):
    """Genera un JSON de wearable con 35 días de datos sintéticos."""
    today = date.today()
    records = []
    for i in range(35):
        d = today - timedelta(days=i)
        records.append({
            "fecha":                    d.isoformat(),
            "pulso_reposo_bpm_media":   60 + (i % 5),
            "pasos":                    6000 + (i % 3) * 1000,
            "min_ejercicio":            30 + (i % 4) * 5,
            "sueno_asleep_horas":       6.5 + (i % 3) * 0.5,
            "respiraciones_por_min_media": 15.0,
            "hrv_sdnn_ms_media":        42.0,
        })
    path = tmp_path / "wearable_test.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return str(path)
