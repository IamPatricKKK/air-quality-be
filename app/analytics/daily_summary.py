"""
Daily summary job — tính thống kê ngày cho mỗi trạm
từ core.air_quality_observations + core.weather_observations.

Columns trong DB: aqi, pm25, pm10, o3, no2, so2, co
(KHÔNG phải pm2_5, ozone, nitrogen_dioxide, ...)
"""

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import select, and_

from app.db import fetch, get_session
from app.models.analytics import DailySummary

logger = logging.getLogger(__name__)


def _aqi_category(avg: float | None) -> str:
    """Phân loại AQI theo EPA."""
    if avg is None:
        return "unknown"
    if avg <= 50:
        return "good"
    if avg <= 100:
        return "moderate"
    if avg <= 150:
        return "unhealthy_sensitive"
    if avg <= 200:
        return "unhealthy"
    if avg <= 300:
        return "very_unhealthy"
    return "hazardous"


async def compute_daily_summaries(target_date: date | None = None) -> int:
    """Tính daily summary cho target_date (mặc định hôm qua)."""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    logger.info("Computing daily summaries for %s", target_date)

    rows = await fetch(
        """
        SELECT
          s.id AS station_id,
          COUNT(a.*)::int AS samples,
          AVG(a.aqi)::NUMERIC(8,2) AS aqi_avg,
          MIN(a.aqi)::NUMERIC(8,2) AS aqi_min,
          MAX(a.aqi)::NUMERIC(8,2) AS aqi_max,
          STDDEV(a.aqi)::NUMERIC(8,2) AS aqi_stddev,
          AVG(a.pm25)::NUMERIC(8,2) AS pm25_avg,
          AVG(a.pm10)::NUMERIC(8,2) AS pm10_avg,
          AVG(a.o3)::NUMERIC(8,2) AS o3_avg,
          AVG(a.no2)::NUMERIC(8,2) AS no2_avg,
          AVG(a.so2)::NUMERIC(8,2) AS so2_avg,
          AVG(a.co)::NUMERIC(8,2) AS co_avg,
          AVG(w.temperature_c)::NUMERIC(6,2) AS temp_avg,
          AVG(w.humidity_pct)::NUMERIC(6,2) AS humidity_avg,
          AVG(w.wind_speed_mps)::NUMERIC(6,2) AS wind_avg
        FROM catalog.stations s
        JOIN core.air_quality_observations a
          ON a.station_id = s.id
          AND a.observed_at::date = $1
        LEFT JOIN core.weather_observations w
          ON w.station_id = s.id
          AND w.observed_at::date = $1
        WHERE s.is_active = TRUE
        GROUP BY s.id
        HAVING COUNT(a.*) >= 1
        """,
        target_date,
    )

    if not rows:
        logger.info("No observations for %s — skip", target_date)
        return 0

    count = 0
    async with get_session() as session:
        for r in rows:
            category = _aqi_category(r["aqi_avg"])
            station_id = uuid.UUID(r["station_id"]) if isinstance(r["station_id"], str) else r["station_id"]

            # Check if exists
            stmt = select(DailySummary).where(
                and_(
                    DailySummary.station_id == station_id,
                    DailySummary.summary_date == target_date
                )
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if existing:
                # Update existing
                existing.samples = r["samples"]
                existing.aqi_avg = float(r["aqi_avg"]) if r["aqi_avg"] else None
                existing.aqi_min = float(r["aqi_min"]) if r["aqi_min"] else None
                existing.aqi_max = float(r["aqi_max"]) if r["aqi_max"] else None
                existing.aqi_stddev = float(r["aqi_stddev"]) if r["aqi_stddev"] else None
                existing.pm25_avg = float(r["pm25_avg"]) if r["pm25_avg"] else None
                existing.pm10_avg = float(r["pm10_avg"]) if r["pm10_avg"] else None
                existing.o3_avg = float(r["o3_avg"]) if r["o3_avg"] else None
                existing.no2_avg = float(r["no2_avg"]) if r["no2_avg"] else None
                existing.so2_avg = float(r["so2_avg"]) if r["so2_avg"] else None
                existing.co_avg = float(r["co_avg"]) if r["co_avg"] else None
                existing.temp_avg = float(r["temp_avg"]) if r["temp_avg"] else None
                existing.humidity_avg = float(r["humidity_avg"]) if r["humidity_avg"] else None
                existing.wind_avg = float(r["wind_avg"]) if r["wind_avg"] else None
                existing.category = category
            else:
                # Create new
                summary = DailySummary(
                    station_id=station_id,
                    summary_date=target_date,
                    samples=r["samples"],
                    aqi_avg=float(r["aqi_avg"]) if r["aqi_avg"] else None,
                    aqi_min=float(r["aqi_min"]) if r["aqi_min"] else None,
                    aqi_max=float(r["aqi_max"]) if r["aqi_max"] else None,
                    aqi_stddev=float(r["aqi_stddev"]) if r["aqi_stddev"] else None,
                    pm25_avg=float(r["pm25_avg"]) if r["pm25_avg"] else None,
                    pm10_avg=float(r["pm10_avg"]) if r["pm10_avg"] else None,
                    o3_avg=float(r["o3_avg"]) if r["o3_avg"] else None,
                    no2_avg=float(r["no2_avg"]) if r["no2_avg"] else None,
                    so2_avg=float(r["so2_avg"]) if r["so2_avg"] else None,
                    co_avg=float(r["co_avg"]) if r["co_avg"] else None,
                    temp_avg=float(r["temp_avg"]) if r["temp_avg"] else None,
                    humidity_avg=float(r["humidity_avg"]) if r["humidity_avg"] else None,
                    wind_avg=float(r["wind_avg"]) if r["wind_avg"] else None,
                    category=category,
                )
                session.add(summary)
            count += 1

        await session.commit()

    logger.info("Daily summaries for %s: %d stations processed", target_date, count)
    return count
