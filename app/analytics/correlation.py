"""
Correlation matrix — tính hệ số tương quan giữa các chỉ số ô nhiễm
và giữa ô nhiễm với weather (nhiệt độ, độ ẩm, gió).

DB columns: aqi, pm25, pm10, o3, no2, so2, co
Weather: temperature_c, humidity_pct, wind_speed_mps
"""

import logging
import uuid as _uuid
from itertools import combinations
from datetime import date

import numpy as np
from sqlalchemy import select, and_

from app.db import fetch, get_session
from app.models.analytics import CorrelationMatrix

logger = logging.getLogger(__name__)

AQ_METRICS = ["aqi", "pm25", "pm10", "o3", "no2", "so2", "co"]
WEATHER_METRICS = ["temperature_c", "humidity_pct", "wind_speed_mps"]
ANALYSIS_DAYS = 30


async def compute_correlation_analysis() -> int:
    """Tính correlation matrix cho mỗi station active."""
    logger.info("Starting correlation analysis")

    stations = await fetch(
        "SELECT id::text AS id, name FROM catalog.stations WHERE is_active = TRUE"
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
            logger.error("Correlation failed for station %s: %s", station["name"], e)

    logger.info("Correlation analysis done — %d stations processed", count)
    return count


async def _analyze_station(station_id: str, station_name: str) -> bool:
    """Tính correlation giữa AQ metrics + weather cho 1 station."""

    # Lấy dữ liệu AQ
    aq_rows = await fetch(
        f"""
        SELECT
          observed_at,
          {', '.join(AQ_METRICS)}
        FROM core.air_quality_observations
        WHERE station_id = $1
          AND observed_at > now() - INTERVAL '{ANALYSIS_DAYS} days'
        ORDER BY observed_at
        """,
        station_id,
    )

    if not aq_rows or len(aq_rows) < 24:
        return False

    # Build data arrays cho AQ
    aq_data = {}
    for col in AQ_METRICS:
        vals = [float(r[col]) if r[col] is not None else np.nan for r in aq_rows]
        aq_data[col] = np.array(vals, dtype=np.float64)

    # Lấy weather data (LEFT JOIN equivalent)
    weather_rows = await fetch(
        f"""
        SELECT
          observed_at,
          {', '.join(WEATHER_METRICS)}
        FROM core.weather_observations
        WHERE station_id = $1
          AND observed_at > now() - INTERVAL '{ANALYSIS_DAYS} days'
        ORDER BY observed_at
        """,
        station_id,
    )

    weather_data = {}
    if weather_rows and len(weather_rows) >= 24:
        for col in WEATHER_METRICS:
            vals = [float(r[col]) if r[col] is not None else np.nan for r in weather_rows]
            weather_data[col] = np.array(vals, dtype=np.float64)

    # Tính correlation matrix cho AQ metrics
    correlations = []

    # AQ vs AQ
    for m1, m2 in combinations(AQ_METRICS, 2):
        r = _pearson_corr(aq_data[m1], aq_data[m2])
        if r is not None:
            correlations.append({
                "metric_a": m1, "metric_b": m2,
                "correlation": round(r, 4),
                "category": "aq_aq",
            })

    # AQ vs Weather
    for aq_m in AQ_METRICS:
        for w_m in WEATHER_METRICS:
            if w_m not in weather_data:
                continue
            # Align arrays to min length
            min_len = min(len(aq_data[aq_m]), len(weather_data[w_m]))
            r = _pearson_corr(aq_data[aq_m][:min_len], weather_data[w_m][:min_len])
            if r is not None:
                w_label = w_m.replace("_c", "").replace("_pct", "").replace("_mps", "")
                correlations.append({
                    "metric_a": aq_m, "metric_b": w_label,
                    "correlation": round(r, 4),
                    "category": "aq_weather",
                })

    if not correlations:
        return False

    # Lưu kết quả
    async with get_session() as session:
        stmt = select(CorrelationMatrix).where(
            and_(
                CorrelationMatrix.station_id == _uuid.UUID(station_id),
                CorrelationMatrix.analysis_date == date.today()
            )
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.period_days = ANALYSIS_DAYS
            existing.correlations = correlations
            existing.sample_size = len(aq_rows)
        else:
            obj = CorrelationMatrix(
                station_id=_uuid.UUID(station_id),
                analysis_date=date.today(),
                period_days=ANALYSIS_DAYS,
                correlations=correlations,
                sample_size=len(aq_rows)
            )
            session.add(obj)

    logger.info("Correlation @ %s — %d pairs computed", station_name, len(correlations))
    return True


def _pearson_corr(a: np.ndarray, b: np.ndarray) -> float | None:
    """Tính Pearson correlation, bỏ qua NaN pairs."""
    mask = ~(np.isnan(a) | np.isnan(b))
    a_clean, b_clean = a[mask], b[mask]
    if len(a_clean) < 10:
        return None
    std_a, std_b = np.std(a_clean), np.std(b_clean)
    if std_a == 0 or std_b == 0:
        return None
    return float(np.corrcoef(a_clean, b_clean)[0, 1])
