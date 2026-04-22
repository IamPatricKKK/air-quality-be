"""
SQLAlchemy ORM models for air-quality-be service.

Schemas covered:
- catalog: Read-only reference data (stations)
- core: Read-only observation data (air quality and weather observations)
- analytics: Read/write analytical results (daily summaries, anomalies, patterns, health impacts)
- forecast: Read/write forecast data (forecast runs and points)
"""

from .base import Base
from .catalog import Station
from .core import AirQualityObservation, WeatherObservation
from .analytics import (
    DailySummary,
    AnomalyRecord,
    SeasonalPattern,
    CorrelationMatrix,
    TrendAnalysis,
    HealthImpact,
)
from .forecast import ForecastRun, ForecastPoint

__all__ = [
    # Base
    "Base",
    # Catalog
    "Station",
    # Core
    "AirQualityObservation",
    "WeatherObservation",
    # Analytics
    "DailySummary",
    "AnomalyRecord",
    "SeasonalPattern",
    "CorrelationMatrix",
    "TrendAnalysis",
    "HealthImpact",
    # Forecast
    "ForecastRun",
    "ForecastPoint",
]
