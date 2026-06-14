# -*- coding: utf-8 -*-
from __future__ import absolute_import

import datetime

from .. import sky_client
from ..compat import ensure_text, local_midnight, parse_hhmm, repair_mojibake
from ..debuglog import write_debug, write_exception


DEFAULT_CHANNEL_ID = 1236
DEFAULT_CHANNEL_NAME = "DFB.TV"
DEFAULT_CHANNEL_SLUG = "dfbtv-c1236"
DEFAULT_EPGIMPORT_CHANNEL_ID = "sky.de.dfb-tv"
DEFAULT_LOGO = "https://www.sky.de/static/img/senderlogos_dark/1236_sky_26-05_senderlogos_dfbtv.png"


def _slug_from_url(value):
    text = ensure_text(value).strip()
    marker = "/tvguide/"
    if marker in text:
        text = text.split(marker, 1)[1]
    text = text.strip("/")
    return text or DEFAULT_CHANNEL_SLUG


def _logo_url(value):
    text = ensure_text(value).strip()
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("/"):
        return "https://www.sky.de" + text
    return text


def _epgimport_channel_id_from_slug(slug, channel_id):
    slug = ensure_text(slug).strip().lower()
    if int(channel_id) == DEFAULT_CHANNEL_ID or slug == DEFAULT_CHANNEL_SLUG:
        return DEFAULT_EPGIMPORT_CHANNEL_ID
    suffix = "-c" + str(int(channel_id))
    if slug.endswith(suffix):
        slug = slug[:-len(suffix)]
    safe = []
    for char in slug:
        if char.isalnum() or char == "-":
            safe.append(char)
        elif char in (" ", "_", ".", "+"):
            safe.append("-")
    text = "".join(safe).strip("-")
    return "sky.de." + (text or str(int(channel_id)))


def normalise_sky_channel(raw):
    channel_id = int(raw.get("ci") or raw.get("sky_channel_id") or raw.get("sky_id") or DEFAULT_CHANNEL_ID)
    slug = _slug_from_url(raw.get("cu") or raw.get("sky_channel_slug") or raw.get("slug") or DEFAULT_CHANNEL_SLUG)
    name = repair_mojibake(raw.get("cn") or raw.get("name") or DEFAULT_CHANNEL_NAME)
    logo = _logo_url(raw.get("clu") or raw.get("logo") or "")
    if not logo and channel_id == DEFAULT_CHANNEL_ID:
        logo = DEFAULT_LOGO
    return {
        "id": _epgimport_channel_id_from_slug(slug, channel_id),
        "name": name,
        "sky_id": channel_id,
        "sky_channel_id": channel_id,
        "sky_channel_slug": slug,
        "logo": logo,
    }


class SkyDeProvider(object):
    id = "sky_de"
    name = "Sky.de EPG"
    max_pages_per_day = 50
    default_channels = [normalise_sky_channel({
        "ci": DEFAULT_CHANNEL_ID,
        "cn": DEFAULT_CHANNEL_NAME,
        "cu": "/tvguide/" + DEFAULT_CHANNEL_SLUG,
        "clu": DEFAULT_LOGO,
    })]

    def available_channels(self):
        return list(self.default_channels)

    def discover_channels(self, progress=None):
        if progress:
            progress("step", "Sky.de Senderliste laden")
        write_debug("Sky channel discovery start", "provider")
        try:
            data = sky_client.list_channels(channel_slug=DEFAULT_CHANNEL_SLUG)
        except Exception as exc:
            write_exception("Sky channel discovery failed", exc)
            raise RuntimeError(u"Sky.de ist gerade nicht erreichbar oder hat keine g\u00fcltige Senderliste geliefert: " + ensure_text(exc))
        channels = []
        for item in data.get("cl", []):
            try:
                channels.append(normalise_sky_channel(item))
            except Exception:
                pass
        if not channels:
            write_debug("Sky channel discovery returned zero channels", "provider")
            raise RuntimeError(u"Sky.de hat keine Senderliste geliefert. Bitte sp\u00e4ter erneut versuchen.")
        channels.sort(key=lambda item: ensure_text(item.get("name", "")).lower())
        write_debug("Sky channel discovery ok: " + str(len(channels)) + " channels", "provider")
        return channels

    def channel_from_task(self, task):
        channel_id = int(task.get("sky_channel_id") or task.get("sky_id") or DEFAULT_CHANNEL_ID)
        slug = ensure_text(task.get("sky_channel_slug") or DEFAULT_CHANNEL_SLUG)
        name = ensure_text(task.get("source_channel_name") or task.get("name") or DEFAULT_CHANNEL_NAME)
        logo = ensure_text(task.get("source_channel_logo") or "")
        return normalise_sky_channel({
            "ci": channel_id,
            "cn": name,
            "cu": "/tvguide/" + slug,
            "clu": logo,
        })

    def fetch(self, task_or_days, access_context=None, progress=None):
        if isinstance(task_or_days, dict):
            days = int(task_or_days.get("days", 3))
            channel = self.channel_from_task(task_or_days)
        else:
            days = int(task_or_days)
            channel = self.default_channels[0]

        if progress:
            progress("step", u"Sky.de EPG f\u00fcr " + ensure_text(channel.get("name")) + " laden")
        write_debug("Sky fetch start channel=%s id=%s days=%s" % (
            ensure_text(channel.get("name")),
            ensure_text(channel.get("sky_channel_id") or channel.get("sky_id")),
            days,
        ), "provider")
        try:
            data = sky_client.fetch_days(
                channel_id=int(channel.get("sky_channel_id") or channel.get("sky_id")),
                channel_slug=ensure_text(channel.get("sky_channel_slug") or DEFAULT_CHANNEL_SLUG),
                start_offset=0,
                num_days=days,
            )
        except Exception as exc:
            write_exception("Sky fetch failed", exc)
            raise RuntimeError("Sky.de EPG konnte nicht geladen werden: " + ensure_text(exc))
        programmes = []
        for index, day in enumerate(data.get("days", [])):
            timestamp = int(day.get("timestamp") or 0) / 1000.0
            date = local_midnight(datetime.datetime.fromtimestamp(timestamp))
            if progress:
                progress("log", "Sky.de Tag %d/%d normalisieren" % (index + 1, days))
            for item in day.get("el", []):
                programme = self._normalise_programme(date, channel, item)
                if programme:
                    programmes.append(programme)
        write_debug("Sky fetch ok events=" + str(len(programmes)), "provider")
        return [channel], programmes

    def _normalise_programme(self, day, channel, item):
        try:
            start = parse_hhmm(day, item.get("bst", "00:00"))
            minutes = int(item.get("len", 0) or 0)
        except Exception:
            return None
        stop = start + datetime.timedelta(minutes=minutes)
        return {
            "channel_id": channel["id"],
            "title": repair_mojibake(item.get("et", "")),
            "category": repair_mojibake(item.get("ec", "")),
            "start": start,
            "stop": stop,
            "country": repair_mojibake(item.get("cop", "")),
            "year": item.get("yop"),
            "rating": repair_mojibake(item.get("fsk", "")),
            "source_id": str(item.get("ei") or item.get("bid") or ""),
        }
