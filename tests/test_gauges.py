"""Tests for the hard-coded rain-gauge table."""

from __future__ import annotations

from custom_components.shmu.shmu_opendata.gauges import (
    GAUGES,
    get_gauge,
    nearest_gauge,
)
from custom_components.shmu.shmu_opendata.stations import STATIONS


def test_table_integrity() -> None:
    assert len(GAUGES) == 190
    ids = [g.ind_zra for g in GAUGES]
    assert len(set(ids)) == len(ids)  # no duplicates
    assert ids == sorted(ids)  # ordered by ind_zra, as documented
    for g in GAUGES:
        assert 10000 <= g.ind_zra <= 99999
        # Bounds are looser than the catalogue's observed extents so a
        # legitimate border gauge added on regeneration does not fail here.
        assert 47.0 <= g.latitude <= 50.0  # within Slovakia
        assert 16.0 <= g.longitude <= 23.0
        assert g.name.strip() == g.name and g.name


def test_id_space_is_disjoint_from_the_synoptic_network() -> None:
    """The two networks are complementary, never the same station twice.

    If SHMÚ ever reused an id across the feeds, keying by the wrong one would
    silently return another station's data.
    """
    assert not {g.ind_zra for g in GAUGES} & {s.ind_kli for s in STATIONS}


def test_get_gauge() -> None:
    assert get_gauge(17720).name == "Kolárovo"
    assert get_gauge(99999) is None


def test_nearest_gauge() -> None:
    # Near Bratislava centre -> the Koliba gauge, ~2 km away.
    nearest = nearest_gauge(48.15, 17.11)
    assert nearest.ind_zra == 17140
    assert nearest.distance_km(48.15, 17.11) < 3.0
    # Near Košice -> a gauge in its vicinity.
    assert nearest_gauge(48.7164, 21.2611).distance_km(48.7164, 21.2611) < 15.0


def test_network_is_denser_than_the_synoptic_one() -> None:
    """The point of adopting this feed: precipitation from closer by.

    Checked at the synoptic stations themselves — the worst case for the
    gauges, since a station sits exactly on top of its own network.
    """
    closer = 0
    for station in STATIONS:
        gauge = nearest_gauge(station.latitude, station.longitude)
        if gauge.distance_km(station.latitude, station.longitude) < 25.0:
            closer += 1
    assert closer == len(STATIONS)
