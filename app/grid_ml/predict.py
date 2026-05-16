"""
Inference: predict AQI cho mọi grid point bằng champion model (plan §3.3).

Gated bởi GRID_ML_ENABLED (mặc định false): Phase 3 là OPTIONAL, không bật
mặc định để KHÔNG ghi đè pipeline fusion đã verify. Khi bật + có champion:
ghi rows source_code='ml_predicted' vào analytics.grid_aqi_observations với
observed_at = giờ hiện tại (tách khỏi observed_at của openmeteo/fused nên
KHÔNG đụng PK; endpoint /grid/latest trả bản mới nhất).

Confidence suy từ MAE champion: thấp MAE → tin cậy cao.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
import joblib
import numpy as np

from app.grid_ml.features import FEATURE_COLUMNS, build_inference_frame
from app.grid_ml.train import CHAMPION_MODEL, CHAMPION_META, _load_champion_meta

logger = logging.getLogger(__name__)

SOURCE_CODE = "ml_predicted"


def _enabled() -> bool:
    return os.getenv("GRID_ML_ENABLED", "false").strip().lower() == "true"


def _get_database_url() -> str | None:
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _confidence_from_mae(mae: float | None) -> float:
    if mae is None:
        return 0.5
    # MAE 0 → 0.95; MAE 50 → ~0.45; clamp [0.3, 0.95].
    return round(max(0.3, min(0.95, 1.0 - mae / 100.0)), 2)


async def run_grid_prediction() -> dict:
    """Trả stats. Skip sạch nếu disabled / chưa có champion."""
    if not _enabled():
        return {"skipped": True, "reason": "GRID_ML_ENABLED != true"}
    if not CHAMPION_MODEL.exists():
        return {"skipped": True, "reason": "chưa có champion model — chạy training trước"}

    db_url = _get_database_url()
    if not db_url:
        raise RuntimeError("DATABASE_URL không được set")

    model = joblib.load(CHAMPION_MODEL)
    meta = _load_champion_meta() or {}
    mae = (meta.get("metrics") or {}).get("mae")
    confidence = _confidence_from_mae(mae)

    df = await build_inference_frame()
    if df.empty:
        return {"skipped": True, "reason": "không có grid point / feature"}

    X = df[FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    preds = model.predict(X)
    observed_at = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    rows = []
    for gid, p in zip(df["grid_point_id"].tolist(), preds):
        aqi = int(round(float(p)))
        if aqi < 0:
            aqi = 0
        rows.append((gid, observed_at, aqi, SOURCE_CODE, confidence))

    conn = await asyncpg.connect(db_url)
    try:
        await conn.executemany(
            """
            INSERT INTO analytics.grid_aqi_observations
                (grid_point_id, observed_at, aqi, source_code, confidence_score)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (grid_point_id, observed_at) DO UPDATE SET
                aqi = EXCLUDED.aqi,
                source_code = EXCLUDED.source_code,
                confidence_score = EXCLUDED.confidence_score,
                fetched_at = now()
            """,
            rows,
        )
    finally:
        await conn.close()

    logger.info(
        "ML predict done — %d grid points, champion MAE=%s, confidence=%.2f",
        len(rows), mae, confidence,
    )
    return {
        "predicted": len(rows),
        "champion_mae": mae,
        "confidence": confidence,
        "observed_at": observed_at.isoformat(),
    }
