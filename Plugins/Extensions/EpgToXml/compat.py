# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import datetime
import os
import time

try:
    basestring
except NameError:
    basestring = str

try:
    unicode
except NameError:
    unicode = str

try:
    unichr
except NameError:
    unichr = chr


def ensure_text(value, encoding="utf-8"):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    args = getattr(value, "args", None)
    if args:
        try:
            return u" ".join([ensure_text(item, encoding) for item in args])
        except Exception:
            pass
    try:
        return value.decode(encoding)
    except Exception:
        try:
            return unicode(value)
        except Exception:
            return u""


def ensure_bytes(value, encoding="utf-8"):
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return ensure_text(value).encode(encoding)


def repair_mojibake(value):
    text = ensure_text(value)
    if u"\xc3" not in text and u"\xc2" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except Exception:
        replacements = (
            (unichr(0xc3) + unichr(0x84), u"\u00c4"),
            (unichr(0xc3) + unichr(0x96), u"\u00d6"),
            (unichr(0xc3) + unichr(0x9c), u"\u00dc"),
            (unichr(0xc3) + unichr(0xa4), u"\u00e4"),
            (unichr(0xc3) + unichr(0xb6), u"\u00f6"),
            (unichr(0xc3) + unichr(0xbc), u"\u00fc"),
            (unichr(0xc3) + unichr(0x9f), u"\u00df"),
            (unichr(0xc2) + unichr(0xb7), u"\u00b7"),
            (unichr(0xc2) + unichr(0xa0), u" "),
        )
        for broken, fixed in replacements:
            text = text.replace(broken, fixed)
        return text


def write_file_atomic(path, raw, tmp_suffix=".tmp"):
    """Datei ueber eine Temporaerdatei ersetzen, ohne sie zwischendurch zu loeschen.

    ``os.rename`` ersetzt das Ziel auf POSIX atomar. Ein ``os.remove`` davor wuerde
    ein Fenster oeffnen, in dem die Datei fuer andere Leser gar nicht existiert --
    genau darin lieferte ``TaskRepository.load()`` eine leere Liste und die
    Legacy-Migration spielte eine alte tasks.json zurueck.

    Der remove+rename-Pfad bleibt als Fallback fuer Dateisysteme, auf denen
    rename-over-existing scheitert.
    """
    tmp = path + tmp_suffix
    handle = open(tmp, "wb")
    try:
        handle.write(ensure_bytes(raw))
    finally:
        handle.close()
    try:
        os.rename(tmp, path)
        return
    except OSError:
        pass
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    os.rename(tmp, path)


def wait_for_db_ready(path, min_size, timeout=90.0, interval=0.5,
                      exists=os.path.exists, getsize=os.path.getsize,
                      sleep=time.sleep, clock=None):
    """Wartet, bis die SQLite-epg.db nach einem async eEPGCache.save() bereit ist.

    Route B (epgimport_engine/epgdb.py) loescht die epg.db und stoesst ein
    asynchrones eEPGCache.save() an. Bei grosser DB ist die Datei noch nicht
    geschrieben, wenn die Insert-Kette laeuft -> getsize wirft und der Import
    stirbt still (Race). Diese Funktion pollt, bis die Datei existiert, mindestens
    ``min_size`` Bytes hat und ihre Groesse ueber zwei aufeinanderfolgende
    Messungen stabil ist (Save abgeschlossen), oder bis ``timeout`` Sekunden
    verstrichen sind.

    Gibt True zurueck wenn die DB bereit ist, sonst False (Timeout). Blockiert
    nie unendlich. Alle I/O-/Zeit-Abhaengigkeiten sind injizierbar (Tests).
    """
    if clock is None:
        clock = getattr(time, "monotonic", time.time)
    deadline = clock() + timeout
    last_size = -1
    while True:
        ready = False
        try:
            if exists(path):
                size = getsize(path)
                if size >= min_size and size == last_size:
                    ready = True
                last_size = size
            else:
                last_size = -1
        except OSError:
            last_size = -1
        if ready:
            return True
        if clock() >= deadline:
            return False
        sleep(interval)


def local_midnight(dt):
    return datetime.datetime(dt.year, dt.month, dt.day, 0, 0, 0)


def timestamp_ms(dt):
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return int(time.mktime(dt.timetuple()) * 1000)


def epgimport_time(dt):
    stamp = time.mktime(dt.timetuple())
    local = time.localtime(stamp)
    if getattr(time, "daylight", 0) and local.tm_isdst > 0:
        offset = -time.altzone
    else:
        offset = -time.timezone
    sign = "+"
    if offset < 0:
        sign = "-"
        offset = -offset
    hours = offset // 3600
    minutes = (offset % 3600) // 60
    return dt.strftime("%Y%m%d%H%M%S ") + ("%s%02d%02d" % (sign, hours, minutes))


def parse_hhmm(day, hhmm):
    parts = hhmm.split(":")
    hour = int(parts[0])
    minute = int(parts[1])
    return datetime.datetime(day.year, day.month, day.day, hour, minute, 0)
