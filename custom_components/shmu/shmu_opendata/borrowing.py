"""Fill a reading a station lacks from a nearby station that has it.

Most of the catalogue's stations measure only part of what the synoptic ones
do (see :mod:`shmu_opendata.stations`), and 26 have no known elevation, so
their sea-level pressure cannot be computed. Some readings are smooth enough
in space that a neighbour's value is a fair stand-in; most are not (showers,
fog and snow depth are local). :data:`BORROW_RULES` is therefore an explicit
allow-list: a reading not in it is never borrowed, and each entry says how far
away, and how high, a source may be.

The station's own value always wins. A borrowed one is returned together with
the station it came from, so callers can say so rather than present it as the
chosen station's measurement.

Pure and Home-Assistant-free like the rest of the library; the caller decides
which neighbouring readings are current enough to offer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from .models import Observation
from .pressure import sea_level_pressure
from .stations import STATIONS, Station


@dataclass(frozen=True, slots=True)
class BorrowRule:
    """When a neighbour's value may stand in for a station's own.

    ``read`` derives the value from a station and its observation (``None``
    when it cannot). A source must be within ``max_distance_km`` of the
    station; ``max_height_diff_m`` bounds the elevation difference between the
    two and ``max_source_elevation_m`` the source's own elevation. A height
    bound fails for any station whose elevation is unknown — an unknown
    difference is never assumed small.
    """

    read: Callable[[Station, Observation], float | None]
    max_distance_km: float
    max_height_diff_m: float | None = None
    max_source_elevation_m: float | None = None

    def admits(self, station: Station, source: Station) -> bool:
        """Whether ``source`` is close and level enough to stand in."""
        if (
            source.distance_km(station.latitude, station.longitude)
            > self.max_distance_km
        ):
            return False
        if self.max_height_diff_m is not None and (
            station.elevation is None
            or source.elevation is None
            or abs(station.elevation - source.elevation) > self.max_height_diff_m
        ):
            return False
        return self.max_source_elevation_m is None or (
            source.elevation is not None
            and source.elevation < self.max_source_elevation_m
        )


@dataclass(frozen=True, slots=True)
class SourcedReading:
    """A value and the station that measured it."""

    value: float
    source: Station
    #: Great-circle distance from the chosen station; 0 for its own value.
    distance_km: float

    @property
    def borrowed(self) -> bool:
        """True when the value came from another station."""
        return self.distance_km > 0


def _sea_level_pressure(station: Station, observation: Observation) -> float | None:
    if station.elevation is None:
        return None
    return sea_level_pressure(
        observation.pressure, station.elevation, observation.temperature
    )


#: Readings that may be borrowed, by name. Anything absent is never borrowed.
#:
#: ``sea_level_pressure`` — measured live 2026-10-15 over 31 daily snapshots:
#: between two stations below 1000 m the reduced pressures differ by a median
#: 0.3-0.7 hPa (p90 1.5-2.3 hPa) at every distance up to 100 km, so the error
#: is mostly each station's own reduction bias, not distance. With a source at
#: or above 1000 m it roughly doubles (median 1.0-1.4 hPa), as the reduction
#: through an imagined air column below a mountain station is the weak step.
#: 40 km keeps a source for all but 2 of the 54 stations without a value.
BORROW_RULES: Final[Mapping[str, BorrowRule]] = {
    "sea_level_pressure": BorrowRule(
        read=_sea_level_pressure,
        max_distance_km=40.0,
        max_source_elevation_m=1000.0,
    ),
}


def borrow(
    rule: BorrowRule,
    station: Station,
    observation: Observation | None,
    neighbours: Mapping[int, Observation],
) -> SourcedReading | None:
    """The station's own value, else the nearest admissible neighbour's.

    ``observation`` is the station's own (possibly carried-forward) reading;
    ``neighbours`` maps ``ind_kli`` to readings the caller considers current.
    Neighbours are tried nearest first; the first that ``rule`` admits and
    that yields a value wins. Returns ``None`` when none does.
    """
    if observation is not None:
        own = rule.read(station, observation)
        if own is not None:
            return SourcedReading(own, station, 0.0)
    candidates = sorted(
        (
            s
            for s in STATIONS
            if s.ind_kli != station.ind_kli
            and s.ind_kli in neighbours
            and rule.admits(station, s)
        ),
        key=lambda s: s.distance_km(station.latitude, station.longitude),
    )
    for source in candidates:
        value = rule.read(source, neighbours[source.ind_kli])
        if value is not None:
            return SourcedReading(
                value, source, source.distance_km(station.latitude, station.longitude)
            )
    return None
