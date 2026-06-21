# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import datetime
import socket
import ssl
import unittest

try:
    from urllib2 import URLError
except ImportError:
    from urllib.error import URLError

from Plugins.Extensions.EpgToXml.providers import redbull_tv
from Plugins.Extensions.EpgToXml.providers.redbull_tv import (
    REDBULL_TV_CHANNELS,
    RedBullTvProvider,
    normalise_redbull_channel,
)
from Plugins.Extensions.EpgToXml.redbull_tv_client import RedBullTvEpgClient, RedBullTvEpgError
from Plugins.Extensions.EpgToXml.compat import ensure_text


def _card(title, start, stop, short_description="", long_description="", card_id=""):
    return {
        "id": card_id,
        "title": title,
        "short_description": short_description,
        "long_description": long_description,
        "start_time": start,
        "end_time": stop,
    }


WORLD_OF_RED_BULL_ID = "c81f8686-ab67-4965-ba04-5f6658bb96cc"
WORLD_OF_RED_BULL_TASK = {"redbull_channel_id": WORLD_OF_RED_BULL_ID, "source_channel_name": "World of Red Bull"}


def _sample_guide_response():
    return {
        "cards": [
            _card(
                "DTM: Lausitzring - Rennen 2",
                "2026-06-21T14:53:41.000Z", "2026-06-21T16:31:20.000Z",
                short_description="Kurzbeschreibung", long_description="Lange Beschreibung der Sendung.",
                card_id="rrn:content:live-videos:17a8913d-71b9-406f-998c-29689bfa5d17:de-INT",
            ),
        ],
    }


class RedBullTvProviderTests(unittest.TestCase):
    def setUp(self):
        self.old_fetch_guide = redbull_tv.redbull_tv_client.fetch_guide

    def tearDown(self):
        redbull_tv.redbull_tv_client.fetch_guide = self.old_fetch_guide

    def test_discover_channels_returns_all_nine_channels(self):
        channels = RedBullTvProvider().discover_channels()
        self.assertEqual(len(channels), 9)
        self.assertEqual(len(REDBULL_TV_CHANNELS), 9)
        by_id = {channel["redbull_channel_id"]: channel for channel in channels}
        world = by_id[WORLD_OF_RED_BULL_ID]
        self.assertEqual(world["name"], "World of Red Bull")
        self.assertEqual(world["id"], "redbull.tv." + WORLD_OF_RED_BULL_ID)
        self.assertIn("e0e6dee0-8c39-4de1-9488-72828468efe0", by_id)

    def test_normalise_channel(self):
        channel = normalise_redbull_channel("f4aa4fe4-5ce6-4b1c-a60b-abc6f21f16d0", "Winter")
        self.assertEqual(channel["id"], "redbull.tv.f4aa4fe4-5ce6-4b1c-a60b-abc6f21f16d0")
        self.assertEqual(channel["redbull_channel_id"], "f4aa4fe4-5ce6-4b1c-a60b-abc6f21f16d0")

    def test_channel_from_task(self):
        channel = RedBullTvProvider().channel_from_task(WORLD_OF_RED_BULL_TASK)
        self.assertEqual(channel["id"], "redbull.tv." + WORLD_OF_RED_BULL_ID)

    def test_fetch_maps_programmes_preferring_long_description(self):
        redbull_tv.redbull_tv_client.fetch_guide = lambda *a, **kw: _sample_guide_response()
        channels, programmes = RedBullTvProvider().fetch(WORLD_OF_RED_BULL_TASK)
        self.assertEqual(channels[0]["id"], "redbull.tv." + WORLD_OF_RED_BULL_ID)
        self.assertEqual(len(programmes), 1)
        programme = programmes[0]
        self.assertEqual(programme["title"], "DTM: Lausitzring - Rennen 2")
        self.assertEqual(programme["description"], "Lange Beschreibung der Sendung.")
        self.assertEqual(programme["start"], datetime.datetime(2026, 6, 21, 14, 53, 41))
        self.assertEqual(programme["stop"], datetime.datetime(2026, 6, 21, 16, 31, 20))
        self.assertEqual(programme["source_id"], "rrn:content:live-videos:17a8913d-71b9-406f-998c-29689bfa5d17:de-INT")

    def test_fetch_falls_back_to_short_description(self):
        response = {
            "cards": [_card(
                "Test", "2026-06-21T14:53:41.000Z", "2026-06-21T16:31:20.000Z",
                short_description="Kurzfassung", long_description="",
            )],
        }
        redbull_tv.redbull_tv_client.fetch_guide = lambda *a, **kw: response
        _, programmes = RedBullTvProvider().fetch(WORLD_OF_RED_BULL_TASK)
        self.assertEqual(programmes[0]["description"], "Kurzfassung")

    def test_fetch_raises_on_empty_cards(self):
        redbull_tv.redbull_tv_client.fetch_guide = lambda *a, **kw: {"cards": []}
        with self.assertRaises(Exception) as ctx:
            RedBullTvProvider().fetch(WORLD_OF_RED_BULL_TASK)
        self.assertIn("keine Sendungen", str(ctx.exception))

    def test_parses_z_suffixed_timestamp_with_milliseconds(self):
        from Plugins.Extensions.EpgToXml.providers.redbull_tv import _parse_redbull_iso8601
        self.assertEqual(
            _parse_redbull_iso8601("2026-06-21T14:30:54.000Z"),
            datetime.datetime(2026, 6, 21, 14, 30, 54),
        )

    def test_redbull_client_reports_dns_errors_clearly(self):
        message = RedBullTvEpgClient()._build_url_error_message(
            URLError(socket.gaierror(-2, "Name or service not known"))
        )
        self.assertIn("DNS", message)
        self.assertIn("Auflösung", message)
        self.assertIn("Nameserver", message)
        self.assertIn("prüfen", message)

    def test_redbull_client_reports_ssl_errors_with_clock_hint(self):
        message = RedBullTvEpgClient()._build_url_error_message(
            URLError(ssl.SSLError("certificate verify failed"))
        )
        self.assertIn("SSL", message)
        self.assertIn("Datum", message)
        self.assertIn("Uhrzeit", message)
        self.assertIn("prüfen", message)

    def test_redbull_client_reports_timeout_clearly(self):
        client = RedBullTvEpgClient(timeout=8)
        message = client._build_url_error_message(URLError("timed out"))
        self.assertIn("8 Sekunden", message)
        self.assertIn("Netzwerkverbindung", message)
        self.assertIn("später", message)

    def test_redbull_fetch_wraps_client_errors(self):
        def raise_error(*args, **kwargs):
            raise RedBullTvEpgError(u"DNS-Auflösung fehlgeschlagen. Bitte prüfen.")

        redbull_tv.redbull_tv_client.fetch_guide = raise_error
        with self.assertRaises(Exception) as ctx:
            RedBullTvProvider().fetch(WORLD_OF_RED_BULL_TASK)
        message = ensure_text(ctx.exception)
        self.assertIn(u"Auflösung", message)
        self.assertNotIn(u"Ã", message)


if __name__ == "__main__":
    unittest.main()
