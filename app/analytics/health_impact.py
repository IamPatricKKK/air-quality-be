"""
Health impact scoring — đánh giá tác động sức khỏe dựa trên EPA AQI.
Tính exposure score, health risk level, và khuyến nghị cho mỗi station.

Bảng phân loại EPA AQI:
  0-50:    Good (xanh lá)
  51-100:  Moderate (vàng)
  101-150: Unhealthy for Sensitive Groups (cam)
  151-200: Unhealthy (đỏ)
  201-300: Very Unhealthy (tím)
  301-500: Hazardous (nâu đỏ)

DB columns: aqi, pm25, pm10, o3, no2, so2, co
"""

import logging
import uuid as _uuid
from datetime import datetime

import numpy as np
from sqlalchemy import select

from app.db import fetch, get_session
from app.models.analytics import HealthImpact

logger = logging.getLogger(__name__)

ANALYSIS_HOURS = 48  # Dùng 48h gần nhất

# EPA AQI breakpoints và mô tả
AQI_LEVELS = [
    {"min": 0, "max": 50, "label": "good", "risk": "low",
     "advice_vi": "Chất lượng không khí tốt. An toàn cho mọi hoạt động ngoài trời.",
     "advice_en": "Air quality is satisfactory. Safe for all outdoor activities."},
    {"min": 51, "max": 100, "label": "moderate", "risk": "low",
     "advice_vi": "Chấp nhận được. Nhóm nhạy cảm nên hạn chế hoạt động ngoài trời kéo dài.",
     "advice_en": "Acceptable. Sensitive groups should limit prolonged outdoor exertion."},
    {"min": 101, "max": 150, "label": "unhealthy_sensitive", "risk": "moderate",
     "advice_vi": "Không lành mạnh cho nhóm nhạy cảm. Trẻ em, người già, người bệnh hô hấp nên ở trong nhà.",
     "advice_en": "Unhealthy for sensitive groups. Children, elderly, and respiratory patients should stay indoors."},
    {"min": 151, "max": 200, "label": "unhealthy", "risk": "high",
     "advice_vi": "Không lành mạnh. Mọi người nên giảm hoạt động ngoài trời. Đeo khẩu trang khi ra ngoài.",
     "advice_en": "Unhealthy. Everyone should reduce outdoor activities. Wear masks outdoors."},
    {"min": 201, "max": 300, "label": "very_unhealthy", "risk": "very_high",
     "advice_vi": "Rất không lành mạnh. Tránh ra ngoài. Đóng cửa sổ, dùng máy lọc không khí.",
     "advice_en": "Very unhealthy. Avoid going outside. Close windows, use air purifiers."},
    {"min": 301, "max": 500, "label": "hazardous", "risk": "critical",
     "advice_vi": "Nguy hiểm! Ở trong nhà, không ra ngoài trừ trường hợp khẩn cấp.",
     "advice_en": "Hazardous! Stay indoors. Do not go outside except in emergencies."},
]


def _get_aqi_level(aqi: float) -> dict:
    """Tra bảng AQI level."""
    for level in AQI_LEVELS:
        if level["min"] <= aqi <= level["max"]:
            return level
    return AQI_LEVELS[-1]  # > 500 → hazardous


def _compute_exposure_score(values: list[float]) -> float:
    """
    Tính exposure score (0-100) dựa trên thời gian tiếp xúc ở mỗi mức AQI.
    Trọng số tăng theo mức: good=0, moderate=1, USG=2, unhealthy=4, VU=8, hazardous=16
    """
    weights = [0, 1, 2, 4, 8, 16]
    total_weight = 0
    for v in values:
        for i, level in enumerate(AQI_LEVELS):
            if v <= level["max"]:
                total_weight += weights[i]
                break
        else:
            total_weight += weights[-1]

    max_possible = len(values) * weights[-1]
    if max_possible == 0:
        return 0
    return round(total_weight / max_possible * 100, 1)


async def compute_health_impact() -> int:
    """Tính health impact cho mỗi station active."""
    logger.info("Starting health impact analysis")

    stations = await fetch(
        "SELECT id::text AS id, name FROM catalog.stations WHERE is_active = TRUE"
    )
    if not stations:
        return 0

    count = 0
    for station in stations:
        try:
            ok = await _analyze_station(station["id"], station["name"])
            if ok:
                count += 1
        except Exception as e:
            logger.error("Health impact failed for station %s: %s", station["name"], e)

    logger.info("Health impact analysis done — %d stations processed", count)
    return count


async def _analyze_station(station_id: str, station_name: str) -> bool:
    """Tính health impact cho 1 station."""

    rows = await fetch(
        f"""
        SELECT aqi, pm25, pm10, o3, no2, so2, co, observed_at
        FROM core.air_quality_observations
        WHERE station_id = $1
          AND observed_at > now() - INTERVAL '{ANALYSIS_HOURS} hours'
          AND aqi IS NOT NULL
        ORDER BY observed_at DESC
        """,
        station_id,
    )

    if not rows or len(rows) < 6:
        return False

    aqi_values = [float(r["aqi"]) for r in rows]
    current_aqi = aqi_values[0]
    avg_aqi = float(np.mean(aqi_values))
    max_aqi = float(np.max(aqi_values))

    current_level = _get_aqi_level(current_aqi)
    avg_level = _get_aqi_level(avg_aqi)
    exposure_score = _compute_exposure_score(aqi_values)

    # Dominant pollutant (highest relative to its "normal" range)
    # Approximate: metric with highest average relative to AQI contribution
    pollutant_avgs = {}
    for col in ["pm25", "pm10", "o3", "no2", "so2", "co"]:
        vals = [float(r[col]) for r in rows if r[col] is not None]
        if vals:
            pollutant_avgs[col] = float(np.mean(vals))

    dominant_pollutant = max(pollutant_avgs, key=pollutant_avgs.get) if pollutant_avgs else "pm25"

    # Time distribution: bao nhiêu giờ ở mỗi mức
    time_in_levels = {}
    for level in AQI_LEVELS:
        label = level["label"]
        hours_count = sum(1 for v in aqi_values if level["min"] <= v <= level["max"])
        if hours_count > 0:
            time_in_levels[label] = hours_count

    async with get_session() as session:
        stmt = select(HealthImpact).where(HealthImpact.station_id == _uuid.UUID(station_id))
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.analysis_time = datetime.now()
            existing.period_hours = ANALYSIS_HOURS
            existing.current_aqi = round(current_aqi, 2)
            existing.avg_aqi = round(avg_aqi, 2)
            existing.max_aqi = round(max_aqi, 2)
            existing.current_level = current_level["label"]
            existing.avg_level = avg_level["label"]
            existing.risk_level = current_level["risk"]
            existing.exposure_score = exposure_score
            existing.dominant_pollutant = dominant_pollutant
            existing.time_in_levels = time_in_levels
            existing.advice_vi = current_level["advice_vi"]
            existing.advice_en = current_level["advice_en"]
            existing.pollutant_averages = pollutant_avgs
        else:
            obj = HealthImpact(
                station_id=_uuid.UUID(station_id),
                analysis_time=datetime.now(),
                period_hours=ANALYSIS_HOURS,
                current_aqi=round(current_aqi, 2),
                avg_aqi=round(avg_aqi, 2),
                max_aqi=round(max_aqi, 2),
                current_level=current_level["label"],
                avg_level=avg_level["label"],
                risk_level=current_level["risk"],
                exposure_score=exposure_score,
                dominant_pollutant=dominant_pollutant,
                time_in_levels=time_in_levels,
                advice_vi=current_level["advice_vi"],
                advice_en=current_level["advice_en"],
                pollutant_averages=pollutant_avgs
            )
            session.add(obj)

    logger.info(
        "Health @ %s — AQI=%.0f (%s), exposure=%.1f",
        station_name, current_aqi, current_level["label"], exposure_score,
    )
    return True
