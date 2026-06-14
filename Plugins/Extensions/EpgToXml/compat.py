# -*- coding: utf-8 -*-
from __future__ import absolute_import

import datetime
import time

try:
    basestring
except NameError:
    basestring = str

try:
    unicode
except NameError:
    unicode = str


def ensure_text(value, encoding="utf-8"):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    try:
        return value.decode(encoding)
    except Exception:
        try:
            return unicode(value)
        except Exception:
            return u""


def ensure_bytes(value, encoding="utf-8"):
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return ensure_text(value).encode(encoding)


def repair_mojibake(value):
    text = ensure_text(value)
    if u"Ã" not in text and u"Â" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except Exception:
        return text


def local_midnight(dt):
    return datetime.datetime(dt.year, dt.month, dt.day, 0, 0, 0)


def timestamp_ms(dt):
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return int(time.mktime(dt.timetuple()) * 1000)


def epgimport_time(dt):
    stamp = time.mktime(dt.timetuple())
    local = time.localtime(stamp)
    if getattr(time, "daylight", 0) and local.tm_isdst > 0:
        offset = -time.altzone
    else:
        offset = -time.timezone
    sign = "+"
    if offset < 0:
        sign = "-"
        offset = -offset
    hours = offset // 3600
    minutes = (offset % 3600) // 60
    return dt.strftime("%Y%m%d%H%M%S ") + ("%s%02d%02d" % (sign, hours, minutes))


def parse_hhmm(day, hhmm):
    parts = hhmm.split(":")
    hour = int(parts[0])
    minute = int(parts[1])
    return datetime.datetime(day.year, day.month, day.day, hour, minute, 0)
