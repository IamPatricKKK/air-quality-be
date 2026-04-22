"""
Catalog schema models - read-only models for reference data.

These tables are managed by other services and are accessed
for relationships and reference data only.
"""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import String, Float, Boolean, DateTime, text, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Station(Base):
    """
    Air quality monitoring station metadata.

    Represents physical or virtual monitoring locations for air quality measurements.
    Read-only in this service (managed by catalog service).
    """
    __tablename__ = "stations"
    __table_args__ = {"schema": "catalog"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    area_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Geographic information
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Configuration
    station_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="monitoring"
    )
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="Asia/Ho_Chi_Minh"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # Metadata as JSONB
    metadata_: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, name="metadata"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    def __repr__(self) -> str:
        return f"<Station(id={self.id}, code={self.code}, name={self.name})>"
