# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import json
import os
import time

from .compat import ensure_text, write_file_atomic
from .debuglog import write_debug, write_exception
from .paths import LEGACY_TASKS_PATH, TASKS_PATH
from .schedule_time import (
    DEFAULT_SCHEDULE_TIME, DEFAULT_SCHEDULE_TIMES,
    normalise_schedule_time, normalise_schedule_times,
)
from .settings import get_default_schedule_times

try:
    unicode
except NameError:
    unicode = str


DEFAULT_SOURCE_ID = "hdplus_de"
DEFAULT_SOURCE_CHANNEL_ID = ""
DEFAULT_TASK_NAME = "Neuer Task"
DEFAULT_SOURCE_CHANNEL_NAME = ""
DEFAULT_DAZN_ASSET_ID = ""

# Quellen mit einer engeren Tagesgrenze als dem globalen Maximum. Bewusst eine
# lokale Tabelle statt eines Imports aus `providers`: normalise_task() läuft bei
# jedem load()/save() pro Task, und get_provider() würde dabei jedes Mal die
# komplette Provider-Liste samt aller HTTP-Clients instanziieren.
# Muss zu TeleboyProvider.max_days passen (Konsistenztest in tests/).
DEFAULT_MAX_DAYS = 14
SOURCE_MAX_DAYS = {
    "teleboy_ch": 4,
}

# "default": globalen Standard-Zeitplan aus den Einstellungen übernehmen
# "custom": eigene schedule_slot_1/2-Werte verwenden (bisheriges Verhalten)
# "off": nie automatisch laufen, auch nicht über den globalen Standard
DEFAULT_SCHEDULE_MODE = "default"
VALID_SCHEDULE_MODES = ("default", "custom", "off")

# Pfade, fuer die die Migration von /media/hdd schon versucht wurde. Nur einmal
# pro Prozess statt bei jedem load() -- siehe _migrate_legacy_once().
_legacy_migration_done = set()


class TaskError(Exception):
    pass


def _task_id():
    return "task-%d" % int(time.time() * 1000)


def _coerce_int(value, default, minimum=None, maximum=None):
    try:
        value = int(value)
    except Exception:
        value = default
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def clean_task_name(value, fallback=DEFAULT_TASK_NAME):
    text = ensure_text(value).strip()
    if not text or text.lower() == "not a string":
        return fallback
    if text.startswith("<") and text.endswith(">"):
        return fallback
    return text


def max_days_for_source(source_id):
    return SOURCE_MAX_DAYS.get(ensure_text(source_id or ""), DEFAULT_MAX_DAYS)


def default_task():
    return {
        "id": _task_id(),
        "name": DEFAULT_TASK_NAME,
        "enabled": True,
        "source_id": DEFAULT_SOURCE_ID,
        "source_channel_id": DEFAULT_SOURCE_CHANNEL_ID,
        "source_channel_name": DEFAULT_SOURCE_CHANNEL_NAME,
        "dazn_asset_id": DEFAULT_DAZN_ASSET_ID,
        "ard_channel_id": "",
        "ard_variant_id": "",
        "zdf_channel_id": "",
        "redbull_channel_id": "",
        "rtlplus_channel_id": "",
        "hdplus_channel_id": "",
        "teleboy_channel_id": "",
        "source_channel_logo": "",
        "target_service_ref": "",
        "target_service_name": "",
        "days": 3,
        "import_after_generate": True,
        "schedule_mode": DEFAULT_SCHEDULE_MODE,
        "schedule_enabled": False,
        "schedule_times": list(DEFAULT_SCHEDULE_TIMES),
        "schedule_slot_1_enabled": False,
        "schedule_slot_1_time": DEFAULT_SCHEDULE_TIME,
        "schedule_slot_2_enabled": False,
        "schedule_slot_2_time": DEFAULT_SCHEDULE_TIME,
        "last_scheduled_run": "",
        "last_status": "Noch nicht gelaufen",
    }


def normalise_task(task, default_schedule_times=None):
    raw = task or {}
    base = default_task()
    base.update(raw)
    source_id = ensure_text(base.get("source_id") or DEFAULT_SOURCE_ID)
    legacy_times = normalise_schedule_times(base.get("schedule_times"))
    has_slot_fields = (
        "schedule_slot_1_enabled" in raw or
        "schedule_slot_1_time" in raw or
        "schedule_slot_2_enabled" in raw or
        "schedule_slot_2_time" in raw
    )
    if has_slot_fields:
        slot_1_enabled = bool(base.get("schedule_slot_1_enabled"))
        slot_1_time = normalise_schedule_time(base.get("schedule_slot_1_time"))
        slot_2_enabled = bool(base.get("schedule_slot_2_enabled"))
        slot_2_time = normalise_schedule_time(base.get("schedule_slot_2_time"))
    else:
        slot_1_enabled = len(legacy_times) > 0
        slot_1_time = legacy_times[0] if len(legacy_times) > 0 else DEFAULT_SCHEDULE_TIME
        slot_2_enabled = len(legacy_times) > 1
        slot_2_time = legacy_times[1] if len(legacy_times) > 1 else DEFAULT_SCHEDULE_TIME
    custom_times = []
    if slot_1_enabled:
        custom_times.append(slot_1_time)
    if slot_2_enabled and slot_2_time not in custom_times:
        custom_times.append(slot_2_time)

    # Tasks ohne explizites "schedule_mode" (z.B. aus einer tasks.json von vor
    # Einführung des globalen Standard-Zeitplans) verhalten sich exakt wie
    # zuvor: eigene Slot-Zeiten zählen als "custom", sonst "off" — sie
    # übernehmen den neuen globalen Fallback nicht unbemerkt.
    schedule_mode = base.get("schedule_mode")
    if "schedule_mode" not in raw or schedule_mode not in VALID_SCHEDULE_MODES:
        schedule_mode = "custom" if custom_times else "off"

    if schedule_mode == "default":
        if default_schedule_times is None:
            default_schedule_times = get_default_schedule_times()
        schedule_times = list(default_schedule_times)
    elif schedule_mode == "custom":
        schedule_times = custom_times
    else:
        schedule_times = []

    return {
        "id": ensure_text(base.get("id") or _task_id()),
        "name": clean_task_name(base.get("name"), DEFAULT_TASK_NAME),
        "enabled": bool(base.get("enabled")),
        "source_id": source_id,
        "source_channel_id": ensure_text(base.get("source_channel_id") or DEFAULT_SOURCE_CHANNEL_ID),
        "source_channel_name": ensure_text(base.get("source_channel_name") or DEFAULT_SOURCE_CHANNEL_NAME),
        "dazn_asset_id": ensure_text(base.get("dazn_asset_id") or DEFAULT_DAZN_ASSET_ID),
        "ard_channel_id": ensure_text(base.get("ard_channel_id") or ""),
        "ard_variant_id": ensure_text(base.get("ard_variant_id") or ""),
        "zdf_channel_id": ensure_text(base.get("zdf_channel_id") or ""),
        "redbull_channel_id": ensure_text(base.get("redbull_channel_id") or ""),
        "rtlplus_channel_id": ensure_text(base.get("rtlplus_channel_id") or ""),
        "hdplus_channel_id": ensure_text(base.get("hdplus_channel_id") or ""),
        "teleboy_channel_id": ensure_text(base.get("teleboy_channel_id") or ""),
        "source_channel_logo": ensure_text(base.get("source_channel_logo") or ""),
        "target_service_ref": ensure_text(base.get("target_service_ref") or ""),
        "target_service_name": ensure_text(base.get("target_service_name") or ""),
        "days": _coerce_int(base.get("days"), 3, 1, max_days_for_source(source_id)),
        "import_after_generate": bool(base.get("import_after_generate")),
        "schedule_mode": schedule_mode,
        "schedule_enabled": bool(schedule_times),
        "schedule_times": schedule_times,
        "schedule_slot_1_enabled": bool(slot_1_enabled),
        "schedule_slot_1_time": slot_1_time,
        "schedule_slot_2_enabled": bool(slot_2_enabled),
        "schedule_slot_2_time": slot_2_time,
        "last_scheduled_run": ensure_text(base.get("last_scheduled_run") or ""),
        "last_status": ensure_text(base.get("last_status") or ""),
    }


def make_legacy_task(service_ref="", days=3):
    task = default_task()
    task["target_service_ref"] = ensure_text(service_ref or "")
    task["days"] = _coerce_int(days, 3, 1, 14)
    return normalise_task(task)


def dedupe_tasks(tasks, log=None):
    """Mehrfache Eintraege mit derselben ID zusammenfuehren.

    Duplikate haben den Scheduler frueher in eine Endlosschleife geschickt:
    ``mark_task`` markierte nur den ersten Treffer, ``find_due`` startete aber
    immer den ersten *unmarkierten*. Der erste Eintrag gewinnt; ein gesetzter
    ``last_scheduled_run`` aus einem Duplikat wird uebernommen, sonst wuerde der
    Task direkt nach dem Aufraeumen noch einmal zusaetzlich laufen.
    """
    result = []
    by_id = {}
    dropped = 0
    for task in tasks:
        task_id = task.get("id")
        kept = by_id.get(task_id)
        if kept is None:
            by_id[task_id] = task
            result.append(task)
            continue
        dropped += 1
        if not kept.get("last_scheduled_run") and task.get("last_scheduled_run"):
            kept["last_scheduled_run"] = task.get("last_scheduled_run")
            kept["last_status"] = task.get("last_status") or kept.get("last_status")
    if dropped and log:
        log("tasks dedupe: %d doppelte Eintraege entfernt" % dropped)
    return result


def _copy_file_if_missing(path, legacy_path):
    if not legacy_path or os.path.exists(path) or not os.path.exists(legacy_path):
        return False
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
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


class TaskRepository(object):
    def __init__(self, path=TASKS_PATH, legacy_path=None):
        self.path = path
        if legacy_path is None and path == TASKS_PATH:
            legacy_path = LEGACY_TASKS_PATH
        self.legacy_path = legacy_path

    def ensure_parent(self):
        directory = os.path.dirname(self.path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

    def _migrate_legacy_once(self):
        # Nur einmal pro Prozess: bei jedem load() wuerde die Migration sonst in
        # das Schreibfenster eines parallelen save() fallen und eine alte
        # tasks.json ueber die aktuelle kopieren.
        if self.path in _legacy_migration_done:
            return
        _legacy_migration_done.add(self.path)
        try:
            if _copy_file_if_missing(self.path, self.legacy_path):
                write_debug("tasks migration: copied " + self.legacy_path + " to " + self.path, "tasks")
        except Exception:
            write_exception("tasks migration failed", "tasks")

    def load(self):
        self._migrate_legacy_once()
        if not os.path.exists(self.path):
            write_debug("tasks load: missing " + self.path, "tasks")
            return []
        handle = open(self.path, "rb")
        try:
            raw = handle.read()
        finally:
            handle.close()
        if not raw:
            return []
        if not isinstance(raw, str):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("tasks", [])
        default_schedule_times = get_default_schedule_times()
        tasks = [normalise_task(item, default_schedule_times=default_schedule_times) for item in data]
        tasks = dedupe_tasks(tasks, log=lambda message: write_debug(message, "tasks"))
        write_debug("tasks load: " + str(len(tasks)) + " from " + self.path, "tasks")
        return tasks

    def save(self, tasks):
        self.ensure_parent()
        default_schedule_times = get_default_schedule_times()
        normalised = [normalise_task(item, default_schedule_times=default_schedule_times) for item in tasks]
        data = {
            "version": 1,
            "tasks": dedupe_tasks(normalised, log=lambda message: write_debug(message, "tasks")),
        }
        raw = json.dumps(data, indent=2, sort_keys=True)
        write_file_atomic(self.path, raw)
        write_debug("tasks save: " + str(len(data["tasks"])) + " to " + self.path, "tasks")

    def get(self, task_id):
        for task in self.load():
            if task.get("id") == task_id:
                return task
        raise TaskError("Task nicht gefunden: " + ensure_text(task_id))

    def upsert(self, task):
        task = normalise_task(task)
        tasks = self.load()
        found = False
        for index, item in enumerate(tasks):
            if item.get("id") == task.get("id"):
                tasks[index] = task
                found = True
                break
        if not found:
            tasks.append(task)
        self.save(tasks)
        write_debug("tasks upsert: " + ensure_text(task.get("id")), "tasks")
        return task

    def delete(self, task_id):
        tasks = [task for task in self.load() if task.get("id") != task_id]
        self.save(tasks)
        write_debug("tasks delete: " + ensure_text(task_id), "tasks")

    def migrate_legacy_if_needed(self, service_ref="", days=3):
        tasks = self.load()
        if tasks:
            return tasks
        task = make_legacy_task(service_ref=service_ref, days=days)
        self.save([task])
        return [task]


def validate_task(task):
    task = normalise_task(task)
    if not task.get("target_service_ref"):
        raise TaskError("Kein Zielsender gewählt.")
    if not task.get("source_id"):
        raise TaskError("Keine Quelle gewählt.")
    if not task.get("source_channel_id"):
        raise TaskError("Kein Quellkanal gewählt.")
    return task
