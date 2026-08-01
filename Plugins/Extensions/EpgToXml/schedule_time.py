# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import re

from .compat import ensure_text

try:
    unicode
except NameError:
    unicode = str


DEFAULT_SCHEDULE_TIMES = []
DEFAULT_SCHEDULE_TIME = "00:00"


def normalise_schedule_times(values, default=None):
    if default is None:
        default = DEFAULT_SCHEDULE_TIMES
    if values is None:
        values = default
    if isinstance(values, (str, unicode)):
        values = [values]
    result = []
    for value in values:
        text = ensure_text(value).strip()
        if not text:
            continue
        match = re.match(r"^([0-9]{1,2}):([0-9]{2})$", text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
        else:
            match = re.match(r"^([0-9]{3,4})$", text)
            if not match:
                continue
            number = int(match.group(1))
            hour = number // 100
            minute = number % 100
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            continue
        formatted = "%02d:%02d" % (hour, minute)
        if formatted not in result:
            result.append(formatted)
        if len(result) >= 2:
            break
    if not result:
        result = list(default)
    return result


def normalise_schedule_time(value, default=DEFAULT_SCHEDULE_TIME):
    times = normalise_schedule_times([value], default=[])
    if times:
        return times[0]
    return default


def hhmm_minutes(value):
    text = ensure_text(value)
    try:
        parts = text.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return -1
