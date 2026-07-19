# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Arcardy
from __future__ import absolute_import

import calendar
import datetime

from .. import hdplus_client
from ..compat import ensure_text
from ..debuglog import write_debug, write_exception


# HD+ hat keine (aufgezeichnete) öffentliche Channel-Discovery-API. Diese Liste
# wurde aus den EPG-Slice-Anfragen der HD+ TV-Guide-Web-App
# (https://tvg-epg.hd-plus-cloud.de) ermittelt (Stand 2026-07-19) und muss von
# Hand gepflegt werden, wenn HD+ Sender hinzufügt, entfernt oder umbenennt. Um
# einen Sender zu ergänzen: die `commonChannel`-ID aus einer
# `/epg/v1/slice/.../<id>`-Anfrage kopieren und hier mit Anzeigenamen eintragen.
HDPLUS_CHANNELS = (
    ("123tv_hd", "1-2-3.tv HD"),
    ("3sat_hd", "3sat HD"),
    ("a_tv_hd", "a.tv HD"),
    ("alpha_hd", "ARD alpha HD"),
    ("anixe", "ANIXE"),
    ("anixe_hd", "ANIXE HD"),
    ("arte_hd", "arte HD"),
    ("atv_hd", "ATV HD"),
    ("baden_tv", "Baden TV"),
    ("bibeltv_hd", "Bibel TV HD"),
    ("bloomberg", "Bloomberg TV"),
    ("br_sued_hd", "BR Süd HD"),
    ("clip_my_horse", "ClipMyHorse.TV"),
    ("comedycentral_hd", "Comedy Central HD"),
    ("crime_time_hd", "Crime Time HD"),
    ("das_erste_hd", "Das Erste HD"),
    ("deluxe_dance_hd", "Deluxe Dance HD"),
    ("deluxe_music_hd", "Deluxe Music HD"),
    ("deluxe_rap_hd", "Deluxe Rap HD"),
    ("deutsches_musik_fernsehen", "Deutsches Musik Fernsehen"),
    ("df1_hd", "DF1 HD"),
    ("dfb_tv", "DFB-TV"),
    ("disney_channel_hd", "Disney Channel HD"),
    ("dmax_hd", "DMAX HD"),
    ("dokusat", "Doku SAT"),
    ("dyn_sportmix_hd", "Dyn Sportmix HD"),
    ("edgesport_hd", "Edge Sport HD"),
    ("esports1_hd", "eSports1 HD"),
    ("euronews_german", "euronews (deutsch)"),
    ("eurosport1_hd", "Eurosport 1 HD"),
    ("ewtn", "EWTN"),
    ("france24_english", "France 24 (English)"),
    ("franken_fernsehen_hd", "Franken Fernsehen HD"),
    ("hgtv", "HGTV"),
    ("hoehenrausch_hd", "Höhenrausch HD"),
    ("hopechannel", "Hope Channel"),
    ("hr_hd", "hr HD"),
    ("hse24_extra_hd", "HSE24 Extra HD"),
    ("hse24_hd", "HSE24 HD"),
    ("hse24_trend_hd", "HSE24 Trend HD"),
    ("juwelo_hd", "Juwelo HD"),
    ("just_cooking_hd", "Just Cooking HD"),
    ("just_fishing_hd", "Just Fishing HD"),
    ("kabel1_hd", "Kabel Eins HD"),
    ("kabel1doku_hd", "Kabel Eins Doku HD"),
    ("kika_hd", "KiKA HD"),
    ("ktv", "K-TV"),
    ("ltv", "L-TV"),
    ("mdr_t_hd", "MDR Thüringen HD"),
    ("melodie_tv", "Melodie TV"),
    ("mtv_hd", "MTV HD"),
    ("muenchen_tv_hd", "München TV HD"),
    ("n24doku", "WELT Doku"),
    ("ndr_sh_hd", "NDR Schleswig-Holstein HD"),
    ("nhk_world", "NHK World Japan"),
    ("nick", "Nickelodeon"),
    ("niederbayern_tv_hd", "Niederbayern TV HD"),
    ("nitro_hd", "RTL Nitro HD"),
    ("ntv_hd", "ntv HD"),
    ("one_hd", "ONE HD"),
    ("one_terra_hd", "One Terra HD"),
    ("orf1_hd", "ORF 1 HD"),
    ("orf2_eu", "ORF 2 Europe"),
    ("orf3_hd", "ORF III HD"),
    ("pearltv_hd", "Pearl.tv HD"),
    ("phoenix", "phoenix"),
    ("pro7_hd", "ProSieben HD"),
    ("pro7maxx_hd", "ProSieben Maxx HD"),
    ("pro7sat1", "ProSiebenSat.1"),
    ("puls4_sd", "PULS 4"),
    ("qvc2_hd", "QVC 2 HD"),
    ("qvc_beauty_hd", "QVC Beauty & Style HD"),
    ("qvc_hd", "QVC HD"),
    ("rbb_berlin_hd", "rbb Berlin HD"),
    ("regiotv", "Regio TV"),
    ("rfo_hd", "RFO HD"),
    ("ric", "RiC"),
    ("rtl2_hd", "RTL II HD"),
    ("rtl_hd", "RTL HD"),
    ("rtl_uhd", "RTL UHD"),
    ("rtlplus_hd", "RTLplus HD"),
    ("sat1_hd", "SAT.1 HD"),
    ("sat1gold_hd", "SAT.1 Gold HD"),
    ("schlager_deluxe", "Schlager Deluxe"),
    ("serien_plus_hd", "Serien+ HD"),
    ("servustv_hd", "ServusTV HD Deutschland"),
    ("shop_lc_hd", "Shop LC HD"),
    ("sixx_hd", "sixx HD"),
    ("sonnenklar_tv_hd", "sonnenklar.TV HD"),
    ("sport1_hd", "SPORT1 HD"),
    ("sport1plus", "SPORT1+"),
    ("sportdigital", "sportdigital fussball"),
    ("sr_hd", "SR Fernsehen HD"),
    ("super_rtl_hd", "SUPER RTL HD"),
    ("swr_bw_hd", "SWR BW HD"),
    ("tagesschau_24_hd", "tagesschau24 HD"),
    ("tele5_hd", "Tele 5 HD"),
    ("telegold", "Telegold"),
    ("tlc_hd", "TLC HD"),
    ("toggoplus", "TOGGO plus"),
    ("tv1_ooe", "TV1 Oberösterreich"),
    ("tv_ingolstadt", "TV Ingolstadt"),
    ("tva", "TVA Ostbayern"),
    ("uhd1", "UHD1 by HD+"),
    ("volksmusik_tv_1", "Volksmusik TV"),
    ("vox_hd", "VOX HD"),
    ("vox_up_hd", "VOXup HD"),
    ("waidwerk", "Waidwerk"),
    ("wdr_k_hd", "WDR Köln HD"),
    ("welt_hd", "WELT HD"),
    ("xplore_hd", "Xplore HD"),
    ("zdf_hd", "ZDF HD"),
    ("zdfinfo_hd", "ZDFinfo HD"),
    ("zdfneo_hd", "ZDFneo HD"),
)

_KNOWN_CHANNEL_IDS = frozenset(cid for cid, _name in HDPLUS_CHANNELS)

# categories/genres kommen als englische Schlüssel; hier auf deutsche XMLTV-Labels
# gemappt. categories wird bevorzugt, genres als Fallback.
_CATEGORY_LABELS = {
    "series": u"Serie",
    "soaps": u"Serie",
    "movies": u"Spielfilm",
    "documentations": u"Dokumentation",
    "news": u"Nachrichten",
    "sports": u"Sport",
    "kids": u"Kinder",
    "music": u"Musik",
    "shows": u"Show",
}
_GENRE_LABELS = {
    "action_adventure": u"Action/Abenteuer",
    "animation": u"Animation",
    "comedy": u"Comedy",
    "cooking": u"Kochen",
    "crime_thriller": u"Krimi/Thriller",
    "culture_lifestyle": u"Kultur/Lifestyle",
    "drama": u"Drama",
    "education": u"Bildung",
    "erotic": u"Erotik",
    "health": u"Gesundheit",
    "horror": u"Horror",
    "nature_animals": u"Natur/Tiere",
    "romantic": u"Liebe/Romantik",
    "scifi_fantasy": u"Science-Fiction/Fantasy",
    "western": u"Western",
}


def _epgimport_channel_id(channel_id):
    return "hdplus.de." + ensure_text(channel_id)


def normalise_hdplus_channel(channel_id, name):
    channel_id = ensure_text(channel_id)
    return {
        "id": _epgimport_channel_id(channel_id),
        "name": ensure_text(name or channel_id),
        "hdplus_channel_id": channel_id,
        "logo": "",
    }


def _parse_hdplus_utc(value):
    """Parse an HD+ ISO8601 UTC timestamp (``...Z``) into a naive *local* datetime.

    ``compat.epgimport_time`` interprets the datetime it receives as local time
    (``time.mktime``), so the UTC instant is converted to the box's local time
    here to keep the emitted XMLTV timestamps correct.
    """
    text = ensure_text(value).strip()
    if len(text) < 19:
        raise ValueError("invalid datetime: " + text)
    parsed = datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
    timestamp = calendar.timegm(parsed.timetuple())
    return datetime.datetime.fromtimestamp(timestamp)


def _category_label(entry):
    for key in entry.get("categories") or []:
        label = _CATEGORY_LABELS.get(ensure_text(key))
        if label:
            return label
    for key in entry.get("genres") or []:
        label = _GENRE_LABELS.get(ensure_text(key))
        if label:
            return label
    return u""


class HdPlusProvider(object):
    id = "hdplus_de"
    name = "HD+ EPG"

    def available_channels(self):
        return self.discover_channels()

    def discover_channels(self, progress=None):
        if progress:
            progress("step", "HD+ Senderliste laden")
        channels = [
            normalise_hdplus_channel(channel_id, name)
            for channel_id, name in HDPLUS_CHANNELS
        ]
        channels.sort(key=lambda item: ensure_text(item.get("name", "")).lower())
        write_debug("HD+ channel discovery ok: " + str(len(channels)) + " channels", "provider")
        return channels

    def channel_from_task(self, task):
        channel_id = ensure_text(task.get("hdplus_channel_id") or "")
        name = ensure_text(task.get("source_channel_name") or "")
        return normalise_hdplus_channel(channel_id, name)

    def fetch(self, task_or_days, access_context=None, progress=None):
        if isinstance(task_or_days, dict):
            days = int(task_or_days.get("days", 3))
            channel = self.channel_from_task(task_or_days)
        else:
            days = int(task_or_days)
            channel = self.discover_channels()[0]

        target_id = ensure_text(channel.get("hdplus_channel_id") or "")
        if target_id not in _KNOWN_CHANNEL_IDS:
            raise RuntimeError(
                u"HD+-Sender '" + ensure_text(channel.get("name")) + u"' wurde in der Senderliste nicht gefunden."
            )

        if progress:
            progress("step", u"HD+ EPG für " + ensure_text(channel.get("name")) + u" laden")
        write_debug("HD+ fetch start channel=%s hdplus_channel_id=%s days=%s" % (
            ensure_text(channel.get("name")), target_id, days,
        ), "provider")

        programmes = []
        seen_starts = set()
        today = datetime.date.today()
        for offset in range(max(days, 1)):
            day = today + datetime.timedelta(days=offset)
            for hour in (0, 12):
                start_iso = "%sT%02d:00:00.000Z" % (day.strftime("%Y-%m-%d"), hour)
                try:
                    data = hdplus_client.fetch_slice(target_id, start_iso)
                except Exception as exc:
                    write_exception("HD+ fetch failed", exc)
                    raise RuntimeError(u"HD+ EPG konnte nicht geladen werden: " + ensure_text(exc))
                for entry in data.get("programmes") or []:
                    start_raw = ensure_text(entry.get("startTime") or "")
                    if not start_raw or start_raw in seen_starts:
                        continue
                    programme = self._normalise_programme(channel, entry)
                    if programme:
                        seen_starts.add(start_raw)
                        programmes.append(programme)

        write_debug("HD+ fetch ok events=" + str(len(programmes)), "provider")
        return [channel], programmes

    def _normalise_programme(self, channel, entry):
        try:
            start = _parse_hdplus_utc(entry.get("startTime"))
        except Exception:
            return None
        try:
            duration = int(entry.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        if duration <= 0:
            return None
        stop = start + datetime.timedelta(seconds=duration)

        title = ensure_text(entry.get("name") or "")
        sub_name = ensure_text(entry.get("subName") or "")
        description = sub_name if sub_name != title else u""

        fsk = entry.get("fskRating")
        rating = ensure_text(fsk) if fsk not in (None, "") else u""

        return {
            "channel_id": channel["id"],
            "title": title,
            "description": description,
            "category": _category_label(entry),
            "start": start,
            "stop": stop,
            "country": "",
            "year": "",
            "rating": rating,
            "source_id": ensure_text(entry.get("detail") or ""),
        }
