"""Tests for the async client (HTTP mocked with aioresponses)."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.shmu.shmu_opendata import (
    ShmuClient,
    ShmuConnectionError,
    ShmuDataError,
)

BASE = "https://opendata.shmu.sk"
OBS = "/meteorology/climate/now/data"
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
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


async def test_get_observations_and_change_detection(session, fixture) -> None:
    obs_file = "aws1min%20-%202026-05-17%2006-55-00.json"
    with aioresponses() as m:
        # Directory listings are read on every call (small); register repeating.
        m.get(f"{BASE}{OBS}/", body=_listing("20260517/"), repeat=True)
        m.get(
            f"{BASE}{OBS}/20260517/",
            body=_listing(obs_file, "aws1min%20-%202026-05-17%2006-50-00.json"),
            repeat=True,
        )
        # The large body is registered only ONCE on purpose.
        m.get(
            f"{BASE}{OBS}/20260517/{obs_file}",
            body=fixture("observations.json"),
        )

        client = ShmuClient(session)
        snap = await client.async_get_observations()
        assert snap.source == f"{OBS}/20260517/aws1min - 2026-05-17 06-55-00.json"
        assert set(snap.observations) == {11858, 11816, 11930}
        assert snap.observations[11858].temperature == 12.1

        # Same newest file -> previous returned, body NOT fetched again
        # (it was only registered once; a second GET would raise).
        again = await client.async_get_observations(previous=snap)
        assert again is snap


async def test_observations_fall_back_to_previous_day_folder(session, fixture) -> None:
    # Midnight rollover: the new day's folder exists but has no file yet.
    obs_file = "aws1min%20-%202026-05-17%2006-55-00.json"
    with aioresponses() as m:
        m.get(f"{BASE}{OBS}/", body=_listing("20260518/", "20260517/"))
        m.get(f"{BASE}{OBS}/20260518/", body=_listing())  # empty new folder
        m.get(f"{BASE}{OBS}/20260517/", body=_listing(obs_file))
        m.get(f"{BASE}{OBS}/20260517/{obs_file}", body=fixture("observations.json"))

        snap = await ShmuClient(session).async_get_observations()
        assert snap.source == f"{OBS}/20260517/aws1min - 2026-05-17 06-55-00.json"
        assert snap.observations[11858].temperature == 12.1


async def test_get_warnings(session, fixture) -> None:
    with aioresponses() as m:
        m.get(f"{BASE}{WARN}/", body=_listing("20260517/"))
        m.get(f"{BASE}{WARN}/20260517/", body=_listing("0353/"))
        m.get(
            f"{BASE}{WARN}/20260517/0353/",
            body=_listing("sk.shmu.meteo.alert.00001.cap.xml"),
        )
        m.get(
            f"{BASE}{WARN}/20260517/0353/sk.shmu.meteo.alert.00001.cap.xml",
            body=fixture("alert.cap.xml"),
        )

        client = ShmuClient(session)
        snap = await client.async_get_warnings()
        assert len(snap.warnings) == 1
        assert snap.warnings[0].event == "Výstraha pred dažďom"
        assert snap.source == f"{WARN}/20260517/0353"


async def test_get_web_conditions(session, fixture) -> None:
    with aioresponses() as m:
        m.get(WEB, body=fixture("apocasie.html"))
        client = ShmuClient(session)
        snap = await client.async_get_web_conditions()
        assert snap.conditions[11858].condition == "rainy"


async def test_connection_error_is_wrapped(session) -> None:
    with aioresponses() as m:
        m.get(f"{BASE}{OBS}/", exception=aiohttp.ClientError("boom"))
        client = ShmuClient(session)
        with pytest.raises(ShmuConnectionError):
            await client.async_get_observations()


def _register_run(m, fixture, day: str, run: str, hours: list[int]) -> None:
    """Register a forecast run folder listing plus its GRIB2 files."""
    names = [_grib_name(h, day, run) for h in hours]
    m.get(f"{BASE}{FCAST}/{day}/{run}/", body=_listing(*names), repeat=True)
    for h, name in zip(hours, names, strict=True):
        m.get(
            f"{BASE}{FCAST}/{day}/{run}/{name}",
            body=fixture(f"aladin_{h:03d}.grb"),
        )


async def test_get_forecast_discovers_and_decodes(session, fixture) -> None:
    with aioresponses() as m:
        m.get(f"{BASE}{FCAST}/", body=_listing("20260517/"), repeat=True)
        m.get(f"{BASE}{FCAST}/20260517/", body=_listing("1200/"), repeat=True)
        _register_run(m, fixture, "20260517", "1200", [0, 1, 2])

        client = ShmuClient(session)
        snap = await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))

        assert snap.source == f"{FCAST}/20260517/1200"
        assert snap.run.isoformat() == "2026-05-17T12:00:00+00:00"
        assert len(snap.steps) == 3
        assert snap.steps[0].time.isoformat() == "2026-05-17T12:00:00+00:00"
        assert snap.steps[1].condition == "rainy"


async def test_get_forecast_skips_incomplete_newest_run(session, fixture) -> None:
    """The newest run is still publishing; fall back to the last complete one."""
    with aioresponses() as m:
        m.get(f"{BASE}{FCAST}/", body=_listing("20260517/"), repeat=True)
        m.get(
            f"{BASE}{FCAST}/20260517/",
            body=_listing("1800/", "1200/"),
            repeat=True,
        )
        # 1800 lacks the requested final hour -> not usable yet.
        m.get(
            f"{BASE}{FCAST}/20260517/1800/",
            body=_listing(_grib_name(0, run="1800"), _grib_name(1, run="1800")),
            repeat=True,
        )
        _register_run(m, fixture, "20260517", "1200", [0, 1, 2])

        client = ShmuClient(session)
        snap = await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))
        assert snap.source == f"{FCAST}/20260517/1200"


async def test_get_forecast_caches_by_run_folder(session, fixture) -> None:
    with aioresponses() as m:
        m.get(f"{BASE}{FCAST}/", body=_listing("20260517/"), repeat=True)
        m.get(f"{BASE}{FCAST}/20260517/", body=_listing("1200/"), repeat=True)
        # GRIB2 files registered ONCE: a second download would raise.
        _register_run(m, fixture, "20260517", "1200", [0, 1, 2])

        client = ShmuClient(session)
        first = await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))
        again = await client.async_get_forecast(
            48.1717, 17.2, forecast_hours=(0, 1, 2), previous=first
        )
        assert again is first  # unchanged run -> cached, not re-downloaded


async def test_get_forecast_no_complete_run_raises(session, fixture) -> None:
    with aioresponses() as m:
        m.get(f"{BASE}{FCAST}/", body=_listing("20260517/"), repeat=True)
        m.get(f"{BASE}{FCAST}/20260517/", body=_listing("1200/"), repeat=True)
        m.get(
            f"{BASE}{FCAST}/20260517/1200/",
            body=_listing(_grib_name(0), _grib_name(1)),
            repeat=True,
        )
        client = ShmuClient(session)
        with pytest.raises(ShmuDataError, match="No ALADIN run with all"):
            await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))


async def test_get_forecast_rejects_run_missing_intermediate_hour(
    session, fixture
) -> None:
    """A gap in the requested hours would misattribute accumulated precip,
    so such a run must be skipped, not silently used."""
    with aioresponses() as m:
        m.get(f"{BASE}{FCAST}/", body=_listing("20260517/"), repeat=True)
        m.get(f"{BASE}{FCAST}/20260517/", body=_listing("1200/"), repeat=True)
        # Hour 1 is absent though the final requested hour (2) is present.
        m.get(
            f"{BASE}{FCAST}/20260517/1200/",
            body=_listing(_grib_name(0), _grib_name(2)),
            repeat=True,
        )
        client = ShmuClient(session)
        with pytest.raises(ShmuDataError, match="No ALADIN run with all"):
            await client.async_get_forecast(48.1717, 17.2, forecast_hours=(0, 1, 2))


_RADAR_OLD = "T_PABV22_C_LZIB_20260517201500.hdf"
_RADAR_NEW = "T_PABV22_C_LZIB_20260517202000.hdf"


async def test_get_radar_discovers_and_renders(session, fixture) -> None:
    with aioresponses() as m:
        m.get(f"{BASE}{RADAR}/", body=_listing("20260517/"), repeat=True)
        m.get(
            f"{BASE}{RADAR}/20260517/",
            body=_listing(_RADAR_OLD, _RADAR_NEW),
            repeat=True,
        )
        # The ~0.3 MB HDF5 is registered ONCE: a second GET would raise.
        m.get(
            f"{BASE}{RADAR}/20260517/{_RADAR_NEW}",
            body=fixture("radar_zmax.hdf"),
        )

        client = ShmuClient(session)
        snap = await client.async_get_radar()
        assert snap.source == f"{RADAR}/20260517/{_RADAR_NEW}"
        assert snap.product == "zmax"
        assert snap.valid_at.isoformat() == "2026-05-17T20:20:00+00:00"
        assert snap.image.png[:8] == b"\x89PNG\r\n\x1a\n"
        assert (snap.image.width, snap.image.height) == (64, 48)

        # Same newest frame -> cached, the body is not fetched again.
        again = await client.async_get_radar(previous=snap)
        assert again is snap


async def test_get_radar_falls_back_to_previous_day_folder(session, fixture) -> None:
    with aioresponses() as m:
        m.get(f"{BASE}{RADAR}/", body=_listing("20260518/", "20260517/"))
        m.get(f"{BASE}{RADAR}/20260518/", body=_listing())  # empty new day
        m.get(f"{BASE}{RADAR}/20260517/", body=_listing(_RADAR_NEW))
        m.get(
            f"{BASE}{RADAR}/20260517/{_RADAR_NEW}",
            body=fixture("radar_zmax.hdf"),
        )

        snap = await ShmuClient(session).async_get_radar()
        assert snap.source == f"{RADAR}/20260517/{_RADAR_NEW}"


async def test_get_radar_no_files_raises(session) -> None:
    with aioresponses() as m:
        m.get(f"{BASE}{RADAR}/", body=_listing("20260517/"))
        m.get(f"{BASE}{RADAR}/20260517/", body=_listing())
        with pytest.raises(ShmuDataError, match="No radar files"):
            await ShmuClient(session).async_get_radar()
