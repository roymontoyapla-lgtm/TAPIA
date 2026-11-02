"""Tests del origen de la clave de cifrado (variable de entorno o fichero)."""

import pytest
from cryptography.fernet import Fernet

from tapia.db import crypto


@pytest.fixture
def sin_fichero(tmp_path, monkeypatch):
    """Apunta la clave a un fichero temporal para no tocar .tapia_key."""
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / ".tapia_key")
    monkeypatch.delenv(crypto.KEY_ENV, raising=False)
    return tmp_path / ".tapia_key"


class TestClaveDesdeVariable:
    def test_usa_la_variable_y_no_crea_fichero(self, sin_fichero, monkeypatch):
        clave = Fernet.generate_key().decode()  # sintetica, solo para el test
        monkeypatch.setenv(crypto.KEY_ENV, clave)
        token = crypto.encrypt("Paciente Sintetico")
        assert Fernet(clave.encode()).decrypt(token.encode()).decode() == "Paciente Sintetico"
        assert not sin_fichero.exists()

    def test_misma_variable_descifra_entre_reinicios(self, sin_fichero, monkeypatch):
        monkeypatch.setenv(crypto.KEY_ENV, Fernet.generate_key().decode())
        token = crypto.encrypt("dato sintetico")
        # Un reinicio en la nube no conserva ficheros, pero si la variable
        assert crypto.decrypt(token) == "dato sintetico"

    def test_variable_mal_formada_da_error_claro(self, sin_fichero, monkeypatch):
        monkeypatch.setenv(crypto.KEY_ENV, "no-es-una-clave")
        with pytest.raises(ValueError, match=crypto.KEY_ENV):
            crypto.encrypt("dato sintetico")
        assert not sin_fichero.exists()

    def test_sin_variable_usa_fichero(self, sin_fichero):
        crypto.encrypt("dato sintetico")
        assert sin_fichero.exists()

    def test_key_location_no_revela_la_clave(self, sin_fichero, monkeypatch):
        clave = Fernet.generate_key().decode()
        monkeypatch.setenv(crypto.KEY_ENV, clave)
        assert clave not in crypto.key_location()
        assert crypto.KEY_ENV in crypto.key_location()

    def test_key_location_sin_variable_es_el_fichero(self, sin_fichero):
        assert crypto.key_location() == str(sin_fichero)
