-- ============================================================
-- Migration 005: WAQI (World Air Quality Index) second data source
-- Thêm provider WAQI vào hệ thống ingest, tạo fusion views
-- để merge dữ liệu từ nhiều nguồn.
-- ============================================================

-- 1) Seed WAQI provider
INSERT INTO ingest.source_providers (id, code, name, category, base_url, is_active, config)
VALUES (
  'a0000000-0000-0000-0000-000000000002',
  'waqi',
  'World Air Quality Index (WAQI)',
  'environmental',
  'https://api.waqi.info',
  TRUE,
  '{"requires_token": true, "rate_limit_rpm": 1000}'::jsonb
)
ON CONFLICT (code) DO UPDATE
  SET name = EXCLUDED.name,
      base_url = EXCLUDED.base_url,
      config = EXCLUDED.config,
      is_active = TRUE;

-- 2) WAQI endpoint: station feed (realtime)
INSERT INTO ingest.source_endpoints (id, source_provider_id, code, name, base_url, path, http_method, parser_key, is_active, config)
VALUES (
  'b0000000-0000-0000-0000-000000000003',
  'a0000000-0000-0000-0000-000000000002',
  'waqi_station_feed',
  'WAQI Station Feed (realtime)',
  'https://api.waqi.info',
  '/feed/geo:{lat};{lng}/',
  'GET',
  'waqi.feed.v1',
  TRUE,
  '{"response_format": "json"}'::jsonb
)
ON CONFLICT (code) DO UPDATE
  SET name = EXCLUDED.name,
      base_url = EXCLUDED.base_url,
      path = EXCLUDED.path,
      parser_key = EXCLUDED.parser_key,
      is_active = TRUE;

-- 3) Thêm cột source_provider_id tham chiếu cho các observation
--    (đã có sẵn từ schema gốc, chỉ đảm bảo index)
CREATE INDEX IF NOT EXISTS idx_aq_obs_provider
  ON core.air_quality_observations (source_provider_id);

CREATE INDEX IF NOT EXISTS idx_weather_obs_provider
  ON core.weather_observations (source_provider_id);

-- 4) Fusion view: merge AQ observations từ tất cả providers
--    Ưu tiên: lấy bản ghi mới nhất cho mỗi (station, hour)
CREATE OR REPLACE VIEW core.v_aq_observations_fused AS
WITH ranked AS (
  SELECT
    o.*,
    sp.code   AS provider_code,
    sp.name   AS provider_name,
    ROW_NUMBER() OVER (
      PARTITION BY o.station_id, date_trunc('hour', o.observed_at)
      ORDER BY
        -- ưu tiên WAQI (dữ liệu trạm thực) rồi Open-Meteo (mô hình)
        CASE sp.code WHEN 'waqi' THEN 1 ELSE 2 END,
        o.fetched_at DESC NULLS LAST
    ) AS rn
  FROM core.air_quality_observations o
  JOIN ingest.source_providers sp ON sp.id = o.source_provider_id
)
SELECT
  id, station_id, source_provider_id, source_endpoint_id,
  pipeline_run_id, raw_payload_id, normalize_run_id,
  observed_at, aqi, pm25, pm10, o3, no2, so2, co,
  european_aqi, ammonia, dust, aerosol_optical_depth, uv_index,
  lineage, fetched_at, created_at,
  provider_code, provider_name
FROM ranked
WHERE rn = 1;

-- 5) View so sánh nguồn: cho mỗi (station, hour) lấy giá trị từ mỗi provider
CREATE OR REPLACE VIEW core.v_aq_source_compare AS
SELECT
  o.station_id,
  s.name   AS station_name,
  date_trunc('hour', o.observed_at) AS hour,
  sp.code  AS provider_code,
  o.aqi,
  o.pm25,
  o.pm10,
  o.o3,
  o.no2,
  o.so2,
  o.co,
  o.fetched_at
FROM core.air_quality_observations o
JOIN ingest.source_providers sp ON sp.id = o.source_provider_id
JOIN catalog.stations s ON s.id = o.station_id
ORDER BY o.station_id, hour DESC, sp.code;

-- 6) Bind WAQI endpoint cho tất cả stations hiện tại
--    (ingest service cũng tự ensure bindings, nhưng seed trước cho tiện)
INSERT INTO ingest.station_source_bindings (station_id, source_provider_id, source_endpoint_id, is_enabled, priority, valid_from, config)
SELECT
  st.id,
  'a0000000-0000-0000-0000-000000000002',
  'b0000000-0000-0000-0000-000000000003',
  TRUE,
  200,  -- thấp hơn Open-Meteo (100) vì WAQI rate-limited
  now(),
  '{}'::jsonb
FROM catalog.stations st
WHERE st.is_active = TRUE
ON CONFLICT (station_id, source_endpoint_id) DO NOTHING;
