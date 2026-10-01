# -*- coding: utf-8 -*-
"""
Diagnostico de un fichero de wearable que TAPIA no consigue leer.

    python scripts/diagnose_wearable.py "C:\\ruta\\al\\fichero.json"

Dice que adaptador reconoce el fichero, cuantos dias saca cada uno y, para
los JSON de Health Auto Export, que metricas trae y cuales entiende TAPIA.

Solo imprime estructura (claves, nombres de metrica, formato de fecha y
numero de valores): nunca valores de salud, para poder pegar la salida sin
compartir datos personales.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent

MAX_CLAVES = 15


def _bootstrap() -> None:
    if "tapia" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "tapia", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)],
        )
        modulo = importlib.util.module_from_spec(spec)
        sys.modules["tapia"] = modulo
        spec.loader.exec_module(modulo)


def describe_payload(datos: Any) -> List[str]:
    """Describe la forma del JSON sin mostrar valores."""
    lineas = []
    if isinstance(datos, list):
        lineas.append(f"Tipo: lista de {len(datos)} elemento(s)")
        if datos and isinstance(datos[0], dict):
            lineas.append(f"Claves del primer elemento: {list(datos[0])[:MAX_CLAVES]}")
    elif isinstance(datos, dict):
        lineas.append(f"Tipo: objeto con claves {list(datos)[:MAX_CLAVES]}")
        interior = datos.get("data")
        if isinstance(interior, dict):
            lineas.append(f"  data -> claves {list(interior)[:MAX_CLAVES]}")
    else:
        lineas.append(f"Tipo: {type(datos).__name__}")
    return lineas


def describe_metrics(datos: Any) -> List[str]:
    """Para Health Auto Export: metricas presentes y cuales entiende TAPIA."""
    from tapia.wearables.adapter_apple_auto import _METRIC_MAP, _extract_metrics

    metricas = _extract_metrics(datos)
    if not metricas:
        return []

    lineas = ["", f"Metricas en el fichero ({len(metricas)}):"]
    reconocidas = 0
    for metrica in metricas:
        if not isinstance(metrica, dict):
            continue
        nombre = str(metrica.get("name", "")).strip()
        campo  = _METRIC_MAP.get(nombre.lower())
        puntos = metrica.get("data") or []
        marca  = f"-> {campo}" if campo else "(TAPIA la ignora)"
        if campo:
            reconocidas += 1
        unidades = metrica.get("units", "")
        lineas.append(f"  {nombre:<32} {len(puntos):>5} punto(s)  [{unidades}] {marca}")

        if puntos and isinstance(puntos[0], dict):
            claves = [k for k in puntos[0] if k != "date"]
            fecha  = str(puntos[0].get("date", ""))
            lineas.append(f"      campos: {claves[:MAX_CLAVES]}")
            lineas.append(f"      formato de fecha: {fecha!r}")

    lineas.append(f"\n  Reconocidas por TAPIA: {reconocidas} de {len(metricas)}")
    return lineas


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnostica un fichero de wearable que TAPIA no lee."
    )
    parser.add_argument("fichero", help="Ruta al JSON (o XML/ZIP) exportado")
    args = parser.parse_args()

    ruta = Path(args.fichero)
    if not ruta.exists():
        raise SystemExit(f"\nNo existe el fichero: {ruta}\n")

    _bootstrap()
    from tapia.wearables.detector import _ADAPTERS

    crudo = ruta.read_bytes()
    print(f"\n=== {ruta.name} ({len(crudo):,} bytes) ===\n")

    try:
        datos: Any = json.loads(crudo.decode("utf-8"))
        print("JSON valido.")
    except Exception as e:
        print(f"No es JSON ({e}); se trata como XML/ZIP de Apple Health.")
        datos = crudo

    if not isinstance(datos, (bytes, bytearray)):
        for linea in describe_payload(datos):
            print(linea)
        for linea in describe_metrics(datos):
            print(linea)

    print("\nAdaptadores:")
    alguno = False
    for adaptador in _ADAPTERS:
        try:
            acepta = adaptador.can_handle(datos)
        except Exception as e:
            print(f"  {adaptador.NAME:<22} error al comprobar: {e}")
            continue
        if not acepta:
            print(f"  {adaptador.NAME:<22} no")
            continue

        alguno = True
        try:
            registros = adaptador.normalize(datos)
        except Exception as e:
            print(f"  {adaptador.NAME:<22} SI, pero falla al normalizar: {e}")
            continue

        print(f"  {adaptador.NAME:<22} SI -> {len(registros)} dia(s)")
        if registros:
            r = registros[0]
            print(f"      primer dia: {r.fecha} | "
                  f"pasos={_hay(r.pasos)} fc={_hay(r.pulso_reposo_bpm_media)} "
                  f"sueno={_hay(r.sueno_asleep_horas)} ejercicio={_hay(r.min_ejercicio)} "
                  f"hrv={_hay(r.hrv_sdnn_ms_media)}")

    if not alguno:
        print("\n  Ningun adaptador reconoce este fichero.")
    print()


def _hay(valor: Any) -> str:
    """Dice si hay dato, sin revelar el valor."""
    return "si" if valor is not None else "NO"


if __name__ == "__main__":
    main()
