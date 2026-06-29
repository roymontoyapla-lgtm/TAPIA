# -*- coding: utf-8 -*-
"""Tests del modulo de cumplimiento: auditoria y RGPD."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import tapia.compliance.audit as audit_mod
import tapia.compliance.gdpr  as gdpr_mod
import tapia.db.database      as db_mod


@pytest.fixture
def tmp_compliance(tmp_path, monkeypatch):
    """BD temporal compartida por audit, gdpr y database."""
    db_file = tmp_path / "test_compliance.db"
    monkeypatch.setattr(audit_mod, "_DB_PATH", db_file)
    monkeypatch.setattr(gdpr_mod,  "_DB_PATH", db_file)
    monkeypatch.setattr(db_mod,    "_DB_PATH", db_file)
    db_mod.init_db()
    audit_mod.init_audit_table()
    gdpr_mod.init_consent_table()
    return {"audit": audit_mod, "gdpr": gdpr_mod, "db": db_mod}


def _create_patient(m, name="Test Paciente", age=40, sex="M"):
    return m["db"].get_or_create_patient(name, age, sex)


def _save_triage(m, pid, name="Test Paciente"):
    return m["db"].save_triage(
        patient_name=name, patient_age=40, patient_sex="M",
        local_bucket="2_semanas", local_score=3, final_bucket="2_semanas",
        ai_bucket="2_semanas", ai_model="claude-sonnet-4-6",
        rec="Medico", spec="-", wearable_days=30,
        report_text="Informe de prueba.", patient_id=pid,
    )


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------

class TestAudit:

    def test_log_inserts_entry(self, tmp_compliance):
        a = tmp_compliance["audit"]
        a.log(a.Action.TRIAGE_RUN, patient_id=1, final_bucket="urgente",
              local_score=10, ai_model="claude-sonnet-4-6")
        entries = a.get_log()
        assert len(entries) == 1
        assert entries[0]["action"] == a.Action.TRIAGE_RUN

    def test_log_stores_algorithm_version(self, tmp_compliance):
        a = tmp_compliance["audit"]
        a.log(a.Action.TRIAGE_RUN)
        entries = a.get_log()
        assert entries[0]["algorithm_version"] == a.ALGORITHM_VERSION

    def test_log_never_raises(self, tmp_compliance):
        """El log no debe lanzar excepcion aunque falle internamente."""
        a = tmp_compliance["audit"]
        a.log("accion_invalida", details="test")  # no debe explotar

    def test_multiple_actions(self, tmp_compliance):
        a = tmp_compliance["audit"]
        a.log(a.Action.TRIAGE_RUN,      patient_id=1)
        a.log(a.Action.WEARABLE_IMPORT, patient_id=1, details="10 dias")
        a.log(a.Action.CONSENT_GRANTED, patient_id=1)
        entries = a.get_log()
        assert len(entries) == 3

    def test_filter_by_action(self, tmp_compliance):
        a = tmp_compliance["audit"]
        a.log(a.Action.TRIAGE_RUN)
        a.log(a.Action.WEARABLE_IMPORT)
        a.log(a.Action.TRIAGE_RUN)
        filtered = a.get_log(action_filter=a.Action.TRIAGE_RUN)
        assert len(filtered) == 2
        assert all(e["action"] == a.Action.TRIAGE_RUN for e in filtered)

    def test_filter_by_patient(self, tmp_compliance):
        a = tmp_compliance["audit"]
        a.log(a.Action.TRIAGE_RUN, patient_id=1)
        a.log(a.Action.TRIAGE_RUN, patient_id=2)
        a.log(a.Action.TRIAGE_RUN, patient_id=1)
        filtered = a.get_log(patient_id_filter=1)
        assert len(filtered) == 2

    def test_stats_empty(self, tmp_compliance):
        stats = tmp_compliance["audit"].get_stats()
        assert stats["total"] == 0

    def test_stats_populated(self, tmp_compliance):
        a = tmp_compliance["audit"]
        a.log(a.Action.TRIAGE_RUN)
        a.log(a.Action.WEARABLE_IMPORT)
        stats = a.get_stats()
        assert stats["total"] == 2
        assert a.Action.TRIAGE_RUN in stats["by_action"]

    def test_order_desc(self, tmp_compliance):
        a = tmp_compliance["audit"]
        a.log(a.Action.TRIAGE_RUN,   details="primero")
        a.log(a.Action.CONSENT_GRANTED, details="segundo")
        entries = a.get_log()
        assert entries[0]["details"] == "segundo"


# ---------------------------------------------------------------------------
# RGPD: consentimiento
# ---------------------------------------------------------------------------

class TestConsent:

    def test_record_consent_granted(self, tmp_compliance):
        g = tmp_compliance["gdpr"]
        pid = _create_patient(tmp_compliance)
        g.record_consent(pid, granted=True)
        assert g.has_valid_consent(pid) is True

    def test_record_consent_revoked(self, tmp_compliance):
        g = tmp_compliance["gdpr"]
        pid = _create_patient(tmp_compliance)
        g.record_consent(pid, granted=True)
        g.record_consent(pid, granted=False)
        assert g.has_valid_consent(pid) is False

    def test_no_consent_record(self, tmp_compliance):
        g = tmp_compliance["gdpr"]
        pid = _create_patient(tmp_compliance)
        assert g.has_valid_consent(pid) is False

    def test_consent_status_fields(self, tmp_compliance):
        g = tmp_compliance["gdpr"]
        pid = _create_patient(tmp_compliance)
        g.record_consent(pid, granted=True, notes="Verbal en consulta")
        status = g.get_consent_status(pid)
        assert status is not None
        assert status["granted"] == 1
        assert "timestamp" in status

    def test_consent_logs_audit(self, tmp_compliance):
        g = tmp_compliance["gdpr"]
        a = tmp_compliance["audit"]
        pid = _create_patient(tmp_compliance)
        g.record_consent(pid, granted=True)
        entries = a.get_log(action_filter=a.Action.CONSENT_GRANTED)
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# RGPD: exportacion de datos
# ---------------------------------------------------------------------------

class TestDataExport:

    def test_export_returns_valid_json(self, tmp_compliance):
        g   = tmp_compliance["gdpr"]
        pid = _create_patient(tmp_compliance)
        _save_triage(tmp_compliance, pid)
        json_str = g.export_patient_data(pid, "Test Paciente")
        data = json.loads(json_str)
        assert "tapia_export" in data

    def test_export_contains_patient_info(self, tmp_compliance):
        g   = tmp_compliance["gdpr"]
        pid = _create_patient(tmp_compliance, name="Juan Perez")
        json_str = g.export_patient_data(pid, "Juan Perez")
        data = json.loads(json_str)
        assert data["tapia_export"]["patient"]["name"] == "Juan Perez"

    def test_export_contains_triages(self, tmp_compliance):
        g   = tmp_compliance["gdpr"]
        pid = _create_patient(tmp_compliance)
        _save_triage(tmp_compliance, pid)
        _save_triage(tmp_compliance, pid)
        json_str = g.export_patient_data(pid, "Test")
        data = json.loads(json_str)
        assert len(data["tapia_export"]["triages"]) == 2

    def test_export_logs_audit(self, tmp_compliance):
        g = tmp_compliance["gdpr"]
        a = tmp_compliance["audit"]
        pid = _create_patient(tmp_compliance)
        g.export_patient_data(pid, "Test")
        entries = a.get_log(action_filter=a.Action.DATA_EXPORTED)
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# RGPD: derecho al olvido
# ---------------------------------------------------------------------------

class TestRightToErasure:

    def test_erase_removes_all_data(self, tmp_compliance):
        g   = tmp_compliance["gdpr"]
        m   = tmp_compliance
        pid = _create_patient(m)
        _save_triage(m, pid)
        m["db"].import_wearable_records(
            pid,
            [{"fecha": "2024-01-01", "pulso_reposo_bpm_media": 65,
              "pasos": 7000, "min_ejercicio": 30, "sueno_asleep_horas": 7.0,
              "respiraciones_por_min_media": 15, "hrv_sdnn_ms_media": 40}]
        )
        g.record_consent(pid, granted=True)
        result = g.erase_patient(pid, "Test Paciente")
        assert result["triajes"]       == 1
        assert result["wearable_days"] == 1
        assert result["consentimientos"] == 1

    def test_erase_logs_anonymously(self, tmp_compliance):
        """El borrado debe quedar en auditoria pero sin patient_id."""
        g   = tmp_compliance["gdpr"]
        a   = tmp_compliance["audit"]
        pid = _create_patient(tmp_compliance)
        g.erase_patient(pid, "Test")
        entries = a.get_log(action_filter=a.Action.PATIENT_DELETED)
        assert len(entries) == 1
        assert entries[0]["patient_id"] is None  # anonimizado

    def test_erase_patient_no_longer_retrievable(self, tmp_compliance):
        g   = tmp_compliance["gdpr"]
        m   = tmp_compliance
        pid = _create_patient(m)
        g.erase_patient(pid, "Test")
        patients = m["db"].list_patients()
        assert all(p["id"] != pid for p in patients)


# ---------------------------------------------------------------------------
# Inventario de datos
# ---------------------------------------------------------------------------

class TestDataInventory:

    def test_inventory_empty_patient(self, tmp_compliance):
        g   = tmp_compliance["gdpr"]
        pid = _create_patient(tmp_compliance)
        inv = g.data_inventory(pid)
        assert inv["triajes"]       == 0
        assert inv["dias_wearable"] == 0
        assert inv["datos_cifrados"] is True

    def test_inventory_populated(self, tmp_compliance):
        g = tmp_compliance["gdpr"]
        m = tmp_compliance
        pid = _create_patient(m)
        _save_triage(m, pid)
        m["db"].import_wearable_records(
            pid,
            [{"fecha": "2024-01-01", "pulso_reposo_bpm_media": 65,
              "pasos": 7000, "min_ejercicio": 30, "sueno_asleep_horas": 7.0,
              "respiraciones_por_min_media": 15, "hrv_sdnn_ms_media": 40}]
        )
        inv = g.data_inventory(pid)
        assert inv["triajes"]       == 1
        assert inv["dias_wearable"] == 1
        assert inv["wearable_desde"] == "2024-01-01"
