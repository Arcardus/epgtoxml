# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import os
import tempfile
import unittest

from Plugins.Extensions.EpgToXml.settings import get_default_schedule_times, load_settings, save_settings


class DefaultScheduleSettingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "settings.json")

    def test_defaults_are_disabled(self):
        settings = load_settings(self.path)
        self.assertFalse(settings["default_schedule_slot_1_enabled"])
        self.assertFalse(settings["default_schedule_slot_2_enabled"])
        self.assertEqual(get_default_schedule_times(settings), [])

    def test_round_trip_single_slot(self):
        save_settings({
            "default_schedule_slot_1_enabled": True,
            "default_schedule_slot_1_time": "06:15",
        }, self.path)
        settings = load_settings(self.path)
        self.assertTrue(settings["default_schedule_slot_1_enabled"])
        self.assertEqual(settings["default_schedule_slot_1_time"], "06:15")
        self.assertEqual(get_default_schedule_times(settings), ["06:15"])

    def test_round_trip_both_slots(self):
        save_settings({
            "default_schedule_slot_1_enabled": True,
            "default_schedule_slot_1_time": "06:15",
            "default_schedule_slot_2_enabled": True,
            "default_schedule_slot_2_time": "18:00",
        }, self.path)
        settings = load_settings(self.path)
        self.assertEqual(get_default_schedule_times(settings), ["06:15", "18:00"])

    def test_invalid_time_coerced_on_load(self):
        save_settings({
            "default_schedule_slot_1_enabled": True,
            "default_schedule_slot_1_time": "not-a-time",
        }, self.path)
        settings = load_settings(self.path)
        self.assertEqual(settings["default_schedule_slot_1_time"], "00:00")

    def test_disabled_slot_excluded_even_with_time_set(self):
        save_settings({
            "default_schedule_slot_1_enabled": False,
            "default_schedule_slot_1_time": "06:15",
        }, self.path)
        settings = load_settings(self.path)
        self.assertEqual(get_default_schedule_times(settings), [])


if __name__ == "__main__":
    unittest.main()
