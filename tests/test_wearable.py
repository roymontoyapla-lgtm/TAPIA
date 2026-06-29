"""Tests del módulo core.wearable."""

import json
from datetime import date, timedelta

import pytest

from tapia.core.wearable import (
    count_days,
    date_range_str,
    filter_by_days,
    load_json,
    mean_or_none,
    parse_date,
    summarize,
    to_float,
)


# ---------------------------------------------------------------------------
# Utilidades básicas
# ---------------------------------------------------------------------------

class TestToFloat:
    def test_int(self):      assert to_float(5)   == 5.0
    def test_float(self):    assert to_float(3.14) == 3.14
    def test_string(self):   assert to_float("5") is None
    def test_none(self):     assert to_float(None) is None


class TestMeanOrNone:
    def test_normal(self):    assert mean_or_none([1.0, 2.0, 3.0]) == 2.0
    def test_empty(self):     assert mean_or_none([]) is None
    def test_all_none(self):  assert mean_or_none([None, None]) is None
    def test_mixed(self):     assert mean_or_none([None, 4.0, None, 6.0]) == 5.0


class TestCountDays:
    def test_basic(self):
        assert count_days([5.0, 8.0, 3.0, 6.0], lambda v: v < 6) == 2

    def test_all_pass(self):
        assert count_days([1.0, 2.0], lambda v: v < 10) == 2

    def test_none_ignored(self):
        assert count_days([None, 5.0, None], lambda v: v < 6) == 1


class TestParseDate:
    def test_valid(self):
        d = parse_date("2024-03-15")
        assert d.year == 2024 and d.month == 3 and d.day == 15

    def test_invalid_format(self): assert parse_date("15/03/2024") is None
    def test_none(self):           assert parse_date(None) is None
    def test_number(self):         assert parse_date(20240315) is None


# ---------------------------------------------------------------------------
# Filtrado y rango
# ---------------------------------------------------------------------------

class TestFilterByDays:
    def _make_records(self, n):
        today = date.today()
        return [{"fecha": (today - timedelta(days=i)).isoformat()} for i in range(n)]

    def test_keeps_recent(self):
        records = self._make_records(60)
        filtered = filter_by_days(records, 30)
        assert len(filtered) == 31  # hoy + 30 días atrás

    def test_empty_input(self):
        assert filter_by_days([], 30) == []

    def test_no_date_field(self):
        assert filter_by_days([{"pasos": 5000}], 30) == []


class TestDateRangeStr:
    def test_normal(self):
        records = [{"fecha": "2024-01-01"}, {"fecha": "2024-01-15"}]
        result = date_range_str(records)
        assert "2024-01-01" in result and "2024-01-15" in result

    def test_empty(self):
        assert date_range_str([]) == "N/D"


# ---------------------------------------------------------------------------
# Carga de JSON
# ---------------------------------------------------------------------------

class TestLoadJson:
    def test_valid(self, tmp_path):
        p = tmp_path / "w.json"
        p.write_text(json.dumps([{"fecha": "2024-01-01", "pasos": 5000}]))
        records = load_json(str(p))
        assert len(records) == 1

    def test_not_a_list(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"fecha": "2024-01-01"}))
        with pytest.raises(ValueError, match="lista"):
            load_json(str(p))

    def test_filters_non_dicts(self, tmp_path):
        p = tmp_path / "mixed.json"
        p.write_text(json.dumps([{"pasos": 1000}, "texto", 42]))
        records = load_json(str(p))
        assert len(records) == 1


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------

class TestSummarize:
    def _records(self, n=10, sleep=7.0, steps=6000, hr=65):
        today = date.today()
        return [
            {
                "fecha":                    (today - timedelta(days=i)).isoformat(),
                "sueno_asleep_horas":       sleep,
                "pasos":                    steps,
                "pulso_reposo_bpm_media":   hr,
                "min_ejercicio":            30,
                "respiraciones_por_min_media": 15,
                "hrv_sdnn_ms_media":        40,
            }
            for i in range(n)
        ]

    def test_days_count(self):
        s = summarize(self._records(10))
        assert s.days == 10

    def test_avg_sleep(self):
        s = summarize(self._records(10, sleep=6.0))
        assert s.avg_sleep_h == 6.0

    def test_low_sleep_days(self):
        records = self._records(10, sleep=5.0)  # todos < 6h
        s = summarize(records)
        assert s.low_sleep_days == 10

    def test_no_low_sleep(self):
        s = summarize(self._records(10, sleep=7.5))
        assert s.low_sleep_days == 0

    def test_high_hr_days(self):
        s = summarize(self._records(5, hr=95))
        assert s.high_resting_hr_days == 5

    def test_empty(self):
        s = summarize([])
        assert s.days == 0
        assert s.avg_sleep_h is None
