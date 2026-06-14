import sys
import types
import unittest

from Plugins.Extensions.EpgToXml.epgimport_adapter import (
    probe_epgimport, read_last_import_result, start_epgimport,
)


MODULES = [
    "Plugins.Extensions.EPGImport.plugin",
    "Plugins.Extensions.EPGImport",
]


class Source(object):
    def __init__(self, description):
        self.description = description


class FakeImporter(object):
    def __init__(self, running=False):
        self.running = running
        self.sources = []

    def isImportRunning(self):
        return self.running


class FakeEPGConfig(object):
    def __init__(self, descriptions):
        self.descriptions = descriptions
        self.calls = []

    def enumSources(self, path, filter=None, categories=False):
        self.calls.append((path, filter))
        for description in self.descriptions:
            if filter is None or description in filter:
                yield Source(description)


class EPGImportAdapterTests(unittest.TestCase):
    def tearDown(self):
        for name in MODULES:
            if name in sys.modules:
                del sys.modules[name]

    def install_fake_epgimport(self, descriptions, running=False, fail_start=False,
                               consume_sources=False, last_result=None,
                               missing_api=False):
        package = types.ModuleType("Plugins.Extensions.EPGImport")
        plugin = types.ModuleType("Plugins.Extensions.EPGImport.plugin")
        importer = FakeImporter(running=running)
        config = FakeEPGConfig(descriptions)
        started = []

        def startImport():
            if fail_start:
                raise RuntimeError("boom")
            if consume_sources:
                while importer.sources:
                    importer.sources.pop()
            started.append(True)

        plugin.epgimport = importer
        plugin.lastImportResult = last_result
        plugin.EPGConfig = config
        if not missing_api:
            plugin.startImport = startImport
        package.plugin = plugin
        sys.modules["Plugins.Extensions.EPGImport"] = package
        sys.modules["Plugins.Extensions.EPGImport.plugin"] = plugin
        return importer, config, started

    def test_starts_selected_epgimport_source(self):
        importer, config, started = self.install_fake_epgimport([
            "Other",
            "EpgToXml - Sky DFB.TV [task-1]",
        ])

        result = start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"],
                                 config_path="/etc/epgimport")

        self.assertTrue(result.started)
        self.assertEqual(config.calls[0], ("/etc/epgimport", ["EpgToXml - Sky DFB.TV [task-1]"]))
        self.assertEqual(len(importer.sources), 1)
        self.assertEqual(importer.sources[0].description, "EpgToXml - Sky DFB.TV [task-1]")
        self.assertEqual(started, [True])

    def test_reports_source_count_before_epgimport_consumes_sources(self):
        importer, config, started = self.install_fake_epgimport([
            "EpgToXml - Sky DFB.TV [task-1]",
        ], consume_sources=True)

        result = start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])

        self.assertTrue(result.started)
        self.assertEqual(result.source_count, 1)
        self.assertEqual(result.message, "EPGImport gestartet: 1 Quelle(n)")
        self.assertEqual(importer.sources, [])
        self.assertEqual(started, [True])

    def test_does_not_start_when_import_is_running(self):
        importer, config, started = self.install_fake_epgimport(["EpgToXml - Sky DFB.TV [task-1]"],
                                                                running=True)

        result = start_epgimport(source_descriptions=["EpgToXml - Sky DFB.TV [task-1]"])

        self.assertFalse(result.started)
        self.assertEqual(config.calls, [])
        self.assertEqual(started, [])
        self.assertEqual(importer.sources, [])

    def test_reports_missing_generated_source(self):
        importer, config, started = self.install_fake_epgimport(["Other"])

        result = start_epgimport(source_descriptions=["EpgToXml - Missing [task-x]"])

        self.assertFalse(result.started)
        self.assertTrue("Keine EPGImport-Quelle gefunden" in result.message)
        self.assertEqual(started, [])
        self.assertEqual(importer.sources, [])

    def test_probe_reports_ready_and_running(self):
        self.install_fake_epgimport(["EpgToXml - Sky DFB.TV [task-1]"])
        ready = probe_epgimport()
        self.assertTrue(ready.installed)
        self.assertTrue(ready.ready)
        self.assertFalse(ready.running)

        self.install_fake_epgimport(["EpgToXml - Sky DFB.TV [task-1]"], running=True)
        running = probe_epgimport()
        self.assertTrue(running.installed)
        self.assertTrue(running.ready)
        self.assertTrue(running.running)

    def test_probe_reports_incompatible_api(self):
        self.install_fake_epgimport(["EpgToXml - Sky DFB.TV [task-1]"], missing_api=True)
        result = probe_epgimport()
        self.assertTrue(result.installed)
        self.assertFalse(result.ready)

    def test_reads_last_import_result(self):
        self.install_fake_epgimport(["EpgToXml - Sky DFB.TV [task-1]"],
                                    last_result=(1234.0, 55))
        self.assertEqual(read_last_import_result(), (1234.0, 55))


if __name__ == "__main__":
    unittest.main()
