# -*- coding: utf-8 -*-
"""
Personalizacion con IA del plan de alimentacion y ejercicio.

El plan numerico lo calcula siempre core.lifestyle (deterministico y auditable).
Este modulo solo pide a la IA que lo convierta en un plan narrativo, cercano
y accionable para el paciente, SIN cambiar las cifras calculadas.

Si la IA no esta disponible (sin clave, sin libreria o desactivada en
config.yaml) se devuelve un aviso y la aplicacion sigue usando el plan
deterministico.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from ..core.config import cfg
from ..core.lifestyle import LifestylePlan, render_plan_text

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un profesional de nutricion y ejercicio fisico que trabaja
junto al medico de atencion primaria. Recibes un plan ya calculado con formulas
validadas (gasto energetico, macronutrientes y prescripcion de ejercicio segun
las directrices de la OMS) y los datos de salud del paciente.

Tu tarea es redactar ese plan para que el paciente lo entienda y lo pueda seguir.

REGLAS ESTRICTAS:
- NO modifiques ninguna cifra del plan recibido (calorias, gramos de
  macronutrientes, minutos de ejercicio, pasos, objetivos). Usalas tal cual.
- NO diagnostiques ni prescribas medicacion ni suplementos.
- Si el plan indica que se requiere autorizacion medica antes de hacer
  ejercicio, dilo de forma destacada al principio y no propongas
  intensidades por encima de lo indicado.
- Respeta las restricciones, alergias y preferencias alimentarias indicadas.
- Usa alimentos habituales y economicos, con raciones caseras (plato, taza,
  punado, cuchara) ademas de los gramos.
- Tono cercano, en segunda persona, sin tecnicismos innecesarios.

Estructura la respuesta con estas secciones en markdown:
## QUE BUSCAMOS CON ESTE PLAN
## TU ALIMENTACION DIA A DIA
## MENU SEMANAL ORIENTATIVO
## LISTA DE LA COMPRA
## TU PLAN DE EJERCICIO
## COMO PROGRESAR SEMANA A SEMANA
## SENALES PARA PARAR Y CONSULTAR
## OBJETIVOS Y PROXIMA REVISION

Responde en español."""


def _anonymize(text: str, name: str) -> str:
    """Sustituye el nombre real por 'PACIENTE' antes de enviar a la IA."""
    if not name:
        return text
    return re.sub(re.escape(name), "PACIENTE", text, flags=re.IGNORECASE)


def build_ai_context(
    plan: LifestylePlan,
    preferences: str = "",
    allergies: str = "",
    notes: str = "",
) -> str:
    """Contexto que se envia a la IA: el plan calculado mas las preferencias."""
    extra = []
    if preferences:
        extra.append(f"Preferencias y gustos alimentarios: {preferences}")
    if allergies:
        extra.append(f"Alergias o intolerancias (EVITAR SIEMPRE): {allergies}")
    if notes:
        extra.append(f"Observaciones del profesional: {notes}")

    context = render_plan_text(plan)
    if extra:
        context += "\n\nINFORMACION ADICIONAL DEL PACIENTE\n" + "\n".join(f"- {e}" for e in extra)
    return context


def generate_ai_lifestyle_plan(
    plan: LifestylePlan,
    preferences: str = "",
    allergies: str = "",
    notes: str = "",
    max_tokens: int = 4000,
) -> Dict[str, Any]:
    """
    Convierte el plan calculado en un plan narrativo con Claude.
    Devuelve {"text": str, "model": str, "ok": bool, "error": str}.
    """
    context = build_ai_context(plan, preferences, allergies, notes)
    if cfg.ai.anonymize_before_send and plan.patient_name:
        context = _anonymize(context, plan.patient_name)

    provider = (cfg.ai.provider or "").lower()
    if provider != "anthropic":
        return _fail(
            f"IA no disponible (provider='{cfg.ai.provider}'). "
            "Se muestra el plan calculado por TAPIA."
        )

    try:
        import anthropic
    except ImportError:
        return _fail("anthropic no instalado. Instala con: pip install anthropic")

    if not cfg.ai.anthropic_api_key:
        return _fail("ANTHROPIC_API_KEY no configurada.")

    try:
        client = anthropic.Anthropic(api_key=cfg.ai.anthropic_api_key)
        resp = client.messages.create(
            model=cfg.ai.anthropic_model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    "Redacta el plan de alimentacion y ejercicio para este paciente "
                    "(identificado como PACIENTE) a partir del plan ya calculado:\n\n"
                    + context
                ),
            }],
        )
        text = resp.content[0].text.strip()
        logger.info("Plan de estilo de vida generado con %s", cfg.ai.anthropic_model)
        return {"text": text, "model": cfg.ai.anthropic_model, "ok": True, "error": ""}

    except Exception as e:
        logger.error("Error generando el plan con IA: %s", e)
        return _fail(f"Fallo al contactar con la IA ({type(e).__name__}): {e}")


def _fail(msg: str) -> Dict[str, Any]:
    return {"text": "", "model": "", "ok": False, "error": msg}
