-- ============================================================
-- Migration 002: Mở rộng cột observations + thêm các trạm đô thị lớn VN
-- Áp dụng trước khi bật ingest mới ở air-quality-api.
-- ============================================================

-- Thêm các trường nâng cao cho air quality
ALTER TABLE core.air_quality_observations
  ADD COLUMN IF NOT EXISTS european_aqi INTEGER,
  ADD COLUMN IF NOT EXISTS uv_index     DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS ammonia      DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS dust         DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS aerosol_optical_depth DOUBLE PRECISION;

-- Thêm cho weather
ALTER TABLE core.weather_observations
  ADD COLUMN IF NOT EXISTS wind_gusts_mps        DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS apparent_temperature_c DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS dew_point_c           DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS rain_mm               DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS surface_pressure_hpa  DOUBLE PRECISION;

-- Mở rộng areas
INSERT INTO catalog.areas (id, code, name, region, created_at, updated_at)
VALUES
  ('20000000-0000-0000-0000-000000000004', 'HP',      'Hai Phong',       'north',  now(), now()),
  ('20000000-0000-0000-0000-000000000005', 'CT',      'Can Tho',         'south',  now(), now()),
  ('20000000-0000-0000-0000-000000000006', 'KH',      'Khanh Hoa',       'central', now(), now()),
  ('20000000-0000-0000-0000-000000000007', 'HUE',     'Thua Thien Hue',  'central', now(), now()),
  ('20000000-0000-0000-0000-000000000008', 'BRVT',    'Ba Ria Vung Tau', 'south',  now(), now()),
  ('20000000-0000-0000-0000-000000000009', 'DNI',     'Dong Nai',        'south',  now(), now()),
  ('20000000-0000-0000-0000-00000000000a', 'DL',      'Lam Dong',        'central', now(), now()),
  ('20000000-0000-0000-0000-00000000000b', 'BD',      'Binh Dinh',       'central', now(), now()),
  ('20000000-0000-0000-0000-00000000000c', 'NA',      'Nghe An',         'central', now(), now()),
  ('20000000-0000-0000-0000-00000000000d', 'QN',      'Quang Ninh',      'north',  now(), now()),
  ('20000000-0000-0000-0000-00000000000e', 'TN',      'Thai Nguyen',     'north',  now(), now()),
  ('20000000-0000-0000-0000-00000000000f', 'DAKLAK',  'Dak Lak',         'central', now(), now())
ON CONFLICT (code) DO NOTHING;

-- Mở rộng stations cho các đô thị lớn VN
INSERT INTO catalog.stations
  (id, code, name, area_id, address, lat, lng, elevation_m, station_type, timezone, is_active, metadata, created_at, updated_at)
VALUES
  ('30000000-0000-0000-0000-000000000004', 'HP-CENTER',  'Hai Phong - Le Chan',       '20000000-0000-0000-0000-000000000004', 'Le Chan, Hai Phong',            20.8449, 106.6881, 7,  'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-000000000005', 'CT-NK',      'Can Tho - Ninh Kieu',       '20000000-0000-0000-0000-000000000005', 'Ninh Kieu, Can Tho',             10.0452, 105.7469, 3,  'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-000000000006', 'NT-CENTER',  'Nha Trang - Center',        '20000000-0000-0000-0000-000000000006', 'Nha Trang, Khanh Hoa',           12.2388, 109.1967, 4,  'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-000000000007', 'HUE-CENTER', 'Hue - Citadel',             '20000000-0000-0000-0000-000000000007', 'Hue, Thua Thien Hue',            16.4637, 107.5909, 7,  'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-000000000008', 'VT-CENTER',  'Vung Tau - Center',         '20000000-0000-0000-0000-000000000008', 'Vung Tau, Ba Ria - Vung Tau',    10.3460, 107.0843, 5,  'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-000000000009', 'BH-CENTER',  'Bien Hoa - Center',         '20000000-0000-0000-0000-000000000009', 'Bien Hoa, Dong Nai',             10.9574, 106.8426, 10, 'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-00000000000a', 'DL-CENTER',  'Da Lat - Center',           '20000000-0000-0000-0000-00000000000a', 'Da Lat, Lam Dong',               11.9404, 108.4583, 1500,'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-00000000000b', 'QN-CENTER',  'Quy Nhon - Center',         '20000000-0000-0000-0000-00000000000b', 'Quy Nhon, Binh Dinh',            13.7829, 109.2196, 4,  'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-00000000000c', 'VINH-CENTER','Vinh - Center',             '20000000-0000-0000-0000-00000000000c', 'Vinh, Nghe An',                  18.6796, 105.6814, 5,  'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-00000000000d', 'HL-CENTER',  'Ha Long - Center',          '20000000-0000-0000-0000-00000000000d', 'Ha Long, Quang Ninh',            20.9593, 107.0759, 5,  'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-00000000000e', 'TN-CENTER',  'Thai Nguyen - Center',      '20000000-0000-0000-0000-00000000000e', 'Thai Nguyen',                    21.5942, 105.8480, 35, 'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now()),
  ('30000000-0000-0000-0000-00000000000f', 'BMT-CENTER', 'Buon Ma Thuot - Center',    '20000000-0000-0000-0000-00000000000f', 'Buon Ma Thuot, Dak Lak',         12.6797, 108.0377, 536,'monitoring', 'Asia/Ho_Chi_Minh', TRUE, '{"source":"open-meteo"}'::jsonb, now(), now())
ON CONFLICT (code) DO NOTHING;

-- Bind các trạm mới với provider Open-Meteo (endpoint sẽ được ingest tự đảm bảo)
-- Lưu ý: air-quality-api (khi chạy ingest) sẽ tự tạo provider/endpoints/bindings nếu chưa có.
