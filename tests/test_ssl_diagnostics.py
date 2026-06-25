# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import ssl
import unittest

from Plugins.Extensions.EpgToXml.ssl_diagnostics import (
    build_ssl_message,
    diagnose_ssl_error,
    looks_like_ssl_error,
)


class SslDiagnosticsTests(unittest.TestCase):
    def test_diagnoses_expired_certificate(self):
        detail = diagnose_ssl_error(ssl.SSLError("certificate verify failed: certificate has expired"))
        self.assertIn("abgelaufen", detail)

    def test_diagnoses_not_yet_valid_certificate(self):
        detail = diagnose_ssl_error(ssl.SSLError("certificate verify failed: certificate is not yet valid"))
        self.assertIn("Systemzeit", detail)

    def test_diagnoses_missing_root_ca(self):
        detail = diagnose_ssl_error(
            ssl.SSLError("certificate verify failed: unable to get local issuer certificate")
        )
        self.assertIn("Trust-Store", detail)

    def test_diagnoses_hostname_mismatch(self):
        detail = diagnose_ssl_error(Exception("hostname 'foo' doesn't match 'bar'"))
        self.assertIn("Hostname-Mismatch", detail)

    def test_unknown_text_returns_none(self):
        self.assertIsNone(diagnose_ssl_error(Exception("some unrelated network problem")))

    def test_looks_like_ssl_error_detects_keyword(self):
        self.assertTrue(looks_like_ssl_error(Exception("handshake failure"), "handshake failure"))
        self.assertFalse(looks_like_ssl_error(Exception("name not known"), "name not known"))

    def test_build_ssl_message_includes_diagnosis_and_legacy_hints(self):
        message = build_ssl_message("Sky.de", ssl.SSLError("certificate verify failed: certificate has expired"))
        self.assertIn("abgelaufen", message)
        self.assertIn("SSL", message)
        self.assertIn("Datum", message)
        self.assertIn("Uhrzeit", message)
        self.assertIn("prüfen", message)

    def test_build_ssl_message_without_specific_diagnosis(self):
        message = build_ssl_message("DAZN", Exception("generic ssl failure"))
        self.assertIn("DAZN SSL-Verbindung fehlgeschlagen.", message)
        self.assertIn("Datum", message)


if __name__ == "__main__":
    unittest.main()
