"""Aviso de entorno de demostracion (variable TAPIA_DEMO_MODE)."""

from __future__ import annotations

from typing import Optional

from ..core.config import demo_mode

DEMO_BANNER = (
    "**Entorno de demostracion.** Usa solo datos ficticios: no introduzcas datos de "
    "pacientes reales. Los datos se borran en cada reinicio."
)

DEMO_SIDEBAR = "Entorno de demostracion"


def demo_banner_text() -> Optional[str]:
    """Texto del aviso si el modo demostracion esta activo; None si no."""
    return DEMO_BANNER if demo_mode() else None
