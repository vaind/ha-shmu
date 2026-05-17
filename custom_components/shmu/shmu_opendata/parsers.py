"""Parsers for the three SHMÚ open-data payloads.

The server is a plain Apache file index, so locating the newest file means
parsing an HTML directory listing; the data itself is JSON (observations) or
CAP 1.2 XML (warnings).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from .exceptions import ShmuDataError
from .models import Observation, Warning

# Apache autoindex links: skip the column-sort links ("?C=...") and the
# "Parent Directory" link ("/...").
_HREF_RE = re.compile(r'<a\s+href="([^"?/][^"]*)"', re.IGNORECASE)

_CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"


def list_directory(html: str) -> list[str]:
    """Return the entry names of an Apache directory listing, in page order.

    Hrefs are percent-decoded so callers see real names (the index encodes
    spaces, e.g. ``aws1min%20-%20...json``). Directory entries keep their
    trailing slash (e.g. ``"20260517/"``).
    """
    return [unquote(href) for href in _HREF_RE.findall(html)]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_minuta(value: str) -> datetime:
    """Parse an observation timestamp.

    SHMÚ documents ``minuta`` as UTC with no zone suffix
    (e.g. ``2026-05-17T06:50:00``); attach UTC explicitly.
    """
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def parse_observations(payload: bytes | str) -> dict[int, Observation]:
    """Parse an ``aws1min`` snapshot into the latest reading per station.

    A snapshot holds several 1-minute records per station; only the most
    recent (largest ``minuta``) is kept for each ``ind_kli``.
    """
    try:
        document = json.loads(payload)
        records: list[Mapping[str, Any]] = document["data"]
    except (json.JSONDecodeError, KeyError, TypeError) as err:
        raise ShmuDataError(f"Malformed observations payload: {err}") from err

    latest: dict[int, Observation] = {}
    for record in records:
        ind_kli = _to_int(record.get("ind_kli"))
        raw_minuta = record.get("minuta")
        if ind_kli is None or not raw_minuta:
            continue
        try:
            measured_at = _parse_minuta(raw_minuta)
        except ValueError:
            continue
        existing = latest.get(ind_kli)
        if existing is not None and measured_at <= existing.measured_at:
            continue
        latest[ind_kli] = Observation(
            ind_kli=ind_kli,
            measured_at=measured_at,
            temperature=_to_float(record.get("t")),
            humidity=_to_float(record.get("vlh_rel")),
            pressure=_to_float(record.get("tlak")),
            wind_speed=_to_float(record.get("vie_pr_rych")),
            wind_gust=_to_float(record.get("vie_max_rych")),
            wind_bearing=_to_float(record.get("vie_pr_smer")),
            precipitation=_to_float(record.get("zra_uhrn")),
            snow_depth=_to_float(record.get("sneh_pokr")),
            visibility=_to_float(record.get("dohl")),
            ground_temperature=_to_float(record.get("tprz")),
            global_radiation=_to_float(record.get("zglo")),
            weather_code=_to_int(record.get("stav_poc")),
            raw=record,
        )
    return latest


def _parse_polygon(text: str | None) -> tuple[tuple[float, float], ...]:
    """Parse a CAP ``<polygon>`` ("lat,lon lat,lon …") into a ring."""
    if not text:
        return ()
    ring: list[tuple[float, float]] = []
    for pair in text.split():
        lat_str, _, lon_str = pair.partition(",")
        try:
            ring.append((float(lat_str), float(lon_str)))
        except ValueError:
            return ()
    return tuple(ring)


def _cap_text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    text = element.text.strip()
    return text or None


def _cap_datetime(element: ET.Element | None) -> datetime | None:
    text = _cap_text(element)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # SHMÚ CAP times carry an explicit offset, but if one ever arrives naive,
    # treat it as UTC (consistent with observation timestamps) rather than
    # letting astimezone() silently assume the host's local zone.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_cap_alert(payload: bytes | str) -> Warning:
    """Parse one SHMÚ CAP 1.2 alert document into a :class:`Warning`.

    The Slovak-language ``<info>`` block is preferred when several languages
    are present.
    """
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as err:
        raise ShmuDataError(f"Malformed CAP XML: {err}") from err

    def q(tag: str) -> str:
        return f"{{{_CAP_NS}}}{tag}"

    identifier = _cap_text(root.find(q("identifier"))) or ""
    sent = _cap_datetime(root.find(q("sent")))

    infos = root.findall(q("info"))
    if not infos:
        raise ShmuDataError(f"CAP alert {identifier!r} has no <info> block")
    info = next(
        (i for i in infos if _cap_text(i.find(q("language"))) == "sk"),
        infos[0],
    )

    awareness_level: str | None = None
    awareness_type: str | None = None
    for param in info.findall(q("parameter")):
        name = _cap_text(param.find(q("valueName")))
        value = _cap_text(param.find(q("value")))
        if value is None:
            continue
        # SHMÚ encodes these as "N; slug; Label"; pick the documented element.
        parts = [p.strip() for p in value.split(";")]
        if name == "awareness_level":
            # e.g. "2; yellow; Moderate" -> "yellow"
            awareness_level = parts[1] if len(parts) > 1 else value
        elif name == "awareness_type":
            # e.g. "10; Rain" -> "Rain"
            awareness_type = parts[-1] if len(parts) > 1 else value

    areas: list[str] = []
    polygons: list[tuple[tuple[float, float], ...]] = []
    for area in info.findall(q("area")):
        desc = _cap_text(area.find(q("areaDesc")))
        if desc is not None:
            areas.append(desc)
        for polygon in area.findall(q("polygon")):
            ring = _parse_polygon(_cap_text(polygon))
            if ring:
                polygons.append(ring)

    return Warning(
        identifier=identifier,
        event=_cap_text(info.find(q("event"))) or "",
        severity=_cap_text(info.find(q("severity"))) or "Unknown",
        certainty=_cap_text(info.find(q("certainty"))),
        awareness_level=awareness_level,
        awareness_type=awareness_type,
        onset=_cap_datetime(info.find(q("onset"))),
        expires=_cap_datetime(info.find(q("expires"))),
        sent=sent,
        headline=_cap_text(info.find(q("headline"))),
        description=_cap_text(info.find(q("description"))),
        instruction=_cap_text(info.find(q("instruction"))),
        areas=tuple(areas),
        polygons=tuple(polygons),
        web=_cap_text(info.find(q("web"))),
    )
