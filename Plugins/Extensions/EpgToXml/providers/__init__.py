# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

from .ard_de import ArdDeProvider
from .dazn_de import DaznDeProvider
from .hdplus_de import HdPlusProvider
from .redbull_tv import RedBullTvProvider
from .rtl_plus import RtlPlusDeProvider
from .zdf_de import ZdfDeProvider


def get_providers():
    return [
        HdPlusProvider(), DaznDeProvider(), ArdDeProvider(), ZdfDeProvider(),
        RedBullTvProvider(), RtlPlusDeProvider(),
    ]


def get_provider(provider_id):
    for provider in get_providers():
        if provider.id == provider_id:
            return provider
    raise KeyError(provider_id)
