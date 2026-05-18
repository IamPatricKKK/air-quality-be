import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager

from app.auth import protect_ops_request
from app.db import fetch
from app.analytics.router import router as analytics_router
from app.analytics.scheduler import start_analytics_scheduler, stop_analytics_scheduler


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        from app.models.ensure import ensure_analytics_tables
        await ensure_analytics_tables()
    except Exception as e:  # không chặn startup nếu DDL lỗi
        import logging
        logging.getLogger(__name__).error("ensure_analytics_tables failed: %s", e)
    start_analytics_scheduler()
    yield
    stop_analytics_scheduler()


def get_cors_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://localhost:4173",
    )
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI(title="air-quality-be", version="0.2.0", lifespan=lifespan)
app.include_router(analytics_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(protect_ops_request)


# NOTE: Ingest (thu thập dữ liệu Open-Meteo) đã được chuyển sang air-quality-api
# (NestJS). BE chỉ còn đọc dữ liệu đã được API ghi xuống DB để phục vụ Admin/FE.


# Pydantic models ProviderPatch / EndpointPatch / SourceBindingPatch đã gỡ
# cùng với các endpoint tương ứng (Phase 5). Admin UI gọi thẳng
# air-quality-api cho nhóm này.


def is_analytics_enabled() -> bool:
    return os.getenv("ANALYTICS_ENABLED", "true").strip().lower() not in ("0", "false", "off", "no")


@app.get("/api/v1/health")
async def get_health():
    return {
        "service": "air-quality-be",
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "analyticsEnabled": is_analytics_enabled(),
        "version": app.version,
    }


# ============================================================
# Phase 5: các endpoint providers / endpoints / source-bindings /
# pipeline-runs ĐÃ ĐƯỢC CHUYỂN HOÀN TOÀN sang air-quality-api.
# Admin UI nay gọi thẳng:
#   GET  /api/v1/ingest/providers
#   PATCH /api/v1/ingest/providers/{id}
#   GET  /api/v1/ingest/endpoints
#   PATCH /api/v1/ingest/endpoints/{id}
#   GET  /api/v1/ingest/source-bindings
#   PATCH /api/v1/ingest/source-bindings/{id}
#   GET  /api/v1/ingest/pipeline-runs
# của air-quality-api (NestJS).
#
# be chỉ còn giữ 3 resource thuộc phạm vi analytics/forecast:
#   /api/v1/ops/model-versions
#   /api/v1/ops/predictions
#   /api/v1/ops/lineage
# (sẽ rename sang /api/v1/analytics/* ở iteration sau).
# ============================================================


@app.get("/api/v1/ops/model-versions")
async def get_model_versions():
    rows = await fetch(
        """
        SELECT
          mv.id::text,
          mr.code AS "modelCode",
          mv.version,
          mr.target::text AS target,
          mv.is_production AS "isProduction",
          COALESCE((mv.metrics->>'mae')::float, 0) AS mae,
          COALESCE(mv.released_at, mv.created_at) AS "updatedAt"
        FROM forecast.model_versions mv
        JOIN forecast.model_registry mr ON mr.id = mv.model_id
        ORDER BY mv.created_at DESC
        """
    )
    return rows or []


@app.get("/api/v1/ops/predictions")
async def get_predictions():
    rows = await fetch(
        """
        SELECT
          p.id::text,
          s.name AS "stationName",
          p.target::text AS target,
          p.predicted_for AS "predictedFor",
          p.predicted_value AS "predictedValue",
          mv.version AS "modelVersion"
        FROM forecast.predictions p
        JOIN catalog.stations s ON s.id = p.station_id
        LEFT JOIN forecast.model_versions mv ON mv.id = p.model_version_id
        ORDER BY p.predicted_for ASC
        LIMIT 100
        """
    )
    return rows or []


@app.get("/api/v1/ops/lineage")
async def get_lineage(
    station_id: Optional[str] = Query(default=None, alias="stationId"),
    limit: int = Query(default=20, ge=1, le=200),
):
    rows = await fetch(
        """
        SELECT
          latest.station_id::text AS "stationId",
          latest.station_code AS "stationCode",
          latest.station_name AS "stationName",
          latest.source_provider_code AS "providerCode",
          latest.source_endpoint_code AS "endpointCode",
          latest.observed_at AS "observedAt",
          latest.fetched_at AS "fetchedAt",
          latest.aqi,
          latest.pipeline_run_id::text AS "pipelineRunId",
          latest.raw_payload_id::text AS "rawPayloadId",
          latest.normalize_run_id::text AS "normalizeRunId",
          analysis.id::text AS "analysisRunId",
          analysis.analysis_type::text AS "analysisType",
          analysis.status::text AS "analysisStatus",
          prediction.prediction_run_id::text AS "predictionRunId",
          COALESCE(prediction.prediction_count, 0) AS "predictionCount",
          prediction.last_predicted_for AS "lastPredictedFor",
          prediction.last_predicted_value AS "lastPredictedValue"
        FROM ops.v_station_source_latest latest
        LEFT JOIN LATERAL (
          SELECT
            ar.id,
            ar.analysis_type,
            ar.status
          FROM analytics.analysis_runs ar
          WHERE ar.station_id = latest.station_id
          ORDER BY ar.created_at DESC
          LIMIT 1
        ) analysis ON TRUE
        LEFT JOIN LATERAL (
          SELECT
            pr.id AS prediction_run_id,
            COUNT(p.id)::int AS prediction_count,
            MAX(p.predicted_for) AS last_predicted_for,
            (ARRAY_AGG(p.predicted_value ORDER BY p.predicted_for DESC))[1] AS last_predicted_value
          FROM forecast.prediction_runs pr
          LEFT JOIN forecast.predictions p ON p.prediction_run_id = pr.id
          WHERE pr.station_id = latest.station_id
          GROUP BY pr.id
          ORDER BY MAX(pr.created_at) DESC
          LIMIT 1
        ) prediction ON TRUE
        WHERE ($1::uuid IS NULL OR latest.station_id = $1::uuid)
        ORDER BY latest.observed_at DESC NULLS LAST, latest.station_name
        LIMIT $2
        """,
        station_id,
        limit,
    )
    return rows or []


# ─── Grid management (admin only — protected by /ops middleware) ─────────

@app.post("/api/v1/ops/grid/refresh")
async def trigger_grid_refresh():
    """
    Force chạy grid ingest ngay, không chờ cron (mặc định 3h/lần).
    Mất ~45-60s để fetch 701 điểm từ Open-Meteo.
    Admin/operator role required (protected bởi protect_ops_request middleware).
    """
    try:
        from app.grid_ingest.openmeteo_grid import run_grid_ingest
        from app.grid_fusion.fuser import run_grid_fusion
        stats = await run_grid_ingest()
        fusion = await run_grid_fusion()
        from app.analytics.router import invalidate_grid_cache
        invalidate_grid_cache()
        return {"ok": True, **stats, "fusion": fusion}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Grid refresh failed: {exc!r}")


@app.post("/api/v1/ops/grid/fuse")
async def trigger_grid_fusion():
    """
    Force chạy fusion (IDW trạm thật + Open-Meteo) ngay, không chờ cron.
    Dùng quan trắc grid mới nhất đã ingest; không gọi Open-Meteo nên nhanh (~1-2s).
    Admin/operator role required (protected bởi protect_ops_request middleware).
    """
    try:
        from app.grid_fusion.fuser import run_grid_fusion
        stats = await run_grid_fusion()
        from app.analytics.router import invalidate_grid_cache
        invalidate_grid_cache()
        return {"ok": True, **stats}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Grid fusion failed: {exc!r}")


@app.post("/api/v1/ops/grid/ml/train")
async def trigger_grid_ml_train():
    """
    Train ML grid predictor + champion-challenger (plan §3.2/3.4).
    Đọc quan trắc trạm thật, đánh giá CV theo trạm, promote nếu tốt hơn ≥5%.
    Admin/operator role required.
    """
    try:
        from app.grid_ml.train import run_grid_training
        stats = await run_grid_training()
        return {"ok": True, **stats}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Grid ML train failed: {exc!r}")


@app.post("/api/v1/ops/grid/ml/predict")
async def trigger_grid_ml_predict():
    """
    Predict AQI cho mọi grid point bằng champion model (plan §3.3).
    Gated GRID_ML_ENABLED — skip sạch nếu chưa bật / chưa có champion.
    Admin/operator role required.
    """
    try:
        from app.grid_ml.predict import run_grid_prediction
        stats = await run_grid_prediction()
        from app.analytics.router import invalidate_grid_cache
        invalidate_grid_cache()
        return {"ok": True, **stats}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Grid ML predict failed: {exc!r}")


@app.get("/api/v1/ops/grid/health")
async def grid_health():
    """
    Trạng thái sức khỏe grid cho admin: bao nhiêu điểm fresh, stale, by source.
    Khác /api/v1/analytics/grid/stats (public): endpoint này có thể mở rộng
    thêm metrics nội bộ trong tương lai (latency, error rate, cost).
    """
    rows = await fetch(
        """
        WITH point_status AS (
            SELECT
              g.id,
              g.province_name,
              o_latest.observed_at,
              o_latest.aqi,
              CASE
                WHEN o_latest.observed_at IS NULL THEN 'no_data'
                WHEN o_latest.observed_at > now() - interval '6 hours' THEN 'fresh'
                WHEN o_latest.observed_at > now() - interval '24 hours' THEN 'stale'
                ELSE 'expired'
              END AS status
            FROM catalog.grid_points g
            LEFT JOIN LATERAL (
              SELECT observed_at, aqi
              FROM analytics.grid_aqi_observations o
              WHERE o.grid_point_id = g.id
              ORDER BY observed_at DESC
              LIMIT 1
            ) o_latest ON TRUE
            WHERE g.is_active = TRUE AND g.is_land = TRUE
        )
        SELECT status, COUNT(*) AS n
        FROM point_status
        GROUP BY status
        """
    )
    status_map = {r["status"]: r["n"] for r in (rows or [])}
    return {
        "fresh": status_map.get("fresh", 0),
        "stale": status_map.get("stale", 0),
        "expired": status_map.get("expired", 0),
        "no_data": status_map.get("no_data", 0),
        "total": sum(status_map.values()),
    }


# NOTE (Phase 4 cleanup):
# Các endpoint /api/v1/ops/* dưới đây (providers / endpoints / source-bindings /
# pipeline-runs) logic thuộc về air-quality-api (service chính, sở hữu ingest).
# Hiện giữ lại để admin UI cũ không vỡ. Khi admin đã migrate sang gọi
# air-quality-api cho các resource này, toàn bộ block /ops/* SẼ ĐƯỢC XÓA và
# be sẽ chỉ còn mount /api/v1/analytics/* + /api/v1/health.
#
# Endpoint /ops/live-sync (deprecated) đã được gỡ hoàn toàn —
# admin phải gọi air-quality-api POST /api/v1/ingest/run.
