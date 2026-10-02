# -*- coding: utf-8 -*-
"""
Tests de la generacion de PDF.

Interesa sobre todo que el semaforo de urgencia solo aparezca en los
informes de triaje: un plan de alimentacion o un informe integral no
tienen prioridad de cita y mostrarla confunde al lector.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pdf = pytest.importorskip("tapia.export.pdf")

if not pdf.REPORTLAB_OK:
    pytest.skip("reportlab no instalado", allow_module_level=True)


REPORT = "INFORME DE PRUEBA\n\nLinea uno.\nLinea dos."


class TestUrgencyBadge:

    def test_triaje_muestra_el_semaforo(self, tmp_path):
        destino = tmp_path / "triaje.pdf"
        with patch.object(pdf, "_urgency_badge", wraps=pdf._urgency_badge) as badge:
            pdf.save_pdf(str(destino), REPORT, patient_name="Ana",
                         final_bucket="urgente", local_score=9)
        badge.assert_called_once()
        assert destino.exists() and destino.stat().st_size > 0

    def test_plan_omite_el_semaforo(self, tmp_path):
        destino = tmp_path / "plan.pdf"
        with patch.object(pdf, "_urgency_badge", wraps=pdf._urgency_badge) as badge:
            pdf.save_pdf(str(destino), REPORT, patient_name="Ana",
                         show_urgency=False,
                         section_title="Plan de alimentacion y ejercicio")
        badge.assert_not_called()
        assert destino.exists() and destino.stat().st_size > 0

    def test_titulo_de_seccion_configurable(self, tmp_path):
        """El titulo por defecto sigue siendo el del informe de triaje."""
        destino = tmp_path / "informe.pdf"
        with patch.object(pdf, "Paragraph", wraps=pdf.Paragraph) as parrafo:
            pdf.save_pdf(str(destino), REPORT, patient_name="Ana")
        textos = [c.args[0] for c in parrafo.call_args_list if c.args]
        assert "Informe completo" in textos

    def test_titulo_de_seccion_personalizado(self, tmp_path):
        destino = tmp_path / "informe.pdf"
        with patch.object(pdf, "Paragraph", wraps=pdf.Paragraph) as parrafo:
            pdf.save_pdf(str(destino), REPORT, patient_name="Ana",
                         show_urgency=False, section_title="Informe clinico integral")
        textos = [c.args[0] for c in parrafo.call_args_list if c.args]
        assert "Informe clinico integral" in textos
        assert "Informe completo" not in textos
