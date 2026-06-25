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
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode

try:
    from argparse import ArgumentParser
except ImportError:
    ArgumentParser = None

try:
    from .ssl_diagnostics import SSL_ERROR_TYPES, build_ssl_message, looks_like_ssl_error
except (ImportError, ValueError):
    from ssl_diagnostics import SSL_ERROR_TYPES, build_ssl_message, looks_like_ssl_error


RAIL_URL = "https://rail-router.discovery.indazn.com/eu/v10/Rail"
DEFAULT_RAIL_ID = "Livetvschedule"
DEFAULT_PLATFORM = "web"
DEFAULT_BRAND = "dazn"
DEFAULT_COUNTRY = "de"
DEFAULT_LANGUAGE_CODE = "de"
DEFAULT_TIMEOUT = 8

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
    "Gecko/20100101 Firefox/152.0"
)


class DaznEpgError(Exception):
    pass


class DaznEpgClient(object):
    """Minimal DAZN live-schedule client for Python 2 / Enigma2 style environments."""

    def __init__(
        self,
        country=DEFAULT_COUNTRY,
        language_code=DEFAULT_LANGUAGE_CODE,
        brand=DEFAULT_BRAND,
        user_agent=DEFAULT_USER_AGENT,
        timeout=DEFAULT_TIMEOUT,
    ):
        self.country = country
        self.language_code = language_code
        self.brand = brand
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch_live_schedule(self, rail_id=DEFAULT_RAIL_ID, platform=DEFAULT_PLATFORM):
        params = {
            "platform": platform,
            "id": rail_id,
            "country": self.country,
            "brand": self.brand,
            "languageCode": self.language_code,
        }
        url = RAIL_URL + "?" + urlencode(params)
        request = self._make_request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://www.dazn.com",
                "Referer": "https://www.dazn.com/",
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
            raise DaznEpgError(self._build_http_error_message(exc))
        except URLError as exc:
            raise DaznEpgError(self._build_url_error_message(exc))
        except socket.timeout:
            raise DaznEpgError(self._timeout_message())
        except SSL_ERROR_TYPES as exc:
            raise DaznEpgError(self._build_ssl_error_message(exc))
        except Exception as exc:
            raise DaznEpgError("DAZN Anfrage fehlgeschlagen: %s" % exc)

    def _build_url_error_message(self, exc):
        reason = getattr(exc, "reason", exc)
        reason_text = str(reason)
        lower = reason_text.lower()
        if looks_like_ssl_error(reason, lower):
            return self._build_ssl_error_message(reason)
        if self._looks_like_dns_error(lower):
            return (
                u"DAZN ist nicht erreichbar: DNS-Auflösung fehlgeschlagen. "
                u"Bitte Internetverbindung und Nameserver der Box prüfen. Details: %s"
            ) % reason_text
        if self._looks_like_timeout(lower):
            return self._timeout_message(u" Details: %s" % reason_text)
        if "protocol not supported" in lower:
            return (
                u"DAZN ist nicht erreichbar: HTTPS/Netzwerk-Stack der Box meldet 'Protocol not supported'. "
                u"Bitte Netzwerk, DNS und Datum/Uhrzeit der Box prüfen. Details: %s"
            ) % reason_text
        return (
            u"DAZN ist nicht erreichbar: Netzwerkfehler. "
            u"Bitte Internetverbindung der Box prüfen und später erneut versuchen. Details: %s"
        ) % reason_text

    def _build_ssl_error_message(self, exc):
        return build_ssl_message(u"DAZN", exc)

    def _timeout_message(self, suffix=""):
        return (
            u"DAZN antwortet nicht innerhalb von %d Sekunden. "
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
        if int(getattr(exc, "code", 0) or 0) >= 500:
            return "DAZN meldet Serverfehler HTTP %s. Bitte später erneut versuchen." % exc.code
        if int(getattr(exc, "code", 0) or 0) == 403:
            return "DAZN blockiert die Anfrage mit HTTP 403."
        return "DAZN meldet HTTP %s für %s: %s" % (exc.code, exc.geturl(), body[:300])

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
                raise DaznEpgError("DAZN lieferte HTML statt JSON. Webseite/API ist gerade nicht nutzbar.")
            raise DaznEpgError("DAZN lieferte ungültiges JSON: %s" % exc)


def fetch_live_schedule(
    country=DEFAULT_COUNTRY,
    language_code=DEFAULT_LANGUAGE_CODE,
    brand=DEFAULT_BRAND,
    rail_id=DEFAULT_RAIL_ID,
    platform=DEFAULT_PLATFORM,
):
    """Public helper for fetching the DAZN live-TV schedule Rail response."""
    client = DaznEpgClient(country=country, language_code=language_code, brand=brand)
    return client.fetch_live_schedule(rail_id=rail_id, platform=platform)


def _build_argument_parser():
    if ArgumentParser is None:
        raise DaznEpgError("argparse is not available in this Python installation")

    parser = ArgumentParser(description="Fetch the DAZN live-TV schedule")
    parser.add_argument("--country", default=DEFAULT_COUNTRY, help="Country code (default: %(default)s)")
    parser.add_argument(
        "--language-code", default=DEFAULT_LANGUAGE_CODE, help="Language code (default: %(default)s)"
    )
    parser.add_argument("--brand", default=DEFAULT_BRAND, help="Brand (default: %(default)s)")
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
        data = fetch_live_schedule(
            country=args.country,
            language_code=args.language_code,
            brand=args.brand,
        )
    except DaznEpgError as exc:
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
