# -*- coding: utf-8 -*-
"""Punto de entrada de TAPIA (interfaz de escritorio)."""

import importlib.util
import sys
from pathlib import Path

# El codigo importa con `tapia.ui...`, pero el directorio clonado puede
# llamarse TAPIA, tapia-main o cualquier otra cosa: se registra esta
# carpeta como el paquete `tapia` antes de importar nada del proyecto.
ROOT = Path(__file__).resolve().parent

if "tapia" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "tapia",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["tapia"] = _module
    _spec.loader.exec_module(_module)

from tapia.ui.app import App


def main() -> None:
    """Arranca la interfaz de escritorio."""
    App().mainloop()


if __name__ == "__main__":
    main()
