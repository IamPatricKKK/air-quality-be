"""
REST endpoints cho analytics & forecast.
Mounted vào FastAPI app tại /api/v1/analytics/*

Models: Prophet, ARIMA, Linear Regression
Analytics: daily summary, anomaly, seasonal, correlation, trend, health impact
"""

import logging
import time
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.db import fetch, fetchrow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

# In-memory TTL cache cho /grid/latest (plan §6.2 — không cần Redis cho đồ án).
# Key = (bounds, province, max_age_hours); value = (expires_epoch, payload).
_GRID_CACHE: dict[tuple, tuple[float, dict]] = {}
_GRID_CACHE_TTL_SEC = 300  # 5 phút (khớp cron grid 3h + fusion → data đổi chậm)


def invalidate_grid_cache() -> None:
    """Xoá cache /grid/latest — gọi sau manual refresh/fuse/predict."""
    _GRID_CACHE.clear()


# ---------- Daily Summaries ----------

@router.get("/daily-summaries")
async def get_daily_summaries(
    station_id: Optional[str] = Query(default=None, alias="stationId"),
    days: int = Query(default=30, ge=1, le=365),
):
    """Lấy daily summaries gần nhất."""
    rows = await fetch(
        """
        SELECT
          ds.id::text,
          ds.station_id::text AS "stationId",
          s.name AS "stationName",
          ds.summary_date::text AS "summaryDate",
          ds.samples,
          ds.aqi_avg AS "aqiAvg",
          ds.aqi_min AS "aqiMin",
          ds.aqi_max AS "aqiMax",
          ds.aqi_stddev AS "aqiStddev",
          ds.pm25_avg AS "pm25Avg",
          ds.pm10_avg AS "pm10Avg",
          ds.o3_avg AS "o3Avg",
          ds.no2_avg AS "no2Avg",
          ds.so2_avg AS "so2Avg",
          ds.co_avg AS "coAvg",
          ds.temp_avg AS "tempAvg",
          ds.humidity_avg AS "humidityAvg",
          ds.wind_avg AS "windAvg",
          ds.category
        FROM analytics.daily_summaries ds
        JOIN catalog.stations s ON s.id = ds.station_id
        WHERE ds.summary_date > CURRENT_DATE - ($1 * INTERVAL '1 day')
          AND ($2::uuid IS NULL OR ds.station_id = $2::uuid)
        ORDER BY ds.summary_date DESC, s.name
        LIMIT 500
        """,
        days, station_id,
    )
    return rows or []


# ---------- Anomalies ----------

@router.get("/anomalies")
async def get_anomalies(
    station_id: Optional[str] = Query(default=None, alias="stationId"),
    days: int = Query(default=7, ge=1, le=90),
    severity: Optional[str] = Query(default=None),
):
    """Lấy danh sách anomaly gần nhất."""
    rows = await fetch(
        """
        SELECT
          a.id::text,
          a.station_id::text AS "stationId",
          s.name AS "stationName",
          a.metric,
          a.detected_at AS "detectedAt",
          a.value,
          a.z_score AS "zScore",
          a.iqr_factor AS "iqrFactor",
          a.method,
          a.severity,
          a.description
        FROM analytics.anomalies a
        JOIN catalog.stations s ON s.id = a.station_id
        WHERE a.detected_at > now() - ($1 || ' days')::INTERVAL
          AND ($2::uuid IS NULL OR a.station_id = $2::uuid)
          AND ($3::text IS NULL OR a.severity = $3)
        ORDER BY a.detected_at DESC
        LIMIT 200
        """,
        str(days), station_id, severity,
    )
    return rows or []


# ---------- Forecast ----------

@router.get("/forecast/latest")
async def get_latest_forecast(
    station_id: str = Query(alias="stationId"),
    metric: str = Query(default="aqi"),
    model: Optional[str] = Query(default=None, alias="modelType"),
):
    """Lấy forecast run mới nhất + forecast points cho 1 station."""
    model_filter = "AND fr.model_type = $3" if model else ""
    params = [station_id, metric]
    if model:
        params.append(model)

    run = await fetchrow(
        f"""
        SELECT
          fr.id::text,
          fr.station_id::text AS "stationId",
          s.name AS "stationName",
          fr.model_type AS "modelType",
          fr.target_metric AS "targetMetric",
          fr.horizon_hours AS "horizonHours",
          fr.mae, fr.rmse, fr.mape,
          fr.training_rows AS "trainingRows",
          fr.status,
          fr.started_at AS "startedAt",
          fr.finished_at AS "finishedAt"
        FROM forecast.forecast_runs fr
        JOIN catalog.stations s ON s.id = fr.station_id
        WHERE fr.station_id = $1::uuid
          AND fr.target_metric = $2
          AND fr.status = 'success'
          {model_filter}
        ORDER BY fr.created_at DESC
        LIMIT 1
        """,
        *params,
    )
    if not run:
        raise HTTPException(status_code=404, detail="No forecast available for this station")

    points = await fetch(
        """
        SELECT
          fp.predicted_at AS "predictedAt",
          fp.predicted_value AS "predictedValue",
          fp.lower_bound AS "lowerBound",
          fp.upper_bound AS "upperBound"
        FROM forecast.forecast_points fp
        WHERE fp.forecast_run_id = $1::uuid
        ORDER BY fp.predicted_at
        """,
        run["id"],
    )

    return {
        "run": run,
        "points": points or [],
    }


@router.get("/forecast/compare")
async def compare_forecast_models(
    station_id: str = Query(alias="stationId"),
    metric: str = Query(default="aqi"),
):
    """So sánh kết quả các model forecast cho 1 station."""
    runs = await fetch(
        """
        SELECT DISTINCT ON (fr.model_type)
          fr.id::text,
          fr.model_type AS "modelType",
          fr.mae, fr.rmse, fr.mape,
          fr.training_rows AS "trainingRows",
          fr.horizon_hours AS "horizonHours",
          fr.finished_at AS "finishedAt"
        FROM forecast.forecast_runs fr
        WHERE fr.station_id = $1::uuid
          AND fr.target_metric = $2
          AND fr.status = 'success'
        ORDER BY fr.model_type, fr.created_at DESC
        """,
        station_id, metric,
    )

    result = []
    for run in (runs or []):
        points = await fetch(
            """
            SELECT
              fp.predicted_at AS "predictedAt",
              fp.predicted_value AS "predictedValue",
              fp.lower_bound AS "lowerBound",
              fp.upper_bound AS "upperBound"
            FROM forecast.forecast_points fp
            WHERE fp.forecast_run_id = $1::uuid
            ORDER BY fp.predicted_at
            """,
            run["id"],
        )
        result.append({"run": run, "points": points or []})

    return result


@router.get("/forecast/runs")
async def get_forecast_runs(
    station_id: Optional[str] = Query(default=None, alias="stationId"),
    model_type: Optional[str] = Query(default=None, alias="modelType"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Lấy danh sách forecast runs."""
    rows = await fetch(
        """
        SELECT
          fr.id::text,
          fr.station_id::text AS "stationId",
          s.name AS "stationName",
          fr.model_type AS "modelType",
          fr.target_metric AS "targetMetric",
          fr.mae, fr.rmse, fr.mape,
          fr.training_rows AS "trainingRows",
          fr.status,
          fr.error_message AS "errorMessage",
          fr.started_at AS "startedAt",
          fr.finished_at AS "finishedAt"
        FROM forecast.forecast_runs fr
        JOIN catalog.stations s ON s.id = fr.station_id
        WHERE ($1::uuid IS NULL OR fr.station_id = $1::uuid)
          AND ($2::text IS NULL OR fr.model_type = $2)
        ORDER BY fr.created_at DESC
        LIMIT $3
        """,
        station_id, model_type, limit,
    )
    return rows or []


# ---------- Seasonal Patterns ----------

@router.get("/seasonal")
async def get_seasonal_patterns(
    station_id: str = Query(alias="stationId"),
    metric: str = Query(default="aqi"),
):
    """Lấy seasonal pattern mới nhất cho 1 station."""
    row = await fetchrow(
        """
        SELECT
          sp.id::text,
          sp.station_id::text AS "stationId",
          s.name AS "stationName",
          sp.metric,
          sp.analysis_date::text AS "analysisDate",
          sp.period_days AS "periodDays",
          sp.hourly_profile AS "hourlyProfile",
          sp.daily_profile AS "dailyProfile",
          sp.peak_hours AS "peakHours",
          sp.off_peak_hours AS "offPeakHours",
          sp.best_dow AS "bestDow",
          sp.worst_dow AS "worstDow",
          sp.overall_avg AS "overallAvg",
          sp.hourly_variation AS "hourlyVariation"
        FROM analytics.seasonal_patterns sp
        JOIN catalog.stations s ON s.id = sp.station_id
        WHERE sp.station_id = $1::uuid
          AND sp.metric = $2
        ORDER BY sp.analysis_date DESC
        LIMIT 1
        """,
        station_id, metric,
    )
    if not row:
        raise HTTPException(status_code=404, detail="No seasonal analysis available")
    return row


# ---------- Correlation ----------

@router.get("/correlation")
async def get_correlation_matrix(
    station_id: str = Query(alias="stationId"),
):
    """Lấy correlation matrix mới nhất cho 1 station."""
    row = await fetchrow(
        """
        SELECT
          cm.id::text,
          cm.station_id::text AS "stationId",
          s.name AS "stationName",
          cm.analysis_date::text AS "analysisDate",
          cm.period_days AS "periodDays",
          cm.correlations,
          cm.sample_size AS "sampleSize"
        FROM analytics.correlation_matrices cm
        JOIN catalog.stations s ON s.id = cm.station_id
        WHERE cm.station_id = $1::uuid
        ORDER BY cm.analysis_date DESC
        LIMIT 1
        """,
        station_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="No correlation analysis available")
    return row


# ---------- Trend ----------

@router.get("/trend")
async def get_trend_analysis(
    station_id: str = Query(alias="stationId"),
):
    """Lấy trend analysis mới nhất cho 1 station."""
    row = await fetchrow(
        """
        SELECT
          ta.id::text,
          ta.station_id::text AS "stationId",
          s.name AS "stationName",
          ta.analysis_date::text AS "analysisDate",
          ta.period_days AS "periodDays",
          ta.trends,
          ta.overall_direction AS "overallDirection"
        FROM analytics.trend_analyses ta
        JOIN catalog.stations s ON s.id = ta.station_id
        WHERE ta.station_id = $1::uuid
        ORDER BY ta.analysis_date DESC
        LIMIT 1
        """,
        station_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="No trend analysis available")
    return row


# ---------- Health Impact ----------

@router.get("/health-impact")
async def get_health_impact(
    station_id: str = Query(alias="stationId"),
):
    """Lấy health impact mới nhất cho 1 station."""
    row = await fetchrow(
        """
        SELECT
          hi.id::text,
          hi.station_id::text AS "stationId",
          s.name AS "stationName",
          hi.analysis_time AS "analysisTime",
          hi.period_hours AS "periodHours",
          hi.current_aqi AS "currentAqi",
          hi.avg_aqi AS "avgAqi",
          hi.max_aqi AS "maxAqi",
          hi.current_level AS "currentLevel",
          hi.avg_level AS "avgLevel",
          hi.risk_level AS "riskLevel",
          hi.exposure_score AS "exposureScore",
          hi.dominant_pollutant AS "dominantPollutant",
          hi.time_in_levels AS "timeInLevels",
          hi.advice_vi AS "adviceVi",
          hi.advice_en AS "adviceEn",
          hi.pollutant_averages AS "pollutantAverages"
        FROM analytics.health_impacts hi
        JOIN catalog.stations s ON s.id = hi.station_id
        WHERE hi.station_id = $1::uuid
        LIMIT 1
        """,
        station_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="No health impact analysis available")
    return row


@router.get("/health-impact/all")
async def get_all_health_impacts():
    """Lấy health impact của tất cả stations (cho dashboard overview)."""
    rows = await fetch(
        """
        SELECT
          hi.station_id::text AS "stationId",
          s.name AS "stationName",
          hi.current_aqi AS "currentAqi",
          hi.current_level AS "currentLevel",
          hi.risk_level AS "riskLevel",
          hi.exposure_score AS "exposureScore",
          hi.dominant_pollutant AS "dominantPollutant",
          hi.advice_vi AS "adviceVi",
          hi.advice_en AS "adviceEn",
          hi.analysis_time AS "analysisTime"
        FROM analytics.health_impacts hi
        JOIN catalog.stations s ON s.id = hi.station_id
        WHERE s.is_active = TRUE
        ORDER BY hi.current_aqi DESC NULLS LAST
        """
    )
    return rows or []


# ---------- Manual triggers ----------

@router.post("/run/daily-summary")
async def trigger_daily_summary(target_date: Optional[str] = Query(default=None)):
    """Chạy daily summary thủ công."""
    from app.analytics.daily_summary import compute_daily_summaries
    d = date.fromisoformat(target_date) if target_date else None
    count = await compute_daily_summaries(d)
    return {"ok": True, "stations_processed": count}


@router.post("/run/anomaly-detection")
async def trigger_anomaly_detection():
    """Chạy anomaly detection thủ công."""
    from app.analytics.anomaly_detection import detect_anomalies
    count = await detect_anomalies()
    return {"ok": True, "anomalies_found": count}


@router.post("/run/forecast")
async def trigger_forecast(
    metric: str = Query(default="aqi"),
    model: str = Query(default="all"),
):
    """Chạy forecast thủ công. model=all|prophet|arima|linear"""
    results = {}

    if model in ("all", "prophet"):
        from app.analytics.forecast_prophet import run_prophet_forecast
        results["prophet"] = await run_prophet_forecast(metric)

    if model in ("all", "arima"):
        from app.analytics.forecast_arima import run_arima_forecast
        results["arima"] = await run_arima_forecast(metric)

    if model in ("all", "linear"):
        from app.analytics.forecast_linear import run_linear_forecast
        results["linear"] = await run_linear_forecast(metric)

    return {"ok": True, "results": results}


@router.post("/run/seasonal")
async def trigger_seasonal(metric: str = Query(default="aqi")):
    """Chạy seasonal analysis thủ công."""
    from app.analytics.seasonal import compute_seasonal_analysis
    count = await compute_seasonal_analysis(metric)
    return {"ok": True, "stations_processed": count}


@router.post("/run/correlation")
async def trigger_correlation():
    """Chạy correlation analysis thủ công."""
    from app.analytics.correlation import compute_correlation_analysis
    count = await compute_correlation_analysis()
    return {"ok": True, "stations_processed": count}


@router.post("/run/trend")
async def trigger_trend():
    """Chạy trend analysis thủ công."""
    from app.analytics.trend import compute_trend_analysis
    count = await compute_trend_analysis()
    return {"ok": True, "stations_processed": count}


@router.post("/run/health-impact")
async def trigger_health_impact():
    """Chạy health impact analysis thủ công."""
    from app.analytics.health_impact import compute_health_impact
    count = await compute_health_impact()
    return {"ok": True, "stations_processed": count}


# ---------- Grid AQI (phủ toàn VN qua Open-Meteo CAMS) ----------


@router.get("/grid/latest")
async def get_grid_latest(
    bounds: Optional[str] = Query(
        default=None,
        description="Bounding box 'lat_min,lng_min,lat_max,lng_max'",
    ),
    province: Optional[str] = Query(
        default=None,
        description="Lọc theo province_code (vd: 'hanoi', 'khanhhoa')",
    ),
    max_age_hours: int = Query(
        default=12,
        ge=1,
        le=72,
        description="Chỉ trả điểm có data trong N giờ gần đây",
    ),
):
    """
    Trả AQI mới nhất cho mỗi grid point trong bounding box hoặc tỉnh.
    Mỗi grid point có 1 observation duy nhất (latest theo observed_at).
    Dùng cho FE để render heatmap surface phủ toàn VN.
    Cache in-memory 5 phút theo (bounds, province, max_age_hours).
    """
    cache_key = (bounds, province, max_age_hours)
    now_epoch = time.monotonic()
    cached = _GRID_CACHE.get(cache_key)
    if cached and cached[0] > now_epoch:
        return cached[1]

    where_clauses = ["g.is_active = TRUE", "g.is_land = TRUE"]
    params: list = []

    if bounds:
        try:
            parts = [float(x) for x in bounds.split(",")]
            if len(parts) != 4:
                raise ValueError()
            lat_min, lng_min, lat_max, lng_max = parts
        except (ValueError, TypeError):
            raise HTTPException(400, "bounds phải có dạng 'lat_min,lng_min,lat_max,lng_max'")

        params.extend([lat_min, lat_max, lng_min, lng_max])
        where_clauses.append(
            f"g.lat BETWEEN ${len(params) - 3} AND ${len(params) - 2}"
        )
        where_clauses.append(
            f"g.lng BETWEEN ${len(params) - 1} AND ${len(params)}"
        )

    if province:
        params.append(province)
        where_clauses.append(f"g.province_code = ${len(params)}")

    where_sql = " AND ".join(where_clauses)

    query = f"""
        SELECT DISTINCT ON (g.id)
            g.id::text          AS id,
            g.lat,
            g.lng,
            g.province_code,
            g.province_name,
            o.aqi,
            o.pm25,
            o.pm10,
            o.observed_at,
            o.source_code,
            o.confidence_score
        FROM catalog.grid_points g
        LEFT JOIN analytics.grid_aqi_observations o
          ON o.grid_point_id = g.id
         AND o.observed_at > now() - interval '{max_age_hours} hours'
        WHERE {where_sql}
        ORDER BY g.id, o.observed_at DESC
    """

    rows = await fetch(query, *params)
    out = []
    for r in rows:
        if r["aqi"] is None:
            # Grid point chưa có observation trong window → bỏ qua
            continue
        out.append({
            "id": r["id"],
            "lat": float(r["lat"]),
            "lng": float(r["lng"]),
            "province_code": r["province_code"],
            "province_name": r["province_name"],
            "aqi": r["aqi"],
            "pm25": float(r["pm25"]) if r["pm25"] is not None else None,
            "pm10": float(r["pm10"]) if r["pm10"] is not None else None,
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
            "source_code": r["source_code"],
            "confidence_score": float(r["confidence_score"]) if r["confidence_score"] is not None else None,
        })
    payload = {"count": len(out), "data": out}
    _GRID_CACHE[cache_key] = (now_epoch + _GRID_CACHE_TTL_SEC, payload)
    return payload


@router.get("/grid/stats")
async def get_grid_stats():
    """Tổng quan grid coverage cho admin: total, fresh, stale, by source."""
    total_row = await fetchrow(
        "SELECT COUNT(*) AS n FROM catalog.grid_points WHERE is_active = TRUE AND is_land = TRUE"
    )
    fresh_row = await fetchrow("""
        SELECT COUNT(DISTINCT grid_point_id) AS n
        FROM analytics.grid_aqi_observations
        WHERE observed_at > now() - interval '6 hours'
    """)
    by_source_rows = await fetch("""
        SELECT source_code, COUNT(*) AS n,
               MIN(observed_at) AS first_at,
               MAX(observed_at) AS last_at
        FROM analytics.grid_aqi_observations
        GROUP BY source_code
        ORDER BY n DESC
    """)
    return {
        "total_grid_points": total_row["n"] if total_row else 0,
        "fresh_within_6h": fresh_row["n"] if fresh_row else 0,
        "by_source": [
            {
                "source_code": r["source_code"],
                "count": r["n"],
                "first_at": r["first_at"].isoformat() if r["first_at"] else None,
                "last_at": r["last_at"].isoformat() if r["last_at"] else None,
            }
            for r in by_source_rows
        ],
    }


@router.post("/run/all")
async def trigger_all_analytics(metric: str = Query(default="aqi")):
    """Chạy tất cả analytics jobs thủ công."""
    results = {}

    from app.analytics.daily_summary import compute_daily_summaries
    results["daily_summary"] = await compute_daily_summaries()

    from app.analytics.anomaly_detection import detect_anomalies
    results["anomalies"] = await detect_anomalies()

    from app.analytics.forecast_prophet import run_prophet_forecast
    results["prophet"] = await run_prophet_forecast(metric)

    from app.analytics.forecast_arima import run_arima_forecast
    results["arima"] = await run_arima_forecast(metric)

    from app.analytics.forecast_linear import run_linear_forecast
    results["linear"] = await run_linear_forecast(metric)

    from app.analytics.seasonal import compute_seasonal_analysis
    results["seasonal"] = await compute_seasonal_analysis(metric)

    from app.analytics.correlation import compute_correlation_analysis
    results["correlation"] = await compute_correlation_analysis()

    from app.analytics.trend import compute_trend_analysis
    results["trend"] = await compute_trend_analysis()

    from app.analytics.health_impact import compute_health_impact
    results["health_impact"] = await compute_health_impact()

    return {"ok": True, "results": results}
