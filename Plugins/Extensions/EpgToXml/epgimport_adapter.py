# -*- coding: utf-8 -*-
from __future__ import absolute_import

import re
import time

from .compat import ensure_text
from .debuglog import write_debug, write_exception
from .paths import CHANNELS_PATH, EPGIMPORT_DIR, SOURCES_PATH


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


def _load_epgimport():
    from Plugins.Extensions.EPGImport import plugin as epg_plugin
    epg_config = getattr(epg_plugin, "EPGConfig", None)
    if epg_config is None:
        try:
            from Plugins.Extensions.EPGImport import EPGConfig as epg_config
        except Exception:
            import EPGConfig as epg_config
    return epg_plugin, epg_config


def probe_epgimport():
    try:
        epg_plugin, epg_config = _load_epgimport()
    except Exception as exc:
        write_debug("probe missing: " + ensure_text(exc), "epgimport")
        return EPGImportProbeResult(False, False, False,
                                    "EPGImport: fehlt (" + ensure_text(exc) + ")")

    epgimport = getattr(epg_plugin, "epgimport", None)
    start_import = getattr(epg_plugin, "startImport", None)
    if epgimport is None or not callable(start_import) or not hasattr(epg_config, "enumSources"):
        write_debug("probe incompatible API", "epgimport")
        return EPGImportProbeResult(True, False, False,
                                    "EPGImport: inkompatible API")

    try:
        running = bool(epgimport.isImportRunning())
    except Exception as exc:
        write_exception("probe running state failed", exc)
        return EPGImportProbeResult(True, False, False,
                                    "EPGImport: Status nicht lesbar (" + ensure_text(exc) + ")")

    if running:
        write_debug("probe running", "epgimport")
        return EPGImportProbeResult(True, True, True,
                                    "EPGImport: Import läuft bereits")
    write_debug("probe ready", "epgimport")
    return EPGImportProbeResult(True, True, False, "EPGImport: bereit")


def _last_import_from_config(epg_plugin):
    try:
        cfg = getattr(epg_plugin, "config", None)
        if cfg is None:
            from Components.config import config as cfg
        value = cfg.plugins.extra_epgimport.last_import.value
    except Exception:
        return None
    text = ensure_text(value)
    matches = re.findall(r"([0-9]+)", text)
    if len(matches) >= 2:
        try:
            return (float(matches[0]), int(matches[1]))
        except Exception:
            return None
    return None


def read_last_import_result():
    try:
        epg_plugin, epg_config = _load_epgimport()
    except Exception as exc:
        write_debug("read result missing EPGImport: " + ensure_text(exc), "epgimport")
        return None
    value = getattr(epg_plugin, "lastImportResult", None)
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            result = (float(value[0]), int(value[1]))
            write_debug("read result plugin=%s/%s" % (result[0], result[1]), "epgimport")
            return result
        except Exception:
            pass
    result = _last_import_from_config(epg_plugin)
    if result is not None:
        write_debug("read result config=%s/%s" % (result[0], result[1]), "epgimport")
    return result


def start_epgimport(session=None, logger=None, source_descriptions=None, config_path=EPGIMPORT_DIR):
    """Start the installed EPGImport plugin for the generated EpgToXml sources."""
    def log(text):
        if logger:
            logger(text)

    descriptions = [ensure_text(item) for item in _as_list(source_descriptions) if item]
    write_debug("start requested descriptions=" + ", ".join(descriptions), "epgimport")
    try:
        epg_plugin, epg_config = _load_epgimport()
    except Exception as exc:
        write_exception("start load failed", exc)
        message = "EPGImport nicht gefunden: " + ensure_text(exc)
        return EPGImportResult(False, message, installed=False, ready=False, error=message)

    epgimport = getattr(epg_plugin, "epgimport", None)
    start_import = getattr(epg_plugin, "startImport", None)
    if epgimport is None or not callable(start_import) or not hasattr(epg_config, "enumSources"):
        write_debug("start incompatible API", "epgimport")
        message = "EPGImport-API nicht erkannt. Quelle liegt bereit: " + SOURCES_PATH
        return EPGImportResult(False, message, installed=True, ready=False, error=message)

    try:
        running = epgimport.isImportRunning()
    except Exception as exc:
        write_exception("start running state failed", exc)
        message = "EPGImport-Status nicht lesbar: " + ensure_text(exc)
        return EPGImportResult(False, message, installed=True, ready=False, error=message)
    if running:
        write_debug("start blocked: already running", "epgimport")
        message = "EPGImport läuft bereits. Bitte später erneut starten."
        return EPGImportResult(False, message, installed=True, ready=True, error=message)

    try:
        filter_values = descriptions or None
        sources = [source for source in epg_config.enumSources(config_path, filter=filter_values)]
    except Exception as exc:
        write_exception("start enumSources failed", exc)
        message = "EPGImport-Quellen konnten nicht gelesen werden: " + ensure_text(exc)
        return EPGImportResult(False, message, installed=True, ready=True, error=message)

    if not sources:
        if descriptions:
            wanted = ", ".join(descriptions)
        else:
            wanted = "EpgToXml"
        message = (
            "Keine EPGImport-Quelle gefunden: " + wanted +
            " (sources: " + SOURCES_PATH + ", channels: " + CHANNELS_PATH + ")"
        )
        write_debug("start no source found for " + wanted, "epgimport")
        return EPGImportResult(False, message, installed=True, ready=True, error=message)

    sources.reverse()
    source_count = len(sources)
    loaded_descriptions = [ensure_text(getattr(source, "description", "")) for source in sources]
    monitor_started_at = time.time()
    try:
        epgimport.sources = list(sources)
        log("EPGImport sources loaded: " + ", ".join(loaded_descriptions))
        write_debug("sources loaded count=%d descriptions=%s" % (source_count, ", ".join(loaded_descriptions)), "epgimport")
        start_import()
    except Exception as exc:
        write_exception("startImport failed", exc)
        message = "EPGImport konnte nicht gestartet werden: " + ensure_text(exc)
        return EPGImportResult(False, message, installed=True, ready=True,
                               source_count=source_count,
                               source_descriptions=loaded_descriptions,
                               error=message)

    write_debug("start ok source_count=" + str(source_count), "epgimport")
    return EPGImportResult(True, "EPGImport gestartet: " + str(source_count) + " Quelle(n)",
                           installed=True, ready=True, source_count=source_count,
                           source_descriptions=loaded_descriptions,
                           monitor_started_at=monitor_started_at)
