# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import sys
import types
import unittest

from Plugins.Extensions.EpgToXml import epgimport_adapter as adapter
from Plugins.Extensions.EpgToXml.epgimport_adapter import (
    probe_epgimport, read_last_import_result, start_epgimport,
)


ENGINE_PKG = "Plugins.Extensions.EpgToXml.epgimport_engine"
MODULES = [ENGINE_PKG + ".EPGConfig", ENGINE_PKG + ".EPGImport", ENGINE_PKG]


class Source(object):
    def __init__(self, description):
        self.description = description


class FakeEngine(object):
    """Stand-in for the embedded EPGImport.EPGImport importer."""

    instances = []
    next_running = False

    def __init__(self, epgcache, channelFilter):
        self.epgcache = epgcache
        self.channelFilter = channelFilter
        self.sources = []
        self.onDone = None
        self.eventCount = None
        self.running = FakeEngine.next_running
        self.begin_calls = []
        FakeEngine.instances.append(self)

    def isImportRunning(self):
        return self.running

    def beginImport(self, longDescUntil=None):
        # Simulate the reactor-driven import: count events, consume the
        # sources and notify the onDone callback (like the real engine).
        self.begin_calls.append({
            "longDescUntil": longDescUntil,
            "force_routine": getattr(self, "force_routine", "auto"),
        })
        self.eventCount = 7 * len(self.sources)
        self.sources = []
        if self.onDone:
            self.onDone(reboot=False, epgfile=None)


class FakeConfig(object):
    descriptions = []
    calls = []

    @staticmethod
    def enumSources(path, filter=None, categories=False):
        FakeConfig.calls.append((path, filter))
        for description in FakeConfig.descriptions:
            if filter is None or description in filter:
                yield Source(description)


class EPGImportAdapterTests(unittest.TestCase):
    def tearDown(self):
        for name in MODULES:
            if name in sys.modules:
                del sys.modules[name]
        adapter.reset_engine()
        FakeEngine.instances = []
        FakeEngine.next_running = False
        FakeConfig.descriptions = []
        FakeConfig.calls = []

    def install_fake_engine(self, descriptions, running=False):
        FakeEngine.instances = []
        FakeEngine.next_running = running
        FakeConfig.descriptions = list(descriptions)
        FakeConfig.calls = []

        package = types.ModuleType(ENGINE_PKG)
        engine_mod = types.ModuleType(ENGINE_PKG + ".EPGImport")
        engine_mod.EPGImport = FakeEngine
        engine_mod.HDD_EPG_DAT = "/hdd/epg.dat"
        config_mod = types.ModuleType(ENGINE_PKG + ".EPGConfig")
        config_mod.enumSources = FakeConfig.enumSources
        package.EPGImport = engine_mod
        package.EPGConfig = config_mod

        sys.modules[ENGINE_PKG] = package
        sys.modules[ENGINE_PKG + ".EPGImport"] = engine_mod
        sys.modules[ENGINE_PKG + ".EPGConfig"] = config_mod
        adapter.reset_engine()
        return engine_mod, config_mod

    def test_starts_selected_source(self):
        self.install_fake_engine([
            "Other",
            "EpgToXml - Sky DFB.TV [task-1]",
        ])

        result = start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"],
                                 config_path="/etc/epgtoxml/import")

        self.assertTrue(result.started)
        self.assertEqual(FakeConfig.calls[0], ("/etc/epgtoxml/import", ["EpgToXml - Sky DFB.TV [task-1]"]))
        engine = FakeEngine.instances[-1]
        self.assertEqual(engine.begin_calls and True, True)
        self.assertEqual(result.source_descriptions, ["EpgToXml - Sky DFB.TV [task-1]"])

    def test_reports_source_count_before_engine_consumes_sources(self):
        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"])

        result = start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])

        self.assertTrue(result.started)
        self.assertEqual(result.source_count, 1)
        self.assertEqual(result.message, "EPG-Import gestartet: 1 Quelle(n)")
        # engine consumed the sources during beginImport
        self.assertEqual(FakeEngine.instances[-1].sources, [])

    def test_does_not_start_when_import_is_running(self):
        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"], running=True)

        result = start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])

        self.assertFalse(result.started)
        self.assertIn("läuft bereits", result.message)
        self.assertEqual(FakeConfig.calls, [])

    def test_reports_missing_generated_source(self):
        self.install_fake_engine(["Other"])

        result = start_epgimport(source_descriptions=["EpgToXml - Missing [task-x]"])

        self.assertFalse(result.started)
        self.assertTrue("Keine EPG-Quelle gefunden" in result.message)

    def test_probe_reports_ready_and_running(self):
        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"])
        ready = probe_epgimport()
        self.assertTrue(ready.installed)
        self.assertTrue(ready.ready)
        self.assertFalse(ready.running)

        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"], running=True)
        running = probe_epgimport()
        self.assertTrue(running.installed)
        self.assertTrue(running.running)

    def test_records_last_import_result_after_done(self):
        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"])
        self.assertIsNone(read_last_import_result())

        start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])

        result = read_last_import_result()
        self.assertIsNotNone(result)
        stamp, count = result
        self.assertGreater(stamp, 0)
        self.assertEqual(count, 7)

    def test_reports_engine_unavailable_when_not_embedded(self):
        # No fakes installed: importing the real (Python 2) engine modules
        # fails under the Python 3 test runtime -> graceful degradation.
        for name in MODULES:
            if name in sys.modules:
                del sys.modules[name]
        adapter.reset_engine()

        result = start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])
        self.assertFalse(result.started)
        self.assertIn("nicht verfügbar", result.message)

    def test_force_routine_auto_forwarded_to_engine(self):
        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"])
        old_getter = adapter.get_import_routine
        try:
            adapter.get_import_routine = lambda: "auto"
            start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])
            engine = FakeEngine.instances[-1]
            self.assertEqual(engine.begin_calls[-1]["force_routine"], "auto")
        finally:
            adapter.get_import_routine = old_getter

    def test_force_routine_b_forwarded_to_engine(self):
        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"])
        old_getter = adapter.get_import_routine
        try:
            adapter.get_import_routine = lambda: "b"
            start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])
            engine = FakeEngine.instances[-1]
            self.assertEqual(engine.begin_calls[-1]["force_routine"], "b")
        finally:
            adapter.get_import_routine = old_getter


if __name__ == "__main__":
    unittest.main()
