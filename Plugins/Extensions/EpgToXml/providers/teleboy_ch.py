# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import calendar
import datetime

from .. import teleboy_client, teleboy_keystore
from ..compat import ensure_text
from ..debuglog import write_debug, write_exception


# Teleboy liefert EPG für etwa -7 bis +13 Tage. Bewusst auf 4 Tage begrenzt, damit
# das Plugin keine unnötige Last auf der API erzeugt. plugin.py liest max_days aus,
# um den "Tage laden"-Regler zu begrenzen; tasks.SOURCE_MAX_DAYS klemmt beim
# Speichern. Diese Konstante hier ist die autoritative Grenze -- sie greift auch bei
# einer von Hand bearbeiteten tasks.json.
MAX_DAYS = 4

# Sprachgruppen für den Sender-Picker. Teleboy hat 310 Sender; ohne Gruppierung wäre
# die Liste im Enigma2-UI (keine Suchfunktion) nicht bedienbar. Die vier großen
# Sprachen bekommen eigene Gruppen, der Rest landet gesammelt in der letzten.
_LANGUAGE_GROUPS = (
    ("de", u"Deutsch"),
    ("fr", u"Französisch"),
    ("it", u"Italienisch"),
    ("en", u"Englisch"),
)
_OTHER_GROUP_LABEL = u"Weitere Sprachen"

# Aus GET /epg/genres (Stand 2026-07-28), Top-Genres und sub_genres flach.
# Bewusst statisch: ein Extra-Request würde die Anfragen eines typischen Laufs
# verdoppeln (1 -> 2), für ein rein kosmetisches XMLTV-Feld.
_GENRE_LABELS = {
    1: u"Film", 2: u"Dokumentation", 3: u"Action", 4: u"Serie",
    6: u"Kinder", 7: u"Sport", 8: u"Talk", 9: u"Kultur",
    10: u"News", 12: u"Unterhaltung", 13: u"Musik", 14: u"Reality",
    15: u"Erotik", 16: u"Abenteuer", 17: u"Trickfilm", 18: u"Krimi",
    19: u"Fantasy", 20: u"Kinderfilm", 21: u"Erotikfilm", 22: u"Horror",
    23: u"Krimiserie", 24: u"Actionserie", 25: u"Trickserie", 26: u"Dramaserie",
    27: u"Kinderserie", 28: u"Fantasyserie", 29: u"Drama", 30: u"Komödie",
    31: u"Musical", 32: u"Romantik", 33: u"SciFi", 34: u"Thriller",
    35: u"Western", 36: u"Info", 37: u"Shopping", 38: u"Wissen",
    39: u"Comedyserie",
}

# Schutz gegen ein fehlerhaftes "total" in der Antwort: 8 * 300 = 2400 Events sind
# für 4 Tage auf einem Sender weit jenseits des Realistischen.
_MAX_PAGES = 8

# Überhang am Fensterende, damit Sendungen über Mitternacht des letzten Tages noch
# mitkommen. Puffert zugleich ab, dass der Server den Zeitzonen-Offset in
# begin/end ignoriert und immer Schweizer Ortszeit annimmt.
_END_OVERHANG_HOURS = 3


def _epgimport_channel_id(channel_id):
    return "teleboy.ch." + ensure_text(channel_id)


def normalise_teleboy_channel(station):
    """Ein Station-Objekt der API in ein Channel-Dict des Plugins übersetzen."""
    station = station or {}
    station_id = ensure_text(station.get("id"))
    name = ensure_text(station.get("name") or station.get("label") or station_id)
    return {
        "id": _epgimport_channel_id(station_id),
        "name": name,
        "teleboy_channel_id": station_id,
        "logo": _logo_url(station),
    }


def _logo_url(station):
    """Logo-URL aus dem Platzhalter-Template der API bauen.

    Reine Kosmetik (landet als <icon> im XMLTV); jeder Fehler führt zu "" statt zu
    einem Abbruch.
    """
    try:
        path = ensure_text((station.get("logos") or {}).get("path") or "")
        if not path:
            return u""
        return path.replace("[size]", "160").replace("[type]", "dark")
    except Exception:
        return u""


def _parse_teleboy_datetime(value):
    """ISO8601 mit numerischem Offset in ein naives *lokales* datetime wandeln.

    Teleboy liefert ``2026-07-28T11:00:00+0200`` -- Python 2 kennt kein ``%z``, der
    Offset wird deshalb von Hand ausgewertet. ``compat.epgimport_time`` interpretiert
    das übergebene datetime per ``time.mktime`` als Ortszeit der Box, also wird hier
    auf ebendiese umgerechnet (analog ``providers/hdplus_de.py``).
    """
    text = ensure_text(value).strip()
    if len(text) < 19:
        raise ValueError("invalid datetime: " + text)
    naive = datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")

    rest = text[19:].strip()
    if rest.startswith("."):
        rest = rest[1:].lstrip("0123456789")
    if not rest:
        # Ohne Offset bleibt die Zeit unverändert -- sie durch timegm zu schicken
        # würde sie fälschlich als UTC deuten.
        return naive
    if rest in ("Z", "z"):
        offset_seconds = 0
    else:
        sign = rest[0]
        digits = rest[1:].replace(":", "")
        if sign not in ("+", "-") or len(digits) < 4 or not digits[:4].isdigit():
            return naive
        offset_seconds = int(digits[:2]) * 3600 + int(digits[2:4]) * 60
        if sign == "-":
            offset_seconds = -offset_seconds

    utc = naive - datetime.timedelta(seconds=offset_seconds)
    return datetime.datetime.fromtimestamp(calendar.timegm(utc.timetuple()))


def _api_timestamp(moment):
    """Zeitstempel im von der API erwarteten Format ``YYYY-MM-DD+HH:MM:SS``."""
    return moment.strftime("%Y-%m-%d+%H:%M:%S")


def _genre_label(entry):
    try:
        return _GENRE_LABELS.get(int(entry.get("genre_id") or 0), u"")
    except (TypeError, ValueError):
        return u""


def _episode_prefix(entry):
    try:
        season = int(entry.get("serie_season") or 0)
    except (TypeError, ValueError):
        season = 0
    try:
        episode = int(entry.get("serie_episode") or 0)
    except (TypeError, ValueError):
        episode = 0
    if season and episode:
        return u"(S%02dE%02d) " % (season, episode)
    if episode:
        return u"(E%02d) " % episode
    return u""


class TeleboyProvider(object):
    id = "teleboy_ch"
    name = "Teleboy.ch (Schweiz)"
    max_days = MAX_DAYS

    def available_channels(self):
        return self.discover_channels()

    def discover_channels(self, progress=None):
        """Sprachgruppen mit den echten Sendern als ``variants``.

        plugin.py besitzt bereits einen zweistufigen Picker (ursprünglich für die
        ARD-Regionalvarianten) und ist dabei völlig generisch -- damit bekommt
        Teleboy die Sprachauswahl ohne Änderung an der Picker-Logik.
        """
        if progress:
            progress("step", "Teleboy Senderliste laden")
        write_debug("Teleboy channel discovery start", "provider")

        client = self._client()
        try:
            data = client.fetch_stations()
        except Exception as exc:
            write_exception("Teleboy channel discovery failed", exc)
            raise RuntimeError(
                u"Teleboy ist gerade nicht erreichbar oder hat keine "
                u"gültige Senderliste geliefert: " + ensure_text(exc)
            )
        finally:
            self._persist_key(client)

        by_language = {}
        for station in (data.get("data") or {}).get("items") or []:
            channel = normalise_teleboy_channel(station)
            if not channel.get("teleboy_channel_id"):
                continue
            language = ensure_text(station.get("language") or "").lower()
            by_language.setdefault(language, []).append(channel)

        if not by_language:
            write_debug("Teleboy channel discovery returned zero channels", "provider")
            raise RuntimeError(u"Teleboy hat keine Senderliste geliefert. Bitte später erneut versuchen.")

        groups = []
        for code, label in _LANGUAGE_GROUPS:
            channels = by_language.pop(code, [])
            if channels:
                groups.append(self._language_group(code, label, channels))

        rest = []
        for channels in by_language.values():
            rest.extend(channels)
        if rest:
            groups.append(self._language_group("other", _OTHER_GROUP_LABEL, rest))

        write_debug("Teleboy channel discovery ok: %d groups" % len(groups), "provider")
        return groups

    def _language_group(self, code, label, channels):
        channels.sort(key=lambda item: ensure_text(item.get("name", "")).lower())
        return {
            "id": "teleboy.ch.lang." + code,
            "name": u"%s (%d)" % (label, len(channels)),
            # Titel des Untermenüs -- ohne das würde plugin.py "Region wählen" zeigen.
            "variant_prompt": "Sender wählen",
            "variants": channels,
        }

    def channel_from_task(self, task):
        station_id = ensure_text(task.get("teleboy_channel_id") or "")
        name = ensure_text(task.get("source_channel_name") or "")
        return {
            "id": _epgimport_channel_id(station_id),
            "name": name or station_id,
            "teleboy_channel_id": station_id,
            "logo": ensure_text(task.get("source_channel_logo") or ""),
        }

    def fetch(self, task_or_days, access_context=None, progress=None):
        if isinstance(task_or_days, dict):
            days = int(task_or_days.get("days", 3))
            channel = self.channel_from_task(task_or_days)
        else:
            days = int(task_or_days)
            channel = self._first_channel()

        if days > self.max_days:
            write_debug("Teleboy days %d capped to %d" % (days, self.max_days), "provider")
        days = max(1, min(days, self.max_days))

        station_id = ensure_text(channel.get("teleboy_channel_id") or "")
        if not station_id:
            raise RuntimeError(u"Für diesen Task ist kein Teleboy-Sender hinterlegt.")

        if progress:
            progress("step", u"Teleboy EPG für " + ensure_text(channel.get("name")) + u" laden")
        write_debug("Teleboy fetch start channel=%s station=%s days=%s" % (
            ensure_text(channel.get("name")), station_id, days,
        ), "provider")

        today = datetime.date.today()
        begin = _api_timestamp(datetime.datetime(today.year, today.month, today.day))
        end_day = today + datetime.timedelta(days=days)
        end = _api_timestamp(
            datetime.datetime(end_day.year, end_day.month, end_day.day) +
            datetime.timedelta(hours=_END_OVERHANG_HOURS)
        )

        client = self._client()
        try:
            entries = self._fetch_all_pages(client, station_id, begin, end)
        except Exception as exc:
            write_exception("Teleboy fetch failed", exc)
            raise RuntimeError(u"Teleboy EPG konnte nicht geladen werden: " + ensure_text(exc))
        finally:
            self._persist_key(client)

        programmes = []
        seen_ids = set()
        for entry in entries:
            entry_id = ensure_text(entry.get("id") or "")
            if entry_id and entry_id in seen_ids:
                continue
            programme = self._normalise_programme(channel, entry)
            if programme:
                if entry_id:
                    seen_ids.add(entry_id)
                programmes.append(programme)

        write_debug("Teleboy fetch ok events=" + str(len(programmes)), "provider")
        return [channel], programmes

    def _fetch_all_pages(self, client, station_id, begin, end):
        items = []
        skip = 0
        for _page in range(_MAX_PAGES):
            data = client.fetch_broadcasts(
                station_id, begin, end,
                limit=teleboy_client.PAGE_LIMIT, skip=skip,
            )
            payload = data.get("data") or {}
            page = payload.get("items") or []
            items.extend(page)
            try:
                total = int(payload.get("total") or 0)
            except (TypeError, ValueError):
                total = 0
            # Abbruch an der leeren Seite statt an "kürzer als limit": falls Teleboy
            # den Deckel später unter 300 senkt, würde letzteres fälschlich nach der
            # ersten Seite stoppen.
            if not page or len(items) >= total:
                break
            skip += teleboy_client.PAGE_LIMIT
        return items

    def _first_channel(self):
        """Erster echter Sender -- discover_channels() liefert Gruppen, keine Sender."""
        for group in self.discover_channels():
            for channel in group.get("variants") or []:
                return channel
        raise RuntimeError(u"Teleboy hat keine Senderliste geliefert.")

    def _client(self):
        """Eine Client-Instanz pro Lauf.

        Bewusste Abweichung von den anderen Providern, die die Modul-Funktionen des
        Clients nutzen: die bauen pro Aufruf eine neue Instanz, wodurch bei einem
        Cache-Miss jedes Mal die ~520 KB große HTML-Seite für den API-Key geladen
        würde.
        """
        return teleboy_client.TeleboyEpgClient(api_key=teleboy_keystore.load_api_key())

    def _persist_key(self, client):
        if getattr(client, "api_key_refreshed", False) and client.api_key:
            teleboy_keystore.save_api_key(client.api_key)

    def _normalise_programme(self, channel, entry):
        try:
            start = _parse_teleboy_datetime(entry.get("begin"))
        except Exception:
            return None

        stop = None
        try:
            stop = _parse_teleboy_datetime(entry.get("end"))
        except Exception:
            try:
                duration = int(entry.get("duration") or 0)
            except (TypeError, ValueError):
                duration = 0
            if duration > 0:
                stop = start + datetime.timedelta(minutes=duration)
        if stop is None or stop <= start:
            return None

        title = ensure_text(entry.get("title") or "")
        subtitle = ensure_text(
            entry.get("subtitle") or entry.get("serie_episode_title") or ""
        )
        if subtitle and subtitle != title:
            title = (title + u": " + subtitle) if title else subtitle

        # description kommt dank expand=detail für praktisch jede Sendung mit;
        # short_description bleibt als Rückfallebene.
        description = ensure_text(
            entry.get("description") or entry.get("short_description") or ""
        )
        if description:
            description = _episode_prefix(entry) + description

        return {
            "channel_id": channel["id"],
            "title": title,
            "description": description,
            "category": _genre_label(entry),
            "start": start,
            "stop": stop,
            "country": ensure_text(entry.get("country") or ""),
            "year": ensure_text(entry.get("year") or ""),
            "rating": ensure_text(entry.get("age") or ""),
            "source_id": ensure_text(entry.get("id") or ""),
        }
