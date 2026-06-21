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

from Plugins.Extensions.EpgToXml.providers import zdf_de
from Plugins.Extensions.EpgToXml.providers.zdf_de import ZdfDeProvider, normalise_zdf_channel
from Plugins.Extensions.EpgToXml.zdf_client import ZdfEpgClient, ZdfEpgError
from Plugins.Extensions.EpgToXml.compat import ensure_text


def _broadcast(title, start, stop, text="", subheadline=None, canonical=""):
    return {
        "title": title,
        "subheadline": subheadline,
        "text": text,
        "airtimeBegin": start,
        "airtimeEnd": stop,
        "video": {"canonical": canonical},
    }


def _sample_epg_response():
    return {
        "data": {
            "epg": [
                {
                    "broadcaster": {"id": "ZDF", "title": "ZDF"},
                    "broadcasts": [
                        _broadcast(
                            "heute journal", "2026-06-21T22:15:00+02:00", "2026-06-21T22:45:00+02:00",
                            text="Die Nachrichten des Tages.", canonical="heute-journal-100",
                        ),
                    ],
                },
                {
                    "broadcaster": {"id": "ZDFneo", "title": "ZDFneo"},
                    "broadcasts": [
                        _broadcast(
                            "Krimi", "2026-06-21T20:15:00+02:00", "2026-06-21T21:45:00+02:00",
                            text="Ein spannender Krimi.<br/>Mit Spannung.",
                        ),
                    ],
                },
            ],
        },
    }


class ZdfProviderTests(unittest.TestCase):
    def setUp(self):
        self.old_fetch_epg = zdf_de.zdf_client.fetch_epg

    def tearDown(self):
        zdf_de.zdf_client.fetch_epg = self.old_fetch_epg

    def test_discover_channels_builds_channels_from_response(self):
        zdf_de.zdf_client.fetch_epg = lambda *a, **kw: _sample_epg_response()
        channels = ZdfDeProvider().discover_channels()
        by_id = {channel["zdf_channel_id"]: channel for channel in channels}
        self.assertEqual(by_id["ZDF"]["name"], "ZDF")
        self.assertEqual(by_id["ZDF"]["id"], "zdf.de.ZDF")
        self.assertFalse(by_id["ZDF"].get("variants"))
        self.assertIn("ZDFneo", by_id)

    def test_discover_channels_reports_empty_response(self):
        zdf_de.zdf_client.fetch_epg = lambda *a, **kw: {"data": {"epg": []}}
        with self.assertRaises(Exception) as ctx:
            ZdfDeProvider().discover_channels()
        self.assertIn("keine Senderliste", str(ctx.exception))

    def test_normalise_channel(self):
        channel = normalise_zdf_channel("ZDFinfo", "ZDFinfo")
        self.assertEqual(channel["id"], "zdf.de.ZDFinfo")
        self.assertEqual(channel["zdf_channel_id"], "ZDFinfo")
        self.assertNotIn("variants", channel)

    def test_channel_from_task(self):
        task = {"zdf_channel_id": "ZDF", "source_channel_name": "ZDF"}
        channel = ZdfDeProvider().channel_from_task(task)
        self.assertEqual(channel["id"], "zdf.de.ZDF")
        self.assertEqual(channel["zdf_channel_id"], "ZDF")

    def test_fetch_maps_programmes_and_strips_html_description(self):
        zdf_de.zdf_client.fetch_epg = lambda *a, **kw: _sample_epg_response()
        task = {"days": 1, "zdf_channel_id": "ZDFneo", "source_channel_name": "ZDFneo"}
        channels, programmes = ZdfDeProvider().fetch(task)
        self.assertEqual(channels[0]["id"], "zdf.de.ZDFneo")
        self.assertEqual(len(programmes), 1)
        programme = programmes[0]
        self.assertEqual(programme["title"], "Krimi")
        self.assertEqual(programme["description"], "Ein spannender Krimi. Mit Spannung.")
        self.assertEqual(programme["start"], datetime.datetime(2026, 6, 21, 20, 15, 0))
        self.assertEqual(programme["stop"], datetime.datetime(2026, 6, 21, 21, 45, 0))

    def test_fetch_populates_source_id_from_video_canonical(self):
        zdf_de.zdf_client.fetch_epg = lambda *a, **kw: _sample_epg_response()
        task = {"days": 1, "zdf_channel_id": "ZDF", "source_channel_name": "ZDF"}
        _, programmes = ZdfDeProvider().fetch(task)
        self.assertEqual(programmes[0]["source_id"], "heute-journal-100")

    def test_fetch_raises_for_unknown_channel(self):
        zdf_de.zdf_client.fetch_epg = lambda *a, **kw: _sample_epg_response()
        task = {"days": 1, "zdf_channel_id": "unknown", "source_channel_name": "Unknown"}
        with self.assertRaises(Exception) as ctx:
            ZdfDeProvider().fetch(task)
        self.assertIn("nicht gefunden", str(ctx.exception))

    def test_parses_offset_timestamps(self):
        from Plugins.Extensions.EpgToXml.providers.zdf_de import _parse_zdf_iso8601
        self.assertEqual(
            _parse_zdf_iso8601("2026-06-21T05:30:51+02:00"),
            datetime.datetime(2026, 6, 21, 5, 30, 51),
        )

    def test_zdf_client_reports_dns_errors_clearly(self):
        message = ZdfEpgClient()._build_url_error_message(
            URLError(socket.gaierror(-2, "Name or service not known"))
        )
        self.assertIn("DNS", message)
        self.assertIn("Auflösung", message)
        self.assertIn("Nameserver", message)
        self.assertIn("prüfen", message)

    def test_zdf_client_reports_ssl_errors_with_clock_hint(self):
        message = ZdfEpgClient()._build_url_error_message(
            URLError(ssl.SSLError("certificate verify failed"))
        )
        self.assertIn("SSL", message)
        self.assertIn("Datum", message)
        self.assertIn("Uhrzeit", message)
        self.assertIn("prüfen", message)

    def test_zdf_client_reports_timeout_clearly(self):
        client = ZdfEpgClient(timeout=8)
        message = client._build_url_error_message(URLError("timed out"))
        self.assertIn("8 Sekunden", message)
        self.assertIn("Netzwerkverbindung", message)
        self.assertIn("später", message)

    def test_zdf_fetch_wraps_client_errors(self):
        def raise_error(*args, **kwargs):
            raise ZdfEpgError(u"DNS-Auflösung fehlgeschlagen. Bitte prüfen.")

        zdf_de.zdf_client.fetch_epg = raise_error
        with self.assertRaises(Exception) as ctx:
            ZdfDeProvider().discover_channels()
        message = ensure_text(ctx.exception)
        self.assertIn(u"Auflösung", message)
        self.assertNotIn(u"Ã", message)


if __name__ == "__main__":
    unittest.main()
