"""
Forecast schema models - read/write forecast data.

These tables store forecast runs, metadata, and individual forecast points
for air quality predictions using various models.
"""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import String, Integer, Float, DateTime, Numeric, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ForecastRun(Base):
    """
    A forecast model execution/training run.

    Records metadata about a single training and prediction session
    for a forecast model (e.g., Prophet, ARIMA, Linear Regression).
    """
    __tablename__ = "forecast_runs"
    __table_args__ = {"schema": "forecast"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # References
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.stations.id"), nullable=False
    )

    # Model configuration
    model_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="prophet"
    )
    target_metric: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="aqi"
    )
    horizon_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="24"
    )

    # Performance metrics
    mae: Mapped[Optional[float]] = mapped_column(Numeric(8, 3), nullable=True)
    rmse: Mapped[Optional[float]] = mapped_column(Numeric(8, 3), nullable=True)
    mape: Mapped[Optional[float]] = mapped_column(Numeric(8, 3), nullable=True)

    # Training data info
    training_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Execution timeline
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Status and error handling
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="running"
    )
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Record metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationship to forecast points
    forecast_points: "Mapped[list[ForecastPoint]]" = relationship(
        "ForecastPoint",
        back_populates="forecast_run",
        cascade="all, delete-orphan",
        foreign_keys="ForecastPoint.forecast_run_id",
    )

    def __repr__(self) -> str:
        return f"<ForecastRun(id={self.id}, station_id={self.station_id}, model_type={self.model_type}, status={self.status})>"


class ForecastPoint(Base):
    """
    Individual forecast point from a forecast run.

    Each record represents one predicted value at a specific time for a metric.
    """
    __tablename__ = "forecast_points"
    __table_args__ = {"schema": "forecast"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # References
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("forecast.forecast_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog.stations.id"), nullable=False
    )

    # Prediction details
    target_metric: Mapped[str] = mapped_column(String(50), nullable=False)

    # Prediction timing
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Prediction value
    predicted_value: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)

    # Confidence bounds
    lower_bound: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    upper_bound: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)

    # Record metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationship to forecast run
    forecast_run: "Mapped[ForecastRun]" = relationship(
        "ForecastRun",
        back_populates="forecast_points",
        foreign_keys=[forecast_run_id],
    )

    def __repr__(self) -> str:
        return f"<ForecastPoint(id={self.id}, forecast_run_id={self.forecast_run_id}, predicted_at={self.predicted_at}, value={self.predicted_value})>"
