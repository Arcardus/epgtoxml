# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import base64
import datetime

from .. import rtlplus_client
from ..compat import ensure_text
from ..debuglog import write_debug, write_exception


def _epgimport_channel_id(service_id):
    return "rtlplus.de." + ensure_text(service_id)


def normalise_rtlplus_channel(service_id, title):
    service_id = ensure_text(service_id)
    return {
        "id": _epgimport_channel_id(service_id),
        "name": ensure_text(title or service_id),
        "rtlplus_channel_id": service_id,
        "logo": "",
    }


def _decode_modal_id(value_modal_id):
    """Decodes a base64 value_modal.id into (service_id, program_id, date).

    Used only for the source_id/logging, not for data extraction -- the
    description/category come from the modal response itself.
    """
    try:
        padded = value_modal_id + "=" * (-len(value_modal_id) % 4)
        decoded = base64.b64decode(padded).decode("utf-8")
        service_id, program_id, date = decoded.split("+", 2)
        return service_id, program_id, date
    except Exception:
        return "", "", ""


def _parse_rtlplus_iso8601(value):
    text = ensure_text(value).strip()
    if len(text) < 19:
        raise ValueError("invalid datetime: " + text)
    return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")


class RtlPlusDeProvider(object):
    id = "rtl_plus"
    name = "RTL+ EPG"

    def available_channels(self):
        return self.discover_channels()

    def discover_channels(self, progress=None):
        if progress:
            progress("step", "RTL+ Senderliste laden")
        write_debug("RTL+ channel discovery start", "provider")
        today = datetime.date.today().strftime("%Y-%m-%d")
        try:
            data = rtlplus_client.fetch_day(today)
        except Exception as exc:
            write_exception("RTL+ channel discovery failed", exc)
            raise RuntimeError(
                u"RTL+ ist gerade nicht erreichbar oder hat keine "
                u"gültige Senderliste geliefert: " + ensure_text(exc)
            )
        channels = []
        for item in self._grid_items(data):
            channel_obj = (item.get("itemContent") or {}).get("channel") or {}
            service_id = ensure_text(channel_obj.get("id") or "")
            if not service_id:
                continue
            channels.append(normalise_rtlplus_channel(service_id, channel_obj.get("title")))
        if not channels:
            write_debug("RTL+ channel discovery returned zero channels", "provider")
            raise RuntimeError(u"RTL+ hat keine Senderliste geliefert. Bitte später erneut versuchen.")
        channels.sort(key=lambda item: ensure_text(item.get("name", "")).lower())
        write_debug("RTL+ channel discovery ok: " + str(len(channels)) + " channels", "provider")
        return channels

    def channel_from_task(self, task):
        service_id = ensure_text(task.get("rtlplus_channel_id") or "")
        name = ensure_text(task.get("source_channel_name") or "")
        return normalise_rtlplus_channel(service_id, name)

    def fetch(self, task_or_days, access_context=None, progress=None):
        if isinstance(task_or_days, dict):
            days = int(task_or_days.get("days", 3))
            channel = self.channel_from_task(task_or_days)
        else:
            days = int(task_or_days)
            channel = self.discover_channels()[0]

        target_id = ensure_text(channel.get("rtlplus_channel_id") or "")

        if progress:
            progress("step", u"RTL+ EPG für " + ensure_text(channel.get("name")) + u" laden")
        write_debug("RTL+ fetch start channel=%s rtlplus_channel_id=%s days=%s" % (
            ensure_text(channel.get("name")), target_id, days,
        ), "provider")

        found_channel = False
        programmes = []
        today = datetime.date.today()
        for offset in range(max(days, 1)):
            day = today + datetime.timedelta(days=offset)
            try:
                data = rtlplus_client.fetch_day(day.strftime("%Y-%m-%d"))
            except Exception as exc:
                write_exception("RTL+ fetch failed", exc)
                raise RuntimeError(u"RTL+ EPG konnte nicht geladen werden: " + ensure_text(exc))
            entry = None
            for item in self._grid_items(data):
                channel_obj = (item.get("itemContent") or {}).get("channel") or {}
                if ensure_text(channel_obj.get("id")) == target_id:
                    entry = item.get("itemContent") or {}
                    break
            if entry is None:
                continue
            found_channel = True
            for box in entry.get("epgBox") or []:
                programme = self._normalise_programme(channel, box)
                if programme:
                    programmes.append(programme)

        if not found_channel:
            raise RuntimeError(
                u"RTL+-Sender '" + ensure_text(channel.get("name")) + u"' wurde in der Senderliste nicht gefunden."
            )
        write_debug("RTL+ fetch ok events=" + str(len(programmes)), "provider")
        return [channel], programmes

    def _grid_items(self, data):
        return (data.get("content") or {}).get("items") or []

    def _normalise_programme(self, channel, box):
        try:
            start = _parse_rtlplus_iso8601((box.get("start") or {}).get("date"))
            stop = _parse_rtlplus_iso8601((box.get("end") or {}).get("date"))
        except Exception:
            return None
        title = ensure_text(box.get("title") or "")
        extra_title = ensure_text(box.get("extraTitle") or "")
        if extra_title and extra_title != title:
            title = (title + ": " + extra_title) if title else extra_title

        description = u""
        category = u""
        program_id = u""
        modal_id = ensure_text(
            (((box.get("action") or {}).get("target") or {}).get("value_modal") or {}).get("id") or ""
        )
        if modal_id:
            _, program_id, _ = _decode_modal_id(modal_id)
            try:
                modal = rtlplus_client.fetch_modal(modal_id)
                description, category = self._extract_modal_details(modal)
            except Exception as exc:
                write_debug("RTL+ modal fetch failed for %s: %s" % (modal_id, ensure_text(exc)), "provider")

        return {
            "channel_id": channel["id"],
            "title": title,
            "description": description,
            "category": category,
            "start": start,
            "stop": stop,
            "country": "",
            "year": "",
            "rating": "",
            "source_id": program_id,
        }

    def _extract_modal_details(self, modal):
        for block in modal.get("blocks") or []:
            for item in (block.get("content") or {}).get("items") or []:
                item_content = item.get("itemContent") or {}
                if item_content:
                    return (
                        ensure_text(item_content.get("description") or ""),
                        ensure_text(item_content.get("extraDetails") or ""),
                    )
        return u"", u""
