# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import datetime
import time

from .. import dazn_client
from ..compat import ensure_text, repair_mojibake
from ..debuglog import write_debug, write_exception


DEFAULT_RAIL_ID = "Livetvschedule"


def _slugify(text):
    text = ensure_text(text).strip().lower()
    safe = []
    for char in text:
        if char.isalnum() or char == "-":
            safe.append(char)
        elif char in (" ", "_", ".", "+"):
            safe.append("-")
    result = "".join(safe).strip("-")
    while "--" in result:
        result = result.replace("--", "-")
    return result


def _epgimport_channel_id(asset_id, title):
    slug = _slugify(title)
    return "dazn.de." + (slug or ensure_text(asset_id) or "unknown")


def _parse_iso8601(value):
    text = ensure_text(value).strip()
    return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")


def normalise_dazn_channel(tile):
    asset_id = ensure_text(tile.get("AssetId") or tile.get("dazn_asset_id") or "")
    name = repair_mojibake(tile.get("Title") or tile.get("name") or "")
    return {
        "id": _epgimport_channel_id(asset_id, name),
        "name": name,
        "dazn_asset_id": asset_id,
        "logo": ensure_text(tile.get("logo") or ""),
    }


def _programme_title(entry):
    title = repair_mojibake(entry.get("Title", ""))
    episode_title = repair_mojibake(entry.get("EpisodeTitle", ""))
    if episode_title:
        return title + ": " + episode_title
    return title


def _programme_category(entry):
    genres = entry.get("Genre") or []
    if genres and isinstance(genres, list):
        return repair_mojibake(genres[0].get("name", ""))
    return u""


class DaznDeProvider(object):
    id = "dazn_de"
    name = "DAZN Live-TV"

    def available_channels(self):
        return self.discover_channels()

    def discover_channels(self, progress=None):
        if progress:
            progress("step", "DAZN Senderliste laden")
        write_debug("DAZN channel discovery start", "provider")
        try:
            data = dazn_client.fetch_live_schedule(rail_id=DEFAULT_RAIL_ID)
        except Exception as exc:
            write_exception("DAZN channel discovery failed", exc)
            raise RuntimeError(
                u"DAZN ist gerade nicht erreichbar oder hat keine "
                u"gültige Senderliste geliefert: " + ensure_text(exc)
            )
        channels = []
        for tile in data.get("Tiles") or []:
            if not tile.get("LinearSchedule"):
                continue
            try:
                channels.append(normalise_dazn_channel(tile))
            except Exception:
                pass
        if not channels:
            write_debug("DAZN channel discovery returned zero channels", "provider")
            raise RuntimeError(u"DAZN hat keine Senderliste geliefert. Bitte später erneut versuchen.")
        channels.sort(key=lambda item: ensure_text(item.get("name", "")).lower())
        write_debug("DAZN channel discovery ok: " + str(len(channels)) + " channels", "provider")
        return channels

    def channel_from_task(self, task):
        asset_id = ensure_text(task.get("dazn_asset_id") or "")
        name = ensure_text(task.get("source_channel_name") or "")
        logo = ensure_text(task.get("source_channel_logo") or "")
        return normalise_dazn_channel({"AssetId": asset_id, "Title": name, "logo": logo})

    def fetch(self, task_or_days, access_context=None, progress=None):
        if isinstance(task_or_days, dict):
            days = int(task_or_days.get("days", 3))
            channel = self.channel_from_task(task_or_days)
        else:
            days = int(task_or_days)
            channel = self.discover_channels()[0]

        if progress:
            progress("step", u"DAZN EPG für " + ensure_text(channel.get("name")) + " laden")
        write_debug("DAZN fetch start channel=%s asset_id=%s days=%s" % (
            ensure_text(channel.get("name")),
            ensure_text(channel.get("dazn_asset_id")),
            days,
        ), "provider")
        try:
            data = dazn_client.fetch_live_schedule(rail_id=DEFAULT_RAIL_ID)
        except Exception as exc:
            write_exception("DAZN fetch failed", exc)
            raise RuntimeError("DAZN EPG konnte nicht geladen werden: " + ensure_text(exc))

        tile = None
        for item in data.get("Tiles") or []:
            if ensure_text(item.get("AssetId")) == ensure_text(channel.get("dazn_asset_id")):
                tile = item
                break
        if tile is None or not tile.get("LinearSchedule"):
            raise RuntimeError(
                u"DAZN-Sender '" + ensure_text(channel.get("name")) + u"' wurde in der Senderliste nicht gefunden."
            )

        schedule = tile["LinearSchedule"]
        entries = []
        for key in ("Now", "Next"):
            entry = schedule.get(key)
            if entry:
                entries.append(entry)
        entries.extend(schedule.get("Later") or [])

        horizon = None
        if days > 0:
            now = datetime.datetime(*time.gmtime()[:6])
            horizon = now + datetime.timedelta(days=days)

        programmes = []
        for entry in entries:
            programme = self._normalise_programme(channel, entry)
            if programme and (horizon is None or programme["start"] <= horizon):
                programmes.append(programme)
        write_debug("DAZN fetch ok events=" + str(len(programmes)), "provider")
        return [channel], programmes

    def _normalise_programme(self, channel, entry):
        try:
            start = _parse_iso8601(entry.get("Start"))
            stop = _parse_iso8601(entry.get("End"))
        except Exception:
            return None
        return {
            "channel_id": channel["id"],
            "title": _programme_title(entry),
            "category": _programme_category(entry),
            "start": start,
            "stop": stop,
            "country": "",
            "year": ensure_text(entry.get("EventYear") or ""),
            "rating": "",
            "source_id": "",
        }
