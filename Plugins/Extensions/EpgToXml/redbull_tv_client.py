#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import print_function

import json
import socket
import ssl
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


GUIDE_URL_TEMPLATE = "https://tv-api.redbull.com/guides/v5/rbtv/%s/%s/rrn:content:video-channels:%s"
DEFAULT_LOCALE = "de_DE"
DEFAULT_LANGUAGE = "de"
DEFAULT_TIMEOUT = 8

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) "
    "Gecko/20100101 Firefox/153.0"
)


class RedBullTvEpgError(Exception):
    pass


class RedBullTvEpgClient(object):
    """Minimal Red Bull TV EPG client for Python 2 / Enigma2 style environments."""

    def __init__(self, user_agent=DEFAULT_USER_AGENT, timeout=DEFAULT_TIMEOUT):
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch_guide(self, channel_id, locale=DEFAULT_LOCALE, language=DEFAULT_LANGUAGE):
        url = GUIDE_URL_TEMPLATE % (locale, language, channel_id)
        request = self._make_request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Origin": "https://www.redbull.tv",
                "Referer": "https://www.redbull.tv/",
            },
        )
        raw = self._open(request).read()
        return self._decode_json(raw)

    def _make_request(self, url, data=None, headers=None):
        headers = headers or {}
        return urllib2.Request(url, data=data, headers=headers)

    def _open(self, request):
        try:
            return urllib2.urlopen(request, timeout=self.timeout)
        except HTTPError as exc:
            raise RedBullTvEpgError(self._build_http_error_message(exc))
        except URLError as exc:
            raise RedBullTvEpgError(self._build_url_error_message(exc))
        except socket.timeout:
            raise RedBullTvEpgError(self._timeout_message())
        except ssl.SSLError as exc:
            raise RedBullTvEpgError(self._build_ssl_error_message(exc))
        except Exception as exc:
            raise RedBullTvEpgError("Red Bull TV Anfrage fehlgeschlagen: %s" % exc)

    def _build_url_error_message(self, exc):
        reason = getattr(exc, "reason", exc)
        reason_text = str(reason)
        lower = reason_text.lower()
        if self._looks_like_ssl_error(reason, lower):
            return self._build_ssl_error_message(reason)
        if self._looks_like_dns_error(lower):
            return (
                u"Red Bull TV ist nicht erreichbar: DNS-Auflösung fehlgeschlagen. "
                u"Bitte Internetverbindung und Nameserver der Box prüfen. Details: %s"
            ) % reason_text
        if self._looks_like_timeout(lower):
            return self._timeout_message(u" Details: %s" % reason_text)
        if "protocol not supported" in lower:
            return (
                u"Red Bull TV ist nicht erreichbar: HTTPS/Netzwerk-Stack der Box meldet "
                u"'Protocol not supported'. Bitte Netzwerk, DNS und Datum/Uhrzeit der Box "
                u"prüfen. Details: %s"
            ) % reason_text
        return (
            u"Red Bull TV ist nicht erreichbar: Netzwerkfehler. "
            u"Bitte Internetverbindung der Box prüfen und später erneut versuchen. Details: %s"
        ) % reason_text

    def _build_ssl_error_message(self, exc):
        return (
            u"Red Bull TV SSL-Verbindung fehlgeschlagen. Bitte Datum/Uhrzeit der Box, "
            u"DNS/Internetverbindung und Zertifikate prüfen. Details: %s"
        ) % str(exc)

    def _timeout_message(self, suffix=""):
        return (
            u"Red Bull TV antwortet nicht innerhalb von %d Sekunden. "
            u"Bitte Netzwerkverbindung prüfen und später erneut versuchen.%s"
        ) % (self.timeout, suffix)

    def _looks_like_ssl_error(self, reason, lower):
        if isinstance(reason, ssl.SSLError):
            return True
        keywords = ("ssl", "certificate", "cert_verify", "tls", "handshake", "wrong version number")
        for keyword in keywords:
            if keyword in lower:
                return True
        return False

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
        if int(getattr(exc, "code", 0) or 0) >= 500:
            return "Red Bull TV meldet Serverfehler HTTP %s. Bitte später erneut versuchen." % exc.code
        if int(getattr(exc, "code", 0) or 0) == 403:
            return "Red Bull TV blockiert die Anfrage mit HTTP 403."
        return "Red Bull TV meldet HTTP %s für %s: %s" % (exc.code, exc.geturl(), body[:300])

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
                raise RedBullTvEpgError("Red Bull TV lieferte HTML statt JSON. Webseite/API ist gerade nicht nutzbar.")
            raise RedBullTvEpgError("Red Bull TV lieferte ungültiges JSON: %s" % exc)


def fetch_guide(channel_id, locale=DEFAULT_LOCALE, language=DEFAULT_LANGUAGE):
    """Public helper for fetching the Red Bull TV guide for a single channel."""
    client = RedBullTvEpgClient()
    return client.fetch_guide(channel_id, locale=locale, language=language)


def _build_argument_parser():
    if ArgumentParser is None:
        raise RedBullTvEpgError("argparse is not available in this Python installation")

    parser = ArgumentParser(description="Fetch the Red Bull TV guide for a channel")
    parser.add_argument(
        "--channel", dest="channel_id", required=True,
        help="Channel id, e.g. c81f8686-ab67-4965-ba04-5f6658bb96cc",
    )
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
        data = fetch_guide(args.channel_id)
    except RedBullTvEpgError as exc:
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
