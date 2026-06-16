# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import json
import os

from .paths import LEGACY_SETTINGS_PATH, SETTINGS_PATH


DEFAULT_SETTINGS = {
    "debug_enabled": True,
}


def _ensure_parent(path):
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)


def _copy_file_if_missing(path, legacy_path):
    if not legacy_path or os.path.exists(path) or not os.path.exists(legacy_path):
        return False
    _ensure_parent(path)
    handle = open(legacy_path, "rb")
    try:
        raw = handle.read()
    finally:
        handle.close()
    tmp = path + ".migrate"
    handle = open(tmp, "wb")
    try:
        handle.write(raw)
    finally:
        handle.close()
    os.rename(tmp, path)
    return True


def load_settings(path=SETTINGS_PATH, legacy_path=None):
    if legacy_path is None and path == SETTINGS_PATH:
        legacy_path = LEGACY_SETTINGS_PATH
    data = dict(DEFAULT_SETTINGS)
    try:
        _copy_file_if_missing(path, legacy_path)
    except Exception:
        pass
    if not os.path.exists(path):
        return data
    handle = open(path, "rb")
    try:
        raw = handle.read()
    finally:
        handle.close()
    if raw:
        if not isinstance(raw, str):
            raw = raw.decode("utf-8")
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            data.update(loaded)
    data["debug_enabled"] = bool(data.get("debug_enabled"))
    return data


def save_settings(settings, path=SETTINGS_PATH):
    _ensure_parent(path)
    data = dict(DEFAULT_SETTINGS)
    data.update(settings or {})
    data["debug_enabled"] = bool(data.get("debug_enabled"))
    raw = json.dumps(data, indent=2, sort_keys=True)
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
    return data


def is_debug_enabled():
    return bool(load_settings().get("debug_enabled"))


def set_debug_enabled(enabled):
    settings = load_settings()
    settings["debug_enabled"] = bool(enabled)
    return bool(save_settings(settings).get("debug_enabled"))


def toggle_debug_enabled():
    settings = load_settings()
    settings["debug_enabled"] = not bool(settings.get("debug_enabled"))
    return bool(save_settings(settings).get("debug_enabled"))
