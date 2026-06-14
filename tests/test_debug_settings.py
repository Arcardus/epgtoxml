import json
import os
import tempfile
import unittest

from Plugins.Extensions.EpgToXml import debuglog
from Plugins.Extensions.EpgToXml.settings import load_settings


class DebugSettingsTests(unittest.TestCase):
    def test_debug_is_enabled_by_default(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "settings.json")
        self.assertTrue(load_settings(path).get("debug_enabled"))

    def test_settings_load_copies_legacy_file_when_new_path_is_missing(self):
        tmp = tempfile.mkdtemp()
        new_path = os.path.join(tmp, "new", "settings.json")
        legacy_path = os.path.join(tmp, "old", "settings.json")
        os.makedirs(os.path.dirname(legacy_path))
        handle = open(legacy_path, "wb")
        try:
            handle.write(json.dumps({"debug_enabled": False}).encode("utf-8"))
        finally:
            handle.close()

        settings = load_settings(new_path, legacy_path=legacy_path)

        self.assertFalse(settings.get("debug_enabled"))
        self.assertTrue(os.path.exists(new_path))
        self.assertTrue(os.path.exists(legacy_path))

    def test_debug_log_rotates(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "epgtoxml-debug.log")
        rotated = os.path.join(tmp, "epgtoxml-debug.log.1")
        handle = open(path, "wb")
        try:
            handle.write(b"x" * (20 * 1024 + 1))
        finally:
            handle.close()
        old_path = debuglog.DEBUG_LOG_PATH
        old_rotated = debuglog.DEBUG_LOG_ROTATED_PATH
        try:
            debuglog.DEBUG_LOG_PATH = path
            debuglog.DEBUG_LOG_ROTATED_PATH = rotated
            debuglog.write_debug("after rotation", force=True)
        finally:
            debuglog.DEBUG_LOG_PATH = old_path
            debuglog.DEBUG_LOG_ROTATED_PATH = old_rotated
        self.assertTrue(os.path.exists(rotated))
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
