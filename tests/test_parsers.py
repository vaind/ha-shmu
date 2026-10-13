"""Tests for the directory, observation and CAP parsers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.shmu.shmu_opendata.exceptions import ShmuDataError
from custom_components.shmu.shmu_opendata.parsers import (
    list_directory,
    parse_cap_alert,
    parse_gauge_observations,
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
    # `minuta` is stamped in SEC (fixed UTC+1), so 06:52 SEC is 05:52 UTC; the
    # offset is asserted too, since that is what the entity attribute renders.
    assert hurbanovo.measured_at == datetime(2026, 5, 17, 5, 52, tzinfo=UTC)
    assert hurbanovo.measured_at.utcoffset() == timedelta(hours=1)
    assert hurbanovo.temperature == 12.1
    assert hurbanovo.weather_code == 61
    # Null upstream values become None, not 0/"".
    assert obs[11816].pressure is None
    assert obs[11816].weather_code is None
    assert obs[11930].snow_depth == 12.0


def test_parse_gauge_observations_keeps_latest_minute_per_gauge(fixture) -> None:
    gauges = parse_gauge_observations(fixture("gauge_observations.json"))

    # Three minutes for 17720, listed out of order; the 06:52 record wins.
    kolarovo = gauges[17720]
    # As with `aws1min`, `minuta` is SEC (fixed UTC+1): 06:52 SEC is 05:52 UTC.
    assert kolarovo.measured_at == datetime(2026, 5, 17, 5, 52, tzinfo=UTC)
    assert kolarovo.measured_at.utcoffset() == timedelta(hours=1)
    assert kolarovo.precipitation == 0.4
    assert kolarovo.temperature == 12.1


def test_parse_gauge_observations_ignores_backfilled_records(fixture) -> None:
    """The feed mixes hours-old backfill in with the current minutes.

    Verified live 2026-08-26: one snapshot carried records spanning 8 hours.
    Taking anything but the newest per gauge would surface a stale reading as
    the current one.
    """
    gauges = parse_gauge_observations(fixture("gauge_observations.json"))

    koliba = gauges[17140]
    assert koliba.measured_at == datetime(2026, 5, 17, 5, 52, tzinfo=UTC)
    assert koliba.precipitation == 1.2  # not the 02:15 backfill's 9.9


def test_parse_gauge_observations_keeps_uncatalogued_ids(fixture) -> None:
    """The catalogue is near-complete, not total, so ids may be unknown."""
    assert 99999 in parse_gauge_observations(fixture("gauge_observations.json"))


def test_parse_gauge_observations_skips_unusable_records() -> None:
    payload = (
        b'{"data": ['
        b'{"ind_zra": null, "minuta": "2026-05-17T06:52:00", "zra_uhrn": 1.0},'
        b'{"ind_zra": 17720, "minuta": "", "zra_uhrn": 1.0},'
        b'{"ind_zra": 17720, "minuta": "not-a-time", "zra_uhrn": 1.0},'
        b'{"ind_zra": 24295, "minuta": "2026-05-17T06:52:00", "zra_uhrn": null}'
        b"]}"
    )
    gauges = parse_gauge_observations(payload)

    assert set(gauges) == {24295}
    # A null upstream value becomes None, not 0.0.
    assert gauges[24295].precipitation is None


# Every shape below used to escape as a raw AttributeError/TypeError/
# UnicodeDecodeError, which the coordinator reports as an "unexpected error"
# with a traceback on every poll instead of a clean update failure.
_MALFORMED_SNAPSHOTS = {
    "not json": (b"not json", "not valid JSON"),
    "invalid utf-8": (b'{"data": ["\xff"]}', "not valid JSON"),
    "no data key": (b'{"no_data_key": true}', "'data' list"),
    "top level not an object": (b"[1, 2]", "'data' list"),
    "data not a list": (b'{"data": {"ind_kli": 1}}', "'data' list"),
    "data null": (b'{"data": null}', "'data' list"),
    "record not an object": (b'{"data": ["oops"]}', "record 0 is str"),
    "minuta not a string": (
        b'{"data": [{"ind_kli": 11858, "ind_zra": 17720, "minuta": 202605170652}]}',
        "'minuta' is int",
    ),
}


@pytest.mark.parametrize(
    "parser", [parse_observations, parse_gauge_observations], ids=["aws", "aps"]
)
@pytest.mark.parametrize(
    ("payload", "message"),
    list(_MALFORMED_SNAPSHOTS.values()),
    ids=list(_MALFORMED_SNAPSHOTS),
)
def test_snapshot_parsers_reject_malformed(parser, payload, message) -> None:
    with pytest.raises(ShmuDataError, match=message):
        parser(payload)


def test_snapshot_parsers_accept_an_empty_snapshot() -> None:
    """An empty ``data`` list is a real upstream state (seen live), not malformed."""
    assert parse_observations(b'{"data": []}') == {}
    assert parse_gauge_observations(b'{"data": []}') == {}


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
