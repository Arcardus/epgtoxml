import datetime
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from Plugins.Extensions.EpgToXml.epgimport_files import (
    source_description_for_task,
    write_channels, write_channels_for_tasks, write_sources, write_sources_for_tasks,
    write_epgimport_program_file,
)
from Plugins.Extensions.EpgToXml.paths import (
    DEBUG_LOG_PATH, EPGIMPORT_PROGRAM_PATH, OUTPUT_DIR, SETTINGS_PATH, TASKS_PATH,
)


class EPGImportFileTests(unittest.TestCase):
    def test_write_epgimport_program_and_source_files(self):
        tmp = tempfile.mkdtemp()
        program_path = os.path.join(tmp, "epgtoxml-sky.xml")
        channels_path = os.path.join(tmp, "epgtoxml.channels.xml")
        sources_path = os.path.join(tmp, "epgtoxml.sources.xml")
        channels = [{"id": "sky.de.dfb-tv", "name": "DFB.TV", "logo": "https://example/logo.png"}]
        programmes = [{
            "channel_id": "sky.de.dfb-tv",
            "title": "WM-Live",
            "category": "Fußball",
            "start": datetime.datetime(2026, 6, 11, 1, 0),
            "stop": datetime.datetime(2026, 6, 11, 2, 0),
            "country": "D",
            "year": 2026,
            "rating": "ab 0 Jahre",
        }]

        write_epgimport_program_file(channels, programmes, program_path)
        write_channels("1:0:1:1234:0:0:0:0:0:0:", path=channels_path)
        write_sources(path=sources_path, channels_file="epgtoxml.channels.xml", program_path=program_path)

        tv = ET.parse(program_path).getroot()
        self.assertEqual(tv.find("channel").attrib["id"], "sky.de.dfb-tv")
        programme = tv.find("programme")
        self.assertEqual(programme.attrib["channel"], "sky.de.dfb-tv")
        self.assertTrue(programme.attrib["start"].startswith("20260611010000 "))
        self.assertEqual(programme.find("title").text, "WM-Live")

        mapping = ET.parse(channels_path).getroot().find("channel")
        self.assertEqual(mapping.attrib["id"], "sky.de.dfb-tv")
        self.assertEqual(mapping.text, "1:0:1:1234:0:0:0:0:0:0:")

        source = ET.parse(sources_path).getroot().find("sourcecat").find("source")
        self.assertEqual(source.attrib["type"], "gen_xmltv")
        self.assertEqual(source.attrib["channels"], "epgtoxml.channels.xml")

    def test_write_task_epgimport_files(self):
        tmp = tempfile.mkdtemp()
        channels_path = os.path.join(tmp, "epgtoxml.channels.xml")
        sources_path = os.path.join(tmp, "epgtoxml.sources.xml")
        tasks = [{
            "id": "task-1",
            "name": "Sky DFB.TV",
            "enabled": True,
            "source_channel_id": "sky.de.dfb-tv",
            "target_service_ref": "1:0:1:1234:0:0:0:0:0:0:",
        }]
        paths = {"task-1": "/tmp/epgtoxml/output/task-1.xml"}

        write_channels_for_tasks(tasks, path=channels_path)
        write_sources_for_tasks(tasks, paths, path=sources_path)

        mapping = ET.parse(channels_path).getroot().find("channel")
        self.assertEqual(mapping.attrib["id"], "sky.de.dfb-tv")
        self.assertEqual(mapping.text, "1:0:1:1234:0:0:0:0:0:0:")

        source = ET.parse(sources_path).getroot().find("sourcecat").find("source")
        self.assertEqual(source.find("url").text, "/tmp/epgtoxml/output/task-1.xml")
        self.assertEqual(source.find("description").text, "EpgToXml - Sky DFB.TV [task-1]")

    def test_write_task_mapping_uses_selected_source_channel(self):
        tmp = tempfile.mkdtemp()
        channels_path = os.path.join(tmp, "epgtoxml.channels.xml")
        tasks = [{
            "id": "task-2",
            "name": "Sky DAZN 1 HD",
            "enabled": True,
            "source_channel_id": "sky.de.dazn-1-hd",
            "target_service_ref": "1:0:19:9999:0:0:0:0:0:0:",
        }]

        write_channels_for_tasks(tasks, path=channels_path)

        mapping = ET.parse(channels_path).getroot().find("channel")
        self.assertEqual(mapping.attrib["id"], "sky.de.dazn-1-hd")
        self.assertEqual(mapping.text, "1:0:19:9999:0:0:0:0:0:0:")

    def test_task_source_description_is_unique(self):
        first = {"id": "task-1", "name": "Sky DFB.TV"}
        second = {"id": "task-2", "name": "Sky DFB.TV"}
        self.assertNotEqual(source_description_for_task(first), source_description_for_task(second))

    def test_only_epgimport_program_files_are_temporary(self):
        self.assertEqual(OUTPUT_DIR, "/tmp/epgtoxml/output")
        self.assertTrue(EPGIMPORT_PROGRAM_PATH.startswith("/tmp/epgtoxml/output/"))
        self.assertTrue(TASKS_PATH.startswith("/media/hdd/epgtoxml/"))
        self.assertTrue(SETTINGS_PATH.startswith("/media/hdd/epgtoxml/"))
        self.assertTrue(DEBUG_LOG_PATH.startswith("/media/hdd/epgtoxml/"))


if __name__ == "__main__":
    unittest.main()
