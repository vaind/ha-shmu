"""Setup / entity tests with a stubbed SHMÚ client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shmu.const import (
    CONF_IND_KLI,
    CONF_LOCATION,
    CONF_LOCATION_MODE,
    DOMAIN,
    LOCATION_MODE_CUSTOM,
    LOCATION_MODE_HASS,
    LOCATION_MODE_STATION,
    OBSERVATION_STALE_AFTER,
)
from custom_components.shmu.shmu_opendata import (
    ForecastSnapshot,
    GaugeSnapshot,
    ObservationSnapshot,
    RadarFrame,
    RadarSnapshot,
    ShmuConnectionError,
    WarningsSnapshot,
    WebConditionsSnapshot,
    get_station,
)
from custom_components.shmu.shmu_opendata.client import _frame_label, _radar_snapshot
from custom_components.shmu.shmu_opendata.forecast import grid_index, parse_forecast
from custom_components.shmu.shmu_opendata.parsers import (
    parse_cap_alert,
    parse_gauge_observations,
    parse_observations,
)
from custom_components.shmu.shmu_opendata.radar import render_radar
from custom_components.shmu.shmu_opendata.website import parse_current_conditions

#: Forecast hours backed by the trimmed real GRIB2 fixtures.
_FCAST_FIXTURE_HOURS = (0, 1, 2, 24)


class _FakeClient:
    """Stand-in for ShmuClient returning canned, fixture-derived snapshots."""

    def __init__(self, load: Callable[[str], bytes]) -> None:
        self._load = load
        #: When True, the next snapshot omits the configured station.
        self.drop_station: int | None = None
        #: Same, for the (independent) rain-gauge feed.
        self.drop_gauge: int | None = None
        #: When set, every fetch raises this — simulates an upstream outage.
        self.fail_with: Exception | None = None
        #: When set, only the rain-gauge fetch raises — that feed is
        #: supplementary, so it fails independently of the observations.
        self.fail_gauges_with: Exception | None = None
        #: Minutes to advance every gauge reading's ``measured_at`` by. The
        #: fixture is static, so by default a refetch returns the *same*
        #: minute — which is exactly what upstream backfill looks like.
        self.gauge_minutes_advanced: int = 0
        #: Coordinates the forecast/radar fetchers were last called with, so
        #: tests can assert the measurement location reaches the client.
        self.forecast_coords: tuple[float, float] | None = None
        self.radar_coords: tuple[float, float] | None = None
        self._serial = 0

    async def async_get_observations(self, previous=None) -> ObservationSnapshot:
        if self.fail_with is not None:
            raise self.fail_with
        observations = parse_observations(self._load("observations.json"))
        if self.drop_station is not None:
            observations.pop(self.drop_station, None)
        self._serial += 1
        return ObservationSnapshot(
            observations=observations,
            source=f"test-{self._serial}",
            fetched_at=datetime.now(UTC),
            published_at=None,
        )

    async def async_get_gauge_observations(self, previous=None) -> GaugeSnapshot:
        if self.fail_gauges_with is not None:
            raise self.fail_gauges_with
        if self.fail_with is not None:
            raise self.fail_with
        gauges = parse_gauge_observations(self._load("gauge_observations.json"))
        if self.drop_gauge is not None:
            gauges.pop(self.drop_gauge, None)
        if self.gauge_minutes_advanced:
            shift = timedelta(minutes=self.gauge_minutes_advanced)
            gauges = {
                k: replace(v, measured_at=v.measured_at + shift)
                for k, v in gauges.items()
            }
        return GaugeSnapshot(
            observations=gauges,
            source=f"test-gauges-{self._serial}",
            fetched_at=datetime.now(UTC),
        )

    async def async_get_warnings(self, previous=None) -> WarningsSnapshot:
        return WarningsSnapshot(
            warnings=[parse_cap_alert(self._load("alert.cap.xml"))],
            source="test",
            fetched_at=datetime.now(UTC),
        )

    async def async_get_web_conditions(self) -> WebConditionsSnapshot:
        return WebConditionsSnapshot(
            conditions=parse_current_conditions(
                self._load("apocasie.html").decode("utf-8")
            ),
            fetched_at=datetime.now(UTC),
        )

    async def async_get_forecast(
        self,
        latitude: float,
        longitude: float,
        *,
        forecast_hours=None,
        previous=None,
    ) -> ForecastSnapshot:
        self.forecast_coords = (latitude, longitude)
        files = [(h, self._load(f"aladin_{h:03d}.grb")) for h in _FCAST_FIXTURE_HOURS]
        return ForecastSnapshot(
            steps=parse_forecast(files, latitude, longitude),
            run=datetime(2026, 5, 17, 12, tzinfo=UTC),
            source="test-run/20260517/1200",
            forecast_hours=tuple(_FCAST_FIXTURE_HOURS),
            grid_point=grid_index(latitude, longitude),
            fetched_at=datetime.now(UTC),
        )

    async def async_get_radar(
        self, latitude, longitude, *, product="zmax", previous=None, tz=None
    ) -> RadarSnapshot:
        self.radar_coords = (latitude, longitude)
        frames = []
        for m in ("10", "15", "20"):
            valid_at = datetime(2026, 5, 17, 20, int(m), tzinfo=UTC)
            frames.append(
                RadarFrame(
                    image=render_radar(
                        self._load("radar_zmax.hdf"),
                        latitude,
                        longitude,
                        label=_frame_label(valid_at, tz),
                    ),
                    source=f"test-run/20260517/T_PABV22_C_LZIB_2026051720{m}00.hdf",
                    valid_at=valid_at,
                )
            )
        return _radar_snapshot(frames, product)


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11858",
        title="Hurbanovo",
        data={CONF_IND_KLI: 11858},
    )
    config_entry.add_to_hass(hass)
    return config_entry


async def test_setup_creates_entities(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    # Polling is driven on the upstream UTC grid, not a fixed interval.
    assert entry.runtime_data.update_interval is None

    weather = hass.states.get("weather.hurbanovo")
    assert weather is not None
    # Website says Zamračené/Dážď for Hurbanovo -> rainy.
    assert weather.state == "rainy"
    assert weather.attributes["temperature"] == 12.1

    # Values come from the latest minute (06:52) of the 3 records for 11858.
    assert hass.states.get("sensor.hurbanovo_temperature").state == "12.1"
    # Raw station pressure (QFE) as reported; the sea-level (QFF) reduction is
    # a separate entity that lifts Hurbanovo's 115 m reading to ~1015 hPa.
    assert hass.states.get("sensor.hurbanovo_pressure").state == "1001.2"
    sea_level = hass.states.get("sensor.hurbanovo_sea_level_pressure")
    assert sea_level is not None
    assert float(sea_level.state) == pytest.approx(1015.06, abs=0.2)

    # The only warning's polygon is around Bratislava; Hurbanovo is outside it.
    assert hass.states.get("binary_sensor.hurbanovo_weather_warning").state == "off"
    assert hass.states.get("sensor.hurbanovo_warning_level").state == "none"


async def test_observation_carried_forward_across_dropout(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    client = _FakeClient(load)
    with patch("custom_components.shmu.ShmuClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.hurbanovo_temperature").state == "12.1"

    # The next snapshot omits the station entirely (a one-cycle dropout).
    client.drop_station = 11858
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    # Last reading is carried forward — no flicker to unknown/unavailable.
    temperature = hass.states.get("sensor.hurbanovo_temperature")
    assert temperature.state == "12.1"
    assert hass.states.get("weather.hurbanovo").state == "rainy"


async def test_entities_survive_transient_update_failure(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """A failed poll must not blank every entity for what is usually a blip.

    Entities stay available while the last successful fetch is within the
    ``OBSERVATION_STALE_AFTER`` window — only a genuine multi-cycle outage
    tips them to unavailable. Otherwise a brief network flake (eg. transient
    DNS / TLS error) would flicker the whole device to "Unavailable".
    """
    client = _FakeClient(load)
    # ``dt_util.utcnow`` is a cached ``functools.partial`` so ``freeze_time``
    # cannot intercept it; patch the module-level reference instead.
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)

    def _now() -> datetime:
        return now

    with (
        patch("custom_components.shmu.coordinator.dt_util.utcnow", _now),
        patch("custom_components.shmu.ShmuClient", return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.hurbanovo_temperature").state == "12.1"
        assert hass.states.get("weather.hurbanovo").state == "rainy"
        # The radar / warning entities live on the same device and need to
        # tolerate the same blip — they read independent coordinator data.
        assert hass.states.get("binary_sensor.hurbanovo_weather_warning").state == "off"
        assert hass.states.get("sensor.hurbanovo_warning_level").state == "none"
        assert hass.states.get("image.hurbanovo_radar").state is not None

        # Upstream becomes unreachable. The coordinator marks the cycle failed
        # but the freshness window hasn't expired yet.
        client.fail_with = ShmuConnectionError("transient TLS error")
        now += timedelta(minutes=10)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        assert entry.runtime_data.last_update_success is False
        # Entities still serve the last good values — no flicker.
        assert hass.states.get("sensor.hurbanovo_temperature").state == "12.1"
        assert hass.states.get("weather.hurbanovo").state == "rainy"
        assert hass.states.get("binary_sensor.hurbanovo_weather_warning").state == "off"
        assert hass.states.get("sensor.hurbanovo_warning_level").state == "none"

        # The outage continues past the tolerance window: now entities flip
        # to unavailable so users (and automations) see the stale state.
        now += OBSERVATION_STALE_AFTER + timedelta(minutes=1)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        assert hass.states.get("sensor.hurbanovo_temperature").state == "unavailable"
        assert hass.states.get("weather.hurbanovo").state == "unavailable"
        assert (
            hass.states.get("binary_sensor.hurbanovo_weather_warning").state
            == "unavailable"
        )
        assert hass.states.get("sensor.hurbanovo_warning_level").state == "unavailable"


async def test_unload(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    with patch("custom_components.shmu.ShmuClient", return_value=_FakeClient(load)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


# --- Measurement location & device naming -----------------------------------

#: A point inside the Bratislava alert polygon (48.10..48.25 N, 17.00..17.25 E),
#: which the configured station (Hurbanovo, 47.87 N 18.19 E) lies outside of.
_BRATISLAVA = (48.15, 17.11)

#: A moment within the fixture alert's onset→expiry window, so it is "active".
_DURING_ALERT = datetime(2026, 5, 16, 12, tzinfo=UTC)


async def _setup_entry(
    hass: HomeAssistant,
    load: Callable[[str], bytes],
    *,
    data: dict,
    options: dict | None = None,
) -> tuple[MockConfigEntry, _FakeClient]:
    """Set up an entry with the fake client and return both."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=str(data[CONF_IND_KLI]),
        title=data.get(CONF_NAME, "SHMÚ"),
        data=data,
        options=options or {},
    )
    entry.add_to_hass(hass)
    client = _FakeClient(load)
    with patch("custom_components.shmu.ShmuClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, client


async def test_device_name_from_config(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    await _setup_entry(hass, load, data={CONF_IND_KLI: 11858, CONF_NAME: "Cottage"})
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "11858")})
    assert device is not None
    assert device.name == "Cottage"


async def test_device_name_falls_back_to_station(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    # A legacy entry created before the Name field existed has no CONF_NAME.
    await _setup_entry(hass, load, data={CONF_IND_KLI: 11858})
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "11858")})
    assert device is not None
    assert device.name == "Hurbanovo"


async def test_location_defaults_to_station(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    entry, client = await _setup_entry(hass, load, data={CONF_IND_KLI: 11858})
    station = get_station(11858)
    coordinator = entry.runtime_data
    assert (coordinator.location_latitude, coordinator.location_longitude) == (
        station.latitude,
        station.longitude,
    )
    # Forecast & radar are fetched at the station point.
    assert client.forecast_coords == (station.latitude, station.longitude)
    assert client.radar_coords == (station.latitude, station.longitude)


async def test_location_mode_home(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    hass.config.latitude = 49.05
    hass.config.longitude = 18.92
    entry, client = await _setup_entry(
        hass,
        load,
        data={CONF_IND_KLI: 11858},
        options={CONF_LOCATION_MODE: LOCATION_MODE_HASS},
    )
    coordinator = entry.runtime_data
    assert (coordinator.location_latitude, coordinator.location_longitude) == (
        49.05,
        18.92,
    )
    assert client.forecast_coords == (49.05, 18.92)


async def test_location_mode_custom(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    entry, client = await _setup_entry(
        hass,
        load,
        data={CONF_IND_KLI: 11858},
        options={
            CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM,
            CONF_LOCATION: {
                CONF_LATITUDE: _BRATISLAVA[0],
                CONF_LONGITUDE: _BRATISLAVA[1],
            },
        },
    )
    coordinator = entry.runtime_data
    assert (
        coordinator.location_latitude,
        coordinator.location_longitude,
    ) == _BRATISLAVA
    assert client.forecast_coords == _BRATISLAVA


async def test_custom_location_malformed_falls_back_to_station(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    # Custom mode but no coordinates stored — must not crash; use the station.
    entry, _ = await _setup_entry(
        hass,
        load,
        data={CONF_IND_KLI: 11858},
        options={CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM},
    )
    station = get_station(11858)
    coordinator = entry.runtime_data
    assert (coordinator.location_latitude, coordinator.location_longitude) == (
        station.latitude,
        station.longitude,
    )


async def test_warnings_follow_measurement_location(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    # Station (Hurbanovo) is outside the Bratislava warning polygon, but the
    # custom measurement location is inside it — so the warning is relevant.
    with patch(
        "custom_components.shmu.coordinator.dt_util.utcnow", lambda: _DURING_ALERT
    ):
        await _setup_entry(
            hass,
            load,
            data={CONF_IND_KLI: 11858, CONF_NAME: "Bratislava"},
            options={
                CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM,
                CONF_LOCATION: {
                    CONF_LATITUDE: _BRATISLAVA[0],
                    CONF_LONGITUDE: _BRATISLAVA[1],
                },
            },
        )
        assert hass.states.get("binary_sensor.bratislava_weather_warning").state == "on"
        assert hass.states.get("sensor.bratislava_warning_level").state != "none"


async def test_options_update_reloads_and_reapplies_location(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="11858",
        title="Home",
        data={CONF_IND_KLI: 11858, CONF_NAME: "Home"},
        options={CONF_LOCATION_MODE: LOCATION_MODE_STATION},
    )
    entry.add_to_hass(hass)
    client = _FakeClient(load)
    with (
        patch("custom_components.shmu.ShmuClient", return_value=client),
        patch(
            "custom_components.shmu.coordinator.dt_util.utcnow",
            lambda: _DURING_ALERT,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        station = get_station(11858)
        assert client.forecast_coords == (station.latitude, station.longitude)
        # Station is outside the alert polygon, so no warning yet.
        assert hass.states.get("binary_sensor.home_weather_warning").state == "off"

        # Move the measurement location into the Bratislava polygon. The update
        # listener reloads the entry, rebuilding the coordinator with a fresh
        # (empty) cache so the new location actually takes effect.
        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM,
                CONF_LOCATION: {
                    CONF_LATITUDE: _BRATISLAVA[0],
                    CONF_LONGITUDE: _BRATISLAVA[1],
                },
            },
        )
        await hass.async_block_till_done()

        assert client.forecast_coords == _BRATISLAVA
        assert hass.states.get("binary_sensor.home_weather_warning").state == "on"


async def test_rain_gauge_sensor_reads_the_nearest_gauge(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """The gauge is chosen from the measurement location, not the station.

    Station 11858 (Hurbanovo) has no gauge of its own — the nearest is
    Kolárovo, ~19 km away — so the sensor must resolve and report it, and say
    which gauge it came from.
    """
    client = _FakeClient(load)
    with patch("custom_components.shmu.ShmuClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.hurbanovo_rain_gauge_precipitation")
    assert state.state == "0.4"  # newest minute for gauge 17720
    assert state.attributes["gauge_ind_zra"] == 17720
    assert state.attributes["gauge_name"] == "Kolárovo"
    assert state.attributes["gauge_distance_km"] == pytest.approx(19.4, abs=0.5)

    # The station's own precipitation sensor is a different network and is
    # deliberately left reading the station.
    assert hass.states.get("sensor.hurbanovo_precipitation").state == "0.2"


async def test_rain_gauge_follows_the_measurement_location(
    hass: HomeAssistant, load: Callable[[str], bytes]
) -> None:
    """A custom measurement point picks that point's gauge, not the station's."""
    entry, _ = await _setup_entry(
        hass,
        load,
        data={CONF_IND_KLI: 11858},
        options={
            CONF_LOCATION_MODE: LOCATION_MODE_CUSTOM,
            CONF_LOCATION: {
                CONF_LATITUDE: _BRATISLAVA[0],
                CONF_LONGITUDE: _BRATISLAVA[1],
            },
        },
    )

    assert entry.runtime_data.gauge.ind_zra == 17140
    state = hass.states.get("sensor.hurbanovo_rain_gauge_precipitation")
    assert state.state == "1.2"
    assert state.attributes["gauge_name"] == "Bratislava - Koliba"


async def test_rain_gauge_is_independent_of_the_station(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """The two networks are disjoint; one dropping out must not blank the other."""
    client = _FakeClient(load)
    with patch("custom_components.shmu.ShmuClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # The station drops out; the gauge keeps reporting.
        client.drop_station = 11858
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        assert (
            hass.states.get("sensor.hurbanovo_rain_gauge_precipitation").state == "0.4"
        )


async def test_rain_gauge_survives_a_one_cycle_dropout(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """A gauge absent from one snapshot keeps serving its last reading."""
    client = _FakeClient(load)
    with patch("custom_components.shmu.ShmuClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        client.drop_gauge = 17720
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        assert (
            hass.states.get("sensor.hurbanovo_rain_gauge_precipitation").state == "0.4"
        )


async def test_rain_gauge_goes_unavailable_during_a_feed_outage(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """A failing gauge feed must eventually surface, not freeze a reading.

    The gauge feed is *supplementary*: a failed fetch keeps the previous
    snapshot and the coordinator cycle still succeeds. So the reading's
    acquisition time may only be refreshed by a genuine fetch — refreshing it
    from the kept-previous snapshot would hold the sensor at its last value
    for ever, and it would never go unavailable.
    """
    client = _FakeClient(load)
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)

    def _now() -> datetime:
        return now

    with (
        patch("custom_components.shmu.coordinator.dt_util.utcnow", _now),
        patch("custom_components.shmu.ShmuClient", return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert (
            hass.states.get("sensor.hurbanovo_rain_gauge_precipitation").state == "0.4"
        )

        # Only the gauge feed fails; observations keep succeeding, so the
        # coordinator cycle stays successful throughout.
        client.fail_gauges_with = ShmuConnectionError("gauge feed down")
        now += timedelta(minutes=10)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        assert entry.runtime_data.last_update_success is True
        # Within the window the last reading is still served.
        assert (
            hass.states.get("sensor.hurbanovo_rain_gauge_precipitation").state == "0.4"
        )
        # ...while the station is unaffected.
        assert hass.states.get("sensor.hurbanovo_temperature").state == "12.1"

        now += OBSERVATION_STALE_AFTER + timedelta(minutes=1)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        assert (
            hass.states.get("sensor.hurbanovo_rain_gauge_precipitation").state
            == "unavailable"
        )
        # The station's own entities are untouched by the gauge outage.
        assert hass.states.get("sensor.hurbanovo_temperature").state == "12.1"


async def test_rain_gauge_backfill_does_not_keep_a_stale_reading_alive(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """A gauge present in every snapshot is not necessarily still reporting.

    The feed carries backfill, so an offline gauge can keep appearing with an
    unchanged, old record — verified upstream on 2026-08-11, where gauge 32100
    was absent all day and then published 73 rows at once whose newest was 29
    hours old. If mere presence counted as a fresh reading the sensor would
    renew itself for ever and never go unavailable.
    """
    client = _FakeClient(load)
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)

    def _now() -> datetime:
        return now

    with (
        patch("custom_components.shmu.coordinator.dt_util.utcnow", _now),
        patch("custom_components.shmu.ShmuClient", return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert (
            hass.states.get("sensor.hurbanovo_rain_gauge_precipitation").state == "0.4"
        )

        # Every fetch succeeds and the gauge is present every time — but its
        # reading never advances past the minute we already have.
        for _ in range(3):
            now += timedelta(minutes=12)
            await entry.runtime_data.async_refresh()
            await hass.async_block_till_done()

        assert entry.runtime_data.last_update_success is True
        assert (
            hass.states.get("sensor.hurbanovo_rain_gauge_precipitation").state
            == "unavailable"
        )


async def test_rain_gauge_stays_available_while_its_readings_advance(
    hass: HomeAssistant, entry: MockConfigEntry, load: Callable[[str], bytes]
) -> None:
    """The converse: a genuinely reporting gauge never goes unavailable."""
    client = _FakeClient(load)
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)

    def _now() -> datetime:
        return now

    with (
        patch("custom_components.shmu.coordinator.dt_util.utcnow", _now),
        patch("custom_components.shmu.ShmuClient", return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Well past the staleness window, but each poll brings a newer minute.
        for step in range(1, 4):
            now += timedelta(minutes=12)
            client.gauge_minutes_advanced = 12 * step
            await entry.runtime_data.async_refresh()
            await hass.async_block_till_done()

        assert (
            hass.states.get("sensor.hurbanovo_rain_gauge_precipitation").state == "0.4"
        )
