"""Tests for the SHMÚ website condition scraper."""

from __future__ import annotations

from custom_components.shmu.shmu_opendata.website import parse_current_conditions


def test_parses_rows_and_maps_conditions(fixture) -> None:
    conditions = parse_current_conditions(fixture("apocasie.html").decode("utf-8"))

    assert set(conditions) == {11858, 11816, 11958}

    # Overcast + active rain -> rainy.
    assert conditions[11858].cloud_text == "Zamračené"
    assert conditions[11858].weather_text == "Dážď"
    assert conditions[11858].condition == "rainy"

    # "Po daždi" (after rain) is not active -> fall back to cloud cover.
    assert conditions[11816].weather_text == "Po daždi"
    assert conditions[11816].condition == "cloudy"

    # Empty cloud and weather -> unknown.
    assert conditions[11958].condition is None


def test_post_storm_is_not_treated_as_active_storm() -> None:
    # "Po búrke" (after a storm) must not map to a thunderstorm; with overcast
    # cloud it falls back to cloudy.
    html = (
        "<tbody><tr>"
        '<td headers="h_oblacnost">Zamračené</td>'
        '<td headers="h_pocasie">Po búrke</td>'
        '<td><a href="?ii=11816"></a></td>'
        "</tr></tbody>"
    )
    result = parse_current_conditions(html)
    assert result[11816].condition == "cloudy"
