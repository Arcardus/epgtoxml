# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
"""Persistenz für den zuletzt funktionierenden Teleboy-API-Key.

Der Key steht öffentlich im HTML von teleboy.ch und kann jederzeit rotieren.
Statt ihn fest im Code zu halten, merkt sich das Plugin den zuletzt erfolgreichen
Key hier und holt nur bei HTTP 403 einen neuen aus der Webseite.

Alle Funktionen sind bewusst fehlertolerant: ein nicht schreibbares ``/etc`` oder
eine kaputte Cache-Datei darf einen EPG-Lauf niemals abbrechen -- es entsteht dann
lediglich pro Lauf ein zusätzlicher HTML-Request.
"""
from __future__ import absolute_import

import datetime
import json
import os
import re

from .compat import ensure_text
from .debuglog import write_debug
from .paths import TELEBOY_KEY_PATH


# Teleboy-Keys sind 64 Hex-Zeichen. Die Prüfung verhindert, dass eine abgeschnittene
# oder anderweitig beschädigte Cache-Datei bei jedem Lauf in einen 403 läuft.
_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _ensure_parent(path):
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)


def is_valid_api_key(key):
    return bool(_KEY_RE.match(ensure_text(key).strip()))


def load_api_key(path=TELEBOY_KEY_PATH):
    """Liefert den gespeicherten Key oder ``u""`` -- wirft nie."""
    try:
        if not os.path.exists(path):
            return u""
        handle = open(path, "rb")
        try:
            raw = handle.read()
        finally:
            handle.close()
        if not raw:
            return u""
        if not isinstance(raw, str):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return u""
        key = ensure_text(data.get("api_key")).strip()
        if not is_valid_api_key(key):
            write_debug("Teleboy key cache holds an invalid key, ignoring it", "teleboy")
            return u""
        return key
    except Exception as exc:
        write_debug("Teleboy key cache could not be read: " + str(exc), "teleboy")
        return u""


def save_api_key(key, path=TELEBOY_KEY_PATH):
    """Schreibt den Key atomar. Liefert ``True`` bei Erfolg -- wirft nie."""
    if not is_valid_api_key(key):
        write_debug("Teleboy key not saved: invalid format", "teleboy")
        return False
    try:
        _ensure_parent(path)
        payload = {
            "api_key": ensure_text(key).strip(),
            "updated": datetime.datetime.now().isoformat(),
        }
        raw = json.dumps(payload, indent=2, sort_keys=True)
        tmp = path + ".tmp"
        handle = open(tmp, "wb")
        try:
            handle.write(raw.encode("utf-8"))
        finally:
            handle.close()
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        os.rename(tmp, path)
        write_debug("Teleboy key cache updated", "teleboy")
        return True
    except Exception as exc:
        # Read-only /etc, volle Platte, fehlende Rechte -- alles unkritisch.
        write_debug("Teleboy key cache could not be written: " + str(exc), "teleboy")
        return False
