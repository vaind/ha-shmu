"""Typed data models returned by the client.

Only the fields relevant to a weather integration are surfaced as named
attributes; the untouched source record is kept on ``Observation.raw`` so
diagnostics and future sensors can reach the extra columns (soil profile,
sunshine duration, gamma dose rate, …) without a model change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Observation:
    """Latest 1-minute reading for a single station.

    Units follow SHMÚ's ``aws1min`` metadata: temperatures °C, pressure hPa,
    wind m/s, wind bearing degrees, humidity %, precipitation mm (1-min sum),
    snow depth cm, visibility m. Any field may be ``None`` (a station need not
    report every quantity).
    """

    ind_kli: int
    measured_at: datetime
    temperature: float | None
    humidity: float | None
    pressure: float | None
    wind_speed: float | None
    wind_gust: float | None
    wind_bearing: float | None
    precipitation: float | None
    snow_depth: float | None
    visibility: float | None
    ground_temperature: float | None
    global_radiation: float | None
    weather_code: int | None
    raw: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class Warning:
    """A single SHMÚ CAP 1.2 meteorological alert."""

    identifier: str
    event: str
    severity: str
    certainty: str | None
    awareness_level: str | None
    awareness_type: str | None
    onset: datetime | None
    expires: datetime | None
    sent: datetime | None
    headline: str | None
    description: str | None
    instruction: str | None
    areas: tuple[str, ...]
    #: One ring per CAP ``<area>``; each a tuple of (lat, lon) vertices.
    polygons: tuple[tuple[tuple[float, float], ...], ...]
    web: str | None

    def is_active(self, at: datetime) -> bool:
        """Whether the warning is in force at ``at`` (timezone-aware UTC)."""
        if self.onset is not None and at < self.onset:
            return False
        return not (self.expires is not None and at >= self.expires)

    def covers(self, latitude: float, longitude: float) -> bool:
        """Whether a point lies in any of the warning's area polygons.

        Warnings with no polygon geometry are treated as covering everywhere
        (country-wide) so they are never silently dropped.
        """
        if not self.polygons:
            return True
        return any(_point_in_ring(latitude, longitude, ring) for ring in self.polygons)


def _point_in_ring(
    lat: float, lon: float, ring: tuple[tuple[float, float], ...]
) -> bool:
    """Ray-casting point-in-polygon test (vertices are (lat, lon))."""
    inside = False
    n = len(ring)
    for i in range(n):
        y1, x1 = ring[i]
        y2, x2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) / (y2 - y1) * (x2 - x1)
            if lon < x_cross:
                inside = not inside
    return inside
