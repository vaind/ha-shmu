"""Reduce station air pressure to mean sea level.

SHMÚ's ``aws1min`` feed reports ``tlak`` as the pressure measured *at the
station* (QFE) — the raw barometer reading, uncorrected for the station's
height. On a mountain station that value is far below the ~1013 hPa people
associate with "air pressure" (e.g. Lomnický Štít at 2635 m reads ≈793 hPa),
which is confusing and not comparable between stations. Home Assistant's
weather platform, synoptic charts and most consumer weather stations instead
report pressure *reduced to sea level* (QFF), so barometers everywhere are on a
common datum.

This module does that reduction with the barometric formula and the ICAO
standard-atmosphere lapse rate, using the station's own temperature (QFF, not
the fixed-temperature QNH used in aviation). It is pure and HA-free so it can
be unit-tested offline like the rest of the vendored library.
"""

from __future__ import annotations

#: ICAO standard-atmosphere constants for the barometric reduction.
_LAPSE_RATE_K_PER_M = 0.0065  # temperature decrease with height (K/m)
_STANDARD_GRAVITY = 9.80665  # m/s^2
_MOLAR_MASS_AIR = 0.0289644  # kg/mol (dry air)
_GAS_CONSTANT = 8.31446  # J/(mol·K)
_KELVIN_OFFSET = 273.15

#: Exponent g·M / (R·L) of the barometric formula (≈5.255). Derived from the
#: constants above rather than hard-coded so the physics stays legible.
_REDUCTION_EXPONENT = (_STANDARD_GRAVITY * _MOLAR_MASS_AIR) / (
    _GAS_CONSTANT * _LAPSE_RATE_K_PER_M
)


def sea_level_pressure(
    station_pressure_hpa: float | None,
    elevation_m: float,
    temperature_c: float | None,
) -> float | None:
    """Reduce a station (QFE) pressure to mean sea level (QFF).

    ``station_pressure_hpa`` is the raw barometer reading, ``elevation_m`` the
    station height above sea level, and ``temperature_c`` the current air
    temperature at the station (drives the reduction, so it must be a real
    reading). Returns the sea-level pressure in hPa, or ``None`` when either the
    pressure or the temperature is missing — the correction is not meaningful
    without both, and guessing would misreport a headline value.

    At ``elevation_m == 0`` the result equals the input (nothing to reduce).
    """
    if station_pressure_hpa is None or temperature_c is None:
        return None

    temperature_k = temperature_c + _KELVIN_OFFSET
    height_term = _LAPSE_RATE_K_PER_M * elevation_m
    ratio = 1.0 - height_term / (temperature_k + height_term)
    return float(station_pressure_hpa * ratio**-_REDUCTION_EXPONENT)
