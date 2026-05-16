"""
Train ML grid AQI predictor + A/B champion-challenger (plan §3.2, §3.4).

Model: sklearn HistGradientBoostingRegressor (xử lý NaN tự nhiên, nhanh,
không cần xgboost — giữ deps nhẹ). Đánh giá bằng GroupKFold theo station_id
(hold-out 1 nhóm trạm → đo khả năng nội suy không gian, đúng plan §3.2).

Champion-challenger (plan §3.4):
  - Champion = model đang production (models/grid_aqi_champion.joblib + .json).
  - Mỗi lần train ra challenger; promote nếu chưa có champion HOẶC
    challenger MAE ≤ champion MAE × (1 - PROMOTE_MARGIN).
  - Metadata (metrics, trained_at, sample_count) lưu sidecar JSON.

Artifact lưu disk (air-quality-be/models/) — KHÔNG đụng forecast.* (owner api).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import GroupKFold
import joblib

from app.grid_ml.features import (
    FEATURE_COLUMNS, TARGET_COLUMN, FEATURE_SET_VERSION, build_training_frame,
)

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
CHAMPION_MODEL = MODELS_DIR / "grid_aqi_champion.joblib"
CHAMPION_META = MODELS_DIR / "grid_aqi_champion.json"

MIN_TRAINING_ROWS = 60
PROMOTE_MARGIN = 0.05  # challenger phải tốt hơn champion ≥ 5%


def _load_champion_meta() -> dict | None:
    if CHAMPION_META.exists():
        try:
            return json.loads(CHAMPION_META.read_text())
        except (ValueError, OSError):
            return None
    return None


async def run_grid_training(training_days: int = 30) -> dict:
    """
    Train challenger, đánh giá CV theo trạm, quyết định promote.
    Trả stats dict (luôn JSON-serializable).
    """
    df = await build_training_frame(training_days)
    if df.empty or len(df) < MIN_TRAINING_ROWS:
        n = 0 if df.empty else len(df)
        logger.warning("ML train skip — chỉ %d dòng (<%d).", n, MIN_TRAINING_ROWS)
        return {"trained": False, "reason": f"insufficient data: {n} rows", "rows": n}

    X = df[FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    y = df[TARGET_COLUMN].to_numpy(dtype=np.float64)
    groups = df["station_id"].to_numpy()
    n_groups = len(np.unique(groups))

    # CV theo nhóm trạm (nếu <2 trạm → đánh giá in-sample, ghi rõ).
    maes, rmses = [], []
    if n_groups >= 2:
        n_splits = min(5, n_groups)
        gkf = GroupKFold(n_splits=n_splits)
        for tr, te in gkf.split(X, y, groups):
            m = HistGradientBoostingRegressor(
                max_iter=300, learning_rate=0.06, max_depth=6,
                min_samples_leaf=15, random_state=42,
            )
            m.fit(X[tr], y[tr])
            pred = m.predict(X[te])
            maes.append(mean_absolute_error(y[te], pred))
            rmses.append(float(np.sqrt(mean_squared_error(y[te], pred))))
        cv_mae = float(np.mean(maes))
        cv_rmse = float(np.mean(rmses))
        cv_kind = f"group_kfold_{n_splits}"
    else:
        m = HistGradientBoostingRegressor(
            max_iter=300, learning_rate=0.06, max_depth=6,
            min_samples_leaf=15, random_state=42,
        )
        m.fit(X, y)
        pred = m.predict(X)
        cv_mae = float(mean_absolute_error(y, pred))
        cv_rmse = float(np.sqrt(mean_squared_error(y, pred)))
        cv_kind = "in_sample_single_group"

    # Fit challenger trên TOÀN bộ data.
    challenger = HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.06, max_depth=6,
        min_samples_leaf=15, random_state=42,
    )
    challenger.fit(X, y)

    meta = {
        "feature_set_version": FEATURE_SET_VERSION,
        "features": FEATURE_COLUMNS,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_days": training_days,
        "sample_count": int(len(df)),
        "station_groups": int(n_groups),
        "cv_kind": cv_kind,
        "metrics": {"mae": round(cv_mae, 3), "rmse": round(cv_rmse, 3)},
        "model_type": "HistGradientBoostingRegressor",
    }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    champ = _load_champion_meta()
    champ_mae = champ["metrics"]["mae"] if champ else None

    promoted = False
    if champ_mae is None:
        reason = "no champion → promote challenger"
        promoted = True
    elif cv_mae <= champ_mae * (1 - PROMOTE_MARGIN):
        reason = f"challenger MAE {cv_mae:.2f} ≤ champion {champ_mae:.2f}×0.95 → promote"
        promoted = True
    else:
        reason = f"challenger MAE {cv_mae:.2f} không vượt champion {champ_mae:.2f} → giữ champion"

    if promoted:
        joblib.dump(challenger, CHAMPION_MODEL)
        meta["is_production"] = True
        CHAMPION_META.write_text(json.dumps(meta, indent=2))

    logger.info(
        "ML train done — rows=%d, groups=%d, MAE=%.3f RMSE=%.3f, %s",
        len(df), n_groups, cv_mae, cv_rmse, reason,
    )
    return {
        "trained": True,
        "promoted": promoted,
        "reason": reason,
        "rows": int(len(df)),
        "station_groups": int(n_groups),
        "metrics": meta["metrics"],
        "champion_mae_before": champ_mae,
    }
