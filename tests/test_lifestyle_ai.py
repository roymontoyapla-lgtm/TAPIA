# -*- coding: utf-8 -*-
"""
Tests del cliente de IA que redacta el plan de alimentacion y ejercicio.
No se hace ninguna llamada real: la libreria anthropic se sustituye por un doble.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from tapia.ai import lifestyle_client
from tapia.ai.lifestyle_client import (
    build_ai_context,
    generate_ai_lifestyle_plan,
)
from tapia.core.lifestyle import build_lifestyle_plan


@pytest.fixture
def plan():
    return build_lifestyle_plan(
        patient={"name": "Maria Lopez", "age": 55, "sex": "F"},
        q={"diet_style": "mediterranea", "other_notes": "", "exercise_days_last_weeks": 2},
        anthro={"weight_kg": 84.0, "height_cm": 160.0, "waist_cm": 98.0},
    )


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Sustituye la libreria anthropic y devuelve el mock del cliente."""
    module = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text="## QUE BUSCAMOS CON ESTE PLAN\nTexto de prueba.")]
    module.Anthropic.return_value.messages.create.return_value = response
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.setattr(lifestyle_client.cfg.ai, "provider", "anthropic", raising=False)
    monkeypatch.setattr(lifestyle_client.cfg.ai, "anthropic_api_key", "sk-test", raising=False)
    monkeypatch.setattr(lifestyle_client.cfg.ai, "anonymize_before_send", True, raising=False)
    return module


class TestContext:

    def test_contexto_incluye_el_plan_calculado(self, plan):
        ctx = build_ai_context(plan)
        assert "PLAN DE ALIMENTACION Y EJERCICIO" in ctx
        assert "BALANCE ENERGETICO" in ctx

    def test_contexto_incluye_preferencias_y_alergias(self, plan):
        ctx = build_ai_context(plan, preferences="no le gusta el pescado", allergies="lactosa")
        assert "no le gusta el pescado" in ctx
        assert "lactosa" in ctx


class TestGeneracion:

    def test_devuelve_texto_de_la_ia(self, plan, fake_anthropic):
        result = generate_ai_lifestyle_plan(plan)
        assert result["ok"] is True
        assert "QUE BUSCAMOS" in result["text"]
        assert result["model"]

    def test_anonimiza_el_nombre_antes_de_enviar(self, plan, fake_anthropic):
        generate_ai_lifestyle_plan(plan)
        enviado = fake_anthropic.Anthropic.return_value.messages.create.call_args
        contenido = enviado.kwargs["messages"][0]["content"]
        assert "Maria Lopez" not in contenido
        assert "PACIENTE" in contenido

    def test_no_anonimiza_si_esta_desactivado(self, plan, fake_anthropic, monkeypatch):
        monkeypatch.setattr(lifestyle_client.cfg.ai, "anonymize_before_send", False, raising=False)
        generate_ai_lifestyle_plan(plan)
        enviado = fake_anthropic.Anthropic.return_value.messages.create.call_args
        assert "Maria Lopez" in enviado.kwargs["messages"][0]["content"]

    def test_provider_desactivado_no_llama_a_la_ia(self, plan, fake_anthropic, monkeypatch):
        monkeypatch.setattr(lifestyle_client.cfg.ai, "provider", "disabled", raising=False)
        result = generate_ai_lifestyle_plan(plan)
        assert result["ok"] is False
        assert "IA no disponible" in result["error"]
        fake_anthropic.Anthropic.return_value.messages.create.assert_not_called()

    def test_sin_clave_devuelve_error_controlado(self, plan, fake_anthropic, monkeypatch):
        monkeypatch.setattr(lifestyle_client.cfg.ai, "anthropic_api_key", "", raising=False)
        result = generate_ai_lifestyle_plan(plan)
        assert result["ok"] is False
        assert "ANTHROPIC_API_KEY" in result["error"]

    def test_error_de_la_api_no_rompe_la_aplicacion(self, plan, fake_anthropic):
        fake_anthropic.Anthropic.return_value.messages.create.side_effect = RuntimeError("timeout")
        result = generate_ai_lifestyle_plan(plan)
        assert result["ok"] is False
        assert "timeout" in result["error"]
        assert result["text"] == ""
