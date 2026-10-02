# -*- coding: utf-8 -*-
"""
Tests del alta del usuario admin.

El repositorio es publico: una clave por defecto escrita en el codigo
equivale a no tener clave. Aqui se fija que ya no exista ninguna.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def auth(tmp_path, monkeypatch):
    """Modulo de autenticacion sobre una base de datos temporal."""
    import tapia.auth.auth as auth_mod
    monkeypatch.setattr(auth_mod, "_DB_PATH", tmp_path / "auth.db")
    monkeypatch.delenv("TAPIA_ADMIN_PASSWORD", raising=False)
    return auth_mod


class TestAltaDelAdmin:

    def test_no_queda_ninguna_clave_fija_en_el_codigo(self, auth):
        """La clave antigua ya no debe servir para entrar en una base nueva."""
        auth.init_auth_tables()
        assert auth.login("admin", auth.LEGACY_DEFAULT_PASSWORD) is None

    def test_usa_la_clave_de_la_variable_de_entorno(self, auth, monkeypatch):
        monkeypatch.setenv("TAPIA_ADMIN_PASSWORD", "Una-Clave-Larga-99")
        auth.init_auth_tables()
        usuario = auth.login("admin", "Una-Clave-Larga-99")
        assert usuario is not None
        assert usuario["role"] == "admin"

    def test_sin_variable_genera_una_aleatoria_y_la_registra(self, auth, caplog):
        with caplog.at_level("WARNING"):
            auth.init_auth_tables()
        mensaje = caplog.text
        assert "clave" in mensaje.lower()

        # La clave del log es la que abre la sesion
        clave = [l.strip() for l in mensaje.splitlines() if "clave  :" in l][0]
        clave = clave.split("clave  :", 1)[1].strip()
        assert len(clave) >= 12
        assert auth.login("admin", clave) is not None

    def test_dos_instalaciones_no_comparten_clave(self, tmp_path, monkeypatch, caplog):
        import tapia.auth.auth as auth_mod

        claves = []
        for i in (1, 2):
            monkeypatch.setattr(auth_mod, "_DB_PATH", tmp_path / f"inst{i}.db")
            monkeypatch.delenv("TAPIA_ADMIN_PASSWORD", raising=False)
            caplog.clear()
            with caplog.at_level("WARNING"):
                auth_mod.init_auth_tables()
            linea = [l for l in caplog.text.splitlines() if "clave  :" in l][0]
            claves.append(linea.split("clave  :", 1)[1].strip())

        assert claves[0] != claves[1]

    def test_no_se_vuelve_a_crear_si_ya_hay_usuarios(self, auth):
        auth.init_auth_tables()
        auth.create_user("medico1", "Otra-Clave-123", "medico")
        antes = len(auth.list_users())
        auth.init_auth_tables()
        assert len(auth.list_users()) == antes


class TestAvisoDeClaveAntigua:
    """Cambiar el codigo no cambia las bases ya creadas: hay que avisar."""

    def test_detecta_la_clave_antigua(self, auth):
        auth.init_auth_tables()
        usuario = auth.list_users()[0]
        auth.change_password(usuario["id"], auth.LEGACY_DEFAULT_PASSWORD)
        assert auth.uses_legacy_default_password() is True

    def test_no_avisa_con_una_clave_propia(self, auth):
        auth.init_auth_tables()
        usuario = auth.list_users()[0]
        auth.change_password(usuario["id"], "Mi-Clave-Nueva-2026")
        assert auth.uses_legacy_default_password() is False

    def test_usuario_inexistente_no_revienta(self, auth):
        auth.init_auth_tables()
        assert auth.uses_legacy_default_password("no_existe") is False
