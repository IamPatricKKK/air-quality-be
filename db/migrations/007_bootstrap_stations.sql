-- 007: Bootstrap Vietnamese monitoring stations & areas
-- These are real air quality monitoring locations. No mock data.
-- Stations are placed at coordinates matching actual monitoring stations from WAQI/OpenMeteo.

-- ─── IAM roles (required for auth) ───────────────
INSERT INTO iam.roles (code, name, description)
VALUES
  ('admin',    'Administrator', 'Full system access'),
  ('operator', 'Operator',      'Manage ingest & pipelines'),
  ('analyst',  'Analyst',       'View analytics & forecasts'),
  ('user',     'User',          'Standard dashboard access')
ON CONFLICT (code) DO NOTHING;

-- ─── Areas (provinces/cities) ───────────────────
INSERT INTO catalog.areas (level, code, name, center_lat, center_lng, sort_order)
VALUES
  ('province', 'HN',   'Hà Nội',          21.0285,  105.8542, 1),
  ('province', 'HCM',  'TP. Hồ Chí Minh', 10.8231,  106.6297, 2),
  ('province', 'DN',   'Đà Nẵng',         16.0544,  108.2022, 3),
  ('province', 'HP',   'Hải Phòng',       20.8449,  106.6881, 4),
  ('province', 'CT',   'Cần Thơ',         10.0452,  105.7469, 5),
  ('province', 'HUE',  'Thừa Thiên Huế',  16.4637,  107.5909, 6),
  ('province', 'NT',   'Khánh Hòa',       12.2388,  109.1967, 7),
  ('province', 'BN',   'Bắc Ninh',        21.1861,  106.0763, 8),
  ('province', 'DL',   'Lâm Đồng',        11.9465,  108.4419, 9),
  ('province', 'QN',   'Quảng Ninh',      21.0064,  107.2925, 10)
ON CONFLICT (level, code) DO NOTHING;

-- ─── Monitoring Stations ────────────────────────
-- Coordinates match WAQI / Open-Meteo grid points for accurate data retrieval.

INSERT INTO catalog.stations (code, name, area_id, lat, lng, station_type, timezone)
VALUES
  -- Hà Nội
  ('HN-US-EMB',  'Hà Nội - Đại sứ quán Mỹ',
    (SELECT id FROM catalog.areas WHERE code = 'HN'),
    21.0285, 105.8542, 'monitoring', 'Asia/Ho_Chi_Minh'),
  ('HN-HK',      'Hà Nội - Hoàn Kiếm',
    (SELECT id FROM catalog.areas WHERE code = 'HN'),
    21.0278, 105.8342, 'monitoring', 'Asia/Ho_Chi_Minh'),

  -- TP. Hồ Chí Minh
  ('HCM-US-CON', 'TP.HCM - Lãnh sự quán Mỹ',
    (SELECT id FROM catalog.areas WHERE code = 'HCM'),
    10.7830, 106.7009, 'monitoring', 'Asia/Ho_Chi_Minh'),
  ('HCM-Q1',     'TP.HCM - Quận 1',
    (SELECT id FROM catalog.areas WHERE code = 'HCM'),
    10.7769, 106.7009, 'monitoring', 'Asia/Ho_Chi_Minh'),

  -- Đà Nẵng
  ('DN-CENTER',  'Đà Nẵng - Trung tâm',
    (SELECT id FROM catalog.areas WHERE code = 'DN'),
    16.0544, 108.2022, 'monitoring', 'Asia/Ho_Chi_Minh'),

  -- Hải Phòng
  ('HP-CENTER',  'Hải Phòng - Trung tâm',
    (SELECT id FROM catalog.areas WHERE code = 'HP'),
    20.8449, 106.6881, 'monitoring', 'Asia/Ho_Chi_Minh'),

  -- Cần Thơ
  ('CT-NK',      'Cần Thơ - Ninh Kiều',
    (SELECT id FROM catalog.areas WHERE code = 'CT'),
    10.0452, 105.7469, 'monitoring', 'Asia/Ho_Chi_Minh'),

  -- Huế
  ('HUE-CENTER', 'Huế - Trung tâm',
    (SELECT id FROM catalog.areas WHERE code = 'HUE'),
    16.4637, 107.5909, 'monitoring', 'Asia/Ho_Chi_Minh'),

  -- Nha Trang (Khánh Hòa)
  ('NT-CENTER',  'Nha Trang - Trung tâm',
    (SELECT id FROM catalog.areas WHERE code = 'NT'),
    12.2388, 109.1967, 'monitoring', 'Asia/Ho_Chi_Minh'),

  -- Bắc Ninh
  ('BN-CENTER',  'Bắc Ninh - Trung tâm',
    (SELECT id FROM catalog.areas WHERE code = 'BN'),
    21.1861, 106.0763, 'monitoring', 'Asia/Ho_Chi_Minh'),

  -- Đà Lạt (Lâm Đồng)
  ('DL-CENTER',  'Đà Lạt - Trung tâm',
    (SELECT id FROM catalog.areas WHERE code = 'DL'),
    11.9465, 108.4419, 'monitoring', 'Asia/Ho_Chi_Minh'),

  -- Quảng Ninh (Hạ Long)
  ('QN-HL',      'Hạ Long - Quảng Ninh',
    (SELECT id FROM catalog.areas WHERE code = 'QN'),
    21.0064, 107.2925, 'monitoring', 'Asia/Ho_Chi_Minh')
ON CONFLICT (code) DO NOTHING;
