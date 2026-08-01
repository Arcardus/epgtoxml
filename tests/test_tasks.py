# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import json
import os
import tempfile
import unittest

from Plugins.Extensions.EpgToXml.tasks import (
    TaskRepository, clean_task_name, default_task, make_legacy_task, normalise_schedule_times,
    normalise_task, validate_task,
)


class TaskTests(unittest.TestCase):
    def test_load_save_task_json(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "tasks.json")
        repo = TaskRepository(path)
        task = make_legacy_task(
            service_ref="1:0:1:1234:0:0:0:0:0:0:",
            days=9,
        )
        repo.save([task])

        loaded = repo.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["target_service_ref"], "1:0:1:1234:0:0:0:0:0:0:")
        self.assertEqual(loaded[0]["days"], 9)
        self.assertFalse(loaded[0]["schedule_enabled"])
        self.assertEqual(loaded[0]["schedule_times"], [])
        self.assertFalse(loaded[0]["schedule_slot_1_enabled"])
        self.assertEqual(loaded[0]["schedule_slot_1_time"], "00:00")

        handle = open(path, "rb")
        try:
            data = json.load(handle)
        finally:
            handle.close()
        self.assertEqual(data["version"], 1)

    def test_migrate_legacy_only_when_empty(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "tasks.json")
        repo = TaskRepository(path)
        tasks = repo.migrate_legacy_if_needed("1:0:1:1234:0:0:0:0:0:0:", 5)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["days"], 5)
        self.assertNotIn("unknown_legacy_value", tasks[0])

        again = repo.migrate_legacy_if_needed("different", 1)
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["days"], 5)

    def test_load_copies_legacy_file_when_new_path_is_missing(self):
        tmp = tempfile.mkdtemp()
        new_path = os.path.join(tmp, "new", "tasks.json")
        legacy_path = os.path.join(tmp, "old", "tasks.json")
        os.makedirs(os.path.dirname(legacy_path))
        task = make_legacy_task(
            service_ref="1:0:1:1234:0:0:0:0:0:0:",
            days=3,
        )
        handle = open(legacy_path, "wb")
        try:
            handle.write(json.dumps({"version": 1, "tasks": [task]}).encode("utf-8"))
        finally:
            handle.close()

        repo = TaskRepository(new_path, legacy_path=legacy_path)
        loaded = repo.load()

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["target_service_ref"], "1:0:1:1234:0:0:0:0:0:0:")
        self.assertTrue(os.path.exists(new_path))
        self.assertTrue(os.path.exists(legacy_path))

    def test_validate_requires_target_service(self):
        task = make_legacy_task(service_ref="")
        with self.assertRaises(Exception):
            validate_task(task)

    def test_normalise_replaces_not_a_string_name(self):
        task = normalise_task({"name": "not a string"})
        self.assertEqual(task["name"], "Neuer Task")

    def test_normalise_drops_unknown_legacy_fields(self):
        task = normalise_task({
            "source_id": "dazn_de",
            "source_channel_id": "dazn.de.dazn-1",
            "unknown_legacy_value": "old",
        })
        self.assertEqual(task["source_id"], "dazn_de")
        self.assertNotIn("unknown_legacy_value", task)
        self.assertNotIn("sky_channel_id", task)
        self.assertNotIn("sky_channel_slug", task)

    def test_normalise_preserves_redbull_channel_id(self):
        task = normalise_task({
            "source_id": "redbull_tv",
            "redbull_channel_id": "c81f8686-ab67-4965-ba04-5f6658bb96cc",
        })
        self.assertEqual(task["redbull_channel_id"], "c81f8686-ab67-4965-ba04-5f6658bb96cc")

    def test_normalise_preserves_rtlplus_channel_id(self):
        task = normalise_task({
            "source_id": "rtl_plus",
            "rtlplus_channel_id": "a684c2539c02651195f8e25de5ca7b18e0a937b2",
        })
        self.assertEqual(task["rtlplus_channel_id"], "a684c2539c02651195f8e25de5ca7b18e0a937b2")

    def test_normalise_preserves_hdplus_channel_id(self):
        task = normalise_task({
            "source_id": "hdplus_de",
            "hdplus_channel_id": "das_erste_hd",
        })
        self.assertEqual(task["hdplus_channel_id"], "das_erste_hd")

    def test_clean_task_name_rejects_object_repr(self):
        self.assertEqual(clean_task_name("<ConfigText object>", "Fallback"), "Fallback")
        self.assertEqual(clean_task_name("", "Fallback"), "Fallback")
        self.assertEqual(clean_task_name("DFB Import", "Fallback"), "DFB Import")

    def test_normalise_schedule_times(self):
        self.assertEqual(normalise_schedule_times(["5:00", "25:00", "07:30", "08:00", ""]), ["05:00", "07:30"])
        self.assertEqual(normalise_schedule_times([]), [])
        self.assertEqual(normalise_schedule_times(["1031", "0000"]), ["10:31", "00:00"])

    def test_schedule_slots_allow_midnight(self):
        task = normalise_task({
            "schedule_slot_1_enabled": True,
            "schedule_slot_1_time": "0000",
            "schedule_slot_2_enabled": False,
        })
        self.assertTrue(task["schedule_enabled"])
        self.assertEqual(task["schedule_times"], ["00:00"])

    def test_default_days_is_three(self):
        self.assertEqual(normalise_task({})["days"], 3)

    def test_new_task_defaults_to_schedule_mode_default(self):
        self.assertEqual(default_task()["schedule_mode"], "default")

    def test_schedule_mode_default_uses_global_default_times(self):
        task = normalise_task(default_task(), default_schedule_times=["06:00", "18:00"])
        self.assertEqual(task["schedule_mode"], "default")
        self.assertTrue(task["schedule_enabled"])
        self.assertEqual(task["schedule_times"], ["06:00", "18:00"])

    def test_schedule_mode_default_with_no_global_default_disables_schedule(self):
        task = normalise_task(default_task(), default_schedule_times=[])
        self.assertEqual(task["schedule_mode"], "default")
        self.assertFalse(task["schedule_enabled"])
        self.assertEqual(task["schedule_times"], [])

    def test_schedule_mode_custom_ignores_global_default(self):
        raw = default_task()
        raw["schedule_mode"] = "custom"
        raw["schedule_slot_1_enabled"] = True
        raw["schedule_slot_1_time"] = "10:00"
        task = normalise_task(raw, default_schedule_times=["06:00"])
        self.assertEqual(task["schedule_mode"], "custom")
        self.assertEqual(task["schedule_times"], ["10:00"])

    def test_schedule_mode_off_ignores_global_default(self):
        raw = default_task()
        raw["schedule_mode"] = "off"
        task = normalise_task(raw, default_schedule_times=["06:00"])
        self.assertEqual(task["schedule_mode"], "off")
        self.assertFalse(task["schedule_enabled"])
        self.assertEqual(task["schedule_times"], [])

    def test_legacy_task_without_schedule_mode_key_stays_off(self):
        """Tasks aus einer tasks.json von vor dem globalen Zeitplan (kein
        "schedule_mode"-Feld, nie konfigurierter Zeitplan) dürfen den neuen
        globalen Fallback nicht unbemerkt übernehmen."""
        task = normalise_task({"schedule_slot_1_enabled": False}, default_schedule_times=["06:00"])
        self.assertEqual(task["schedule_mode"], "off")
        self.assertFalse(task["schedule_enabled"])
        self.assertEqual(task["schedule_times"], [])

    def test_legacy_task_without_schedule_mode_key_preserves_custom_slots(self):
        task = normalise_task({
            "schedule_slot_1_enabled": True,
            "schedule_slot_1_time": "10:00",
        }, default_schedule_times=["06:00"])
        self.assertEqual(task["schedule_mode"], "custom")
        self.assertEqual(task["schedule_times"], ["10:00"])

    def test_invalid_schedule_mode_falls_back_like_legacy(self):
        raw = default_task()
        raw["schedule_mode"] = "not-a-mode"
        raw["schedule_slot_1_enabled"] = True
        raw["schedule_slot_1_time"] = "10:00"
        task = normalise_task(raw, default_schedule_times=["06:00"])
        self.assertEqual(task["schedule_mode"], "custom")
        self.assertEqual(task["schedule_times"], ["10:00"])


if __name__ == "__main__":
    unittest.main()
