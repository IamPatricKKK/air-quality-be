"""
Seasonal decomposition — phân tích pattern theo giờ/ngày/tuần.
Tính trung bình theo khung giờ (hourly profile), ngày trong tuần,
và peak/off-peak periods cho mỗi station.

DB columns: aqi, pm25, pm10, o3, no2, so2, co
"""

import logging
import uuid as _uuid
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select, and_

from app.db import fetch, get_session
from app.models.analytics import SeasonalPattern

logger = logging.getLogger(__name__)

METRICS = ["aqi", "pm25", "pm10", "o3", "no2", "so2", "co"]
ANALYSIS_DAYS = 30  # dùng data 30 ngày


async def compute_seasonal_analysis(target_metric: str = "aqi") -> int:
    """Phân tích seasonal pattern cho mỗi station active."""
    logger.info("Starting seasonal analysis for metric=%s", target_metric)

    if target_metric not in METRICS:
        target_metric = "aqi"

    stations = await fetch(
        "SELECT id::text AS id, name FROM catalog.stations WHERE is_active = TRUE"
    )
    if not stations:
        return 0

    count = 0
    for station in stations:
        try:
            ok = await _analyze_station(station["id"], station["name"], target_metric)
            if ok:
                count += 1
        except Exception as e:
            logger.error("Seasonal failed for station %s: %s", station["name"], e)

    logger.info("Seasonal analysis done — %d stations processed", count)
    return count


async def _analyze_station(station_id: str, station_name: str, metric: str) -> bool:
    """Tính hourly profile + daily profile + peak hours cho 1 station."""

    # --- Hourly profile: trung bình theo giờ trong ngày ---
    hourly_rows = await fetch(
        f"""
        SELECT
          EXTRACT(HOUR FROM observed_at) AS hour,
          AVG({metric})::NUMERIC(8,2) AS avg_val,
          STDDEV({metric})::NUMERIC(8,2) AS std_val,
          MIN({metric})::NUMERIC(8,2) AS min_val,
          MAX({metric})::NUMERIC(8,2) AS max_val,
          COUNT(*)::int AS samples
        FROM core.air_quality_observations
        WHERE station_id = $1
          AND observed_at > now() - INTERVAL '{ANALYSIS_DAYS} days'
          AND {metric} IS NOT NULL
        GROUP BY EXTRACT(HOUR FROM observed_at)
        ORDER BY hour
        """,
        station_id,
    )

    if not hourly_rows or len(hourly_rows) < 12:
        return False

    # --- Daily profile: trung bình theo ngày trong tuần ---
    daily_rows = await fetch(
        f"""
        SELECT
          EXTRACT(DOW FROM observed_at) AS dow,
          AVG({metric})::NUMERIC(8,2) AS avg_val,
          STDDEV({metric})::NUMERIC(8,2) AS std_val,
          COUNT(*)::int AS samples
        FROM core.air_quality_observations
        WHERE station_id = $1
          AND observed_at > now() - INTERVAL '{ANALYSIS_DAYS} days'
          AND {metric} IS NOT NULL
        GROUP BY EXTRACT(DOW FROM observed_at)
        ORDER BY dow
        """,
        station_id,
    )

    # Tìm peak hours (top 3 giờ có AQI cao nhất)
    sorted_hours = sorted(hourly_rows, key=lambda r: float(r["avg_val"] or 0), reverse=True)
    peak_hours = [int(r["hour"]) for r in sorted_hours[:3]]
    off_peak_hours = [int(r["hour"]) for r in sorted_hours[-3:]]

    # Tìm best/worst day of week
    if daily_rows:
        sorted_days = sorted(daily_rows, key=lambda r: float(r["avg_val"] or 0))
        best_dow = int(sorted_days[0]["dow"])
        worst_dow = int(sorted_days[-1]["dow"])
    else:
        best_dow, worst_dow = None, None

    # Overall stats
    overall_avg = float(np.mean([float(r["avg_val"]) for r in hourly_rows]))
    hourly_variation = float(np.std([float(r["avg_val"]) for r in hourly_rows]))

    # Prepare data
    hourly_profile = [{"hour": int(r["hour"]), "avg": float(r["avg_val"] or 0), "std": float(r["std_val"] or 0),
                      "min": float(r["min_val"] or 0), "max": float(r["max_val"] or 0), "samples": r["samples"]}
                     for r in hourly_rows]
    daily_profile = [{"dow": int(r["dow"]), "avg": float(r["avg_val"] or 0), "std": float(r["std_val"] or 0),
                     "samples": r["samples"]}
                    for r in daily_rows] if daily_rows else []

    # Lưu kết quả
    async with get_session() as session:
        stmt = select(SeasonalPattern).where(
            and_(
                SeasonalPattern.station_id == _uuid.UUID(station_id),
                SeasonalPattern.metric == metric,
                SeasonalPattern.analysis_date == date.today()
            )
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.period_days = ANALYSIS_DAYS
            existing.hourly_profile = hourly_profile
            existing.daily_profile = daily_profile
            existing.peak_hours = peak_hours
            existing.off_peak_hours = off_peak_hours
            existing.best_dow = best_dow
            existing.worst_dow = worst_dow
            existing.overall_avg = round(overall_avg, 2)
            existing.hourly_variation = round(hourly_variation, 2)
        else:
            obj = SeasonalPattern(
                station_id=_uuid.UUID(station_id),
                metric=metric,
                analysis_date=date.today(),
                period_days=ANALYSIS_DAYS,
                hourly_profile=hourly_profile,
                daily_profile=daily_profile,
                peak_hours=peak_hours,
                off_peak_hours=off_peak_hours,
                best_dow=best_dow,
                worst_dow=worst_dow,
                overall_avg=round(overall_avg, 2),
                hourly_variation=round(hourly_variation, 2)
            )
            session.add(obj)

    logger.info("Seasonal %s @ %s — avg=%.1f, variation=%.1f", metric, station_name, overall_avg, hourly_variation)
    return True
