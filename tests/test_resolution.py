"""Tests for the cross-source condition priority ladder."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.shmu.shmu_opendata.forecast import ForecastStep
from custom_components.shmu.shmu_opendata.resolution import resolve_condition
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
        condition=condition,
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
