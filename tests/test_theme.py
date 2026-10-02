# -*- coding: utf-8 -*-
"""
Tests del tema visual.

No se comprueba como se ve (eso se mira con capturas), sino que el CSS se
genera entero y que cada prioridad de triaje tiene su color: un bucket sin
color saldria gris y pasaria desapercibido.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tapia.core.triage import URGENCY_LABELS
from tapia.ui import theme


class TestCSS:

    def test_el_css_se_genera_completo(self):
        css = theme._css()
        assert css.startswith("\n<style>")
        assert css.rstrip().endswith("</style>")

    def test_no_quedan_llaves_de_formato_sin_resolver(self):
        """El CSS va en un f-string: las llaves dobles deben haberse cerrado."""
        css = theme._css()
        assert "{{" not in css
        assert "}}" not in css

    def test_las_llaves_del_css_estan_equilibradas(self):
        css = theme._css()
        assert css.count("{") == css.count("}")

    def test_incluye_la_pila_tipografica_del_sistema(self):
        css = theme._css()
        assert "-apple-system" in css
        assert "Segoe UI" in css      # Windows, que es donde se usa

    def test_respeta_la_fuente_de_los_iconos(self):
        """Sin esta excepcion los iconos salen como texto ('visibility')."""
        css = theme._css()
        assert 'stIconMaterial' in css
        assert "Material Symbols Rounded" in css

    def test_usa_selectores_estables_para_la_navegacion(self):
        """
        Las clases generadas por Streamlit cambian entre versiones, asi que
        no deben usarse como selector (mencionarlas en un comentario si vale).
        """
        css = theme._css()
        assert 'label[data-testid="stRadioOption"]' in css
        assert ".st-emotion-cache" not in css

    def test_inject_escribe_el_estilo(self, monkeypatch):
        escrito = {}

        def _markdown(texto, **kwargs):
            escrito["texto"] = texto
            escrito["kwargs"] = kwargs

        monkeypatch.setattr(theme.st, "markdown", _markdown)
        theme.inject()

        assert escrito["kwargs"]["unsafe_allow_html"] is True
        assert "<style>" in escrito["texto"]


class TestColoresDeUrgencia:

    def test_hay_color_para_cada_prioridad(self):
        assert set(theme.URGENCIA) == set(URGENCY_LABELS)

    @pytest.mark.parametrize("bucket", ["urgente", "7_dias", "2_semanas"])
    def test_la_pastilla_usa_el_color_del_bucket(self, bucket):
        html = theme.urgency_badge_html(URGENCY_LABELS[bucket], bucket)
        assert theme.URGENCIA[bucket] in html
        assert URGENCY_LABELS[bucket] in html

    def test_bucket_desconocido_no_revienta(self):
        html = theme.urgency_badge_html("Sin clasificar", "inventado")
        assert theme.TEXTO_SUAVE in html

    @pytest.mark.parametrize("bucket", ["urgente", "7_dias", "2_semanas"])
    def test_el_texto_blanco_contrasta_sobre_el_color(self, bucket):
        """WCAG AA para texto grande: al menos 3:1 (aqui se exige 4.5:1)."""
        color = theme.URGENCIA[bucket]
        r, g, b = (int(color[i:i+2], 16) / 255 for i in (1, 3, 5))

        def _lineal(c):
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        lum = 0.2126 * _lineal(r) + 0.7152 * _lineal(g) + 0.0722 * _lineal(b)
        contraste = 1.05 / (lum + 0.05)
        assert contraste >= 4.5, f"{bucket} queda en {contraste:.2f}:1"
