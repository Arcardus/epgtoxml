# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import os
import xml.etree.ElementTree as ET

from .compat import ensure_text, epgimport_time
from .paths import CHANNELS_PATH, EPGIMPORT_PROGRAM_PATH, SOURCES_PATH


LEGACY_SOURCE_DESCRIPTION = "EpgToXml - Sky.de DFB.TV"


def ensure_parent(path):
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)


def indent(elem, level=0):
    space = "\n" + level * "\t"
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = space + "\t"
        for child in elem:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = space
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = space


def write_xml(path, root, encoding="utf-8"):
    ensure_parent(path)
    indent(root)
    tree = ET.ElementTree(root)
    tree.write(path, encoding=encoding, xml_declaration=True)


def write_epgimport_program_file(channels, programmes, path=EPGIMPORT_PROGRAM_PATH):
    root = ET.Element("tv", {
        "generator-info-name": "EpgToXml",
        "generator-info-url": "https://www.sky.de/tvguide/dfbtv-c1236",
    })
    for channel in channels:
        ch = ET.SubElement(root, "channel", {"id": channel["id"]})
        ET.SubElement(ch, "display-name").text = ensure_text(channel["name"])
        if channel.get("logo"):
            ET.SubElement(ch, "icon", {"src": ensure_text(channel["logo"])})
    for programme in programmes:
        attrs = {
            "channel": ensure_text(programme["channel_id"]),
            "start": epgimport_time(programme["start"]),
            "stop": epgimport_time(programme["stop"]),
        }
        pr = ET.SubElement(root, "programme", attrs)
        ET.SubElement(pr, "title", {"lang": "de"}).text = ensure_text(programme.get("title", ""))
        if programme.get("category"):
            ET.SubElement(pr, "category", {"lang": "de"}).text = ensure_text(programme.get("category", ""))
        if programme.get("country"):
            ET.SubElement(pr, "country").text = ensure_text(programme.get("country", ""))
        if programme.get("year"):
            ET.SubElement(pr, "date").text = ensure_text(programme.get("year"))
        if programme.get("rating"):
            rating = ET.SubElement(pr, "rating", {"system": "FSK"})
            ET.SubElement(rating, "value").text = ensure_text(programme.get("rating"))
    write_xml(path, root)
    return path


def write_channels(service_ref, channel_id="sky.de.dfb-tv", path=CHANNELS_PATH):
    root = ET.Element("channels")
    channel = ET.SubElement(root, "channel", {"id": channel_id})
    channel.text = ensure_text(service_ref)
    write_xml(path, root, encoding="latin-1")
    return path


def write_channels_for_tasks(tasks, path=CHANNELS_PATH):
    root = ET.Element("channels")
    for task in tasks:
        service_ref = task.get("target_service_ref")
        channel_id = task.get("source_channel_id")
        if not service_ref or not channel_id:
            continue
        channel = ET.SubElement(root, "channel", {"id": ensure_text(channel_id)})
        channel.text = ensure_text(service_ref)
    write_xml(path, root, encoding="latin-1")
    return path


def source_description_for_task(task):
    task_id = ensure_text(task.get("id") or "task")
    name = ensure_text(task.get("name") or task_id)
    return "EpgToXml - " + name + " [" + task_id + "]"


def source_descriptions_for_tasks(tasks, task_program_paths):
    descriptions = []
    for task in tasks:
        if task_program_paths.get(task.get("id")):
            descriptions.append(source_description_for_task(task))
    return descriptions


def write_sources(path=SOURCES_PATH, channels_file="epgtoxml.channels.xml", program_path=EPGIMPORT_PROGRAM_PATH):
    root = ET.Element("sources")
    sourcecat = ET.SubElement(root, "sourcecat", {"sourcecatname": "EpgToXml"})
    source = ET.SubElement(sourcecat, "source", {
        "type": "gen_xmltv",
        "channels": channels_file,
        "nocheck": "1",
    })
    ET.SubElement(source, "description").text = LEGACY_SOURCE_DESCRIPTION
    ET.SubElement(source, "url").text = program_path
    write_xml(path, root)
    return path


def write_sources_for_tasks(tasks, task_program_paths, path=SOURCES_PATH, channels_file="epgtoxml.channels.xml"):
    root = ET.Element("sources")
    sourcecat = ET.SubElement(root, "sourcecat", {"sourcecatname": "EpgToXml"})
    for task in tasks:
        task_id = task.get("id")
        program_path = task_program_paths.get(task_id)
        if not program_path:
            continue
        source = ET.SubElement(sourcecat, "source", {
            "type": "gen_xmltv",
            "channels": channels_file,
            "nocheck": "1",
        })
        ET.SubElement(source, "description").text = source_description_for_task(task)
        ET.SubElement(source, "url").text = ensure_text(program_path)
    write_xml(path, root)
    return path
