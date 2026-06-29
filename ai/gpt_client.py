"""
Integración con IA (OpenAI o Anthropic).
El proveedor activo se configura en config.yaml → ai.provider.
"""

import json
import logging
import re
from typing import Any, Dict

from ..core.config import cfg

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Eres un asistente clínico para triaje en atención primaria. "
    "NO diagnostiques. SOLO clasifica la urgencia de la cita basándote en el informe. "
    "Devuelve JSON con claves: urgency, justification, red_flags. "
    "urgency debe ser EXACTAMENTE uno de: 'urgente', '7_dias', '2_semanas'. "
    "justification: entre 1 y 5 frases claras y concisas. "
    "red_flags: lista corta (puede estar vacía). "
    "Si faltan datos o no hay banderas rojas relevantes, elige '2_semanas'."
)

_FALLBACK: Dict[str, Any] = {
    "urgency": "2_semanas",
    "justification": "IA no disponible. Se usa clasificación local.",
    "red_flags": [],
}


def _anonymize(text: str, name: str) -> str:
    """Sustituye el nombre real por 'PACIENTE' antes de enviar a la IA."""
    if not name:
        return text
    return re.sub(re.escape(name), "PACIENTE", text, flags=re.IGNORECASE)


def _sanitize(out: Dict[str, Any]) -> Dict[str, Any]:
    from ..core.triage import URGENCY_ORDER
    if out.get("urgency") not in URGENCY_ORDER:
        out["urgency"] = "2_semanas"
    if not isinstance(out.get("justification"), str):
        out["justification"] = ""
    if not isinstance(out.get("red_flags"), list):
        out["red_flags"] = []
    return out


# ---------------------------------------------------------------------------
# Proveedor: OpenAI
# ---------------------------------------------------------------------------

def _call_openai(report_text: str) -> Dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai no está instalado.")
        return {**_FALLBACK, "justification": "openai no instalado."}

    if not cfg.ai.openai_api_key:
        return {**_FALLBACK, "justification": "OPENAI_API_KEY no configurada."}

    client = OpenAI(api_key=cfg.ai.openai_api_key)
    last_err = None

    for model in cfg.ai.openai_models:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": report_text},
                ],
                response_format={"type": "json_object"},
                temperature=cfg.ai.temperature,
                max_tokens=cfg.ai.max_tokens,
            )
            out = json.loads(resp.choices[0].message.content)
            out["_model_used"] = model
            return _sanitize(out)
        except Exception as e:
            last_err = e
            logger.warning("Fallo con modelo %s: %s", model, e)

    return {
        **_FALLBACK,
        "justification": f"Fallo OpenAI ({type(last_err).__name__}). Usando clasificación local.",
    }


# ---------------------------------------------------------------------------
# Proveedor: Anthropic
# ---------------------------------------------------------------------------

def _call_anthropic(report_text: str) -> Dict[str, Any]:
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic no está instalado.")
        return {**_FALLBACK, "justification": "anthropic no instalado."}

    if not cfg.ai.anthropic_api_key:
        return {**_FALLBACK, "justification": "ANTHROPIC_API_KEY no configurada."}

    try:
        client = anthropic.Anthropic(api_key=cfg.ai.anthropic_api_key)
        resp = client.messages.create(
            model=cfg.ai.anthropic_model,
            max_tokens=cfg.ai.max_tokens,
            system=SYSTEM_PROMPT + " Responde SOLO con JSON válido, sin texto adicional.",
            messages=[{"role": "user", "content": report_text}],
        )
        raw = resp.content[0].text.strip()
        # Eliminar posibles bloques ```json ... ```
        raw = re.sub(r"^```json\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
        out = json.loads(raw)
        out["_model_used"] = cfg.ai.anthropic_model
        return _sanitize(out)
    except Exception as e:
        logger.warning("Fallo Anthropic: %s", e)
        return {
            **_FALLBACK,
            "justification": f"Fallo Anthropic ({type(e).__name__}). Usando clasificación local.",
        }


# ---------------------------------------------------------------------------
# Punto de entrada público
# ---------------------------------------------------------------------------

def get_ai_urgency(report_text: str, patient_name: str = "") -> Dict[str, Any]:
    """
    Clasifica la urgencia del informe usando el proveedor configurado.
    Anonimiza el nombre si `ai.anonymize_before_send` está activo.
    """
    if cfg.ai.anonymize_before_send and patient_name:
        report_text = _anonymize(report_text, patient_name)

    provider = cfg.ai.provider.lower()

    if provider == "openai":
        return _call_openai(report_text)
    elif provider == "anthropic":
        return _call_anthropic(report_text)
    else:
        logger.info("IA desactivada (provider='%s').", provider)
        return {**_FALLBACK, "justification": "IA desactivada en configuración."}
