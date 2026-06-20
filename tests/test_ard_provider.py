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

from Plugins.Extensions.EpgToXml.providers import ard_de
from Plugins.Extensions.EpgToXml.providers.ard_de import ArdDeProvider, normalise_ard_channel, normalise_ard_variant
from Plugins.Extensions.EpgToXml.ard_client import ArdEpgClient, ArdEpgError
from Plugins.Extensions.EpgToXml.compat import ensure_text


def _epg_entry(title, subline, start, stop, channel_id, channel_name, main_channel_id):
    return {
        "coreTitle": title,
        "coreSubline": subline,
        "broadcastedOn": start,
        "broadcastEnd": stop,
        "channel": {"id": channel_id, "name": channel_name, "main_channel_id": main_channel_id},
    }


def _sample_day_response():
    return {
        "channels": [
            {
                "id": "daserste",
                "trackingPiano": {"widget_title": "Das Erste"},
                "timeSlots": [[
                    _epg_entry(
                        "Tagesschau", "", "2026-06-20T20:00:00+02:00", "2026-06-20T20:15:00+02:00",
                        "daserste", "Das Erste", "daserste",
                    ),
                ]],
            },
            {
                "id": "br",
                "trackingPiano": {"widget_title": "BR"},
                "timeSlots": [[
                    _epg_entry(
                        "Rundschau Nord", "", "2026-06-20T19:00:00+02:00", "2026-06-20T19:30:00+02:00",
                        "brnord", "BR Nord", "br",
                    ),
                    _epg_entry(
                        "Rundschau Süd", "", "2026-06-20T19:00:00+02:00", "2026-06-20T19:30:00+02:00",
                        "brsued", "BR Süd", "br",
                    ),
                ]],
            },
        ]
    }


class ArdProviderTests(unittest.TestCase):
    def setUp(self):
        self.old_fetch_day = ard_de.ard_client.fetch_day

    def tearDown(self):
        ard_de.ard_client.fetch_day = self.old_fetch_day

    def test_discover_channels_builds_generic_name_without_variants(self):
        ard_de.ard_client.fetch_day = lambda day: _sample_day_response()
        channels = ArdDeProvider().discover_channels()
        by_id = {channel["ard_channel_id"]: channel for channel in channels}
        self.assertEqual(by_id["daserste"]["name"], "Das Erste")
        self.assertFalse(by_id["daserste"].get("variants"))

    def test_discover_channels_collects_regional_variants(self):
        ard_de.ard_client.fetch_day = lambda day: _sample_day_response()
        channels = ArdDeProvider().discover_channels()
        by_id = {channel["ard_channel_id"]: channel for channel in channels}
        br = by_id["br"]
        self.assertEqual(br["name"], "BR")
        self.assertEqual(br["id"], "ard.de.br")
        variant_names = sorted(variant["name"] for variant in br["variants"])
        self.assertEqual(variant_names, ["BR Nord", "BR Süd"])
        variant_ids = sorted(variant["ard_variant_id"] for variant in br["variants"])
        self.assertEqual(variant_ids, ["brnord", "brsued"])

    def test_discover_channels_reports_empty_response(self):
        ard_de.ard_client.fetch_day = lambda day: {"channels": []}
        with self.assertRaises(Exception) as ctx:
            ArdDeProvider().discover_channels()
        self.assertIn("keine Senderliste", str(ctx.exception))

    def test_normalise_channel_and_variant_ids(self):
        channel = normalise_ard_channel("br", "BR")
        self.assertEqual(channel["id"], "ard.de.br")
        self.assertEqual(channel["ard_variant_id"], "")
        variant = normalise_ard_variant("br", "brnord", "BR Nord")
        self.assertEqual(variant["id"], "ard.de.brnord")
        self.assertEqual(variant["ard_channel_id"], "br")
        self.assertEqual(variant["ard_variant_id"], "brnord")

    def test_channel_from_task_without_variant(self):
        task = {"ard_channel_id": "daserste", "ard_variant_id": "", "source_channel_name": "Das Erste"}
        channel = ArdDeProvider().channel_from_task(task)
        self.assertEqual(channel["id"], "ard.de.daserste")
        self.assertEqual(channel["ard_variant_id"], "")

    def test_channel_from_task_with_variant(self):
        task = {"ard_channel_id": "br", "ard_variant_id": "brnord", "source_channel_name": "BR Nord"}
        channel = ArdDeProvider().channel_from_task(task)
        self.assertEqual(channel["id"], "ard.de.brnord")
        self.assertEqual(channel["ard_variant_id"], "brnord")

    def test_fetch_without_variant_uses_main_channel_entries_only(self):
        ard_de.ard_client.fetch_day = lambda day: _sample_day_response()
        task = {"days": 1, "ard_channel_id": "daserste", "ard_variant_id": "", "source_channel_name": "Das Erste"}
        channels, programmes = ArdDeProvider().fetch(task)
        self.assertEqual(channels[0]["id"], "ard.de.daserste")
        self.assertEqual(len(programmes), 1)
        self.assertEqual(programmes[0]["title"], "Tagesschau")
        self.assertEqual(programmes[0]["start"], datetime.datetime(2026, 6, 20, 20, 0, 0))
        self.assertEqual(programmes[0]["stop"], datetime.datetime(2026, 6, 20, 20, 15, 0))

    def test_fetch_with_variant_filters_to_matching_region_only(self):
        ard_de.ard_client.fetch_day = lambda day: _sample_day_response()
        task = {"days": 1, "ard_channel_id": "br", "ard_variant_id": "brnord", "source_channel_name": "BR Nord"}
        channels, programmes = ArdDeProvider().fetch(task)
        self.assertEqual(channels[0]["id"], "ard.de.brnord")
        self.assertEqual(len(programmes), 1)
        self.assertEqual(programmes[0]["title"], "Rundschau Nord")
        for programme in programmes:
            self.assertEqual(programme["channel_id"], "ard.de.brnord")

    def test_fetch_raises_for_unknown_channel(self):
        ard_de.ard_client.fetch_day = lambda day: _sample_day_response()
        task = {"days": 1, "ard_channel_id": "unknown", "ard_variant_id": "", "source_channel_name": "Unknown"}
        with self.assertRaises(Exception) as ctx:
            ArdDeProvider().fetch(task)
        self.assertIn("nicht gefunden", str(ctx.exception))

    def test_parses_offset_timestamps(self):
        from Plugins.Extensions.EpgToXml.providers.ard_de import _parse_local_iso8601
        self.assertEqual(
            _parse_local_iso8601("2026-06-20T05:30:51+02:00"),
            datetime.datetime(2026, 6, 20, 5, 30, 51),
        )

    def test_ard_client_reports_dns_errors_clearly(self):
        message = ArdEpgClient()._build_url_error_message(
            URLError(socket.gaierror(-2, "Name or service not known"))
        )
        self.assertIn("DNS", message)
        self.assertIn("Auflösung", message)
        self.assertIn("Nameserver", message)
        self.assertIn("prüfen", message)

    def test_ard_client_reports_ssl_errors_with_clock_hint(self):
        message = ArdEpgClient()._build_url_error_message(
            URLError(ssl.SSLError("certificate verify failed"))
        )
        self.assertIn("SSL", message)
        self.assertIn("Datum", message)
        self.assertIn("Uhrzeit", message)
        self.assertIn("prüfen", message)

    def test_ard_client_reports_timeout_clearly(self):
        client = ArdEpgClient(timeout=8)
        message = client._build_url_error_message(URLError("timed out"))
        self.assertIn("8 Sekunden", message)
        self.assertIn("Netzwerkverbindung", message)
        self.assertIn("später", message)

    def test_ard_fetch_wraps_client_errors(self):
        def raise_error(day):
            raise ArdEpgError(u"DNS-Auflösung fehlgeschlagen. Bitte prüfen.")

        ard_de.ard_client.fetch_day = raise_error
        with self.assertRaises(Exception) as ctx:
            ArdDeProvider().discover_channels()
        message = ensure_text(ctx.exception)
        self.assertIn(u"Auflösung", message)
        self.assertNotIn(u"Ã", message)


if __name__ == "__main__":
    unittest.main()
