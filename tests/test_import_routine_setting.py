# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import json
import os
import tempfile
import unittest

from Plugins.Extensions.EpgToXml.settings import load_settings, save_settings


class ImportRoutineSettingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "settings.json")

    def test_default_is_auto(self):
        self.assertEqual(load_settings(self.path).get("import_routine"), "auto")

    def test_valid_values_round_trip(self):
        for value in ("auto", "a", "b"):
            save_settings({"import_routine": value}, self.path)
            self.assertEqual(load_settings(self.path).get("import_routine"), value)

    def test_invalid_value_coerced_to_auto_on_load(self):
        handle = open(self.path, "wb")
        try:
            handle.write(json.dumps({"import_routine": "invalid"}).encode("utf-8"))
        finally:
            handle.close()
        self.assertEqual(load_settings(self.path).get("import_routine"), "auto")

    def test_invalid_value_coerced_to_auto_on_save(self):
        saved = save_settings({"import_routine": "x"}, self.path)
        self.assertEqual(saved.get("import_routine"), "auto")

    def test_none_coerced_to_auto_on_load(self):
        handle = open(self.path, "wb")
        try:
            handle.write(json.dumps({"import_routine": None}).encode("utf-8"))
        finally:
            handle.close()
        self.assertEqual(load_settings(self.path).get("import_routine"), "auto")

    def test_get_set_import_routine_end_to_end(self):
        from Plugins.Extensions.EpgToXml.settings import load_settings, save_settings
        for value in ("b", "a", "auto"):
            save_settings({"import_routine": value}, self.path)
            self.assertEqual(load_settings(self.path).get("import_routine"), value)

    def test_set_import_routine_rejects_invalid(self):
        from Plugins.Extensions.EpgToXml.settings import load_settings, save_settings
        save_settings({"import_routine": "invalid"}, self.path)
        self.assertEqual(load_settings(self.path).get("import_routine"), "auto")


if __name__ == "__main__":
    unittest.main()
