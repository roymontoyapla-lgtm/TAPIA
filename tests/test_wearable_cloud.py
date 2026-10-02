# -*- coding: utf-8 -*-
"""
Tests de la carga de wearable desde la nube:
adaptador de Health Auto Export, cliente de Dropbox y sincronizacion.

No se hace ninguna llamada de red: `requests` se sustituye por un doble.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from tapia.wearables import cloud as cloud_mod
from tapia.wearables.adapter_apple_auto import AppleAutoExportAdapter
from tapia.wearables.cloud import CloudFile, CloudSource, CloudSourceError, DropboxSource
from tapia.wearables.detector import detect_and_normalize, load_and_detect
from tapia.wearables.sync import sync_patient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metric(name: str, units: str, puntos: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"name": name, "units": units, "data": puntos}


def _payload(*metricas) -> Dict[str, Any]:
    return {"data": {"metrics": list(metricas), "workouts": []}}


def _dia_completo(fecha: str = "2026-09-01") -> Dict[str, Any]:
    marca = f"{fecha} 00:00:00 +0200"
    return _payload(
        _metric("step_count",              "count",     [{"date": marca, "qty": 7500}]),
        _metric("resting_heart_rate",      "count/min", [{"date": marca, "Avg": 58}]),
        _metric("sleep_analysis",          "hr",        [{"date": marca, "asleep": 7.2}]),
        _metric("apple_exercise_time",     "min",       [{"date": marca, "qty": 35}]),
        _metric("heart_rate_variability",  "ms",        [{"date": marca, "qty": 42}]),
        _metric("respiratory_rate",        "count/min", [{"date": marca, "Avg": 15}]),
    )


# ---------------------------------------------------------------------------
# Adaptador de Health Auto Export
# ---------------------------------------------------------------------------

class TestAppleAutoExportAdapter:

    def test_normaliza_un_dia_completo(self):
        registros, nombre = detect_and_normalize(_dia_completo())
        assert nombre == "apple_auto_export"
        assert len(registros) == 1
        r = registros[0]
        assert r.fecha == "2026-09-01"
        assert r.pulso_reposo_bpm_media == 58
        assert r.pasos == 7500
        assert r.sueno_asleep_horas == 7.2
        assert r.min_ejercicio == 35
        assert r.hrv_sdnn_ms_media == 42
        assert r.respiraciones_por_min_media == 15

    def test_suma_los_pasos_del_mismo_dia(self):
        """Con agregacion horaria llegan varios puntos por dia."""
        datos = _payload(_metric("step_count", "count", [
            {"date": "2026-09-01 08:00:00 +0200", "qty": 3000},
            {"date": "2026-09-01 14:00:00 +0200", "qty": 2500},
            {"date": "2026-09-01 20:00:00 +0200", "qty": 2000},
        ]))
        registros = AppleAutoExportAdapter().normalize(datos)
        assert registros[0].pasos == 7500

    def test_promedia_la_frecuencia_cardiaca_del_mismo_dia(self):
        datos = _payload(_metric("resting_heart_rate", "count/min", [
            {"date": "2026-09-01 08:00:00 +0200", "Avg": 60},
            {"date": "2026-09-01 20:00:00 +0200", "Avg": 70},
        ]))
        registros = AppleAutoExportAdapter().normalize(datos)
        assert registros[0].pulso_reposo_bpm_media == 65

    def test_sueno_en_minutos_se_convierte_a_horas(self):
        datos = _payload(_metric("sleep_analysis", "min", [
            {"date": "2026-09-01 00:00:00 +0200", "asleep": 432},
        ]))
        registros = AppleAutoExportAdapter().normalize(datos)
        assert registros[0].sueno_asleep_horas == 7.2

    def test_sueno_a_partir_de_las_fases(self):
        """Si no viene 'asleep', se suman las fases (sin contar el desvelo)."""
        datos = _payload(_metric("sleep_analysis", "hr", [
            {"date": "2026-09-01 00:00:00 +0200",
             "core": 4.0, "deep": 1.2, "rem": 1.6, "awake": 0.5, "inBed": 8.0},
        ]))
        registros = AppleAutoExportAdapter().normalize(datos)
        assert registros[0].sueno_asleep_horas == 6.8

    def test_varios_dias_ordenados(self):
        datos = _payload(_metric("step_count", "count", [
            {"date": "2026-09-03 00:00:00 +0200", "qty": 9000},
            {"date": "2026-09-01 00:00:00 +0200", "qty": 7000},
            {"date": "2026-09-02 00:00:00 +0200", "qty": 8000},
        ]))
        registros = AppleAutoExportAdapter().normalize(datos)
        assert [r.fecha for r in registros] == ["2026-09-01", "2026-09-02", "2026-09-03"]

    def test_acepta_payload_sin_envolver(self):
        datos = {"metrics": [_metric("step_count", "count",
                                     [{"date": "2026-09-01 00:00:00 +0200", "qty": 5000}])]}
        registros, nombre = detect_and_normalize(datos)
        assert nombre == "apple_auto_export"
        assert registros[0].pasos == 5000

    def test_acepta_lista_de_payloads_por_lotes(self):
        """La app parte los envios grandes en varias peticiones."""
        datos = [_dia_completo("2026-09-01"), _dia_completo("2026-09-02")]
        registros, nombre = detect_and_normalize(datos)
        assert nombre == "apple_auto_export"
        assert len(registros) == 2

    def test_ignora_metricas_desconocidas(self):
        datos = _payload(
            _metric("blood_glucose", "mg/dL", [{"date": "2026-09-01 00:00:00 +0200", "qty": 95}]),
            _metric("step_count",    "count", [{"date": "2026-09-01 00:00:00 +0200", "qty": 5000}]),
        )
        registros = AppleAutoExportAdapter().normalize(datos)
        assert len(registros) == 1
        assert registros[0].pasos == 5000

    def test_descarta_puntos_sin_fecha_valida(self):
        datos = _payload(_metric("step_count", "count", [
            {"qty": 1000},
            {"date": "no-es-fecha", "qty": 2000},
            {"date": "2026-09-01 00:00:00 +0200", "qty": 3000},
        ]))
        registros = AppleAutoExportAdapter().normalize(datos)
        assert len(registros) == 1
        assert registros[0].pasos == 3000

    def test_no_secuestra_otros_formatos(self):
        """El adaptador nuevo no debe capturar los formatos ya soportados."""
        adaptador = AppleAutoExportAdapter()
        tapia  = [{"fecha": "2026-09-01", "pasos": 5000}]
        fitbit = [{"dateTime": "2026-09-01", "value": {"steps": 5000}}]
        apple  = [{"date": "2026-09-01", "restingHeartRate": 60}]
        assert adaptador.can_handle(tapia)  is False
        assert adaptador.can_handle(fitbit) is False
        assert adaptador.can_handle(apple)  is False
        assert detect_and_normalize(fitbit)[1] == "fitbit"
        assert detect_and_normalize(apple)[1]  == "apple_health"

    def test_desde_bytes_json(self):
        registros, nombre = load_and_detect(json.dumps(_dia_completo()).encode("utf-8"))
        assert nombre == "apple_auto_export"
        assert registros[0]["pasos"] == 7500


# ---------------------------------------------------------------------------
# Cliente de Dropbox
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_requests(monkeypatch):
    """Sustituye requests dentro del modulo cloud."""
    modulo = MagicMock()
    monkeypatch.setattr(cloud_mod, "_requests", lambda: modulo)
    return modulo


def _resp(status=200, payload=None, content=b""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {}
    r.content = content
    r.text = json.dumps(payload) if payload else ""
    return r


def _entry(name, modified, tag="file"):
    return {".tag": tag, "name": name, "path_lower": f"/{name}",
            "server_modified": modified, "size": 100}


class TestDropboxSource:

    def test_no_configurado_sin_credenciales(self):
        source = DropboxSource(app_key="", app_secret="", refresh_token="", access_token="")
        assert source.is_configured() is False
        assert "DROPBOX_APP_KEY" in source.missing_config()

    def test_configurado_con_token_de_refresco(self):
        source = DropboxSource(app_key="k", app_secret="s", refresh_token="r", access_token="")
        assert source.is_configured() is True
        assert source.missing_config() == []

    def test_configurado_con_token_directo(self):
        source = DropboxSource(app_key="", app_secret="", refresh_token="", access_token="tok")
        assert source.is_configured() is True

    def test_renueva_el_token_antes_de_listar(self, fake_requests):
        fake_requests.post.side_effect = [
            _resp(payload={"access_token": "nuevo-token"}),
            _resp(payload={"entries": [_entry("a.json", "2026-09-01T10:00:00Z")], "has_more": False}),
        ]
        source = DropboxSource(app_key="k", app_secret="s", refresh_token="r", access_token="")
        ficheros = source.list_files()
        assert [f.name for f in ficheros] == ["a.json"]
        cabeceras = fake_requests.post.call_args_list[1].kwargs["headers"]
        assert cabeceras["Authorization"] == "Bearer nuevo-token"

    def test_token_de_refresco_invalido_da_error_claro(self, fake_requests):
        fake_requests.post.return_value = _resp(status=400, payload={"error": "invalid_grant"})
        source = DropboxSource(app_key="k", app_secret="s", refresh_token="malo", access_token="")
        with pytest.raises(CloudSourceError, match="refresco"):
            source.list_files()

    def test_filtra_por_extension(self, fake_requests):
        fake_requests.post.return_value = _resp(payload={"entries": [
            _entry("salud.json", "2026-09-01T10:00:00Z"),
            _entry("notas.txt",  "2026-09-01T11:00:00Z"),
            _entry("carpeta",    "2026-09-01T12:00:00Z", tag="folder"),
        ], "has_more": False})
        source = DropboxSource(access_token="tok")
        assert [f.name for f in source.list_files()] == ["salud.json"]

    def test_filtra_por_fecha_de_modificacion(self, fake_requests):
        fake_requests.post.return_value = _resp(payload={"entries": [
            _entry("viejo.json", "2026-08-01T10:00:00Z"),
            _entry("nuevo.json", "2026-09-01T10:00:00Z"),
        ], "has_more": False})
        source = DropboxSource(access_token="tok")
        ficheros = source.list_files(since="2026-08-15T00:00:00Z")
        assert [f.name for f in ficheros] == ["nuevo.json"]

    def test_pagina_resultados(self, fake_requests):
        fake_requests.post.side_effect = [
            _resp(payload={"entries": [_entry("a.json", "2026-09-01T10:00:00Z")],
                           "has_more": True, "cursor": "c1"}),
            _resp(payload={"entries": [_entry("b.json", "2026-09-02T10:00:00Z")],
                           "has_more": False}),
        ]
        source = DropboxSource(access_token="tok")
        assert [f.name for f in source.list_files()] == ["a.json", "b.json"]

    def test_devuelve_ordenado_por_fecha(self, fake_requests):
        fake_requests.post.return_value = _resp(payload={"entries": [
            _entry("c.json", "2026-09-03T10:00:00Z"),
            _entry("a.json", "2026-09-01T10:00:00Z"),
            _entry("b.json", "2026-09-02T10:00:00Z"),
        ], "has_more": False})
        source = DropboxSource(access_token="tok")
        assert [f.name for f in source.list_files()] == ["a.json", "b.json", "c.json"]

    def test_descarga_devuelve_bytes(self, fake_requests):
        fake_requests.post.return_value = _resp(content=b'{"data": {}}')
        source = DropboxSource(access_token="tok")
        assert source.download("/a.json") == b'{"data": {}}'
        cabeceras = fake_requests.post.call_args.kwargs["headers"]
        assert json.loads(cabeceras["Dropbox-API-Arg"]) == {"path": "/a.json"}

    def test_error_de_descarga(self, fake_requests):
        fake_requests.post.return_value = _resp(status=409, payload={"error": "not_found"})
        source = DropboxSource(access_token="tok")
        with pytest.raises(CloudSourceError, match="409"):
            source.download("/no-existe.json")

    def test_error_de_red_no_escapa_sin_envolver(self, fake_requests):
        fake_requests.post.side_effect = OSError("sin conexion")
        source = DropboxSource(access_token="tok")
        with pytest.raises(CloudSourceError):
            source.list_files()


# ---------------------------------------------------------------------------
# Sincronizacion
# ---------------------------------------------------------------------------

class FakeSource(CloudSource):
    """Origen en memoria para probar la sincronizacion sin red."""

    NAME = "fake"
    DESCRIPTION = "Origen de prueba"

    def __init__(self, ficheros: Dict[str, bytes], modificados: Dict[str, str],
                 configurado: bool = True):
        self.ficheros    = ficheros
        self.modificados = modificados
        self.configurado = configurado
        self.descargas: List[str] = []

    def is_configured(self) -> bool:
        return self.configurado

    def list_files(self, since=None):
        salida = [
            CloudFile(path=n, name=n, modified=self.modificados[n])
            for n in sorted(self.ficheros, key=lambda x: self.modificados[x])
        ]
        if since:
            salida = [f for f in salida if f.modified > since]
        return salida

    def download(self, path: str) -> bytes:
        self.descargas.append(path)
        return self.ficheros[path]


@pytest.fixture
def sync_db(tmp_path, monkeypatch):
    import tapia.db.database as database_module
    monkeypatch.setattr(database_module, "_DB_PATH", tmp_path / "sync.db")
    database_module.init_db()
    return database_module


def _fake_source(dias=("2026-09-01", "2026-09-02")):
    ficheros    = {f"{d}.json": json.dumps(_dia_completo(d)).encode() for d in dias}
    modificados = {f"{d}.json": f"{d}T23:00:00Z" for d in dias}
    return FakeSource(ficheros, modificados)


class TestSync:

    def test_importa_los_ficheros_nuevos(self, sync_db):
        pid = sync_db.get_or_create_patient("Ana Sync", 40, "F")
        resultado = sync_patient(pid, source=_fake_source())
        assert resultado.files_imported == 2
        assert resultado.days_inserted == 2
        assert resultado.adapters == ["apple_auto_export"]
        assert len(sync_db.get_wearable_history(pid)) == 2

    def test_segunda_pasada_no_duplica(self, sync_db):
        pid = sync_db.get_or_create_patient("Ana Sync", 40, "F")
        source = _fake_source()
        sync_patient(pid, source=source)
        segunda = sync_patient(pid, source=source)
        # La marca guardada evita volver a descargar lo ya leido
        assert segunda.files_seen == 0
        assert len(sync_db.get_wearable_history(pid)) == 2

    def test_releer_todo_no_duplica_dias(self, sync_db):
        pid = sync_db.get_or_create_patient("Ana Sync", 40, "F")
        source = _fake_source()
        sync_patient(pid, source=source)
        completa = sync_patient(pid, source=source, full=True)
        assert completa.files_imported == 2
        assert completa.days_inserted == 0      # ya estaban
        assert completa.days_skipped == 2
        assert len(sync_db.get_wearable_history(pid)) == 2

    def test_solo_descarga_lo_nuevo(self, sync_db):
        pid = sync_db.get_or_create_patient("Ana Sync", 40, "F")
        source = _fake_source(("2026-09-01",))
        sync_patient(pid, source=source)
        source.ficheros["2026-09-05.json"]    = json.dumps(_dia_completo("2026-09-05")).encode()
        source.modificados["2026-09-05.json"] = "2026-09-05T23:00:00Z"
        segunda = sync_patient(pid, source=source)
        assert segunda.files_imported == 1
        assert source.descargas == ["2026-09-01.json", "2026-09-05.json"]

    def test_guarda_el_estado_de_sincronizacion(self, sync_db):
        pid = sync_db.get_or_create_patient("Ana Sync", 40, "F")
        sync_patient(pid, source=_fake_source())
        estado = sync_db.get_sync_state(pid, "fake")
        assert estado["files_imported"] == 2
        assert estado["last_file"] == "2026-09-02.json"
        assert estado["last_modified"] == "2026-09-02T23:00:00Z"

    def test_origen_sin_configurar_avisa(self, sync_db):
        pid = sync_db.get_or_create_patient("Ana Sync", 40, "F")
        source = FakeSource({}, {}, configurado=False)
        resultado = sync_patient(pid, source=source)
        assert resultado.files_imported == 0
        assert any("no esta configurado" in e for e in resultado.errors)

    def test_sin_ficheros_nuevos(self, sync_db):
        pid = sync_db.get_or_create_patient("Ana Sync", 40, "F")
        resultado = sync_patient(pid, source=FakeSource({}, {}))
        assert resultado.files_seen == 0
        assert "No hay ficheros nuevos" in resultado.summary()

    def test_fichero_ilegible_no_corta_la_sincronizacion(self, sync_db):
        pid = sync_db.get_or_create_patient("Ana Sync", 40, "F")
        source = _fake_source()
        source.ficheros["roto.json"]    = b"{no es json valido"
        source.modificados["roto.json"] = "2026-09-03T23:00:00Z"
        resultado = sync_patient(pid, source=source)
        assert resultado.files_imported == 2       # los dos buenos entraron
        assert any("roto.json" in e for e in resultado.errors)

    def test_respeta_el_tope_de_ficheros(self, sync_db):
        pid = sync_db.get_or_create_patient("Ana Sync", 40, "F")
        source = _fake_source(("2026-09-01", "2026-09-02", "2026-09-03"))
        resultado = sync_patient(pid, source=source, max_files=2)
        assert resultado.files_imported == 2
        assert resultado.pending_files == 1
        assert "pendientes" in resultado.summary()


class TestSyncConDropbox:
    """Cadena completa: Dropbox -> descarga -> adaptador -> base de datos."""

    def test_flujo_completo(self, sync_db, fake_requests):
        pid = sync_db.get_or_create_patient("Luis Dropbox", 55, "M")
        contenido = json.dumps(_dia_completo("2026-09-01")).encode()

        fake_requests.post.side_effect = [
            _resp(payload={"access_token": "tok"}),                       # refresco
            _resp(payload={"entries": [_entry("HealthAutoExport-2026-09-01.json",
                                              "2026-09-01T23:00:00Z")],
                           "has_more": False}),                           # listado
            _resp(payload={"access_token": "tok"}),                       # refresco
            _resp(content=contenido),                                     # descarga
        ]

        source = DropboxSource(app_key="k", app_secret="s", refresh_token="r", access_token="")
        resultado = sync_patient(pid, source=source)

        assert resultado.files_imported == 1
        assert resultado.days_inserted == 1
        assert resultado.adapters == ["apple_auto_export"]

        historial = sync_db.get_wearable_history(pid)
        assert len(historial) == 1
        assert historial[0]["fecha"] == "2026-09-01"
        assert historial[0]["pasos"] == 7500
        assert historial[0]["sueno_asleep_horas"] == 7.2

        # El origen queda registrado en la tabla (el historial devuelve el
        # formato que consume core.wearable, sin la columna source)
        with sync_db._connect() as conn:
            origen = conn.execute(
                "SELECT source FROM wearable_data WHERE patient_id = ?", (pid,)
            ).fetchone()["source"]
        assert origen == "apple_auto_export"

        estado = sync_db.get_sync_state(pid, "dropbox")
        assert estado["last_file"] == "HealthAutoExport-2026-09-01.json"
