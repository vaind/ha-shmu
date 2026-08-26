"""SHMÚ ALADIN forecast: fixed grid, point extraction, field mapping.

The :mod:`grib2` module decodes raw fields; this module knows what SHMÚ's
``aladin/sk/4.5km`` product *is*. All of the following were verified against
a live file in the Phase-2a spike (issue #2) and are **constant** — SHMÚ has
no API and the operational grid does not change between runs, so hard-coding
it (like the station catalogue) is correct and avoids interpreting Section 3
geometry at runtime:

* Lambert conformal conic, spherical earth R = 6 371 229 m, one standard
  parallel (tangent cone) φ₀ = 46.2447°, central meridian 17.0°E;
* 94 x 48 points, 4.5 km spacing, first grid point (the SW corner, scan mode
  ``0x40``) at 47.74175°N, 16.849607°E;
* a bitmap masks the rectangle to the ~2479-point Slovakia sub-domain, so the
  nearest grid point to a location may be masked — we spiral out to the
  nearest point that actually carries values.

Condition strings are Home Assistant's vocabulary but are plain ``str`` — this
module imports no Home Assistant code, so the library stays swappable and
offline-testable.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from .exceptions import ShmuDataError
from .grib2 import Grib2Field, iter_fields

# --- Fixed ALADIN/SHMÚ 4.5 km grid (Phase-2a spike, issue #2) ----------------

_EARTH_RADIUS_M = 6_371_229.0
_PHI0 = math.radians(46.2447)  # standard parallel == LaD == Latin1 == Latin2
_LOV = math.radians(17.0)  # central meridian / orientation longitude
_LA1 = 47.74175  # first grid point latitude (deg)
_LO1 = 16.849607  # first grid point longitude (deg)
_DX = 4500.0  # grid spacing (m)
_DY = 4500.0
_NX = 94
_NY = 48

#: How a field is addressed inside one hour-file: *what* it is
#: ``(discipline, category, number, level type)`` plus *where* it sits (the
#: level value, in that level type's units — see :class:`grib2.Grib2Field`).
#: The level is part of the key because ALADIN publishes the same quantity on
#: five pressure levels; keyed by ``param`` alone they collapse onto one entry.
#: Matching is by float equality, which holds because SHMÚ's levels decode to
#: exact integers-as-floats. A level that stopped decoding to its constant
#: would make that field go *silently* missing — see AGENTS.md for the
#: re-verification trigger.
type _FieldKey = tuple[int, int, int, int, float | None]

# --- Surface fields we need ------------------------------------------------
# Verified present in every hourly file (levels re-verified on live 2026-08-26
# bytes). Wind/precip gusts are PDT 4.8 (time-processed), which carries the
# level at the same octets, so the key form is the same.
_T2M: _FieldKey = (0, 0, 0, 103, 2.0)  # 2 m temperature (K)
_U10: _FieldKey = (0, 2, 2, 103, 10.0)  # 10 m u-wind (m/s)
_V10: _FieldKey = (0, 2, 3, 103, 10.0)  # 10 m v-wind (m/s)
_GUST_U: _FieldKey = (0, 2, 23, 103, 10.0)  # 10 m u-wind gust (m/s)
_GUST_V: _FieldKey = (0, 2, 24, 103, 10.0)  # 10 m v-wind gust (m/s)
_TP: _FieldKey = (0, 1, 193, 1, 0.0)  # total precip, accumulated (kg/m²≡mm)
_TCC: _FieldKey = (192, 128, 164, 1, 0.0)  # total cloud cover (fraction 0..1)
_PRMSL: _FieldKey = (0, 3, 1, 101, 0.0)  # pressure reduced to MSL (Pa)
_CAPE: _FieldKey = (0, 7, 6, 1, 0.0)  # convective available potential (J/kg)
#: Model terrain height (gpm). Published **only in a run's hour-000 file**, and
#: constant — decoded once per run and reused for every step.
_OROGRAPHY: _FieldKey = (0, 3, 5, 1, 0.0)

# --- Upper-air fields (issue #44, verified live 2026-08-26) ----------------
# The same hour-files carry temperature, humidity, wind and geopotential on
# five pressure levels; we read only temperature and geopotential, which is
# what a vertical temperature profile needs. Humidity and upper winds are
# decoded too (``iter_fields`` decodes every message) but deliberately not
# surfaced — see AGENTS.md.
_T_PRESSURE = (0, 0, 0, 100)  # temperature on a pressure level (K)
_Z_PRESSURE = (0, 3, 4, 100)  # geopotential on a pressure level (m²/s²)
#: The published levels, bottom-up (Pa).
_PRESSURE_LEVELS_PA: tuple[float, ...] = (92500.0, 85000.0, 70000.0, 50000.0, 25000.0)
#: The air-mass level: ~1450 m, i.e. above the boundary layer but still inside
#: the weather, which is why 850 hPa temperature is the standard air-mass chart.
_AIR_MASS_LEVEL_PA = 85000.0
#: WMO standard gravity: geopotential (m²/s²) / g₀ = geopotential metres, which
#: differ from geometric metres by <0.3 % below 10 km — immaterial here.
_G0 = 9.80665
#: Height (m) of the 2 m screen above the model terrain, the profile's anchor.
_SCREEN_HEIGHT = 2.0

# Home Assistant weather condition strings (plain values; no HA import).
SUNNY = "sunny"
PARTLYCLOUDY = "partlycloudy"
CLOUDY = "cloudy"
RAINY = "rainy"
POURING = "pouring"
SNOWY = "snowy"
SNOWY_RAINY = "snowy-rainy"
LIGHTNING_RAINY = "lightning-rainy"

#: Rain *rate* (mm/h) heavy enough to call "pouring". Classification is by
#: intensity, not by a step's raw accumulation: ALADIN steps are hourly only to
#: +48 h and 3-hourly beyond (see ``const.FORECAST_HOURS``), so a 3-hourly step
#: bundles three hours of rain — thresholding its raw total would overstate the
#: intensity three-fold (a gentle drizzle would read as "pouring").
_HEAVY_RAIN_MM_PER_H = 2.5
#: Rain rate (mm/h) at/under which a step counts as no meaningful precipitation.
_TRACE_MM_PER_H = 0.05
#: CAPE above this with precipitation implies a thunderstorm.
_THUNDER_CAPE = 200.0


@dataclass(frozen=True, slots=True)
class ForecastStep:
    """One forecast valid time at the configured location's grid point.

    Units mirror the library's observation model: temperatures °C, wind m/s,
    bearing degrees, pressure hPa, precipitation mm accumulated *within this
    step*, cloud cover %, CAPE J/kg. Any field may be ``None`` if its source
    message was absent. ``condition`` is an HA condition string (plain text).

    ``temperature_850hpa`` (°C) and ``freezing_level`` (metres **above sea
    level**) come from the upper-air fields on the same grid point. The
    freezing level is ``None`` when the profile cannot support one — see
    :func:`derive_freezing_level`.

    ``span_hours`` is the width of the accumulation window ``precipitation``
    represents — the gap to the previous step *of the same run*. It is
    retained (rather than being a local of :func:`parse_forecast`) because a
    caller may merge steps from several runs into one series, and such a
    series is only correct while every step's window equals the gap to its
    predecessor. Without the width there is no way to tell, and a mismatch
    silently double-counts or drops rain.

    ``run`` is the reference time of the model run the step came from, so a
    merged series stays traceable to its sources.
    """

    time: datetime
    temperature: float | None
    precipitation: float | None
    wind_speed: float | None
    wind_gust: float | None
    wind_bearing: float | None
    pressure: float | None
    cloud_coverage: float | None
    cape: float | None
    temperature_850hpa: float | None
    freezing_level: float | None
    condition: str | None
    span_hours: float
    run: datetime


def grid_index(latitude: float, longitude: float) -> tuple[int, int]:
    """Nearest ``(i, j)`` grid cell to a point (clamped to the grid).

    Forward Lambert conformal projection (spherical, tangent cone). The y
    origin cancels because we measure relative to the first grid point, so
    only the cone constant ``n`` and the projected radius ``rho`` are needed.
    """
    n = math.sin(_PHI0)
    f = (math.cos(_PHI0) * math.tan(math.pi / 4 + _PHI0 / 2) ** n) / n

    def project(lat_deg: float, lon_deg: float) -> tuple[float, float]:
        lat = math.radians(lat_deg)
        rho = _EARTH_RADIUS_M * f / math.tan(math.pi / 4 + lat / 2) ** n
        theta = n * (math.radians(lon_deg) - _LOV)
        return rho * math.sin(theta), -rho * math.cos(theta)

    x0, y0 = project(_LA1, _LO1)
    x, y = project(latitude, longitude)
    i = round((x - x0) / _DX)
    j = round((y - y0) / _DY)
    return (
        min(max(i, 0), _NX - 1),
        min(max(j, 0), _NY - 1),
    )


def nearest_unmasked_index(
    field: Grib2Field, latitude: float, longitude: float
) -> tuple[int, int]:
    """Grid cell nearest the point that actually carries a value.

    The Lambert-nearest cell can fall in the bitmap-masked area outside the
    Slovakia sub-domain; expand a square ring search until a point with data
    is found. The mask is identical for every field in a file, so the result
    can be reused across that file's fields. Raises if the whole grid is
    masked (a structurally broken file, not a normal "no data here").
    """
    ci, cj = grid_index(latitude, longitude)
    if field.value_at(ci, cj) is not None:
        return ci, cj
    for radius in range(1, max(_NX, _NY)):
        for i in range(max(ci - radius, 0), min(ci + radius, _NX - 1) + 1):
            for j in range(max(cj - radius, 0), min(cj + radius, _NY - 1) + 1):
                if (
                    max(abs(i - ci), abs(j - cj)) == radius
                    and field.value_at(i, j) is not None
                ):
                    return i, j
    raise ShmuDataError("GRIB2 field is entirely masked")


def sky_from_cloud(cloud_coverage: float | None) -> str | None:
    """Dry-sky condition from cloud-cover percent, or ``None`` if unknown.

    The single home of the cloud-cover thresholds, shared by the model's own
    :func:`derive_condition` and the resolution ladder (which falls back to a
    model *sky* state when a station's present-weather observation vetoes the
    model's precipitation), so the two cannot drift.
    """
    if cloud_coverage is None:
        return None
    if cloud_coverage < 20.0:
        return SUNNY
    if cloud_coverage < 70.0:
        return PARTLYCLOUDY
    return CLOUDY


def derive_freezing_level(profile: Sequence[tuple[float, float]]) -> float | None:
    """Lowest height (m) at which a temperature profile reaches 0 °C.

    ``profile`` is ``(height, temperature °C)`` ordered bottom-up and anchored
    at the surface — :func:`_vertical_profile` returns nothing else, because
    "lowest" is only meaningful when the ground is where the profile starts.
    *Lowest* follows the standard
    definition of the freezing level ("the lowest altitude at which the air
    temperature is 0 °C"); a winter valley inversion can produce several
    crossings and the one nearest the ground is the one that decides what
    reaches it.

    Returns ``None`` when the profile cannot support an answer: fewer than two
    points (a single reading is not a profile — pinning the freezing level to
    the ground from one number would claim more than the data says), or no
    crossing at all. With a real profile topped by 250 hPa, always far below
    freezing, "no crossing" only happens for degenerate input, so ``None``
    uniformly reads as *not derivable* rather than as a physical claim.

    A first point already at or below 0 °C is itself the answer: that is a
    surface frost, and the freezing level is *at the ground* by definition.
    Accuracy follows the profile's spacing: dense below
    850 hPa, where winter freezing levels sit, but the 700→500 hPa gap spans
    ~2.6 km, so a summer isotherm interpolated there can be a few hundred
    metres out.
    """
    if len(profile) < 2:
        return None
    base_height, base_temperature = profile[0]
    if base_temperature <= 0.0:
        return base_height
    for (lower_h, lower_t), (upper_h, upper_t) in pairwise(profile):
        if upper_t <= 0.0 < lower_t:
            # Temperature is ~linear in height within a layer, so interpolate
            # in height rather than in log-pressure.
            return lower_h + (upper_h - lower_h) * lower_t / (lower_t - upper_t)
    return None


def derive_condition(
    *,
    cloud_coverage: float | None,
    precipitation: float | None,
    temperature: float | None,
    cape: float | None,
    hours: float = 1.0,
) -> str | None:
    """Map model surface fields to a Home Assistant condition string.

    Cloud cover gives the *self-contained* sky state the observation feed
    lacks (the reason Phase 1 had to scrape). Returns ``None`` only when cloud
    cover is unknown and it is dry — the caller surfaces that as "unknown"
    rather than inventing a sky state (same philosophy as ``conditions.py``).

    ``precipitation`` is the accumulation *over this step*; ``hours`` is the
    step's duration, so precipitation is classified as an intensity (mm/h)
    rather than a raw total. This matters past +48 h where ALADIN steps are
    3-hourly: without normalising, a light drizzle spread over three hours
    would be mis-read as "pouring" (and a trace as "rainy"). Defaults to
    ``1.0`` so an hourly step is unchanged.
    """
    rate = None
    if precipitation is not None:
        rate = precipitation / hours if hours > 0 else precipitation
    wet = rate is not None and rate > _TRACE_MM_PER_H
    if wet:
        if cape is not None and cape >= _THUNDER_CAPE:
            return LIGHTNING_RAINY
        if temperature is not None and temperature <= 0.5:
            return SNOWY
        if temperature is not None and temperature <= 2.0:
            return SNOWY_RAINY
        assert rate is not None
        return POURING if rate >= _HEAVY_RAIN_MM_PER_H else RAINY
    return sky_from_cloud(cloud_coverage)


def _vertical_profile(
    value: Callable[[_FieldKey], float | None],
    surface_temperature: float | None,
    terrain: float | None,
) -> list[tuple[float, float]]:
    """Temperature profile ``(height m, °C)`` at one grid point, bottom-up.

    Always anchored at the 2 m screen over the model terrain, then every
    pressure level above it — **an unanchored profile is not returned at all**
    (empty list). The anchor is what makes the result answerable: without the
    ground the profile starts at whatever pressure level happens to be lowest,
    and everything below it — where a winter freezing level actually sits — is
    simply unobserved. A sub-zero 925 hPa point would then look like a frozen
    "surface" and yield its own height as the freezing level, a number the data
    cannot support. Unknown is the honest answer, so both inputs are required.

    Levels *below* the terrain are dropped: the model fills them by
    extrapolation, so at a mountain grid point the 925 hPa "temperature"
    describes air that is underground (verified live 2026-08-26 — a Chopok
    point has its terrain at 1501 m and 925 hPa at 816 m), and interpolating a
    crossing through it can place the freezing level below the ground it is
    measured from.
    """
    if terrain is None or surface_temperature is None:
        return []
    anchor_height = terrain + _SCREEN_HEIGHT
    profile: list[tuple[float, float]] = [(anchor_height, surface_temperature)]
    for level_pa in _PRESSURE_LEVELS_PA:
        level_t = value((*_T_PRESSURE, level_pa))
        geopotential = value((*_Z_PRESSURE, level_pa))
        if level_t is None or geopotential is None:
            continue
        height = geopotential / _G0
        if height <= anchor_height:
            continue
        profile.append((height, level_t - 273.15))
    return profile


def parse_forecast(
    hourly_files: Sequence[tuple[int, bytes]],
    latitude: float,
    longitude: float,
) -> list[ForecastStep]:
    """Decode an ordered run into per-step forecasts at a location.

    ``hourly_files`` is ``(forecast_hour, grib_bytes)`` pairs; they must be
    ordered by forecast hour because total precipitation is accumulated since
    the run start, so the per-step amount is the difference between successive
    files' accumulations (the first available step is reported as-is).

    The model terrain height is published only in a run's hour-000 file and is
    constant, so it is picked up from whichever file carries it and reused for
    every step's upper-air profile. In production that file is always present
    and first (the client takes a run's *contiguous leading* hours, and
    ``FORECAST_HOURS`` starts at 0). A caller passing later hours only gets no
    ``freezing_level`` at all rather than an unanchored guess at one; the
    850 hPa temperature, a plain lookup, is unaffected.
    """
    steps: list[ForecastStep] = []
    grid: tuple[int, int] | None = None
    prev_accum: float | None = None
    prev_hour: int | None = None
    terrain: float | None = None

    for forecast_hour, payload in hourly_files:
        fields: dict[_FieldKey, Grib2Field] = {}
        reference_time: datetime | None = None
        for field in iter_fields(payload):
            reference_time = field.reference_time
            fields.setdefault((*field.param, field.level), field)
        if reference_time is None:
            raise ShmuDataError(f"No fields in forecast hour {forecast_hour}")

        if grid is None:
            anchor = fields.get(_T2M) or next(iter(fields.values()))
            grid = nearest_unmasked_index(anchor, latitude, longitude)
        i, j = grid

        def value(
            key: _FieldKey,
            _fields: dict[_FieldKey, Grib2Field] = fields,
            _i: int = i,
            _j: int = j,
        ) -> float | None:
            field = _fields.get(key)
            return None if field is None else field.value_at(_i, _j)

        t2m = value(_T2M)
        temperature = None if t2m is None else t2m - 273.15

        accum = value(_TP)
        if accum is None:
            precipitation = None
        elif prev_accum is None:
            precipitation = max(accum, 0.0)
        else:
            # A new run resets accumulation; clamp negatives to 0.
            precipitation = max(accum - prev_accum, 0.0)
        if accum is not None:
            prev_accum = accum

        # The precip accumulation covers the gap since the previous file, so
        # that same gap is the step duration used to turn the total into a
        # rate. The first step spans from the run start (its own forecast
        # hour); a non-increasing gap (files fed out of order) falls back to 1.
        span = forecast_hour - prev_hour if prev_hour is not None else forecast_hour
        hours = float(span) if span > 0 else 1.0
        prev_hour = forecast_hour

        u10, v10 = value(_U10), value(_V10)
        if u10 is None or v10 is None:
            wind_speed = wind_bearing = None
        else:
            wind_speed = math.hypot(u10, v10)
            # Meteorological "from" direction.
            wind_bearing = (270.0 - math.degrees(math.atan2(v10, u10))) % 360.0

        gust_u, gust_v = value(_GUST_U), value(_GUST_V)
        wind_gust = (
            None if gust_u is None or gust_v is None else math.hypot(gust_u, gust_v)
        )

        tcc = value(_TCC)
        cloud_coverage = None if tcc is None else min(max(tcc * 100.0, 0.0), 100.0)

        prmsl = value(_PRMSL)
        pressure = None if prmsl is None else prmsl / 100.0

        cape = value(_CAPE)

        if terrain is None:
            terrain = value(_OROGRAPHY)
        t850 = value((*_T_PRESSURE, _AIR_MASS_LEVEL_PA))
        # The published 850 hPa value is reported as-is, even where that level
        # is below the model terrain (a High Tatras grid point sits above it):
        # that is what every 850 hPa air-mass chart shows. Only the profile
        # below drops such levels, because interpolating a crossing through
        # extrapolated sub-surface air would move a real one.
        temperature_850hpa = None if t850 is None else t850 - 273.15

        steps.append(
            ForecastStep(
                time=reference_time + timedelta(hours=forecast_hour),
                temperature=temperature,
                precipitation=precipitation,
                wind_speed=wind_speed,
                wind_gust=wind_gust,
                wind_bearing=wind_bearing,
                pressure=pressure,
                cloud_coverage=cloud_coverage,
                cape=cape,
                temperature_850hpa=temperature_850hpa,
                freezing_level=derive_freezing_level(
                    _vertical_profile(value, temperature, terrain)
                ),
                condition=derive_condition(
                    cloud_coverage=cloud_coverage,
                    precipitation=precipitation,
                    temperature=temperature,
                    cape=cape,
                    hours=hours,
                ),
                span_hours=hours,
                run=reference_time,
            )
        )
    return steps
