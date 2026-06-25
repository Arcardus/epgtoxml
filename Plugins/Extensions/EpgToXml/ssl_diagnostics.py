#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
"""Shared SSL/TLS error classification for the EPG HTTP clients.

Turns a generic ssl.SSLError/ssl.CertificateError into a German
plain-text hint (expired cert, missing root CA, hostname mismatch,
wrong system clock, ...) so debug logs and the UI status line show
something more actionable than "SSL-Verbindung fehlgeschlagen".
"""
from __future__ import print_function

import ssl

try:
    SSL_ERROR_TYPES = (ssl.SSLError, ssl.CertificateError)
except AttributeError:
    SSL_ERROR_TYPES = (ssl.SSLError,)


_SSL_KEYWORDS = ("ssl", "certificate", "cert_verify", "tls", "handshake", "wrong version number")

_DIAGNOSES = (
    (
        ("certificate has expired", "certificate expired"),
        u"Das SSL-Zertifikat des Servers ist laut Prüfung abgelaufen (oder die "
        u"Boxzeit liegt bereits nach dessen Ablaufdatum).",
    ),
    (
        ("certificate is not yet valid",),
        u"Das SSL-Zertifikat ist laut Box-Uhrzeit noch nicht gültig. Das deutet "
        u"auf eine falsche/zu alte Systemzeit der Box hin (keine NTP-Synchronisation?).",
    ),
    (
        (
            "unable to get local issuer certificate",
            "unable to get issuer certificate",
            "unable to verify the first certificate",
            "self signed certificate",
            "self-signed certificate",
        ),
        u"Das Root-/Zwischenzertifikat des Servers ist im Zertifikatsspeicher "
        u"(Trust-Store) der Box nicht vorhanden oder veraltet. Möglicherweise "
        u"muss der CA-Zertifikatsspeicher der Box aktualisiert werden.",
    ),
    (
        ("hostname", "doesn't match", "doesn't match any of"),
        u"Der Servername im Zertifikat passt nicht zur aufgerufenen Adresse "
        u"(Hostname-Mismatch).",
    ),
    (
        ("wrong version number", "unsupported protocol", "unknown protocol"),
        u"Box und Server konnten sich auf keine gemeinsame TLS-Version einigen "
        u"(möglicherweise zu altes OpenSSL auf der Box).",
    ),
    (
        ("tlsv1 alert", "alert unknown ca", "alert handshake failure"),
        u"Der Server hat den TLS-Handshake abgelehnt (z. B. unbekannte Root-CA "
        u"oder veraltete Cipher-Suite der Box).",
    ),
    (
        ("certificate verify failed",),
        u"Allgemeiner Zertifikatsprüfungsfehler. Mögliche Ursachen: abgelaufenes "
        u"Zertifikat, fehlendes/veraltetes Root-Zertifikat im Trust-Store der Box "
        u"oder falsche Systemzeit.",
    ),
)


def looks_like_ssl_error(reason, lower_text):
    """Heuristic: does this URLError reason look like an SSL/TLS failure?"""
    if isinstance(reason, SSL_ERROR_TYPES):
        return True
    for keyword in _SSL_KEYWORDS:
        if keyword in lower_text:
            return True
    return False


def diagnose_ssl_error(exc):
    """Classify an SSL/TLS exception and return a German detail sentence, or None."""
    lower = str(exc).lower()
    for keywords, detail in _DIAGNOSES:
        for keyword in keywords:
            if keyword in lower:
                return detail
    return None


def build_ssl_message(product_name, exc):
    """Build the user/debug-log facing SSL failure message for one provider."""
    detail = diagnose_ssl_error(exc)
    if detail:
        prefix = u"%s SSL-Verbindung fehlgeschlagen: %s " % (product_name, detail)
    else:
        prefix = u"%s SSL-Verbindung fehlgeschlagen. " % product_name
    return prefix + (
        u"Bitte Datum/Uhrzeit der Box, DNS/Internetverbindung und Zertifikate "
        u"prüfen. Details: %s"
    ) % str(exc)
