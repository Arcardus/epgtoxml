#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import print_function

import json
import socket
import sys

try:
    import urllib2
except ImportError:
    import urllib.request as urllib2

try:
    from urllib2 import HTTPError, URLError
except ImportError:
    from urllib.error import HTTPError, URLError

try:
    from argparse import ArgumentParser
except ImportError:
    ArgumentParser = None

try:
    from .ssl_diagnostics import SSL_ERROR_TYPES, build_ssl_message, looks_like_ssl_error
except (ImportError, ValueError):
    from ssl_diagnostics import SSL_ERROR_TYPES, build_ssl_message, looks_like_ssl_error


BASE_URL = "https://api-gn-epg.prd.tvengine.hd-plus-cloud.de"
ORIGIN = "https://tvg-epg.hd-plus-cloud.de"
SLICE_URL_TEMPLATE = BASE_URL + "/epg/v1/slice/%s/%s/%s"

# Die Web-App fragt pro Tag zwei überlappende 14h30m-Fenster ab (Start 00:00 und
# 12:00 UTC). Wir übernehmen dasselbe Fenster; der Provider dedupliziert die
# Überlappung über startTime.
SLICE_DURATION = "PT14H30M"
DEFAULT_TIMEOUT = 8

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)


class HdPlusEpgError(Exception):
    pass


class HdPlusEpgClient(object):
    """Minimal HD+ (hd-plus-cloud.de) EPG client for Python 2 / Enigma2 style environments.

    The slice endpoint is public: no OAuth/token chain is needed, only the
    Origin/Referer of the HD+ TV-guide web app. One CLI subprocess invocation
    covers all days/channels needed for a fetch run.
    """

    def __init__(self, user_agent=DEFAULT_USER_AGENT, timeout=DEFAULT_TIMEOUT):
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch_slice(self, channel_id, start_iso, duration=SLICE_DURATION):
        request = self._make_request(
            SLICE_URL_TEMPLATE % (start_iso, duration, channel_id),
            headers=self._epg_headers(),
        )
        raw = self._open(request).read()
        return self._decode_json(raw)

    def _epg_headers(self):
        return {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Accept-Language": "de-DE,de;q=0.9",
            "Origin": ORIGIN,
            "Referer": ORIGIN + "/",
        }

    def _make_request(self, url, data=None, headers=None):
        headers = headers or {}
        return urllib2.Request(url, data=data, headers=headers)

    def _open(self, request):
        try:
            return urllib2.urlopen(request, timeout=self.timeout)
        except HTTPError as exc:
            raise HdPlusEpgError(self._build_http_error_message(exc))
        except URLError as exc:
            raise HdPlusEpgError(self._build_url_error_message(exc))
        except socket.timeout:
            raise HdPlusEpgError(self._timeout_message())
        except SSL_ERROR_TYPES as exc:
            raise HdPlusEpgError(self._build_ssl_error_message(exc))
        except Exception as exc:
            raise HdPlusEpgError("HD+ Anfrage fehlgeschlagen: %s" % exc)

    def _build_url_error_message(self, exc):
        reason = getattr(exc, "reason", exc)
        reason_text = str(reason)
        lower = reason_text.lower()
        if looks_like_ssl_error(reason, lower):
            return self._build_ssl_error_message(reason)
        if self._looks_like_dns_error(lower):
            return (
                u"HD+ ist nicht erreichbar: DNS-Auflösung fehlgeschlagen. "
                u"Bitte Internetverbindung und Nameserver der Box prüfen. Details: %s"
            ) % reason_text
        if self._looks_like_timeout(lower):
            return self._timeout_message(u" Details: %s" % reason_text)
        if "protocol not supported" in lower:
            return (
                u"HD+ ist nicht erreichbar: HTTPS/Netzwerk-Stack der Box meldet "
                u"'Protocol not supported'. Bitte Netzwerk, DNS und Datum/Uhrzeit der Box "
                u"prüfen. Details: %s"
            ) % reason_text
        return (
            u"HD+ ist nicht erreichbar: Netzwerkfehler. "
            u"Bitte Internetverbindung der Box prüfen und später erneut versuchen. Details: %s"
        ) % reason_text

    def _build_ssl_error_message(self, exc):
        return build_ssl_message(u"HD+", exc)

    def _timeout_message(self, suffix=""):
        return (
            u"HD+ antwortet nicht innerhalb von %d Sekunden. "
            u"Bitte Netzwerkverbindung prüfen und später erneut versuchen.%s"
        ) % (self.timeout, suffix)

    def _looks_like_dns_error(self, lower):
        keywords = (
            "name or service not known", "temporary failure in name resolution",
            "getaddrinfo", "nodename nor servname", "no address associated",
            "11001", "errno -2"
        )
        for keyword in keywords:
            if keyword in lower:
                return True
        return False

    def _looks_like_timeout(self, lower):
        return "timed out" in lower or "timeout" in lower

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
        code = int(getattr(exc, "code", 0) or 0)
        if code == 404:
            return "HD+ kennt diesen Sender/Zeitraum nicht (HTTP 404)."
        if code >= 500:
            return "HD+ meldet Serverfehler HTTP %s. Bitte später erneut versuchen." % exc.code
        if code == 403:
            return "HD+ blockiert die Anfrage mit HTTP 403."
        return "HD+ meldet HTTP %s für %s: %s" % (exc.code, exc.geturl(), body[:300])

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
                raise HdPlusEpgError("HD+ lieferte HTML statt JSON. Webseite/API ist gerade nicht nutzbar.")
            raise HdPlusEpgError("HD+ lieferte ungültiges JSON: %s" % exc)


def fetch_slice(channel_id, start_iso, duration=SLICE_DURATION):
    """Public helper for fetching one HD+ EPG slice (channel + time window)."""
    client = HdPlusEpgClient()
    return client.fetch_slice(channel_id, start_iso, duration=duration)


def _build_argument_parser():
    if ArgumentParser is None:
        raise HdPlusEpgError("argparse is not available in this Python installation")

    parser = ArgumentParser(description="Fetch one HD+ EPG slice")
    parser.add_argument("--channel", dest="channel", required=True, help="Channel id, e.g. das_erste_hd")
    parser.add_argument(
        "--start", dest="start", required=True,
        help="Slice start, ISO UTC, e.g. 2026-07-19T00:00:00.000Z",
    )
    parser.add_argument("--duration", dest="duration", default=SLICE_DURATION, help="ISO8601 duration")
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


def main(argv=None):
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    try:
        data = fetch_slice(args.channel, args.start, duration=args.duration)
    except HdPlusEpgError as exc:
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
