# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
import gzip
import os
import tarfile
import tempfile
import unittest

from tools import build_deb, build_ipk


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


def tar_mode(data, member_name):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        tmp.write(data)
        tmp.close()
        handle = gzip.open(tmp.name, "rb")
        try:
            tar = tarfile.open(fileobj=handle, mode="r:")
            try:
                return tar.getmember(member_name).mode
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
        self.assertEqual(build_deb.read_version(ROOT), "0.6.4")

    def test_builds_deb_with_expected_control_and_payload(self):
        tmp = tempfile.mkdtemp()
        deb_path = build_deb.write_deb(ROOT, tmp)
        self.assertEqual(
            os.path.basename(deb_path),
            "enigma2-plugin-extensions-epgtoxml_0.6.4_all.deb",
        )

        members = read_ar_members(deb_path)
        self.assertEqual(members["debian-binary"], b"2.0\n")
        self.assertIn("control.tar.gz", members)
        self.assertIn("data.tar.gz", members)

        control = tar_text(members["control.tar.gz"], "./control")
        postinst = tar_text(members["control.tar.gz"], "./postinst")
        self.assertIn("Package: enigma2-plugin-extensions-epgtoxml", control)
        self.assertIn("Version: 0.6.4", control)
        self.assertIn("Architecture: all", control)
        self.assertIn("Maintainer: Arcardy", control)
        self.assertIn("Homepage: https://github.com/Arcardus/epgtoxml", control)
        self.assertIn('PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/EpgToXml"', postinst)
        self.assertIn('CONFIG_DIR="/etc/epgtoxml"', postinst)
        self.assertIn('IMPORT_DIR="/etc/epgtoxml/import"', postinst)
        self.assertIn('LEGACY_CONFIG_DIR="/media/hdd/epgtoxml"', postinst)
        self.assertIn("tasks.json", postinst)
        self.assertIn("settings.json", postinst)
        self.assertIn('name "*.pyc"', postinst)
        self.assertIn('name "*.pyo"', postinst)

        names = tar_names(members["data.tar.gz"])
        self.assertIn("./usr/lib/enigma2/python/Plugins/Extensions/EpgToXml/plugin.py", names)
        self.assertIn("./usr/lib/enigma2/python/Plugins/Extensions/EpgToXml/EPGtoXML.png", names)
        self.assertIn("./usr/lib/enigma2/python/Plugins/Extensions/EpgToXml/EPGtoXML.svg", names)
        # embedded EPG import engine must be packaged (no external EPGImport plugin)
        self.assertIn("./usr/lib/enigma2/python/Plugins/Extensions/EpgToXml/epgimport_engine/EPGImport.py", names)
        self.assertIn("./usr/lib/enigma2/python/Plugins/Extensions/EpgToXml/epgimport_engine/epgdb.py", names)
        self.assertIn("./usr/share/doc/enigma2-plugin-extensions-epgtoxml/copyright", names)
        self.assertIn("./usr/share/doc/enigma2-plugin-extensions-epgtoxml/LICENSE.MIT", names)
        self.assertIn("./usr/share/doc/enigma2-plugin-extensions-epgtoxml/NOTICE", names)
        for name in names:
            self.assertNotIn("__pycache__", name)
            self.assertFalse(name.endswith(".pyc"))
            self.assertFalse(name.endswith(".pyo"))
            self.assertFalse(name.endswith("/" + "xml" + "tv.py"))
            self.assertNotIn("epgtoxml-debug", name)
            self.assertNotIn("enigma2xmltv-master", name)
            self.assertNotIn("sky-epg-scraper", name)

    def test_builds_reproducible_ipk_for_vti(self):
        first_dir = tempfile.mkdtemp()
        second_dir = tempfile.mkdtemp()
        first_path = build_ipk.write_ipk(ROOT, first_dir)
        second_path = build_ipk.write_ipk(ROOT, second_dir)
        self.assertEqual(
            os.path.basename(first_path),
            "enigma2-plugin-extensions-epgtoxml_0.6.4_all.ipk",
        )
        with open(first_path, "rb") as first, open(second_path, "rb") as second:
            self.assertEqual(first.read(), second.read())

        members = read_ar_members(first_path)
        self.assertEqual(members["debian-binary"], b"2.0\n")
        self.assertEqual(
            sorted(members),
            ["control.tar.gz", "data.tar.gz", "debian-binary"],
        )
        control = tar_text(members["control.tar.gz"], "./control")
        postinst = tar_text(members["control.tar.gz"], "./postinst")
        self.assertIn("Package: enigma2-plugin-extensions-epgtoxml", control)
        self.assertIn("Version: 0.6.4", control)
        self.assertIn("Architecture: all", control)
        self.assertIn("python-compression", control)
        self.assertIn("python-netclient", control)
        self.assertIn("python-twisted-core", control)
        self.assertIn("python-twisted-web", control)
        self.assertIn("python-six", control)
        self.assertIn("VTi 15", control)
        self.assertEqual(tar_mode(members["control.tar.gz"], "./postinst"), 0o755)
        self.assertIn('CONFIG_DIR="/etc/epgtoxml"', postinst)

        names = tar_names(members["data.tar.gz"])
        self.assertIn(
            "./usr/lib/enigma2/python/Plugins/Extensions/EpgToXml/plugin.py",
            names,
        )
        self.assertIn(
            "./usr/lib/enigma2/python/Plugins/Extensions/EpgToXml/"
            "epgimport_engine/epgdat.py",
            names,
        )
        self.assertIn(
            "./usr/lib/enigma2/python/Plugins/Extensions/EpgToXml/EPGtoXML.png",
            names,
        )
        for name in names:
            self.assertNotIn("__pycache__", name)
            self.assertFalse(name.endswith(".pyc"))
            self.assertFalse(name.endswith(".pyo"))

    def test_version_override_is_shared_by_deb_and_ipk(self):
        output = tempfile.mkdtemp()
        version = "0.6.3~unstable+abc123"
        deb_path = build_deb.write_deb(ROOT, output, version)
        ipk_path = build_ipk.write_ipk(ROOT, output, version)
        self.assertIn("_%s_all.deb" % version, deb_path)
        self.assertIn("_%s_all.ipk" % version, ipk_path)

    def test_license_is_gplv2_with_arcardy_copyright(self):
        license_path = os.path.join(ROOT, "LICENSE")
        handle = open(license_path, "rb")
        try:
            text = handle.read().decode("utf-8")
        finally:
            handle.close()
        # The combined work is governed by the GPLv2 full text.
        self.assertIn("GNU GENERAL PUBLIC LICENSE", text)
        self.assertIn("Version 2", text)
        self.assertIn("Copyright (c) 2026 Arcardy", text)
        # ... and it points to the MIT text used for our own files.
        self.assertIn("LICENSE.MIT", text)

    def test_mit_license_file_for_own_code(self):
        mit_path = os.path.join(ROOT, "LICENSE.MIT")
        handle = open(mit_path, "rb")
        try:
            text = handle.read().decode("utf-8")
        finally:
            handle.close()
        self.assertIn("MIT License", text)
        self.assertIn("Copyright (c) 2026 Arcardy", text)

    def test_notice_credits_embedded_epgimport_engine(self):
        notice_path = os.path.join(ROOT, "NOTICE")
        handle = open(notice_path, "rb")
        try:
            text = handle.read().decode("utf-8")
        finally:
            handle.close()
        self.assertIn("epgimport_engine", text)
        self.assertIn("GPLv2", text)


if __name__ == "__main__":
    unittest.main()
