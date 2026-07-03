"""
Carga la configuración desde config.yaml y las variables de entorno desde .env.
El resto de módulos importan `cfg` desde aquí para leer cualquier ajuste.
"""

import logging
import os
from pathlib import Path
from typing import Any

try:
    import yaml
    YAML_OK = True
except ImportError:
    YAML_OK = False

try:
    from dotenv import load_dotenv
    DOTENV_OK = True
except ImportError:
    DOTENV_OK = False

# Directorio raíz del proyecto (donde vive config.yaml)
ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """Carga .env si existe y python-dotenv está instalado."""
    env_path = ROOT / ".env"
    if DOTENV_OK and env_path.exists():
        load_dotenv(env_path)
    elif not DOTENV_OK:
        logging.warning(
            "python-dotenv no está instalado. "
            "Las variables de entorno deben definirse manualmente."
        )


def _load_yaml() -> dict:
    """Lee config.yaml. Si falla devuelve un dict vacío."""
    cfg_path = ROOT / "config.yaml"
    if not YAML_OK:
        logging.warning("PyYAML no instalado. Se usarán valores por defecto.")
        return {}
    if not cfg_path.exists():
        logging.warning("config.yaml no encontrado en %s.", ROOT)
        return {}
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_get(d: dict, *keys: str, default: Any = None) -> Any:
    """Acceso seguro a claves anidadas: _deep_get(cfg, 'a', 'b', 'c')."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


# ---------------------------------------------------------------------------
# Inicialización (se ejecuta una sola vez al importar el módulo)
# ---------------------------------------------------------------------------
_load_env()
_raw: dict = _load_yaml()


# ---------------------------------------------------------------------------
# Acceso tipado a los valores más usados
# (si el YAML cambia, solo hay que tocar aquí)
# ---------------------------------------------------------------------------

class _ThresholdsSleep:
    low_hours:              int = _deep_get(_raw, "thresholds", "sleep", "low_hours", default=6)
    low_days_month_ap:      int = _deep_get(_raw, "thresholds", "sleep", "low_days_month_ap", default=10)
    low_days_month_urgent:  int = _deep_get(_raw, "thresholds", "sleep", "low_days_month_urgent", default=15)
    low_days_month_moderate:int = _deep_get(_raw, "thresholds", "sleep", "low_days_month_moderate", default=8)
    low_days_8w_ap:         int = _deep_get(_raw, "thresholds", "sleep", "low_days_8w_ap", default=20)
    low_days_8w_persistent: int = _deep_get(_raw, "thresholds", "sleep", "low_days_8w_persistent", default=25)


class _ThresholdsActivity:
    very_low_steps:          int = _deep_get(_raw, "thresholds", "activity", "very_low_steps", default=3000)
    low_days_month_ap:       int = _deep_get(_raw, "thresholds", "activity", "low_days_month_ap", default=10)
    low_days_month_urgent:   int = _deep_get(_raw, "thresholds", "activity", "low_days_month_urgent", default=15)
    low_days_month_moderate: int = _deep_get(_raw, "thresholds", "activity", "low_days_month_moderate", default=8)


class _ThresholdsHR:
    high_resting_bpm:    int = _deep_get(_raw, "thresholds", "heart_rate", "high_resting_bpm", default=90)
    high_days_specialist:int = _deep_get(_raw, "thresholds", "heart_rate", "high_days_specialist", default=3)
    high_days_score_4:   int = _deep_get(_raw, "thresholds", "heart_rate", "high_days_score_4", default=5)
    high_days_score_3:   int = _deep_get(_raw, "thresholds", "heart_rate", "high_days_score_3", default=3)


class _Thresholds:
    sleep    = _ThresholdsSleep()
    activity = _ThresholdsActivity()
    hr       = _ThresholdsHR()


class _Urgency:
    urgent_threshold: int = _deep_get(_raw, "urgency", "urgent_threshold", default=9)
    week_threshold:   int = _deep_get(_raw, "urgency", "week_threshold",   default=5)


class _Scoring:
    age_over_75:             int = _deep_get(_raw, "scoring", "age", "over_75", default=3)
    age_over_65:             int = _deep_get(_raw, "scoring", "age", "over_65", default=2)
    age_over_50:             int = _deep_get(_raw, "scoring", "age", "over_50", default=1)
    fever:                   int = _deep_get(_raw, "scoring", "fever", default=3)
    fever_plus_bad_general:  int = _deep_get(_raw, "scoring", "fever_plus_bad_general", default=2)
    headache:                int = _deep_get(_raw, "scoring", "headache", default=1)
    general_bad:             int = _deep_get(_raw, "scoring", "general_feeling", "bad", default=3)
    general_fair:            int = _deep_get(_raw, "scoring", "general_feeling", "fair", default=1)
    rest_bad:                int = _deep_get(_raw, "scoring", "rest", "bad", default=2)
    rest_fair:               int = _deep_get(_raw, "scoring", "rest", "fair", default=1)
    exercise_very_low:       int = _deep_get(_raw, "scoring", "exercise_days", "very_low", default=2)
    exercise_low:            int = _deep_get(_raw, "scoring", "exercise_days", "low", default=1)


class _AI:
    provider:               str  = _deep_get(_raw, "ai", "provider", default="openai")
    openai_models:          list = _deep_get(_raw, "ai", "openai_models", default=["gpt-4o-mini", "gpt-4o"])
    anthropic_model:        str  = _deep_get(_raw, "ai", "anthropic_model", default="claude-sonnet-4-6")
    temperature:            float= _deep_get(_raw, "ai", "temperature", default=0.3)
    max_tokens:             int  = _deep_get(_raw, "ai", "max_tokens", default=1000)
    anonymize_before_send:  bool = _deep_get(_raw, "ai", "anonymize_before_send", default=True)
    openai_api_key:         str  = os.getenv("OPENAI_API_KEY", "")
    anthropic_api_key:      str  = os.getenv("ANTHROPIC_API_KEY", "")


class _Wearable:
    window_short: int = _deep_get(_raw, "wearable", "window_days_short", default=30)
    window_long:  int = _deep_get(_raw, "wearable", "window_days_long",  default=56)
    date_field:   str = _deep_get(_raw, "wearable", "date_field",        default="fecha")
    fields: dict      = _deep_get(_raw, "wearable", "fields", default={
        "resting_hr":   "pulso_reposo_bpm_media",
        "steps":        "pasos",
        "exercise_min": "min_ejercicio",
        "sleep_h":      "sueno_asleep_horas",
        "resp_rate":    "respiraciones_por_min_media",
        "hrv":          "hrv_sdnn_ms_media",
    })


class _App:
    name:     str = _deep_get(_raw, "app", "name",     default="TAPIA")
    version:  str = _deep_get(_raw, "app", "version",  default="1.1.0")
    geometry: str = _deep_get(_raw, "app", "geometry", default="980x700")
    log_level:str = _deep_get(_raw, "app", "log_level",default="WARNING")


class Config:
    """Punto de acceso único a toda la configuración."""
    app        = _App()
    thresholds = _Thresholds()
    urgency    = _Urgency()
    scoring    = _Scoring()
    ai         = _AI()
    wearable   = _Wearable()


cfg = Config()

# Configurar nivel de log según config.yaml
logging.basicConfig(
    level=getattr(logging, cfg.app.log_level, logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
