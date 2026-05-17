"""Tests for the directory, observation and CAP parsers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.shmu.shmu_opendata.exceptions import ShmuDataError
from custom_components.shmu.shmu_opendata.parsers import (
    list_directory,
    parse_cap_alert,
    parse_observations,
)


def test_list_directory_decodes_and_skips_navigation(fixture) -> None:
    entries = list_directory(fixture("dir_listing.html").decode("utf-8"))

    # Parent ("/parent/") and the "?C=" sort links are excluded.
    assert "/parent/" not in entries
    assert not any(e.startswith("?") for e in entries)
    # Percent-encoded spaces are decoded.
    assert "aws1min - 2026-05-17 06-55-00.json" in entries
    assert "20260517/" in entries


def test_parse_observations_keeps_latest_minute_per_station(fixture) -> None:
    obs = parse_observations(fixture("observations.json"))

    assert set(obs) == {11858, 11816, 11930}
    # Three minutes for 11858; the 06:52 record must win.
    hurbanovo = obs[11858]
    assert hurbanovo.measured_at == datetime(2026, 5, 17, 6, 52, tzinfo=UTC)
    assert hurbanovo.temperature == 12.1
    assert hurbanovo.weather_code == 61
    # Null upstream values become None, not 0/"".
    assert obs[11816].pressure is None
    assert obs[11816].weather_code is None
    assert obs[11930].snow_depth == 12.0


def test_parse_observations_rejects_malformed() -> None:
    with pytest.raises(ShmuDataError):
        parse_observations(b"not json")
    with pytest.raises(ShmuDataError):
        parse_observations(b'{"no_data_key": true}')


def test_parse_cap_alert_prefers_slovak_and_extracts_polygon(fixture) -> None:
    warning = parse_cap_alert(fixture("alert.cap.xml"))

    # The Slovak <info> block is chosen over the English one.
    assert warning.event == "Výstraha pred dažďom"
    assert warning.headline == "Očakávame dážď"
    assert warning.severity == "Moderate"
    assert warning.awareness_level == "yellow"
    assert warning.awareness_type == "Rain"
    assert warning.onset == datetime(2026, 5, 15, 18, 0, tzinfo=UTC)
    assert warning.expires == datetime(2026, 5, 17, 18, 0, tzinfo=UTC)
    assert "Bratislava" in warning.areas
    assert len(warning.polygons) == 1
    assert warning.polygons[0][0] == (48.10, 17.00)


def test_parse_cap_alert_rejects_malformed() -> None:
    with pytest.raises(ShmuDataError):
        parse_cap_alert(b"<not-cap/>")
