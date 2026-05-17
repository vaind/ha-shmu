"""Tests for the async client (HTTP mocked with aioresponses)."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.shmu.shmu_opendata import ShmuClient, ShmuConnectionError

BASE = "https://opendata.shmu.sk"
OBS = "/meteorology/climate/now/data"
WARN = "/meteorology/weather/alerts/cap"
WEB = "https://www.shmu.sk/sk/?page=1&id=meteo_apocasie_sk"


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
