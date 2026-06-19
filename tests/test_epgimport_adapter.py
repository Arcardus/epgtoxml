# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import os
import sqlite3
import sys
import tempfile
import types
import unittest

from Plugins.Extensions.EpgToXml import epgimport_adapter as adapter
from Plugins.Extensions.EpgToXml.epgimport_adapter import (
    probe_epgimport, read_last_import_result, start_epgimport,
)


ENGINE_PKG = "Plugins.Extensions.EpgToXml.epgimport_engine"
MODULES = [ENGINE_PKG + ".EPGConfig", ENGINE_PKG + ".EPGImport", ENGINE_PKG]


def make_epgdb(path, rytec_count, other_count=0, begin=1900000000):
    """Minimal-epg.db mit der von _inspect_epgdb abgefragten Struktur."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE T_Source (id INTEGER PRIMARY KEY, "
                "source_name TEXT NOT NULL, priority INTEGER NOT NULL)")
    cur.execute("CREATE TABLE T_Event (id INTEGER PRIMARY KEY, "
                "service_id INTEGER, begin_time INTEGER, duration INTEGER, "
                "source_id INTEGER, dvb_event_id INTEGER)")
    cur.execute("INSERT INTO T_Source (id, source_name, priority) "
                "VALUES (5, 'Rytec XMLTV', 99)")
    cur.execute("INSERT INTO T_Source (id, source_name, priority) "
                "VALUES (1, 'DVB Now/Next Table', 0)")
    for i in range(rytec_count):
        cur.execute("INSERT INTO T_Event (service_id, begin_time, duration, "
                    "source_id, dvb_event_id) VALUES (1, ?, 60, 5, ?)",
                    (begin + i * 60, i))
    for i in range(other_count):
        cur.execute("INSERT INTO T_Event (service_id, begin_time, duration, "
                    "source_id, dvb_event_id) VALUES (2, ?, 60, 1, ?)",
                    (begin + i * 60, i))
    conn.commit()
    conn.close()


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
        self.selected_routine = None
        self.running = FakeEngine.next_running
        self.begin_calls = []
        FakeEngine.instances.append(self)

    def isImportRunning(self):
        return self.running

    def beginImport(self, longDescUntil=None):
        # Simulate the reactor-driven import: count events, consume the
        # sources and notify the onDone callback (like the real engine).
        force = getattr(self, "force_routine", "auto")
        self.begin_calls.append({
            "longDescUntil": longDescUntil,
            "force_routine": force,
        })
        # Mirror the engine's storage selection so selected_routine is realistic.
        if force == "b":
            self.selected_routine = "b"
        elif hasattr(self.epgcache, "importEvents"):
            self.selected_routine = "a1"
        elif hasattr(self.epgcache, "importEvent"):
            self.selected_routine = "a2"
        else:
            self.selected_routine = "b"
        self.eventCount = 7 * len(self.sources)
        self.sources = []
        if self.onDone:
            self.onDone(reboot=False, epgfile=None)


class FakeEPGCacheWithPatch(object):
    """Stand-in eEPGCache that exposes the Route-A importEvents patch."""

    def importEvents(self, services, events):
        pass


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
        self.assertTrue(result.message.startswith("EPG-Import gestartet: 1 Quelle(n)"))
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
        stamp, count, verdict = result
        self.assertGreater(stamp, 0)
        self.assertEqual(count, 7)
        # Ohne erreichbare epg.db (kein enigma im Test) -> unverified.
        self.assertEqual(verdict, "unverified")

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

    def test_force_routine_a_aborts_without_patch(self):
        # epgcache is None in the test runtime (no enigma) -> Route A unsupported.
        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"])
        old_getter = adapter.get_import_routine
        try:
            adapter.get_import_routine = lambda: "a"
            result = start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])
        finally:
            adapter.get_import_routine = old_getter

        self.assertFalse(result.started)
        self.assertIn("Routine A wird von dieser Box nicht unterstützt", result.message)
        self.assertIn("Routine A wird von dieser Box nicht unterstützt", result.error)
        # beginImport must never be called when Route A is gated.
        self.assertEqual(FakeEngine.instances[-1].begin_calls, [])

    def test_force_routine_a_runs_when_patch_present(self):
        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"])
        old_getter = adapter.get_import_routine
        old_cache = adapter._epgcache_instance
        try:
            adapter.get_import_routine = lambda: "a"
            adapter._epgcache_instance = lambda: FakeEPGCacheWithPatch()
            adapter.reset_engine()
            result = start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])
        finally:
            adapter.get_import_routine = old_getter
            adapter._epgcache_instance = old_cache

        self.assertTrue(result.started)
        self.assertEqual(result.selected_routine, "a1")
        self.assertIn("Routine A", result.message)

    def test_selected_routine_reported(self):
        # Default routine "auto" + no patch -> engine selects Route B.
        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"])
        old_getter = adapter.get_import_routine
        try:
            adapter.get_import_routine = lambda: "auto"
            result = start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])
        finally:
            adapter.get_import_routine = old_getter

        self.assertTrue(result.started)
        self.assertEqual(result.selected_routine, "b")
        self.assertIn("Routine B", result.message)

    # --- Post-Import-Check (Verdikt) -------------------------------------

    def _run_with_epgdb(self, db_path, routine="auto", patch_cache=False,
                        wait_for_db=None):
        self.install_fake_engine(["EpgToXml - Sky DFB.TV [task-1]"])
        old_path = adapter._epgdb_path
        old_getter = adapter.get_import_routine
        old_cache = adapter._epgcache_instance
        old_wait = adapter.wait_for_db_ready
        try:
            adapter._epgdb_path = lambda: db_path
            adapter.get_import_routine = lambda: routine
            if wait_for_db is None:
                def wait_for_db(path, min_size):
                    return os.path.exists(path)
            adapter.wait_for_db_ready = wait_for_db
            if patch_cache:
                adapter._epgcache_instance = lambda: FakeEPGCacheWithPatch()
                adapter.reset_engine()
            start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])
        finally:
            adapter._epgdb_path = old_path
            adapter.get_import_routine = old_getter
            adapter._epgcache_instance = old_cache
            adapter.wait_for_db_ready = old_wait
        return read_last_import_result()

    def test_verdict_ok_when_events_landed(self):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "epg.db")
        make_epgdb(db, rytec_count=7)
        stamp, count, verdict = self._run_with_epgdb(db)
        self.assertEqual(count, 7)
        self.assertEqual(verdict, "ok")

    def test_verdict_failed_when_db_missing(self):
        db = "/nonexistent/path/epg.db"
        stamp, count, verdict = self._run_with_epgdb(db)
        self.assertEqual(count, 7)
        self.assertEqual(verdict, "failed")

    def test_verdict_failed_when_source_empty(self):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "epg.db")
        make_epgdb(db, rytec_count=0, other_count=5)
        stamp, count, verdict = self._run_with_epgdb(db)
        self.assertEqual(count, 7)
        self.assertEqual(verdict, "failed")

    def test_verdict_unverified_for_route_a(self):
        # Route A schreibt direkt in den Live-Cache -> nicht on-disk geprueft,
        # selbst wenn die epg.db Events enthielte.
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "epg.db")
        make_epgdb(db, rytec_count=7)
        stamp, count, verdict = self._run_with_epgdb(db, routine="a",
                                                     patch_cache=True)
        self.assertEqual(verdict, "unverified")

    def test_route_b_waits_for_final_db_save_before_inspection(self):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "epg.db")
        make_epgdb(db, rytec_count=7)
        calls = []

        def wait_for_db(path, min_size):
            calls.append((path, min_size))
            return True

        stamp, count, verdict = self._run_with_epgdb(
            db, wait_for_db=wait_for_db)
        self.assertEqual(count, 7)
        self.assertEqual(verdict, "ok")
        self.assertEqual(calls, [(db, 23 * 1024)])

    def test_inspect_epgdb_reports_source_count(self):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "epg.db")
        make_epgdb(db, rytec_count=42, other_count=3)
        old_path = adapter._epgdb_path
        try:
            adapter._epgdb_path = lambda: db
            state = adapter._inspect_epgdb("test")
        finally:
            adapter._epgdb_path = old_path
        self.assertTrue(state["exists"])
        self.assertTrue(state["readable"])
        self.assertTrue(state["is_db"])
        self.assertEqual(state["total"], 45)
        self.assertEqual(state["source_count"], 42)


if __name__ == "__main__":
    unittest.main()
