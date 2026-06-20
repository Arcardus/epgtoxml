#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import, print_function

import argparse
import os

try:
    from . import package_common
except (ImportError, ValueError):
    import package_common


def write_ipk(root, output_dir=None, version_override=None):
    return package_common.write_package(
        root,
        "ipk",
        os.path.join(root, "packaging", "opkg", "control"),
        output_dir,
        version_override,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the EpgToXml VTi OPKG package")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--version-override", default=None,
                        help="Override version instead of reading from __init__.py")
    args = parser.parse_args(argv)
    path = write_ipk(package_common.repo_root(), args.output_dir, args.version_override)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
