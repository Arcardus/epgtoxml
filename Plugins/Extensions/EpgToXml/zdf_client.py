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
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode

try:
    from argparse import ArgumentParser
except ImportError:
    ArgumentParser = None


GRAPHQL_URL = "https://api.zdf.de/graphql"
GETEPG_SHA256 = "e36a71fb3206e75a82a5438737113b221e43daf0363d85f3eeceda288d158821"
DEFAULT_TIMEOUT = 8

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
    "Gecko/20100101 Firefox/152.0"
)
DEFAULT_API_AUTH = "Bearer aa3noh4ohz9eeboo8shiesheec9ciequ9Quah7el"
DEFAULT_APP_ID = "ffw-mt-web-036df51e"


class ZdfEpgError(Exception):
    pass


class ZdfEpgClient(object):
    """Minimal ZDF EPG GraphQL client for Python 2 / Enigma2 style environments."""

    def __init__(self, user_agent=DEFAULT_USER_AGENT, timeout=DEFAULT_TIMEOUT,
                 api_auth=DEFAULT_API_AUTH, app_id=DEFAULT_APP_ID):
        self.user_agent = user_agent
        self.timeout = timeout
        self.api_auth = api_auth
        self.app_id = app_id

    def fetch_epg(self, from_iso, to_iso, broadcaster_ids):
        variables = json.dumps({
            "filter": {
                "broadcasterIds": list(broadcaster_ids),
                "from": from_iso,
                "to": to_iso,
            },
        }, separators=(",", ":"))
        extensions = json.dumps({
            "clientLibrary": {"name": "@apollo/client", "version": "4.1.9"},
            "persistedQuery": {"version": 1, "sha256Hash": GETEPG_SHA256},
        }, separators=(",", ":"))
        query = urlencode({
            "operationName": "getEpg",
            "variables": variables,
            "extensions": extensions,
        })
        url = GRAPHQL_URL + "?" + query
        request = self._make_request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/graphql-response+json,application/json;q=0.9",
                "Origin": "https://www.zdf.de",
                "Referer": "https://www.zdf.de/",
                "api-auth": self.api_auth,
                "zdf-app-id": self.app_id,
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
            raise ZdfEpgError(self._build_http_error_message(exc))
        except URLError as exc:
            raise ZdfEpgError(self._build_url_error_message(exc))
        except socket.timeout:
            raise ZdfEpgError(self._timeout_message())
        except ssl.SSLError as exc:
            raise ZdfEpgError(self._build_ssl_error_message(exc))
        except Exception as exc:
            raise ZdfEpgError("ZDF Anfrage fehlgeschlagen: %s" % exc)

    def _build_url_error_message(self, exc):
        reason = getattr(exc, "reason", exc)
        reason_text = str(reason)
        lower = reason_text.lower()
        if self._looks_like_ssl_error(reason, lower):
            return self._build_ssl_error_message(reason)
        if self._looks_like_dns_error(lower):
            return (
                u"ZDF ist nicht erreichbar: DNS-Auflösung fehlgeschlagen. "
                u"Bitte Internetverbindung und Nameserver der Box prüfen. Details: %s"
            ) % reason_text
        if self._looks_like_timeout(lower):
            return self._timeout_message(u" Details: %s" % reason_text)
        if "protocol not supported" in lower:
            return (
                u"ZDF ist nicht erreichbar: HTTPS/Netzwerk-Stack der Box meldet 'Protocol not supported'. "
                u"Bitte Netzwerk, DNS und Datum/Uhrzeit der Box prüfen. Details: %s"
            ) % reason_text
        return (
            u"ZDF ist nicht erreichbar: Netzwerkfehler. "
            u"Bitte Internetverbindung der Box prüfen und später erneut versuchen. Details: %s"
        ) % reason_text

    def _build_ssl_error_message(self, exc):
        return (
            u"ZDF SSL-Verbindung fehlgeschlagen. Bitte Datum/Uhrzeit der Box, "
            u"DNS/Internetverbindung und Zertifikate prüfen. Details: %s"
        ) % str(exc)

    def _timeout_message(self, suffix=""):
        return (
            u"ZDF antwortet nicht innerhalb von %d Sekunden. "
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
            return "ZDF meldet Serverfehler HTTP %s. Bitte später erneut versuchen." % exc.code
        if int(getattr(exc, "code", 0) or 0) == 403:
            return "ZDF blockiert die Anfrage mit HTTP 403."
        return "ZDF meldet HTTP %s für %s: %s" % (exc.code, exc.geturl(), body[:300])

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
                raise ZdfEpgError("ZDF lieferte HTML statt JSON. Webseite/API ist gerade nicht nutzbar.")
            raise ZdfEpgError("ZDF lieferte ungültiges JSON: %s" % exc)


def fetch_epg(from_iso, to_iso, broadcaster_ids):
    """Public helper for fetching the ZDF EPG for a time range and broadcaster set."""
    client = ZdfEpgClient()
    return client.fetch_epg(from_iso, to_iso, broadcaster_ids)


def _build_argument_parser():
    if ArgumentParser is None:
        raise ZdfEpgError("argparse is not available in this Python installation")

    parser = ArgumentParser(description="Fetch the ZDF EPG for a time range")
    parser.add_argument("--from", dest="from_iso", required=True, help="Start, e.g. 2026-06-21T03:00:00Z")
    parser.add_argument("--to", dest="to_iso", required=True, help="End, e.g. 2026-06-22T02:59:59Z")
    parser.add_argument(
        "--broadcaster", dest="broadcasters", action="append", required=True,
        help="Broadcaster id, may be repeated",
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
        data = fetch_epg(args.from_iso, args.to_iso, args.broadcasters)
    except ZdfEpgError as exc:
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
