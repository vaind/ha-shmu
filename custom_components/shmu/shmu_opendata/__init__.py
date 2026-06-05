"""Async client for the Slovak Hydrometeorological Institute (SHMÚ) open data.

Data © SHMÚ, https://opendata.shmu.sk/, licensed CC BY 4.0.
"""

from __future__ import annotations

from ._ssl import create_ssl_context
from .client import (
    ForecastSnapshot,
    ObservationSnapshot,
    RadarFrame,
    RadarSnapshot,
    ShmuClient,
    WarningsSnapshot,
    WebConditionsSnapshot,
)
from .conditions import condition_from_weather_code
from .exceptions import ShmuConnectionError, ShmuDataError, ShmuError
from .forecast import ForecastStep
from .models import Observation, Warning
from .radar import RadarImage
from .resolution import resolve_condition
from .stations import (
    STATIONS,
    Station,
    get_station,
    nearest_station,
)
from .website import WebCondition

#: Vendored library version (no PyPI distribution to read it from).
__version__ = "0.1.0"

__all__ = [
    "STATIONS",
    "ForecastSnapshot",
    "ForecastStep",
    "Observation",
    "ObservationSnapshot",
    "RadarFrame",
    "RadarImage",
    "RadarSnapshot",
    "ShmuClient",
    "ShmuConnectionError",
    "ShmuDataError",
    "ShmuError",
    "Station",
    "Warning",
    "WarningsSnapshot",
    "WebCondition",
    "WebConditionsSnapshot",
    "__version__",
    "condition_from_weather_code",
    "create_ssl_context",
    "get_station",
    "nearest_station",
    "resolve_condition",
]
