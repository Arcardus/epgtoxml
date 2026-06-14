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
