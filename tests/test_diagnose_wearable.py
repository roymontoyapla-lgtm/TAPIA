# -*- coding: utf-8 -*-
"""
Tests del diagnostico de ficheros de wearable (scripts/diagnose_wearable.py).

Lo importante: que describa la estructura y que NO imprima valores de salud,
porque la idea es poder pegar su salida en un chat de soporte.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def diag():
    spec = importlib.util.spec_from_file_location(
        "diagnose_wearable", ROOT / "scripts" / "diagnose_wearable.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["diagnose_wearable"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _payload(nombre="step_count", qty=7531):
    return {"data": {"metrics": [
        {"name": nombre, "units": "count",
         "data": [{"date": "2026-09-28 00:00:00 +0200", "qty": qty}]},
    ]}}


class TestDescripcion:

    def test_describe_una_lista(self, diag):
        salida = "\n".join(diag.describe_payload([{"fecha": "2026-09-28", "pasos": 100}]))
        assert "lista de 1" in salida
        assert "fecha" in salida

    def test_describe_un_objeto_anidado(self, diag):
        salida = "\n".join(diag.describe_payload(_payload()))
        assert "data" in salida
        assert "metrics" in salida

    def test_marca_las_metricas_reconocidas(self, diag):
        salida = "\n".join(diag.describe_metrics(_payload("step_count")))
        assert "-> steps" in salida
        assert "Reconocidas por TAPIA: 1 de 1" in salida

    def test_marca_las_metricas_ignoradas(self, diag):
        """El caso que deja el fichero sin dias validos."""
        salida = "\n".join(diag.describe_metrics(_payload("walking_running_distance")))
        assert "TAPIA la ignora" in salida
        assert "Reconocidas por TAPIA: 0 de 1" in salida

    def test_muestra_el_formato_de_fecha(self, diag):
        salida = "\n".join(diag.describe_metrics(_payload()))
        assert "2026-09-28 00:00:00 +0200" in salida

    def test_no_filtra_valores_de_salud(self, diag):
        """La salida es pegable en un chat: estructura si, valores no."""
        datos = _payload(qty=7531)
        salida = "\n".join(diag.describe_payload(datos) + diag.describe_metrics(datos))
        assert "7531" not in salida

    def test_otros_formatos_no_dan_descripcion_de_metricas(self, diag):
        assert diag.describe_metrics([{"fecha": "2026-09-28", "pasos": 100}]) == []
