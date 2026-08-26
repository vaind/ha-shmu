"""Tests for the shared great-circle helper."""

from __future__ import annotations

import pytest

from custom_components.shmu.shmu_opendata.distance import haversine_km

# Bratislava - Koliba and Košice, from the synoptic catalogue.
_KOLIBA = (48.1686, 17.1106)
_KOSICE = (48.6731, 21.2311)


def test_zero_distance_to_itself() -> None:
    assert haversine_km(*_KOLIBA, *_KOLIBA) == 0.0


def test_known_pair() -> None:
    """Koliba->Kosice is ~309 km; a spherical model is well within 1 km."""
    assert haversine_km(*_KOLIBA, *_KOSICE) == pytest.approx(309.0, abs=1.0)


def test_symmetric() -> None:
    assert haversine_km(*_KOLIBA, *_KOSICE) == pytest.approx(
        haversine_km(*_KOSICE, *_KOLIBA)
    )


def test_one_degree_of_latitude() -> None:
    """A degree of latitude is ~111.2 km anywhere."""
    assert haversine_km(48.0, 17.0, 49.0, 17.0) == pytest.approx(111.2, abs=0.1)
