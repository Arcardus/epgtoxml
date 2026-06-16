# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import glob
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "Plugins", "Extensions", "EpgToXml")
ENGINE = os.path.join(PKG, "epgimport_engine")

MIT = "SPDX-License-Identifier: MIT"
GPL = "SPDX-License-Identifier: GPL-2.0-only"


def read(path):
    handle = open(path, "rb")
    try:
        return handle.read().decode("utf-8")
    finally:
        handle.close()


class LicenseHeaderTests(unittest.TestCase):
    def test_engine_files_are_gplv2(self):
        engine_files = sorted(glob.glob(os.path.join(ENGINE, "*.py")))
        self.assertTrue(engine_files)
        for path in engine_files:
            text = read(path)
            self.assertIn(GPL, text, "missing GPL-2.0-only header: " + path)
            self.assertNotIn(MIT, text, "engine file must not be MIT: " + path)

    def test_own_files_are_mit(self):
        own = [
            "plugin.py", "core.py", "epgimport_adapter.py", "epgimport_files.py",
            "tasks.py", "runner_cli.py", "paths.py", "settings.py",
            "debuglog.py", "compat.py", "sky_client.py", "__init__.py",
        ]
        for name in own:
            text = read(os.path.join(PKG, name))
            self.assertIn(MIT, text, "missing MIT header: " + name)
            self.assertNotIn(GPL, text, "own file must not be GPL: " + name)

    def test_every_plugin_source_has_an_spdx_header(self):
        for path in glob.glob(os.path.join(PKG, "**", "*.py"), recursive=True):
            text = read(path)
            self.assertIn("SPDX-License-Identifier:", text,
                          "missing SPDX header: " + path)


if __name__ == "__main__":
    unittest.main()
