"""Live contract checks against the real SHMÚ servers.

The offline suite under ``tests/`` proves the code handles the fixtures it was
given; it cannot notice SHMÚ changing what it serves. These tests run the real
client against opendata.shmu.sk and www.shmu.sk and assert the upstream facts
recorded in AGENTS.md — freshness, coverage, the forecast horizon, the radar
loop — so an upstream change surfaces as a failed scheduled CI run rather than
as a user's log full of warnings.

They hit the network on purpose, so they live outside ``tests/`` (whose
contract is offline and deterministic) and run only when asked:
``python -m pytest tests_e2e/ -p no:homeassistant`` (that plugin blocks every
non-localhost socket; ``conftest.py`` refuses to run without the opt-out).
Thresholds are deliberately loose — they must pass on
any ordinary day — so a failure means the contract moved, not that the weather
was unusual.
"""

from __future__ import annotations

import re
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from shmu_opendata import (
    GAUGES,
    STATIONS,
    ShmuClient,
    create_ssl_context,
)
from shmu_opendata.const import (
    MIN_FORECAST_HOURS,
    RADAR_LOOP_FRAMES,
    WARNINGS_PATH,
)

# Trnava: inside both the forecast grid and the radar composite.
LATITUDE, LONGITUDE = 48.377, 17.588

# The 5-minute feeds publish within a few minutes; matches the integration's
# OBSERVATION_STALE_AFTER, past which it would treat a reading as stale anyway.
FRESH_WITHIN = timedelta(minutes=30)
# A future timestamp means a time-zone regression (`minuta` was once read as
# UTC instead of SEC, putting every reading an hour ahead). Small slack for
# clock skew on the CI runner.
FUTURE_SLACK = timedelta(minutes=5)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_BRATISLAVA = ZoneInfo("Europe/Bratislava")
# Upload lag between a snapshot's nominal time and its Last-Modified: seconds
# when verified, loose so a slow publish isn't mistaken for a convention change.
PUBLISH_LAG = timedelta(minutes=10)


def test_library_loads_without_home_assistant() -> None:
    # The vendored library must stay HA-free (see conftest.py).
    assert "homeassistant" not in sys.modules


@pytest.fixture
async def client() -> AsyncIterator[ShmuClient]:
    # The real TLS path, bundled intermediate included: if SHMÚ rotates its
    # certificate chain, every test here fails at the handshake.
    async with aiohttp.ClientSession() as session:
        yield ShmuClient(session, ssl_context=create_ssl_context())


def _assert_fresh(newest: datetime, what: str) -> None:
    now = datetime.now(UTC)
    assert newest <= now + FUTURE_SLACK, f"{what} newest {newest} is in the future"
    assert now - newest <= FRESH_WITHIN, f"{what} newest {newest} is stale"


async def test_observations(client: ShmuClient) -> None:
    snap = await client.async_get_observations()
    _assert_fresh(max(o.measured_at for o in snap.observations.values()), "aws1min")

    # The catalogue is hand-curated (stations.py); most of it must still report.
    reporting = [
        s
        for s in STATIONS
        if (o := snap.observations.get(s.ind_kli)) and o.temperature is not None
    ]
    assert len(reporting) >= 0.8 * len(STATIONS), (
        f"only {len(reporting)}/{len(STATIONS)} catalogue stations report"
    )
    # Checked per network too, so the larger non-synoptic part could not hide
    # the synoptic stations (the ones reporting pressure) going quiet.
    synoptic = [s for s in STATIONS if s.synoptic]
    reporting_synoptic = [s for s in reporting if s.synoptic]
    assert len(reporting_synoptic) >= 0.8 * len(synoptic), (
        f"only {len(reporting_synoptic)}/{len(synoptic)} synoptic stations report"
    )

    # AGENTS.md: the catalogue holds every feed station with known coordinates,
    # and only Oravice and Jakubovany lacked them. More unknown ids means SHMÚ
    # added stations and stations.py needs regenerating.
    unknown = set(snap.observations) - {s.ind_kli for s in STATIONS}
    assert len(unknown) <= 3, f"feed ids missing from stations.py: {sorted(unknown)}"

    # A station marked in_feed=False is hidden from new entries; if SHMÚ
    # publishes it again, flip the flag so it can be chosen once more.
    back = [
        s.name for s in STATIONS if not s.in_feed and s.ind_kli in snap.observations
    ]
    assert not back, f"reporting again, set in_feed=True in stations.py: {back}"


async def test_observation_file_names_are_local_time(client: ShmuClient) -> None:
    # AGENTS.md: day folders and file names are Slovak wall time (CET/CEST),
    # unlike `minuta`, which is fixed UTC+1. Read as UTC instead, the name
    # would sit one or two hours *after* the file's Last-Modified.
    snap = await client.async_get_observations()
    assert snap.published_at is not None, "no Last-Modified on the newest file"
    match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2})\.json$", snap.source)
    assert match, f"unexpected file name {snap.source}"
    named = (
        datetime.strptime(match[1], "%Y-%m-%d %H-%M-%S")
        .replace(tzinfo=_BRATISLAVA)
        .astimezone(UTC)
    )
    # The day folder follows the same local date, so just after local
    # midnight it is a UTC day ahead.
    assert snap.source.split("/")[-2] == match[1][:10].replace("-", "")
    lag = snap.published_at - named
    assert timedelta(0) <= lag <= PUBLISH_LAG, (
        f"{snap.source}: Last-Modified {snap.published_at} is {lag} after the "
        "name read as Europe/Bratislava time"
    )


async def test_rain_gauges(client: ShmuClient) -> None:
    snap = await client.async_get_gauge_observations()
    _assert_fresh(max(o.measured_at for o in snap.observations.values()), "aps1min")

    # Both networks would match a renumbered id set by luck at best, so a
    # mostly-unknown feed means the catalogue (gauges.py) needs regenerating.
    known = sum(1 for g in GAUGES if g.ind_zra in snap.observations)
    assert known >= 0.5 * len(GAUGES), f"only {known}/{len(GAUGES)} gauges present"


async def test_warnings(client: ShmuClient) -> None:
    snap = await client.async_get_warnings()

    if snap.source == WARNINGS_PATH:
        # Calm weather empties the tree; nothing more to check today.
        assert snap.warnings == []
        return
    # An issuance exists, so it must yield alerts: the client skips CAP files
    # it cannot parse, and an empty list here would hide a parser broken by an
    # upstream format change behind what looks like calm weather.
    assert snap.source.startswith(f"{WARNINGS_PATH}/")
    assert snap.warnings, f"no parseable alerts in {snap.source}"
    for warning in snap.warnings:
        assert warning.identifier
        assert warning.event
        assert warning.severity
        assert warning.areas or warning.polygons, warning.identifier


async def test_website_conditions(client: ShmuClient) -> None:
    snap = await client.async_get_web_conditions()

    # The scraper must still find the table and map its rows to stations. The
    # condition columns themselves are often blank, so they are not asserted.
    parsed = sum(1 for s in STATIONS if s.ind_kli in snap.conditions)
    assert parsed >= 0.8 * len(STATIONS), (
        f"scraper matched only {parsed}/{len(STATIONS)} catalogue stations"
    )


async def test_forecast(client: ShmuClient) -> None:
    snap = await client.async_get_forecast(LATITUDE, LONGITUDE)

    # Four runs a day; the newest usable one should never be over a day old.
    assert datetime.now(UTC) - snap.run <= timedelta(hours=30), snap.run
    horizon = snap.steps[-1].time - snap.run
    assert horizon >= timedelta(hours=MIN_FORECAST_HOURS), horizon

    for step in snap.steps:
        missing = [
            name
            for name in (
                "temperature",
                "wind_speed",
                "wind_gust",
                "wind_bearing",
                "pressure",
                "cloud_coverage",
                "cape",
                "temperature_850hpa",
                "condition",
            )
            if getattr(step, name) is None
        ]
        # Hour 000 carries no accumulated precipitation (orography takes its
        # slot); every later hour must.
        if step.time != snap.run and step.precipitation is None:
            missing.append("precipitation")
        # A field that silently stops decoding (changed level set, new
        # parameter number) shows up only as None — exactly what this catches.
        assert not missing, f"{step.time}: missing {missing}"
        assert step.temperature is not None
        assert -50 < step.temperature < 50, step


async def test_radar(client: ShmuClient) -> None:
    snap = await client.async_get_radar(LATITUDE, LONGITUDE)
    _assert_fresh(snap.valid_at, "radar")

    assert len(snap.frames) == RADAR_LOOP_FRAMES
    assert snap.image.png.startswith(_PNG_SIGNATURE)
    assert snap.map_image.png.startswith(_PNG_SIGNATURE)
    assert snap.loop_png.startswith(_PNG_SIGNATURE)
