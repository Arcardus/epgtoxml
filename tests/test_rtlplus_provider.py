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

from Plugins.Extensions.EpgToXml.providers import rtl_plus
from Plugins.Extensions.EpgToXml.providers.rtl_plus import (
    RtlPlusDeProvider,
    _decode_modal_id,
    _parse_rtlplus_iso8601,
    normalise_rtlplus_channel,
)
from Plugins.Extensions.EpgToXml.rtlplus_client import RtlPlusEpgClient, RtlPlusEpgError
from Plugins.Extensions.EpgToXml.compat import ensure_text


RTL_MODAL_ID = "cnRsZGVfcnRsKzQ2NTg1NSsyMDI2LTA2LTIw"  # rtlde_rtl+465855+2026-06-20


def _epg_box(title, start, stop, extra_title="", modal_id=""):
    box = {
        "start": {"date": start, "title": start[11:16]},
        "end": {"date": stop, "title": stop[11:16]},
        "title": title,
        "extraTitle": extra_title,
    }
    if modal_id:
        box["action"] = {"target": {"value_modal": {"id": modal_id}}}
    return box


def _grid_response():
    return {
        "content": {
            "items": [
                {
                    "itemContent": {
                        "channel": {"id": "rtlde_rtl", "title": "RTL HD"},
                        "epgBox": [
                            _epg_box(
                                "Punkt 12", "2026-06-21T12:00:00+02:00", "2026-06-21T13:00:00+02:00",
                                modal_id=RTL_MODAL_ID,
                            ),
                        ],
                    },
                },
                {
                    "itemContent": {
                        "channel": {"id": "rtlde_vox", "title": "VOX HD"},
                        "epgBox": [
                            _epg_box("Hot oder Schrott", "2026-06-21T20:15:00+02:00", "2026-06-21T21:15:00+02:00"),
                        ],
                    },
                },
            ],
        },
    }


def _modal_response(description="Volltextbeschreibung.", extra_details="Magazin"):
    return {
        "blocks": [
            {
                "content": {
                    "items": [
                        {"itemContent": {"description": description, "extraDetails": extra_details}},
                    ],
                },
            },
        ],
    }


RTL_TASK = {"rtlplus_channel_id": "rtlde_rtl", "source_channel_name": "RTL HD"}
VOX_TASK = {"rtlplus_channel_id": "rtlde_vox", "source_channel_name": "VOX HD"}


class RtlPlusProviderTests(unittest.TestCase):
    def setUp(self):
        self.old_fetch_day = rtl_plus.rtlplus_client.fetch_day
        self.old_fetch_modal = rtl_plus.rtlplus_client.fetch_modal

    def tearDown(self):
        rtl_plus.rtlplus_client.fetch_day = self.old_fetch_day
        rtl_plus.rtlplus_client.fetch_modal = self.old_fetch_modal

    def test_discover_channels_builds_channels_from_response(self):
        rtl_plus.rtlplus_client.fetch_day = lambda *a, **kw: _grid_response()
        channels = RtlPlusDeProvider().discover_channels()
        by_id = {channel["rtlplus_channel_id"]: channel for channel in channels}
        self.assertEqual(by_id["rtlde_rtl"]["name"], "RTL HD")
        self.assertEqual(by_id["rtlde_rtl"]["id"], "rtlplus.de.rtlde_rtl")
        self.assertIn("rtlde_vox", by_id)

    def test_discover_channels_reports_empty_response(self):
        rtl_plus.rtlplus_client.fetch_day = lambda *a, **kw: {"content": {"items": []}}
        with self.assertRaises(Exception) as ctx:
            RtlPlusDeProvider().discover_channels()
        self.assertIn("keine Senderliste", str(ctx.exception))

    def test_normalise_channel(self):
        channel = normalise_rtlplus_channel("rtlde_ntv", "ntv HD")
        self.assertEqual(channel["id"], "rtlplus.de.rtlde_ntv")
        self.assertEqual(channel["rtlplus_channel_id"], "rtlde_ntv")

    def test_channel_from_task(self):
        channel = RtlPlusDeProvider().channel_from_task(RTL_TASK)
        self.assertEqual(channel["id"], "rtlplus.de.rtlde_rtl")

    def test_fetch_maps_programmes_with_description_from_modal(self):
        rtl_plus.rtlplus_client.fetch_day = lambda *a, **kw: _grid_response()
        rtl_plus.rtlplus_client.fetch_modal = lambda *a, **kw: _modal_response()
        task = dict(RTL_TASK, days=1)
        channels, programmes = RtlPlusDeProvider().fetch(task)
        self.assertEqual(channels[0]["id"], "rtlplus.de.rtlde_rtl")
        self.assertEqual(len(programmes), 1)
        programme = programmes[0]
        self.assertEqual(programme["title"], "Punkt 12")
        self.assertEqual(programme["description"], "Volltextbeschreibung.")
        self.assertEqual(programme["category"], "Magazin")
        self.assertEqual(programme["start"], datetime.datetime(2026, 6, 21, 12, 0, 0))
        self.assertEqual(programme["stop"], datetime.datetime(2026, 6, 21, 13, 0, 0))
        self.assertEqual(programme["source_id"], "465855")

    def test_fetch_tolerates_failing_modal_call(self):
        rtl_plus.rtlplus_client.fetch_day = lambda *a, **kw: _grid_response()

        def raise_modal_error(*args, **kwargs):
            raise RtlPlusEpgError("RTL+ Anfrage fehlgeschlagen")

        rtl_plus.rtlplus_client.fetch_modal = raise_modal_error
        task = dict(RTL_TASK, days=1)
        _, programmes = RtlPlusDeProvider().fetch(task)
        self.assertEqual(len(programmes), 1)
        self.assertEqual(programmes[0]["title"], "Punkt 12")
        self.assertEqual(programmes[0]["description"], "")

    def test_fetch_without_modal_id_skips_description_call(self):
        rtl_plus.rtlplus_client.fetch_day = lambda *a, **kw: _grid_response()

        def fail_if_called(*args, **kwargs):
            raise AssertionError("fetch_modal should not be called without a modal id")

        rtl_plus.rtlplus_client.fetch_modal = fail_if_called
        task = dict(VOX_TASK, days=1)
        _, programmes = RtlPlusDeProvider().fetch(task)
        self.assertEqual(programmes[0]["description"], "")

    def test_fetch_raises_for_unknown_channel(self):
        rtl_plus.rtlplus_client.fetch_day = lambda *a, **kw: _grid_response()
        task = {"days": 1, "rtlplus_channel_id": "unknown", "source_channel_name": "Unknown"}
        with self.assertRaises(Exception) as ctx:
            RtlPlusDeProvider().fetch(task)
        self.assertIn("nicht gefunden", str(ctx.exception))

    def test_parses_offset_timestamps(self):
        self.assertEqual(
            _parse_rtlplus_iso8601("2026-06-21T05:40:00+02:00"),
            datetime.datetime(2026, 6, 21, 5, 40, 0),
        )

    def test_decode_modal_id(self):
        self.assertEqual(_decode_modal_id(RTL_MODAL_ID), ("rtlde_rtl", "465855", "2026-06-20"))

    def test_decode_modal_id_returns_empty_on_invalid_input(self):
        self.assertEqual(_decode_modal_id("not-base64!"), ("", "", ""))

    def test_rtlplus_client_reports_dns_errors_clearly(self):
        message = RtlPlusEpgClient()._build_url_error_message(
            URLError(socket.gaierror(-2, "Name or service not known"))
        )
        self.assertIn("DNS", message)
        self.assertIn("Auflösung", message)
        self.assertIn("Nameserver", message)
        self.assertIn("prüfen", message)

    def test_rtlplus_client_reports_ssl_errors_with_clock_hint(self):
        message = RtlPlusEpgClient()._build_url_error_message(
            URLError(ssl.SSLError("certificate verify failed"))
        )
        self.assertIn("SSL", message)
        self.assertIn("Datum", message)
        self.assertIn("Uhrzeit", message)
        self.assertIn("prüfen", message)

    def test_rtlplus_client_reports_timeout_clearly(self):
        client = RtlPlusEpgClient(timeout=8)
        message = client._build_url_error_message(URLError("timed out"))
        self.assertIn("8 Sekunden", message)
        self.assertIn("Netzwerkverbindung", message)
        self.assertIn("später", message)

    def test_rtlplus_fetch_wraps_client_errors(self):
        def raise_error(*args, **kwargs):
            raise RtlPlusEpgError(u"DNS-Auflösung fehlgeschlagen. Bitte prüfen.")

        rtl_plus.rtlplus_client.fetch_day = raise_error
        with self.assertRaises(Exception) as ctx:
            RtlPlusDeProvider().fetch(dict(RTL_TASK, days=1))
        message = ensure_text(ctx.exception)
        self.assertIn(u"Auflösung", message)
        self.assertNotIn(u"Ã", message)

    def test_client_caches_bearer_and_bedrock_tokens_across_calls(self):
        client = RtlPlusEpgClient()
        calls = {"bearer": 0, "bedrock": 0, "grid": 0}

        def fake_open(request):
            url = request.get_full_url() if hasattr(request, "get_full_url") else request.full_url
            if "openid-connect/token" in url:
                calls["bearer"] += 1
                return _FakeResponse('{"access_token": "bearer-token"}')
            if "front-auth" in url:
                calls["bedrock"] += 1
                return _FakeResponse('{"token": "bedrock-token"}')
            calls["grid"] += 1
            return _FakeResponse('{"content": {"items": []}}')

        client._open = fake_open
        client.fetch_day("2026-06-21")
        client.fetch_day("2026-06-22")

        self.assertEqual(calls["bearer"], 1)
        self.assertEqual(calls["bedrock"], 1)
        self.assertEqual(calls["grid"], 2)


class _FakeResponse(object):
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode("utf-8")


if __name__ == "__main__":
    unittest.main()
