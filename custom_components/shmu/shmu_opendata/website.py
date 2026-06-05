"""Supplementary current-condition source: the SHMÚ public website.

The open-data ``aws1min`` feed has no cloud cover and only sparse present
weather, so it cannot yield a trustworthy Home Assistant ``condition``. The
SHMÚ "Aktuálne počasie - tabuľka" page does expose, per station (keyed by the
same ``ind_kli`` via its ``ii=`` link), an ``Oblačnosť`` (cloud amount) and a
``Počasie`` (present weather) text column.

This module is **deliberately isolated**: it is the only place that scrapes
HTML. When the Phase-2 ALADIN model provides cloud cover, the weather entity
can switch its condition source away from here without touching anything else
(and an open-data-only mode remains possible for an eventual HA-core path).

Numeric measurements still come exclusively from the open-data client; this
module only provides the qualitative sky/weather condition.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from html import unescape

_LOGGER = logging.getLogger(__name__)

# Home Assistant weather condition strings.
SUNNY = "sunny"
PARTLYCLOUDY = "partlycloudy"
CLOUDY = "cloudy"
FOG = "fog"
RAINY = "rainy"
POURING = "pouring"
SNOWY = "snowy"
SNOWY_RAINY = "snowy-rainy"
HAIL = "hail"
LIGHTNING = "lightning"
LIGHTNING_RAINY = "lightning-rainy"

WEBSITE_URL = "https://www.shmu.sk/sk/?page=1&id=meteo_apocasie_sk"

_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_II_RE = re.compile(r"ii=(\d+)")
_CLOUD_CELL_RE = re.compile(
    r'headers="h_oblacnost"[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL
)
_WEATHER_CELL_RE = re.compile(
    r'headers="h_pocasie"[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class WebCondition:
    """Per-station qualitative condition scraped from the SHMÚ website.

    ``weather_condition`` (from ``Počasie``) and ``cloud_condition`` (from
    ``Oblačnosť``) are kept apart because the cross-source priority ladder
    ranks an *active*-weather reading differently from a *sky*-cover one (see
    :mod:`shmu_opendata.resolution`). ``condition`` is the merged convenience
    (present weather over cloud) used where a single value is enough.
    """

    ind_kli: int
    cloud_text: str
    weather_text: str
    weather_condition: str | None
    cloud_condition: str | None
    condition: str | None


def _norm(text: str) -> str:
    """Lowercase and strip Slovak diacritics for robust keyword matching."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def _condition_from_weather(weather: str) -> str | None:
    """Map the ``Počasie`` (present weather) phrase to an HA condition.

    Returns ``None`` when the phrase carries no *active* weather (empty, or
    "after rain" / "distant fog"), so the caller can fall back to cloud cover.
    """
    w = _norm(weather)
    # "po <jav>" (po daždi / po búrke / po snežení) describes recent *past*
    # weather; "vzdialen" is distant. Neither is active here -> fall back to
    # cloud cover.
    if not w or w.startswith("po ") or "vzdialen" in w:
        return None
    if "burk" in w:  # búrka — thunderstorm
        return LIGHTNING_RAINY
    if "krupob" in w or "ladovec" in w or "kruty" in w:  # hail
        return HAIL
    if "mrzn" in w:  # mrznúci dážď / mrholenie — freezing
        return SNOWY_RAINY
    if ("sneh" in w or "snez" in w) and ("dazd" in w or "dazo" in w):
        return SNOWY_RAINY
    if "sneh" in w or "snez" in w:  # sneženie / snehové prehánky
        return SNOWY
    if "mrhol" in w:  # mrholenie — drizzle
        return RAINY
    if "dazd" in w or "dazo" in w:  # dážď — rain (silný → pouring)
        return POURING if ("siln" in w or "vydatn" in w or "intenz" in w) else RAINY
    if "prehank" in w:  # prehánky — showers (assume rain unless snow handled)
        return RAINY
    if "hmla" in w or "hmlist" in w:  # hmla — fog
        return FOG
    if "zakal" in w or "dymno" in w or "opar" in w:  # haze / mist
        return FOG
    return None


def _condition_from_cloud(cloud: str) -> str | None:
    """Map the ``Oblačnosť`` (cloud amount) phrase to an HA sky condition."""
    c = _norm(cloud)
    if not c:
        return None
    if "zamracene" in c:  # takmer zamračené / zamračené — (nearly) overcast
        return CLOUDY
    if "velka oblacnost" in c:
        return CLOUDY
    if "polojasno" in c or "mala oblacnost" in c or "oblacno" in c:
        return PARTLYCLOUDY
    if "jasno" in c:  # jasno / takmer jasno — clear
        return SUNNY
    return None


def _cell(pattern: re.Pattern[str], row: str) -> str:
    match = pattern.search(row)
    if match is None:
        return ""
    return unescape(_TAG_RE.sub("", match.group(1))).strip()


def parse_current_conditions(html: str) -> dict[int, WebCondition]:
    """Parse the SHMÚ current-weather table into per-station conditions.

    Present weather takes precedence over cloud amount; if neither yields an
    active condition the station's ``condition`` is ``None`` (unknown).
    """
    body = html.split("<tbody>", 1)
    rows_html = body[1].split("</tbody>", 1)[0] if len(body) > 1 else html
    result: dict[int, WebCondition] = {}
    for row in _ROW_RE.findall(rows_html):
        ii = _II_RE.search(row)
        if ii is None:
            continue
        ind_kli = int(ii.group(1))
        cloud = _cell(_CLOUD_CELL_RE, row)
        weather = _cell(_WEATHER_CELL_RE, row)
        weather_condition = _condition_from_weather(weather)
        cloud_condition = _condition_from_cloud(cloud)
        result[ind_kli] = WebCondition(
            ind_kli=ind_kli,
            cloud_text=cloud,
            weather_text=weather,
            weather_condition=weather_condition,
            cloud_condition=cloud_condition,
            condition=weather_condition or cloud_condition,
        )
    # The <tbody> split and cell regexes are inherently markup-coupled. If a
    # non-trivial page yields nothing, SHMÚ likely changed the layout — surface
    # it instead of silently returning an empty mapping.
    if not result and len(html) > 1000:
        _LOGGER.warning(
            "SHMÚ current-weather page parsed to zero stations (%d bytes); "
            "the page layout may have changed",
            len(html),
        )
    return result
