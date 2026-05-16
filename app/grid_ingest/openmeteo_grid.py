"""
Cron job fetch AQI từ Open-Meteo cho từng grid point và upsert vào
analytics.grid_aqi_observations.

Schedule: mỗi 3 giờ (configurable qua GRID_INGEST_CRON).

Tại sao Open-Meteo:
- Free, không cần API key, hỗ trợ CORS.
- Dữ liệu từ CAMS (Copernicus Atmosphere Monitoring Service) — cùng nguồn
  Berkeley Earth/aqi.in dùng. Resolution global 0.4° (~45 km), Europe 0.1°.
- Query được bất kỳ lat/lng nào → phủ toàn VN.
- Quota free tier rộng (10k req/day soft); với 701 điểm × 8 lần/ngày = 5,608 req/day → safe.

Performance:
- Concurrency 8 → 701 điểm fetch xong trong ~30-60s.
- Bulk upsert qua executemany → 1 round-trip DB.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

import asyncpg
import httpx

logger = logging.getLogger(__name__)

OPENMETEO_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
DEFAULT_CONCURRENCY = 4  # Open-Meteo burst-limit khoảng 5-10 req/s; 4 concurrent là sweet spot
DEFAULT_TIMEOUT_SEC = 15.0
RETRY_DELAYS_SEC = (0.5, 2.0)  # 2 retries với exponential backoff khi 429
SOURCE_CODE = "openmeteo"
CONFIDENCE_SCORE = 0.6  # modeled data → confidence medium


def _get_database_url() -> str | None:
    """Get DATABASE_URL, normalize cho asyncpg (loại bỏ `+asyncpg` driver suffix)."""
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    # SQLAlchemy URL `postgresql+asyncpg://...` không hợp lệ cho asyncpg.connect()
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _fetch_one_point(
    client: httpx.AsyncClient,
    point: dict[str, Any],
    sem: asyncio.Semaphore,
) -> dict[str, Any] | None:
    """Fetch 1 grid point từ Open-Meteo. Trả None nếu lỗi."""
    params = {
        "latitude": float(point["lat"]),
        "longitude": float(point["lng"]),
        "current": (
            "us_aqi,pm2_5,pm10,"
            "nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide"
        ),
        "timezone": "Asia/Ho_Chi_Minh",
    }

    async with sem:
        try:
            payload = None
            # Retry khi 429 (rate-limited) với exponential backoff
            for attempt, delay in enumerate((0.0,) + RETRY_DELAYS_SEC):
                if delay > 0:
                    await asyncio.sleep(delay)
                r = await client.get(OPENMETEO_URL, params=params, timeout=DEFAULT_TIMEOUT_SEC)
                if r.status_code == 200:
                    payload = r.json()
                    break
                if r.status_code != 429:
                    # lỗi khác → không retry, bỏ qua
                    logger.debug(
                        "Open-Meteo HTTP %s for (%s, %s)",
                        r.status_code, point["lat"], point["lng"],
                    )
                    return None
                # 429 → retry sau delay
            if payload is None:
                return None
            cur = payload.get("current") or {}
            aqi = cur.get("us_aqi")
            if aqi is None:
                return None

            # Open-Meteo trả time dạng "2026-05-15T10:00" (local-naive theo timezone đã request).
            observed_at_str = cur.get("time")
            if observed_at_str:
                # Append timezone offset cho Asia/Ho_Chi_Minh (+07:00).
                observed_at = datetime.fromisoformat(observed_at_str + "+07:00")
            else:
                observed_at = datetime.now()

            return {
                "grid_point_id": point["id"],
                "observed_at": observed_at,
                "aqi": int(round(float(aqi))),
                "pm25": _opt_num(cur.get("pm2_5")),
                "pm10": _opt_num(cur.get("pm10")),
                "no2": _opt_num(cur.get("nitrogen_dioxide")),
                "o3": _opt_num(cur.get("ozone")),
                "so2": _opt_num(cur.get("sulphur_dioxide")),
                "co": _opt_num(cur.get("carbon_monoxide")),
            }
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError) as e:
            logger.debug(
                "Open-Meteo fetch failed for (%s, %s): %s",
                point["lat"], point["lng"], e,
            )
            return None


def _opt_num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
        return v if v == v else None  # NaN check
    except (TypeError, ValueError):
        return None


async def run_grid_ingest(concurrency: int = DEFAULT_CONCURRENCY) -> dict[str, int]:
    """
    Fetch AQI từ Open-Meteo cho mọi active grid point và upsert vào DB.
    Trả về stats: {'total': N, 'fetched': M, 'inserted': K}.
    """
    db_url = _get_database_url()
    if not db_url:
        raise RuntimeError("DATABASE_URL không được set")

    conn = await asyncpg.connect(db_url)
    try:
        points = await conn.fetch(
            """
            SELECT id, lat, lng FROM catalog.grid_points
            WHERE is_active = TRUE AND is_land = TRUE
            ORDER BY province_name, lat, lng
            """
        )
    finally:
        await conn.close()

    if not points:
        logger.warning("Không có grid point nào để ingest. Chạy seed_grid_vietnam.py trước.")
        return {"total": 0, "fetched": 0, "inserted": 0}

    point_dicts = [
        {"id": p["id"], "lat": float(p["lat"]), "lng": float(p["lng"])}
        for p in points
    ]

    logger.info("Bắt đầu fetch Open-Meteo cho %d grid points...", len(point_dicts))
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_one_point(client, p, sem) for p in point_dicts]
        results = await asyncio.gather(*tasks)

    valid = [r for r in results if r is not None]
    logger.info("Fetched %d/%d points thành công", len(valid), len(point_dicts))

    if not valid:
        return {"total": len(point_dicts), "fetched": 0, "inserted": 0}

    # Bulk upsert
    conn = await asyncpg.connect(db_url)
    try:
        rows = [
            (
                r["grid_point_id"], r["observed_at"], r["aqi"],
                r["pm25"], r["pm10"], r["o3"], r["no2"], r["so2"], r["co"],
                SOURCE_CODE, CONFIDENCE_SCORE,
            )
            for r in valid
        ]
        await conn.executemany(
            """
            INSERT INTO analytics.grid_aqi_observations
                (grid_point_id, observed_at, aqi, pm25, pm10, o3, no2, so2, co,
                 source_code, confidence_score)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (grid_point_id, observed_at) DO UPDATE SET
                aqi = EXCLUDED.aqi,
                pm25 = EXCLUDED.pm25,
                pm10 = EXCLUDED.pm10,
                o3 = EXCLUDED.o3,
                no2 = EXCLUDED.no2,
                so2 = EXCLUDED.so2,
                co = EXCLUDED.co,
                source_code = EXCLUDED.source_code,
                confidence_score = EXCLUDED.confidence_score,
                fetched_at = now()
            """,
            rows,
        )
    finally:
        await conn.close()

    return {
        "total": len(point_dicts),
        "fetched": len(valid),
        "inserted": len(valid),
    }
