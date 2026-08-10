# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
"""Persistenz-Haerte der tasks.json/settings.json.

Hintergrund: doppelte Task-Eintraege und ein Schreibfenster, in dem die Datei
kurz gar nicht existiert, haben den Automatik-Scheduler in eine Endlosschleife
geschickt.
"""
import json
import os
import tempfile
import unittest

from Plugins.Extensions.EpgToXml import settings as settings_module
from Plugins.Extensions.EpgToXml import tasks as tasks_module
from Plugins.Extensions.EpgToXml.settings import load_settings, save_settings
from Plugins.Extensions.EpgToXml.tasks import TaskRepository, dedupe_tasks, make_legacy_task


def sample_task(task_id, last_scheduled_run="", last_status=""):
    task = make_legacy_task(service_ref="1:0:1:1234:0:0:0:0:0:0:", days=3)
    task["id"] = task_id
    task["last_scheduled_run"] = last_scheduled_run
    task["last_status"] = last_status
    return task


class DedupeTests(unittest.TestCase):
    def test_duplicates_are_dropped_on_save_and_load(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "tasks.json")
        repo = TaskRepository(path, legacy_path="")
        repo.save([sample_task("task-1"), sample_task("task-1"), sample_task("task-2")])

        handle = open(path, "rb")
        try:
            data = json.load(handle)
        finally:
            handle.close()
        self.assertEqual([item["id"] for item in data["tasks"]], ["task-1", "task-2"])
        self.assertEqual([item["id"] for item in repo.load()], ["task-1", "task-2"])

    def test_marker_from_duplicate_is_carried_over(self):
        # Sonst liefe der Task direkt nach dem Aufraeumen noch einmal zusaetzlich.
        merged = dedupe_tasks([
            sample_task("task-1"),
            sample_task("task-1", last_scheduled_run="2026-08-07 05:00", last_status="Automatik OK"),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["last_scheduled_run"], "2026-08-07 05:00")
        self.assertEqual(merged[0]["last_status"], "Automatik OK")

    def test_existing_marker_wins_over_empty_duplicate(self):
        merged = dedupe_tasks([
            sample_task("task-1", last_scheduled_run="2026-08-07 05:00"),
            sample_task("task-1"),
        ])
        self.assertEqual(merged[0]["last_scheduled_run"], "2026-08-07 05:00")

    def test_dedupe_keeps_distinct_ids_in_order(self):
        merged = dedupe_tasks([sample_task("b"), sample_task("a"), sample_task("b")])
        self.assertEqual([item["id"] for item in merged], ["b", "a"])


class AtomicWriteTests(unittest.TestCase):
    """Die Zieldatei darf nie kurzzeitig fehlen: in genau diesem Fenster liefert
    load() eine leere Liste und die Legacy-Migration spielt eine alte Datei zurueck.
    """

    def assert_target_never_missing(self, path, write):
        seen = []
        real_rename = os.rename

        def spy_rename(src, dst):
            if dst == path:
                seen.append(os.path.exists(path))
            return real_rename(src, dst)

        os.rename = spy_rename
        try:
            write()
        finally:
            os.rename = real_rename
        self.assertTrue(seen, "os.rename auf die Zieldatei wurde nie aufgerufen")
        self.assertTrue(all(seen), "Zieldatei war beim Ersetzen verschwunden")

    def test_task_save_replaces_without_removing_first(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "tasks.json")
        repo = TaskRepository(path, legacy_path="")
        repo.save([sample_task("task-1")])
        self.assert_target_never_missing(path, lambda: repo.save([sample_task("task-1")]))

    def test_settings_save_replaces_without_removing_first(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "settings.json")
        save_settings({"debug_enabled": True}, path)
        self.assert_target_never_missing(
            path, lambda: save_settings({"debug_enabled": False}, path))
        self.assertFalse(load_settings(path)["debug_enabled"])


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        tasks_module._legacy_migration_done.clear()
        settings_module._legacy_migration_done.clear()

    def test_task_migration_is_attempted_only_once_per_path(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "tasks.json")
        legacy = os.path.join(tmp, "legacy.json")
        handle = open(legacy, "wb")
        try:
            handle.write(json.dumps({"version": 1, "tasks": [sample_task("task-1")]}).encode("utf-8"))
        finally:
            handle.close()

        repo = TaskRepository(path, legacy_path=legacy)
        self.assertEqual([item["id"] for item in repo.load()], ["task-1"])

        # Zielpfad verschwindet (z.B. im Schreibfenster eines parallelen save):
        # die alte Datei darf jetzt NICHT erneut zurueckgespielt werden.
        os.remove(path)
        self.assertEqual(repo.load(), [])
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
