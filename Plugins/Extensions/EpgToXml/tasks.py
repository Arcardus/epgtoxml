# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import json
import os
import re
import time

from .compat import ensure_text
from .debuglog import write_debug, write_exception
from .paths import LEGACY_TASKS_PATH, TASKS_PATH

try:
    unicode
except NameError:
    unicode = str


DEFAULT_SOURCE_ID = "sky_de"
DEFAULT_SOURCE_CHANNEL_ID = "sky.de.dfb-tv"
DEFAULT_TASK_NAME = "Sky DFB.TV"
DEFAULT_SOURCE_CHANNEL_NAME = "DFB.TV"
DEFAULT_SKY_CHANNEL_ID = 1236
DEFAULT_SKY_CHANNEL_SLUG = "dfbtv-c1236"
DEFAULT_SKY_CHANNEL_LOGO = "https://www.sky.de/static/img/senderlogos_dark/1236_sky_26-05_senderlogos_dfbtv.png"
DEFAULT_DAZN_ASSET_ID = ""
DEFAULT_SCHEDULE_TIMES = []
DEFAULT_SCHEDULE_TIME = "00:00"


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


def normalise_schedule_times(values, default=None):
    if default is None:
        default = DEFAULT_SCHEDULE_TIMES
    if values is None:
        values = default
    if isinstance(values, (str, unicode)):
        values = [values]
    result = []
    for value in values:
        text = ensure_text(value).strip()
        if not text:
            continue
        match = re.match(r"^([0-9]{1,2}):([0-9]{2})$", text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
        else:
            match = re.match(r"^([0-9]{3,4})$", text)
            if not match:
                continue
            number = int(match.group(1))
            hour = number // 100
            minute = number % 100
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            continue
        formatted = "%02d:%02d" % (hour, minute)
        if formatted not in result:
            result.append(formatted)
        if len(result) >= 2:
            break
    if not result:
        result = list(default)
    return result


def normalise_schedule_time(value, default=DEFAULT_SCHEDULE_TIME):
    times = normalise_schedule_times([value], default=[])
    if times:
        return times[0]
    return default


def clean_task_name(value, fallback=DEFAULT_TASK_NAME):
    text = ensure_text(value).strip()
    if not text or text.lower() == "not a string":
        return fallback
    if text.startswith("<") and text.endswith(">"):
        return fallback
    return text


def default_task():
    return {
        "id": _task_id(),
        "name": DEFAULT_TASK_NAME,
        "enabled": True,
        "source_id": DEFAULT_SOURCE_ID,
        "source_channel_id": DEFAULT_SOURCE_CHANNEL_ID,
        "source_channel_name": DEFAULT_SOURCE_CHANNEL_NAME,
        "sky_channel_id": DEFAULT_SKY_CHANNEL_ID,
        "sky_channel_slug": DEFAULT_SKY_CHANNEL_SLUG,
        "dazn_asset_id": DEFAULT_DAZN_ASSET_ID,
        "ard_channel_id": "",
        "ard_variant_id": "",
        "zdf_channel_id": "",
        "redbull_channel_id": "",
        "source_channel_logo": DEFAULT_SKY_CHANNEL_LOGO,
        "target_service_ref": "",
        "target_service_name": "",
        "days": 3,
        "import_after_generate": True,
        "schedule_enabled": False,
        "schedule_times": list(DEFAULT_SCHEDULE_TIMES),
        "schedule_slot_1_enabled": False,
        "schedule_slot_1_time": DEFAULT_SCHEDULE_TIME,
        "schedule_slot_2_enabled": False,
        "schedule_slot_2_time": DEFAULT_SCHEDULE_TIME,
        "last_scheduled_run": "",
        "last_status": "Noch nicht gelaufen",
    }


def normalise_task(task):
    raw = task or {}
    base = default_task()
    base.update(raw)
    source_id = ensure_text(base.get("source_id") or DEFAULT_SOURCE_ID)
    logo_default = DEFAULT_SKY_CHANNEL_LOGO if source_id == DEFAULT_SOURCE_ID else ""
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
    schedule_times = []
    if slot_1_enabled:
        schedule_times.append(slot_1_time)
    if slot_2_enabled and slot_2_time not in schedule_times:
        schedule_times.append(slot_2_time)
    return {
        "id": ensure_text(base.get("id") or _task_id()),
        "name": clean_task_name(base.get("name"), DEFAULT_TASK_NAME),
        "enabled": bool(base.get("enabled")),
        "source_id": source_id,
        "source_channel_id": ensure_text(base.get("source_channel_id") or DEFAULT_SOURCE_CHANNEL_ID),
        "source_channel_name": ensure_text(base.get("source_channel_name") or DEFAULT_SOURCE_CHANNEL_NAME),
        "sky_channel_id": _coerce_int(base.get("sky_channel_id"), DEFAULT_SKY_CHANNEL_ID, 1, None),
        "sky_channel_slug": ensure_text(base.get("sky_channel_slug") or DEFAULT_SKY_CHANNEL_SLUG),
        "dazn_asset_id": ensure_text(base.get("dazn_asset_id") or DEFAULT_DAZN_ASSET_ID),
        "ard_channel_id": ensure_text(base.get("ard_channel_id") or ""),
        "ard_variant_id": ensure_text(base.get("ard_variant_id") or ""),
        "zdf_channel_id": ensure_text(base.get("zdf_channel_id") or ""),
        "redbull_channel_id": ensure_text(base.get("redbull_channel_id") or ""),
        "source_channel_logo": ensure_text(base.get("source_channel_logo") or logo_default),
        "target_service_ref": ensure_text(base.get("target_service_ref") or ""),
        "target_service_name": ensure_text(base.get("target_service_name") or ""),
        "days": _coerce_int(base.get("days"), 3, 1, 14),
        "import_after_generate": bool(base.get("import_after_generate")),
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

    def load(self):
        try:
            if _copy_file_if_missing(self.path, self.legacy_path):
                write_debug("tasks migration: copied " + self.legacy_path + " to " + self.path, "tasks")
        except Exception:
            write_exception("tasks migration failed", "tasks")
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
        tasks = [normalise_task(item) for item in data]
        write_debug("tasks load: " + str(len(tasks)) + " from " + self.path, "tasks")
        return tasks

    def save(self, tasks):
        self.ensure_parent()
        data = {"version": 1, "tasks": [normalise_task(item) for item in tasks]}
        raw = json.dumps(data, indent=2, sort_keys=True)
        tmp = self.path + ".tmp"
        handle = open(tmp, "wb")
        try:
            handle.write(raw.encode("utf-8"))
        finally:
            handle.close()
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except Exception:
                pass
        os.rename(tmp, self.path)
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
