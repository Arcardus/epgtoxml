# -*- coding: utf-8 -*-
from __future__ import absolute_import

CONFIG_DIR = "/etc/epgtoxml"
LEGACY_CONFIG_DIR = "/media/hdd/epgtoxml"
TASKS_PATH = CONFIG_DIR + "/tasks.json"
LEGACY_TASKS_PATH = LEGACY_CONFIG_DIR + "/tasks.json"
OUTPUT_DIR = "/tmp/epgtoxml/output"
SETTINGS_PATH = CONFIG_DIR + "/settings.json"
LEGACY_SETTINGS_PATH = LEGACY_CONFIG_DIR + "/settings.json"
DEBUG_LOG_PATH = "/var/log/epgtoxml.log"
DEBUG_LOG_ROTATED_PATH = "/var/log/epgtoxml.log.1"
DEBUG_LOG_MAX_BYTES = 20 * 1024

EPGIMPORT_DIR = "/etc/epgimport"
EPGIMPORT_PROGRAM_PATH = OUTPUT_DIR + "/epgtoxml-sky.xml"
SOURCES_PATH = EPGIMPORT_DIR + "/epgtoxml.sources.xml"
CHANNELS_PATH = EPGIMPORT_DIR + "/epgtoxml.channels.xml"
LOG_PATH = "/tmp/epgtoxml.log"
