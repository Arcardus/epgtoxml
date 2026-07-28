# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import calendar
import json
import os
import shutil
import socket
import tempfile
import time
import unittest

try:
    from urllib2 import URLError
except ImportError:
    from urllib.error import URLError

from Plugins.Extensions.EpgToXml import tasks as tasks_module
from Plugins.Extensions.EpgToXml import teleboy_keystore
from Plugins.Extensions.EpgToXml.providers import get_provider, get_providers
from Plugins.Extensions.EpgToXml.providers import teleboy_ch
from Plugins.Extensions.EpgToXml.providers.teleboy_ch import (
    TeleboyProvider,
    _parse_teleboy_datetime,
    normalise_teleboy_channel,
)
from Plugins.Extensions.EpgToXml.teleboy_client import (
    TeleboyAuthError,
    TeleboyEpgClient,
    TeleboyEpgError,
)


VALID_KEY = "541f13d53884e15c21045ea7d39d7b173add142a724cb030f7e698b951e8a538"
OTHER_KEY = "a" * 64

SRF_TASK = {
    "days": 4,
    "teleboy_channel_id": "303",
    "source_channel_name": "SRF 1",
}


def _station(station_id, name, language, with_logos=True):
    station = {
        "id": station_id,
        "name": name,
        "label": name.replace(" ", ""),
        "language": language,
        "country": "ch",
    }
    if with_logos:
        station["logos"] = {
            "path": "https://static.teleboy.ch/shared/stations/%d/icon[size]_[type].png" % station_id,
        }
    return station


def _stations_response(stations=None):
    if stations is None:
        stations = [
            _station(303, "SRF 1", "de"),
            _station(350, "3+", "de"),
            _station(400, "RTS 1", "fr"),
            _station(500, "RSI La 1", "it"),
            _station(600, "BBC One", "en"),
            _station(700, "TRT 1", "tr", with_logos=False),
        ]
    return {"success": True, "data": {"total": len(stations), "items": stations}}


def _broadcast(broadcast_id, title, begin, end, **extra):
    entry = {
        "id": broadcast_id,
        "title": title,
        "begin": begin,
        "end": end,
        "station_id": 303,
        "genre_id": 12,
        "description": "Volltext zu " + title,
        "short_description": "Kurz zu " + title,
        "country": "Schweiz",
        "year": 2026,
        "age": 12,
    }
    entry.update(extra)
    return entry


def _broadcasts_response(items, total=None):
    if total is None:
        total = len(items)
    return {"success": True, "data": {"total": total, "items": items}}


class _FakeResponse(object):
    def __init__(self, text):
        self._text = text

    def read(self, *args):
        return self._text.encode("utf-8")


class _FakeClient(object):
    """Client-Ersatz, der die übergebenen Argumente protokolliert."""

    def __init__(self, pages=None, stations=None):
        self.pages = pages if pages is not None else [_broadcasts_response([])]
        self.stations = stations if stations is not None else _stations_response()
        self.calls = []
        self.api_key = VALID_KEY
        self.api_key_refreshed = False

    def fetch_stations(self):
        return self.stations

    def fetch_broadcasts(self, station_id, begin, end, limit=300, skip=0):
        self.calls.append({
            "station_id": station_id, "begin": begin, "end": end,
            "limit": limit, "skip": skip,
        })
        index = len(self.calls) - 1
        if index < len(self.pages):
            return self.pages[index]
        return _broadcasts_response([])


class TeleboyDateParsingTests(unittest.TestCase):
    def _epoch(self, result):
        return int(time.mktime(result.timetuple()))

    def test_parses_numeric_offset_without_colon(self):
        result = _parse_teleboy_datetime("2026-07-28T11:00:00+0200")
        self.assertIsNone(result.tzinfo)
        self.assertEqual(self._epoch(result), calendar.timegm((2026, 7, 28, 9, 0, 0, 0, 0, 0)))

    def test_colon_offset_matches_plain_offset(self):
        with_colon = _parse_teleboy_datetime("2026-07-28T11:00:00+02:00")
        without = _parse_teleboy_datetime("2026-07-28T11:00:00+0200")
        self.assertEqual(with_colon, without)

    def test_parses_negative_offset(self):
        result = _parse_teleboy_datetime("2026-07-28T11:00:00-0500")
        self.assertEqual(self._epoch(result), calendar.timegm((2026, 7, 28, 16, 0, 0, 0, 0, 0)))

    def test_parses_zulu_as_utc(self):
        result = _parse_teleboy_datetime("2026-07-28T11:00:00Z")
        self.assertEqual(self._epoch(result), calendar.timegm((2026, 7, 28, 11, 0, 0, 0, 0, 0)))

    def test_without_offset_stays_naive_local(self):
        # Ohne Offset darf nicht umgerechnet werden -- sonst würde die Zeit
        # fälschlich als UTC gedeutet.
        result = _parse_teleboy_datetime("2026-07-28T11:00:00")
        self.assertEqual(result.hour, 11)
        self.assertEqual(result.day, 28)

    def test_strips_fractional_seconds(self):
        result = _parse_teleboy_datetime("2026-07-28T11:00:00.123+0200")
        self.assertEqual(self._epoch(result), calendar.timegm((2026, 7, 28, 9, 0, 0, 0, 0, 0)))

    def test_rejects_too_short_value(self):
        self.assertRaises(ValueError, _parse_teleboy_datetime, "2026-07-28")


class TeleboyChannelTests(unittest.TestCase):
    def setUp(self):
        self.provider = TeleboyProvider()
        self.client = _FakeClient()
        self.provider._client = lambda: self.client

    def test_normalise_channel_builds_id_and_logo(self):
        channel = normalise_teleboy_channel(_station(303, "SRF 1", "de"))
        self.assertEqual(channel["id"], "teleboy.ch.303")
        self.assertEqual(channel["name"], "SRF 1")
        self.assertEqual(channel["teleboy_channel_id"], "303")
        self.assertEqual(
            channel["logo"],
            "https://static.teleboy.ch/shared/stations/303/icon160_dark.png",
        )

    def test_station_without_logos_yields_empty_logo(self):
        channel = normalise_teleboy_channel(_station(700, "TRT 1", "tr", with_logos=False))
        self.assertEqual(channel["logo"], "")

    def test_discover_channels_groups_by_language(self):
        groups = self.provider.discover_channels()
        names = [group["name"] for group in groups]
        self.assertEqual(names, [
            "Deutsch (2)", u"Französisch (1)", "Italienisch (1)",
            "Englisch (1)", "Weitere Sprachen (1)",
        ])
        for group in groups:
            self.assertTrue(group["variants"])
            self.assertEqual(group["variant_prompt"], u"Sender wählen")

    def test_language_groups_are_sorted_by_name(self):
        groups = self.provider.discover_channels()
        german = [group for group in groups if group["id"].endswith(".de")][0]
        self.assertEqual([channel["name"] for channel in german["variants"]], ["3+", "SRF 1"])

    def test_discover_channels_raises_when_empty(self):
        self.client.stations = _stations_response([])
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.discover_channels()
        self.assertIn("keine Senderliste", str(ctx.exception))

    def test_channel_from_task(self):
        channel = self.provider.channel_from_task(SRF_TASK)
        self.assertEqual(channel["id"], "teleboy.ch.303")
        self.assertEqual(channel["teleboy_channel_id"], "303")
        self.assertEqual(channel["name"], "SRF 1")


class TeleboyFetchTests(unittest.TestCase):
    def setUp(self):
        self.provider = TeleboyProvider()
        self.client = _FakeClient()
        self.provider._client = lambda: self.client

    def _run(self, task=None):
        self.client.pages = [_broadcasts_response([
            _broadcast(1, "Tagesschau", "2026-07-28T19:30:00+0200", "2026-07-28T20:00:00+0200"),
        ])]
        return self.provider.fetch(task or dict(SRF_TASK))

    def test_fetch_maps_all_programme_fields(self):
        channels, programmes = self._run()
        self.assertEqual(len(channels), 1)
        self.assertEqual(len(programmes), 1)
        programme = programmes[0]
        self.assertEqual(programme["channel_id"], "teleboy.ch.303")
        self.assertEqual(programme["title"], "Tagesschau")
        self.assertEqual(programme["description"], "Volltext zu Tagesschau")
        self.assertEqual(programme["category"], "Unterhaltung")
        self.assertEqual(programme["country"], "Schweiz")
        self.assertEqual(programme["year"], "2026")
        self.assertEqual(programme["rating"], "12")
        self.assertEqual(programme["source_id"], "1")

    def test_subtitle_is_appended_to_title(self):
        self.client.pages = [_broadcasts_response([
            _broadcast(1, "Büssis SommerLacher", "2026-07-28T19:30:00+0200",
                       "2026-07-28T20:00:00+0200", subtitle="Frauen-Power"),
        ])]
        _, programmes = self.provider.fetch(dict(SRF_TASK))
        self.assertEqual(programmes[0]["title"], u"Büssis SommerLacher: Frauen-Power")

    def test_episode_prefix_is_prepended_to_description(self):
        self.client.pages = [_broadcasts_response([
            _broadcast(1, "Serie", "2026-07-28T19:30:00+0200", "2026-07-28T20:00:00+0200",
                       serie_season=3, serie_episode=4),
        ])]
        _, programmes = self.provider.fetch(dict(SRF_TASK))
        self.assertTrue(programmes[0]["description"].startswith("(S03E04) "))

    def test_short_description_is_used_when_description_missing(self):
        self.client.pages = [_broadcasts_response([
            _broadcast(1, "Ohne", "2026-07-28T19:30:00+0200", "2026-07-28T20:00:00+0200",
                       description=""),
        ])]
        _, programmes = self.provider.fetch(dict(SRF_TASK))
        self.assertEqual(programmes[0]["description"], "Kurz zu Ohne")

    def test_missing_end_falls_back_to_duration(self):
        self.client.pages = [_broadcasts_response([
            _broadcast(1, "Ohne Ende", "2026-07-28T19:30:00+0200", "", duration=45),
        ])]
        _, programmes = self.provider.fetch(dict(SRF_TASK))
        delta = programmes[0]["stop"] - programmes[0]["start"]
        self.assertEqual(delta.total_seconds(), 45 * 60)

    def test_broken_entry_is_skipped_not_fatal(self):
        self.client.pages = [_broadcasts_response([
            _broadcast(1, "Kaputt", "keine-zeit", "auch-nicht"),
            _broadcast(2, "Heil", "2026-07-28T19:30:00+0200", "2026-07-28T20:00:00+0200"),
        ])]
        _, programmes = self.provider.fetch(dict(SRF_TASK))
        self.assertEqual([p["title"] for p in programmes], ["Heil"])

    def test_days_are_capped_at_four(self):
        self._run(dict(SRF_TASK, days=14))
        call = self.client.calls[0]
        begin = call["begin"].split("+")[0]
        end = call["end"].split("+")[0]
        begin_day = time.strptime(begin, "%Y-%m-%d")
        end_day = time.strptime(end, "%Y-%m-%d")
        span = (calendar.timegm(end_day) - calendar.timegm(begin_day)) / 86400
        self.assertEqual(span, TeleboyProvider.max_days)

    def test_fetch_without_station_id_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.fetch({"days": 1, "teleboy_channel_id": ""})
        self.assertIn("kein Teleboy-Sender", str(ctx.exception))

    def test_client_errors_are_wrapped_with_intact_umlauts(self):
        def boom(*args, **kwargs):
            raise TeleboyEpgError(u"Teleboy ist nicht erreichbar: DNS-Auflösung fehlgeschlagen.")
        self.client.fetch_broadcasts = boom
        with self.assertRaises(RuntimeError) as ctx:
            self.provider.fetch(dict(SRF_TASK))
        message = str(ctx.exception) if str is not bytes else unicode(ctx.exception)  # noqa: F821
        self.assertIn("konnte nicht geladen werden", message)
        self.assertNotIn(u"Ã", message)


class TeleboyPaginationTests(unittest.TestCase):
    def setUp(self):
        self.provider = TeleboyProvider()
        self.client = _FakeClient()
        self.provider._client = lambda: self.client

    def _page(self, count, start_id, total):
        items = [
            _broadcast(start_id + i, "Titel %d" % (start_id + i),
                       "2026-07-28T%02d:00:00+0200" % (i % 24),
                       "2026-07-28T%02d:30:00+0200" % (i % 24))
            for i in range(count)
        ]
        return _broadcasts_response(items, total=total)

    def test_single_page_stops_immediately(self):
        self.client.pages = [self._page(10, 1, 10)]
        _, programmes = self.provider.fetch(dict(SRF_TASK))
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(len(programmes), 10)

    def test_two_pages_are_collected(self):
        self.client.pages = [self._page(300, 1, 450), self._page(150, 301, 450)]
        _, programmes = self.provider.fetch(dict(SRF_TASK))
        self.assertEqual(len(self.client.calls), 2)
        self.assertEqual(self.client.calls[1]["skip"], 300)
        self.assertEqual(len(programmes), 450)

    def test_bogus_total_stops_at_max_pages(self):
        # total lügt (99999), jede Seite liefert volle 300 -> darf nicht endlos laufen.
        self.client.pages = [self._page(300, 1 + i * 300, 99999) for i in range(20)]
        self.provider.fetch(dict(SRF_TASK))
        self.assertEqual(len(self.client.calls), teleboy_ch._MAX_PAGES)

    def test_empty_page_stops_loop(self):
        self.client.pages = [self._page(300, 1, 99999), _broadcasts_response([], total=99999)]
        self.provider.fetch(dict(SRF_TASK))
        self.assertEqual(len(self.client.calls), 2)


class TeleboyClientKeyTests(unittest.TestCase):
    def _fake_open(self, calls, fail_first_n=0):
        state = {"api": 0}

        def fake_open(request):
            url = request.get_full_url() if hasattr(request, "get_full_url") else request.full_url
            if "teleboy.ch/programm" in url:
                calls["scrape"] += 1
                return _FakeResponse(
                    "<html><body>var x = {tvapiKey: '%s', other: 1};</body></html>" % VALID_KEY
                )
            calls["api"] += 1
            state["api"] += 1
            if state["api"] <= fail_first_n:
                raise TeleboyAuthError("Teleboy lehnt die Anfrage ab (HTTP 403).")
            return _FakeResponse(json.dumps(_stations_response()))

        return fake_open

    def test_valid_key_causes_no_scrape(self):
        calls = {"scrape": 0, "api": 0}
        client = TeleboyEpgClient(api_key=VALID_KEY)
        client._open = self._fake_open(calls)
        client.fetch_stations()
        self.assertEqual(calls["scrape"], 0)
        self.assertEqual(calls["api"], 1)
        self.assertFalse(client.api_key_refreshed)

    def test_missing_key_is_scraped_before_first_request(self):
        calls = {"scrape": 0, "api": 0}
        client = TeleboyEpgClient()
        client._open = self._fake_open(calls)
        client.fetch_stations()
        self.assertEqual(calls["scrape"], 1)
        self.assertEqual(client.api_key, VALID_KEY)
        self.assertTrue(client.api_key_refreshed)

    def test_stale_key_triggers_exactly_one_retry(self):
        calls = {"scrape": 0, "api": 0}
        client = TeleboyEpgClient(api_key=OTHER_KEY)
        client._open = self._fake_open(calls, fail_first_n=1)
        client.fetch_stations()
        self.assertEqual(calls["scrape"], 1)
        self.assertEqual(calls["api"], 2)
        self.assertEqual(client.api_key, VALID_KEY)
        self.assertTrue(client.api_key_refreshed)

    def test_second_403_raises_without_further_scrape(self):
        calls = {"scrape": 0, "api": 0}
        client = TeleboyEpgClient(api_key=OTHER_KEY)
        client._open = self._fake_open(calls, fail_first_n=99)
        self.assertRaises(TeleboyAuthError, client.fetch_stations)
        self.assertEqual(calls["scrape"], 1)
        self.assertEqual(calls["api"], 2)

    def test_fresh_scrape_then_403_does_not_scrape_again(self):
        # Ohne Start-Key scrapt _ensure_key() bereits vor dem ersten Request. Wenn
        # dieser frische Key dann trotzdem 403 liefert, darf _with_key_retry nicht
        # ein zweites Mal die Webseite ziehen -- das ist der Fall, für den
        # _key_attempted existiert.
        calls = {"scrape": 0, "api": 0}
        client = TeleboyEpgClient()
        client._open = self._fake_open(calls, fail_first_n=99)
        self.assertRaises(TeleboyAuthError, client.fetch_stations)
        self.assertEqual(calls["scrape"], 1)
        self.assertEqual(calls["api"], 1)

    def test_repeated_calls_scrape_at_most_once(self):
        calls = {"scrape": 0, "api": 0}
        client = TeleboyEpgClient()
        client._open = self._fake_open(calls)
        client.fetch_stations()
        client.fetch_stations()
        client.fetch_stations()
        self.assertEqual(calls["scrape"], 1)
        self.assertEqual(calls["api"], 3)

    def test_scrape_does_not_hit_the_html_json_trap(self):
        # Regressionstest: _decode_json wirft bei Text, der mit '<' beginnt. Der
        # Key-Pfad muss daran vorbeigehen.
        client = TeleboyEpgClient()
        client._open = lambda request: _FakeResponse(
            "<!DOCTYPE html><html>tvapiKey: '%s'</html>" % VALID_KEY
        )
        self.assertEqual(client._scrape_api_key(), VALID_KEY)

    def test_scrape_falls_back_to_any_hex_key(self):
        client = TeleboyEpgClient()
        client._open = lambda request: _FakeResponse(
            "<html>renamedKey = \"%s\"</html>" % VALID_KEY
        )
        self.assertEqual(client._scrape_api_key(), VALID_KEY)

    def test_scrape_without_key_raises_explanatory_error(self):
        client = TeleboyEpgClient()
        client._open = lambda request: _FakeResponse("<html>nichts hier</html>")
        with self.assertRaises(TeleboyEpgError) as ctx:
            client._scrape_api_key()
        self.assertIn("Programmseite", str(ctx.exception))

    def test_unsuccessful_payload_raises(self):
        client = TeleboyEpgClient(api_key=VALID_KEY)
        client._open = lambda request: _FakeResponse(
            json.dumps({"success": False, "message": "kaputt"})
        )
        with self.assertRaises(TeleboyEpgError) as ctx:
            client.fetch_stations()
        self.assertIn("kaputt", str(ctx.exception))

    def test_broadcasts_url_requests_full_descriptions(self):
        captured = {}

        def fake_open(request):
            captured["url"] = request.get_full_url() if hasattr(request, "get_full_url") \
                else request.full_url
            return _FakeResponse(json.dumps(_broadcasts_response([])))

        client = TeleboyEpgClient(api_key=VALID_KEY)
        client._open = fake_open
        client.fetch_broadcasts("303", "2026-07-28+00:00:00", "2026-08-01+03:00:00")
        self.assertIn("expand=detail", captured["url"])
        self.assertIn("station=303", captured["url"])

    def test_api_key_header_is_sent(self):
        captured = {}

        def fake_open(request):
            captured["key"] = request.get_header("X-teleboy-apikey")
            return _FakeResponse(json.dumps(_stations_response()))

        client = TeleboyEpgClient(api_key=VALID_KEY)
        client._open = fake_open
        client.fetch_stations()
        self.assertEqual(captured["key"], VALID_KEY)


class TeleboyClientErrorMessageTests(unittest.TestCase):
    def test_dns_errors_are_reported_clearly(self):
        message = TeleboyEpgClient()._build_url_error_message(
            URLError(socket.gaierror(-2, "Name or service not known"))
        )
        self.assertIn("DNS", message)
        self.assertIn(u"Auflösung", message)
        self.assertNotIn(u"Ã", message)

    def test_timeout_message_names_the_limit(self):
        message = TeleboyEpgClient(timeout=8)._timeout_message()
        self.assertIn("8 Sekunden", message)

    def test_html_instead_of_json_is_explained(self):
        with self.assertRaises(TeleboyEpgError) as ctx:
            TeleboyEpgClient()._decode_json("<html>nope</html>")
        self.assertIn("HTML statt JSON", str(ctx.exception))


class TeleboyKeystoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "sub", "teleboy_key.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip(self):
        self.assertTrue(teleboy_keystore.save_api_key(VALID_KEY, self.path))
        self.assertEqual(teleboy_keystore.load_api_key(self.path), VALID_KEY)

    def test_missing_file_returns_empty(self):
        self.assertEqual(teleboy_keystore.load_api_key(self.path), u"")

    def test_broken_json_returns_empty(self):
        os.makedirs(os.path.dirname(self.path))
        handle = open(self.path, "w")
        handle.write("{kaputt")
        handle.close()
        self.assertEqual(teleboy_keystore.load_api_key(self.path), u"")

    def test_malformed_key_is_rejected_on_read(self):
        os.makedirs(os.path.dirname(self.path))
        handle = open(self.path, "w")
        handle.write(json.dumps({"api_key": "zu-kurz"}))
        handle.close()
        self.assertEqual(teleboy_keystore.load_api_key(self.path), u"")

    def test_malformed_key_is_rejected_on_write(self):
        self.assertFalse(teleboy_keystore.save_api_key("zu-kurz", self.path))

    def test_unwritable_path_returns_false_without_raising(self):
        self.assertFalse(teleboy_keystore.save_api_key(VALID_KEY, "/proc/nope/key.json"))


class TeleboyRegistrationTests(unittest.TestCase):
    def test_provider_is_registered(self):
        provider = get_provider("teleboy_ch")
        self.assertIsInstance(provider, TeleboyProvider)
        self.assertIn("teleboy_ch", [p.id for p in get_providers()])

    def test_max_days_matches_tasks_table(self):
        # Die 4 steht an zwei Stellen (Provider und tasks.py) -- hier verankert.
        self.assertEqual(
            TeleboyProvider.max_days,
            tasks_module.SOURCE_MAX_DAYS["teleboy_ch"],
        )

    def test_tasks_clamp_days_for_teleboy_only(self):
        teleboy = tasks_module.normalise_task({"source_id": "teleboy_ch", "days": 14})
        hdplus = tasks_module.normalise_task({"source_id": "hdplus_de", "days": 14})
        self.assertEqual(teleboy["days"], 4)
        self.assertEqual(hdplus["days"], 14)

    def test_task_keeps_teleboy_channel_id(self):
        task = tasks_module.normalise_task({
            "source_id": "teleboy_ch", "teleboy_channel_id": "303",
        })
        self.assertEqual(task["teleboy_channel_id"], "303")


if __name__ == "__main__":
    unittest.main()
