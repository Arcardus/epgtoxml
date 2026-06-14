#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function

import json
import socket
import sys

try:
    import cookielib
    import urllib2
except ImportError:
    import http.cookiejar as cookielib
    import urllib.request as urllib2

try:
    from urllib2 import HTTPError, URLError
except ImportError:
    from urllib.error import HTTPError, URLError

try:
    from argparse import ArgumentParser
except ImportError:
    ArgumentParser = None


DEFAULT_CHANNEL_ID = 1236
DEFAULT_CHANNEL_SLUG = "dfbtv-c1236"
DEFAULT_PAGE_SIZE = 64
DEFAULT_TIMEOUT = 8
MILLIS_PER_DAY = 24 * 60 * 60 * 1000

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
    "Gecko/20100101 Firefox/152.0"
)


class SkyEpgError(Exception):
    pass


class SkyEpgClient(object):
    """Minimal Sky EPG client for Python 2 / Enigma2 style environments."""

    def __init__(self, channel_slug=DEFAULT_CHANNEL_SLUG, user_agent=DEFAULT_USER_AGENT, timeout=DEFAULT_TIMEOUT):
        self.channel_slug = channel_slug
        self.user_agent = user_agent
        self.timeout = timeout
        self.page_url = "https://www.sky.de/tvguide/%s" % channel_slug
        self.service_base = "https://www.sky.de/sgtvg/service/"
        self.cookie_jar = cookielib.CookieJar()
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cookie_jar))
        self._bootstrapped = False

    def bootstrap(self):
        """Create a fresh website session and let Sky set its own cookies."""
        if self._bootstrapped:
            return

        request = self._make_request(
            self.page_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        self._open(request).read(1)
        self._bootstrapped = True

    def get_current_system_time(self):
        """Return the Sky backend timestamp in milliseconds."""
        payload = self._post_json("getCurrentSystemTime", {})
        if "d" not in payload:
            raise SkyEpgError("Sky response for getCurrentSystemTime does not contain 'd'")
        return payload["d"]

    def get_channel_list(self):
        """Return the raw Sky channel list response."""
        self.bootstrap()
        payload = {"dom": "de", "s": 0, "feed": 1}
        data = self._post_json("getChannelList", payload)
        channels = data.get("cl")
        if not isinstance(channels, list):
            raise SkyEpgError("Sky response for getChannelList contains invalid 'cl'")
        return data

    def get_broadcasts_page(self, day_timestamp, channel_id, page_number, page_size):
        payload = {
            "d": day_timestamp,
            "lt": 6,
            "t": 0,
            "s": 0,
            "pn": page_number,
            "sto": 10,
            "epp": page_size,
            "cil": [channel_id],
        }
        return self._post_json("getBroadcasts", payload)

    def fetch_days(self, channel_id=DEFAULT_CHANNEL_ID, start_offset=0, num_days=1, page_size=DEFAULT_PAGE_SIZE):
        """Fetch one or more Sky EPG days for a single channel."""
        if int(num_days) < 1:
            raise SkyEpgError("num_days must be at least 1")
        if int(page_size) < 1:
            raise SkyEpgError("page_size must be at least 1")

        self.bootstrap()
        base_timestamp = self.get_current_system_time()

        start_offset = int(start_offset)
        num_days = int(num_days)
        page_size = int(page_size)

        day_results = []

        for index in range(num_days):
            day_offset = start_offset + index
            target_timestamp = base_timestamp + (day_offset * MILLIS_PER_DAY)
            events = self._fetch_day_events(target_timestamp, channel_id, page_size)
            day_results.append(
                {
                    "day_offset": day_offset,
                    "timestamp": target_timestamp,
                    "el": events,
                }
            )

        return {
            "channel_id": int(channel_id),
            "channel_slug": self.channel_slug,
            "start_offset": start_offset,
            "num_days": num_days,
            "days": day_results,
        }

    def fetch_day(self, channel_id=DEFAULT_CHANNEL_ID, day_offset=0, page_size=DEFAULT_PAGE_SIZE):
        """Fetch exactly one Sky EPG day in the original Sky response shape."""
        data = self.fetch_days(
            channel_id=channel_id,
            start_offset=day_offset,
            num_days=1,
            page_size=page_size,
        )
        return {"el": data["days"][0]["el"]}

    def _fetch_day_events(self, target_timestamp, channel_id, page_size):
        """Collect all paginated events for one Sky day request."""
        channel_id = int(channel_id)

        collected = []
        page_number = 1
        seen_pages = {}

        while True:
            page_data = self.get_broadcasts_page(target_timestamp, channel_id, page_number, page_size)
            events = page_data.get("el", [])
            if not isinstance(events, list):
                raise SkyEpgError("Sky response for getBroadcasts contains invalid 'el'")

            signature = self._event_signature(events)
            if signature and signature in seen_pages:
                break
            if signature:
                seen_pages[signature] = True

            collected.extend(events)

            if len(events) < page_size:
                break

            page_number += 1

            if page_number > 50:
                raise SkyEpgError("Aborting pagination after 50 pages")

        return collected

    def _event_signature(self, events):
        signature = []
        for event in events:
            signature.append((
                event.get("ei"),
                event.get("bid"),
                event.get("bst"),
                event.get("et"),
                event.get("len"),
            ))
        return tuple(signature)

    def _post_json(self, endpoint, payload):
        body = json.dumps(payload).encode("utf-8")
        request = self._make_request(
            self.service_base + endpoint,
            data=body,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://www.sky.de",
                "Referer": self.page_url,
            },
        )
        response = self._open(request)
        raw = response.read()
        return self._decode_json(raw)

    def _make_request(self, url, data=None, headers=None):
        headers = headers or {}
        try:
            return urllib2.Request(url, data=data, headers=headers)
        except TypeError:
            request = urllib2.Request(url, data=data, headers=headers)
            return request

    def _open(self, request):
        try:
            return self.opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            message = self._build_http_error_message(exc)
            raise SkyEpgError(message)
        except URLError as exc:
            raise SkyEpgError("Sky.de ist nicht erreichbar: %s" % exc)
        except socket.timeout:
            raise SkyEpgError("Sky.de antwortet nicht innerhalb von %d Sekunden." % self.timeout)
        except Exception as exc:
            raise SkyEpgError("Sky.de Anfrage fehlgeschlagen: %s" % exc)

    def _build_http_error_message(self, exc):
        body = ""
        try:
            body = exc.read()
        except Exception:
            body = ""
        if isinstance(body, bytes):
            try:
                body = body.decode("utf-8")
            except Exception:
                body = body.decode("latin-1", "replace")
        if int(getattr(exc, "code", 0) or 0) >= 500:
            return "Sky.de meldet Serverfehler HTTP %s. Bitte später erneut versuchen." % exc.code
        if int(getattr(exc, "code", 0) or 0) == 403:
            return "Sky.de blockiert die Anfrage mit HTTP 403."
        return "Sky.de meldet HTTP %s für %s: %s" % (exc.code, exc.geturl(), body[:300])

    def _decode_json(self, raw):
        if isinstance(raw, bytes):
            text = raw.decode("utf-8")
        else:
            text = raw
        try:
            return json.loads(text)
        except ValueError as exc:
            preview = text[:120].strip().replace("\n", " ")
            if preview.lower().startswith("<"):
                raise SkyEpgError("Sky.de lieferte HTML statt JSON. Webseite/API ist gerade nicht nutzbar.")
            raise SkyEpgError("Sky.de lieferte ungültiges JSON: %s" % exc)


def fetch_days(
    channel_id=DEFAULT_CHANNEL_ID,
    start_offset=0,
    num_days=1,
    page_size=DEFAULT_PAGE_SIZE,
    channel_slug=DEFAULT_CHANNEL_SLUG,
):
    """Public helper for multi-day Sky EPG retrieval."""
    client = SkyEpgClient(channel_slug=channel_slug)
    return client.fetch_days(
        channel_id=channel_id,
        start_offset=start_offset,
        num_days=num_days,
        page_size=page_size,
    )


def fetch_day(channel_id=DEFAULT_CHANNEL_ID, day_offset=0, page_size=DEFAULT_PAGE_SIZE, channel_slug=DEFAULT_CHANNEL_SLUG):
    """Backward-compatible helper that returns one day in raw Sky format."""
    client = SkyEpgClient(channel_slug=channel_slug)
    return client.fetch_day(channel_id=channel_id, day_offset=day_offset, page_size=page_size)


def list_channels(channel_slug=DEFAULT_CHANNEL_SLUG):
    """Return the raw Sky channel list for discovery and testing."""
    client = SkyEpgClient(channel_slug=channel_slug)
    return client.get_channel_list()


def _build_argument_parser():
    if ArgumentParser is None:
        raise SkyEpgError("argparse is not available in this Python installation")

    parser = ArgumentParser(description="Fetch Sky EPG data from sky.de")
    parser.add_argument("--channel-id", type=int, default=DEFAULT_CHANNEL_ID, help="Sky channel id (default: %(default)s)")
    parser.add_argument("--channel-slug", default=DEFAULT_CHANNEL_SLUG, help="Sky tvguide slug (default: %(default)s)")
    parser.add_argument("--start-offset", type=int, default=None, help="Start day offset relative to Sky server time")
    parser.add_argument("--day-offset", type=int, default=None, help="Legacy alias for --start-offset")
    parser.add_argument("--days", type=int, default=1, help="How many days to fetch starting at the offset")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help="Items per request page (default: %(default)s)")
    parser.add_argument("--list-channels", action="store_true", help="List channels returned by Sky instead of fetching EPG")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    return parser


def _write_stdout(text):
    if isinstance(text, bytes):
        data = text
    else:
        data = text.encode("utf-8")

    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(data)
        return

    sys.stdout.write(data)


def _resolve_start_offset(args):
    if args.start_offset is not None:
        return args.start_offset
    if args.day_offset is not None:
        return args.day_offset
    return 0


def main(argv=None):
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    try:
        if args.days < 1:
            raise SkyEpgError("--days must be at least 1")
        if args.page_size < 1:
            raise SkyEpgError("--page-size must be at least 1")

        if args.list_channels:
            data = list_channels(channel_slug=args.channel_slug)
        else:
            start_offset = _resolve_start_offset(args)
            if args.days == 1:
                data = fetch_day(
                    channel_id=args.channel_id,
                    day_offset=start_offset,
                    page_size=args.page_size,
                    channel_slug=args.channel_slug,
                )
            else:
                data = fetch_days(
                    channel_id=args.channel_id,
                    start_offset=start_offset,
                    num_days=args.days,
                    page_size=args.page_size,
                    channel_slug=args.channel_slug,
                )
    except SkyEpgError as exc:
        sys.stderr.write("ERROR: %s\n" % exc)
        return 1

    if args.pretty:
        output = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        output = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    _write_stdout(output)
    _write_stdout("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
