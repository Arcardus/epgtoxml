# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import threading
import time

from .compat import ensure_text
from .debuglog import write_debug, write_exception
from .paths import CHANNELS_PATH, IMPORT_DIR, SOURCES_PATH


class EPGImportResult(object):
    def __init__(self, started, message, installed=False, ready=False,
                 source_count=0, source_descriptions=None, error="",
                 monitor_started_at=None):
        self.started = started
        self.message = message
        self.installed = installed
        self.ready = ready
        self.source_count = source_count
        self.source_descriptions = source_descriptions or []
        self.error = error
        self.monitor_started_at = monitor_started_at


class EPGImportProbeResult(object):
    def __init__(self, installed=False, ready=False, running=False, message=""):
        self.installed = installed
        self.ready = ready
        self.running = running
        self.message = message


def _as_list(values):
    if values is None:
        return []
    if isinstance(values, (list, tuple)):
        return list(values)
    return [values]


# Modul-globaler Zustand: die eingebettete Import-Engine lebt im Haupt-Enigma2-
# Prozess und wird genau einmal an den aktiven eEPGCache gebunden. Das Ergebnis
# des letzten Imports merken wir uns, damit plugin.py es pollen kann.
_engine = None
_last_import_result = None
_log_bridge_installed = False


class _LineBridge(object):
    """Sammelt write()-Fragmente der Engine und gibt vollständige Zeilen an sink.

    Die eingebettete Engine loggt via ``print>>log, ...``; das erzeugt mehrere
    write()-Aufrufe pro Logzeile (je Argument, Trenner und abschließendes "\\n").
    Wir puffern bis zum Zeilenumbruch, damit im Debuglog ganze Zeilen mit genau
    einem Timestamp landen statt zerstückelter Fragmente.
    """

    def __init__(self, sink):
        self._sink = sink
        self._buf = []
        self._lock = threading.Lock()

    def write(self, data):
        try:
            self._lock.acquire()
            try:
                self._buf.append(ensure_text(data))
                joined = "".join(self._buf)
                if "\n" not in joined:
                    return
                parts = joined.split("\n")
                self._buf[:] = [parts[-1]]  # angefangene Zeile behalten
                lines = parts[:-1]
            finally:
                self._lock.release()
            for line in lines:
                line = line.rstrip("\r")
                if line:
                    self._sink(line)
        except Exception as exc:
            write_exception("log bridge write failed", exc)


def _install_log_bridge():
    """Leitet die Ausgabe der eingebetteten Engine in unseren Debuglog um.

    Ersetzt ``epgimport_engine.log.write`` (statt es zu wrappen), daher entfällt
    die bisherige sys.stdout-/Ringpuffer-Ausgabe — die Engine-Zeilen landen nur
    noch im Debuglog (category="engine", an das Debug-Flag gekoppelt).
    """
    global _log_bridge_installed
    if _log_bridge_installed:
        return
    try:
        from .epgimport_engine import log as engine_log
    except Exception as exc:
        write_debug("log bridge unavailable: " + ensure_text(exc), "epgimport")
        return
    engine_log.write = _LineBridge(lambda line: write_debug(line, "engine")).write
    _log_bridge_installed = True
    write_debug("engine log bridge installed", "epgimport")


def _channel_filter(ref):
    # Wir schreiben die channels.xml selbst und nehmen nur unsere Zielsender auf,
    # daher alle Referenzen akzeptieren (vermeidet NavigationInstance/recordService).
    return True


def _load_engine():
    """Lazy-Import der eingebetteten Engine (lädt twisted/enigma -> nur auf der Box)."""
    from .epgimport_engine import EPGImport as engine_mod
    from .epgimport_engine import EPGConfig as config_mod
    _install_log_bridge()
    return engine_mod, config_mod


def _epgcache_instance():
    try:
        from enigma import eEPGCache
        return eEPGCache.getInstance()
    except Exception:
        return None


def _get_engine(engine_mod):
    global _engine
    if _engine is None:
        _engine = engine_mod.EPGImport(_epgcache_instance(), _channel_filter)
        write_debug("engine instance created", "epgimport")
    return _engine


def reset_engine():
    """Setzt den Engine-Singleton zurück (für Tests)."""
    global _engine, _last_import_result, _log_bridge_installed
    _engine = None
    _last_import_result = None
    _log_bridge_installed = False


def _done_import(reboot=False, epgfile=None):
    global _last_import_result
    count = 0
    try:
        if _engine is not None and _engine.eventCount is not None:
            count = int(_engine.eventCount)
    except Exception:
        count = 0
    _last_import_result = (time.time(), count)
    write_debug("import done events=%d reboot=%s" % (count, reboot), "epgimport")


def _set_hdd_epg_dat(engine_mod):
    try:
        from Components.config import config
        value = config.misc.epgcache_filename.value
        engine_mod.HDD_EPG_DAT = value
        write_debug("HDD_EPG_DAT=" + ensure_text(value), "epgimport")
    except Exception as exc:
        write_exception("set HDD_EPG_DAT failed", exc)


def probe_epgimport():
    try:
        engine_mod, _config_mod = _load_engine()
    except Exception as exc:
        write_debug("probe engine unavailable: " + ensure_text(exc), "epgimport")
        return EPGImportProbeResult(False, False, False,
                                    "EPG-Import: Engine fehlt (" + ensure_text(exc) + ")")
    try:
        engine = _get_engine(engine_mod)
        running = bool(engine.isImportRunning())
    except Exception as exc:
        write_exception("probe running state failed", exc)
        return EPGImportProbeResult(True, False, False,
                                    "EPG-Import: Status nicht lesbar (" + ensure_text(exc) + ")")
    if running:
        write_debug("probe running", "epgimport")
        return EPGImportProbeResult(True, True, True, "EPG-Import: läuft bereits")
    write_debug("probe ready", "epgimport")
    return EPGImportProbeResult(True, True, False, "EPG-Import: bereit")


def read_last_import_result():
    return _last_import_result


def start_epgimport(session=None, logger=None, source_descriptions=None, config_path=IMPORT_DIR):
    """Importiert die generierten EpgToXml-Quellen in-process in den EPG-Cache."""
    def log(text):
        if logger:
            logger(text)

    descriptions = [ensure_text(item) for item in _as_list(source_descriptions) if item]
    write_debug("start requested descriptions=" + ", ".join(descriptions), "epgimport")
    try:
        engine_mod, config_mod = _load_engine()
    except Exception as exc:
        write_exception("start engine load failed", exc)
        message = "EPG-Engine nicht verfügbar: " + ensure_text(exc)
        return EPGImportResult(False, message, installed=False, ready=False, error=message)

    try:
        engine = _get_engine(engine_mod)
    except Exception as exc:
        write_exception("start engine init failed", exc)
        message = "EPG-Engine konnte nicht initialisiert werden: " + ensure_text(exc)
        return EPGImportResult(False, message, installed=True, ready=False, error=message)

    try:
        running = engine.isImportRunning()
    except Exception as exc:
        write_exception("start running state failed", exc)
        message = "EPG-Import-Status nicht lesbar: " + ensure_text(exc)
        return EPGImportResult(False, message, installed=True, ready=False, error=message)
    if running:
        write_debug("start blocked: already running", "epgimport")
        message = "EPG-Import läuft bereits. Bitte später erneut starten."
        return EPGImportResult(False, message, installed=True, ready=True, error=message)

    try:
        filter_values = descriptions or None
        sources = [source for source in config_mod.enumSources(config_path, filter=filter_values)]
    except Exception as exc:
        write_exception("start enumSources failed", exc)
        message = "EPG-Quellen konnten nicht gelesen werden: " + ensure_text(exc)
        return EPGImportResult(False, message, installed=True, ready=True, error=message)

    if not sources:
        if descriptions:
            wanted = ", ".join(descriptions)
        else:
            wanted = "EpgToXml"
        message = (
            "Keine EPG-Quelle gefunden: " + wanted +
            " (sources: " + SOURCES_PATH + ", channels: " + CHANNELS_PATH + ")"
        )
        write_debug("start no source found for " + wanted, "epgimport")
        return EPGImportResult(False, message, installed=True, ready=True, error=message)

    sources.reverse()
    source_count = len(sources)
    loaded_descriptions = [ensure_text(getattr(source, "description", "")) for source in sources]
    monitor_started_at = time.time()
    try:
        engine.sources = list(sources)
        engine.onDone = _done_import
        _set_hdd_epg_dat(engine_mod)
        joined = ", ".join(loaded_descriptions)
        log("EPG-Import Quellen geladen: " + joined)
        write_debug("sources loaded count=%d descriptions=%s" % (source_count, joined), "epgimport")
        engine.beginImport(longDescUntil=time.time() + 7 * 24 * 3600)
    except Exception as exc:
        write_exception("beginImport failed", exc)
        message = "EPG-Import konnte nicht gestartet werden: " + ensure_text(exc)
        return EPGImportResult(False, message, installed=True, ready=True,
                               source_count=source_count,
                               source_descriptions=loaded_descriptions,
                               error=message)

    write_debug("start ok source_count=" + str(source_count), "epgimport")
    return EPGImportResult(True, "EPG-Import gestartet: " + str(source_count) + " Quelle(n)",
                           installed=True, ready=True, source_count=source_count,
                           source_descriptions=loaded_descriptions,
                           monitor_started_at=monitor_started_at)
