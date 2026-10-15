"""Tests for filling a station's missing reading from a neighbour."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.shmu.shmu_opendata.borrowing import (
    BORROW_RULES,
    BorrowRule,
    borrow,
)
from custom_components.shmu.shmu_opendata.models import Observation
from custom_components.shmu.shmu_opendata.pressure import sea_level_pressure
from custom_components.shmu.shmu_opendata.stations import Station, get_station


def _station(ind_kli: int) -> Station:
    station = get_station(ind_kli)
    assert station is not None
    return station


# Real catalogue stations, so the distances are the ones users get.
HURBANOVO = _station(11858)  # 115 m
VELKE_LOVCE = _station(11883)  # 186 m, 22.9 km from Hurbanovo
MUZLA = _station(11884)  # 120 m, 31.0 km
NITRA = _station(11855)  # 135 m, 45.5 km
BARDEJOV = _station(11962)  # elevation unknown
LIPTOVSKY_HRADOK = _station(11874)  # 638 m
CHOPOK = _station(11916)  # 2005 m, 14.1 km from Liptovský Hrádok
BREZNO = _station(11917)  # 488 m, 16.3 km from Liptovský Hrádok

RULE = BORROW_RULES["sea_level_pressure"]


def _obs(
    station: Station, pressure: float | None = 990.0, temperature: float = 10.0
) -> Observation:
    return Observation(
        ind_kli=station.ind_kli,
        measured_at=datetime(2026, 10, 15, 10, 0, tzinfo=UTC),
        temperature=temperature,
        humidity=None,
        pressure=pressure,
        wind_speed=None,
        wind_gust=None,
        wind_bearing=None,
        precipitation=None,
        snow_depth=None,
        visibility=None,
        ground_temperature=None,
        global_radiation=None,
        weather_code=None,
        raw={},
    )


def _qff(station: Station, pressure: float = 990.0) -> float:
    assert station.elevation is not None
    value = sea_level_pressure(pressure, station.elevation, 10.0)
    assert value is not None
    return value


def _read_pressure(station: Station, observation: Observation) -> float | None:
    return observation.pressure


class TestAdmits:
    def test_distance(self) -> None:
        rule = BorrowRule(read=_read_pressure, max_distance_km=30.0)
        assert rule.admits(HURBANOVO, VELKE_LOVCE)  # 22.9 km
        assert not rule.admits(HURBANOVO, MUZLA)  # 31.0 km

    def test_height_difference(self) -> None:
        rule = BorrowRule(
            read=_read_pressure, max_distance_km=500.0, max_height_diff_m=100.0
        )
        assert rule.admits(HURBANOVO, VELKE_LOVCE)  # 71 m apart
        assert not rule.admits(HURBANOVO, BREZNO)  # 373 m apart

    def test_unknown_elevation_fails_a_height_bound_either_way(self) -> None:
        rule = BorrowRule(
            read=_read_pressure, max_distance_km=500.0, max_height_diff_m=10_000.0
        )
        assert not rule.admits(BARDEJOV, HURBANOVO)
        assert not rule.admits(HURBANOVO, BARDEJOV)
        # Without a height bound, distance alone decides.
        assert BorrowRule(read=_read_pressure, max_distance_km=500.0).admits(
            BARDEJOV, HURBANOVO
        )

    def test_source_elevation_cap(self) -> None:
        assert not RULE.admits(LIPTOVSKY_HRADOK, CHOPOK)  # 2005 m source
        assert RULE.admits(LIPTOVSKY_HRADOK, BREZNO)  # 488 m source
        # The cap is on the source only: a mountain station may borrow.
        assert RULE.admits(CHOPOK, BREZNO)
        # And an unknown source elevation cannot pass it.
        assert not BorrowRule(
            read=_read_pressure, max_distance_km=500.0, max_source_elevation_m=1000.0
        ).admits(HURBANOVO, BARDEJOV)


class TestBorrow:
    def test_own_value_wins(self) -> None:
        reading = borrow(
            RULE, HURBANOVO, _obs(HURBANOVO), {VELKE_LOVCE.ind_kli: _obs(VELKE_LOVCE)}
        )
        assert reading is not None
        assert reading.source is HURBANOVO
        assert reading.distance_km == 0.0
        assert not reading.borrowed
        assert reading.value == pytest.approx(_qff(HURBANOVO))

    def test_nearest_admissible_neighbour_wins(self) -> None:
        reading = borrow(
            RULE,
            HURBANOVO,
            _obs(HURBANOVO, pressure=None),
            {
                MUZLA.ind_kli: _obs(MUZLA, pressure=1000.0),
                VELKE_LOVCE.ind_kli: _obs(VELKE_LOVCE, pressure=980.0),
            },
        )
        assert reading is not None
        assert reading.source is VELKE_LOVCE
        assert reading.borrowed
        assert reading.distance_km == pytest.approx(22.9, abs=0.1)
        assert reading.value == pytest.approx(_qff(VELKE_LOVCE, 980.0))

    def test_neighbours_without_a_value_are_skipped(self) -> None:
        reading = borrow(
            RULE,
            HURBANOVO,
            None,
            {
                VELKE_LOVCE.ind_kli: _obs(VELKE_LOVCE, pressure=None),
                MUZLA.ind_kli: _obs(MUZLA),
            },
        )
        assert reading is not None
        assert reading.source is MUZLA

    def test_station_without_elevation_borrows_despite_its_own_pressure(
        self,
    ) -> None:
        # Its raw reading cannot be reduced, so a neighbour's QFF stands in.
        assert BARDEJOV.elevation is None
        tisinec = _station(11976)  # 28.6 km, 216 m
        reading = borrow(
            RULE, BARDEJOV, _obs(BARDEJOV), {tisinec.ind_kli: _obs(tisinec)}
        )
        assert reading is not None
        assert reading.source is tisinec

    def test_nothing_in_range(self) -> None:
        assert (
            borrow(RULE, HURBANOVO, None, {NITRA.ind_kli: _obs(NITRA)}) is None
        )  # 45.5 km

    def test_the_station_itself_is_not_a_neighbour(self) -> None:
        # Its own reading, offered as a "neighbour", must not be re-read.
        assert (
            borrow(
                RULE,
                HURBANOVO,
                _obs(HURBANOVO, pressure=None),
                {HURBANOVO.ind_kli: _obs(HURBANOVO)},
            )
            is None
        )
