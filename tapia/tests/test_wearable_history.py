# -*- coding: utf-8 -*-
"""Tests del historial acumulativo de wearable en SQLite."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

import tapia.db.database as dbmod


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_wearable.db"
    monkeypatch.setattr(dbmod, "_DB_PATH", db_file)
    dbmod.init_db()
    return dbmod


def _make_records(n, start_offset=0, sleep=7.0, steps=6000, hr=65):
    today = date.today()
    return [
        {
            "fecha":                       (today - timedelta(days=i + start_offset)).isoformat(),
            "pulso_reposo_bpm_media":      hr,
            "pasos":                       steps,
            "min_ejercicio":               30,
            "sueno_asleep_horas":          sleep,
            "respiraciones_por_min_media": 15,
            "hrv_sdnn_ms_media":           40,
        }
        for i in range(n)
    ]


class TestPatients:

    def test_create_patient(self, tmp_db):
        pid = tmp_db.get_or_create_patient("Ana Garcia", 35, "F")
        assert isinstance(pid, int) and pid >= 1

    def test_same_name_returns_same_id(self, tmp_db):
        pid1 = tmp_db.get_or_create_patient("Carlos Lopez", 50, "M")
        pid2 = tmp_db.get_or_create_patient("Carlos Lopez", 50, "M")
        assert pid1 == pid2

    def test_case_insensitive_match(self, tmp_db):
        pid1 = tmp_db.get_or_create_patient("Maria Ruiz", 40, "F")
        pid2 = tmp_db.get_or_create_patient("maria ruiz", 40, "F")
        assert pid1 == pid2

    def test_different_names_different_ids(self, tmp_db):
        pid1 = tmp_db.get_or_create_patient("Paciente A", 30, "M")
        pid2 = tmp_db.get_or_create_patient("Paciente B", 30, "M")
        assert pid1 != pid2

    def test_list_patients(self, tmp_db):
        tmp_db.get_or_create_patient("Paciente 1", 30, "M")
        tmp_db.get_or_create_patient("Paciente 2", 40, "F")
        patients = tmp_db.list_patients()
        assert len(patients) == 2

    def test_patient_name_decrypted(self, tmp_db):
        tmp_db.get_or_create_patient("Juan Perez", 55, "M")
        patients = tmp_db.list_patients()
        names = [p["name"] for p in patients]
        assert "Juan Perez" in names


class TestIncrementalImport:

    def test_import_new_records(self, tmp_db):
        pid = tmp_db.get_or_create_patient("Test", 40, "M")
        result = tmp_db.import_wearable_records(pid, _make_records(10))
        assert result["inserted"] == 10
        assert result["skipped"]  == 0

    def test_no_duplicates_same_file(self, tmp_db):
        pid     = tmp_db.get_or_create_patient("Test", 40, "M")
        records = _make_records(10)
        tmp_db.import_wearable_records(pid, records)
        result = tmp_db.import_wearable_records(pid, records)
        assert result["inserted"] == 0
        assert result["skipped"]  == 10

    def test_incremental_adds_only_new(self, tmp_db):
        pid = tmp_db.get_or_create_patient("Test", 40, "M")
        # Primera importacion: dias 0-29
        tmp_db.import_wearable_records(pid, _make_records(30, start_offset=0))
        # Segunda importacion: dias 0-59 (30 ya existen, 30 son nuevos)
        result = tmp_db.import_wearable_records(pid, _make_records(60, start_offset=0))
        assert result["inserted"] == 30
        assert result["skipped"]  == 30

    def test_total_days_after_two_imports(self, tmp_db):
        pid = tmp_db.get_or_create_patient("Test", 40, "M")
        tmp_db.import_wearable_records(pid, _make_records(30, start_offset=0))
        tmp_db.import_wearable_records(pid, _make_records(30, start_offset=30))
        history = tmp_db.get_wearable_history(pid)
        assert len(history) == 60

    def test_records_compatible_with_summarize(self, tmp_db):
        from tapia.core.wearable import summarize, filter_by_days
        pid = tmp_db.get_or_create_patient("Test", 40, "M")
        tmp_db.import_wearable_records(pid, _make_records(35, sleep=7.0, steps=6000, hr=65))
        history = tmp_db.get_wearable_history(pid)
        w30 = summarize(filter_by_days(history, 30))
        assert w30.days == 31
        assert w30.avg_sleep_h == 7.0
        assert w30.avg_resting_hr == 65.0

    def test_source_stored(self, tmp_db):
        pid = tmp_db.get_or_create_patient("Test", 40, "M")
        tmp_db.import_wearable_records(pid, _make_records(5), source="fitbit")
        stats = tmp_db.get_wearable_stats(pid)
        assert stats["total_days"] == 5

    def test_import_skips_missing_fecha(self, tmp_db):
        pid     = tmp_db.get_or_create_patient("Test", 40, "M")
        records = _make_records(5) + [{"pulso_reposo_bpm_media": 70}]  # sin fecha
        result  = tmp_db.import_wearable_records(pid, records)
        assert result["inserted"] == 5
        assert result["skipped"]  == 1


class TestWearableHistory:

    def test_get_all_history(self, tmp_db):
        pid = tmp_db.get_or_create_patient("Test", 40, "M")
        tmp_db.import_wearable_records(pid, _make_records(40))
        history = tmp_db.get_wearable_history(pid)
        assert len(history) == 40

    def test_get_history_with_days_filter(self, tmp_db):
        pid = tmp_db.get_or_create_patient("Test", 40, "M")
        tmp_db.import_wearable_records(pid, _make_records(60))
        history = tmp_db.get_wearable_history(pid, days=30)
        assert len(history) <= 31

    def test_history_dict_keys(self, tmp_db):
        pid = tmp_db.get_or_create_patient("Test", 40, "M")
        tmp_db.import_wearable_records(pid, _make_records(5))
        history = tmp_db.get_wearable_history(pid)
        required_keys = {"fecha", "pulso_reposo_bpm_media", "pasos",
                         "sueno_asleep_horas", "min_ejercicio"}
        assert required_keys.issubset(set(history[0].keys()))

    def test_stats_empty(self, tmp_db):
        pid   = tmp_db.get_or_create_patient("Test", 40, "M")
        stats = tmp_db.get_wearable_stats(pid)
        assert stats["total_days"] == 0
        assert stats["first_date"] == "N/D"

    def test_stats_populated(self, tmp_db):
        pid = tmp_db.get_or_create_patient("Test", 40, "M")
        tmp_db.import_wearable_records(pid, _make_records(30))
        stats = tmp_db.get_wearable_stats(pid)
        assert stats["total_days"] == 30
        assert stats["first_date"] != "N/D"
        assert stats["last_date"]  != "N/D"


class TestDeletePatient:

    def test_delete_removes_all_data(self, tmp_db):
        pid = tmp_db.get_or_create_patient("A Borrar", 40, "M")
        tmp_db.import_wearable_records(pid, _make_records(10))
        tmp_db.save_triage(
            patient_name="A Borrar", patient_age=40, patient_sex="M",
            local_bucket="2_semanas", local_score=3, final_bucket="2_semanas",
            ai_bucket="2_semanas", ai_model="", rec="Medico", spec="-",
            wearable_days=10, report_text="Informe.", patient_id=pid,
        )
        result = tmp_db.delete_patient_data(pid)
        assert result["triages"]       == 1
        assert result["wearable_days"] == 10
        assert tmp_db.get_wearable_history(pid) == []
