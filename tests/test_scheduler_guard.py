# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import unittest

from Plugins.Extensions.EpgToXml.scheduler_core import (
    SCHEDULE_WINDOW_MINUTES, done_key_for, find_due, prune_done_keys, run_key_for,
)
from Plugins.Extensions.EpgToXml.tasks import normalise_task

TODAY = "2026-08-07"


def task(task_id, times, last_scheduled_run="", enabled=True):
    return normalise_task({
        "id": task_id,
        "name": task_id,
        "enabled": enabled,
        "target_service_ref": "1:0:1:1234:0:0:0:0:0:0:",
        "source_channel_id": "hdplus.de.dfb_tv",
        "schedule_mode": "custom",
        "schedule_slot_1_enabled": len(times) > 0,
        "schedule_slot_1_time": times[0] if times else "00:00",
        "schedule_slot_2_enabled": len(times) > 1,
        "schedule_slot_2_time": times[1] if len(times) > 1 else "00:00",
        "last_scheduled_run": last_scheduled_run,
    })


class SchedulerGuardTests(unittest.TestCase):
    """Der Automatik-Scheduler darf einen Task pro geplanter Uhrzeit genau
    einmal starten -- auch wenn die tasks.json kaputt oder nicht schreibbar ist.
    """

    def run_loop(self, tasks, now="05:10", limit=5):
        """Scheduler-Runden simulieren: faellig -> starten -> markieren."""
        done_keys = {}
        starts = []
        for _ in range(limit):
            due = find_due(tasks, now, TODAY, done_keys=done_keys)
            if due is None:
                break
            found, run_key = due
            starts.append((found["id"], run_key))
            done_keys[done_key_for(found["id"], run_key)] = True
            # mark_task: alle Eintraege mit dieser ID markieren, kein break
            for item in tasks:
                if item["id"] == found["id"]:
                    item["last_scheduled_run"] = run_key
        return starts

    def test_task_runs_once_per_scheduled_time(self):
        starts = self.run_loop([task("task-1", ["05:00"])])
        self.assertEqual(starts, [("task-1", "2026-08-07 05:00")])

    def test_duplicate_entries_with_same_id_run_only_once(self):
        # Der auf dem Receiver reproduzierte Fall: zwei Eintraege, derselbe Task.
        # Frueher lief er alle 60 Sekunden neu, bis das Fenster zumachte.
        tasks = [task("task-1", ["05:00"]), task("task-1", ["05:00"])]
        self.assertEqual(self.run_loop(tasks), [("task-1", "2026-08-07 05:00")])

    def test_unwritable_marker_does_not_cause_a_loop(self):
        # mark_task schlaegt fehl -> last_scheduled_run bleibt leer. Der
        # Speicher-Merker muss den zweiten Lauf trotzdem verhindern.
        tasks = [task("task-1", ["05:00"])]
        done_keys = {}
        starts = []
        for _ in range(5):
            due = find_due(tasks, "05:10", TODAY, done_keys=done_keys)
            if due is None:
                break
            found, run_key = due
            starts.append(run_key)
            done_keys[done_key_for(found["id"], run_key)] = True
            # kein Schreiben in die tasks.json
        self.assertEqual(starts, ["2026-08-07 05:00"])
        self.assertEqual(tasks[0]["last_scheduled_run"], "")

    def test_every_task_sharing_a_time_runs_exactly_once(self):
        # Der Normalfall mit globalem Zeitplan: viele Tasks, eine Uhrzeit.
        tasks = [task("task-%d" % n, ["05:00"]) for n in range(1, 4)]
        starts = self.run_loop(tasks, limit=10)
        self.assertEqual(
            starts,
            [("task-1", "2026-08-07 05:00"),
             ("task-2", "2026-08-07 05:00"),
             ("task-3", "2026-08-07 05:00")],
        )

    def test_two_slots_produce_two_separate_runs(self):
        tasks = [task("task-1", ["05:00", "05:15"])]
        starts = self.run_loop(tasks, now="05:20", limit=10)
        self.assertEqual(
            starts,
            [("task-1", "2026-08-07 05:00"), ("task-1", "2026-08-07 05:15")],
        )

    def test_window_boundaries(self):
        tasks = [task("task-1", ["05:00"])]
        self.assertIsNotNone(find_due(tasks, "05:00", TODAY))
        self.assertIsNotNone(find_due(tasks, "05:30", TODAY))
        self.assertIsNone(find_due(tasks, "05:31", TODAY))
        self.assertIsNone(find_due(tasks, "04:59", TODAY))
        self.assertEqual(SCHEDULE_WINDOW_MINUTES, 30)

    def test_disabled_and_unscheduled_tasks_are_skipped(self):
        self.assertIsNone(find_due([task("task-1", ["05:00"], enabled=False)], "05:10", TODAY))
        self.assertIsNone(find_due([task("task-2", [])], "05:10", TODAY))

    def test_marker_from_tasks_json_survives_restart(self):
        # Ebene 1 allein muss reichen, wenn der Prozess neu startet (done_keys leer).
        tasks = [task("task-1", ["05:00"], last_scheduled_run="2026-08-07 05:00")]
        self.assertIsNone(find_due(tasks, "05:10", TODAY, done_keys={}))

    def test_prune_done_keys_drops_other_days(self):
        done_keys = {
            done_key_for("task-1", "2026-08-06 05:00"): True,
            done_key_for("task-1", "2026-08-07 05:00"): True,
        }
        prune_done_keys(done_keys, TODAY)
        self.assertEqual(list(done_keys.keys()), [done_key_for("task-1", "2026-08-07 05:00")])

    def test_run_key_format(self):
        self.assertEqual(run_key_for(TODAY, "05:00"), "2026-08-07 05:00")


if __name__ == "__main__":
    unittest.main()
