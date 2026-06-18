# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import threading
import time

from .compat import ensure_text
from .debuglog import write_debug, write_exception
from .paths import CHANNELS_PATH, IMPORT_DIR, SOURCES_PATH
from .settings import get_import_routine


class EPGImportResult(object):
    def __init__(self, started, message, installed=False, ready=False,
                 source_count=0, source_descriptions=None, error="",
                 monitor_started_at=None, selected_routine=None):
        self.started = started
        self.message = message
        self.installed = installed
        self.ready = ready
        self.source_count = source_count
        self.source_descriptions = source_descriptions or []
        self.error = error
        self.monitor_started_at = monitor_started_at
        self.selected_routine = selected_routine


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


def _epgcache_supports_route_a(epgcache):
    """Route A braucht den EPGImport/Oudeis-Patch (importEvents oder importEvent)."""
    return bool(epgcache is not None and
                (hasattr(epgcache, "importEvents") or hasattr(epgcache, "importEvent")))


def _routine_label(selected_routine):
    """Mappt die intern gewählte Routine (a1/a2/b) auf einen Anzeigenamen."""
    if selected_routine in ("a1", "a2"):
        return "Routine A"
    if selected_routine == "b":
        return "Routine B"
    return None


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
    _inspect_epgdb("after")


def _set_hdd_epg_dat(engine_mod):
    try:
        from Components.config import config
        value = config.misc.epgcache_filename.value
        engine_mod.HDD_EPG_DAT = value
        write_debug("HDD_EPG_DAT=" + ensure_text(value), "epgimport")
    except Exception as exc:
        write_exception("set HDD_EPG_DAT failed", exc)


def _fmt_epoch(value):
    """Epoch-Sekunden -> lesbares Datum (oder Rohwert bei Fehlern)."""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(value)))
    except Exception:
        return ensure_text(value)


def _log_cache_config():
    """Diagnose: relevante eEPGCache-/EPG-Konfiguration loggen.

    Wichtig fuer die Timespan-Hypothese: wenn epgcache_timespan auf dem SDK-Image
    kleiner ist als das Quell-Fenster, werden Events jenseits davon verworfen.
    """
    try:
        from Components.config import config
    except Exception as exc:
        write_debug("cache config unavailable: " + ensure_text(exc), "diag")
        return
    misc = getattr(config, "misc", None)
    for name in ("epgcache_timespan", "epgcache_outdated_timespan",
                 "epgcache_filename", "epgcache_maxdays", "epgmaxdays"):
        try:
            node = getattr(misc, name, None)
            if node is not None:
                write_debug("config.misc.%s=%s" % (name, ensure_text(node.value)), "diag")
        except Exception as exc:
            write_debug("config.misc.%s read failed: %s" % (name, ensure_text(exc)), "diag")


def _epgdb_path():
    try:
        from Components.config import config
        return config.misc.epgcache_filename.value
    except Exception:
        return None


def _inspect_epgdb(label):
    """Diagnose: epg.db read-only inspizieren (Existenz, Groesse, Event-Horizont).

    Zeigt direkt, ob sich max(begin_time) durch den Import bewegt -- fuer Route A
    und B. Vollstaendig defensiv: Datei kann fehlen oder .dat statt .db sein.
    """
    import os as _os
    path = _epgdb_path()
    if not path:
        write_debug("epgdb[%s]: path unknown" % label, "diag")
        return
    if not _os.path.exists(path):
        write_debug("epgdb[%s]: %s does not exist" % (label, ensure_text(path)), "diag")
        return
    try:
        size = _os.path.getsize(path)
    except Exception:
        size = -1
    write_debug("epgdb[%s]: %s size=%d" % (label, ensure_text(path), size), "diag")
    if not ensure_text(path).endswith(".db"):
        return  # epg_new.dat o.ae. -> keine SQLite-Inspektion
    try:
        from sqlite3 import dbapi2 as sqlite
    except Exception as exc:
        write_debug("epgdb[%s]: sqlite unavailable: %s" % (label, ensure_text(exc)), "diag")
        return
    conn = None
    try:
        conn = sqlite.connect(path, timeout=5)
        conn.text_factory = str
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), MAX(begin_time) FROM T_Event")
        total, max_begin = cur.fetchone()
        write_debug("epgdb[%s]: T_Event total=%s max_begin=%s" % (
            label, ensure_text(total),
            _fmt_epoch(max_begin) if max_begin is not None else "none"), "diag")
        cur.execute(
            "SELECT s.source_name, COUNT(*), MAX(e.begin_time) "
            "FROM T_Event e LEFT JOIN T_Source s ON e.source_id = s.id "
            "GROUP BY e.source_id ORDER BY COUNT(*) DESC")
        for row in cur.fetchall():
            src, cnt, mb = row
            write_debug("epgdb[%s]: source=%s count=%s max_begin=%s" % (
                label, ensure_text(src), ensure_text(cnt),
                _fmt_epoch(mb) if mb is not None else "none"), "diag")
    except Exception as exc:
        write_debug("epgdb[%s]: inspect failed: %s" % (label, ensure_text(exc)), "diag")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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

    routine = get_import_routine()
    if routine == "a" and not _epgcache_supports_route_a(engine.epgcache):
        write_debug("start blocked: routine a unsupported", "epgimport")
        message = ("Routine A wird von dieser Box nicht unterstützt "
                   "(kein importEvents/importEvent-Patch). Bitte Routine B oder Auto wählen.")
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
        engine.force_routine = routine
        write_debug("force_routine=" + routine, "epgimport")
        _log_cache_config()
        _inspect_epgdb("before")
        engine.beginImport(longDescUntil=time.time() + 7 * 24 * 3600)
    except Exception as exc:
        write_exception("beginImport failed", exc)
        message = "EPG-Import konnte nicht gestartet werden: " + ensure_text(exc)
        return EPGImportResult(False, message, installed=True, ready=True,
                               source_count=source_count,
                               source_descriptions=loaded_descriptions,
                               error=message)

    selected_routine = getattr(engine, "selected_routine", None)
    write_debug("selected_routine=" + str(selected_routine), "epgimport")
    message = "EPG-Import gestartet: " + str(source_count) + " Quelle(n)"
    routine_label = _routine_label(selected_routine)
    if routine_label:
        message += " (" + routine_label + ")"
    write_debug("start ok source_count=" + str(source_count), "epgimport")
    return EPGImportResult(True, message,
                           installed=True, ready=True, source_count=source_count,
                           source_descriptions=loaded_descriptions,
                           selected_routine=selected_routine,
                           monitor_started_at=monitor_started_at)
