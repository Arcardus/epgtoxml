#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import print_function

import json
import re
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


BASE_URL = "https://api.teleboy.ch"
STATIONS_URL = BASE_URL + "/epg/stations?expand=logos&language=de"
GENRES_URL = BASE_URL + "/epg/genres"
# expand=detail liefert die Volltext-Beschreibung direkt in der Liste mit -- ohne den
# Parameter hat nur etwa die Hälfte der Sendungen überhaupt einen Text
# (short_description), mit ihm alle. Der Detail-Endpunkt /epg/broadcasts/:id wäre die
# Alternative, kostet aber einen Request pro Sendung; so bleibt es bei einem einzigen.
# Preis: die Antwort wächst von rund 90 KB auf rund 300 KB pro Sender und Woche.
BROADCASTS_URL_TEMPLATE = (
    BASE_URL + "/epg/broadcasts?begin=%s&end=%s&station=%d&limit=%d&skip=%d"
    "&sort=station&expand=detail"
)

# Seite, aus der der API-Key gelesen wird. https://www.teleboy.ch/ ist ein 302 und
# enthält den Key nicht -- die Programmseite schon.
KEY_PAGE_URL = "https://www.teleboy.ch/programm"

# Die API deckelt limit hart bei 300, größere Werte werden stillschweigend gekappt.
PAGE_LIMIT = 300

DEFAULT_TIMEOUT = 8

# Obergrenze für den HTML-Download der Key-Seite (real ~520 KB). Schützt eine Box mit
# wenig RAM davor, eine unerwartet große Antwort komplett einzulesen.
MAX_KEY_PAGE_BYTES = 2 * 1024 * 1024

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:154.0) "
    "Gecko/20100101 Firefox/154.0"
)

# Der Key steht als AngularJS-Konstante im HTML:
#     tvapiKey:                   '541f13d5…',
# Zweite Stufe als Netz für den Fall, dass der Bezeichner umbenannt wird: auf der
# gesamten Seite existiert genau ein 64-stelliger Hex-String.
_TVAPIKEY_RE = re.compile(r"tvapiKey\s*[:=]\s*['\"]([0-9a-fA-F]{64})['\"]")
_ANY_KEY_RE = re.compile(r"[0-9a-fA-F]{64}")


class TeleboyEpgError(Exception):
    pass


class TeleboyAuthError(TeleboyEpgError):
    """HTTP 403 -- der API-Key fehlt, ist abgelaufen oder wurde rotiert.

    Eigene Klasse statt eines Stringvergleichs auf der Fehlermeldung, damit der
    Retry-Pfad nicht an einer Textänderung zerbricht.
    """
    pass


class TeleboyEpgClient(object):
    """Minimaler Teleboy-EPG-Client für Python 2 / Enigma2.

    Die API braucht einen einzigen Header (``x-teleboy-apikey``) und keinerlei
    Login. Der Key steht öffentlich im HTML der Webseite; er wird nur dann von dort
    geholt, wenn keiner übergeben wurde oder der übergebene mit HTTP 403 abgelehnt
    wird. Ob der Key erneuert wurde, verrät ``api_key_refreshed`` -- der Provider
    persistiert ihn dann über ``teleboy_keystore``.

    Der Client importiert bewusst kein Projektmodul außer ``ssl_diagnostics``, damit
    die CLI am Ende dieser Datei auch als eigenständiges Skript läuft.
    """

    def __init__(self, api_key=None, user_agent=DEFAULT_USER_AGENT, timeout=DEFAULT_TIMEOUT):
        self.api_key = (api_key or "").strip()
        self.user_agent = user_agent
        self.timeout = timeout
        # Signalisiert dem Provider, dass der Key neu geholt wurde und gespeichert
        # werden sollte.
        self.api_key_refreshed = False
        # Loop-Bremse: pro Instanz wird die HTML-Seite höchstens einmal gelesen.
        self._key_attempted = False

    # -- öffentliche Abrufe ------------------------------------------------

    def fetch_stations(self):
        return self._with_key_retry(lambda: self._get_json(STATIONS_URL))

    def fetch_genres(self):
        return self._with_key_retry(lambda: self._get_json(GENRES_URL))

    def fetch_broadcasts(self, station_id, begin, end, limit=PAGE_LIMIT, skip=0):
        """Ein Zeitfenster für einen Sender.

        ``begin``/``end`` im Format ``YYYY-MM-DD+HH:MM:SS``. Der Server ignoriert
        einen mitgegebenen UTC-Offset und liest die Angabe immer als Schweizer
        Ortszeit, deshalb wird hier bewusst kein Offset angehängt.
        """
        url = BROADCASTS_URL_TEMPLATE % (
            begin, end, int(station_id), int(limit), int(skip),
        )
        return self._with_key_retry(lambda: self._get_json(url))

    # -- Key-Beschaffung ---------------------------------------------------

    def _with_key_retry(self, action):
        self._ensure_key()
        try:
            return action()
        except TeleboyAuthError:
            if self._key_attempted:
                # In diesem Lauf wurde bereits ein frischer Key geholt -- ein
                # weiterer Versuch würde nur dasselbe Ergebnis liefern.
                raise
            self.api_key = self._scrape_api_key()
            self.api_key_refreshed = True
            return action()

    def _ensure_key(self):
        if not self.api_key:
            self.api_key = self._scrape_api_key()
            self.api_key_refreshed = True

    def _scrape_api_key(self):
        # Vor dem Request setzen: selbst wenn das Scraping fehlschlägt, darf es
        # innerhalb einer Instanz kein zweites Mal versucht werden.
        self._key_attempted = True
        request = self._make_request(KEY_PAGE_URL, headers={
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-CH,de;q=0.9",
        })
        raw = self._open(request).read(MAX_KEY_PAGE_BYTES)
        if isinstance(raw, bytes):
            # Bewusst nicht über _decode_json: das würde HTML als Fehler werten.
            text = raw.decode("utf-8", "replace")
        else:
            text = raw
        match = _TVAPIKEY_RE.search(text)
        if not match:
            match = _ANY_KEY_RE.search(text)
            if match:
                return match.group(0)
            raise TeleboyEpgError(
                u"Teleboy API-Key konnte nicht aus der Programmseite gelesen werden. "
                u"Der Aufbau der Webseite hat sich vermutlich geändert."
            )
        return match.group(1)

    # -- HTTP --------------------------------------------------------------

    def _get_json(self, url):
        request = self._make_request(url, headers=self._epg_headers())
        raw = self._open(request).read()
        data = self._decode_json(raw)
        if isinstance(data, dict) and not data.get("success", True):
            raise TeleboyEpgError(
                u"Teleboy meldet einen Fehler: %s" % (
                    data.get("message") or data.get("error") or u"unbekannte Ursache",
                )
            )
        return data

    def _epg_headers(self):
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "de-CH,de;q=0.9",
            "x-teleboy-apikey": self.api_key,
        }

    def _make_request(self, url, data=None, headers=None):
        headers = headers or {}
        return urllib2.Request(url, data=data, headers=headers)

    def _open(self, request):
        try:
            return urllib2.urlopen(request, timeout=self.timeout)
        except HTTPError as exc:
            message = self._build_http_error_message(exc)
            if int(getattr(exc, "code", 0) or 0) == 403:
                raise TeleboyAuthError(message)
            raise TeleboyEpgError(message)
        except URLError as exc:
            raise TeleboyEpgError(self._build_url_error_message(exc))
        except socket.timeout:
            raise TeleboyEpgError(self._timeout_message())
        except SSL_ERROR_TYPES as exc:
            raise TeleboyEpgError(self._build_ssl_error_message(exc))
        except Exception as exc:
            raise TeleboyEpgError("Teleboy Anfrage fehlgeschlagen: %s" % exc)

    def _build_url_error_message(self, exc):
        reason = getattr(exc, "reason", exc)
        reason_text = str(reason)
        lower = reason_text.lower()
        if looks_like_ssl_error(reason, lower):
            return self._build_ssl_error_message(reason)
        if self._looks_like_dns_error(lower):
            return (
                u"Teleboy ist nicht erreichbar: DNS-Auflösung fehlgeschlagen. "
                u"Bitte Internetverbindung und Nameserver der Box prüfen. Details: %s"
            ) % reason_text
        if self._looks_like_timeout(lower):
            return self._timeout_message(u" Details: %s" % reason_text)
        if "protocol not supported" in lower:
            return (
                u"Teleboy ist nicht erreichbar: HTTPS/Netzwerk-Stack der Box meldet "
                u"'Protocol not supported'. Bitte Netzwerk, DNS und Datum/Uhrzeit der Box "
                u"prüfen. Details: %s"
            ) % reason_text
        return (
            u"Teleboy ist nicht erreichbar: Netzwerkfehler. "
            u"Bitte Internetverbindung der Box prüfen und später erneut versuchen. Details: %s"
        ) % reason_text

    def _build_ssl_error_message(self, exc):
        return build_ssl_message(u"Teleboy", exc)

    def _timeout_message(self, suffix=""):
        return (
            u"Teleboy antwortet nicht innerhalb von %d Sekunden. "
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
        if code == 403:
            return (
                u"Teleboy lehnt die Anfrage ab (HTTP 403). Der API-Key ist ungültig "
                u"oder der Zugriff wird von diesem Anschluss aus blockiert."
            )
        if code == 404:
            return u"Teleboy kennt diesen Sender/Zeitraum nicht (HTTP 404)."
        if code >= 500:
            return u"Teleboy meldet Serverfehler HTTP %s. Bitte später erneut versuchen." % exc.code
        return u"Teleboy meldet HTTP %s für %s: %s" % (exc.code, exc.geturl(), body[:300])

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
                raise TeleboyEpgError(
                    "Teleboy lieferte HTML statt JSON. Webseite/API ist gerade nicht nutzbar."
                )
            raise TeleboyEpgError("Teleboy lieferte ungültiges JSON: %s" % exc)


def fetch_stations(api_key=None):
    """Senderliste holen (eigene Client-Instanz -- nur für CLI/Tests)."""
    return TeleboyEpgClient(api_key=api_key).fetch_stations()


def fetch_genres(api_key=None):
    """Genre-Liste holen (eigene Client-Instanz -- nur für CLI/Tests)."""
    return TeleboyEpgClient(api_key=api_key).fetch_genres()


def fetch_broadcasts(station_id, begin, end, limit=PAGE_LIMIT, skip=0, api_key=None):
    """Ein EPG-Fenster holen (eigene Client-Instanz -- nur für CLI/Tests).

    Der Provider benutzt diese Helfer absichtlich *nicht*, sondern hält eine eigene
    Client-Instanz über den ganzen Lauf: sonst würde bei jedem Aufruf erneut die
    ~520 KB große HTML-Seite für den API-Key geladen.
    """
    client = TeleboyEpgClient(api_key=api_key)
    return client.fetch_broadcasts(station_id, begin, end, limit=limit, skip=skip)


def fetch_api_key():
    """Den aktuellen API-Key aus der Teleboy-Webseite lesen."""
    return TeleboyEpgClient()._scrape_api_key()


def _build_argument_parser():
    if ArgumentParser is None:
        raise TeleboyEpgError("argparse is not available in this Python installation")

    parser = ArgumentParser(description="Fetch Teleboy EPG data")
    parser.add_argument("--stations", action="store_true", help="Senderliste abrufen")
    parser.add_argument("--genres", action="store_true", help="Genre-Liste abrufen")
    parser.add_argument("--key", action="store_true", help="Nur den API-Key ausgeben")
    parser.add_argument("--broadcasts", action="store_true", help="EPG-Fenster abrufen")
    parser.add_argument("--station", dest="station", help="Sender-ID, z.B. 303")
    parser.add_argument("--begin", dest="begin", help="Start, z.B. '2026-07-28+00:00:00'")
    parser.add_argument("--end", dest="end", help="Ende, z.B. '2026-08-01+03:00:00'")
    parser.add_argument("--limit", dest="limit", type=int, default=PAGE_LIMIT)
    parser.add_argument("--skip", dest="skip", type=int, default=0)
    parser.add_argument("--api-key", dest="api_key", default=None, help="Key vorgeben")
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
        if args.key:
            _write_stdout(fetch_api_key() + "\n")
            return 0
        if args.stations:
            data = fetch_stations(api_key=args.api_key)
        elif args.genres:
            data = fetch_genres(api_key=args.api_key)
        elif args.broadcasts:
            if not (args.station and args.begin and args.end):
                sys.stderr.write("ERROR: --broadcasts braucht --station, --begin und --end\n")
                return 1
            data = fetch_broadcasts(
                args.station, args.begin, args.end,
                limit=args.limit, skip=args.skip, api_key=args.api_key,
            )
        else:
            sys.stderr.write("ERROR: bitte --stations, --genres, --broadcasts oder --key angeben\n")
            return 1
    except TeleboyEpgError as exc:
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
