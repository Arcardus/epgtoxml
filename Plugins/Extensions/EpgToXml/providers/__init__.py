# -*- coding: utf-8 -*-
from __future__ import absolute_import

from .sky_de import SkyDeProvider


def get_providers():
    return [SkyDeProvider()]


def get_provider(provider_id):
    for provider in get_providers():
        if provider.id == provider_id:
            return provider
    raise KeyError(provider_id)
