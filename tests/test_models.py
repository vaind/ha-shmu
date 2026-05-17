"""Tests for Warning.is_active and point-in-polygon coverage."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.shmu.shmu_opendata.models import Warning

_RING = ((48.10, 17.00), (48.10, 17.25), (48.25, 17.25), (48.25, 17.00))


def _warning(**kw) -> Warning:
    base = dict(
        identifier="x",
        event="e",
        severity="Moderate",
        certainty=None,
        awareness_level="yellow",
        awareness_type="Rain",
        onset=datetime(2026, 5, 15, 18, 0, tzinfo=UTC),
        expires=datetime(2026, 5, 17, 18, 0, tzinfo=UTC),
        sent=None,
        headline=None,
        description=None,
        instruction=None,
        areas=("Bratislava",),
        polygons=(_RING,),
        web=None,
    )
    base.update(kw)
    return Warning(**base)


def test_is_active_window() -> None:
    w = _warning()
    assert not w.is_active(datetime(2026, 5, 15, 17, 0, tzinfo=UTC))  # before onset
    assert w.is_active(datetime(2026, 5, 16, 12, 0, tzinfo=UTC))  # within
    assert not w.is_active(datetime(2026, 5, 17, 18, 0, tzinfo=UTC))  # at expiry


def test_is_active_open_ended() -> None:
    assert _warning(onset=None, expires=None).is_active(datetime.now(UTC))


def test_covers_point_in_and_out_of_polygon() -> None:
    w = _warning()
    assert w.covers(48.17, 17.10)  # inside the box
    assert not w.covers(49.00, 21.20)  # far away (Košice-ish)


def test_covers_without_geometry_is_country_wide() -> None:
    assert _warning(polygons=()).covers(49.0, 21.2)
