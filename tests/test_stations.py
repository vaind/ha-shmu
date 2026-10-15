"""Tests for the hard-coded automatic weather station table."""

from __future__ import annotations

from custom_components.shmu.shmu_opendata.stations import (
    STATIONS,
    get_station,
    nearest_station,
)

#: The synoptic network, curated from ?page=318. These ids are what every
#: config entry created before the catalogue grew refers to, so each must stay.
_SYNOPTIC = {
    11812, 11813, 11816, 11819, 11826, 11841, 11855, 11856, 11858, 11867,
    11880, 11894, 11900, 11903, 11916, 11918, 11927, 11930, 11933, 11934,
    11938, 11952, 11958, 11968, 11976, 11978, 11993,
}  # fmt: skip


def test_table_integrity() -> None:
    ids = [s.ind_kli for s in STATIONS]
    assert len(set(ids)) == len(ids)  # no duplicates
    assert ids == sorted(ids)  # ordered as documented
    assert len({s.name for s in STATIONS}) == len(STATIONS)  # unambiguous picker
    assert len(STATIONS) == 95
    for s in STATIONS:
        assert 11000 <= s.ind_kli <= 12000  # Slovak WMO block
        assert 47.0 <= s.latitude <= 50.0  # within Slovakia
        assert 16.0 <= s.longitude <= 23.0
        if s.elevation is not None:
            assert 90.0 <= s.elevation <= 2700.0  # Lomnický Štít ≈ 2635 m
        assert s.name.strip() == s.name and s.name


def test_synoptic_stations_are_kept_and_marked() -> None:
    assert {s.ind_kli for s in STATIONS if s.synoptic} == _SYNOPTIC
    # The synoptic stations come from ?page=318, which publishes every
    # elevation, and the sea-level pressure of existing entries depends on it.
    assert all(s.elevation is not None for s in STATIONS if s.synoptic)


def test_unknown_elevation_is_none_not_a_guess() -> None:
    # Bardejov reports pressure but no source publishes its elevation.
    bardejov = get_station(11962)
    assert bardejov is not None
    assert bardejov.elevation is None
    # Banská Bystrica's comes from WMO OSCAR.
    assert get_station(11898).elevation == 429.0


def test_get_station() -> None:
    assert get_station(11858).name == "Hurbanovo"
    assert get_station(99999) is None


def test_nearest_station() -> None:
    # Near Bratislava centre -> a Bratislava station.
    assert "Bratislava" in nearest_station(48.1486, 17.1077).name
    # Košice city centre is nearer the Podhradová station than the airport.
    assert nearest_station(48.7164, 21.2611).name == "Košice - Podhradová"
    # Right on top of a synoptic station -> that station.
    assert nearest_station(47.8733, 18.1944).name == "Hurbanovo"
