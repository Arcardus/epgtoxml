# -*- coding: utf-8 -*-
from __future__ import absolute_import

import os
import time

from .compat import ensure_text
from .debuglog import write_debug, write_exception
from .epgimport_adapter import start_epgimport
from .paths import EPGIMPORT_PROGRAM_PATH, LOG_PATH, OUTPUT_DIR
from .providers import get_provider
from .tasks import TaskRepository, validate_task
from .epgimport_files import (
    LEGACY_SOURCE_DESCRIPTION, source_description_for_task,
    write_channels, write_channels_for_tasks, write_sources, write_sources_for_tasks,
    write_epgimport_program_file,
)


def task_epgimport_path(task):
    task_id = ensure_text(task.get("id") or "task")
    safe = []
    for char in task_id:
        if char.isalnum() or char in ("-", "_"):
            safe.append(char)
        else:
            safe.append("_")
    return os.path.join(OUTPUT_DIR, "".join(safe) + ".xml")


class EpgToXmlRunner(object):
    def __init__(self, provider_id="sky_de", days=3,
                 service_ref="", log_path=LOG_PATH, session=None, task=None,
                 tasks_path=None, progress=None):
        self.provider_id = provider_id
        self.days = int(days)
        self.service_ref = service_ref
        self.log_path = log_path
        self.session = session
        self.task = task
        self.tasks_path = tasks_path
        self.progress = progress

    def log(self, message):
        write_debug(message, "runner")
        line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + ensure_text(message) + "\n"
        directory = os.path.dirname(self.log_path)
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except Exception:
                pass
        try:
            handle = open(self.log_path, "ab")
            handle.write(line.encode("utf-8"))
            handle.close()
        except Exception:
            pass

    def emit(self, kind, message):
        self.log(kind + ": " + ensure_text(message))
        if self.progress:
            self.progress(kind, ensure_text(message))

    def run(self, import_epg=True):
        if self.task is not None:
            return self.run_task(self.task, import_epg=import_epg)
        self.log("Starting provider " + self.provider_id)
        provider = get_provider(self.provider_id)
        channels, programmes = provider.fetch(self.days)
        self.log("Fetched " + str(len(programmes)) + " programmes")
        write_epgimport_program_file(channels, programmes, EPGIMPORT_PROGRAM_PATH)
        if self.service_ref:
            write_channels(self.service_ref)
        write_sources()
        message = "EPGImport-Daten geschrieben: " + EPGIMPORT_PROGRAM_PATH
        if import_epg:
            result = start_epgimport(self.session, self.log, source_descriptions=[LEGACY_SOURCE_DESCRIPTION])
            message += "; " + result.message
            if not result.started:
                raise RuntimeError(result.message)
        self.log(message)
        return {
            "channels": len(channels),
            "programmes": len(programmes),
            "message": message,
        }

    def run_task(self, task, import_epg=True):
        started = time.time()
        task = validate_task(task)
        try:
            self.emit("step", "Task prüfen")
            write_debug("task start: " + ensure_text(task.get("id")) + " days=" + str(task.get("days")), "runner")
            provider = get_provider(task.get("source_id"))

            self.emit("step", "EPG von " + provider.name + " laden")
            channels, programmes = provider.fetch(task, progress=self.emit)
            if time.time() - started > 180:
                raise RuntimeError("Import-Timeout erreicht.")
            self.emit("log", str(len(programmes)) + " Sendungen geladen")

            epgimport_path = task_epgimport_path(task)
            self.emit("step", "EPGImport-Daten schreiben")
            write_epgimport_program_file(channels, programmes, epgimport_path)
        except Exception as exc:
            write_exception("runner task failed", exc)
            raise

        repo = TaskRepository(self.tasks_path) if self.tasks_path else TaskRepository()
        tasks = repo.load()
        replaced = False
        for index, item in enumerate(tasks):
            if item.get("id") == task.get("id"):
                item["last_status"] = "OK: " + time.strftime("%Y-%m-%d %H:%M:%S")
                tasks[index] = item
                replaced = True
                break
        if not replaced:
            task["last_status"] = "OK: " + time.strftime("%Y-%m-%d %H:%M:%S")
            tasks.append(task)
        repo.save(tasks)

        enabled = [item for item in tasks if item.get("enabled")]
        enabled_ids = {}
        for item in enabled:
            enabled_ids[item.get("id")] = True
        if task.get("id") not in enabled_ids:
            enabled.append(task)
        paths = {}
        for item in enabled:
            path = task_epgimport_path(item)
            if item.get("id") == task.get("id") or os.path.exists(path):
                paths[item.get("id")] = path

        self.emit("step", "EPGImport-Dateien schreiben")
        write_channels_for_tasks(enabled)
        write_sources_for_tasks(enabled, paths)

        message = "EPGImport-Daten geschrieben: " + epgimport_path
        if import_epg and task.get("import_after_generate"):
            self.emit("step", "EPGImport starten")
            result = start_epgimport(
                self.session,
                self.log,
                source_descriptions=[source_description_for_task(task)],
            )
            message += "; " + result.message
            if result.started:
                self.emit("log", "EPGImport-Quelle geladen: " + source_description_for_task(task))
            else:
                self.emit("error", result.message)
                raise RuntimeError(result.message)
        self.emit("done", message)
        return {
            "channels": len(channels),
            "programmes": len(programmes),
            "message": message,
            "epgimport_path": epgimport_path,
        }
