# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import datetime

from .. import redbull_tv_client
from ..compat import ensure_text
from ..debuglog import write_debug, write_exception


# Red Bull TV hat keine öffentliche Channel-Discovery-API. Diese Liste wurde durch
# Beobachten der Netzwerk-Anfragen auf https://www.redbull.tv/de/epg ermittelt
# (Stand 2026-06-21) und muss von Hand aktualisiert werden, wenn Red Bull Sender
# hinzufügt, entfernt oder umbenennt. Um einen Sender zu ergänzen: Channel-Kachel
# auf der EPG-Seite öffnen, die `rrn:content:video-channels:<id>`-ID aus der
# Netzwerk-Anfrage `tv-api.redbull.com/guides/v5/rbtv/...` kopieren, hier mit
# Titel eintragen (Titel kommt aus `tv-api.redbull.com/products/v5.3/.../<id>`).
REDBULL_TV_CHANNELS = (
    ("c81f8686-ab67-4965-ba04-5f6658bb96cc", "World of Red Bull"),
    ("e0e6dee0-8c39-4de1-9488-72828468efe0", "Padel"),
    ("ee30c528-32b1-4604-8976-e3bcee4ae7f0", "Bike"),
    ("870bcfa8-62b1-4e84-9c85-39f083df368a", "Adventure"),
    ("fd4ed3c9-1800-477b-9909-53255da06632", "Motorsports"),
    ("2f6afaec-7ade-4fb8-961a-a51aa8279a99", "Surfing"),
    ("5021f46c-6f34-4f51-ba1f-967f2885ac97", "Skateboarding"),
    ("f4aa4fe4-5ce6-4b1c-a60b-abc6f21f16d0", "Winter"),
    ("69a66f02-21fd-42a1-be5b-6965541cfe6a", "Action Reel"),
)


def _epgimport_channel_id(channel_id):
    return "redbull.tv." + ensure_text(channel_id)


def normalise_redbull_channel(channel_id, name):
    channel_id = ensure_text(channel_id)
    return {
        "id": _epgimport_channel_id(channel_id),
        "name": ensure_text(name or channel_id),
        "redbull_channel_id": channel_id,
        "logo": "",
    }


def _parse_redbull_iso8601(value):
    text = ensure_text(value).strip()
    if len(text) < 19:
        raise ValueError("invalid datetime: " + text)
    return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")


class RedBullTvProvider(object):
    id = "redbull_tv"
    name = "Red Bull TV"

    def available_channels(self):
        return self.discover_channels()

    def discover_channels(self, progress=None):
        if progress:
            progress("step", "Red Bull TV Senderliste laden")
        channels = [
            normalise_redbull_channel(channel_id, name)
            for channel_id, name in REDBULL_TV_CHANNELS
        ]
        write_debug("Red Bull TV channel discovery ok: " + str(len(channels)) + " channels", "provider")
        return channels

    def channel_from_task(self, task):
        channel_id = ensure_text(task.get("redbull_channel_id") or "")
        name = ensure_text(task.get("source_channel_name") or "")
        return normalise_redbull_channel(channel_id, name)

    def fetch(self, task_or_days, access_context=None, progress=None):
        if isinstance(task_or_days, dict):
            channel = self.channel_from_task(task_or_days)
        else:
            channel = self.discover_channels()[0]

        target_id = ensure_text(channel.get("redbull_channel_id") or "")

        if progress:
            progress("step", u"Red Bull TV EPG für " + ensure_text(channel.get("name")) + u" laden")
        write_debug("Red Bull TV fetch start channel=%s redbull_channel_id=%s" % (
            ensure_text(channel.get("name")), target_id,
        ), "provider")

        try:
            data = redbull_tv_client.fetch_guide(target_id)
        except Exception as exc:
            write_exception("Red Bull TV fetch failed", exc)
            raise RuntimeError(u"Red Bull TV EPG konnte nicht geladen werden: " + ensure_text(exc))

        cards = data.get("cards") or []
        if not cards:
            raise RuntimeError(
                u"Red Bull TV hat keine Sendungen für '" + ensure_text(channel.get("name")) + u"' geliefert."
            )

        programmes = []
        for card in cards:
            programme = self._normalise_programme(channel, card)
            if programme:
                programmes.append(programme)
        write_debug("Red Bull TV fetch ok events=" + str(len(programmes)), "provider")
        return [channel], programmes

    def _normalise_programme(self, channel, card):
        try:
            start = _parse_redbull_iso8601(card.get("start_time"))
            stop = _parse_redbull_iso8601(card.get("end_time"))
        except Exception:
            return None
        title = ensure_text(card.get("title") or "")
        description = ensure_text(card.get("long_description") or card.get("short_description") or "")
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
            "source_id": ensure_text(card.get("id") or ""),
        }
