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


# ---------------------------------------------------------------------------
# XML de Apple Health
# ---------------------------------------------------------------------------

def _xml(*filas: str) -> bytes:
    cuerpo = "\n".join(filas)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE HealthData [<!ELEMENT HealthData (Record*)>]>\n'
        f'<HealthData locale="es_ES">\n{cuerpo}\n</HealthData>\n'
    ).encode("utf-8")


def _record(tipo: str, dias_atras: int, valor: str = "1234") -> str:
    from datetime import datetime, timedelta
    d = (datetime.now() - timedelta(days=dias_atras)).strftime("%Y-%m-%d %H:%M:%S +0200")
    return (f'<Record type="{tipo}" sourceName="Apple Watch" '
            f'startDate="{d}" endDate="{d}" value="{valor}"/>')


PASOS = "HKQuantityTypeIdentifierStepCount"
AGUA  = "HKQuantityTypeIdentifierDietaryWater"


class TestAppleXML:

    def test_cuenta_los_registros_en_ventana(self, diag):
        salida = "\n".join(diag.describe_apple_xml(_xml(
            _record(PASOS, 1), _record(PASOS, 2), _record(PASOS, 3),
        )))
        assert "Registros <Record>: 3" in salida
        assert "en ventana=        3" in salida

    def test_avisa_si_todo_queda_fuera_de_la_ventana(self, diag):
        """Export viejo: hay datos, pero anteriores a la ventana pedida."""
        salida = "\n".join(diag.describe_apple_xml(_xml(
            _record(PASOS, 400), _record(PASOS, 401),
        )))
        assert "total=        2" in salida
        assert "en ventana=        0" in salida
        assert "ninguno de los tipos que TAPIA usa" in salida

    def test_lista_los_tipos_que_tapia_no_usa(self, diag):
        salida = "\n".join(diag.describe_apple_xml(_xml(_record(AGUA, 1))))
        assert AGUA in salida
        assert "Otros tipos presentes" in salida

    def test_la_ventana_es_configurable(self, diag):
        xml = _xml(_record(PASOS, 300))
        assert "en ventana=        0" in "\n".join(diag.describe_apple_xml(xml, days=180))
        assert "en ventana=        1" in "\n".join(diag.describe_apple_xml(xml, days=365))

    def test_xml_roto_no_revienta(self, diag):
        salida = "\n".join(diag.describe_apple_xml(b"<HealthData><Record "))
        assert "Error recorriendo el XML" in salida

    def test_no_filtra_valores_de_salud(self, diag):
        salida = "\n".join(diag.describe_apple_xml(_xml(_record(PASOS, 1, valor="98765"))))
        assert "98765" not in salida
