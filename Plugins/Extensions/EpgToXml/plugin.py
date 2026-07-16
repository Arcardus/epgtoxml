# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import json
import os
import time

from . import _
from .compat import ensure_text, repair_mojibake
from .debuglog import write_debug, write_exception
from .epgimport_adapter import probe_epgimport, read_last_import_result, start_epgimport
from .epgimport_files import source_description_for_task
from .paths import TASKS_PATH
from .providers import get_provider, get_providers
from .settings import is_debug_enabled, set_debug_enabled, get_import_routine, set_import_routine
from .tasks import (
    DEFAULT_SOURCE_CHANNEL_ID, DEFAULT_SOURCE_ID, DEFAULT_TASK_NAME,
    TaskRepository, clean_task_name, default_task, normalise_task,
    normalise_schedule_time, normalise_schedule_times,
)

try:
    from Plugins.Plugin import PluginDescriptor
    from Components.ActionMap import ActionMap
    from Components.ConfigList import ConfigListScreen
    from Components.Label import Label
    from Components.MenuList import MenuList
    from Components.config import (
        config, ConfigSubsection, ConfigText, ConfigInteger, ConfigYesNo,
        ConfigSelection, getConfigListEntry,
    )
    from Screens.Screen import Screen
    from Screens.MessageBox import MessageBox
    from enigma import eConsoleAppContainer, eServiceCenter, eTimer
except Exception:
    PluginDescriptor = None


if PluginDescriptor is not None:
    config.plugins.epgtoxml = ConfigSubsection()
    config.plugins.epgtoxml.enabled = ConfigYesNo(default=True)
    config.plugins.epgtoxml.service_ref = ConfigText(default="", fixed_size=False)
    config.plugins.epgtoxml.days = ConfigInteger(default=3, limits=(1, 14))

    # Minimal-Subsection, die die eingebettete Import-Engine (epgimport_engine)
    # auf dpkg-/DreamOS-Boxen erwartet (epgdat_importer liest clear_oldepg).
    if not hasattr(config.plugins, "epgimport"):
        config.plugins.epgimport = ConfigSubsection()
    if not hasattr(config.plugins.epgimport, "clear_oldepg"):
        config.plugins.epgimport.clear_oldepg = ConfigYesNo(default=False)


def _t(value):
    text = repair_mojibake(value)
    try:
        unicode
    except NameError:
        return text
    try:
        return text.encode("utf-8")
    except Exception:
        return str(value)


def _hhmm_to_int(value, fallback="00:00"):
    text = ensure_text(value or fallback).strip()
    if ":" in text:
        parts = text.split(":")
        try:
            return int(parts[0]) * 100 + int(parts[1])
        except Exception:
            return 0
    try:
        return int(text)
    except Exception:
        return 0


def _time_cfg_text(entry, fallback="00:00"):
    try:
        value = int(entry.value)
    except Exception:
        try:
            value = int(entry.getText())
        except Exception:
            return fallback
    hour = value // 100
    minute = value % 100
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return fallback
    return "%02d:%02d" % (hour, minute)


def _hhmm_minutes(value):
    text = ensure_text(value)
    try:
        parts = text.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return -1


def _command_text(value):
    return _t(value)


def _runner_command(task_id):
    runner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner_cli.py")
    return "python %s --task-id %s --tasks-path %s" % (
        runner_path, task_id, TASKS_PATH)


class DisplayValue(object):
    def __init__(self, text=""):
        self.value = text
        self.enabled = True

    def getText(self):
        return _t(self.value)

    def __call__(self, selected=False):
        return self.getText()

    def handleKey(self, key):
        return

    def onSelect(self, session):
        return

    def onDeselect(self, session):
        return

    def isChanged(self):
        return False

    def save(self):
        return

    def cancel(self):
        return

    def load(self):
        return


def _source_text(task):
    try:
        provider_name = get_provider(task.get("source_id")).name
    except Exception:
        provider_name = "EPG-Quelle"
    channel_name = task.get("source_channel_name") or task.get("source_channel_id") or ""
    return provider_name + ": " + ensure_text(channel_name)


def _target_text(task):
    return task.get("target_service_name") or task.get("target_service_ref") or _("Noch kein Zielsender gewählt")


def _epgimport_status_text():
    try:
        return probe_epgimport().message
    except Exception as exc:
        write_exception("EPG-Import status failed", exc)
        return _("EPG-Import: Statusfehler ") + ensure_text(exc)


def _update_task_status(task_id, status):
    try:
        repo = TaskRepository()
        tasks = repo.load()
        changed = False
        for index, task in enumerate(tasks):
            if task.get("id") == task_id:
                task["last_status"] = ensure_text(status)
                tasks[index] = task
                changed = True
                break
        if changed:
            repo.save(tasks)
    except Exception as exc:
        write_exception("task status update failed", exc)


def _unpack_import_result(result):
    """Entpackt read_last_import_result() in (stamp, count, verdict).

    Toleriert das alte 2-Tupel (ohne Verdikt) -> verdict "unverified", damit
    ein Mischbetrieb (alter Adapter-Zustand) nicht crasht.
    """
    if result is None:
        return (0, 0, "unverified")
    stamp = result[0]
    count = result[1] if len(result) > 1 else 0
    verdict = result[2] if len(result) > 2 else "unverified"
    return (stamp, count, verdict)


_plugin_busy = False


def _set_plugin_busy(value):
    global _plugin_busy
    _plugin_busy = bool(value)
    write_debug("plugin busy=" + str(_plugin_busy), "plugin")


def _is_plugin_busy():
    return bool(_plugin_busy)


def _legacy_tasks():
    return TaskRepository().load()


def _task_line(task):
    target = task.get("target_service_name") or task.get("target_service_ref") or "kein Zielsender"
    status = task.get("last_status") or ""
    enabled = "an" if task.get("enabled") else "aus"
    line = "%s [%s] -> %s  %s" % (
        clean_task_name(task.get("name"), DEFAULT_TASK_NAME),
        ensure_text(enabled),
        ensure_text(target),
        ensure_text(status),
    )
    return _t(line)


class EpgToXmlTaskList(Screen):
    skin = """
    <screen name="EpgToXmlTaskList" position="center,center" size="760,500" title="EpgToXml Tasks">
        <widget name="tasks" position="10,10" size="740,330" scrollbarMode="showOnDemand" />
        <widget name="hint" position="10,350" size="740,60" font="Regular;20" />
        <ePixmap pixmap="skin_default/buttons/red.png" position="10,440" size="140,40" alphatest="on" />
        <ePixmap pixmap="skin_default/buttons/green.png" position="160,440" size="140,40" alphatest="on" />
        <ePixmap pixmap="skin_default/buttons/yellow.png" position="310,440" size="140,40" alphatest="on" />
        <ePixmap pixmap="skin_default/buttons/blue.png" position="460,440" size="140,40" alphatest="on" />
        <widget name="key_red" position="10,440" size="140,40" font="Regular;18"
            halign="center" valign="center" foregroundColor="#ffffff"
            backgroundColor="#9f1313" transparent="0" zPosition="2" />
        <widget name="key_green" position="160,440" size="140,40" font="Regular;18"
            halign="center" valign="center" foregroundColor="#ffffff"
            backgroundColor="#1f771f" transparent="0" zPosition="2" />
        <widget name="key_yellow" position="310,440" size="140,40" font="Regular;18"
            halign="center" valign="center" foregroundColor="#ffffff"
            backgroundColor="#9f9f13" transparent="0" zPosition="2" />
        <widget name="key_blue" position="460,440" size="140,40" font="Regular;18"
            halign="center" valign="center" foregroundColor="#ffffff"
            backgroundColor="#1f3f9f" transparent="0" zPosition="2" />
    </screen>
    """

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        self.repo = TaskRepository()
        self.tasks = []
        self["tasks"] = MenuList([])
        self["hint"] = Label("")
        self["key_red"] = Label(_t(_("Schließen")))
        self["key_green"] = Label(_t(_("Neu")))
        self["key_yellow"] = Label(_t(_("Bearbeiten")))
        self["key_blue"] = Label(_t(_("Import")))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "MenuActions"], {
            "cancel": self.close,
            "red": self.close,
            "green": self.add_task,
            "yellow": self.edit_task,
            "blue": self.run_task,
            "ok": self.edit_task,
            "menu": self.open_settings,
        }, -2)
        write_debug("main screen opened", "plugin")
        self.reload()

    def debug_hint(self):
        if is_debug_enabled():
            return "Debugmodus ist ein"
        return "Debugmodus ist aus"

    def reload(self, *args):
        try:
            self.tasks = _legacy_tasks()
            normalised = [normalise_task(task) for task in self.tasks]
            if normalised != self.tasks:
                self.repo.save(normalised)
                self.tasks = normalised
        except Exception as exc:
            write_exception("task list reload failed", exc)
            self.tasks = []
            self["hint"].setText(_t(_("Tasks konnten nicht geladen werden: ") + ensure_text(exc)))
        self["tasks"].setList([_task_line(task) for task in self.tasks])
        epg_status = _epgimport_status_text()
        if self.tasks:
            hint = epg_status + "\n" + self.debug_hint() + " · Blau startet den manuellen Import."
        else:
            hint = epg_status + "\n" + self.debug_hint() + " · Noch keine Tasks vorhanden. Grün legt einen Task an."
        self["hint"].setText(_t(hint))
        write_debug("main screen reload tasks=" + str(len(self.tasks)), "plugin")

    def selected_task(self):
        if len(self.tasks) == 1:
            return self.tasks[0]
        try:
            index = self["tasks"].getSelectedIndex()
        except Exception:
            try:
                index = self["tasks"].getSelectionIndex()
            except Exception:
                index = 0
        if index is None or index < 0 or index >= len(self.tasks):
            return None
        return self.tasks[index]

    def add_task(self):
        write_debug("add task requested", "plugin")
        self.session.openWithCallback(self.reload, EpgToXmlTaskEditor, default_task())

    def edit_task(self):
        task = self.selected_task()
        if task:
            try:
                write_debug("edit task requested: " + ensure_text(task.get("id")), "plugin")
                self.session.openWithCallback(self.reload, EpgToXmlTaskEditor, task)
            except Exception as exc:
                write_exception("open task editor failed", exc)
                self.session.open(MessageBox, _t(_("Task-Editor konnte nicht geöffnet werden: ") + ensure_text(exc)),
                                  MessageBox.TYPE_ERROR, timeout=15)

    def run_task(self):
        task = self.selected_task()
        if task:
            try:
                write_debug("manual import requested: " + ensure_text(task.get("id")), "plugin")
                self.session.openWithCallback(self.reload, EpgToXmlImportScreen, _t(task.get("id")))
            except Exception as exc:
                write_exception("open import screen failed", exc)
                self.session.open(MessageBox, _t(_("Import-Fenster konnte nicht geöffnet werden: ") + ensure_text(exc)),
                                  MessageBox.TYPE_ERROR, timeout=15)

    def open_settings(self):
        write_debug("settings opened", "plugin")
        self.session.openWithCallback(self.reload, EpgToXmlSettings)


class EpgToXmlSettings(Screen, ConfigListScreen):
    skin = """
    <screen name="EpgToXmlSettings" position="center,center" size="720,460" title="EpgToXml Einstellungen">
        <widget name="config" position="10,10" size="700,380" scrollbarMode="showOnDemand" />
        <ePixmap pixmap="skin_default/buttons/red.png" position="10,400" size="140,40" alphatest="on" />
        <ePixmap pixmap="skin_default/buttons/green.png" position="160,400" size="140,40" alphatest="on" />
        <widget name="key_red" position="10,400" size="140,40" font="Regular;18"
            halign="center" valign="center" foregroundColor="#ffffff"
            backgroundColor="#9f1313" transparent="0" zPosition="2" />
        <widget name="key_green" position="160,400" size="140,40" font="Regular;18"
            halign="center" valign="center" foregroundColor="#ffffff"
            backgroundColor="#1f771f" transparent="0" zPosition="2" />
    </screen>
    """

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        self.debug_cfg = ConfigYesNo(default=is_debug_enabled())
        self.routine_cfg = ConfigSelection(
            choices=[
                ("auto", _t(_("Standard (A dann B)"))),
                ("a",    _t(_("Routine A (importEvents)"))),
                ("b",    _t(_("Routine B (epgdat)"))),
            ],
            default=get_import_routine(),
        )
        self.list = []
        ConfigListScreen.__init__(self, self.list, session=session)
        self["key_red"] = Label(_t(_("Abbrechen")))
        self["key_green"] = Label(_t(_("Speichern")))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "SetupActions"], {
            "cancel": self.close,
            "red": self.close,
            "green": self.save,
            "ok": self.save,
            "left": self.keyLeft,
            "right": self.keyRight,
        }, -2)
        self.build_list()

    def build_list(self):
        self.list = [
            getConfigListEntry(_t(_("Debug-Logging")), self.debug_cfg),
            getConfigListEntry(_t(_("Import-Routine")), self.routine_cfg),
        ]
        self["config"].list = self.list
        self["config"].l.setList(self.list)

    def save(self):
        set_debug_enabled(self.debug_cfg.value)
        write_debug("debug set enabled=" + str(self.debug_cfg.value), "settings", force=True)
        set_import_routine(self.routine_cfg.value)
        write_debug("import_routine set=" + str(self.routine_cfg.value), "settings", force=True)
        self.close()


class EpgToXmlSimpleSelection(Screen):
    skin = """
    <screen name="EpgToXmlSimpleSelection" position="center,center" size="640,460" title="EpgToXml Auswahl">
        <widget name="list" position="10,10" size="620,380" scrollbarMode="showOnDemand" />
        <widget name="hint" position="10,400" size="620,30" font="Regular;18" />
    </screen>
    """

    def __init__(self, session, title, items):
        Screen.__init__(self, session)
        self.session = session
        self.selection_items = list(items or [])
        try:
            self.setTitle(_t(title))
        except Exception:
            pass
        self["list"] = MenuList([_t(item[0]) for item in self.selection_items])
        self["hint"] = Label(_t(_("OK wählt aus, EXIT bricht ab.")))
        self["actions"] = ActionMap(["OkCancelActions"], {
            "ok": self.ok,
            "cancel": self.cancel,
        }, -2)

    def cancel(self):
        self.close(None)

    def ok(self):
        try:
            index = self["list"].getSelectedIndex()
        except Exception:
            try:
                index = self["list"].getSelectionIndex()
            except Exception:
                index = 0
        if index is None or index < 0 or index >= len(self.selection_items):
            self.close(None)
            return
        self.close(self.selection_items[index][1])


class EpgToXmlTaskEditor(Screen, ConfigListScreen):
    skin = """
    <screen name="EpgToXmlTaskEditor" position="center,center" size="720,500" title="EpgToXml Task">
        <widget name="config" position="10,10" size="700,300" scrollbarMode="showOnDemand" />
        <widget name="target" position="10,320" size="700,70" font="Regular;20" />
        <ePixmap pixmap="skin_default/buttons/red.png" position="10,440" size="140,40" alphatest="on" />
        <ePixmap pixmap="skin_default/buttons/green.png" position="160,440" size="140,40" alphatest="on" />
        <ePixmap pixmap="skin_default/buttons/yellow.png" position="310,440" size="180,40" alphatest="on" />
        <widget name="key_red" position="10,440" size="140,40" font="Regular;18"
            halign="center" valign="center" foregroundColor="#ffffff"
            backgroundColor="#9f1313" transparent="0" zPosition="2" />
        <widget name="key_green" position="160,440" size="140,40" font="Regular;18"
            halign="center" valign="center" foregroundColor="#ffffff"
            backgroundColor="#1f771f" transparent="0" zPosition="2" />
        <widget name="key_yellow" position="310,440" size="180,40" font="Regular;18"
            halign="center" valign="center" foregroundColor="#ffffff"
            backgroundColor="#9f9f13" transparent="0" zPosition="2" />
    </screen>
    """

    def __init__(self, session, task):
        Screen.__init__(self, session)
        self.session = session
        self.repo = TaskRepository()
        self.task = normalise_task(task)
        write_debug("editor open task=" + ensure_text(self.task.get("id")), "plugin")
        self.enabled_cfg = ConfigYesNo(default=self.task.get("enabled"))
        self.days_cfg = ConfigInteger(default=self.task.get("days"), limits=(1, 14))
        self.import_cfg = ConfigYesNo(default=self.task.get("import_after_generate"))
        self.schedule_slot_1_enabled_cfg = ConfigYesNo(default=self.task.get("schedule_slot_1_enabled"))
        self.schedule_time_1_cfg = ConfigInteger(
            default=_hhmm_to_int(
                self.task.get("schedule_slot_1_time") or "00:00",
                "00:00",
            ),
            limits=(0, 2359),
        )
        self.schedule_slot_2_enabled_cfg = ConfigYesNo(default=self.task.get("schedule_slot_2_enabled"))
        self.schedule_time_2_cfg = ConfigInteger(
            default=_hhmm_to_int(
                self.task.get("schedule_slot_2_time") or "00:00",
                "00:00",
            ),
            limits=(0, 2359),
        )
        self.list = []
        self.row_keys = []
        ConfigListScreen.__init__(self, self.list, session=session)
        self["target"] = Label("")
        self["key_red"] = Label(_t(_("Abbrechen")))
        self["key_green"] = Label(_t(_("Speichern")))
        self["key_yellow"] = Label(_t(_("Zielsender")))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "SetupActions"], {
            "cancel": self.close,
            "red": self.close,
            "green": self.save,
            "ok": self.ok_pressed,
            "yellow": self.pick_service,
            "left": self.key_left,
            "right": self.key_right,
        }, -2)
        self.build_list()

    def build_list(self):
        self.row_keys = []
        self.list = []
        self._append("enabled", _("Aktiv"), self.enabled_cfg)
        self._append("source", _("Quelle"), DisplayValue(_source_text(self.task)))
        self._append("target", _("Zielsender"), DisplayValue(_target_text(self.task)))
        self._append("days", _("Tage laden"), self.days_cfg)
        self._append("import", _("EPG danach importieren"), self.import_cfg)
        self._append("schedule_slot_1_enabled", _("Tägliche Importzeit 1"), self.schedule_slot_1_enabled_cfg)
        if self.schedule_slot_1_enabled_cfg.value:
            self._append("schedule_time_1", _("Uhrzeit 1"), self.schedule_time_1_cfg)
        self._append("schedule_slot_2_enabled", _("Tägliche Importzeit 2"), self.schedule_slot_2_enabled_cfg)
        if self.schedule_slot_2_enabled_cfg.value:
            self._append("schedule_time_2", _("Uhrzeit 2"), self.schedule_time_2_cfg)
        self._append("delete", _("Task löschen"), DisplayValue(_("OK drücken")))
        self["config"].list = self.list
        self["config"].l.setList(self.list)
        target_text = (
            _("Quelle: ") + _source_text(self.task)
            + "\n"
            + _("Zielsender: ") + _target_text(self.task)
        )
        self["target"].setText(_t(target_text))

    def _append(self, key, label, entry):
        self.row_keys.append(key)
        self.list.append(getConfigListEntry(_t(label), entry))

    def current_key(self):
        try:
            index = self["config"].getCurrentIndex()
        except Exception:
            try:
                index = self["config"].getSelectedIndex()
            except Exception:
                index = 0
        if index is None or index < 0 or index >= len(self.row_keys):
            return ""
        return self.row_keys[index]

    def _is_slot_key(self, key):
        return key in ("schedule_slot_1_enabled", "schedule_slot_2_enabled")

    def ok_pressed(self):
        key = self.current_key()
        if key == "source":
            self.pick_source()
        elif key == "target":
            self.pick_service()
        elif key == "delete":
            self.confirm_delete()
        elif key == "schedule_slot_1_enabled":
            self.schedule_slot_1_enabled_cfg.value = not self.schedule_slot_1_enabled_cfg.value
            write_debug("slot 1 toggled=" + str(self.schedule_slot_1_enabled_cfg.value), "plugin")
            self.build_list()
        elif key == "schedule_slot_2_enabled":
            self.schedule_slot_2_enabled_cfg.value = not self.schedule_slot_2_enabled_cfg.value
            write_debug("slot 2 toggled=" + str(self.schedule_slot_2_enabled_cfg.value), "plugin")
            self.build_list()
        else:
            self.save()

    def key_left(self):
        key = self.current_key()
        try:
            ConfigListScreen.keyLeft(self)
        except Exception:
            pass
        if self._is_slot_key(key):
            self.build_list()

    def key_right(self):
        key = self.current_key()
        try:
            ConfigListScreen.keyRight(self)
        except Exception:
            pass
        if self._is_slot_key(key):
            self.build_list()

    def pick_source(self):
        write_debug("source picker opened", "plugin")
        items = [(provider.name, provider.id) for provider in get_providers()]
        self.session.openWithCallback(
            self.source_selected,
            EpgToXmlSimpleSelection,
            _t(_("Quelle wählen")),
            items,
        )

    def source_selected(self, source_id=None):
        if source_id is None:
            write_debug("source picker cancelled", "plugin")
            return
        self.pick_channel(source_id)

    def pick_channel(self, source_id):
        try:
            provider = get_provider(source_id)
            channels = provider.discover_channels()
        except Exception as exc:
            write_exception("channel picker failed", exc)
            self.session.open(MessageBox, _t(_("Senderliste konnte nicht geladen werden: ") + ensure_text(exc)),
                              MessageBox.TYPE_ERROR, timeout=15)
            return
        items = []
        for channel in channels:
            items.append((ensure_text(channel.get("name")), (source_id, channel)))
        write_debug("channel picker loaded " + str(len(items)) + " channels for " + ensure_text(source_id), "plugin")
        self.session.openWithCallback(
            self.channel_selected,
            EpgToXmlSimpleSelection,
            _t(_("Sender wählen")),
            items,
        )

    def channel_selected(self, selection=None):
        if not selection:
            write_debug("channel picker cancelled", "plugin")
            return
        source_id, channel = selection
        variants = channel.get("variants") or []
        if variants:
            items = [(ensure_text(variant.get("name")), (source_id, variant)) for variant in variants]
            write_debug("region picker opened for " + ensure_text(channel.get("name")), "plugin")
            self.session.openWithCallback(
                self.channel_selected,
                EpgToXmlSimpleSelection,
                _t(_("Region wählen")),
                items,
            )
            return
        self._apply_channel_selection(source_id, channel)

    def _apply_channel_selection(self, source_id, channel):
        self.task["source_id"] = ensure_text(source_id)
        self.task["source_channel_id"] = ensure_text(channel.get("id") or DEFAULT_SOURCE_CHANNEL_ID)
        self.task["source_channel_name"] = ensure_text(channel.get("name") or "DFB.TV")
        self.task["source_channel_logo"] = ensure_text(channel.get("logo") or "")
        for key, value in channel.items():
            if key in ("id", "name", "logo", "variants"):
                continue
            self.task[key] = value
        self.task["name"] = clean_task_name(ensure_text(self.task.get("source_channel_name")), DEFAULT_TASK_NAME)
        write_debug("channel selected: " + ensure_text(self.task.get("source_channel_name")), "plugin")
        self.build_list()

    def pick_service(self):
        try:
            from Screens.ChannelSelection import SimpleChannelSelection
            self.session.openWithCallback(self.service_selected, SimpleChannelSelection, _t(_("Zielsender wählen")))
        except Exception as exc:
            write_exception("service picker failed", exc)
            self.session.open(MessageBox, _t(_("Service-Auswahl nicht verfügbar: ") + ensure_text(exc)),
                              MessageBox.TYPE_ERROR, timeout=10)

    def service_selected(self, service=None):
        if service is None:
            write_debug("service picker cancelled", "plugin")
            return
        try:
            ref = service.toString()
        except Exception:
            ref = str(service)
        name = ""
        try:
            info = eServiceCenter.getInstance().info(service)
            if info:
                name = info.getName(service)
        except Exception:
            pass
        self.task["target_service_ref"] = ref
        self.task["target_service_name"] = name or ref
        write_debug("service selected: " + ensure_text(self.task.get("target_service_name")), "plugin")
        self.build_list()

    def confirm_delete(self):
        self.session.openWithCallback(self.delete_confirmed, MessageBox,
                                      _t(_("Task wirklich löschen?")),
                                      MessageBox.TYPE_YESNO, timeout=10)

    def delete_confirmed(self, confirmed=False):
        if not confirmed:
            return
        write_debug("editor delete task: " + ensure_text(self.task.get("id")), "plugin")
        self.repo.delete(self.task.get("id"))
        self.close(True)

    def save(self):
        self.task["name"] = clean_task_name(self.task.get("name"), DEFAULT_TASK_NAME)
        self.task["enabled"] = self.enabled_cfg.value
        self.task["source_id"] = ensure_text(self.task.get("source_id") or DEFAULT_SOURCE_ID)
        self.task["days"] = self.days_cfg.value
        self.task["import_after_generate"] = self.import_cfg.value
        self.task["schedule_slot_1_enabled"] = self.schedule_slot_1_enabled_cfg.value
        self.task["schedule_slot_1_time"] = normalise_schedule_time(_time_cfg_text(self.schedule_time_1_cfg, "00:00"))
        self.task["schedule_slot_2_enabled"] = self.schedule_slot_2_enabled_cfg.value
        self.task["schedule_slot_2_time"] = normalise_schedule_time(_time_cfg_text(self.schedule_time_2_cfg, "00:00"))
        self.task["schedule_times"] = []
        if self.task["schedule_slot_1_enabled"]:
            self.task["schedule_times"].append(self.task["schedule_slot_1_time"])
        if (
            self.task["schedule_slot_2_enabled"]
            and self.task["schedule_slot_2_time"] not in self.task["schedule_times"]
        ):
            self.task["schedule_times"].append(self.task["schedule_slot_2_time"])
        self.task["schedule_enabled"] = bool(self.task["schedule_times"])
        saved = self.repo.upsert(self.task)
        write_debug(
            "editor save task=%s schedule=%s"
            % (
                ensure_text(saved.get("id")),
                ", ".join(saved.get("schedule_times") or []),
            ),
            "plugin",
        )
        self.close(True)


class EpgToXmlImportScreen(Screen):
    skin = """
    <screen name="EpgToXmlImportScreen" position="center,center" size="760,560" title="EpgToXml Import">
        <widget name="status" position="10,10" size="740,40" font="Regular;22" />
        <widget name="log" position="10,60" size="740,420" font="Regular;18" />
        <ePixmap pixmap="skin_default/buttons/red.png" position="10,510" size="180,40" alphatest="on" />
        <widget name="key_red" position="10,510" size="180,40" font="Regular;18"
            halign="center" valign="center" foregroundColor="#ffffff"
            backgroundColor="#9f1313" transparent="0" zPosition="2" />
    </screen>
    """

    def __init__(self, session, task_id):
        Screen.__init__(self, session)
        self.session = session
        self.task_id = task_id
        self.container = None
        self.buffer = ""
        self.lines = []
        self.running = False
        self.finished = False
        self.epg_monitor_started_at = None
        self.epg_monitor_deadline = 0
        self.epg_monitor_last_log = 0
        self["status"] = Label(_t(_("Import startet...")))
        self["log"] = Label("")
        self["key_red"] = Label(_t(_("Abbrechen")))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "cancel": self.cancel_or_close,
            "red": self.cancel_or_close,
        }, -2)
        self.timeout_timer = eTimer()
        try:
            self.timeout_timer.callback.append(self.timeout)
        except Exception:
            self.timeout_conn = self.timeout_timer.timeout.connect(self.timeout)
        self.import_monitor_timer = eTimer()
        try:
            self.import_monitor_timer.callback.append(self.monitor_epgimport)
        except Exception:
            self.import_monitor_conn = self.import_monitor_timer.timeout.connect(self.monitor_epgimport)
        self.onLayoutFinish.append(self.start)

    def append_log(self, text):
        write_debug("manual: " + ensure_text(text), "import")
        self.lines.append(ensure_text(text))
        if len(self.lines) > 18:
            self.lines = self.lines[-18:]
        self["log"].setText(_t("\n".join(self.lines)))

    def start(self):
        if self.running:
            return
        write_debug("manual import screen start task=" + ensure_text(self.task_id), "import")
        self.container = eConsoleAppContainer()
        try:
            self.container.dataAvail.append(self.data_avail)
            self.container.appClosed.append(self.app_closed)
        except Exception:
            self.data_conn = self.container.dataAvail.connect(self.data_avail)
            self.closed_conn = self.container.appClosed.connect(self.app_closed)
        command = _runner_command(self.task_id)
        command = _command_text(command)
        self.running = True
        _set_plugin_busy(True)
        self.timeout_timer.startLongTimer(180)
        self.append_log(command)
        result = self.container.execute(command)
        if result:
            self.running = False
            _set_plugin_busy(False)
            self["status"].setText(_t(_("Import konnte nicht gestartet werden")))
            self.append_log(_("Helper-Prozess konnte nicht gestartet werden."))

    def parse_line(self, line):
        if not line.startswith("EPGTOXML "):
            self.append_log(line)
            return
        try:
            event = json.loads(line[len("EPGTOXML "):])
        except Exception:
            self.append_log(line)
            return
        kind = event.get("kind")
        message = event.get("message", "")
        if kind == "step":
            self["status"].setText(_t(message))
        elif kind == "done":
            self.finished = True
            self["status"].setText(_t(_("Fertig")))
        elif kind == "error":
            self.finished = True
            self["status"].setText(_t(_("Fehler")))
        self.append_log(message)

    def data_avail(self, data):
        try:
            if not isinstance(data, str):
                data = data.decode("utf-8", "replace")
        except Exception:
            data = str(data)
        self.buffer += data
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.strip()
            if line:
                self.parse_line(line)

    def app_closed(self, retval):
        write_debug("manual helper closed retval=" + str(retval), "import")
        self.running = False
        try:
            self.timeout_timer.stop()
        except Exception:
            pass
        if self.buffer.strip():
            self.parse_line(self.buffer.strip())
            self.buffer = ""
        if retval == 0:
            if not self.finished:
                self["status"].setText(_t(_("Fertig")))
            self.start_epgimport()
            self["key_red"].setText(_t(_("Schließen")))
        else:
            if not self.finished:
                self["status"].setText(_t(_("Fehler")))
                self.append_log(_("Import beendet mit Code ") + str(retval))
            self["key_red"].setText(_t(_("Schließen")))
            _set_plugin_busy(False)

    def start_epgimport(self):
        try:
            task = TaskRepository().get(self.task_id)
        except Exception as exc:
            write_exception("manual EPG-Import task load failed", exc)
            self["status"].setText(_t(_("Fehler")))
            self.append_log(_("Task für EPG-Import nicht gefunden: ") + ensure_text(exc))
            _set_plugin_busy(False)
            return
        if not task.get("import_after_generate"):
            self.append_log(_("EPG-Import für diesen Task deaktiviert."))
            _set_plugin_busy(False)
            return
        self["status"].setText(_t(_("EPG-Import starten")))
        description = source_description_for_task(task)
        self.append_log(_("EPG-Import-Quelle laden: ") + description)
        result = start_epgimport(self.session, self.append_log, source_descriptions=[description])
        if result.started:
            self["status"].setText(_t(_("EPG-Import gestartet")))
            if result.source_descriptions:
                self.append_log(_("EPG-Import-Quelle gefunden: ") + ", ".join(result.source_descriptions))
            self.epg_monitor_started_at = result.monitor_started_at or time.time()
            self.epg_monitor_deadline = time.time() + 180
            self.epg_monitor_last_log = 0
            self.start_import_monitor()
        else:
            self["status"].setText(_t(_("Fehler")))
            _update_task_status(self.task_id, "EPG-Import Fehler: " + result.message)
            _set_plugin_busy(False)
        self.append_log(result.message)

    def start_import_monitor(self):
        try:
            self.import_monitor_timer.start(1000, False)
        except Exception:
            self.import_monitor_timer.startLongTimer(1)

    def stop_import_monitor(self):
        try:
            self.import_monitor_timer.stop()
        except Exception:
            pass

    def monitor_epgimport(self):
        if not self.epg_monitor_started_at:
            return
        result = read_last_import_result()
        if result is not None:
            stamp, count, verdict = _unpack_import_result(result)
            write_debug(
                "monitor poll result_stamp=%s started=%s count=%s verdict=%s"
                % (stamp, self.epg_monitor_started_at, count, verdict),
                "import",
            )
            if stamp >= self.epg_monitor_started_at - 1:
                self.stop_import_monitor()
                if verdict == "failed":
                    message = ("EPG-Import fehlgeschlagen: 0 Events in epg.db "
                               "geschrieben (geparst: " + str(count) + "). "
                               "Ursache: beschädigte oder sehr große epg.db, "
                               "oder Events außerhalb des EPG-Zeitfensters.")
                    self["status"].setText(_t(_("EPG-Import fehlgeschlagen")))
                    self.append_log(message)
                    _update_task_status(self.task_id, "Fehler: nicht in DB")
                elif count > 0:
                    message = "EPG-Import fertig: " + str(count) + " Events importiert"
                    self["status"].setText(_t(_("EPG-Import fertig")))
                    self.append_log(message)
                    _update_task_status(self.task_id, "OK: " + str(count) + " Events")
                else:
                    message = "EPG-Import fertig: 0 Events importiert"
                    self["status"].setText(_t(_("EPG-Import Warnung")))
                    self.append_log(message)
                    _update_task_status(self.task_id, "Warnung: 0 Events")
                _set_plugin_busy(False)
                return

        now = time.time()
        try:
            probe = probe_epgimport()
        except Exception as exc:
            write_exception("manual EPG-Import monitor probe failed", exc)
            probe = None
        if probe is not None and probe.running:
            if now - self.epg_monitor_last_log >= 5:
                self.append_log(_("EPG-Import läuft..."))
                self.epg_monitor_last_log = now
            self.start_import_monitor()
            return
        if now >= self.epg_monitor_deadline:
            self.stop_import_monitor()
            self["status"].setText(_t(_("EPG-Import Timeout")))
            self.append_log(_("EPG-Import-Ergebnis nach 180 Sekunden nicht erkannt."))
            _update_task_status(self.task_id, "EPG-Import Timeout")
            _set_plugin_busy(False)
            return
        self.start_import_monitor()

    def timeout(self):
        if not self.running:
            return
        self.append_log(_("Timeout erreicht. Import wird beendet."))
        try:
            self.container.kill()
        except Exception:
            pass
        self.running = False
        self.finished = True
        self.stop_import_monitor()
        _set_plugin_busy(False)
        self["status"].setText(_t(_("Timeout")))
        self["key_red"].setText(_t(_("Schließen")))

    def cancel_or_close(self):
        if self.running:
            self.append_log(_("Import abgebrochen."))
            try:
                self.container.kill()
            except Exception:
                pass
            self.running = False
            self.stop_import_monitor()
            _set_plugin_busy(False)
            self["status"].setText(_t(_("Abgebrochen")))
            self["key_red"].setText(_t(_("Schließen")))
            return
        self.stop_import_monitor()
        _set_plugin_busy(False)
        self.close(True)


class EpgToXmlScheduler(object):
    def __init__(self, session):
        self.session = session
        self.timer = eTimer()
        self.container = None
        self.current_task = None
        self.current_run_key = ""
        self.current_started_at = 0
        self.buffer = ""
        self.epg_monitor_started_at = None
        self.epg_monitor_deadline = 0
        try:
            self.timer.callback.append(self.tick)
        except Exception:
            self.timer_conn = self.timer.timeout.connect(self.tick)

    def start(self):
        write_debug("scheduler start", "scheduler")
        self.start_timer(30)

    def start_timer(self, seconds):
        try:
            self.timer.startLongTimer(seconds)
        except Exception:
            self.timer.start(seconds * 1000, True)

    def tick(self):
        write_debug("scheduler tick", "scheduler")
        if self.epg_monitor_started_at:
            if not self.monitor_epgimport():
                self.start_timer(1)
            return
        if self.container is not None and self.current_started_at:
            if time.time() - self.current_started_at > 180:
                write_debug("scheduler helper timeout", "scheduler")
                try:
                    self.container.kill()
                except Exception:
                    pass
                if self.current_task is not None:
                    self.mark_task(self.current_task.get("id"), self.current_run_key,
                                   "Automatik Timeout")
                self.finish()
                return
        if self.container is not None or _is_plugin_busy():
            write_debug("scheduler skip: plugin busy", "scheduler")
            self.start_timer(5)
            return
        try:
            probe = probe_epgimport()
            if probe.running:
                write_debug("scheduler skip: EPG-Import running", "scheduler")
                self.start_timer(60)
                return
        except Exception as exc:
            write_exception("scheduler probe failed", exc)
        due = self.find_due_task()
        if due is None:
            write_debug("scheduler no due task", "scheduler")
            self.start_timer(60)
            return
        self.start_task(due)

    def find_due_task(self):
        now_hhmm = time.strftime("%H:%M")
        now_minutes = _hhmm_minutes(now_hhmm)
        today = time.strftime("%Y-%m-%d")
        try:
            tasks = TaskRepository().load()
        except Exception as exc:
            write_exception("scheduler load tasks failed", exc)
            return None
        for task in tasks:
            if not task.get("enabled"):
                write_debug("scheduler skip disabled task=" + ensure_text(task.get("id")), "scheduler")
                continue
            if not task.get("schedule_enabled"):
                write_debug("scheduler skip no schedule task=" + ensure_text(task.get("id")), "scheduler")
                continue
            times = normalise_schedule_times(task.get("schedule_times"))
            for scheduled in times:
                scheduled_minutes = _hhmm_minutes(scheduled)
                if scheduled_minutes < 0:
                    continue
                delay = now_minutes - scheduled_minutes
                if delay < 0 or delay > 30:
                    continue
                run_key = today + " " + scheduled
                if task.get("last_scheduled_run") == run_key:
                    write_debug("scheduler skip already ran " + run_key, "scheduler")
                    continue
                write_debug("scheduler due task=%s run=%s" % (ensure_text(task.get("id")), run_key), "scheduler")
                return (task, run_key)
        return None

    def mark_task(self, task_id, run_key, status):
        try:
            repo = TaskRepository()
            tasks = repo.load()
            for index, task in enumerate(tasks):
                if task.get("id") == task_id:
                    task["last_scheduled_run"] = run_key
                    task["last_status"] = ensure_text(status)
                    tasks[index] = task
                    break
            repo.save(tasks)
            write_debug("scheduler mark task=%s status=%s" % (ensure_text(task_id), ensure_text(status)), "scheduler")
        except Exception as exc:
            write_exception("scheduler mark task failed", exc)

    def start_task(self, due):
        task, run_key = due
        self.current_task = task
        self.current_run_key = run_key
        self.buffer = ""
        self.mark_task(task.get("id"), run_key, "Automatik gestartet: " + run_key)
        _set_plugin_busy(True)
        self.current_started_at = time.time()
        self.container = eConsoleAppContainer()
        try:
            self.container.dataAvail.append(self.data_avail)
            self.container.appClosed.append(self.app_closed)
        except Exception:
            self.data_conn = self.container.dataAvail.connect(self.data_avail)
            self.closed_conn = self.container.appClosed.connect(self.app_closed)
        command = _runner_command(_t(task.get("id")))
        write_debug("scheduler execute: " + ensure_text(command), "scheduler")
        result = self.container.execute(_command_text(command))
        if result:
            self.mark_task(task.get("id"), run_key, "Automatik Fehler: Helper nicht gestartet")
            self.finish()

    def data_avail(self, data):
        try:
            if not isinstance(data, str):
                data = data.decode("utf-8", "replace")
        except Exception:
            data = str(data)
        self.buffer += data
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.strip()
            if line:
                write_debug("scheduler helper: " + ensure_text(line), "scheduler")

    def app_closed(self, retval):
        write_debug("scheduler helper closed retval=" + str(retval), "scheduler")
        task = self.current_task
        if task is None:
            self.finish()
            return
        if retval != 0:
            self.mark_task(task.get("id"), self.current_run_key,
                           "Automatik Fehler: Code " + str(retval))
            self.finish()
            return
        if not task.get("import_after_generate"):
            self.mark_task(task.get("id"), self.current_run_key,
                           "Automatik EPG-Import-Daten OK: " + self.current_run_key)
            self.finish()
            return
        description = source_description_for_task(task)
        result = start_epgimport(self.session, None, source_descriptions=[description])
        if not result.started:
            self.mark_task(task.get("id"), self.current_run_key,
                           "Automatik EPG-Import Fehler: " + result.message)
            self.finish()
            return
        self.epg_monitor_started_at = result.monitor_started_at or time.time()
        self.epg_monitor_deadline = time.time() + 180
        self.container = None
        self.start_timer(1)

    def monitor_epgimport(self):
        task = self.current_task
        if task is None:
            self.finish()
            return True
        result = read_last_import_result()
        if result is not None:
            stamp, count, verdict = _unpack_import_result(result)
            write_debug(
                "monitor poll result_stamp=%s started=%s count=%s verdict=%s"
                % (stamp, self.epg_monitor_started_at, count, verdict),
                "import",
            )
            if stamp >= self.epg_monitor_started_at - 1:
                if verdict == "failed":
                    self.mark_task(task.get("id"), self.current_run_key,
                                   "Automatik Fehler: nicht in DB")
                elif count > 0:
                    self.mark_task(task.get("id"), self.current_run_key,
                                   "Automatik OK: " + str(count) + " Events")
                else:
                    self.mark_task(task.get("id"), self.current_run_key,
                                   "Automatik Warnung: 0 Events")
                self.finish()
                return True
        if time.time() >= self.epg_monitor_deadline:
            self.mark_task(task.get("id"), self.current_run_key,
                           "Automatik EPG-Import Timeout")
            self.finish()
            return True
        return False

    def finish(self):
        write_debug("scheduler finish", "scheduler")
        self.container = None
        self.current_task = None
        self.current_started_at = 0
        self.epg_monitor_started_at = None
        _set_plugin_busy(False)
        self.start_timer(60)


_scheduler = None


def main(session, **kwargs):
    write_debug("plugin menu entry opened", "plugin")
    session.open(EpgToXmlTaskList)


def autostart(reason, session=None, **kwargs):
    global _scheduler
    if reason != 0 or session is None or PluginDescriptor is None:
        return
    write_debug("session start reason=" + str(reason), "plugin")
    if _scheduler is None:
        _scheduler = EpgToXmlScheduler(session)
        _scheduler.start()


def Plugins(**kwargs):
    if PluginDescriptor is None:
        return []
    descriptors = [
        PluginDescriptor(name="EpgToXml", description="Taskbasierter EPG Import aus Online-Quellen",
                         where=PluginDescriptor.WHERE_PLUGINMENU, fnc=main,
                         icon="EPGtoXML.png"),
    ]
    where_sessionstart = getattr(PluginDescriptor, "WHERE_SESSIONSTART", None)
    if where_sessionstart is not None:
        descriptors.append(
            PluginDescriptor(name="EpgToXml Scheduler", where=where_sessionstart, fnc=autostart)
        )
    return descriptors
