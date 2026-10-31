"""Tests de creacion segura del admin inicial y bloqueo de la clave antigua."""

import sqlite3

import pytest

from tapia.auth import auth

CLAVE_SINTETICA = "clave-sintetica-de-prueba-123"


@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    """Apunta auth a una base temporal para no tocar tapia_history.db."""
    monkeypatch.setattr(auth, "_DB_PATH", tmp_path / "auth_test.db")
    monkeypatch.delenv(auth.ADMIN_PASSWORD_ENV, raising=False)
    return tmp_path / "auth_test.db"


def _crear_usuario_hash_antiguo(db_path, username, password, role="admin"):
    """Simula un usuario de una version anterior (hash SHA-256 de una vuelta)."""
    auth.init_auth_tables()  # sin variable: crea las tablas, no el admin
    salt = "salt-sintetico"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, role, active, created_at) "
            "VALUES (?,?,?,?,1,'2026-01-01T00:00:00')",
            (username, auth._legacy_hash(password, salt), salt, role),
        )


def _crear_admin_con_clave_antigua(db_path):
    """Simula una base de una version anterior, con el admin y la clave publicada."""
    _crear_usuario_hash_antiguo(db_path, "admin", auth._LEGACY_DEFAULT_PASSWORD)


def _hash_guardado(db_path, username):
    with sqlite3.connect(str(db_path)) as conn:
        return conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()[0]


class TestAdminInicial:
    def test_sin_variable_no_crea_admin(self, db_temporal):
        auth.init_auth_tables()
        assert auth.list_users() == []
        assert auth.admin_setup_pending()

    def test_con_variable_crea_admin(self, db_temporal, monkeypatch):
        monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, CLAVE_SINTETICA)
        auth.init_auth_tables()
        assert not auth.admin_setup_pending()
        user = auth.login("admin", CLAVE_SINTETICA)
        assert user is not None and user["role"] == "admin"

    def test_clave_corta_se_rechaza(self, db_temporal, monkeypatch):
        monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, "corta")
        auth.init_auth_tables()
        assert auth.list_users() == []

    def test_clave_no_aparece_en_el_log(self, db_temporal, monkeypatch, caplog):
        monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, CLAVE_SINTETICA)
        with caplog.at_level("DEBUG"):
            auth.init_auth_tables()
        assert CLAVE_SINTETICA not in caplog.text
        assert auth._LEGACY_DEFAULT_PASSWORD not in caplog.text

    def test_es_idempotente(self, db_temporal, monkeypatch):
        monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, CLAVE_SINTETICA)
        auth.init_auth_tables()
        auth.init_auth_tables()
        assert len(auth.list_users()) == 1


class TestClaveAntigua:
    def test_clave_antigua_no_da_acceso(self, db_temporal):
        _crear_admin_con_clave_antigua(db_temporal)
        assert auth.login("admin", auth._LEGACY_DEFAULT_PASSWORD) is None

    def test_clave_antigua_se_sustituye(self, db_temporal, monkeypatch):
        _crear_admin_con_clave_antigua(db_temporal)
        monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, CLAVE_SINTETICA)
        auth.init_auth_tables()
        assert auth.login("admin", CLAVE_SINTETICA) is not None
        assert len(auth.list_users()) == 1

    def test_no_pisa_una_clave_ya_cambiada(self, db_temporal, monkeypatch):
        monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, CLAVE_SINTETICA)
        auth.init_auth_tables()
        admin_id = auth.list_users()[0]["id"]
        auth.change_password(admin_id, "otra-clave-sintetica-456")
        auth.init_auth_tables()
        assert auth.login("admin", "otra-clave-sintetica-456") is not None
        assert auth.login("admin", CLAVE_SINTETICA) is None


class TestHashPBKDF2:
    def test_usuarios_nuevos_usan_pbkdf2(self, db_temporal):
        auth.init_auth_tables()
        auth.create_user("medico1", CLAVE_SINTETICA, "medico")
        guardado = _hash_guardado(db_temporal, "medico1")
        assert guardado.startswith(f"pbkdf2_sha256${auth.PBKDF2_ITERATIONS}$")
        assert auth.login("medico1", CLAVE_SINTETICA) is not None
        assert auth.login("medico1", "clave-equivocada-000") is None

    def test_hash_antiguo_sigue_entrando_y_se_migra(self, db_temporal):
        _crear_usuario_hash_antiguo(db_temporal, "medico1", CLAVE_SINTETICA, "medico")
        assert auth.login("medico1", CLAVE_SINTETICA) is not None
        assert _hash_guardado(db_temporal, "medico1").startswith("pbkdf2_sha256$")
        assert auth.login("medico1", CLAVE_SINTETICA) is not None

    def test_login_fallido_no_migra(self, db_temporal):
        _crear_usuario_hash_antiguo(db_temporal, "medico1", CLAVE_SINTETICA, "medico")
        assert auth.login("medico1", "clave-equivocada-000") is None
        assert not _hash_guardado(db_temporal, "medico1").startswith("pbkdf2_sha256$")

    def test_iteraciones_antiguas_se_actualizan(self, db_temporal, monkeypatch):
        auth.init_auth_tables()
        monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1000)
        auth.create_user("medico1", CLAVE_SINTETICA, "medico")
        monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 2000)
        assert auth.login("medico1", CLAVE_SINTETICA) is not None
        assert _hash_guardado(db_temporal, "medico1").startswith("pbkdf2_sha256$2000$")

    def test_hash_corrupto_no_da_acceso(self):
        assert not auth._verify_password("x", "salt", "pbkdf2_sha256$roto")
