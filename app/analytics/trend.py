"""
Trend analysis — phân tích xu hướng dài hạn.
Dùng linear regression trên daily averages để xác định
trend direction (improving / worsening / stable) cho mỗi metric.

DB columns: aqi, pm25, pm10, o3, no2, so2, co
"""

import logging
import uuid as _uuid
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select, and_

from app.db import fetch, get_session
from app.models.analytics import TrendAnalysis

logger = logging.getLogger(__name__)

METRICS = ["aqi", "pm25", "pm10", "o3", "no2", "so2", "co"]
ANALYSIS_DAYS = 30
MIN_DAYS = 7  # ít nhất 7 ngày data


async def compute_trend_analysis() -> int:
    """Phân tích trend cho mỗi station active."""
    logger.info("Starting trend analysis")

    stations = await fetch(
        "SELECT id, name FROM catalog.stations WHERE is_active = TRUE"
    )
    if not stations:
        return 0

    count = 0
    for station in stations:
        try:
            ok = await _analyze_station(station["id"], station["name"])
            if ok:
                count += 1
        except Exception as e:
            logger.error("Trend failed for station %s: %s", station["name"], e)

    logger.info("Trend analysis done — %d stations processed", count)
    return count


async def _analyze_station(station_id: str, station_name: str) -> bool:
    """Tính trend cho tất cả metrics của 1 station."""

    # Lấy daily averages
    rows = await fetch(
        f"""
        SELECT
          observed_at::date AS day,
          {', '.join(f'AVG({m})::NUMERIC(8,2) AS {m}' for m in METRICS)}
        FROM core.air_quality_observations
        WHERE station_id = $1
          AND observed_at > now() - INTERVAL '{ANALYSIS_DAYS} days'
        GROUP BY observed_at::date
        ORDER BY day
        """,
        station_id,
    )

    if not rows or len(rows) < MIN_DAYS:
        return False

    # Tính trend cho mỗi metric
    trends = {}
    for metric in METRICS:
        values = [float(r[metric]) if r[metric] is not None else np.nan for r in rows]
        values = np.array(values, dtype=np.float64)

        # Bỏ NaN
        mask = ~np.isnan(values)
        if mask.sum() < MIN_DAYS:
            continue

        clean_vals = values[mask]
        x = np.arange(len(clean_vals), dtype=np.float64)

        # Linear regression: y = slope * x + intercept
        slope, intercept = np.polyfit(x, clean_vals, 1)

        # Tính % change over period
        start_val = float(intercept)
        end_val = float(slope * (len(clean_vals) - 1) + intercept)
        pct_change = ((end_val - start_val) / start_val * 100) if start_val != 0 else 0

        # Xác định direction
        if abs(pct_change) < 5:
            direction = "stable"
        elif pct_change > 0:
            direction = "worsening"  # AQI tăng = xấu đi
        else:
            direction = "improving"  # AQI giảm = tốt hơn

        # R² (coefficient of determination)
        y_pred = slope * x + intercept
        ss_res = np.sum((clean_vals - y_pred) ** 2)
        ss_tot = np.sum((clean_vals - np.mean(clean_vals)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        trends[metric] = {
            "slope": round(float(slope), 4),
            "intercept": round(float(intercept), 2),
            "r_squared": round(float(r_squared), 4),
            "pct_change": round(float(pct_change), 2),
            "direction": direction,
            "start_avg": round(float(np.mean(clean_vals[:3])), 2),
            "end_avg": round(float(np.mean(clean_vals[-3:])), 2),
            "overall_avg": round(float(np.mean(clean_vals)), 2),
            "data_points": int(mask.sum()),
        }

    if not trends:
        return False

    # Overall direction (based on AQI if available)
    overall_direction = trends.get("aqi", {}).get("direction", "unknown")

    async with get_session() as session:
        stmt = select(TrendAnalysis).where(
            and_(
                TrendAnalysis.station_id == _uuid.UUID(station_id),
                TrendAnalysis.analysis_date == date.today()
            )
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.period_days = ANALYSIS_DAYS
            existing.trends = trends
            existing.overall_direction = overall_direction
        else:
            obj = TrendAnalysis(
                station_id=_uuid.UUID(station_id),
                analysis_date=date.today(),
                period_days=ANALYSIS_DAYS,
                trends=trends,
                overall_direction=overall_direction
            )
            session.add(obj)

    logger.info(
        "Trend @ %s — AQI %s (%.1f%%)",
        station_name, overall_direction,
        trends.get("aqi", {}).get("pct_change", 0),
    )
    return True
