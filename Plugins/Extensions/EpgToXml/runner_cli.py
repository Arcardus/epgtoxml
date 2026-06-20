# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import json
import os
import sys
import time
import types

# Der Helper wird als Skript gestartet, weil schlanke OE-2.0-Images nicht
# zwingend pkgutil (und damit kein funktionsfaehiges ``python -m``) enthalten.
# Aus dem eigenen Speicherort laesst sich der Enigma2-Python-Root fuer VTi und
# DreamOS identisch ableiten. Plugins und Plugins.Extensions sind bei Enigma2
# Namespace-Verzeichnisse ohne __init__.py; fuer einen separaten Python-2-
# Prozess werden diese beiden Paket-Eltern deshalb explizit bereitgestellt.
PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)


def _ensure_namespace(name, path, parent=None, child=None):
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        module.__path__ = [path]
        sys.modules[name] = module
    if parent is not None and child is not None:
        setattr(parent, child, module)
    return module


plugins_package = _ensure_namespace(
    "Plugins", os.path.join(PACKAGE_ROOT, "Plugins"))
_ensure_namespace(
    "Plugins.Extensions",
    os.path.join(PACKAGE_ROOT, "Plugins", "Extensions"),
    plugins_package,
    "Extensions",
)

from Plugins.Extensions.EpgToXml.compat import ensure_text  # noqa: E402
from Plugins.Extensions.EpgToXml.core import EpgToXmlRunner  # noqa: E402
from Plugins.Extensions.EpgToXml.debuglog import write_debug, write_exception  # noqa: E402
from Plugins.Extensions.EpgToXml.tasks import TaskRepository  # noqa: E402


def _write_event(kind, message):
    data = {"kind": kind, "message": ensure_text(message)}
    line = "EPGTOXML " + json.dumps(data, sort_keys=True)
    try:
        sys.stdout.write(line + "\n")
    except UnicodeEncodeError:
        sys.stdout.write((line + "\n").encode("utf-8"))
    try:
        sys.stdout.flush()
    except Exception:
        pass


def _arg_value(args, name, default=None):
    if name not in args:
        return default
    index = args.index(name)
    if index + 1 >= len(args):
        return default
    return args[index + 1]


def _mark_status(repo, task_id, status):
    try:
        tasks = repo.load()
        for task in tasks:
            if task.get("id") == task_id:
                task["last_status"] = status
                break
        repo.save(tasks)
    except Exception:
        pass


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    task_id = _arg_value(argv, "--task-id")
    tasks_path = _arg_value(argv, "--tasks-path")
    import_epg = "--import" in argv
    write_debug("runner_cli start task_id=" + ensure_text(task_id) + " tasks_path=" + ensure_text(tasks_path), "runner")
    if not task_id:
        _write_event("error", "Keine Task-ID angegeben.")
        return 2

    repo = TaskRepository(tasks_path) if tasks_path else TaskRepository()
    try:
        task = repo.get(task_id)
        runner = EpgToXmlRunner(task=task, tasks_path=tasks_path, progress=_write_event)
        runner.run_task(task, import_epg=import_epg)
        write_debug("runner_cli done task_id=" + ensure_text(task_id), "runner")
        return 0
    except Exception as exc:
        write_exception("runner_cli failed", exc)
        message = ensure_text(exc)
        _mark_status(repo, task_id, "Fehler: " + message + " (" + time.strftime("%Y-%m-%d %H:%M:%S") + ")")
        _write_event("error", message)
        return 1


if __name__ == "__main__":
    sys.exit(main())
