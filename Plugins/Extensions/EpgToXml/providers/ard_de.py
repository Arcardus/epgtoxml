# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import datetime

from .. import ard_client
from ..compat import ensure_text, repair_mojibake
from ..debuglog import write_debug, write_exception


def _epgimport_channel_id(channel_id):
    return "ard.de." + ensure_text(channel_id)


def _widget_title(channel_obj):
    tracking = channel_obj.get("trackingPiano") or {}
    return ensure_text(tracking.get("widget_title") or "")


def _flatten_timeslots(channel_obj):
    entries = []
    for group in channel_obj.get("timeSlots") or []:
        if isinstance(group, list):
            entries.extend(group)
        elif group:
            entries.append(group)
    return entries


def _collect_subchannels(top_id, entries):
    found = {}
    for entry in entries:
        sub = entry.get("channel") or {}
        sub_id = ensure_text(sub.get("id") or "")
        main_id = ensure_text(sub.get("main_channel_id") or "")
        if not sub_id or sub_id == top_id or main_id != top_id:
            continue
        found[sub_id] = ensure_text(sub.get("name") or sub_id)
    return found


def _local_channel_variants(top):
    top_id = ensure_text(top.get("id") or "")
    found = {}
    for entry in top.get("localChannelList") or []:
        sub_id = ensure_text(entry.get("id") or "")
        if not sub_id or sub_id == top_id:
            continue
        found[sub_id] = ensure_text(entry.get("name") or sub_id)
    return found


def normalise_ard_channel(top_id, name, variants=None):
    top_id = ensure_text(top_id)
    channel = {
        "id": _epgimport_channel_id(top_id),
        "name": ensure_text(name or top_id.upper()),
        "ard_channel_id": top_id,
        "ard_variant_id": "",
        "logo": "",
    }
    if variants:
        channel["variants"] = variants
    return channel


def normalise_ard_variant(top_id, sub_id, name):
    sub_id = ensure_text(sub_id)
    return {
        "id": _epgimport_channel_id(sub_id),
        "name": ensure_text(name or sub_id),
        "ard_channel_id": ensure_text(top_id),
        "ard_variant_id": sub_id,
        "logo": "",
    }


def _parse_local_iso8601(value):
    text = ensure_text(value).strip()
    if len(text) < 19:
        raise ValueError("invalid datetime: " + text)
    return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")


class ArdDeProvider(object):
    id = "ard_de"
    name = "ARD EPG"

    def available_channels(self):
        return self.discover_channels()

    def discover_channels(self, progress=None):
        if progress:
            progress("step", "ARD Senderliste laden")
        write_debug("ARD channel discovery start", "provider")
        today = datetime.date.today().strftime("%Y-%m-%d")
        try:
            data = ard_client.fetch_day(today)
        except Exception as exc:
            write_exception("ARD channel discovery failed", exc)
            raise RuntimeError(
                u"ARD ist gerade nicht erreichbar oder hat keine "
                u"gültige Senderliste geliefert: " + ensure_text(exc)
            )
        channels = []
        for top in data.get("channels") or []:
            top_id = ensure_text(top.get("id") or "")
            if not top_id:
                continue
            subchannels = _local_channel_variants(top)
            if not subchannels:
                entries = _flatten_timeslots(top)
                fallback = _collect_subchannels(top_id, entries)
                if len(fallback) > 1:
                    subchannels = fallback
            variants = []
            for sub_id, sub_name in sorted(subchannels.items(), key=lambda kv: kv[1].lower()):
                variants.append(normalise_ard_variant(top_id, sub_id, sub_name))
            channels.append(normalise_ard_channel(top_id, _widget_title(top), variants))
        if not channels:
            write_debug("ARD channel discovery returned zero channels", "provider")
            raise RuntimeError(u"ARD hat keine Senderliste geliefert. Bitte später erneut versuchen.")
        channels.sort(key=lambda item: ensure_text(item.get("name", "")).lower())
        write_debug("ARD channel discovery ok: " + str(len(channels)) + " channels", "provider")
        return channels

    def channel_from_task(self, task):
        top_id = ensure_text(task.get("ard_channel_id") or "")
        variant_id = ensure_text(task.get("ard_variant_id") or "")
        name = ensure_text(task.get("source_channel_name") or "")
        if variant_id:
            return normalise_ard_variant(top_id, variant_id, name)
        return normalise_ard_channel(top_id, name)

    def fetch(self, task_or_days, access_context=None, progress=None):
        if isinstance(task_or_days, dict):
            days = int(task_or_days.get("days", 3))
            channel = self.channel_from_task(task_or_days)
        else:
            days = int(task_or_days)
            channel = self.discover_channels()[0]

        top_id = ensure_text(channel.get("ard_channel_id") or "")
        variant_id = ensure_text(channel.get("ard_variant_id") or "")
        target_id = variant_id or top_id

        if progress:
            progress("step", u"ARD EPG für " + ensure_text(channel.get("name")) + " laden")
        write_debug("ARD fetch start channel=%s ard_channel_id=%s ard_variant_id=%s days=%s" % (
            ensure_text(channel.get("name")), top_id, variant_id, days,
        ), "provider")

        found_channel = False
        programmes = []
        today = datetime.date.today()
        for offset in range(max(days, 1)):
            day = today + datetime.timedelta(days=offset)
            try:
                data = ard_client.fetch_day(day.strftime("%Y-%m-%d"))
            except Exception as exc:
                write_exception("ARD fetch failed", exc)
                raise RuntimeError(u"ARD EPG konnte nicht geladen werden: " + ensure_text(exc))
            top = None
            for item in data.get("channels") or []:
                if ensure_text(item.get("id")) == top_id:
                    top = item
                    break
            if top is None:
                continue
            found_channel = True
            for entry in _flatten_timeslots(top):
                sub = entry.get("channel") or {}
                entry_id = ensure_text(sub.get("id") or top_id)
                is_shared = variant_id and entry_id == top_id
                if entry_id != target_id and not is_shared:
                    continue
                programme = self._normalise_programme(channel, entry)
                if programme:
                    programmes.append(programme)

        if not found_channel:
            raise RuntimeError(
                u"ARD-Sender '" + ensure_text(channel.get("name")) + u"' wurde in der Senderliste nicht gefunden."
            )
        write_debug("ARD fetch ok events=" + str(len(programmes)), "provider")
        return [channel], programmes

    def _normalise_programme(self, channel, entry):
        try:
            start = _parse_local_iso8601(entry.get("broadcastedOn") or entry.get("beginNet"))
            stop = _parse_local_iso8601(entry.get("broadcastEnd"))
        except Exception:
            return None
        title = repair_mojibake(entry.get("coreTitle") or entry.get("title") or "")
        subline = repair_mojibake(entry.get("coreSubline") or entry.get("subline") or "")
        if subline and subline != title:
            title = (title + ": " + subline) if title else subline
        return {
            "channel_id": channel["id"],
            "title": title,
            "category": u"",
            "start": start,
            "stop": stop,
            "country": "",
            "year": "",
            "rating": "",
            "source_id": ensure_text(entry.get("id") or ""),
        }
