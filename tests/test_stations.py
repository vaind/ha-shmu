"""Tests for the hard-coded synoptic station table."""

from __future__ import annotations

from custom_components.shmu.shmu_opendata.stations import (
    STATIONS,
    get_station,
    nearest_station,
)


def test_table_integrity() -> None:
    assert len(STATIONS) == 27
    ids = [s.ind_kli for s in STATIONS]
    assert len(set(ids)) == 27  # no duplicates
    for s in STATIONS:
        assert 11000 <= s.ind_kli <= 12000  # Slovak WMO block
        assert 47.0 <= s.latitude <= 50.0  # within Slovakia
        assert 16.0 <= s.longitude <= 23.0
        assert -50.0 <= s.elevation <= 2700.0  # Lomnický Štít ≈ 2635 m
        assert s.name.strip() == s.name and s.name


def test_get_station() -> None:
    assert get_station(11858).name == "Hurbanovo"
    assert get_station(99999) is None


def test_nearest_station() -> None:
    # Near Bratislava centre -> a Bratislava station.
    assert "Bratislava" in nearest_station(48.1486, 17.1077).name
    # Near Košice -> Košice.
    assert nearest_station(48.7164, 21.2611).name == "Košice"
