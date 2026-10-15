"""Async client for the Slovak Hydrometeorological Institute (SHMÚ) open data.

Data © SHMÚ, https://opendata.shmu.sk/, licensed CC BY 4.0.
"""

from __future__ import annotations

from ._ssl import create_ssl_context
from .borrowing import BORROW_RULES, BorrowRule, SourcedReading, borrow
from .client import (
    ForecastSnapshot,
    GaugeSnapshot,
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
from .gauges import (
    GAUGES,
    Gauge,
    get_gauge,
    nearest_gauge,
)
from .models import GaugeObservation, Observation, Warning
from .pressure import sea_level_pressure
from .radar import LocalEcho, RadarImage
from .resolution import (
    ConditionCandidate,
    ConditionResolution,
    explain_condition,
    resolve_condition,
)
from .stations import (
    STATIONS,
    Station,
    get_station,
    nearest_station,
)
from .website import WebCondition

#: Vendored library version (no PyPI distribution to read it from). It ships
#: only inside the integration, so it is bumped with ``manifest.json`` rather
#: than read from it — the library must not depend on its host package.
__version__ = "0.11.1"

__all__ = [
    "BORROW_RULES",
    "GAUGES",
    "STATIONS",
    "BorrowRule",
    "ConditionCandidate",
    "ConditionResolution",
    "ForecastSnapshot",
    "ForecastStep",
    "Gauge",
    "GaugeObservation",
    "GaugeSnapshot",
    "LocalEcho",
    "Observation",
    "ObservationSnapshot",
    "RadarFrame",
    "RadarImage",
    "RadarSnapshot",
    "ShmuClient",
    "ShmuConnectionError",
    "ShmuDataError",
    "ShmuError",
    "SourcedReading",
    "Station",
    "Warning",
    "WarningsSnapshot",
    "WebCondition",
    "WebConditionsSnapshot",
    "__version__",
    "borrow",
    "condition_from_weather_code",
    "create_ssl_context",
    "explain_condition",
    "get_gauge",
    "get_station",
    "nearest_gauge",
    "nearest_station",
    "resolve_condition",
    "sea_level_pressure",
]
