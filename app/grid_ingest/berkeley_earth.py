"""
Berkeley Earth NetCDF ingest — OPTIONAL, cross-validation cho grid (plan §2.2).

⚠️ Plan khuyến nghị SKIP cho đồ án: Open-Meteo (cùng nguồn CAMS) đã đủ; deps
nặng (xarray + netCDF4 ~50MB). Module này CHỈ chạy khi:
  - BERKELEY_EARTH_ENABLED=true, VÀ
  - xarray + netCDF4 đã được cài (lazy import — KHÔNG phải hard dependency).

Không bật / thiếu deps → run_berkeley_ingest() trả {'skipped': True, ...},
KHÔNG raise, KHÔNG ảnh hưởng grid_ingest/fusion. Giữ requirements.txt nhẹ.

Khi bật: tải NetCDF PM2.5 mới nhất, với mỗi grid point lấy giá trị nearest,
quy đổi PM2.5→US AQI (EPA), upsert source_code='berkeley_earth' vào
analytics.grid_aqi_observations (confidence 0.7 — gridded reanalysis).
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import date, datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)

SOURCE_CODE = "berkeley_earth"
CONFIDENCE_SCORE = 0.7
# Cho phép override URL vì format real-time của Berkeley Earth thay đổi theo thời gian.
DEFAULT_URL_TEMPLATE = (
    "https://berkeleyearth.lbl.gov/auto/Real-Time/AirQuality/Maps/PM25_{ymd}.nc"
)


def _enabled() -> bool:
    return os.getenv("BERKELEY_EARTH_ENABLED", "false").strip().lower() == "true"


def _get_database_url() -> str | None:
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _pm25_to_aqi(pm25: float) -> int | None:
    """EPA PM2.5 → US AQI (cùng breakpoints với openweather.ts/openaq.ts)."""
    if pm25 is None or pm25 != pm25 or pm25 < 0:  # NaN/None/neg
        return None
    bp = [
        (0.0, 12.0, 0, 50), (12.1, 35.4, 51, 100), (35.5, 55.4, 101, 150),
        (55.5, 150.4, 151, 200), (150.5, 250.4, 201, 300), (250.5, 500.4, 301, 500),
    ]
    for c_lo, c_hi, i_lo, i_hi in bp:
        if c_lo <= pm25 <= c_hi:
            return round((i_hi - i_lo) / (c_hi - c_lo) * (pm25 - c_lo) + i_lo)
    return 500 if pm25 > 500.4 else None


async def run_berkeley_ingest() -> dict:
    """
    Trả stats. Khi disabled/thiếu deps: {'skipped': True, 'reason': ...}.
    Khi chạy: {'total','fetched','inserted'}.
    """
    if not _enabled():
        return {"skipped": True, "reason": "BERKELEY_EARTH_ENABLED != true"}

    # Lazy import — chỉ require khi thực sự bật.
    try:
        import httpx  # noqa: F401  (đã có sẵn trong requirements)
        import xarray as xr
    except ImportError as e:
        logger.warning("Berkeley Earth bật nhưng thiếu deps (%s) — skip.", e)
        return {"skipped": True, "reason": f"missing dependency: {e}"}

    db_url = _get_database_url()
    if not db_url:
        raise RuntimeError("DATABASE_URL không được set")

    ymd = date.today().strftime("%Y%m%d")
    url = os.getenv("BERKELEY_EARTH_URL") or DEFAULT_URL_TEMPLATE.format(ymd=ymd)

    import httpx
    tmp_path = None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return {"skipped": True, "reason": f"HTTP {r.status_code} từ {url}"}
            with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tf:
                tf.write(r.content)
                tmp_path = tf.name

        conn = await asyncpg.connect(db_url)
        try:
            points = await conn.fetch(
                """
                SELECT id, lat, lng FROM catalog.grid_points
                WHERE is_active = TRUE AND is_land = TRUE
                """
            )
        finally:
            await conn.close()
        if not points:
            return {"total": 0, "fetched": 0, "inserted": 0}

        ds = xr.open_dataset(tmp_path)
        # Tên biến PM2.5 khác nhau giữa các bản — thử vài khả năng.
        var = None
        for cand in ("PM25", "pm25", "PM2.5", "pm2p5"):
            if cand in ds:
                var = cand
                break
        if var is None:
            ds.close()
            return {"skipped": True, "reason": f"không tìm thấy biến PM2.5 trong {url}"}

        observed_at = datetime.now(timezone.utc)
        rows = []
        for p in points:
            try:
                val = ds[var].sel(
                    lat=float(p["lat"]), lon=float(p["lng"]), method="nearest"
                ).values
                pm25 = float(val)
            except Exception:
                continue
            aqi = _pm25_to_aqi(pm25)
            if aqi is None:
                continue
            rows.append((p["id"], observed_at, aqi, pm25, SOURCE_CODE, CONFIDENCE_SCORE))
        ds.close()

        if rows:
            conn = await asyncpg.connect(db_url)
            try:
                await conn.executemany(
                    """
                    INSERT INTO analytics.grid_aqi_observations
                        (grid_point_id, observed_at, aqi, pm25, source_code, confidence_score)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (grid_point_id, observed_at) DO UPDATE SET
                        aqi = EXCLUDED.aqi,
                        pm25 = EXCLUDED.pm25,
                        source_code = EXCLUDED.source_code,
                        confidence_score = EXCLUDED.confidence_score,
                        fetched_at = now()
                    """,
                    rows,
                )
            finally:
                await conn.close()

        return {"total": len(points), "fetched": len(rows), "inserted": len(rows)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
