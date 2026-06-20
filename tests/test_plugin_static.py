# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import os
import struct
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "Plugins", "Extensions", "EpgToXml", "plugin.py")
PLUGIN_ICON = os.path.join(ROOT, "Plugins", "Extensions", "EpgToXml", "EPGtoXML.png")
PLUGIN_ICON_SOURCE = os.path.join(ROOT, "Plugins", "Extensions", "EpgToXml", "EPGtoXML.svg")


def plugin_text():
    handle = open(PLUGIN, "rb")
    try:
        return handle.read().decode("utf-8")
    finally:
        handle.close()


class PluginStaticTests(unittest.TestCase):
    def test_selection_screen_does_not_shadow_screen_items_method(self):
        text = plugin_text()
        self.assertIn("self.selection_items", text)
        self.assertNotIn("self.items = list(items or [])", text)

    def test_display_value_is_callable_for_config_list(self):
        text = plugin_text()
        self.assertIn("def __call__(self, selected=False):", text)
        self.assertIn("self.enabled = True", text)

    def test_selection_cancel_returns_none_to_callback(self):
        text = plugin_text()
        self.assertIn('"cancel": self.cancel', text)
        self.assertIn("def cancel(self):", text)
        self.assertIn("self.close(None)", text)

    def test_editor_callbacks_accept_cancel_without_argument(self):
        text = plugin_text()
        self.assertIn("def source_selected(self, source_id=None):", text)
        self.assertIn("def channel_selected(self, selection=None):", text)
        self.assertIn("def service_selected(self, service=None):", text)

    def test_scheduler_is_registered_for_session_start(self):
        text = plugin_text()
        self.assertIn("class EpgToXmlScheduler", text)
        self.assertIn("WHERE_SESSIONSTART", text)
        self.assertIn("schedule_enabled", text)

    def test_import_screen_monitors_epgimport_result(self):
        text = plugin_text()
        self.assertIn("def monitor_epgimport(self):", text)
        self.assertIn("read_last_import_result", text)
        self.assertIn("EPG-Import fertig: ", text)

    def test_both_import_monitors_report_database_write_failures(self):
        text = plugin_text()
        self.assertEqual(text.count('verdict == "failed"'), 2)
        self.assertIn("EPG-Import fehlgeschlagen", text)
        self.assertIn("Fehler: nicht in DB", text)
        self.assertIn("Automatik Fehler: nicht in DB", text)

    def test_editor_has_two_daily_import_time_labels(self):
        text = plugin_text()
        self.assertIn("Tägliche Importzeit 1", text)
        self.assertIn("Tägliche Importzeit 2", text)
        self.assertNotIn("Importzeit 3", text)
        self.assertIn("Task löschen", text)

    def test_empty_task_list_is_allowed(self):
        text = plugin_text()
        self.assertIn("return TaskRepository().load()", text)
        self.assertNotIn("return repo.migrate_legacy_if_needed", text)

    def test_schedule_times_use_numeric_config(self):
        text = plugin_text()
        self.assertIn("self.schedule_time_1_cfg = ConfigInteger", text)
        self.assertIn("self.schedule_time_2_cfg = ConfigInteger", text)
        self.assertIn("self.schedule_slot_1_enabled_cfg = ConfigYesNo", text)
        self.assertIn("self.schedule_slot_2_enabled_cfg = ConfigYesNo", text)

    def test_schedule_slot_time_rows_are_conditional(self):
        text = plugin_text()
        self.assertIn("schedule_slot_1_enabled", text)
        self.assertIn("schedule_slot_2_enabled", text)
        self.assertIn("Uhrzeit 1", text)
        self.assertIn("Uhrzeit 2", text)

    def test_menu_opens_settings_instead_of_deleting_tasks(self):
        text = plugin_text()
        self.assertIn('"menu": self.open_settings', text)
        self.assertNotIn('"menu": self.delete_task', text)
        self.assertIn("class EpgToXmlSettings", text)
        self.assertIn("set_debug_enabled(self.debug_cfg.value)", text)
        self.assertIn("Debugmodus ist ein", text)
        self.assertIn("Debugmodus ist aus", text)

    def test_ui_text_uses_utf8_bytes_for_dreamos_widgets(self):
        text = plugin_text()
        self.assertIn("repair_mojibake(value)", text)
        self.assertIn('text.encode("utf-8")', text)
        self.assertNotIn('text.encode("latin-1", "replace")', text)

    def test_plugin_menu_descriptor_references_icon(self):
        text = plugin_text()
        self.assertIn('icon="EPGtoXML.png"', text)
        self.assertNotIn('icon="EPGtoXML.svg"', text)
        self.assertTrue(os.path.exists(PLUGIN_ICON))
        self.assertTrue(os.path.exists(PLUGIN_ICON_SOURCE))

    def test_plugin_icon_is_vti_compatible_png(self):
        handle = open(PLUGIN_ICON, "rb")
        try:
            header = handle.read(24)
        finally:
            handle.close()
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", header[16:24]), (100, 40))


if __name__ == "__main__":
    unittest.main()
