"""
Feature engineering cho ML grid AQI predictor (plan §3.1).

Target  : AQI trạm thật (core.air_quality_observations.aqi).
Features:
  - Spatial : lat, lng
  - Time    : hour, dow, month + sin/cos(hour) (chu kỳ ngày)
  - Weather : temperature_c, humidity_pct, wind_speed_mps, pressure_hpa,
              precipitation_mm, cloud_cover_pct (core.weather_observations,
              join theo station_id + observed_at gần nhất ±1h)
  - Neighbor: mean AQI của tối đa 3 trạm khác gần nhất tại cùng mốc giờ
              + mean distance (km) — proxy cho lan truyền không gian.

Chỉ đọc READ-only core.*/catalog.* (owner air-quality-api).
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from app.db import fetch

logger = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    "lat", "lng",
    "hour_sin", "hour_cos", "dow", "month",
    "temperature_c", "humidity_pct", "wind_speed_mps",
    "pressure_hpa", "precipitation_mm", "cloud_cover_pct",
    "neighbor_aqi_mean", "neighbor_dist_mean", "neighbor_count",
]
TARGET_COLUMN = "aqi"
FEATURE_SET_VERSION = "grid_aqi_v1"


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _time_feats(ts: pd.Timestamp) -> dict[str, float]:
    h = ts.hour
    return {
        "hour_sin": math.sin(2 * math.pi * h / 24),
        "hour_cos": math.cos(2 * math.pi * h / 24),
        "dow": float(ts.dayofweek),
        "month": float(ts.month),
    }


def _neighbor_feats(
    lat: float, lng: float,
    others: list[dict[str, Any]],  # [{'lat','lng','aqi'}] cùng mốc giờ, KHÔNG gồm điểm hiện tại
    k: int = 3,
) -> dict[str, float]:
    if not others:
        return {"neighbor_aqi_mean": np.nan, "neighbor_dist_mean": np.nan, "neighbor_count": 0.0}
    scored = sorted(
        ((o, _haversine_km(lat, lng, o["lat"], o["lng"])) for o in others),
        key=lambda t: t[1],
    )[:k]
    aqis = [o["aqi"] for o, _ in scored]
    dists = [d for _, d in scored]
    return {
        "neighbor_aqi_mean": float(np.mean(aqis)),
        "neighbor_dist_mean": float(np.mean(dists)),
        "neighbor_count": float(len(scored)),
    }


async def build_training_frame(training_days: int = 30) -> pd.DataFrame:
    """
    Tạo bảng (features + target + station_id) từ quan trắc trạm thật.
    Gộp weather theo cùng station_id và làm tròn observed_at xuống giờ.
    """
    aq = await fetch(
        """
        SELECT a.station_id::text AS station_id,
               s.lat AS lat, s.lng AS lng,
               date_trunc('hour', a.observed_at) AS ts,
               AVG(a.aqi)::float AS aqi
        FROM core.air_quality_observations a
        JOIN catalog.stations s ON s.id = a.station_id
        WHERE s.is_active = TRUE
          AND a.aqi IS NOT NULL
          AND a.observed_at > now() - make_interval(days => $1)
        GROUP BY a.station_id, s.lat, s.lng, date_trunc('hour', a.observed_at)
        """,
        training_days,
    ) or []
    if not aq:
        return pd.DataFrame()

    wx = await fetch(
        """
        SELECT w.station_id::text AS station_id,
               date_trunc('hour', w.observed_at) AS ts,
               AVG(w.temperature_c)   AS temperature_c,
               AVG(w.humidity_pct)    AS humidity_pct,
               AVG(w.wind_speed_mps)  AS wind_speed_mps,
               AVG(w.pressure_hpa)    AS pressure_hpa,
               AVG(w.precipitation_mm) AS precipitation_mm,
               AVG(w.cloud_cover_pct) AS cloud_cover_pct
        FROM core.weather_observations w
        WHERE w.observed_at > now() - make_interval(days => $1)
        GROUP BY w.station_id, date_trunc('hour', w.observed_at)
        """,
        training_days,
    ) or []

    df = pd.DataFrame(aq)
    wxdf = pd.DataFrame(wx) if wx else pd.DataFrame(
        columns=["station_id", "ts", "temperature_c", "humidity_pct",
                 "wind_speed_mps", "pressure_hpa", "precipitation_mm", "cloud_cover_pct"]
    )
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    if not wxdf.empty:
        wxdf["ts"] = pd.to_datetime(wxdf["ts"], utc=True)
    df = df.merge(wxdf, on=["station_id", "ts"], how="left")

    # Neighbor features: nhóm theo mốc giờ.
    rows = []
    for ts, grp in df.groupby("ts"):
        recs = grp.to_dict("records")
        for r in recs:
            others = [
                {"lat": o["lat"], "lng": o["lng"], "aqi": o["aqi"]}
                for o in recs if o["station_id"] != r["station_id"]
            ]
            nb = _neighbor_feats(r["lat"], r["lng"], others)
            tf = _time_feats(pd.Timestamp(ts))
            rows.append({**r, **tf, **nb})

    out = pd.DataFrame(rows)
    for c in FEATURE_COLUMNS:
        if c not in out.columns:
            out[c] = np.nan
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out[TARGET_COLUMN] = pd.to_numeric(out[TARGET_COLUMN], errors="coerce")
    out = out.dropna(subset=[TARGET_COLUMN])
    return out


async def build_inference_frame() -> pd.DataFrame:
    """
    Tạo features cho MỌI grid point để predict.
    Weather lấy từ trạm thật gần nhất (latest <6h); neighbor từ AQI trạm thật latest.
    """
    grid = await fetch(
        """
        SELECT id::text AS grid_point_id, lat, lng
        FROM catalog.grid_points
        WHERE is_active = TRUE AND is_land = TRUE
        """
    ) or []
    if not grid:
        return pd.DataFrame()

    stations = await fetch(
        """
        SELECT DISTINCT ON (s.id)
            s.id::text AS station_id, s.lat AS lat, s.lng AS lng,
            a.aqi::float AS aqi, a.observed_at AS observed_at
        FROM catalog.stations s
        JOIN core.air_quality_observations a ON a.station_id = s.id
        WHERE s.is_active = TRUE AND a.aqi IS NOT NULL
          AND a.observed_at > now() - interval '6 hours'
        ORDER BY s.id, a.observed_at DESC
        """
    ) or []

    wx = await fetch(
        """
        SELECT DISTINCT ON (w.station_id)
            w.station_id::text AS station_id, s.lat AS lat, s.lng AS lng,
            w.temperature_c, w.humidity_pct, w.wind_speed_mps,
            w.pressure_hpa, w.precipitation_mm, w.cloud_cover_pct
        FROM core.weather_observations w
        JOIN catalog.stations s ON s.id = w.station_id
        WHERE w.observed_at > now() - interval '6 hours'
        ORDER BY w.station_id, w.observed_at DESC
        """
    ) or []

    now = pd.Timestamp.utcnow()
    tf = _time_feats(now)
    rows = []
    for g in grid:
        glat, glng = float(g["lat"]), float(g["lng"])
        nb = _neighbor_feats(
            glat, glng,
            [{"lat": float(s["lat"]), "lng": float(s["lng"]), "aqi": float(s["aqi"])} for s in stations],
        )
        # Weather của trạm gần nhất.
        wfeat = {c: np.nan for c in (
            "temperature_c", "humidity_pct", "wind_speed_mps",
            "pressure_hpa", "precipitation_mm", "cloud_cover_pct")}
        if wx:
            nearest = min(wx, key=lambda w: _haversine_km(glat, glng, float(w["lat"]), float(w["lng"])))
            for c in wfeat:
                v = nearest.get(c)
                wfeat[c] = float(v) if v is not None else np.nan
        rows.append({
            "grid_point_id": g["grid_point_id"],
            "lat": glat, "lng": glng,
            **tf, **wfeat, **nb,
        })

    out = pd.DataFrame(rows)
    for c in FEATURE_COLUMNS:
        if c not in out.columns:
            out[c] = np.nan
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out
