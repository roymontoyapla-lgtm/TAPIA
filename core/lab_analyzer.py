# -*- coding: utf-8 -*-
"""
Extraccion de valores de analisis clinicos mediante Claude Vision.

Soporta imagenes JPG, PNG y PDF escaneados.
Claude lee la imagen y devuelve los valores en formato JSON estructurado.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un asistente clinico especializado en leer analisis de laboratorio.
Se te proporcionara una imagen de un analisis clinico.
Extrae TODOS los valores que encuentres y devuelve SOLO un JSON valido con esta estructura exacta:

{
  "fecha_analisis": "YYYY-MM-DD o null si no se ve",
  "laboratorio": "nombre del laboratorio o null",
  "hemograma": {
    "hemoglobina_g_dl": null,
    "hematocrito_pct": null,
    "globulos_rojos_mill": null,
    "globulos_blancos_mil": null,
    "plaquetas_mil": null,
    "neutrofilos_pct": null,
    "linfocitos_pct": null,
    "monocitos_pct": null,
    "eosinofilos_pct": null,
    "vem_fl": null,
    "hem_pg": null
  },
  "bioquimica": {
    "glucosa_mg_dl": null,
    "colesterol_total_mg_dl": null,
    "colesterol_hdl_mg_dl": null,
    "colesterol_ldl_mg_dl": null,
    "trigliceridos_mg_dl": null,
    "creatinina_mg_dl": null,
    "urea_mg_dl": null,
    "acido_urico_mg_dl": null,
    "alt_u_l": null,
    "ast_u_l": null,
    "ggt_u_l": null,
    "bilirrubina_total_mg_dl": null,
    "proteinas_totales_g_dl": null,
    "albumina_g_dl": null,
    "sodio_meq_l": null,
    "potasio_meq_l": null,
    "calcio_mg_dl": null,
    "hierro_ug_dl": null,
    "ferritina_ng_ml": null,
    "vitamina_d_ng_ml": null,
    "vitamina_b12_pg_ml": null,
    "tsh_uui_ml": null,
    "pcr_mg_l": null,
    "hba1c_pct": null
  },
  "orina": {
    "ph": null,
    "densidad": null,
    "proteinas": null,
    "glucosa": null,
    "cetonas": null,
    "bilirrubina": null,
    "sangre": null,
    "leucocitos": null,
    "nitritos": null
  },
  "valores_fuera_rango": [],
  "notas": ""
}

Rellena SOLO los valores que puedas leer claramente. Deja null los que no aparezcan.
En valores_fuera_rango lista los parametros que aparezcan marcados como H (alto), L (bajo) o con asterisco.
Responde SOLO con el JSON, sin texto adicional ni bloques de codigo."""


def _encode_image(image_bytes: bytes, mime_type: str) -> str:
    """Convierte la imagen a base64."""
    return base64.standard_b64encode(image_bytes).decode("utf-8")


def extract_lab_values(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> Dict[str, Any]:
    """
    Usa Claude Vision para extraer valores del analisis clinico.
    Devuelve un dict con los valores extraidos.
    """
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic no instalado")
        return _fallback("anthropic no instalado")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _fallback("ANTHROPIC_API_KEY no configurada")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        image_b64 = _encode_image(image_bytes, mime_type)

        response = client.messages.create(
            model="claude-opus-4-5",  # modelo con mejor vision
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extrae todos los valores de este analisis clinico.",
                        },
                    ],
                }
            ],
            system=SYSTEM_PROMPT,
        )

        raw = response.content[0].text.strip()
        # Limpiar posibles bloques ```json ... ```
        raw = re.sub(r"^```json\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
        result = json.loads(raw)
        result["_success"] = True
        logger.info("Analisis extraido correctamente. Fuera de rango: %s",
                    result.get("valores_fuera_rango", []))
        return result

    except json.JSONDecodeError as e:
        logger.error("Error parseando JSON de Claude: %s", e)
        return _fallback(f"Error parseando respuesta de la IA: {e}")
    except Exception as e:
        logger.error("Error en extract_lab_values: %s", e)
        return _fallback(str(e))


def _fallback(reason: str) -> Dict[str, Any]:
    return {
        "_success": False,
        "_error": reason,
        "fecha_analisis": None,
        "laboratorio": None,
        "hemograma": {},
        "bioquimica": {},
        "orina": {},
        "valores_fuera_rango": [],
        "notas": f"Error: {reason}",
    }


# ---------------------------------------------------------------------------
# Valores de referencia para el score de urgencia
# ---------------------------------------------------------------------------

# (valor, min_normal, max_normal, puntos_si_fuera_rango, descripcion)
LAB_SCORE_RULES = [
    # Hemograma
    ("hemograma.hemoglobina_g_dl",   7.0,  10.0, 3, "Hemoglobina muy baja"),
    ("hemograma.hemoglobina_g_dl",   10.0, 12.0, 1, "Hemoglobina baja"),
    ("hemograma.globulos_blancos_mil",11.0, 30.0, 2, "Leucocitosis"),
    ("hemograma.globulos_blancos_mil", 1.0,  3.5, 2, "Leucopenia"),
    ("hemograma.plaquetas_mil",        50.0,100.0, 3, "Trombocitopenia grave"),
    ("hemograma.plaquetas_mil",       100.0,150.0, 1, "Trombocitopenia leve"),
    # Bioquimica
    ("bioquimica.glucosa_mg_dl",     250.0, 999.0, 3, "Hiperglucemia grave"),
    ("bioquimica.glucosa_mg_dl",     126.0, 250.0, 1, "Hiperglucemia"),
    ("bioquimica.glucosa_mg_dl",       0.0,  70.0, 3, "Hipoglucemia"),
    ("bioquimica.creatinina_mg_dl",    1.5,  3.0,  2, "Insuficiencia renal moderada"),
    ("bioquimica.creatinina_mg_dl",    3.0, 99.0,  4, "Insuficiencia renal grave"),
    ("bioquimica.potasio_meq_l",       0.0,  3.0,  3, "Hipopotasemia grave"),
    ("bioquimica.potasio_meq_l",       5.5,  7.0,  3, "Hiperpotasemia"),
    ("bioquimica.pcr_mg_l",           10.0, 50.0,  1, "PCR elevada"),
    ("bioquimica.pcr_mg_l",           50.0, 99999, 2, "PCR muy elevada"),
    ("bioquimica.hba1c_pct",           8.0,  10.0, 1, "HbA1c elevada"),
    ("bioquimica.hba1c_pct",          10.0,  99.0, 2, "HbA1c muy elevada"),
]


def lab_urgency_score(lab_data: Dict[str, Any]) -> tuple[int, List[str]]:
    """
    Calcula puntos de urgencia basados en los valores del analisis.
    Devuelve (score, lista_de_motivos).
    """
    score = 0
    motivos = []

    def _get(path: str):
        keys = path.split(".")
        d = lab_data
        for k in keys:
            if not isinstance(d, dict):
                return None
            d = d.get(k)
        return d

    for path, min_val, max_val, pts, desc in LAB_SCORE_RULES:
        val = _get(path)
        if val is None:
            continue
        try:
            v = float(val)
            if min_val <= v <= max_val:
                score += pts
                motivos.append(f"{desc}: {v} (+{pts})")
        except (TypeError, ValueError):
            continue

    return score, motivos
