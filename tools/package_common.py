#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import gzip
import io
import os
import re
import tarfile


PACKAGE = "enigma2-plugin-extensions-epgtoxml"
ARCHITECTURE = "all"
PLUGIN_REL = os.path.join("Plugins", "Extensions", "EpgToXml")
PLUGIN_TARGET = "./usr/lib/enigma2/python/Plugins/Extensions/EpgToXml"
DOC_TARGET = "./usr/share/doc/" + PACKAGE
DEFAULT_EXCLUDES = (".pyc", ".pyo")


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_version(root):
    init_path = os.path.join(root, PLUGIN_REL, "__init__.py")
    return_match = re.search(
        r'VERSION\s*=\s*"([^"]+)"',
        read_text(init_path),
    )
    if not return_match:
        raise RuntimeError("VERSION not found in " + init_path)
    return return_match.group(1)


def read_text(path):
    handle = open(path, "rb")
    try:
        return handle.read().decode("utf-8")
    finally:
        handle.close()


def should_include_plugin_file(path):
    parts = path.replace("\\", "/").split("/")
    if "__pycache__" in parts:
        return False
    if path.endswith(DEFAULT_EXCLUDES):
        return False
    return True


def iter_plugin_files(root):
    plugin_root = os.path.join(root, PLUGIN_REL)
    for current, dirs, files in os.walk(plugin_root):
        dirs[:] = sorted(item for item in dirs if item != "__pycache__")
        for filename in sorted(files):
            source = os.path.join(current, filename)
            if not should_include_plugin_file(source):
                continue
            rel = os.path.relpath(source, plugin_root).replace("\\", "/")
            yield source, PLUGIN_TARGET + "/" + rel


def tar_add_bytes(tar, name, data, mode=0o644):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    tar.addfile(info, io.BytesIO(data))


def tar_add_dir(tar, name, added):
    name = name.rstrip("/")
    if not name or name in added:
        return
    parent = os.path.dirname(name)
    if parent and parent != ".":
        tar_add_dir(tar, parent, added)
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    tar.addfile(info)
    added.add(name)


def tar_add_file(tar, source, name, mode=0o644):
    stat_result = os.stat(source)
    info = tarfile.TarInfo(name)
    info.size = stat_result.st_size
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    handle = open(source, "rb")
    try:
        tar.addfile(info, handle)
    finally:
        handle.close()


def gzip_bytes(data):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as handle:
        handle.write(data)
    return output.getvalue()


def make_tar_gz(populate):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.GNU_FORMAT) as tar:
        populate(tar)
    return gzip_bytes(output.getvalue())


def make_control_tar(root, version, control_path):
    control = read_text(control_path).replace("@VERSION@", version).encode("utf-8")
    postinst_path = os.path.join(root, "packaging", "common", "postinst")
    handle = open(postinst_path, "rb")
    try:
        postinst = handle.read()
    finally:
        handle.close()

    def populate(tar):
        tar_add_bytes(tar, "./control", control, 0o644)
        tar_add_bytes(tar, "./postinst", postinst, 0o755)

    return make_tar_gz(populate)


def make_data_tar(root):
    def populate(tar):
        added_dirs = set()
        for source, target in iter_plugin_files(root):
            tar_add_dir(tar, os.path.dirname(target), added_dirs)
            tar_add_file(tar, source, target)
        tar_add_dir(tar, DOC_TARGET, added_dirs)
        tar_add_file(tar, os.path.join(root, "LICENSE"), DOC_TARGET + "/copyright")
        tar_add_file(tar, os.path.join(root, "LICENSE.MIT"), DOC_TARGET + "/LICENSE.MIT")
        tar_add_file(tar, os.path.join(root, "NOTICE"), DOC_TARGET + "/NOTICE")
        tar_add_file(tar, os.path.join(root, "README.md"), DOC_TARGET + "/README.md")
        changelog = os.path.join(root, "CHANGELOG.md")
        if os.path.exists(changelog):
            tar_add_file(tar, changelog, DOC_TARGET + "/changelog")

    return make_tar_gz(populate)


def ar_member(name, data):
    encoded_name = name.encode("ascii")
    if len(encoded_name) > 16:
        raise RuntimeError("ar member name too long: " + name)
    header = (
        encoded_name.ljust(16, b" ")
        + b"0".ljust(12, b" ")
        + b"0".ljust(6, b" ")
        + b"0".ljust(6, b" ")
        + ("%o" % 0o100644).encode("ascii").ljust(8, b" ")
        + str(len(data)).encode("ascii").ljust(10, b" ")
        + b"`\n"
    )
    body = header + data
    if len(data) % 2:
        body += b"\n"
    return body


def write_package(root, extension, control_path, output_dir=None, version_override=None):
    version = version_override if version_override is not None else read_version(root)
    if output_dir is None:
        output_dir = os.path.join(root, "dist")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    filename = "%s_%s_%s.%s" % (PACKAGE, version, ARCHITECTURE, extension)
    output_path = os.path.join(output_dir, filename)
    content = (
        b"!<arch>\n"
        + ar_member("debian-binary", b"2.0\n")
        + ar_member("control.tar.gz", make_control_tar(root, version, control_path))
        + ar_member("data.tar.gz", make_data_tar(root))
    )
    handle = open(output_path, "wb")
    try:
        handle.write(content)
    finally:
        handle.close()
    return output_path
