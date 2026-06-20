# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import json
import os
import subprocess
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "Plugins", "Extensions", "EpgToXml", "runner_cli.py")


class RunnerCliTests(unittest.TestCase):
    def test_direct_script_start_bootstraps_package_imports(self):
        process = subprocess.Popen(
            [sys.executable, RUNNER],
            cwd=os.path.dirname(RUNNER),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 2, stderr.decode("utf-8", "replace"))
        lines = stdout.decode("utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("EPGTOXML "))
        event = json.loads(lines[0][len("EPGTOXML "):])
        self.assertEqual(event["kind"], "error")
        self.assertIn("Task-ID", event["message"])


if __name__ == "__main__":
    unittest.main()
