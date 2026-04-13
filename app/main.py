from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.db import fetch
from app.mock_data import (
    endpoints,
    lineage,
    model_versions,
    patch_endpoint,
    patch_provider,
    patch_source_binding,
    pipeline_runs,
    predictions,
    providers,
    source_bindings,
)


app = FastAPI(title="air-quality-be", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProviderPatch(BaseModel):
    isActive: Optional[bool] = None
    timeoutSeconds: Optional[int] = Field(default=None, ge=1)
    rateLimitPerMinute: Optional[int] = Field(default=None, ge=1)
    config: Optional[Dict[str, Any]] = None


class EndpointPatch(BaseModel):
    isActive: Optional[bool] = None
    scheduleExpression: Optional[str] = None
    parserKey: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class SourceBindingPatch(BaseModel):
    isEnabled: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=0)
    validTo: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


@app.get("/api/v1/health")
async def get_health():
    return {
        "service": "air-quality-be",
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/ops/providers")
async def get_providers():
    rows = await fetch(
        """
        SELECT
          sp.id::text,
          sp.code,
          sp.name,
          sp.category,
          sp.base_url AS "baseUrl",
          sp.auth_type AS "authType",
          sp.rate_limit_per_minute AS "rateLimitPerMinute",
          sp.timeout_seconds AS "timeoutSeconds",
          sp.is_active AS "isActive",
          COALESCE(last_payload.fetched_at, last_run.finished_at, last_run.started_at, sp.updated_at, sp.created_at) AS "lastFetchedAt",
          last_run.started_at AS "lastRunAt",
          last_run.status::text AS "lastRunStatus"
        FROM ingest.source_providers sp
        LEFT JOIN LATERAL (
          SELECT
            pr.started_at,
            pr.finished_at,
            pr.status
          FROM ingest.outbound_requests req
          JOIN ingest.pipeline_runs pr ON pr.id = req.pipeline_run_id
          WHERE req.source_provider_id = sp.id
          ORDER BY pr.started_at DESC
          LIMIT 1
        ) last_run ON TRUE
        LEFT JOIN LATERAL (
          SELECT fetched_at
          FROM ingest.raw_payloads rp
          WHERE rp.source_provider_id = sp.id
          ORDER BY fetched_at DESC
          LIMIT 1
        ) last_payload ON TRUE
        ORDER BY sp.code
        """
    )
    if rows is not None:
        return rows
    return providers


@app.patch("/api/v1/ops/providers/{provider_id}")
async def update_provider(provider_id: str, payload: ProviderPatch):
    rows = await fetch(
        """
        UPDATE ingest.source_providers
        SET
          is_active = COALESCE($2, is_active),
          timeout_seconds = COALESCE($3, timeout_seconds),
          rate_limit_per_minute = COALESCE($4, rate_limit_per_minute),
          config = CASE
            WHEN $5::jsonb IS NULL THEN config
            ELSE config || $5::jsonb
          END,
          updated_at = now()
        WHERE id = $1::uuid
        RETURNING
          id::text,
          code,
          name,
          category,
          base_url AS "baseUrl",
          auth_type AS "authType",
          rate_limit_per_minute AS "rateLimitPerMinute",
          timeout_seconds AS "timeoutSeconds",
          is_active AS "isActive",
          updated_at AS "lastFetchedAt",
          updated_at AS "lastRunAt",
          NULL::text AS "lastRunStatus"
        """,
        provider_id,
        payload.isActive,
        payload.timeoutSeconds,
        payload.rateLimitPerMinute,
        payload.config,
    )
    if rows:
        return rows[0]

    patched = patch_provider(
        provider_id,
        {
            "isActive": payload.isActive,
            "timeoutSeconds": payload.timeoutSeconds,
            "rateLimitPerMinute": payload.rateLimitPerMinute,
        },
    )
    if patched is not None:
        return patched
    raise HTTPException(status_code=404, detail="Provider not found")


@app.get("/api/v1/ops/endpoints")
async def get_endpoints():
    rows = await fetch(
        """
        SELECT
          se.id::text,
          sp.code AS "providerCode",
          se.code,
          se.name,
          se.kind::text AS kind,
          se.http_method AS "httpMethod",
          se.path,
          se.schedule_expression AS "scheduleExpression",
          se.parser_key AS "parserKey",
          se.is_active AS "isActive",
          se.updated_at AS "updatedAt"
        FROM ingest.source_endpoints se
        JOIN ingest.source_providers sp ON sp.id = se.provider_id
        ORDER BY sp.code, se.code
        """
    )
    if rows is not None:
        return rows
    return endpoints


@app.patch("/api/v1/ops/endpoints/{endpoint_id}")
async def update_endpoint(endpoint_id: str, payload: EndpointPatch):
    rows = await fetch(
        """
        UPDATE ingest.source_endpoints
        SET
          is_active = COALESCE($2, is_active),
          schedule_expression = COALESCE($3, schedule_expression),
          parser_key = COALESCE($4, parser_key),
          config = CASE
            WHEN $5::jsonb IS NULL THEN config
            ELSE config || $5::jsonb
          END,
          updated_at = now()
        WHERE id = $1::uuid
        RETURNING
          id::text,
          (SELECT code FROM ingest.source_providers WHERE id = provider_id) AS "providerCode",
          code,
          name,
          kind::text AS kind,
          http_method AS "httpMethod",
          path,
          schedule_expression AS "scheduleExpression",
          parser_key AS "parserKey",
          is_active AS "isActive",
          updated_at AS "updatedAt"
        """,
        endpoint_id,
        payload.isActive,
        payload.scheduleExpression,
        payload.parserKey,
        payload.config,
    )
    if rows:
        return rows[0]

    patched = patch_endpoint(
        endpoint_id,
        {
            "isActive": payload.isActive,
            "scheduleExpression": payload.scheduleExpression,
            "parserKey": payload.parserKey,
        },
    )
    if patched is not None:
        return patched
    raise HTTPException(status_code=404, detail="Endpoint not found")


@app.get("/api/v1/ops/source-bindings")
async def get_source_bindings():
    rows = await fetch(
        """
        SELECT
          ssb.id::text,
          s.id::text AS "stationId",
          s.name AS "stationName",
          sp.code AS "providerCode",
          se.code AS "endpointCode",
          ssb.external_object_id AS "externalObjectId",
          ssb.priority,
          ssb.is_enabled AS "isEnabled",
          ssb.valid_from AS "validFrom",
          ssb.valid_to AS "validTo",
          ssb.updated_at AS "updatedAt"
        FROM ingest.station_source_bindings ssb
        JOIN catalog.stations s ON s.id = ssb.station_id
        JOIN ingest.source_endpoints se ON se.id = ssb.endpoint_id
        JOIN ingest.source_providers sp ON sp.id = se.provider_id
        ORDER BY s.name, ssb.priority, se.code
        """
    )
    if rows is not None:
        return rows
    return source_bindings


@app.patch("/api/v1/ops/source-bindings/{binding_id}")
async def update_source_binding(binding_id: str, payload: SourceBindingPatch):
    rows = await fetch(
        """
        UPDATE ingest.station_source_bindings
        SET
          is_enabled = COALESCE($2, is_enabled),
          priority = COALESCE($3, priority),
          valid_to = COALESCE($4::timestamptz, valid_to),
          config = CASE
            WHEN $5::jsonb IS NULL THEN config
            ELSE config || $5::jsonb
          END,
          updated_at = now()
        WHERE id = $1::uuid
        RETURNING
          id::text,
          (SELECT s.id::text FROM catalog.stations s WHERE s.id = station_id) AS "stationId",
          (SELECT s.name FROM catalog.stations s WHERE s.id = station_id) AS "stationName",
          (SELECT sp.code
           FROM ingest.source_endpoints se
           JOIN ingest.source_providers sp ON sp.id = se.provider_id
           WHERE se.id = endpoint_id) AS "providerCode",
          (SELECT se.code FROM ingest.source_endpoints se WHERE se.id = endpoint_id) AS "endpointCode",
          external_object_id AS "externalObjectId",
          priority,
          is_enabled AS "isEnabled",
          valid_from AS "validFrom",
          valid_to AS "validTo",
          updated_at AS "updatedAt"
        """,
        binding_id,
        payload.isEnabled,
        payload.priority,
        payload.validTo,
        payload.config,
    )
    if rows:
        return rows[0]

    patched = patch_source_binding(
        binding_id,
        {
            "isEnabled": payload.isEnabled,
            "priority": payload.priority,
            "validTo": payload.validTo,
        },
    )
    if patched is not None:
        return patched
    raise HTTPException(status_code=404, detail="Source binding not found")


@app.get("/api/v1/ops/pipeline-runs")
async def get_pipeline_runs():
    rows = await fetch(
        """
        SELECT
          overview.id::text,
          overview.pipeline_code AS "pipelineCode",
          overview.status::text AS status,
          overview.trigger_type AS "triggerType",
          overview.started_at AS "startedAt",
          overview.finished_at AS "finishedAt",
          overview.endpoint_code AS "endpointCode",
          overview.error_summary AS "errorSummary",
          COALESCE(req.request_count, 0) AS "requestCount",
          COALESCE(payloads.payload_count, 0) AS "payloadCount",
          COALESCE(norm.normalize_count, 0) AS "normalizeCount",
          COALESCE(analysis.analysis_count, 0) AS "analysisCount",
          COALESCE(pred.prediction_count, 0) AS "predictionCount"
        FROM ops.v_pipeline_run_overview overview
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS request_count
          FROM ingest.outbound_requests req
          WHERE req.pipeline_run_id = overview.id
        ) req ON TRUE
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS payload_count
          FROM ingest.raw_payloads payload
          WHERE payload.pipeline_run_id = overview.id
        ) payloads ON TRUE
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS normalize_count
          FROM ingest.normalize_runs nr
          WHERE nr.pipeline_run_id = overview.id
        ) norm ON TRUE
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS analysis_count
          FROM analytics.analysis_runs ar
          WHERE ar.pipeline_run_id = overview.id
        ) analysis ON TRUE
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS prediction_count
          FROM forecast.prediction_runs pr
          WHERE pr.pipeline_run_id = overview.id
        ) pred ON TRUE
        ORDER BY overview.started_at DESC
        LIMIT 50
        """
    )
    if rows is not None:
        return rows
    return pipeline_runs


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
    if rows is not None:
        return rows
    return model_versions


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
    if rows is not None:
        return rows
    return predictions


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
    if rows is not None:
        return rows

    if station_id:
        return [item for item in lineage if item["stationId"] == station_id][:limit]
    return lineage[:limit]
