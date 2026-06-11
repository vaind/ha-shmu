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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

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

# --- Surface fields we need, by (discipline, category, number, level type) ---
# Verified present in every hourly file. Wind/precip gusts are PDT 4.8
# (time-processed) but the tuple still uniquely identifies them.
_T2M = (0, 0, 0, 103)  # 2 m temperature (K)
_U10 = (0, 2, 2, 103)  # 10 m u-wind (m/s)
_V10 = (0, 2, 3, 103)  # 10 m v-wind (m/s)
_GUST_U = (0, 2, 23, 103)  # 10 m u-wind gust (m/s)
_GUST_V = (0, 2, 24, 103)  # 10 m v-wind gust (m/s)
_TP = (0, 1, 193, 1)  # total precipitation, accumulated since run (kg/m²≡mm)
_TCC = (192, 128, 164, 1)  # total cloud cover (fraction 0..1)
_PRMSL = (0, 3, 1, 101)  # pressure reduced to MSL (Pa)
_CAPE = (0, 7, 6, 1)  # convective available potential energy (J/kg)

# Home Assistant weather condition strings (plain values; no HA import).
SUNNY = "sunny"
PARTLYCLOUDY = "partlycloudy"
CLOUDY = "cloudy"
RAINY = "rainy"
POURING = "pouring"
SNOWY = "snowy"
SNOWY_RAINY = "snowy-rainy"
LIGHTNING_RAINY = "lightning-rainy"

#: Rain heavy enough to call "pouring" (mm per forecast step ≈ per hour).
_HEAVY_RAIN_MM = 2.5
#: Any wet step at/under this counts as no meaningful precipitation.
_TRACE_MM = 0.05
#: CAPE above this with precipitation implies a thunderstorm.
_THUNDER_CAPE = 200.0


@dataclass(frozen=True, slots=True)
class ForecastStep:
    """One forecast valid time at the configured location's grid point.

    Units mirror the library's observation model: temperatures °C, wind m/s,
    bearing degrees, pressure hPa, precipitation mm accumulated *within this
    step*, cloud cover %, CAPE J/kg. Any field may be ``None`` if its source
    message was absent. ``condition`` is an HA condition string (plain text).
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
    condition: str | None


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


def derive_condition(
    *,
    cloud_coverage: float | None,
    precipitation: float | None,
    temperature: float | None,
    cape: float | None,
) -> str | None:
    """Map model surface fields to a Home Assistant condition string.

    Cloud cover gives the *self-contained* sky state the observation feed
    lacks (the reason Phase 1 had to scrape). Returns ``None`` only when cloud
    cover is unknown and it is dry — the caller surfaces that as "unknown"
    rather than inventing a sky state (same philosophy as ``conditions.py``).
    """
    wet = precipitation is not None and precipitation > _TRACE_MM
    if wet:
        if cape is not None and cape >= _THUNDER_CAPE:
            return LIGHTNING_RAINY
        if temperature is not None and temperature <= 0.5:
            return SNOWY
        if temperature is not None and temperature <= 2.0:
            return SNOWY_RAINY
        assert precipitation is not None
        return POURING if precipitation >= _HEAVY_RAIN_MM else RAINY
    return sky_from_cloud(cloud_coverage)


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
    """
    steps: list[ForecastStep] = []
    grid: tuple[int, int] | None = None
    prev_accum: float | None = None

    for forecast_hour, payload in hourly_files:
        fields: dict[tuple[int, int, int, int], Grib2Field] = {}
        reference_time: datetime | None = None
        for field in iter_fields(payload):
            reference_time = field.reference_time
            fields.setdefault(field.param, field)
        if reference_time is None:
            raise ShmuDataError(f"No fields in forecast hour {forecast_hour}")

        if grid is None:
            anchor = fields.get(_T2M) or next(iter(fields.values()))
            grid = nearest_unmasked_index(anchor, latitude, longitude)
        i, j = grid

        def value(
            key: tuple[int, int, int, int],
            _fields: dict[tuple[int, int, int, int], Grib2Field] = fields,
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
                condition=derive_condition(
                    cloud_coverage=cloud_coverage,
                    precipitation=precipitation,
                    temperature=temperature,
                    cape=cape,
                ),
            )
        )
    return steps
