-- ============================================================
-- Migration 006: Advanced analytics tables
-- Seasonal patterns, correlation matrices, trend analyses,
-- health impact scoring.
-- ============================================================

-- 1) Seasonal patterns — hourly/daily profiles
CREATE TABLE IF NOT EXISTS analytics.seasonal_patterns (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id       UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  metric           TEXT NOT NULL DEFAULT 'aqi',
  analysis_date    DATE NOT NULL DEFAULT CURRENT_DATE,
  period_days      INT NOT NULL DEFAULT 30,
  hourly_profile   JSONB,           -- [{hour, avg, std, min, max, samples}, ...]
  daily_profile    JSONB,           -- [{dow, avg, std, samples}, ...]
  peak_hours       INT[],           -- top 3 giờ cao nhất
  off_peak_hours   INT[],           -- top 3 giờ thấp nhất
  best_dow         INT,             -- day of week tốt nhất (0=Sun)
  worst_dow        INT,             -- day of week xấu nhất
  overall_avg      NUMERIC(8,2),
  hourly_variation NUMERIC(8,2),    -- std of hourly averages
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (station_id, metric, analysis_date)
);

CREATE INDEX IF NOT EXISTS idx_seasonal_station_date
  ON analytics.seasonal_patterns(station_id, analysis_date DESC);

-- 2) Correlation matrices — hệ số tương quan giữa metrics
CREATE TABLE IF NOT EXISTS analytics.correlation_matrices (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id     UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  analysis_date  DATE NOT NULL DEFAULT CURRENT_DATE,
  period_days    INT NOT NULL DEFAULT 30,
  correlations   JSONB NOT NULL,    -- [{metric_a, metric_b, correlation, category}, ...]
  sample_size    INT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (station_id, analysis_date)
);

CREATE INDEX IF NOT EXISTS idx_correlation_station_date
  ON analytics.correlation_matrices(station_id, analysis_date DESC);

-- 3) Trend analyses — xu hướng dài hạn
CREATE TABLE IF NOT EXISTS analytics.trend_analyses (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id        UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  analysis_date     DATE NOT NULL DEFAULT CURRENT_DATE,
  period_days       INT NOT NULL DEFAULT 30,
  trends            JSONB NOT NULL,  -- {metric: {slope, r_squared, pct_change, direction, ...}}
  overall_direction TEXT,            -- improving | stable | worsening
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (station_id, analysis_date)
);

CREATE INDEX IF NOT EXISTS idx_trend_station_date
  ON analytics.trend_analyses(station_id, analysis_date DESC);

-- 4) Health impacts — tác động sức khỏe realtime
CREATE TABLE IF NOT EXISTS analytics.health_impacts (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id         UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  analysis_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
  period_hours       INT NOT NULL DEFAULT 48,
  current_aqi        NUMERIC(8,2),
  avg_aqi            NUMERIC(8,2),
  max_aqi            NUMERIC(8,2),
  current_level      TEXT,           -- good | moderate | unhealthy_sensitive | ...
  avg_level          TEXT,
  risk_level         TEXT,           -- low | moderate | high | very_high | critical
  exposure_score     NUMERIC(5,1),   -- 0-100
  dominant_pollutant TEXT,           -- pm25 | o3 | ...
  time_in_levels     JSONB,          -- {good: N, moderate: N, ...}
  advice_vi          TEXT,
  advice_en          TEXT,
  pollutant_averages JSONB,          -- {pm25: x, pm10: y, ...}
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (station_id)                -- chỉ giữ record mới nhất per station
);

CREATE INDEX IF NOT EXISTS idx_health_impact_station
  ON analytics.health_impacts(station_id);
