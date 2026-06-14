import datetime
import socket
import ssl
import unittest

try:
    from urllib2 import URLError
except ImportError:
    from urllib.error import URLError

from Plugins.Extensions.EpgToXml.providers import sky_de
from Plugins.Extensions.EpgToXml.providers.sky_de import SkyDeProvider, normalise_sky_channel
from Plugins.Extensions.EpgToXml.sky_client import SkyEpgClient, SkyEpgError
from Plugins.Extensions.EpgToXml.compat import ensure_text, repair_mojibake

try:
    unichr
except NameError:
    unichr = chr


class SkyProviderTests(unittest.TestCase):
    def setUp(self):
        self.old_fetch_days = sky_de.sky_client.fetch_days
        self.old_list_channels = sky_de.sky_client.list_channels

    def tearDown(self):
        sky_de.sky_client.fetch_days = self.old_fetch_days
        sky_de.sky_client.list_channels = self.old_list_channels

    def test_normalises_broadcasts(self):
        provider = SkyDeProvider()
        day = datetime.datetime(2026, 6, 12)
        channel = provider.default_channels[0]
        programmes = [provider._normalise_programme(day, channel, {
            "bst": "01:00",
            "et": "WM-Live",
            "ec": "Fußball",
            "len": 60,
            "cop": "D",
            "yop": 2026,
            "fsk": "ab 0 Jahre",
            "ei": 146452481,
            "bid": 18116310,
        })]
        self.assertEqual(programmes[0]["channel_id"], "sky.de.dfb-tv")
        self.assertEqual(programmes[0]["title"], "WM-Live")
        self.assertEqual(programmes[0]["category"], "Fußball")
        self.assertEqual(programmes[0]["start"].hour, 1)
        self.assertEqual(programmes[0]["stop"].hour, 2)

    def test_discovers_channels_from_sky_list(self):
        sky_de.sky_client.list_channels = lambda channel_slug=None: {
            "cl": [
                {"ci": 659, "cn": "DAZN 1 HD", "cu": "/tvguide/dazn-1-hd-c659", "clu": "/logo.png"},
                {"ci": 1236, "cn": "DFB.TV", "cu": "/tvguide/dfbtv-c1236", "clu": "/dfb.png"},
            ]
        }
        channels = SkyDeProvider().discover_channels()
        ids = [channel["id"] for channel in channels]
        self.assertIn("sky.de.dazn-1-hd", ids)
        self.assertIn("sky.de.dfb-tv", ids)

    def test_discover_channels_reports_empty_sky_response(self):
        sky_de.sky_client.list_channels = lambda channel_slug=None: {"cl": []}
        with self.assertRaises(Exception) as ctx:
            SkyDeProvider().discover_channels()
        self.assertIn("keine Senderliste", str(ctx.exception))

    def test_normalise_channel_keeps_dfb_compat_id(self):
        channel = normalise_sky_channel({"ci": 1236, "cn": "DFB.TV", "cu": "/tvguide/dfbtv-c1236"})
        self.assertEqual(channel["id"], "sky.de.dfb-tv")
        self.assertEqual(channel["sky_channel_slug"], "dfbtv-c1236")

    def test_fetch_uses_sky_client_fields_from_task(self):
        calls = []

        def fake_fetch_days(channel_id=None, channel_slug=None, start_offset=None, num_days=None):
            calls.append((channel_id, channel_slug, start_offset, num_days))
            return {
                "days": [{
                    "timestamp": 1781215200000,
                    "el": [{"bst": "01:00", "et": "A", "len": 30, "ci": channel_id}],
                }]
            }

        sky_de.sky_client.fetch_days = fake_fetch_days
        task = {
            "days": 3,
            "source_channel_name": "DAZN 1 HD",
            "source_channel_id": "sky.de.dazn-1-hd",
            "sky_channel_id": 659,
            "sky_channel_slug": "dazn-1-hd-c659",
        }
        channels, programmes = SkyDeProvider().fetch(task)
        self.assertEqual(calls, [(659, "dazn-1-hd-c659", 0, 3)])
        self.assertEqual(channels[0]["id"], "sky.de.dazn-1-hd")
        self.assertEqual(programmes[0]["channel_id"], "sky.de.dazn-1-hd")
        self.assertEqual(programmes[0]["title"], "A")

    def test_sky_client_reports_dns_errors_clearly(self):
        message = SkyEpgClient()._build_url_error_message(
            URLError(socket.gaierror(-2, "Name or service not known"))
        )
        self.assertIn("DNS", message)
        self.assertIn("Auflösung", message)
        self.assertIn("Nameserver", message)
        self.assertIn("prüfen", message)

    def test_sky_client_reports_ssl_errors_with_clock_hint(self):
        message = SkyEpgClient()._build_url_error_message(
            URLError(ssl.SSLError("certificate verify failed"))
        )
        self.assertIn("SSL", message)
        self.assertIn("Datum", message)
        self.assertIn("Uhrzeit", message)
        self.assertIn("prüfen", message)

    def test_sky_client_reports_timeout_clearly(self):
        client = SkyEpgClient(timeout=8)
        message = client._build_url_error_message(URLError("timed out"))
        self.assertIn("8 Sekunden", message)
        self.assertIn("Netzwerkverbindung", message)
        self.assertIn("später", message)

    def test_sky_client_error_messages_do_not_contain_mojibake(self):
        client = SkyEpgClient(timeout=8)
        messages = [
            client._build_url_error_message(URLError(socket.gaierror(-2, "Name or service not known"))),
            client._build_url_error_message(URLError(ssl.SSLError("certificate verify failed"))),
            client._build_url_error_message(URLError("timed out")),
            client._build_url_error_message(URLError("generic network problem")),
        ]
        for message in messages:
            self.assertNotIn("Ã", message)
            self.assertNotIn("Â", message)

    def test_exception_text_preserves_umlauts(self):
        original = SkyEpgError(u"DNS-Aufl\u00f6sung fehlgeschlagen. Bitte pr\u00fcfen.")
        wrapped = RuntimeError(u"Sky.de ist gerade nicht erreichbar: " + ensure_text(original))
        message = ensure_text(wrapped)
        self.assertIn(u"Aufl\u00f6sung", message)
        self.assertIn(u"pr\u00fcfen", message)
        self.assertNotIn(u"Ã", message)

    def test_repair_mojibake_repairs_single_utf8_latin1_mixup(self):
        message = repair_mojibake(u"DNS-AuflÃ¶sung prÃ¼fen")
        self.assertEqual(message, u"DNS-Aufl\u00f6sung pr\u00fcfen")

    def test_repair_mojibake_repairs_mixed_correct_and_broken_text(self):
        message = repair_mojibake(
            u"keine g\u00fcltige Senderliste geliefert: DNS-Aufl" +
            unichr(0xc3) + unichr(0xb6) + u"sung pr" +
            unichr(0xc3) + unichr(0xbc) + u"fen"
        )
        self.assertEqual(
            message,
            u"keine g\u00fcltige Senderliste geliefert: DNS-Aufl\u00f6sung pr\u00fcfen",
        )


if __name__ == "__main__":
    unittest.main()
