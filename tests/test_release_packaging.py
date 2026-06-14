import gzip
import os
import tarfile
import tempfile
import unittest

from tools import build_deb


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_ar_members(path):
    handle = open(path, "rb")
    try:
        data = handle.read()
    finally:
        handle.close()
    if not data.startswith(b"!<arch>\n"):
        raise AssertionError("not an ar archive")
    offset = 8
    members = {}
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) < 60:
            break
        name = header[:16].decode("ascii").strip()
        size = int(header[48:58].decode("ascii").strip())
        start = offset + 60
        end = start + size
        members[name] = data[start:end]
        offset = end + (size % 2)
    return members


def tar_names(data):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        tmp.write(data)
        tmp.close()
        handle = gzip.open(tmp.name, "rb")
        try:
            tar = tarfile.open(fileobj=handle, mode="r:")
            try:
                return tar.getnames()
            finally:
                tar.close()
        finally:
            handle.close()
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def tar_text(data, member_name):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        tmp.write(data)
        tmp.close()
        handle = gzip.open(tmp.name, "rb")
        try:
            tar = tarfile.open(fileobj=handle, mode="r:")
            try:
                extracted = tar.extractfile(member_name)
                return extracted.read().decode("utf-8")
            finally:
                tar.close()
        finally:
            handle.close()
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


class ReleasePackagingTests(unittest.TestCase):
    def test_version_is_release_version(self):
        self.assertEqual(build_deb.read_version(ROOT), "0.5.1")

    def test_builds_deb_with_expected_control_and_payload(self):
        tmp = tempfile.mkdtemp()
        deb_path = build_deb.write_deb(ROOT, tmp)
        self.assertEqual(
            os.path.basename(deb_path),
            "enigma2-plugin-extensions-epgtoxml_0.5.1_all.deb",
        )

        members = read_ar_members(deb_path)
        self.assertEqual(members["debian-binary"], b"2.0\n")
        self.assertIn("control.tar.gz", members)
        self.assertIn("data.tar.gz", members)

        control = tar_text(members["control.tar.gz"], "./control")
        postinst = tar_text(members["control.tar.gz"], "./postinst")
        self.assertIn("Package: enigma2-plugin-extensions-epgtoxml", control)
        self.assertIn("Version: 0.5.1", control)
        self.assertIn("Architecture: all", control)
        self.assertIn("Maintainer: Arcardy", control)
        self.assertIn('PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/EpgToXml"', postinst)
        self.assertIn('name "*.pyc"', postinst)
        self.assertIn('name "*.pyo"', postinst)

        names = tar_names(members["data.tar.gz"])
        self.assertIn("./usr/lib/enigma2/python/Plugins/Extensions/EpgToXml/plugin.py", names)
        self.assertIn("./usr/share/doc/enigma2-plugin-extensions-epgtoxml/copyright", names)
        for name in names:
            self.assertNotIn("__pycache__", name)
            self.assertFalse(name.endswith(".pyc"))
            self.assertFalse(name.endswith(".pyo"))
            self.assertFalse(name.endswith("/" + "xml" + "tv.py"))
            self.assertNotIn("epgtoxml-debug", name)
            self.assertNotIn("enigma2xmltv-master", name)
            self.assertNotIn("sky-epg-scraper", name)

    def test_license_mentions_arcardy_and_mit(self):
        license_path = os.path.join(ROOT, "LICENSE")
        handle = open(license_path, "rb")
        try:
            text = handle.read().decode("utf-8")
        finally:
            handle.close()
        self.assertIn("MIT License", text)
        self.assertIn("Copyright (c) 2026 Arcardy", text)


if __name__ == "__main__":
    unittest.main()
