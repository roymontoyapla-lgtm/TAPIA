# -*- coding: utf-8 -*-
"""
Tests del asistente de alta de Dropbox (scripts/dropbox_setup.py).

Interesa sobre todo que no destroce un .env existente y que el canje del
codigo de autorizacion avise bien cuando algo falla.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def setup_mod():
    """Carga el script como modulo (vive fuera del paquete)."""
    spec = importlib.util.spec_from_file_location(
        "dropbox_setup", ROOT / "scripts" / "dropbox_setup.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["dropbox_setup"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


# ---------------------------------------------------------------------------
# Escritura del .env
# ---------------------------------------------------------------------------

class TestEnv:

    def test_anade_claves_a_un_env_vacio(self, setup_mod):
        salida = setup_mod.update_env_text("", {"DROPBOX_APP_KEY": "k"})
        assert "DROPBOX_APP_KEY=k" in salida

    def test_conserva_las_demas_claves(self, setup_mod):
        original = "ANTHROPIC_API_KEY=sk-ant-xxx\nTAPIA_ENV=development\n"
        salida = setup_mod.update_env_text(original, {"DROPBOX_APP_KEY": "k"})
        assert "ANTHROPIC_API_KEY=sk-ant-xxx" in salida
        assert "TAPIA_ENV=development" in salida
        assert "DROPBOX_APP_KEY=k" in salida

    def test_sustituye_en_su_sitio_sin_duplicar(self, setup_mod):
        original = "DROPBOX_APP_KEY=viejo\nTAPIA_ENV=development\n"
        salida = setup_mod.update_env_text(original, {"DROPBOX_APP_KEY": "nuevo"})
        assert salida.count("DROPBOX_APP_KEY") == 1
        assert "DROPBOX_APP_KEY=nuevo" in salida
        assert "viejo" not in salida

    def test_respeta_comentarios(self, setup_mod):
        original = "# --- Anthropic ---\nANTHROPIC_API_KEY=sk-ant-xxx\n"
        salida = setup_mod.update_env_text(original, {"DROPBOX_APP_KEY": "k"})
        assert "# --- Anthropic ---" in salida

    def test_lee_el_env_ignorando_comillas_y_comentarios(self, setup_mod, tmp_path):
        env = tmp_path / ".env"
        env.write_text('# comentario\nDROPBOX_APP_KEY="k"\nOTRA=valor\n', encoding="utf-8")
        valores = setup_mod.read_env(env)
        assert valores["DROPBOX_APP_KEY"] == "k"
        assert valores["OTRA"] == "valor"

    def test_env_inexistente_devuelve_vacio(self, setup_mod, tmp_path):
        assert setup_mod.read_env(tmp_path / "no-existe") == {}

    def test_escribe_y_relee(self, setup_mod, tmp_path):
        env = tmp_path / ".env"
        env.write_text("TAPIA_ENV=development\n", encoding="utf-8")
        setup_mod.write_env({"DROPBOX_REFRESH_TOKEN": "tok"}, env)
        valores = setup_mod.read_env(env)
        assert valores["DROPBOX_REFRESH_TOKEN"] == "tok"
        assert valores["TAPIA_ENV"] == "development"


# ---------------------------------------------------------------------------
# Canje del codigo
# ---------------------------------------------------------------------------

class TestExchange:

    def _requests(self, monkeypatch, setup_mod, resp):
        modulo = MagicMock()
        modulo.post.return_value = resp
        monkeypatch.setitem(sys.modules, "requests", modulo)
        return modulo

    def _resp(self, status=200, payload=None):
        r = MagicMock()
        r.status_code = status
        r.json.return_value = payload or {}
        r.text = ""
        return r

    def test_devuelve_el_refresh_token(self, setup_mod, monkeypatch):
        self._requests(monkeypatch, setup_mod, self._resp(payload={
            "access_token": "sl.u.corto", "refresh_token": "largo",
            "scope": "files.content.read files.metadata.read",
        }))
        datos = setup_mod.exchange_code("k", "s", "codigo")
        assert datos["refresh_token"] == "largo"

    def test_codigo_caducado_avisa_de_repetir(self, setup_mod, monkeypatch):
        self._requests(monkeypatch, setup_mod, self._resp(
            status=400, payload={"error": "invalid_grant"},
        ))
        with pytest.raises(SystemExit, match="caducado"):
            setup_mod.exchange_code("k", "s", "usado")

    def test_credenciales_malas_muestran_el_error(self, setup_mod, monkeypatch):
        self._requests(monkeypatch, setup_mod, self._resp(
            status=401, payload={"error_description": "Invalid client credentials"},
        ))
        with pytest.raises(SystemExit, match="Invalid client credentials"):
            setup_mod.exchange_code("k", "malo", "codigo")

    def test_sin_refresh_token_explica_el_parametro(self, setup_mod, monkeypatch):
        self._requests(monkeypatch, setup_mod, self._resp(payload={"access_token": "sl.u.x"}))
        with pytest.raises(SystemExit, match="token_access_type=offline"):
            setup_mod.exchange_code("k", "s", "codigo")
