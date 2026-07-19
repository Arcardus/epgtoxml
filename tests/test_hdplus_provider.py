# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import calendar
import datetime
import socket
import ssl
import time
import unittest

try:
    from urllib2 import URLError
except ImportError:
    from urllib.error import URLError

from Plugins.Extensions.EpgToXml import hdplus_client as hdplus_client_module
from Plugins.Extensions.EpgToXml.providers import hdplus_de
from Plugins.Extensions.EpgToXml.providers.hdplus_de import (
    HDPLUS_CHANNELS,
    HdPlusProvider,
    _parse_hdplus_utc,
    normalise_hdplus_channel,
)
from Plugins.Extensions.EpgToXml.hdplus_client import HdPlusEpgClient, HdPlusEpgError
from Plugins.Extensions.EpgToXml.compat import ensure_text


def _programme(name, start_time, duration, sub_name="", fsk=None, categories=None, genres=None):
    entry = {
        "startTime": start_time,
        "duration": duration,
        "name": name,
        "subName": sub_name,
        "isHD": True,
        "isWidescreen": True,
        "categories": categories or [],
        "genres": genres or [],
        "detail": "16589256/EP024012010006",
    }
    if fsk is not None:
        entry["fskRating"] = fsk
    return entry


def _slice_response(programmes, common="das_erste_hd", parent="das_erste"):
    return {
        "commonChannel": common,
        "parentChannel": parent,
        "programmes": programmes,
    }


ERSTE_TASK = {"hdplus_channel_id": "das_erste_hd", "source_channel_name": "Das Erste HD"}


class HdPlusProviderTests(unittest.TestCase):
    def setUp(self):
        self.old_fetch_slice = hdplus_de.hdplus_client.fetch_slice

    def tearDown(self):
        hdplus_de.hdplus_client.fetch_slice = self.old_fetch_slice

    def test_discover_channels_returns_static_list(self):
        channels = HdPlusProvider().discover_channels()
        self.assertEqual(len(channels), len(HDPLUS_CHANNELS))
        by_id = {channel["hdplus_channel_id"]: channel for channel in channels}
        self.assertEqual(by_id["das_erste_hd"]["id"], "hdplus.de.das_erste_hd")
        self.assertEqual(by_id["das_erste_hd"]["name"], "Das Erste HD")
        self.assertIn("zdf_hd", by_id)

    def test_discover_channels_needs_no_network(self):
        def fail_if_called(*args, **kwargs):
            raise AssertionError("discover_channels must not hit the network")

        hdplus_de.hdplus_client.fetch_slice = fail_if_called
        self.assertEqual(len(HdPlusProvider().discover_channels()), len(HDPLUS_CHANNELS))

    def test_normalise_channel(self):
        channel = normalise_hdplus_channel("zdf_hd", "ZDF HD")
        self.assertEqual(channel["id"], "hdplus.de.zdf_hd")
        self.assertEqual(channel["hdplus_channel_id"], "zdf_hd")

    def test_channel_from_task(self):
        channel = HdPlusProvider().channel_from_task(ERSTE_TASK)
        self.assertEqual(channel["id"], "hdplus.de.das_erste_hd")

    def test_fetch_maps_programme_fields(self):
        programmes = [
            _programme(
                "Der Zürich-Krimi", "2026-07-18T23:15:00.000Z", 5580,
                sub_name="S1/E6 - Borchert und der Sündenfall",
                fsk=12, categories=["series"], genres=["crime_thriller"],
            ),
        ]
        hdplus_de.hdplus_client.fetch_slice = lambda *a, **kw: _slice_response(programmes)
        channels, result = HdPlusProvider().fetch(dict(ERSTE_TASK, days=1))
        self.assertEqual(channels[0]["id"], "hdplus.de.das_erste_hd")
        programme = result[0]
        self.assertEqual(programme["channel_id"], "hdplus.de.das_erste_hd")
        self.assertEqual(programme["title"], "Der Zürich-Krimi: S1/E6 - Borchert und der Sündenfall")
        self.assertEqual(programme["description"], "")
        self.assertEqual(programme["category"], u"Serie")
        self.assertEqual(programme["rating"], "12")
        self.assertEqual(programme["source_id"], "16589256/EP024012010006")
        # start/stop are naive datetimes and stop == start + duration
        self.assertIsNone(programme["start"].tzinfo)
        self.assertEqual(programme["stop"] - programme["start"], datetime.timedelta(seconds=5580))

    def test_fetch_uses_genre_when_category_has_no_label(self):
        programmes = [_programme("Doku", "2026-07-19T10:00:00.000Z", 1800, categories=["unknown"], genres=["cooking"])]
        hdplus_de.hdplus_client.fetch_slice = lambda *a, **kw: _slice_response(programmes)
        _, result = HdPlusProvider().fetch(dict(ERSTE_TASK, days=1))
        self.assertEqual(result[0]["category"], u"Kochen")

    def test_fetch_deduplicates_overlapping_windows(self):
        # The two per-day windows (00:00 and 12:00) overlap; a programme returned
        # in both must appear only once.
        programmes = [_programme("Tagesschau", "2026-07-19T12:00:00.000Z", 900)]
        calls = {"n": 0}

        def fake_slice(*args, **kwargs):
            calls["n"] += 1
            return _slice_response(programmes)

        hdplus_de.hdplus_client.fetch_slice = fake_slice
        _, result = HdPlusProvider().fetch(dict(ERSTE_TASK, days=1))
        self.assertEqual(calls["n"], 2)  # two windows fetched
        self.assertEqual(len(result), 1)  # but deduplicated to one programme

    def test_fetch_skips_programme_without_duration(self):
        programmes = [_programme("Kein Ende", "2026-07-19T12:00:00.000Z", 0)]
        hdplus_de.hdplus_client.fetch_slice = lambda *a, **kw: _slice_response(programmes)
        _, result = HdPlusProvider().fetch(dict(ERSTE_TASK, days=1))
        self.assertEqual(result, [])

    def test_fetch_raises_for_unknown_channel(self):
        task = {"days": 1, "hdplus_channel_id": "does_not_exist", "source_channel_name": "Unknown"}
        with self.assertRaises(Exception) as ctx:
            HdPlusProvider().fetch(task)
        self.assertIn("nicht gefunden", str(ctx.exception))

    def test_parse_hdplus_utc_converts_from_utc(self):
        # tz-independent: the resulting naive local datetime must represent the
        # same absolute instant as the input UTC timestamp.
        result = _parse_hdplus_utc("2026-07-19T00:00:00.000Z")
        self.assertIsNone(result.tzinfo)
        utc_epoch = calendar.timegm((2026, 7, 19, 0, 0, 0, 0, 0, 0))
        self.assertEqual(int(time.mktime(result.timetuple())), utc_epoch)

    def test_hdplus_client_reports_dns_errors_clearly(self):
        message = HdPlusEpgClient()._build_url_error_message(
            URLError(socket.gaierror(-2, "Name or service not known"))
        )
        self.assertIn("DNS", message)
        self.assertIn("Auflösung", message)
        self.assertIn("Nameserver", message)
        self.assertIn("prüfen", message)

    def test_hdplus_client_reports_ssl_errors_with_clock_hint(self):
        message = HdPlusEpgClient()._build_url_error_message(
            URLError(ssl.SSLError("certificate verify failed"))
        )
        self.assertIn("SSL", message)
        self.assertIn("Datum", message)
        self.assertIn("Uhrzeit", message)
        self.assertIn("prüfen", message)

    def test_hdplus_client_reports_certificate_error_as_ssl_not_generic(self):
        old_urlopen = hdplus_client_module.urllib2.urlopen

        def raise_certificate_error(request, timeout=None):
            raise ssl.CertificateError(
                "hostname 'api-gn-epg.prd.tvengine.hd-plus-cloud.de' doesn't match 'example.com'"
            )

        hdplus_client_module.urllib2.urlopen = raise_certificate_error
        try:
            with self.assertRaises(HdPlusEpgError) as ctx:
                HdPlusEpgClient()._open(object())
        finally:
            hdplus_client_module.urllib2.urlopen = old_urlopen
        message = str(ctx.exception)
        self.assertIn("SSL", message)
        self.assertIn("Hostname-Mismatch", message)

    def test_hdplus_client_reports_timeout_clearly(self):
        client = HdPlusEpgClient(timeout=8)
        message = client._build_url_error_message(URLError("timed out"))
        self.assertIn("8 Sekunden", message)
        self.assertIn("Netzwerkverbindung", message)
        self.assertIn("später", message)

    def test_hdplus_fetch_wraps_client_errors(self):
        def raise_error(*args, **kwargs):
            raise HdPlusEpgError(u"DNS-Auflösung fehlgeschlagen. Bitte prüfen.")

        hdplus_de.hdplus_client.fetch_slice = raise_error
        with self.assertRaises(Exception) as ctx:
            HdPlusProvider().fetch(dict(ERSTE_TASK, days=1))
        message = ensure_text(ctx.exception)
        self.assertIn(u"Auflösung", message)
        self.assertNotIn(u"Ã", message)


if __name__ == "__main__":
    unittest.main()
