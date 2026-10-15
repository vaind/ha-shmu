"""Tests for the cross-source condition priority ladder."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.shmu.shmu_opendata.forecast import ForecastStep
from custom_components.shmu.shmu_opendata.radar import LocalEcho
from custom_components.shmu.shmu_opendata.resolution import (
    explain_condition,
    resolve_condition,
)
from custom_components.shmu.shmu_opendata.website import WebCondition


def _web(*, weather: str | None = None, cloud: str | None = None) -> WebCondition:
    """A website reading carrying only the mapped conditions the ladder reads."""
    return WebCondition(
        ind_kli=11813,
        cloud_text="",
        weather_text="",
        weather_condition=weather,
        cloud_condition=cloud,
        condition=weather or cloud,
    )


def _step(condition: str | None, *, cloud: float | None = None) -> ForecastStep:
    """An ALADIN step carrying only the fields the ladder reads."""
    return ForecastStep(
        time=datetime(2026, 6, 5, 8, 0, tzinfo=UTC),
        temperature=None,
        precipitation=None,
        wind_speed=None,
        wind_gust=None,
        wind_bearing=None,
        pressure=None,
        cloud_coverage=cloud,
        cape=None,
        temperature_850hpa=None,
        freezing_level=None,
        condition=condition,
        span_hours=1.0,
        run=datetime(2026, 6, 5, 0, 0, tzinfo=UTC),
    )


def test_unknown_when_no_source_has_anything() -> None:
    assert resolve_condition(
        web=None, weather_code=None, precipitation=None, forecast_step=None
    ) == (None, "unknown")


def test_koliba_regression_aladin_fills_blank_sky() -> None:
    """The reported bug: blank website cloud + wawa 0 used to be "unknown".

    With the model's current-hour cloud cover as a tier, an overcast-but-dry
    moment now resolves to ``cloudy`` instead of flipping to unknown.
    """
    condition, source = resolve_condition(
        web=None,
        weather_code=0,  # "no significant weather" — carries no sky state
        precipitation=0.0,
        forecast_step=_step("cloudy"),
    )
    assert (condition, source) == ("cloudy", "aladin")


def test_observed_present_weather_outranks_everything_else() -> None:
    condition, source = resolve_condition(
        web=_web(weather="rainy", cloud="cloudy"),
        weather_code=0,
        precipitation=0.0,
        forecast_step=_step("sunny"),
    )
    assert (condition, source) == ("rainy", "website")


def test_within_severe_band_website_text_beats_automatic_code() -> None:
    condition, source = resolve_condition(
        web=_web(weather="lightning-rainy"),
        weather_code=95,  # thunderstorm -> lightning-rainy (also severe)
        precipitation=1.0,
        forecast_step=None,
    )
    assert (condition, source) == ("lightning-rainy", "website")


def test_stav_poc_precipitation_beats_website_cloud() -> None:
    """The latent 'cloudy while actually raining' case the ladder also fixes."""
    condition, source = resolve_condition(
        web=_web(cloud="cloudy"),  # only a sky reading, no present weather
        weather_code=61,  # rain
        precipitation=0.2,
        forecast_step=None,
    )
    assert (condition, source) == ("rainy", "stav_poc")


def test_squalls_windy_beats_sky_but_loses_to_precip() -> None:
    # Squalls (wawa 18) outrank an observed sky state...
    assert resolve_condition(
        web=_web(cloud="cloudy"),
        weather_code=18,
        precipitation=0.0,
        forecast_step=None,
    ) == ("windy", "stav_poc")
    # ...but observed precipitation still wins.
    assert resolve_condition(
        web=_web(weather="rainy"),
        weather_code=18,
        precipitation=0.0,
        forecast_step=None,
    ) == ("rainy", "website")


def test_observed_clear_outranks_model_cloud_and_distant_lightning() -> None:
    """A real 'jasno' observation beats a model guess and a faraway storm."""
    condition, source = resolve_condition(
        web=_web(cloud="sunny"),  # observed clear sky
        weather_code=12,  # distant lightning
        precipitation=0.0,
        forecast_step=_step("cloudy"),
    )
    assert (condition, source) == ("sunny", "website")


def test_distant_lightning_outranks_model_clear() -> None:
    """The firm requirement: wawa 12 beats a *modeled* clear sky."""
    condition, source = resolve_condition(
        web=None,
        weather_code=12,
        precipitation=0.0,
        forecast_step=_step("sunny"),
    )
    assert (condition, source) == ("lightning", "stav_poc")


def test_model_precipitation_outranks_observed_clear() -> None:
    """Modeled rain overrides an observed clear sky when no obs contradicts it.

    ``weather_code=None`` means the station does not report present weather, so
    nothing vetoes the model.
    """
    condition, source = resolve_condition(
        web=_web(cloud="sunny"),
        weather_code=None,
        precipitation=0.0,
        forecast_step=_step("rainy"),
    )
    assert (condition, source) == ("rainy", "aladin")


def test_stav_poc_zero_vetoes_model_storm_keeping_model_sky() -> None:
    """The reported false 'lightning-rainy': station says quiet, model says storm.

    A station reporting ``stav_poc=0`` (no significant weather) and dry must not
    show the model's forecast thunderstorm; it falls back to the model's
    cloud-only sky state (here 90% cloud -> cloudy).
    """
    condition, source = resolve_condition(
        web=None,
        weather_code=0,
        precipitation=0.0,
        forecast_step=_step("lightning-rainy", cloud=90.0),
    )
    assert (condition, source) == ("cloudy", "aladin")


def test_veto_falls_through_to_partlycloudy_on_moderate_cloud() -> None:
    condition, source = resolve_condition(
        web=None,
        weather_code=0,
        precipitation=0.0,
        forecast_step=_step("rainy", cloud=45.0),
    )
    assert (condition, source) == ("partlycloudy", "aladin")


def test_no_veto_without_a_present_weather_observation() -> None:
    """A missing ``stav_poc`` is not an observation of 'quiet' — no veto."""
    condition, source = resolve_condition(
        web=None,
        weather_code=None,
        precipitation=None,
        forecast_step=_step("lightning-rainy", cloud=90.0),
    )
    assert (condition, source) == ("lightning-rainy", "aladin")


def test_observed_rain_is_never_vetoed() -> None:
    """The veto only suppresses the *model*; a real observed code still wins."""
    condition, source = resolve_condition(
        web=None,
        weather_code=61,  # rain observed -> active, not quiet
        precipitation=0.2,
        forecast_step=_step("lightning-rainy", cloud=90.0),
    )
    assert (condition, source) == ("rainy", "stav_poc")


def test_model_clear_is_the_last_resort_above_unknown() -> None:
    condition, source = resolve_condition(
        web=None, weather_code=0, precipitation=0.0, forecast_step=_step("sunny")
    )
    assert (condition, source) == ("sunny", "aladin")


def test_explain_lists_all_candidates_winner_first() -> None:
    """Diagnostics view: every contributing source, highest priority first."""
    res = explain_condition(
        web=_web(cloud="cloudy"),  # website cloud -> 60
        weather_code=61,  # stav_poc rain -> 78
        precipitation=0.2,
        forecast_step=_step("rainy"),  # model precip -> 50
    )
    assert (res.condition, res.source) == ("rainy", "stav_poc")
    assert [(c.source, c.priority) for c in res.candidates] == [
        ("stav_poc", 78),
        ("website", 60),
        ("aladin", 50),
    ]
    # Winner is first; tiers are human-readable.
    assert res.candidates[0].tier == "stav_poc"
    assert res.suppressed_model_condition is None
    assert res.ignored_weather_code is None


def test_explain_reports_the_veto_and_suppressed_condition() -> None:
    res = explain_condition(
        web=None,
        weather_code=0,  # station quiet
        precipitation=0.0,
        forecast_step=_step("lightning-rainy", cloud=90.0),
    )
    assert (res.condition, res.source) == ("cloudy", "aladin")
    assert res.suppressed_model_condition == "lightning-rainy"
    # The surviving candidate is the model's cloud-only sky state.
    assert [(c.condition, c.tier) for c in res.candidates] == [
        ("cloudy", "model cloud")
    ]


def test_explain_unknown_has_no_candidates() -> None:
    res = explain_condition(
        web=None, weather_code=None, precipitation=None, forecast_step=None
    )
    assert (res.condition, res.source) == (None, "unknown")
    assert res.candidates == ()
    assert res.suppressed_model_condition is None


_WET = LocalEcho(max_dbz=32.5)
_DRY = LocalEcho(max_dbz=None)


def test_radar_echo_fills_precipitation_a_station_cannot_report() -> None:
    """No present-weather code, and a dry model: the radar says it rains."""
    res = explain_condition(
        web=_web(cloud="cloudy"),  # website cloud -> 60, below the radar
        weather_code=None,
        precipitation=None,
        forecast_step=_step("cloudy", cloud=90.0),
        radar_echo=_WET,
        temperature=9.0,
    )
    assert (res.condition, res.source) == ("rainy", "radar")
    assert res.candidates[0].priority == 75
    assert res.candidates[0].tier == "radar echo"


def test_a_weak_echo_is_not_precipitation_but_vetoes_the_model() -> None:
    """Below 20 dBZ counts as dry, and a covered dry pixel overrules the model."""
    res = explain_condition(
        web=None,
        weather_code=None,
        precipitation=None,
        forecast_step=_step("rainy", cloud=80.0),
        radar_echo=LocalEcho(max_dbz=19.5),
    )
    assert (res.condition, res.source) == ("cloudy", "aladin")
    assert res.suppressed_model_condition == "rainy"
    assert res.suppressed_by == "radar"


def test_radar_dry_vetoes_a_modelled_storm() -> None:
    res = explain_condition(
        web=None,
        weather_code=None,
        precipitation=None,
        forecast_step=_step("lightning-rainy", cloud=95.0),
        radar_echo=_DRY,
    )
    assert (res.condition, res.source) == ("cloudy", "aladin")
    assert res.suppressed_by == "radar"


def test_no_radar_coverage_leaves_the_model_alone() -> None:
    """``None`` means the radar says nothing: neither rain nor a veto."""
    condition, source = resolve_condition(
        web=None,
        weather_code=None,
        precipitation=None,
        forecast_step=_step("rainy"),
        radar_echo=None,
    )
    assert (condition, source) == ("rainy", "aladin")


def test_station_present_weather_outranks_the_radar() -> None:
    """The station observes the type at its own point; the radar only an echo."""
    condition, source = resolve_condition(
        web=None,
        weather_code=71,  # snow
        precipitation=0.1,
        forecast_step=None,
        radar_echo=_WET,
        temperature=9.0,  # would type the echo as rain
    )
    assert (condition, source) == ("snowy", "stav_poc")


def test_a_quiet_station_overrules_an_echo_overhead() -> None:
    res = explain_condition(
        web=None,
        weather_code=0,
        precipitation=0.0,
        forecast_step=_step("cloudy", cloud=90.0),
        radar_echo=_WET,
    )
    assert (res.condition, res.source) == ("cloudy", "aladin")
    assert all(c.source != "radar" for c in res.candidates)


def test_station_veto_is_reported_as_the_station_s() -> None:
    res = explain_condition(
        web=None,
        weather_code=0,
        precipitation=0.0,
        forecast_step=_step("rainy", cloud=90.0),
        radar_echo=_DRY,
    )
    assert res.suppressed_by == "stav_poc"


@pytest.mark.parametrize(
    ("temperature", "expected"),
    [(-3.0, "snowy"), (0.5, "snowy"), (1.5, "snowy-rainy"), (2.5, "rainy")],
)
def test_an_echo_is_typed_by_the_station_temperature(temperature, expected) -> None:
    condition, _ = resolve_condition(
        web=None,
        weather_code=None,
        precipitation=None,
        forecast_step=None,
        radar_echo=_WET,
        temperature=temperature,
    )
    assert condition == expected


def test_an_echo_falls_back_to_the_model_temperature() -> None:
    step = replace(_step("cloudy", cloud=90.0), temperature=-2.0)
    condition, _ = resolve_condition(
        web=None,
        weather_code=None,
        precipitation=None,
        forecast_step=step,
        radar_echo=_WET,
    )
    assert condition == "snowy"


def test_a_strong_echo_is_never_heavy_rain_or_thunder() -> None:
    """The radar alone does not support severity (no thunder in the data)."""
    condition, _ = resolve_condition(
        web=None,
        weather_code=None,
        precipitation=None,
        forecast_step=_step("lightning-rainy"),
        radar_echo=LocalEcho(max_dbz=55.0),
        temperature=20.0,
    )
    assert condition == "rainy"


def test_untrusted_precipitation_code_leaves_the_condition_to_the_model() -> None:
    """An over-reporting sensor's drizzle must not paint the station rainy.

    Five stations report codes 40/5x in 29-48 % of hours while the radar shows
    an echo in a few (AGENTS.md); without this, ``stav_poc`` (78) outranks the
    model and the station reads ``rainy`` most of the time.
    """
    res = explain_condition(
        web=None,
        weather_code=40,
        precipitation=0.0,
        forecast_step=_step("cloudy", cloud=90.0),
        trust_precipitation_codes=False,
    )
    assert (res.condition, res.source) == ("cloudy", "aladin")
    assert res.ignored_weather_code == 40
    assert [c.source for c in res.candidates] == ["aladin"]


def test_ignored_precipitation_code_is_not_a_quiet_observation() -> None:
    """Dropping the code must not turn it into a veto of the model's rain."""
    res = explain_condition(
        web=None,
        weather_code=52,
        precipitation=0.0,
        forecast_step=_step("rainy", cloud=90.0),
        trust_precipitation_codes=False,
    )
    assert (res.condition, res.source) == ("rainy", "aladin")
    assert res.suppressed_model_condition is None


def test_untrusted_sensor_still_vetoes_the_model_when_quiet() -> None:
    """Only the precipitation half is untrusted: its code 0 stays a veto."""
    res = explain_condition(
        web=None,
        weather_code=0,
        precipitation=0.0,
        forecast_step=_step("lightning-rainy", cloud=90.0),
        trust_precipitation_codes=False,
    )
    assert (res.condition, res.source) == ("cloudy", "aladin")
    assert res.suppressed_model_condition == "lightning-rainy"
    assert res.ignored_weather_code is None


def test_untrusted_sensor_keeps_its_gauge_and_non_precipitation_codes() -> None:
    # The station's own rain gauge is a separate instrument, still believed.
    assert resolve_condition(
        web=None,
        weather_code=51,
        precipitation=0.1,
        forecast_step=None,
        trust_precipitation_codes=False,
    ) == ("rainy", "stav_poc")
    # Fog is not a precipitation code, so it is not dropped.
    assert resolve_condition(
        web=None,
        weather_code=30,
        precipitation=0.0,
        forecast_step=_step("cloudy", cloud=90.0),
        trust_precipitation_codes=False,
    ) == ("fog", "stav_poc")
