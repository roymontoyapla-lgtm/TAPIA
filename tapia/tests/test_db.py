"""
Tests de la capa de persistencia (db.database) y cifrado (db.crypto).
Usan una base de datos temporal en cada test para total aislamiento.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Cifrado
# ---------------------------------------------------------------------------

class TestCrypto:

    def test_encrypt_decrypt_roundtrip(self):
        from tapia.db.crypto import decrypt, encrypt
        original = "María López García"
        token    = encrypt(original)
        result   = decrypt(token)
        assert result == original

    def test_encrypted_differs_from_plaintext(self):
        from tapia.db.crypto import encrypt
        text  = "texto sensible"
        token = encrypt(text)
        assert token != text

    def test_each_encrypt_produces_unique_token(self):
        """Fernet usa IV aleatorio → cada cifrado produce un token distinto."""
        from tapia.db.crypto import encrypt
        text = "mismo texto"
        assert encrypt(text) != encrypt(text)

    def test_decrypt_wrong_token_raises(self):
        from tapia.db.crypto import decrypt
        with pytest.raises((ValueError, Exception)):
            decrypt("esto_no_es_un_token_valido")

    def test_empty_string(self):
        from tapia.db.crypto import decrypt, encrypt
        assert decrypt(encrypt("")) == ""

    def test_unicode_characters(self):
        from tapia.db.crypto import decrypt, encrypt
        text = "Paciente: José Ñoño 心电图 αβγ"
        assert decrypt(encrypt(text)) == text

    def test_long_text(self):
        from tapia.db.crypto import decrypt, encrypt
        text = "A" * 10_000
        assert decrypt(encrypt(text)) == text

    def test_is_available_returns_bool(self):
        from tapia.db.crypto import is_available
        assert isinstance(is_available(), bool)

    def test_key_path_returns_string(self):
        from tapia.db.crypto import key_path
        assert isinstance(key_path(), str)
        assert key_path().endswith(".tapia_key")


# ---------------------------------------------------------------------------
# Base de datos (con BD temporal por test)
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """
    Parchea _DB_PATH para que cada test use una BD temporal aislada.
    También inicializa el esquema.
    """
    db_file = tmp_path / "test_tapia.db"
    import tapia.db.database as database_module
    monkeypatch.setattr(database_module, "_DB_PATH", db_file)
    database_module.init_db()
    return database_module


def _save_sample(db_mod, name="Ana García", age=35, sex="F",
                 local_bucket="2_semanas", local_score=3,
                 final_bucket="2_semanas", ai_bucket="2_semanas"):
    return db_mod.save_triage(
        patient_name=name, patient_age=age, patient_sex=sex,
        local_bucket=local_bucket, local_score=local_score,
        final_bucket=final_bucket, ai_bucket=ai_bucket,
        ai_model="gpt-4o-mini", rec="Médico de cabecera", spec="-",
        wearable_days=30, report_text=f"Informe de {name}.",
    )


class TestDatabase:

    def test_init_db_creates_table(self, tmp_db, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test_tapia.db"))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        conn.close()
        assert "triages" in tables

    def test_init_db_idempotent(self, tmp_db):
        """Llamar init_db() varias veces no falla."""
        tmp_db.init_db()
        tmp_db.init_db()

    def test_save_returns_id(self, tmp_db):
        row_id = _save_sample(tmp_db)
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_save_and_retrieve(self, tmp_db):
        _save_sample(tmp_db, name="Carlos Ruiz", age=52)
        rows = tmp_db.get_all()
        assert len(rows) == 1
        assert rows[0].patient_name == "Carlos Ruiz"
        assert rows[0].patient_age  == 52

    def test_report_text_roundtrip(self, tmp_db):
        """El texto del informe se cifra y descifra correctamente."""
        report = "INFORME RESUMEN\nPrioridad: URGENTE\nNombre: Test."
        _save_sample(tmp_db, name="Test Paciente")
        # Guardamos directamente con el texto conocido
        tmp_db.save_triage(
            patient_name="Test", patient_age=40, patient_sex="M",
            local_bucket="urgente", local_score=10, final_bucket="urgente",
            ai_bucket="urgente", ai_model="gpt-4o-mini",
            rec="Médico", spec="-", wearable_days=28, report_text=report,
        )
        rows = tmp_db.get_all()
        saved = next(r for r in rows if r.patient_name == "Test")
        assert saved.report_text == report

    def test_name_encrypted_in_raw_db(self, tmp_db, tmp_path):
        """El nombre NO debe aparecer en claro en el fichero SQLite."""
        _save_sample(tmp_db, name="NombreSecreto")
        conn = sqlite3.connect(str(tmp_path / "test_tapia.db"))
        raw = conn.execute("SELECT patient_name FROM triages").fetchone()[0]
        conn.close()
        assert "NombreSecreto" not in raw

    def test_get_all_order_desc(self, tmp_db):
        """get_all() devuelve los más recientes primero."""
        _save_sample(tmp_db, name="Primero")
        _save_sample(tmp_db, name="Segundo")
        rows = tmp_db.get_all()
        assert rows[0].patient_name == "Segundo"
        assert rows[1].patient_name == "Primero"

    def test_get_all_limit(self, tmp_db):
        for i in range(10):
            _save_sample(tmp_db, name=f"Paciente {i}")
        rows = tmp_db.get_all(limit=5)
        assert len(rows) == 5

    def test_get_by_id_found(self, tmp_db):
        rid = _save_sample(tmp_db, name="Búsqueda por ID")
        row = tmp_db.get_by_id(rid)
        assert row is not None
        assert row.patient_name == "Búsqueda por ID"
        assert row.id == rid

    def test_get_by_id_not_found(self, tmp_db):
        assert tmp_db.get_by_id(99999) is None

    def test_search_by_name(self, tmp_db):
        _save_sample(tmp_db, name="Juan Pérez")
        _save_sample(tmp_db, name="Ana García")
        results = tmp_db.search_by_name("pérez")
        assert len(results) == 1
        assert results[0].patient_name == "Juan Pérez"

    def test_search_case_insensitive(self, tmp_db):
        _save_sample(tmp_db, name="María López")
        assert len(tmp_db.search_by_name("MARÍA")) == 1
        assert len(tmp_db.search_by_name("maría")) == 1
        assert len(tmp_db.search_by_name("ría")) == 1

    def test_search_no_results(self, tmp_db):
        _save_sample(tmp_db, name="Carlos")
        assert tmp_db.search_by_name("zzz_no_existe") == []

    def test_get_stats_empty(self, tmp_db):
        stats = tmp_db.get_stats()
        assert stats["total"] == 0
        assert stats["avg_score"] == 0.0

    def test_get_stats_populated(self, tmp_db):
        _save_sample(tmp_db, final_bucket="urgente",   local_score=10)
        _save_sample(tmp_db, final_bucket="urgente",   local_score=12)
        _save_sample(tmp_db, final_bucket="7_dias",    local_score=6)
        _save_sample(tmp_db, final_bucket="2_semanas", local_score=2)
        stats = tmp_db.get_stats()
        assert stats["total"]     == 4
        assert stats["urgente"]   == 2
        assert stats["7_dias"]    == 1
        assert stats["2_semanas"] == 1
        assert stats["avg_score"] == pytest.approx(7.5, 0.1)

    def test_delete_triage(self, tmp_db):
        rid = _save_sample(tmp_db, name="A eliminar")
        assert tmp_db.delete_triage(rid) is True
        assert tmp_db.get_by_id(rid) is None

    def test_delete_nonexistent(self, tmp_db):
        assert tmp_db.delete_triage(99999) is False

    def test_delete_all(self, tmp_db):
        for i in range(5):
            _save_sample(tmp_db, name=f"P{i}")
        n = tmp_db.delete_all()
        assert n == 5
        assert tmp_db.get_stats()["total"] == 0

    def test_multiple_saves_independent(self, tmp_db):
        """Cada save() es independiente y no corrompe registros anteriores."""
        ids = [_save_sample(tmp_db, name=f"Paciente {i}", local_score=i) for i in range(5)]
        for i, rid in enumerate(ids):
            row = tmp_db.get_by_id(rid)
            assert row.patient_name == f"Paciente {i}"
            assert row.local_score  == i

    def test_db_path_returns_string(self, tmp_db):
        assert isinstance(tmp_db.db_path(), str)
