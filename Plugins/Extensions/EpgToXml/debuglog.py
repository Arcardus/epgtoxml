# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import os
import time
import traceback

from .compat import ensure_text
from .paths import DEBUG_LOG_MAX_BYTES, DEBUG_LOG_PATH, DEBUG_LOG_ROTATED_PATH


def _ensure_parent(path):
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)


def _rotate_if_needed(path=DEBUG_LOG_PATH):
    try:
        if os.path.exists(path) and os.path.getsize(path) > DEBUG_LOG_MAX_BYTES:
            if os.path.exists(DEBUG_LOG_ROTATED_PATH):
                try:
                    os.remove(DEBUG_LOG_ROTATED_PATH)
                except Exception:
                    pass
            os.rename(path, DEBUG_LOG_ROTATED_PATH)
    except Exception:
        pass


def debug_enabled():
    try:
        from .settings import is_debug_enabled
        return is_debug_enabled()
    except Exception:
        return True


def write_debug(message, category="debug", force=False):
    if not force and not debug_enabled():
        return
    try:
        _ensure_parent(DEBUG_LOG_PATH)
        _rotate_if_needed(DEBUG_LOG_PATH)
        line = "%s [%s] %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"),
            ensure_text(category),
            ensure_text(message),
        )
        handle = open(DEBUG_LOG_PATH, "ab")
        try:
            handle.write(line.encode("utf-8"))
        finally:
            handle.close()
    except Exception:
        pass


def write_exception(context, exc=None):
    if exc is None:
        exc = ""
    text = ensure_text(context)
    if exc:
        text += ": " + ensure_text(exc)
    try:
        trace = traceback.format_exc()
        if trace and "None" not in trace:
            text += "\n" + ensure_text(trace)
    except Exception:
        pass
    write_debug(text, "exception", force=True)
