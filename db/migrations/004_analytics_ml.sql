-- ============================================================
-- Migration 004: Analytics & ML persistence tables
-- Dùng bởi air-quality-be (Python) cho daily summary, anomaly,
-- Prophet forecast, model evaluation.
-- ============================================================

-- 1) Daily summaries — thống kê ngày cho mỗi station
CREATE TABLE IF NOT EXISTS analytics.daily_summaries (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id    UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  summary_date  DATE NOT NULL,
  samples       INT NOT NULL DEFAULT 0,
  aqi_avg       NUMERIC(8,2),
  aqi_min       NUMERIC(8,2),
  aqi_max       NUMERIC(8,2),
  aqi_stddev    NUMERIC(8,2),
  pm25_avg      NUMERIC(8,2),
  pm10_avg      NUMERIC(8,2),
  o3_avg        NUMERIC(8,2),
  no2_avg       NUMERIC(8,2),
  so2_avg       NUMERIC(8,2),
  co_avg        NUMERIC(8,2),
  temp_avg      NUMERIC(6,2),
  humidity_avg  NUMERIC(6,2),
  wind_avg      NUMERIC(6,2),
  category      TEXT,            -- dominant AQI category of the day
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (station_id, summary_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_summaries_station_date
  ON analytics.daily_summaries(station_id, summary_date DESC);

-- 2) Anomalies — phát hiện dị thường
CREATE TABLE IF NOT EXISTS analytics.anomalies (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id    UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  metric        TEXT NOT NULL,          -- aqi | pm25 | pm10 ...
  detected_at   TIMESTAMPTZ NOT NULL,
  value         NUMERIC NOT NULL,
  z_score       NUMERIC(8,3),
  iqr_factor    NUMERIC(8,3),
  method        TEXT NOT NULL DEFAULT 'zscore',  -- zscore | iqr
  severity      TEXT NOT NULL DEFAULT 'warning', -- info | warning | critical
  description   TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomalies_station
  ON analytics.anomalies(station_id, detected_at DESC);

-- 3) Forecast runs — mỗi lần Prophet/ARIMA chạy
CREATE TABLE IF NOT EXISTS forecast.forecast_runs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id    UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  model_type    TEXT NOT NULL DEFAULT 'prophet',  -- prophet | arima | linear
  target_metric TEXT NOT NULL DEFAULT 'aqi',
  horizon_hours INT NOT NULL DEFAULT 24,
  mae           NUMERIC(8,3),
  rmse          NUMERIC(8,3),
  mape          NUMERIC(8,3),
  training_rows INT,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  status        TEXT NOT NULL DEFAULT 'running',  -- running | success | failed
  error_message TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_forecast_runs_station
  ON forecast.forecast_runs(station_id, created_at DESC);

-- 4) Forecast points — các điểm dự báo cụ thể
CREATE TABLE IF NOT EXISTS forecast.forecast_points (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  forecast_run_id UUID NOT NULL REFERENCES forecast.forecast_runs(id) ON DELETE CASCADE,
  station_id      UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  target_metric   TEXT NOT NULL,
  predicted_at    TIMESTAMPTZ NOT NULL,   -- thời điểm dự báo cho
  predicted_value NUMERIC(8,2) NOT NULL,
  lower_bound     NUMERIC(8,2),           -- confidence interval
  upper_bound     NUMERIC(8,2),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_forecast_points_run
  ON forecast.forecast_points(forecast_run_id);
CREATE INDEX IF NOT EXISTS idx_forecast_points_station
  ON forecast.forecast_points(station_id, target_metric, predicted_at DESC);
