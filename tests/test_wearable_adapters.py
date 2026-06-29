# -*- coding: utf-8 -*-
"""Tests de los adaptadores multi-wearable y el detector automatico."""

from __future__ import annotations
import json
import pytest
from tapia.wearables.base import NormalizedRecord
from tapia.wearables.adapter_tapia    import TapiaAdapter
from tapia.wearables.adapter_fitbit   import FitbitAdapter
from tapia.wearables.adapter_garmin   import GarminAdapter
from tapia.wearables.adapter_apple    import AppleHealthAdapter
from tapia.wearables.adapter_withings import WithingsAdapter
from tapia.wearables.detector         import detect_and_normalize, load_and_detect


# ---------------------------------------------------------------------------
# Datos de prueba
# ---------------------------------------------------------------------------

TAPIA_DATA = [
    {"fecha": "2024-03-01", "pulso_reposo_bpm_media": 62, "pasos": 7500,
     "min_ejercicio": 35, "sueno_asleep_horas": 7.2,
     "respiraciones_por_min_media": 15, "hrv_sdnn_ms_media": 42},
    {"fecha": "2024-03-02", "pulso_reposo_bpm_media": 65, "pasos": 8000,
     "min_ejercicio": 40, "sueno_asleep_horas": 6.8,
     "respiraciones_por_min_media": 15, "hrv_sdnn_ms_media": 38},
]

FITBIT_DATA = [
    {"dateTime": "2024-03-01", "value": {
        "restingHeartRate": 62, "steps": 7500,
        "minutesAsleep": 432, "minutesFairlyActive": 20, "minutesVeryActive": 15,
        "breathingRate": 15.0, "hrv": 42.0,
    }},
    {"dateTime": "2024-03-02", "value": {
        "restingHeartRate": 65, "steps": 8000,
        "minutesAsleep": 408, "minutesFairlyActive": 25, "minutesVeryActive": 15,
    }},
]

GARMIN_DATA = [
    {"calendarDate": "2024-03-01", "restingHeartRate": 62, "totalSteps": 7500,
     "sleepingSeconds": 25920, "moderateIntensityMinutes": 20, "vigorousIntensityMinutes": 15,
     "averageRespirationValue": 15.0},
    {"calendarDate": "2024-03-02", "restingHeartRate": 65, "totalSteps": 8000,
     "sleepingSeconds": 24480, "moderateIntensityMinutes": 25, "vigorousIntensityMinutes": 15},
]

APPLE_DATA = [
    {"date": "2024-03-01", "restingHeartRate": 62, "steps": 7500,
     "sleepHours": 7.2, "exerciseMinutes": 35, "hrv": 42, "respiratoryRate": 15},
    {"date": "2024-03-02", "restingHeartRate": 65, "steps": 8000,
     "sleepHours": 6.8, "exerciseMinutes": 40},
]

WITHINGS_DATA = [
    {"date": "2024-03-01", "heart_rate_resting": 62, "steps": 7500, "sleep_duration": 25920},
    {"date": "2024-03-02", "heart_rate_resting": 65, "steps": 8000, "sleep_duration": 24480},
]


# ---------------------------------------------------------------------------
# Tests: TapiaAdapter
# ---------------------------------------------------------------------------

class TestTapiaAdapter:
    def setup_method(self): self.a = TapiaAdapter()

    def test_can_handle_valid(self):    assert self.a.can_handle(TAPIA_DATA)
    def test_cannot_handle_fitbit(self):assert not self.a.can_handle(FITBIT_DATA)
    def test_cannot_handle_empty(self): assert not self.a.can_handle([])

    def test_normalize_count(self):
        r = self.a.normalize(TAPIA_DATA)
        assert len(r) == 2

    def test_normalize_values(self):
        r = self.a.normalize(TAPIA_DATA)
        assert r[0].fecha == "2024-03-01"
        assert r[0].pulso_reposo_bpm_media == 62.0
        assert r[0].pasos == 7500.0
        assert r[0].sueno_asleep_horas == 7.2

    def test_normalize_skips_invalid(self):
        data = TAPIA_DATA + [{"sin_fecha": True}]
        r = self.a.normalize(data)
        assert len(r) == 2


# ---------------------------------------------------------------------------
# Tests: FitbitAdapter
# ---------------------------------------------------------------------------

class TestFitbitAdapter:
    def setup_method(self): self.a = FitbitAdapter()

    def test_can_handle_valid(self):    assert self.a.can_handle(FITBIT_DATA)
    def test_cannot_handle_tapia(self): assert not self.a.can_handle(TAPIA_DATA)

    def test_normalize_count(self):
        r = self.a.normalize(FITBIT_DATA)
        assert len(r) == 2

    def test_normalize_sleep_conversion(self):
        r = self.a.normalize(FITBIT_DATA)
        # 432 min / 60 = 7.2h
        assert r[0].sueno_asleep_horas == pytest.approx(7.2, 0.1)

    def test_normalize_exercise_sum(self):
        r = self.a.normalize(FITBIT_DATA)
        # fairly(20) + very(15) = 35
        assert r[0].min_ejercicio == 35.0

    def test_normalize_hr(self):
        r = self.a.normalize(FITBIT_DATA)
        assert r[0].pulso_reposo_bpm_media == 62.0

    def test_normalize_hrv(self):
        r = self.a.normalize(FITBIT_DATA)
        assert r[0].hrv_sdnn_ms_media == 42.0

    def test_missing_optional_fields(self):
        # Segundo registro no tiene hrv
        r = self.a.normalize(FITBIT_DATA)
        assert r[1].hrv_sdnn_ms_media is None


# ---------------------------------------------------------------------------
# Tests: GarminAdapter
# ---------------------------------------------------------------------------

class TestGarminAdapter:
    def setup_method(self): self.a = GarminAdapter()

    def test_can_handle_valid(self):    assert self.a.can_handle(GARMIN_DATA)
    def test_cannot_handle_tapia(self): assert not self.a.can_handle(TAPIA_DATA)

    def test_normalize_count(self):
        r = self.a.normalize(GARMIN_DATA)
        assert len(r) == 2

    def test_normalize_sleep_seconds(self):
        r = self.a.normalize(GARMIN_DATA)
        # 25920 sec / 3600 = 7.2h
        assert r[0].sueno_asleep_horas == pytest.approx(7.2, 0.1)

    def test_normalize_exercise(self):
        r = self.a.normalize(GARMIN_DATA)
        # mod(20) + vig(15) = 35
        assert r[0].min_ejercicio == 35.0

    def test_normalize_fecha(self):
        r = self.a.normalize(GARMIN_DATA)
        assert r[0].fecha == "2024-03-01"


# ---------------------------------------------------------------------------
# Tests: AppleHealthAdapter
# ---------------------------------------------------------------------------

class TestAppleHealthAdapter:
    def setup_method(self): self.a = AppleHealthAdapter()

    def test_can_handle_valid(self):    assert self.a.can_handle(APPLE_DATA)
    def test_cannot_handle_tapia(self): assert not self.a.can_handle(TAPIA_DATA)

    def test_normalize_count(self):
        r = self.a.normalize(APPLE_DATA)
        assert len(r) == 2

    def test_normalize_values(self):
        r = self.a.normalize(APPLE_DATA)
        assert r[0].pulso_reposo_bpm_media == 62.0
        assert r[0].sueno_asleep_horas     == 7.2
        assert r[0].hrv_sdnn_ms_media      == 42.0

    def test_fecha_truncated(self):
        data = [{"date": "2024-03-01T00:00:00", "restingHeartRate": 60, "steps": 5000}]
        r = self.a.normalize(data)
        assert r[0].fecha == "2024-03-01"


# ---------------------------------------------------------------------------
# Tests: WithingsAdapter
# ---------------------------------------------------------------------------

class TestWithingsAdapter:
    def setup_method(self): self.a = WithingsAdapter()

    def test_can_handle_valid(self):    assert self.a.can_handle(WITHINGS_DATA)
    def test_cannot_handle_tapia(self): assert not self.a.can_handle(TAPIA_DATA)

    def test_normalize_count(self):
        r = self.a.normalize(WITHINGS_DATA)
        assert len(r) == 2

    def test_normalize_sleep(self):
        r = self.a.normalize(WITHINGS_DATA)
        # 25920 sec / 3600 = 7.2h
        assert r[0].sueno_asleep_horas == pytest.approx(7.2, 0.1)

    def test_normalize_hr(self):
        r = self.a.normalize(WITHINGS_DATA)
        assert r[0].pulso_reposo_bpm_media == 62.0

    def test_api_format(self):
        api_data = {
            "status": 0,
            "body": {"series": [
                {"date": 1709251200, "heart_rate": {"resting": 62},
                 "steps": 7500, "sleep": {"total": 25920}}
            ]}
        }
        assert self.a.can_handle(api_data)
        r = self.a.normalize(api_data)
        assert len(r) == 1
        assert r[0].pulso_reposo_bpm_media == 62.0


# ---------------------------------------------------------------------------
# Tests: Detector automatico
# ---------------------------------------------------------------------------

class TestDetector:

    def test_detects_tapia(self):
        _, name = detect_and_normalize(TAPIA_DATA)
        assert name == "tapia"

    def test_detects_fitbit(self):
        _, name = detect_and_normalize(FITBIT_DATA)
        assert name == "fitbit"

    def test_detects_garmin(self):
        _, name = detect_and_normalize(GARMIN_DATA)
        assert name == "garmin"

    def test_detects_apple(self):
        _, name = detect_and_normalize(APPLE_DATA)
        assert name == "apple_health"

    def test_detects_withings(self):
        _, name = detect_and_normalize(WITHINGS_DATA)
        assert name == "withings"

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError, match="no reconocido"):
            detect_and_normalize([{"campo_raro": 1}])

    def test_normalized_records_have_fecha(self):
        records, _ = detect_and_normalize(FITBIT_DATA)
        assert all(r.fecha for r in records)

    def test_to_dicts_compatible_with_wearable_module(self):
        """Los dicts generados deben ser compatibles con core.wearable.summarize."""
        from tapia.wearables.detector import to_tapia_dicts
        from tapia.core.wearable import summarize
        records, _ = detect_and_normalize(TAPIA_DATA)
        dicts = to_tapia_dicts(records)
        summary = summarize(dicts)
        assert summary.days == 2
        assert summary.avg_resting_hr == pytest.approx(63.5, 0.1)

    def test_load_and_detect_from_bytes(self):
        raw = json.dumps(FITBIT_DATA).encode("utf-8")
        dicts, name = load_and_detect(raw)
        assert name == "fitbit"
        assert len(dicts) == 2
        assert "fecha" in dicts[0]

    def test_load_and_detect_invalid_json(self):
        with pytest.raises(ValueError, match="JSON valido"):
            load_and_detect(b"esto no es json")
