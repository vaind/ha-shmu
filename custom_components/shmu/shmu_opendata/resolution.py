"""Cross-source current-condition resolution (the priority ladder).

No single SHMÚ source yields a trustworthy Home Assistant ``condition`` on its
own: the open-data feed has **no cloud cover** and only sparse present weather
(``conditions.py``), the scraped website cloud column is **populated for only a
minority of stations at any moment** (``website.py``), and the ALADIN model
(``forecast.py``) is a forecast rather than an observation. Each is strong for
some states and silent or weak for others, so they must be *layered*.

This module layers them with an explicit priority ladder — each source emits
zero or more candidate conditions tagged with a priority, and the highest
priority wins:

==== ============================= ===============================
Pri  Source / trigger              Home Assistant condition
==== ============================= ===============================
 90  website ``Počasie`` severe    lightning-rainy / hail / pouring
 88  ``stav_poc`` severe           lightning-rainy / hail / pouring
 80  website ``Počasie`` active    rainy / snowy / snowy-rainy / fog
 78  ``stav_poc`` active           rainy / snowy / snowy-rainy / fog
 70  ``stav_poc`` squalls          windy
 60  website ``Oblačnosť``         partlycloudy / cloudy
 50  ALADIN now (active)           rainy / pouring / snowy* / lightning-rainy
 45  website ``Oblačnosť`` clear   sunny
 40  ALADIN now (sky)              partlycloudy / cloudy
 30  ``stav_poc`` distant storm    lightning
 20  ALADIN now (clear)            sunny
 --  nothing matched              (unknown)
==== ============================= ===============================

The design choices encoded here:

* **Observations outrank the model.** The model only fills gaps the
  observations leave (most notably the sky state when the website cloud cell
  is blank — the cause of the intermittent "unknown" this ladder fixes).
* **Severity is never hidden.** Observed thunderstorm/hail/heavy rain sits at
  the top; ``stav_poc`` precipitation (78) also outranks a website *cloud*
  reading (60) so a station whose ``Počasie`` cell is blank but whose code
  says "raining now" reports ``rainy``, not ``cloudy``.
* **"Clear sky" is the weakest claim.** Asserting a clear sky is the most
  easily-wrong reading, so both clear candidates rank low — below a
  *distant-storm* hint (30), which therefore surfaces only when nothing but a
  modeled clear sky would otherwise apply.
* **Within a shared band the curated website text beats the automatic code**
  (90 > 88, 80 > 78).
* **An observation of "nothing happening" vetoes a modeled storm.** When a
  station reports a present-weather code that means no significant weather
  (``stav_poc`` 0, and dry), the model's *active* (rain/thunder) candidate is
  dropped in favour of its cloud-only *sky* state — the model alone must not
  paint a convective cell as rain/thunder over a station observing itself dry.

Pure and Home-Assistant-free (plain condition strings), so it stays
offline-testable. A clear sky is returned as ``sunny``; the day/night
``sunny`` -> ``clear-night`` shift is a UI concern handled by the weather
entity.
"""

from __future__ import annotations

from dataclasses import dataclass

from .conditions import condition_from_weather_code
from .forecast import ForecastStep, sky_from_cloud
from .website import WebCondition

#: HA condition strings, grouped by how the ladder bands them.
_SEVERE = frozenset({"lightning-rainy", "hail", "pouring", "lightning"})
_SKY_CLOUDY = frozenset({"partlycloudy", "cloudy"})
_MODEL_ACTIVE = frozenset(
    {"rainy", "pouring", "snowy", "snowy-rainy", "lightning-rainy"}
)
_CLEAR = "sunny"

#: ``stav_poc`` (WMO 4680 *wawa*) codes given a band by the code itself rather
#: than by the condition string: 12 is *distant* lightning (a last-resort hint,
#: not local weather) and 18 is squalls (wind), both of which map to condition
#: strings that would otherwise be banded as severe/active.
_WAWA_DISTANT_LIGHTNING = 12
_WAWA_SQUALLS = 18

# Priority bands (higher wins); unique per source so the winner is unambiguous.
_P_WEB_SEVERE = 90
_P_AWS_SEVERE = 88
_P_WEB_ACTIVE = 80
_P_AWS_ACTIVE = 78
_P_AWS_WINDY = 70
_P_WEB_SKY = 60
_P_MODEL_ACTIVE = 50
_P_WEB_CLEAR = 45
_P_MODEL_SKY = 40
_P_AWS_DISTANT = 30
_P_MODEL_CLEAR = 20

#: Diagnostics provenance labels for the winning source.
SOURCE_WEBSITE = "website"
SOURCE_STAV_POC = "stav_poc"
SOURCE_ALADIN = "aladin"
SOURCE_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class _Candidate:
    priority: int
    condition: str
    source: str


def _website_candidates(web: WebCondition | None) -> list[_Candidate]:
    """Up to two candidates: the present-weather reading and the sky cover."""
    if web is None:
        return []
    out: list[_Candidate] = []
    weather = web.weather_condition
    if weather is not None:
        band = _P_WEB_SEVERE if weather in _SEVERE else _P_WEB_ACTIVE
        out.append(_Candidate(band, weather, SOURCE_WEBSITE))
    cloud = web.cloud_condition
    if cloud is not None:
        band = _P_WEB_CLEAR if cloud == _CLEAR else _P_WEB_SKY
        out.append(_Candidate(band, cloud, SOURCE_WEBSITE))
    return out


def _stav_poc_candidate(
    weather_code: int | None, precipitation: float | None
) -> _Candidate | None:
    """The single ``stav_poc`` reading, banded by its *wawa* code."""
    condition = condition_from_weather_code(weather_code, precipitation=precipitation)
    if condition is None:
        return None
    if weather_code == _WAWA_DISTANT_LIGHTNING:
        return _Candidate(_P_AWS_DISTANT, condition, SOURCE_STAV_POC)
    if weather_code == _WAWA_SQUALLS:
        return _Candidate(_P_AWS_WINDY, condition, SOURCE_STAV_POC)
    band = _P_AWS_SEVERE if condition in _SEVERE else _P_AWS_ACTIVE
    return _Candidate(band, condition, SOURCE_STAV_POC)


def _model_candidate(
    step: ForecastStep | None, *, suppress_active: bool
) -> _Candidate | None:
    """The ALADIN current-hour reading, banded as active / sky / clear.

    ``suppress_active`` is set when a station *observed* no significant weather
    (see :func:`resolve_condition`): the model's precipitation/storm claim is
    then dropped in favour of its cloud-only sky state, so a forecast
    convective cell cannot show as rain/thunder over a station that reports
    itself dry. Cloud cover is still the model's, so the sky state survives.
    """
    if step is None or step.condition is None:
        return None
    condition = step.condition
    if condition in _MODEL_ACTIVE:
        if not suppress_active:
            return _Candidate(_P_MODEL_ACTIVE, condition, SOURCE_ALADIN)
        # Vetoed by the observation — fall back to the model's sky state.
        sky = sky_from_cloud(step.cloud_coverage)
        if sky is None:
            return None
        condition = sky
    if condition in _SKY_CLOUDY:
        return _Candidate(_P_MODEL_SKY, condition, SOURCE_ALADIN)
    if condition == _CLEAR:
        return _Candidate(_P_MODEL_CLEAR, condition, SOURCE_ALADIN)
    # ALADIN never emits fog/hail/windy/distant-lightning; be explicit.
    return None


def resolve_condition(
    *,
    web: WebCondition | None,
    weather_code: int | None,
    precipitation: float | None,
    forecast_step: ForecastStep | None,
) -> tuple[str | None, str]:
    """Resolve an HA condition and its source from all available signals.

    ``forecast_step`` is the ALADIN step nearest the current hour (the caller
    selects it; this module does not look at the clock). Returns
    ``(condition, source)`` where ``source`` is one of the ``SOURCE_*``
    labels; ``(None, "unknown")`` when no source produced anything.
    """
    candidates = _website_candidates(web)
    aws = _stav_poc_candidate(weather_code, precipitation)
    if aws is not None:
        candidates.append(aws)
    # A station that reported a present-weather code yielding no active weather
    # (``stav_poc`` 0 "no significant weather", and dry) is affirmatively quiet
    # now — trust that over a model forecast of precipitation/storm.
    station_quiet = weather_code is not None and aws is None
    model = _model_candidate(forecast_step, suppress_active=station_quiet)
    if model is not None:
        candidates.append(model)
    if not candidates:
        return None, SOURCE_UNKNOWN
    best = max(candidates, key=lambda c: c.priority)
    return best.condition, best.source
