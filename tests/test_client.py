"""Tests for the async client, with HTTP mocked by HA's ``AiohttpClientMocker``.

It ships with the aiohttp Home Assistant pins, so unlike a third-party mock it
cannot fall behind it. The library under test stays HA-free.

A registration answers any number of requests: tests that a body is *not*
re-downloaded count requests (``_fetches``), and a response that changes
between polls is re-registered after ``clear_requests()``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from yarl import URL

from custom_components.shmu.shmu_opendata import (
    ShmuClient,
    ShmuConnectionError,
    ShmuDataError,
)
from custom_components.shmu.shmu_opendata import client as client_module
from custom_components.shmu.shmu_opendata.client import _frame_label

BASE = "https://opendata.shmu.sk"
OBS = "/meteorology/climate/now/data"
GAUGE = "/meteorology/precipitation/now/data"
WARN = "/meteorology/weather/alerts/cap"
FCAST = "/meteorology/weather/nwp/aladin/sk/4.5km"
RADAR = "/meteorology/weather/radar/composite/skcomp/zmax"
WEB = "https://www.shmu.sk/sk/?page=1&id=meteo_apocasie_sk"


def _grib_name(hour: int, day: str = "20260517", run: str = "1200") -> str:
    return f"al-grib_sk_{hour:03d}-{day}-{run}-nwp-.grb"


def _listing(*entries: str) -> str:
    links = "".join(f'<a href="{e}">{e}</a>' for e in entries)
    return f"<html><body>{links}</body></html>"


@pytest.fixture
def http() -> AiohttpClientMocker:
    return AiohttpClientMocker()


@pytest.fixture
async def session(http: AiohttpClientMocker) -> AsyncIterator[aiohttp.ClientSession]:
    s = http.create_session(asyncio.get_running_loop())
    yield s
    await s.close()


def _fetches(http: AiohttpClientMocker, url: str) -> int:
    """How many requests the client made for ``url``."""
    return sum(call[1] == URL(url) for call in http.mock_calls)


async def test_get_observations_and_change_detection(http, session, fixture) -> None:
    obs_file = "aws1min%20-%202026-05-17%2006-55-00.json"
    http.get(f"{BASE}{OBS}/", text=_listing("20260517/"))
    http.get(
        f"{BASE}{OBS}/20260517/",
        text=_listing(obs_file, "aws1min%20-%202026-05-17%2006-50-00.json"),
    )
    body_url = f"{BASE}{OBS}/20260517/{obs_file}"
    http.get(
        body_url,
        content=fixture("observations.json"),
    )

    client = ShmuClient(session)
    snap = await client.async_get_observations()
    assert snap.source == f"{OBS}/20260517/aws1min - 2026-05-17 06-55-00.json"
    assert set(snap.observations) == {11858, 11816, 11930}
    assert snap.observations[11858].temperature == 12.1

    # Same newest file -> previous returned, body NOT re-fetched.
    again = await client.async_get_observations(previous=snap)
    assert again is snap
    assert _fetches(http, body_url) == 1


async def test_get_gauge_observations_and_change_detection(
    http, session, fixture
) -> None:
    gauge_file = "aps1min%20-%202026-05-17%2006-55-00.json"
    http.get(f"{BASE}{GAUGE}/", text=_listing("20260517/"))
    http.get(
        f"{BASE}{GAUGE}/20260517/",
        text=_listing(gauge_file, "aps1min%20-%202026-05-17%2006-50-00.json"),
    )
    body_url = f"{BASE}{GAUGE}/20260517/{gauge_file}"
    http.get(body_url, content=fixture("gauge_observations.json"))

    client = ShmuClient(session)
    snap = await client.async_get_gauge_observations()
    assert snap.source == f"{GAUGE}/20260517/aps1min - 2026-05-17 06-55-00.json"
    assert snap.observations[17720].precipitation == 0.4

    # Same newest file -> previous returned, body NOT re-fetched.
    again = await client.async_get_gauge_observations(previous=snap)
    assert again is snap
    assert _fetches(http, body_url) == 1


async def test_gauge_observations_fall_back_to_previous_day_folder(
    http, session, fixture
) -> None:
    # Midnight rollover: the new day's folder exists but has no file yet.
    gauge_file = "aps1min%20-%202026-05-17%2006-55-00.json"
    http.get(f"{BASE}{GAUGE}/", text=_listing("20260518/", "20260517/"))
    http.get(f"{BASE}{GAUGE}/20260518/", text=_listing())  # empty new folder
    http.get(f"{BASE}{GAUGE}/20260517/", text=_listing(gauge_file))
    http.get(
        f"{BASE}{GAUGE}/20260517/{gauge_file}",
        content=fixture("gauge_observations.json"),
    )

    snap = await ShmuClient(session).async_get_gauge_observations()

    assert snap.source.endswith("20260517/aps1min - 2026-05-17 06-55-00.json")


async def test_gauge_observations_ignore_the_other_feeds_files(http, session) -> None:
    """Only ``aps1min`` files count, even though the layout is shared."""
    http.get(f"{BASE}{GAUGE}/", text=_listing("20260517/"))
    http.get(
        f"{BASE}{GAUGE}/20260517/",
        text=_listing("aws1min%20-%202026-05-17%2006-55-00.json"),
    )

    with pytest.raises(ShmuDataError):
        await ShmuClient(session).async_get_gauge_observations()


async def test_observations_fall_back_to_previous_day_folder(
    http, session, fixture
) -> None:
    # Midnight rollover: the new day's folder exists but has no file yet.
    obs_file = "aws1min%20-%202026-05-17%2006-55-00.json"
    http.get(f"{BASE}{OBS}/", text=_listing("20260518/", "20260517/"))
    http.get(f"{BASE}{OBS}/20260518/", text=_listing())  # empty new folder
    http.get(f"{BASE}{OBS}/20260517/", text=_listing(obs_file))
    http.get(f"{BASE}{OBS}/20260517/{obs_file}", content=fixture("observations.json"))

    snap = await ShmuClient(session).async_get_observations()
    assert snap.source == f"{OBS}/20260517/aws1min - 2026-05-17 06-55-00.json"
    assert snap.observations[11858].temperature == 12.1


async def test_get_warnings(http, session, fixture) -> None:
    http.get(f"{BASE}{WARN}/", text=_listing("20260517/"))
    http.get(f"{BASE}{WARN}/20260517/", text=_listing("0353/"))
    http.get(
        f"{BASE}{WARN}/20260517/0353/",
        text=_listing("sk.shmu.meteo.alert.00001.cap.xml"),
    )
    http.get(
        f"{BASE}{WARN}/20260517/0353/sk.shmu.meteo.alert.00001.cap.xml",
        content=fixture("alert.cap.xml"),
    )

    client = ShmuClient(session)
    snap = await client.async_get_warnings()
    assert len(snap.warnings) == 1
    assert snap.warnings[0].event == "Výstraha pred dažďom"
    assert snap.source == f"{WARN}/20260517/0353"


async def test_empty_warnings_tree_means_no_warnings(http, session, fixture) -> None:
    # Live 2026-10-13: with nothing in force, SHMÚ prunes old day folders and
    # publishes no empty issuance, so the CAP root lists nothing at all. The
    # fixture is that real Apache page, sort and parent links included.
    http.get(f"{BASE}{WARN}/", content=fixture("cap_empty_listing.html"))

    snap = await ShmuClient(session).async_get_warnings()
    assert snap.warnings == []
    assert snap.source == WARN


async def test_warnings_root_without_day_folders_is_an_error(http, session) -> None:
    # Entries that are not day folders mean the layout changed, not that the
    # weather is calm; reporting "no warnings" would hide active ones.
    http.get(f"{BASE}{WARN}/", text=_listing("2026-10-13/", "latest.xml"))

    with pytest.raises(ShmuDataError):
        await ShmuClient(session).async_get_warnings()


async def test_get_web_conditions(http, session, fixture) -> None:
    http.get(WEB, content=fixture("apocasie.html"))
    client = ShmuClient(session)
    snap = await client.async_get_web_conditions()
    assert snap.conditions[11858].condition == "rainy"


async def test_connection_error_is_wrapped(http, session) -> None:
    http.get(f"{BASE}{OBS}/", exc=aiohttp.ClientError("boom"))
    client = ShmuClient(session)
    with pytest.raises(ShmuConnectionError):
        await client.async_get_observations()


def _register_run(http, fixture, day: str, run: str, hours: list[int]) -> None:
    """Register a forecast run folder listing plus its GRIB2 files."""
    names = [_grib_name(h, day, run) for h in hours]
    http.get(f"{BASE}{FCAST}/{day}/{run}/", text=_listing(*names))
    for h, name in zip(hours, names, strict=True):
        http.get(
            f"{BASE}{FCAST}/{day}/{run}/{name}",
            content=fixture(f"aladin_{h:03d}.grb"),
        )


async def test_get_forecast_discovers_and_decodes(http, session, fixture) -> None:
    http.get(f"{BASE}{FCAST}/", text=_listing("20260517/"))
    http.get(f"{BASE}{FCAST}/20260517/", text=_listing("1200/"))
    _register_run(http, fixture, "20260517", "1200", [0, 1, 2])

    client = ShmuClient(session)
    snap = await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))

    assert snap.source == f"{FCAST}/20260517/1200"
    assert snap.run.isoformat() == "2026-05-17T12:00:00+00:00"
    assert len(snap.steps) == 3
    assert snap.steps[0].time.isoformat() == "2026-05-17T12:00:00+00:00"
    assert snap.steps[1].condition == "rainy"


async def test_get_forecast_decodes_off_the_event_loop(
    http, session, fixture, monkeypatch
) -> None:
    """The GRIB2 decode is pure-Python CPU work over a whole run (~67 files of
    36 messages live); run inline it would freeze Home Assistant for seconds
    on every new model run and at every startup."""
    decode_threads: list[threading.Thread] = []
    real_parse = client_module.parse_forecast

    def recording_parse(*args, **kwargs):
        decode_threads.append(threading.current_thread())
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(client_module, "parse_forecast", recording_parse)
    http.get(f"{BASE}{FCAST}/", text=_listing("20260517/"))
    http.get(f"{BASE}{FCAST}/20260517/", text=_listing("1200/"))
    _register_run(http, fixture, "20260517", "1200", [0, 1, 2])

    client = ShmuClient(session)
    snap = await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))

    assert len(snap.steps) == 3
    assert decode_threads, "parse_forecast was not called"
    assert threading.current_thread() not in decode_threads


async def test_get_forecast_skips_incomplete_newest_run(http, session, fixture) -> None:
    """The newest run is still publishing; fall back to the last complete one."""
    http.get(f"{BASE}{FCAST}/", text=_listing("20260517/"))
    http.get(
        f"{BASE}{FCAST}/20260517/",
        text=_listing("1800/", "1200/"),
    )
    # 1800 lacks the requested final hour -> not usable yet.
    http.get(
        f"{BASE}{FCAST}/20260517/1800/",
        text=_listing(_grib_name(0, run="1800"), _grib_name(1, run="1800")),
    )
    _register_run(http, fixture, "20260517", "1200", [0, 1, 2])

    client = ShmuClient(session)
    snap = await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))
    assert snap.source == f"{FCAST}/20260517/1200"


async def test_get_forecast_caches_by_run_folder(http, session, fixture) -> None:
    http.get(f"{BASE}{FCAST}/", text=_listing("20260517/"))
    http.get(f"{BASE}{FCAST}/20260517/", text=_listing("1200/"))
    _register_run(http, fixture, "20260517", "1200", [0, 1, 2])

    client = ShmuClient(session)
    first = await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))
    again = await client.async_get_forecast(
        48.1717, 17.2, forecast_hours=(0, 1, 2), previous=first
    )
    assert again is first  # unchanged run -> cached, not re-downloaded
    for hour in (0, 1, 2):
        url = f"{BASE}{FCAST}/20260517/1200/{_grib_name(hour)}"
        assert _fetches(http, url) == 1


async def test_get_forecast_no_complete_run_raises(http, session, fixture) -> None:
    http.get(f"{BASE}{FCAST}/", text=_listing("20260517/"))
    http.get(f"{BASE}{FCAST}/20260517/", text=_listing("1200/"))
    http.get(
        f"{BASE}{FCAST}/20260517/1200/",
        text=_listing(_grib_name(0), _grib_name(1)),
    )
    client = ShmuClient(session)
    with pytest.raises(ShmuDataError, match="No ALADIN run publishing"):
        await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))


async def test_get_forecast_rejects_run_missing_intermediate_hour(
    http, session, fixture
) -> None:
    """A gap in the requested hours would misattribute accumulated precip,
    so such a run must be skipped, not silently used."""
    http.get(f"{BASE}{FCAST}/", text=_listing("20260517/"))
    http.get(f"{BASE}{FCAST}/20260517/", text=_listing("1200/"))
    # Hour 1 is absent though the final requested hour (2) is present.
    http.get(
        f"{BASE}{FCAST}/20260517/1200/",
        text=_listing(_grib_name(0), _grib_name(2)),
    )
    client = ShmuClient(session)
    with pytest.raises(ShmuDataError, match="No ALADIN run publishing"):
        await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))


async def test_get_forecast_accepts_a_run_short_of_the_full_request(
    http, session, fixture, monkeypatch
) -> None:
    """A run reaching the floor is used even without every requested hour.

    Only the 00 UTC run publishes the full +102 h; the 06/12/18 UTC runs stop
    at +72 h. Demanding the whole request rejected three runs in four and
    pinned the forecast to one refresh a day. The floor is patched down here so
    the assertion does not need 73 GRIB2 fixtures.
    """
    monkeypatch.setattr(
        "custom_components.shmu.shmu_opendata.client.MIN_FORECAST_HOURS", 1
    )
    http.get(f"{BASE}{FCAST}/", text=_listing("20260517/"))
    http.get(f"{BASE}{FCAST}/20260517/", text=_listing("1200/"))
    # Hour 2 was requested but is not published; 0 and 1 are contiguous.
    _register_run(http, fixture, "20260517", "1200", [0, 1])

    client = ShmuClient(session)
    snap = await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))

    assert snap.forecast_hours == (0, 1)
    assert len(snap.steps) == 2


async def test_get_forecast_refetches_when_a_run_publishes_further(
    http, session, fixture, monkeypatch
) -> None:
    """A run picked up mid-publication must be re-read once it reaches further.

    The run folder alone is not a sufficient cache key any more: the same
    folder can yield a longer series later, and holding the short one would
    silently cap the horizon until the next run.
    """
    monkeypatch.setattr(
        "custom_components.shmu.shmu_opendata.client.MIN_FORECAST_HOURS", 1
    )
    # First poll sees two hours, the second sees three (same run folder).
    http.get(f"{BASE}{FCAST}/", text=_listing("20260517/"))
    http.get(f"{BASE}{FCAST}/20260517/", text=_listing("1200/"))
    _register_run(http, fixture, "20260517", "1200", [0, 1])

    client = ShmuClient(session)
    first = await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))
    assert first.forecast_hours == (0, 1)

    http.clear_requests()
    http.get(f"{BASE}{FCAST}/", text=_listing("20260517/"))
    http.get(f"{BASE}{FCAST}/20260517/", text=_listing("1200/"))
    _register_run(http, fixture, "20260517", "1200", [0, 1, 2])

    again = await client.async_get_forecast(
        48.1717, 17.2, forecast_hours=(0, 1, 2), previous=first
    )
    assert again is not first  # same folder, longer set -> re-read
    assert again.forecast_hours == (0, 1, 2)
    assert len(again.steps) == 3


_RADAR_OLD = "T_PABV22_C_LZIB_20260517201000.hdf"
_RADAR_MID = "T_PABV22_C_LZIB_20260517201500.hdf"
_RADAR_NEW = "T_PABV22_C_LZIB_20260517202000.hdf"
_RADAR_NEWER = "T_PABV22_C_LZIB_20260517202500.hdf"


def _is_apng(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n" and b"acTL" in data


async def test_get_radar_backfills_a_loop(http, session, fixture) -> None:
    http.get(f"{BASE}{RADAR}/", text=_listing("20260517/"))
    http.get(
        f"{BASE}{RADAR}/20260517/",
        text=_listing(_RADAR_OLD, _RADAR_MID, _RADAR_NEW),
    )
    for name in (_RADAR_OLD, _RADAR_MID, _RADAR_NEW):
        http.get(f"{BASE}{RADAR}/20260517/{name}", content=fixture("radar_zmax.hdf"))

    client = ShmuClient(session)
    snap = await client.async_get_radar(48.1686, 17.1106)

    # The newest frame drives the still picture / max_dbz.
    assert snap.source == f"{RADAR}/20260517/{_RADAR_NEW}"
    assert snap.product == "zmax"
    assert snap.valid_at.isoformat() == "2026-05-17T20:20:00+00:00"
    assert snap.image.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert 0 < snap.image.width < 64
    assert (snap.image.center_lat, snap.image.center_lon) == (48.1686, 17.1106)
    # The loop is the whole backfilled buffer, oldest -> newest.
    assert [f.source for f in snap.frames] == [
        f"{RADAR}/20260517/{_RADAR_OLD}",
        f"{RADAR}/20260517/{_RADAR_MID}",
        f"{RADAR}/20260517/{_RADAR_NEW}",
    ]
    assert [f.valid_at for f in snap.frames] == sorted(f.valid_at for f in snap.frames)
    assert _is_apng(snap.loop_png)

    # Nothing new published -> every frame reused, none re-fetched.
    again = await client.async_get_radar(48.1686, 17.1106, previous=snap)
    assert again is snap
    for name in (_RADAR_OLD, _RADAR_MID, _RADAR_NEW):
        assert _fetches(http, f"{BASE}{RADAR}/20260517/{name}") == 1


async def test_get_radar_appends_only_the_new_frame(http, session, fixture) -> None:
    def publish(*names: str) -> None:
        http.get(f"{BASE}{RADAR}/", text=_listing("20260517/"))
        http.get(f"{BASE}{RADAR}/20260517/", text=_listing(*names))
        for name in names:
            http.get(
                f"{BASE}{RADAR}/20260517/{name}", content=fixture("radar_zmax.hdf")
            )

    publish(_RADAR_OLD, _RADAR_MID, _RADAR_NEW)
    client = ShmuClient(session)
    first = await client.async_get_radar(48.1686, 17.1106)

    # The listing grows by one between the two polls.
    http.clear_requests()
    publish(_RADAR_OLD, _RADAR_MID, _RADAR_NEW, _RADAR_NEWER)
    second = await client.async_get_radar(48.1686, 17.1106, previous=first)

    # Only the new frame is downloaded; the reused ones are not re-fetched.
    fetched = [
        name
        for name in (_RADAR_OLD, _RADAR_MID, _RADAR_NEW, _RADAR_NEWER)
        if _fetches(http, f"{BASE}{RADAR}/20260517/{name}")
    ]
    assert fetched == [_RADAR_NEWER]
    assert second is not first
    assert second.source == f"{RADAR}/20260517/{_RADAR_NEWER}"
    assert len(second.frames) == 4
    # Carried-over frames are the very same objects.
    for old, new in zip(first.frames, second.frames[:3], strict=True):
        assert old is new


async def test_get_radar_loop_is_a_rolling_window(
    http, session, fixture, monkeypatch
) -> None:
    monkeypatch.setattr(
        "custom_components.shmu.shmu_opendata.client.RADAR_LOOP_FRAMES", 2
    )
    http.get(f"{BASE}{RADAR}/", text=_listing("20260517/"))
    http.get(
        f"{BASE}{RADAR}/20260517/",
        text=_listing(_RADAR_OLD, _RADAR_MID, _RADAR_NEW),
    )
    # Only the two newest are fetched; the oldest is outside the window.
    for name in (_RADAR_MID, _RADAR_NEW):
        http.get(f"{BASE}{RADAR}/20260517/{name}", content=fixture("radar_zmax.hdf"))

    snap = await ShmuClient(session).async_get_radar(48.1686, 17.1106)
    assert [f.source for f in snap.frames] == [
        f"{RADAR}/20260517/{_RADAR_MID}",
        f"{RADAR}/20260517/{_RADAR_NEW}",
    ]
    assert _fetches(http, f"{BASE}{RADAR}/20260517/{_RADAR_OLD}") == 0


async def test_get_radar_falls_back_to_previous_day_folder(
    http, session, fixture
) -> None:
    http.get(f"{BASE}{RADAR}/", text=_listing("20260518/", "20260517/"))
    http.get(f"{BASE}{RADAR}/20260518/", text=_listing())  # empty new day
    http.get(f"{BASE}{RADAR}/20260517/", text=_listing(_RADAR_NEW))
    http.get(
        f"{BASE}{RADAR}/20260517/{_RADAR_NEW}",
        content=fixture("radar_zmax.hdf"),
    )

    snap = await ShmuClient(session).async_get_radar(48.1686, 17.1106)
    assert snap.source == f"{RADAR}/20260517/{_RADAR_NEW}"
    assert len(snap.frames) == 1
    assert _is_apng(snap.loop_png)


async def test_get_radar_no_files_raises(http, session) -> None:
    http.get(f"{BASE}{RADAR}/", text=_listing("20260517/"))
    http.get(f"{BASE}{RADAR}/20260517/", text=_listing())
    with pytest.raises(ShmuDataError, match="No radar files"):
        await ShmuClient(session).async_get_radar(48.1686, 17.1106)


def test_frame_label_uses_the_ha_timezone() -> None:
    ts = datetime(2026, 5, 18, 17, 20, tzinfo=UTC)
    # Europe/Bratislava is CEST (UTC+2) in May.
    assert _frame_label(ts, "Europe/Bratislava") == "2026-05-18 19:20"
    # No / unknown zone -> UTC, so the picture still carries a real time.
    assert _frame_label(ts, None) == "2026-05-18 17:20"
    assert _frame_label(ts, "Not/AZone") == "2026-05-18 17:20"
