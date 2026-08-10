# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import json
import os

from .compat import write_file_atomic
from .paths import LEGACY_SETTINGS_PATH, SETTINGS_PATH
from .schedule_time import DEFAULT_SCHEDULE_TIME, normalise_schedule_time


DEFAULT_SETTINGS = {
    "debug_enabled": True,
    "import_routine": "auto",
    "default_schedule_slot_1_enabled": False,
    "default_schedule_slot_1_time": DEFAULT_SCHEDULE_TIME,
    "default_schedule_slot_2_enabled": False,
    "default_schedule_slot_2_time": DEFAULT_SCHEDULE_TIME,
}

_VALID_IMPORT_ROUTINES = ("auto", "a", "b")

# Pfade, fuer die die Legacy-Migration schon versucht wurde (einmal pro Prozess).
_legacy_migration_done = set()


def _coerce_import_routine(value):
    if value in _VALID_IMPORT_ROUTINES:
        return value
    return "auto"


def _coerce_settings(data):
    data["debug_enabled"] = bool(data.get("debug_enabled"))
    data["import_routine"] = _coerce_import_routine(data.get("import_routine"))
    data["default_schedule_slot_1_enabled"] = bool(data.get("default_schedule_slot_1_enabled"))
    data["default_schedule_slot_1_time"] = normalise_schedule_time(data.get("default_schedule_slot_1_time"))
    data["default_schedule_slot_2_enabled"] = bool(data.get("default_schedule_slot_2_enabled"))
    data["default_schedule_slot_2_time"] = normalise_schedule_time(data.get("default_schedule_slot_2_time"))
    return data


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
    # Nur einmal pro Prozess: bei jedem Aufruf wuerde die Migration sonst in das
    # Schreibfenster eines parallelen save_settings() fallen. load_settings()
    # laeuft seit dem globalen Zeitplan sehr haeufig -- normalise_task() ruft es
    # pro Task und pro load()/save() der tasks.json auf.
    if path not in _legacy_migration_done:
        _legacy_migration_done.add(path)
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
    return _coerce_settings(data)


def save_settings(settings, path=SETTINGS_PATH):
    _ensure_parent(path)
    data = dict(DEFAULT_SETTINGS)
    data.update(settings or {})
    _coerce_settings(data)
    raw = json.dumps(data, indent=2, sort_keys=True)
    write_file_atomic(path, raw)
    return data


def is_debug_enabled():
    return bool(load_settings().get("debug_enabled"))


def set_debug_enabled(enabled):
    settings = load_settings()
    settings["debug_enabled"] = bool(enabled)
    return bool(save_settings(settings).get("debug_enabled"))


def get_import_routine():
    return _coerce_import_routine(load_settings().get("import_routine"))


def set_import_routine(value):
    settings = load_settings()
    settings["import_routine"] = _coerce_import_routine(value)
    return save_settings(settings).get("import_routine")


def toggle_debug_enabled():
    settings = load_settings()
    settings["debug_enabled"] = not bool(settings.get("debug_enabled"))
    return bool(save_settings(settings).get("debug_enabled"))


def get_default_schedule_slots():
    settings = load_settings()
    return (
        bool(settings.get("default_schedule_slot_1_enabled")),
        settings.get("default_schedule_slot_1_time"),
        bool(settings.get("default_schedule_slot_2_enabled")),
        settings.get("default_schedule_slot_2_time"),
    )


def set_default_schedule_slots(slot_1_enabled, slot_1_time, slot_2_enabled, slot_2_time):
    settings = load_settings()
    settings["default_schedule_slot_1_enabled"] = bool(slot_1_enabled)
    settings["default_schedule_slot_1_time"] = normalise_schedule_time(slot_1_time)
    settings["default_schedule_slot_2_enabled"] = bool(slot_2_enabled)
    settings["default_schedule_slot_2_time"] = normalise_schedule_time(slot_2_time)
    saved = save_settings(settings)
    return get_default_schedule_times(saved)


def get_default_schedule_times(settings=None):
    settings = settings if settings is not None else load_settings()
    times = []
    if settings.get("default_schedule_slot_1_enabled"):
        times.append(normalise_schedule_time(settings.get("default_schedule_slot_1_time")))
    if settings.get("default_schedule_slot_2_enabled"):
        slot_2 = normalise_schedule_time(settings.get("default_schedule_slot_2_time"))
        if slot_2 not in times:
            times.append(slot_2)
    return times
