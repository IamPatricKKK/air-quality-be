"""
Fusion service: kết hợp AQI trạm thật (core.air_quality_observations) với
baseline Open-Meteo (analytics.grid_aqi_observations source_code='openmeteo')
bằng Inverse-Distance-Weighting (IDW), ghi đè giá trị fused vào chính dòng
quan trắc mới nhất của mỗi grid point.

Chạy ngay SAU grid_ingest (cron riêng), đọc:
  - READ-only  core.air_quality_observations + catalog.stations  (owner: air-quality-api)
  - READ/WRITE analytics.grid_aqi_observations                   (owner: air-quality-be)

Thuật toán IDW (theo plan §2.3):
  - Mỗi grid point luôn có nguồn baseline Open-Meteo, weight = 1.0.
  - Trạm thật cách < 30 km: weight = 3 / dist_km²  (cap 100 khi dist < 0.1 km).
  - fused_aqi   = Σ(aqi · w) / Σw
  - confidence  = min(1, Σw / 3)
  - source_code = 'fused' nếu có ≥ 1 trạm thật đóng góp, ngược lại giữ 'openmeteo'.

Vì PK của analytics.grid_aqi_observations là (grid_point_id, observed_at) —
KHÔNG gồm source_code — không thể có đồng thời 1 dòng 'openmeteo' và 1 dòng
'fused' cùng observed_at. Do đó fusion UPDATE tại chỗ dòng openmeteo mới nhất
(set aqi/source_code/confidence_score). Endpoint /grid/latest luôn trả dòng
observed_at mới nhất nên tự động ưu tiên 'fused', fallback 'openmeteo' cho các
điểm không có trạm thật gần.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

MAX_STATION_DIST_KM = 30.0  # trạm xa hơn không đóng góp
STATION_MAX_AGE_HOURS = 6   # chỉ dùng quan trắc trạm thật còn tươi
OPENMETEO_BASE_WEIGHT = 1.0
IDW_NUMERATOR = 3.0         # weight = IDW_NUMERATOR / dist_km²
IDW_NEAR_CAP = 100.0        # cap khi trạm ~ trùng grid point (dist < 0.1 km)
CONFIDENCE_DIVISOR = 3.0    # confidence = min(1, Σw / 3)


def _get_database_url() -> str | None:
    """DATABASE_URL chuẩn hoá cho asyncpg (bỏ '+asyncpg' driver suffix)."""
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Khoảng cách great-circle (km)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def fuse_point(
    grid_lat: float,
    grid_lng: float,
    openmeteo_aqi: float,
    stations: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Tính giá trị fused cho 1 grid point.

    stations: [{'lat','lng','aqi'}, ...] — danh sách trạm thật đang hoạt động.
    Trả {'aqi','confidence_score','source_code','source_count'}.
    """
    weighted_sum = openmeteo_aqi * OPENMETEO_BASE_WEIGHT
    total_weight = OPENMETEO_BASE_WEIGHT
    contributing = 0

    for s in stations:
        s_aqi = s.get("aqi")
        if s_aqi is None:
            continue
        dist = _haversine_km(grid_lat, grid_lng, s["lat"], s["lng"])
        if dist >= MAX_STATION_DIST_KM:
            continue
        weight = IDW_NEAR_CAP if dist < 0.1 else IDW_NUMERATOR / (dist * dist)
        weighted_sum += float(s_aqi) * weight
        total_weight += weight
        contributing += 1

    fused_aqi = int(round(weighted_sum / total_weight))
    confidence = min(1.0, total_weight / CONFIDENCE_DIVISOR)
    return {
        "aqi": fused_aqi,
        "confidence_score": round(confidence, 2),
        "source_code": "fused" if contributing > 0 else "openmeteo",
        "source_count": contributing + 1,
    }


async def run_grid_fusion() -> dict[str, int]:
    """
    Fuse mọi grid point có quan trắc Open-Meteo mới nhất.
    Trả stats: {'grid_points','with_station','fused','updated'}.
    """
    db_url = _get_database_url()
    if not db_url:
        raise RuntimeError("DATABASE_URL không được set")

    conn = await asyncpg.connect(db_url)
    try:
        # 1) Quan trắc grid mới nhất / điểm (chỉ điểm còn baseline openmeteo|fused).
        grid_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (g.id)
                g.id          AS grid_point_id,
                g.lat         AS lat,
                g.lng         AS lng,
                o.observed_at AS observed_at,
                o.aqi         AS aqi
            FROM catalog.grid_points g
            JOIN analytics.grid_aqi_observations o ON o.grid_point_id = g.id
            WHERE g.is_active = TRUE AND g.is_land = TRUE
              AND o.aqi IS NOT NULL
              AND o.observed_at > now() - interval '24 hours'
            ORDER BY g.id, o.observed_at DESC
            """
        )

        # 2) AQI trạm thật mới nhất / trạm (READ-only core + catalog).
        station_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (s.id)
                s.lat AS lat,
                s.lng AS lng,
                a.aqi AS aqi
            FROM catalog.stations s
            JOIN core.air_quality_observations a ON a.station_id = s.id
            WHERE s.is_active = TRUE
              AND a.aqi IS NOT NULL
              AND a.observed_at > now() - make_interval(hours => $1)
            ORDER BY s.id, a.observed_at DESC
            """,
            STATION_MAX_AGE_HOURS,
        )
    finally:
        await conn.close()

    if not grid_rows:
        logger.warning("Fusion: chưa có quan trắc grid nào. Chạy grid_ingest trước.")
        return {"grid_points": 0, "with_station": 0, "fused": 0, "updated": 0}

    stations = [
        {"lat": float(r["lat"]), "lng": float(r["lng"]), "aqi": float(r["aqi"])}
        for r in station_rows
    ]
    logger.info(
        "Fusion: %d grid points, %d trạm thật còn tươi (<%dh)",
        len(grid_rows), len(stations), STATION_MAX_AGE_HOURS,
    )

    updates: list[tuple] = []
    fused_count = 0
    for r in grid_rows:
        res = fuse_point(
            float(r["lat"]),
            float(r["lng"]),
            float(r["aqi"]),
            stations,
        )
        if res["source_code"] == "fused":
            fused_count += 1
        updates.append((
            res["aqi"],
            res["source_code"],
            res["confidence_score"],
            r["grid_point_id"],
            r["observed_at"],
        ))

    conn = await asyncpg.connect(db_url)
    try:
        await conn.executemany(
            """
            UPDATE analytics.grid_aqi_observations
               SET aqi = $1,
                   source_code = $2,
                   confidence_score = $3,
                   fetched_at = now()
             WHERE grid_point_id = $4 AND observed_at = $5
            """,
            updates,
        )
    finally:
        await conn.close()

    stats = {
        "grid_points": len(grid_rows),
        "with_station": len(stations),
        "fused": fused_count,
        "updated": len(updates),
    }
    logger.info(
        "Fusion done — grid=%d, stations=%d, fused=%d, updated=%d",
        stats["grid_points"], stats["with_station"],
        stats["fused"], stats["updated"],
    )
    return stats
