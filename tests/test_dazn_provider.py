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

from Plugins.Extensions.EpgToXml import dazn_client as dazn_client_module
from Plugins.Extensions.EpgToXml.providers import dazn_de
from Plugins.Extensions.EpgToXml.providers.dazn_de import DaznDeProvider, normalise_dazn_channel
from Plugins.Extensions.EpgToXml.dazn_client import DaznEpgClient, DaznEpgError
from Plugins.Extensions.EpgToXml.compat import ensure_text


def _sample_rail_response():
    return {
        "Tiles": [
            {
                "Title": "DAZN 1",
                "AssetId": "bj5o60qt6uoe1clfdsev239pr",
                "LinearSchedule": {
                    "Now": {
                        "Title": "Sendepause",
                        "EpisodeTitle": "",
                        "Genre": [{"name": "Special"}],
                        "Start": "2026-06-18T22:00:00Z",
                        "End": "2026-06-19T06:00:00Z",
                        "EventYear": "2005",
                    },
                    "Next": {
                        "Title": "3.Liga-Highlightshow",
                        "EpisodeTitle": "34. Spieltag",
                        "Genre": [{"name": "Soccer"}],
                        "Start": "2026-06-19T06:00:00Z",
                        "End": "2026-06-19T07:00:00Z",
                        "EventYear": "2026",
                    },
                    "Later": [
                        {
                            "Title": "Best of DAZN - Highlights",
                            "EpisodeTitle": "",
                            "Genre": [{"name": "Entertainment"}],
                            "Start": "2026-06-19T07:00:00Z",
                            "End": "2026-06-19T07:45:00Z",
                            "EventYear": "2020",
                        },
                        {
                            "Title": "Spanish Copa del Rey Soccer",
                            "EpisodeTitle": "Atlético Madrid - Real Sociedad",
                            "Genre": [{"name": "Soccer"}],
                            "Start": "2026-06-19T07:45:00Z",
                            "End": "2026-06-19T09:30:00Z",
                            "EventYear": "2026",
                        },
                    ],
                },
            },
            {
                "Title": "Rally TV",
                "AssetId": "rally-tv-asset",
                "LinearSchedule": None,
            },
            {
                "Title": "DFB.TV",
                "AssetId": "dfbtv-asset",
                "LinearSchedule": {
                    "Now": None,
                    "Next": None,
                    "Later": [
                        {
                            "Title": "3. Liga",
                            "EpisodeTitle": "",
                            "Genre": [{"name": "Soccer"}],
                            "Start": "2026-06-19T10:00:00Z",
                            "End": "2026-06-19T12:00:00Z",
                            "EventYear": "2026",
                        },
                    ],
                },
            },
        ]
    }


class DaznProviderTests(unittest.TestCase):
    def setUp(self):
        self.old_fetch_live_schedule = dazn_de.dazn_client.fetch_live_schedule

    def tearDown(self):
        dazn_de.dazn_client.fetch_live_schedule = self.old_fetch_live_schedule

    def test_discovers_channels_skips_tiles_without_schedule(self):
        dazn_de.dazn_client.fetch_live_schedule = lambda rail_id=None: _sample_rail_response()
        channels = DaznDeProvider().discover_channels()
        ids = [channel["id"] for channel in channels]
        self.assertIn("dazn.de.dazn-1", ids)
        self.assertIn("dazn.de.dfb-tv", ids)
        self.assertEqual(len(channels), 2)

    def test_discover_channels_reports_empty_response(self):
        dazn_de.dazn_client.fetch_live_schedule = lambda rail_id=None: {"Tiles": []}
        with self.assertRaises(Exception) as ctx:
            DaznDeProvider().discover_channels()
        self.assertIn("keine Senderliste", str(ctx.exception))

    def test_normalise_channel_builds_stable_id(self):
        channel = normalise_dazn_channel({"AssetId": "bj5o60qt6uoe1clfdsev239pr", "Title": "DAZN 1"})
        self.assertEqual(channel["id"], "dazn.de.dazn-1")
        self.assertEqual(channel["dazn_asset_id"], "bj5o60qt6uoe1clfdsev239pr")

    def test_fetch_combines_now_next_later_in_order(self):
        dazn_de.dazn_client.fetch_live_schedule = lambda rail_id=None: _sample_rail_response()
        task = {
            "days": 3,
            "source_channel_name": "DAZN 1",
            "dazn_asset_id": "bj5o60qt6uoe1clfdsev239pr",
        }
        channels, programmes = DaznDeProvider().fetch(task)
        self.assertEqual(channels[0]["id"], "dazn.de.dazn-1")
        self.assertEqual(len(programmes), 4)
        self.assertEqual(programmes[0]["title"], "Sendepause")
        self.assertEqual(programmes[1]["title"], "3.Liga-Highlightshow: 34. Spieltag")
        self.assertEqual(programmes[2]["title"], "Best of DAZN - Highlights")
        self.assertEqual(programmes[3]["title"], "Spanish Copa del Rey Soccer: Atlético Madrid - Real Sociedad")
        self.assertEqual(programmes[0]["start"], datetime.datetime(2026, 6, 18, 22, 0, 0))
        self.assertEqual(programmes[0]["stop"], datetime.datetime(2026, 6, 19, 6, 0, 0))
        self.assertEqual(programmes[0]["category"], "Special")
        for programme in programmes:
            self.assertEqual(programme["channel_id"], "dazn.de.dazn-1")

    def test_fetch_skips_missing_now_and_next(self):
        dazn_de.dazn_client.fetch_live_schedule = lambda rail_id=None: _sample_rail_response()
        task = {
            "days": 3,
            "source_channel_name": "DFB.TV",
            "dazn_asset_id": "dfbtv-asset",
        }
        channels, programmes = DaznDeProvider().fetch(task)
        self.assertEqual(len(programmes), 1)
        self.assertEqual(programmes[0]["title"], "3. Liga")

    def test_fetch_raises_for_unknown_channel(self):
        dazn_de.dazn_client.fetch_live_schedule = lambda rail_id=None: _sample_rail_response()
        task = {"days": 3, "source_channel_name": "Unknown", "dazn_asset_id": "does-not-exist"}
        with self.assertRaises(Exception) as ctx:
            DaznDeProvider().fetch(task)
        self.assertIn("nicht gefunden", str(ctx.exception))

    def test_dazn_client_reports_dns_errors_clearly(self):
        message = DaznEpgClient()._build_url_error_message(
            URLError(socket.gaierror(-2, "Name or service not known"))
        )
        self.assertIn("DNS", message)
        self.assertIn("Auflösung", message)
        self.assertIn("Nameserver", message)
        self.assertIn("prüfen", message)

    def test_dazn_client_reports_ssl_errors_with_clock_hint(self):
        message = DaznEpgClient()._build_url_error_message(
            URLError(ssl.SSLError("certificate verify failed"))
        )
        self.assertIn("SSL", message)
        self.assertIn("Datum", message)
        self.assertIn("Uhrzeit", message)
        self.assertIn("prüfen", message)

    def test_dazn_client_reports_certificate_error_as_ssl_not_generic(self):
        old_urlopen = dazn_client_module.urllib2.urlopen

        def raise_certificate_error(request, timeout=None):
            raise ssl.CertificateError("hostname 'rail-router.discovery.indazn.com' doesn't match 'example.com'")

        dazn_client_module.urllib2.urlopen = raise_certificate_error
        try:
            with self.assertRaises(DaznEpgError) as ctx:
                DaznEpgClient()._open(object())
        finally:
            dazn_client_module.urllib2.urlopen = old_urlopen
        message = str(ctx.exception)
        self.assertIn("SSL", message)
        self.assertIn("Hostname-Mismatch", message)

    def test_dazn_client_reports_timeout_clearly(self):
        client = DaznEpgClient(timeout=8)
        message = client._build_url_error_message(URLError("timed out"))
        self.assertIn("8 Sekunden", message)
        self.assertIn("Netzwerkverbindung", message)
        self.assertIn("später", message)

    def test_dazn_fetch_wraps_client_errors(self):
        def raise_error(rail_id=None):
            raise DaznEpgError(u"DNS-Auflösung fehlgeschlagen. Bitte prüfen.")

        dazn_de.dazn_client.fetch_live_schedule = raise_error
        with self.assertRaises(Exception) as ctx:
            DaznDeProvider().discover_channels()
        message = ensure_text(ctx.exception)
        self.assertIn(u"Auflösung", message)
        self.assertNotIn(u"Ã", message)


if __name__ == "__main__":
    unittest.main()
