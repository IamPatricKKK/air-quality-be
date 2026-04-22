-- ============================================================
-- Migration 001: Station analytics views
-- Cung cấp dữ liệu phân tích thật cho FE (không phải mock)
-- Nguồn: core.air_quality_observations đã được BE ingest từ Open-Meteo.
-- ============================================================

-- Phân loại AQI theo thang US EPA
CREATE OR REPLACE FUNCTION app.fn_aqi_category(aqi NUMERIC)
RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN aqi IS NULL                THEN 'unknown'
    WHEN aqi <= 50                  THEN 'good'
    WHEN aqi <= 100                 THEN 'moderate'
    WHEN aqi <= 150                 THEN 'unhealthy_sensitive'
    WHEN aqi <= 200                 THEN 'unhealthy'
    WHEN aqi <= 300                 THEN 'very_unhealthy'
    ELSE                                 'hazardous'
  END
$$;

-- Thống kê 24h cho mỗi trạm từ observations thật
CREATE OR REPLACE VIEW analytics.v_station_24h_summary AS
SELECT
  s.id                               AS station_id,
  s.code                             AS station_code,
  COUNT(a.*)                         AS samples,
  AVG(a.aqi)::NUMERIC(6,2)           AS aqi_avg,
  MIN(a.aqi)                         AS aqi_min,
  MAX(a.aqi)                         AS aqi_max,
  AVG(a.pm25)::NUMERIC(6,2)          AS pm25_avg,
  AVG(a.pm10)::NUMERIC(6,2)          AS pm10_avg,
  AVG(a.o3)::NUMERIC(6,2)            AS o3_avg,
  AVG(a.no2)::NUMERIC(6,2)           AS no2_avg,
  AVG(a.so2)::NUMERIC(6,2)           AS so2_avg,
  AVG(a.co)::NUMERIC(6,2)            AS co_avg,
  MAX(a.observed_at)                 AS last_observed_at
FROM catalog.stations s
LEFT JOIN core.air_quality_observations a
  ON a.station_id = s.id
 AND a.observed_at >= now() - INTERVAL '24 hours'
WHERE s.is_active = TRUE
GROUP BY s.id, s.code;

-- Dự báo tuyến tính đơn giản 6h tới dựa trên xu hướng 6h gần nhất
-- (sai phân trung bình từng bước giờ, an toàn khi ít điểm)
CREATE OR REPLACE VIEW forecast.v_station_simple_forecast AS
WITH recent AS (
  SELECT
    station_id,
    observed_at,
    aqi,
    ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY observed_at DESC) AS rn
  FROM core.air_quality_observations
  WHERE observed_at >= now() - INTERVAL '12 hours'
),
latest AS (
  SELECT station_id, aqi AS last_aqi, observed_at AS last_at
  FROM recent WHERE rn = 1
),
slope AS (
  SELECT
    station_id,
    -- slope AQI per hour, fallback 0
    COALESCE(
      (MAX(aqi) FILTER (WHERE rn = 1) - MAX(aqi) FILTER (WHERE rn = 6))
      / NULLIF(EXTRACT(EPOCH FROM (MAX(observed_at) FILTER (WHERE rn = 1)
                                 - MAX(observed_at) FILTER (WHERE rn = 6))) / 3600.0, 0),
      0
    )::NUMERIC(8,3) AS aqi_per_hour
  FROM recent
  GROUP BY station_id
)
SELECT
  l.station_id,
  l.last_at,
  l.last_aqi,
  s.aqi_per_hour,
  GREATEST(0, ROUND(l.last_aqi + s.aqi_per_hour * 1))::INT AS aqi_next_1h,
  GREATEST(0, ROUND(l.last_aqi + s.aqi_per_hour * 3))::INT AS aqi_next_3h,
  GREATEST(0, ROUND(l.last_aqi + s.aqi_per_hour * 6))::INT AS aqi_next_6h
FROM latest l
JOIN slope  s USING (station_id);

-- Tổng hợp phân tích cho FE
CREATE OR REPLACE VIEW app.v_station_analytics AS
SELECT
  v.station_id,
  v.station_code,
  v.station_name,
  v.area_id,
  v.lat, v.lng,
  v.aqi                                       AS current_aqi,
  app.fn_aqi_category(v.aqi)                  AS current_category,
  v.pm25, v.pm10, v.o3, v.no2, v.so2, v.co,
  v.temperature_c, v.humidity_pct, v.wind_speed_mps,
  v.observed_at,
  s24.samples                                 AS samples_24h,
  s24.aqi_avg, s24.aqi_min, s24.aqi_max,
  s24.pm25_avg, s24.pm10_avg,
  app.fn_aqi_category(s24.aqi_avg)            AS avg_category_24h,
  f.aqi_next_1h, f.aqi_next_3h, f.aqi_next_6h,
  f.aqi_per_hour                              AS forecast_slope_per_hour,
  app.fn_aqi_category(f.aqi_next_6h)          AS forecast_category_6h
FROM app.v_station_latest_air_quality v
LEFT JOIN analytics.v_station_24h_summary s24 ON s24.station_id = v.station_id
LEFT JOIN forecast.v_station_simple_forecast f ON f.station_id  = v.station_id;
