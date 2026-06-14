# -*- coding: utf-8 -*-
from __future__ import absolute_import

import json
import sys
import time

from .compat import ensure_text
from .core import EpgToXmlRunner
from .debuglog import write_debug, write_exception
from .tasks import TaskRepository


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
