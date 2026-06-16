# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

from Plugins.Extensions.EpgToXml.epgimport_adapter import _LineBridge


def _collect():
    lines = []
    return lines, _LineBridge(lines.append)


def test_fragments_joined_into_single_line():
    lines, bridge = _collect()
    bridge.write("[X] a")
    bridge.write(" ")
    bridge.write("b")
    assert lines == []  # noch kein Newline -> gepuffert
    bridge.write("\n")
    assert lines == ["[X] a b"]


def test_multiple_lines_in_one_write():
    lines, bridge = _collect()
    bridge.write("l1\nl2\n")
    assert lines == ["l1", "l2"]


def test_partial_line_stays_buffered():
    lines, bridge = _collect()
    bridge.write("angefangen")
    assert lines == []
    bridge.write(" ende\n")
    assert lines == ["angefangen ende"]


def test_empty_lines_suppressed():
    lines, bridge = _collect()
    bridge.write("\n\nreal\n\n")
    assert lines == ["real"]


def test_carriage_return_stripped():
    lines, bridge = _collect()
    bridge.write("windows\r\n")
    assert lines == ["windows"]
