"""
Analytics schema models - read/write analytical results.

These tables store computed analytics, summaries, anomalies, and patterns
derived from raw observations. Managed by the analytics service.
"""

from datetime import datetime, date
from typing import Optional
import uuid

from sqlalchemy import String, Integer, Float, DateTime, Date, Numeric, JSON, ForeignKey, UniqueConstraint, text, ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DailySummary(Base):
    """
    Daily aggregated air quality summary for a station.

    Computed from hourly/sub-hourly observations for quick retrieval.
    """
    __tablename__ = "daily_summaries"
    __table_args__ = (
        UniqueConstraint("station_id", "summary_date", name="uq_daily_summaries_station_date"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # References
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.stations.id"), nullable=False
    )

    # Summary period
    summary_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Statistics
    samples: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    aqi_avg: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    aqi_min: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    aqi_max: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    aqi_stddev: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)

    # Pollutant averages
    pm25_avg: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    pm10_avg: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    o3_avg: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    no2_avg: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    so2_avg: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    co_avg: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)

    # Weather averages
    temp_avg: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    humidity_avg: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    wind_avg: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)

    # Classification
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Record metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return f"<DailySummary(station_id={self.station_id}, summary_date={self.summary_date}, aqi_avg={self.aqi_avg})>"


class AnomalyRecord(Base):
    """
    Detected anomalous observation at a station.

    Records unusual patterns that deviate from normal conditions.
    """
    __tablename__ = "anomalies"
    __table_args__ = {"schema": "analytics"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # References
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.stations.id"), nullable=False
    )

    # Metric identifier
    metric: Mapped[str] = mapped_column(String(50), nullable=False)

    # Detection details
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    value: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)

    # Statistical measures
    z_score: Mapped[Optional[float]] = mapped_column(Numeric(8, 3), nullable=True)
    iqr_factor: Mapped[Optional[float]] = mapped_column(Numeric(8, 3), nullable=True)

    # Detection method
    method: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="zscore"
    )

    # Severity and notes
    severity: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="warning"
    )
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Record metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return f"<AnomalyRecord(station_id={self.station_id}, metric={self.metric}, severity={self.severity})>"


class SeasonalPattern(Base):
    """
    Seasonal and temporal patterns in air quality metrics.

    Identifies periodic trends such as hourly, daily, and weekly patterns.
    """
    __tablename__ = "seasonal_patterns"
    __table_args__ = (
        UniqueConstraint("station_id", "metric", "analysis_date", name="uq_seasonal_patterns_unique"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # References
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.stations.id"), nullable=False
    )

    # Pattern definition
    metric: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="aqi"
    )

    # Analysis period
    analysis_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")

    # Hourly and daily profiles as JSON
    hourly_profile: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    daily_profile: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Peak times
    peak_hours: Mapped[Optional[list]] = mapped_column(ARRAY(Integer), nullable=True)
    off_peak_hours: Mapped[Optional[list]] = mapped_column(ARRAY(Integer), nullable=True)

    # Day of week patterns
    best_dow: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0=Monday, 6=Sunday
    worst_dow: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Summary statistics
    overall_avg: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    hourly_variation: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)

    # Record metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return f"<SeasonalPattern(station_id={self.station_id}, metric={self.metric}, analysis_date={self.analysis_date})>"


class CorrelationMatrix(Base):
    """
    Correlation matrix between multiple pollutants and weather factors.

    Computed periodically to understand relationships between variables.
    """
    __tablename__ = "correlation_matrices"
    __table_args__ = (
        UniqueConstraint("station_id", "analysis_date", name="uq_correlation_matrices_unique"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # References
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.stations.id"), nullable=False
    )

    # Analysis period
    analysis_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # Correlation data as JSON
    correlations: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Sample size for statistical relevance
    sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Record metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return f"<CorrelationMatrix(station_id={self.station_id}, analysis_date={self.analysis_date})>"


class TrendAnalysis(Base):
    """
    Trend analysis for air quality metrics.

    Captures directional changes (improving/worsening) over time periods.
    """
    __tablename__ = "trend_analyses"
    __table_args__ = (
        UniqueConstraint("station_id", "analysis_date", name="uq_trend_analyses_unique"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # References
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.stations.id"), nullable=False
    )

    # Analysis period
    analysis_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # Trend data as JSON with individual metric trends
    trends: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Overall direction
    overall_direction: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True  # e.g., 'improving', 'worsening', 'stable'
    )

    # Record metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return f"<TrendAnalysis(station_id={self.station_id}, analysis_date={self.analysis_date}, direction={self.overall_direction})>"


class HealthImpact(Base):
    """
    Health impact assessment for current and recent air quality.

    Latest health impact analysis per station with exposure scores and advice.
    Only the most recent record per station is kept.
    """
    __tablename__ = "health_impacts"
    __table_args__ = {"schema": "analytics"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # References (UNIQUE - only latest per station)
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.stations.id"), nullable=False, unique=True
    )

    # Analysis time
    analysis_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Time window for analysis
    period_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="48"
    )

    # Current and aggregate AQI
    current_aqi: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    avg_aqi: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    max_aqi: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)

    # Air quality categories
    current_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    avg_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Health metrics
    exposure_score: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False)
    dominant_pollutant: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Time-in-level distribution
    time_in_levels: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Health advice
    advice_vi: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    advice_en: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Detailed pollutant data
    pollutant_averages: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Record metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return f"<HealthImpact(station_id={self.station_id}, current_aqi={self.current_aqi}, exposure_score={self.exposure_score})>"
