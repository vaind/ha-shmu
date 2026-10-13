"""Tests for the SHMÚ website condition scraper."""

from __future__ import annotations

import logging

import pytest

from custom_components.shmu.shmu_opendata.exceptions import ShmuDataError
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


def test_changed_layout_raises_instead_of_returning_nothing(caplog) -> None:
    """A real-sized page with no recognisable rows means the markup changed.

    Raising lets the coordinator keep the last good conditions and report the
    outage itself; an empty success would wipe them, and logging from here
    would repeat on every poll for as long as the layout stayed changed.
    """
    html = "<html><body><table><tbody>" + "<tr><td>x</td></tr>" * 100
    html += "</tbody></table></body></html>"

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(ShmuDataError, match="zero stations"),
    ):
        parse_current_conditions(html)
    assert not caplog.records


def test_trivially_small_page_is_not_a_layout_change() -> None:
    assert parse_current_conditions("<tbody></tbody>") == {}
