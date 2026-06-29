"""Modelos de datos del dominio."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PatientInfo:
    name: str
    age: int
    sex: str


@dataclass
class Questionnaire:
    headache_last_month: bool
    fever: bool
    general_feeling: int        # 1–5
    diet_style: str
    rested_enough: int          # 1–5
    exercise_days_last_weeks: int
    other_notes: str


@dataclass
class WearableSummary:
    days: int
    range: str
    avg_resting_hr: Optional[float]
    avg_steps: Optional[float]
    avg_exercise_min: Optional[float]
    avg_sleep_h: Optional[float]
    avg_resp: Optional[float]
    avg_hrv: Optional[float]
    low_sleep_days: int
    very_low_activity_days: int
    high_resting_hr_days: int
