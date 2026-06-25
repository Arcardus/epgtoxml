#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import print_function

import json
import socket
import sys
import uuid

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


OIDC_TOKEN_URL = "https://auth.rtl.de/auth/realms/rtlplus/protocol/openid-connect/token"
OIDC_CLIENT_ID = "anonymous-user"
OIDC_CLIENT_SECRET = "4bfeb73f-1c4a-4e9f-a7fa-96aa1ad3d94c"

FRONT_AUTH_URL = "https://front-auth.rtlde.bedrock.tech/v2/rtlde/platforms/m6group_web/token"

LAYOUT_BASE_URL = "https://layout.rtlde.bedrock.tech/front/v1/rtlde/m6group_web/main/token-web-31"
EPG_GRID_URL = LAYOUT_BASE_URL + "/epg_grid"
MODAL_URL_TEMPLATE = LAYOUT_BASE_URL + "/epg_grid/%s/modal"

DEFAULT_CUSTOMER_NAME = "rtlde"
DEFAULT_CLIENT_RELEASE = "6.44.1"
DEFAULT_NB_PAGES = 5
DEFAULT_TIMEOUT = 8

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) "
    "Gecko/20100101 Firefox/153.0"
)


class RtlPlusEpgError(Exception):
    pass


class RtlPlusEpgClient(object):
    """Minimal RTL+ (plus.rtl.de) EPG client for Python 2 / Enigma2 style environments.

    Authenticates anonymously against the Bedrock platform (3-step chain:
    OIDC bearer -> Bedrock token -> epg_grid/modal). Tokens are cached on the
    instance for the lifetime of one fetch run (one CLI subprocess invocation
    covers all days/calls needed, so there's no need to persist tokens
    across runs).
    """

    def __init__(self, user_agent=DEFAULT_USER_AGENT, timeout=DEFAULT_TIMEOUT,
                 customer_name=DEFAULT_CUSTOMER_NAME, client_release=DEFAULT_CLIENT_RELEASE):
        self.user_agent = user_agent
        self.timeout = timeout
        self.customer_name = customer_name
        self.client_release = client_release
        self._bearer = None
        self._bedrock_token = None

    def fetch_day(self, day_iso, nb_pages=DEFAULT_NB_PAGES):
        return self._with_auth_retry(lambda: self._fetch_day(day_iso, nb_pages))

    def fetch_modal(self, modal_id):
        return self._with_auth_retry(lambda: self._fetch_modal(modal_id))

    def _with_auth_retry(self, action):
        self._ensure_auth()
        try:
            return action()
        except RtlPlusEpgError as exc:
            if "498" not in str(exc):
                raise
            self._bearer = None
            self._bedrock_token = None
            self._ensure_auth()
            return action()

    def _ensure_auth(self):
        if self._bearer is None:
            self._bearer = self._fetch_bearer_token()
        if self._bedrock_token is None:
            self._bedrock_token = self._fetch_bedrock_token(self._bearer)
        return self._bearer, self._bedrock_token

    def _fetch_bearer_token(self):
        body = urlencode({
            "client_id": OIDC_CLIENT_ID,
            "client_secret": OIDC_CLIENT_SECRET,
            "grant_type": "client_credentials",
        })
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        request = self._make_request(
            OIDC_TOKEN_URL,
            data=body,
            headers={
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        raw = self._open(request).read()
        data = self._decode_json(raw)
        token = data.get("access_token")
        if not token:
            raise RtlPlusEpgError("RTL+ lieferte keinen access_token in der OIDC-Antwort.")
        return token

    def _fetch_bedrock_token(self, bearer):
        device_id = "_luid_" + str(uuid.uuid4())
        request = self._make_request(
            FRONT_AUTH_URL,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Authorization": "Bearer " + bearer,
                "X-Customer-Name": self.customer_name,
                "X-Client-Release": self.client_release,
                "x-auth-device-name": "Windows - Firefox",
                "x-auth-device-player-size-width": "1920",
                "x-auth-device-player-size-height": "1041",
                "x-auth-device-id": device_id,
            },
        )
        raw = self._open(request).read()
        data = self._decode_json(raw)
        token = data.get("token")
        if not token:
            raise RtlPlusEpgError("RTL+ lieferte keinen Bedrock-Token.")
        return token

    def _fetch_day(self, day_iso, nb_pages):
        query = urlencode({"day": day_iso, "nbPages": nb_pages})
        request = self._make_request(
            EPG_GRID_URL + "?" + query,
            headers=self._epg_headers(),
        )
        raw = self._open(request).read()
        return self._decode_json(raw)

    def _fetch_modal(self, modal_id):
        request = self._make_request(
            MODAL_URL_TEMPLATE % modal_id,
            headers=self._epg_headers(),
        )
        raw = self._open(request).read()
        return self._decode_json(raw)

    def _epg_headers(self):
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Authorization": "Bearer " + self._bearer,
            "X-Bedrock-Token": self._bedrock_token,
            "X-Customer-Name": self.customer_name,
            "X-Client-Release": self.client_release,
            "X-Location": "https://plus.rtl.de/tv-programm",
            "Origin": "https://plus.rtl.de",
            "Referer": "https://plus.rtl.de/",
        }

    def _make_request(self, url, data=None, headers=None):
        headers = headers or {}
        return urllib2.Request(url, data=data, headers=headers)

    def _open(self, request):
        try:
            return urllib2.urlopen(request, timeout=self.timeout)
        except HTTPError as exc:
            raise RtlPlusEpgError(self._build_http_error_message(exc))
        except URLError as exc:
            raise RtlPlusEpgError(self._build_url_error_message(exc))
        except socket.timeout:
            raise RtlPlusEpgError(self._timeout_message())
        except SSL_ERROR_TYPES as exc:
            raise RtlPlusEpgError(self._build_ssl_error_message(exc))
        except Exception as exc:
            raise RtlPlusEpgError("RTL+ Anfrage fehlgeschlagen: %s" % exc)

    def _build_url_error_message(self, exc):
        reason = getattr(exc, "reason", exc)
        reason_text = str(reason)
        lower = reason_text.lower()
        if looks_like_ssl_error(reason, lower):
            return self._build_ssl_error_message(reason)
        if self._looks_like_dns_error(lower):
            return (
                u"RTL+ ist nicht erreichbar: DNS-Auflösung fehlgeschlagen. "
                u"Bitte Internetverbindung und Nameserver der Box prüfen. Details: %s"
            ) % reason_text
        if self._looks_like_timeout(lower):
            return self._timeout_message(u" Details: %s" % reason_text)
        if "protocol not supported" in lower:
            return (
                u"RTL+ ist nicht erreichbar: HTTPS/Netzwerk-Stack der Box meldet "
                u"'Protocol not supported'. Bitte Netzwerk, DNS und Datum/Uhrzeit der Box "
                u"prüfen. Details: %s"
            ) % reason_text
        return (
            u"RTL+ ist nicht erreichbar: Netzwerkfehler. "
            u"Bitte Internetverbindung der Box prüfen und später erneut versuchen. Details: %s"
        ) % reason_text

    def _build_ssl_error_message(self, exc):
        return build_ssl_message(u"RTL+", exc)

    def _timeout_message(self, suffix=""):
        return (
            u"RTL+ antwortet nicht innerhalb von %d Sekunden. "
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
        if code == 498:
            return "RTL+ meldet HTTP 498 (Token expired/invalid): %s" % body[:300]
        if code >= 500:
            return "RTL+ meldet Serverfehler HTTP %s. Bitte später erneut versuchen." % exc.code
        if code == 403:
            return "RTL+ blockiert die Anfrage mit HTTP 403."
        return "RTL+ meldet HTTP %s für %s: %s" % (exc.code, exc.geturl(), body[:300])

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
                raise RtlPlusEpgError("RTL+ lieferte HTML statt JSON. Webseite/API ist gerade nicht nutzbar.")
            raise RtlPlusEpgError("RTL+ lieferte ungültiges JSON: %s" % exc)


def fetch_day(day_iso, nb_pages=DEFAULT_NB_PAGES):
    """Public helper for fetching the RTL+ epg_grid for a single day."""
    client = RtlPlusEpgClient()
    return client.fetch_day(day_iso, nb_pages=nb_pages)


def fetch_modal(modal_id):
    """Public helper for fetching the RTL+ programme description modal."""
    client = RtlPlusEpgClient()
    return client.fetch_modal(modal_id)


def _build_argument_parser():
    if ArgumentParser is None:
        raise RtlPlusEpgError("argparse is not available in this Python installation")

    parser = ArgumentParser(description="Fetch the RTL+ EPG grid for a day")
    parser.add_argument("--day", dest="day_iso", required=True, help="Day, e.g. 2026-06-21")
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
        data = fetch_day(args.day_iso)
    except RtlPlusEpgError as exc:
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
