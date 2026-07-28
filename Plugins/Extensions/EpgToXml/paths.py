# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

CONFIG_DIR = "/etc/epgtoxml"
LEGACY_CONFIG_DIR = "/media/hdd/epgtoxml"
TASKS_PATH = CONFIG_DIR + "/tasks.json"
LEGACY_TASKS_PATH = LEGACY_CONFIG_DIR + "/tasks.json"
OUTPUT_DIR = "/tmp/epgtoxml/output"
SETTINGS_PATH = CONFIG_DIR + "/settings.json"
LEGACY_SETTINGS_PATH = LEGACY_CONFIG_DIR + "/settings.json"

# Zuletzt funktionierender Teleboy-API-Key. Bewusst eine eigene Datei und nicht
# settings.json: save_settings() schreibt die ganze Datei neu, der Fetch-Subprozess
# würde damit zeitgleiche UI-Änderungen überschreiben.
TELEBOY_KEY_PATH = CONFIG_DIR + "/teleboy_key.json"
DEBUG_LOG_PATH = "/var/log/epgtoxml.log"
DEBUG_LOG_ROTATED_PATH = "/var/log/epgtoxml.log.1"
DEBUG_LOG_MAX_BYTES = 20 * 1024

# Eigenes Import-Verzeichnis (kein externes EPGImport-Plugin mehr nötig).
IMPORT_DIR = CONFIG_DIR + "/import"
EPGIMPORT_PROGRAM_PATH = OUTPUT_DIR + "/epgtoxml-sky.xml"
SOURCES_PATH = IMPORT_DIR + "/epgtoxml.sources.xml"
CHANNELS_PATH = IMPORT_DIR + "/epgtoxml.channels.xml"
LOG_PATH = "/tmp/epgtoxml.log"
