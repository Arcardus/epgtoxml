# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import datetime
import re

try:
    from HTMLParser import HTMLParser
    _html_unescape = HTMLParser().unescape
except ImportError:
    from html import unescape as _html_unescape

from .. import zdf_client
from ..compat import ensure_text
from ..debuglog import write_debug, write_exception


# ZDF's GraphQL API has no broadcaster/channel discovery endpoint -- the
# request must name the broadcasters it wants and the response echoes back
# exactly (and only) those. This is the single place to add a newly launched
# ZDF channel; everything else (display name, programmes) comes from the API.
ZDF_BROADCASTER_IDS = ("ZDF", "ZDFneo", "ZDFinfo", "3sat", "KI.KA", "PHOENIX", "arte")

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _epgimport_channel_id(channel_id):
    return "zdf.de." + ensure_text(channel_id)


def normalise_zdf_channel(channel_id, title):
    channel_id = ensure_text(channel_id)
    return {
        "id": _epgimport_channel_id(channel_id),
        "name": ensure_text(title or channel_id),
        "zdf_channel_id": channel_id,
        "logo": "",
    }


def _parse_zdf_iso8601(value):
    text = ensure_text(value).strip()
    if len(text) < 19:
        raise ValueError("invalid datetime: " + text)
    return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")


def _strip_html(text):
    text = ensure_text(text)
    if not text:
        return u""
    text = _TAG_RE.sub(u" ", text)
    text = _html_unescape(text)
    return _WHITESPACE_RE.sub(u" ", text).strip()


def _day_window(day):
    start = day.strftime("%Y-%m-%dT03:00:00Z")
    end = (day + datetime.timedelta(days=1)).strftime("%Y-%m-%dT02:59:59Z")
    return start, end


class ZdfDeProvider(object):
    id = "zdf_de"
    name = "ZDF EPG"

    def available_channels(self):
        return self.discover_channels()

    def discover_channels(self, progress=None):
        if progress:
            progress("step", "ZDF Senderliste laden")
        write_debug("ZDF channel discovery start", "provider")
        today = datetime.date.today()
        from_iso, to_iso = _day_window(today)
        try:
            data = zdf_client.fetch_epg(from_iso, to_iso, ZDF_BROADCASTER_IDS)
        except Exception as exc:
            write_exception("ZDF channel discovery failed", exc)
            raise RuntimeError(
                u"ZDF ist gerade nicht erreichbar oder hat keine "
                u"gültige Senderliste geliefert: " + ensure_text(exc)
            )
        channels = []
        for item in (data.get("data") or {}).get("epg") or []:
            broadcaster = item.get("broadcaster") or {}
            channel_id = ensure_text(broadcaster.get("id") or "")
            if not channel_id:
                continue
            channels.append(normalise_zdf_channel(channel_id, broadcaster.get("title")))
        if not channels:
            write_debug("ZDF channel discovery returned zero channels", "provider")
            raise RuntimeError(u"ZDF hat keine Senderliste geliefert. Bitte später erneut versuchen.")
        channels.sort(key=lambda item: ensure_text(item.get("name", "")).lower())
        write_debug("ZDF channel discovery ok: " + str(len(channels)) + " channels", "provider")
        return channels

    def channel_from_task(self, task):
        channel_id = ensure_text(task.get("zdf_channel_id") or "")
        name = ensure_text(task.get("source_channel_name") or "")
        return normalise_zdf_channel(channel_id, name)

    def fetch(self, task_or_days, access_context=None, progress=None):
        if isinstance(task_or_days, dict):
            days = int(task_or_days.get("days", 3))
            channel = self.channel_from_task(task_or_days)
        else:
            days = int(task_or_days)
            channel = self.discover_channels()[0]

        target_id = ensure_text(channel.get("zdf_channel_id") or "")

        if progress:
            progress("step", u"ZDF EPG für " + ensure_text(channel.get("name")) + u" laden")
        write_debug("ZDF fetch start channel=%s zdf_channel_id=%s days=%s" % (
            ensure_text(channel.get("name")), target_id, days,
        ), "provider")

        found_channel = False
        programmes = []
        today = datetime.date.today()
        for offset in range(max(days, 1)):
            day = today + datetime.timedelta(days=offset)
            from_iso, to_iso = _day_window(day)
            try:
                data = zdf_client.fetch_epg(from_iso, to_iso, ZDF_BROADCASTER_IDS)
            except Exception as exc:
                write_exception("ZDF fetch failed", exc)
                raise RuntimeError(u"ZDF EPG konnte nicht geladen werden: " + ensure_text(exc))
            entry = None
            for item in (data.get("data") or {}).get("epg") or []:
                broadcaster = item.get("broadcaster") or {}
                if ensure_text(broadcaster.get("id")) == target_id:
                    entry = item
                    break
            if entry is None:
                continue
            found_channel = True
            for broadcast in entry.get("broadcasts") or []:
                programme = self._normalise_programme(channel, broadcast)
                if programme:
                    programmes.append(programme)

        if not found_channel:
            raise RuntimeError(
                u"ZDF-Sender '" + ensure_text(channel.get("name")) + u"' wurde in der Senderliste nicht gefunden."
            )
        write_debug("ZDF fetch ok events=" + str(len(programmes)), "provider")
        return [channel], programmes

    def _normalise_programme(self, channel, entry):
        try:
            start = _parse_zdf_iso8601(entry.get("airtimeBegin"))
            stop = _parse_zdf_iso8601(entry.get("airtimeEnd"))
        except Exception:
            return None
        title = ensure_text(entry.get("title") or "")
        subheadline = ensure_text(entry.get("subheadline") or "")
        if subheadline and subheadline != title:
            title = (title + ": " + subheadline) if title else subheadline
        description = _strip_html(entry.get("text") or "")
        video = entry.get("video") or {}
        return {
            "channel_id": channel["id"],
            "title": title,
            "description": description,
            "category": u"",
            "start": start,
            "stop": stop,
            "country": "",
            "year": "",
            "rating": "",
            "source_id": ensure_text(video.get("canonical") or ""),
        }
