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


def describe_apple_xml(crudo: bytes, days: int = 180) -> List[str]:
    """
    Recorre el XML de Apple Health y cuenta que tipos de registro trae y de
    que fechas, que es lo unico que explica un 'SI -> 0 dias'.

    Streaming: no carga el arbol en memoria (estos ficheros pasan del GB).
    """
    import xml.etree.ElementTree as ET
    from collections import Counter
    from datetime import datetime, timedelta

    from tapia.wearables.adapter_apple_xml import (
        _RECORD_TYPES, _SLEEP_ASLEEP, _SLEEP_TYPE, _open_xml_stream,
    )

    corte = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    tipos:     Counter = Counter()
    recientes: Counter = Counter()
    etiquetas: Counter = Counter()
    fechas:    List[str] = []
    total = 0

    try:
        contexto = ET.iterparse(_open_xml_stream(crudo), events=("end",))
        for _, elem in contexto:
            etiquetas[elem.tag] += 1
            if elem.tag == "Record":
                total += 1
                tipo = elem.get("type", "")
                dia  = (elem.get("startDate", "") or "")[:10]
                tipos[tipo] += 1
                if dia:
                    if not fechas:
                        fechas = [dia, dia]
                    else:
                        fechas[0] = min(fechas[0], dia)
                        fechas[1] = max(fechas[1], dia)
                    if dia >= corte:
                        recientes[tipo] += 1
            elem.clear()
    except Exception as e:
        return ["", f"Error recorriendo el XML: {type(e).__name__}: {e}"]

    lineas = ["", f"Elementos del XML: " +
              ", ".join(f"{t}={n}" for t, n in etiquetas.most_common(5))]
    lineas.append(f"Registros <Record>: {total:,}")
    if fechas:
        lineas.append(f"Rango de fechas: {fechas[0]} a {fechas[1]}")
    lineas.append(f"Ventana analizada: ultimos {days} dias (desde {corte})")

    interesantes = set(_RECORD_TYPES) | {_SLEEP_TYPE}
    lineas.append("\nTipos que TAPIA busca:")
    for tipo in sorted(interesantes):
        lineas.append(
            f"  {tipo:<52} total={tipos.get(tipo, 0):>9,} "
            f"en ventana={recientes.get(tipo, 0):>9,}"
        )

    otros = [(t, n) for t, n in tipos.most_common(12) if t not in interesantes]
    if otros:
        lineas.append("\nOtros tipos presentes (los 12 mas frecuentes):")
        for tipo, n in otros:
            lineas.append(f"  {tipo:<52} {n:>9,}")

    if total and not any(recientes.get(t) for t in interesantes):
        lineas.append(
            "\n  >> Hay registros, pero ninguno de los tipos que TAPIA usa "
            "cae dentro de la ventana."
        )
    return lineas


def _ultimo_de_dropbox():
    """Descarga el fichero mas reciente de la carpeta configurada en Dropbox."""
    from tapia.core.config import cfg
    from tapia.wearables.cloud import CloudSourceError, DropboxSource

    source = DropboxSource(
        folder=cfg.wearable_sync.folder,
        extensions=tuple(cfg.wearable_sync.extensions),
    )
    if not source.is_configured():
        faltan = ", ".join(source.missing_config()) or "las credenciales de Dropbox"
        raise SystemExit(
            f"\nDropbox no esta configurado: falta {faltan} en el .env.\n"
            "Ejecuta antes: python scripts/dropbox_setup.py\n"
        )

    carpeta = cfg.wearable_sync.folder or "/ (raiz de la carpeta de la app)"
    try:
        ficheros = source.list_files()
    except CloudSourceError as e:
        raise SystemExit(f"\n{e}\n")

    if not ficheros:
        raise SystemExit(
            f"\nNo hay ficheros en {carpeta}.\n"
            "Comprueba que la automatizacion de Health Auto Export exporta a la\n"
            "carpeta de la app (Aplicaciones/<nombre de tu app>) y no a la raiz\n"
            "de tu Dropbox.\n"
        )

    print(f"\n{len(ficheros)} fichero(s) en {carpeta}; se analiza el mas reciente:")
    for f in ficheros[-5:]:
        print(f"  {f.name}  ({f.modified}, {f.size:,} bytes)")

    ultimo = ficheros[-1]
    return ultimo.name, source.download(ultimo.path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnostica un fichero de wearable que TAPIA no lee."
    )
    parser.add_argument("fichero", nargs="?",
                        help="Ruta al JSON (o XML/ZIP) exportado")
    parser.add_argument("--dropbox", action="store_true",
                        help="Analiza el ultimo fichero que haya dejado el movil en Dropbox")
    parser.add_argument("--dias", type=int, default=180,
                        help="Ventana a analizar en el XML de Apple (por defecto 180)")
    args = parser.parse_args()

    if not args.fichero and not args.dropbox:
        raise SystemExit("\nIndica un fichero, o usa --dropbox para coger el ultimo de la nube.\n")

    _bootstrap()
    from tapia.wearables.detector import _ADAPTERS

    if args.dropbox:
        nombre, crudo = _ultimo_de_dropbox()
    else:
        ruta = Path(args.fichero)
        if not ruta.exists():
            raise SystemExit(f"\nNo existe el fichero: {ruta}\n")
        nombre, crudo = ruta.name, ruta.read_bytes()

    print(f"\n=== {nombre} ({len(crudo):,} bytes) ===\n")

    try:
        datos: Any = json.loads(crudo.decode("utf-8"))
        print("JSON valido.")
    except Exception as e:
        print(f"No es JSON ({e}); se trata como XML/ZIP de Apple Health.")
        datos = crudo

    if isinstance(datos, (bytes, bytearray)):
        print("Recorriendo el XML, puede tardar varios minutos...")
        for linea in describe_apple_xml(datos, days=args.dias):
            print(linea)
    else:
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
        if isinstance(datos, (bytes, bytearray)):
            # Ya se ha recorrido arriba; volver a parsear un XML de 1 GB
            # costaria otros tantos minutos sin aportar nada.
            print(f"  {adaptador.NAME:<22} SI (ver el recuento de arriba)")
            continue

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
