# -*- coding: utf-8 -*-
"""
Registra la raiz del repositorio como el paquete `tapia`.

El codigo importa con `tapia.core...`, pero el directorio clonado puede
llamarse TAPIA, tapia-main o cualquier otra cosa. Este conftest registra
esta carpeta bajo el nombre `tapia` antes de recolectar los tests, de modo
que `pytest` funcione tal cual desde la raiz del repositorio.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if "tapia" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "tapia",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["tapia"] = module
    spec.loader.exec_module(module)
