# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
"""Der Helper-Subprozess schreibt Status, legt aber keine Tasks an.

Ein Append-Fallback hat frueher Duplikate mit derselben ID erzeugt, und die
haben den Automatik-Scheduler in eine Endlosschleife geschickt.
"""
import os
import tempfile
import unittest

from Plugins.Extensions.EpgToXml import core
from Plugins.Extensions.EpgToXml.core import EpgToXmlRunner
from Plugins.Extensions.EpgToXml.tasks import TaskRepository, make_legacy_task


class FakeProvider(object):
    name = "Fake EPG"

    def fetch(self, task, progress=None):
        return ([{"id": "fake.channel", "name": "Fake"}], [])


def sample_task(task_id):
    task = make_legacy_task(service_ref="1:0:1:1234:0:0:0:0:0:0:", days=3)
    task["id"] = task_id
    task["source_channel_id"] = "fake.channel"
    return task


class CoreTaskStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "tasks.json")
        self.log_path = os.path.join(self.tmp, "run.log")
        self.patched = {}
        for name in ("write_epgimport_program_file", "write_channels_for_tasks",
                     "write_sources_for_tasks"):
            self.patched[name] = getattr(core, name)
            setattr(core, name, lambda *args, **kwargs: None)
        self.patched["get_provider"] = core.get_provider
        core.get_provider = lambda source_id: FakeProvider()

    def tearDown(self):
        for name, original in self.patched.items():
            setattr(core, name, original)

    def run_task(self, task):
        runner = EpgToXmlRunner(task=task, tasks_path=self.path, log_path=self.log_path)
        return runner.run_task(task)

    def test_status_is_written_for_a_known_task(self):
        TaskRepository(self.path, legacy_path="").save([sample_task("task-1")])
        self.run_task(sample_task("task-1"))
        stored = TaskRepository(self.path, legacy_path="").load()
        self.assertEqual(len(stored), 1)
        self.assertTrue(stored[0]["last_status"].startswith("OK: "))

    def test_unknown_task_is_not_appended(self):
        TaskRepository(self.path, legacy_path="").save([sample_task("task-1")])
        self.run_task(sample_task("task-fremd"))
        stored = TaskRepository(self.path, legacy_path="").load()
        self.assertEqual([item["id"] for item in stored], ["task-1"])

    def test_empty_task_file_is_not_overwritten_with_a_single_task(self):
        self.run_task(sample_task("task-1"))
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
