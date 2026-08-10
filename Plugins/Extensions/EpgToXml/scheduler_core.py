# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
"""Reine Entscheidungslogik des Automatik-Schedulers.

Bewusst ohne Enigma2-Imports und ohne Dateizugriff: ``plugin.py`` laesst sich
ausserhalb einer Box nicht importieren (die Screen-Klassen brauchen ``Screen``),
damit waere die Faelligkeitslogik nicht testbar. Der Scheduler in ``plugin.py``
laedt die Tasks und delegiert die Entscheidung hierher.
"""
from __future__ import absolute_import

from .compat import ensure_text
from .schedule_time import hhmm_minutes, normalise_schedule_times


# Wie lange nach der geplanten Uhrzeit ein Task noch nachgeholt wird (Minuten).
# Faengt Boxen ab, die zur geplanten Zeit im Standby/aus waren oder gerade einen
# anderen Task laufen hatten.
SCHEDULE_WINDOW_MINUTES = 30


def run_key_for(today, scheduled):
    """Identitaet eines geplanten Laufs: "YYYY-MM-DD HH:MM"."""
    return ensure_text(today) + u" " + ensure_text(scheduled)


def done_key_for(task_id, run_key):
    return (ensure_text(task_id), ensure_text(run_key))


def prune_done_keys(done_keys, today):
    """Merker fremder Tage verwerfen, damit der Dict nicht unbegrenzt waechst."""
    prefix = ensure_text(today) + u" "
    for key in list(done_keys.keys()):
        if not key[1].startswith(prefix):
            del done_keys[key]
    return done_keys


def find_due(tasks, now_hhmm, today, done_keys=None, log=None):
    """Ersten faelligen Task liefern als ``(task, run_key)`` oder ``None``.

    Zwei Schutzebenen gegen Mehrfachlaeufe:

    1. ``last_scheduled_run`` aus der tasks.json (ueberlebt einen Neustart).
    2. ``done_keys`` im Speicher des laufenden Enigma2-Prozesses.

    Ebene 2 ist bewusst redundant: schlaegt das Schreiben der tasks.json fehl
    oder stehen dort zwei Eintraege mit derselben ID, wuerde Ebene 1 den Task
    endlos neu starten (bis das Faelligkeitsfenster zumacht).
    """
    if done_keys is None:
        done_keys = {}
    now_minutes = hhmm_minutes(now_hhmm)
    if now_minutes < 0:
        return None
    for task in tasks or []:
        task_id = ensure_text(task.get("id"))
        if not task.get("enabled"):
            if log:
                log("scheduler skip disabled task=" + task_id)
            continue
        if not task.get("schedule_enabled"):
            if log:
                log("scheduler skip no schedule task=" + task_id)
            continue
        for scheduled in normalise_schedule_times(task.get("schedule_times")):
            scheduled_minutes = hhmm_minutes(scheduled)
            if scheduled_minutes < 0:
                continue
            delay = now_minutes - scheduled_minutes
            if delay < 0 or delay > SCHEDULE_WINDOW_MINUTES:
                continue
            run_key = run_key_for(today, scheduled)
            if ensure_text(task.get("last_scheduled_run")) == run_key:
                if log:
                    log("scheduler skip already ran " + run_key)
                continue
            if done_key_for(task_id, run_key) in done_keys:
                # Ebene 1 hat nicht gegriffen -> die tasks.json ist kaputt oder
                # nicht schreibbar. Genau der Fall, der frueher zur Endlos-
                # schleife wurde.
                if log:
                    log("scheduler skip already ran this session " + run_key
                        + " task=" + task_id + " (Marker in tasks.json fehlt!)")
                continue
            if log:
                log("scheduler due task=%s run=%s" % (task_id, run_key))
            return (task, run_key)
    return None
