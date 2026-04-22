"""
Anomaly detection: z-score + IQR.
Quét observations gần nhất, so sánh với lịch sử 7 ngày.

DB columns: aqi, pm25, pm10, o3, no2, so2, co
"""

import logging
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select, and_

from app.db import fetch, get_session
from app.models.analytics import AnomalyRecord

logger = logging.getLogger(__name__)

# Tên cột trong DB — dùng trực tiếp, không map
METRICS = ["aqi", "pm25", "pm10", "o3", "no2", "so2", "co"]

ZSCORE_THRESHOLD = 3.0
IQR_FACTOR = 1.5


async def detect_anomalies() -> int:
    """Quét observations 2h gần nhất, phát hiện anomaly bằng z-score + IQR."""
    logger.info("Starting anomaly detection scan")

    stations = await fetch(
        "SELECT id, name FROM catalog.stations WHERE is_active = TRUE"
    )
    if not stations:
        return 0

    total = 0
    for station in stations:
        sid = station["id"]
        for col in METRICS:
            count = await _check_metric(sid, col)
            total += count

    logger.info("Anomaly detection done — %d anomalies found", total)
    return total


async def _check_metric(station_id: str, col: str) -> int:
    """Kiểm tra 1 metric cho 1 station."""
    # Lấy lịch sử 7 ngày
    history = await fetch(
        f"""
        SELECT {col} AS val
        FROM core.air_quality_observations
        WHERE station_id = $1
          AND observed_at > now() - INTERVAL '7 days'
          AND {col} IS NOT NULL
        ORDER BY observed_at
        """,
        station_id,
    )
    if not history or len(history) < 10:
        return 0  # không đủ data

    values = np.array([float(r["val"]) for r in history], dtype=np.float64)
    mean = float(np.mean(values))
    std = float(np.std(values))

    # Lấy observations 2h gần nhất
    recent = await fetch(
        f"""
        SELECT {col} AS val, observed_at
        FROM core.air_quality_observations
        WHERE station_id = $1
          AND observed_at > now() - INTERVAL '2 hours'
          AND {col} IS NOT NULL
        ORDER BY observed_at DESC
        """,
        station_id,
    )
    if not recent:
        return 0

    count = 0
    q1, q3 = float(np.percentile(values, 25)), float(np.percentile(values, 75))
    iqr = q3 - q1
    station_uuid = uuid.UUID(station_id) if isinstance(station_id, str) else station_id

    async with get_session() as session:
        for r in recent:
            val = float(r["val"])
            obs_at = r["observed_at"]

            # Z-score method
            z = (val - mean) / std if std > 0 else 0
            is_zscore_anomaly = abs(z) >= ZSCORE_THRESHOLD

            # IQR method
            iqr_lower = q1 - IQR_FACTOR * iqr
            iqr_upper = q3 + IQR_FACTOR * iqr
            is_iqr_anomaly = val < iqr_lower or val > iqr_upper
            iqr_f = max(
                (val - iqr_upper) / iqr if iqr > 0 and val > iqr_upper else 0,
                (iqr_lower - val) / iqr if iqr > 0 and val < iqr_lower else 0,
            )

            if not is_zscore_anomaly and not is_iqr_anomaly:
                continue

            # Xác định severity
            severity = "info"
            if abs(z) >= 4.0 or iqr_f >= 3.0:
                severity = "critical"
            elif abs(z) >= 3.0 or iqr_f >= 1.5:
                severity = "warning"

            method = "zscore" if is_zscore_anomaly else "iqr"
            desc = (
                f"{col.upper()} = {val:.1f} (mean={mean:.1f}, std={std:.1f}, z={z:.2f})"
                if method == "zscore"
                else f"{col.upper()} = {val:.1f} nằm ngoài IQR [{iqr_lower:.1f}, {iqr_upper:.1f}]"
            )

            # Dedup: kiểm tra anomaly cùng station + metric + hour
            existing = await fetch(
                """
                SELECT 1 FROM analytics.anomalies
                WHERE station_id = $1 AND metric = $2
                  AND detected_at > $3::timestamptz - INTERVAL '1 hour'
                LIMIT 1
                """,
                station_id, col, obs_at,
            )
            if existing:
                continue

            # Create anomaly record via ORM
            anomaly = AnomalyRecord(
                station_id=station_uuid,
                metric=col,
                detected_at=obs_at,
                value=val,
                z_score=round(z, 3),
                iqr_factor=round(iqr_f, 3),
                method=method,
                severity=severity,
                description=desc,
            )
            session.add(anomaly)
            count += 1

        await session.commit()

    return count
