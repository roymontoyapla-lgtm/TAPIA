"""Tests del modo demostracion (TAPIA_DEMO_MODE)."""

import pytest

from tapia.core.config import DEMO_MODE_ENV, demo_mode
from tapia.ui.demo import DEMO_BANNER, demo_banner_text


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", "si", "yes", " 1 "])
def test_valores_que_activan(monkeypatch, valor):
    monkeypatch.setenv(DEMO_MODE_ENV, valor)
    assert demo_mode()
    assert demo_banner_text() == DEMO_BANNER


@pytest.mark.parametrize("valor", ["", "0", "false", "no"])
def test_valores_que_no_activan(monkeypatch, valor):
    monkeypatch.setenv(DEMO_MODE_ENV, valor)
    assert not demo_mode()
    assert demo_banner_text() is None


def test_sin_variable_no_hay_aviso(monkeypatch):
    monkeypatch.delenv(DEMO_MODE_ENV, raising=False)
    assert demo_banner_text() is None


def test_el_aviso_pide_datos_ficticios():
    assert "datos ficticios" in DEMO_BANNER
    assert "pacientes reales" in DEMO_BANNER
