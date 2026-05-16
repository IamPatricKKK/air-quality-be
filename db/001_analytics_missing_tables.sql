-- Bảng analytics còn thiếu (seasonal/correlation/trend/health_impact).
-- Tương đương app/models/ensure.py (chạy tự động lúc be startup). File này
-- để áp dụng THỦ CÔNG khi không muốn restart be:
--   docker exec -i <pg> psql -U postgres -d sky_pulse < db/001_analytics_missing_tables.sql
-- Idempotent: dùng IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS analytics.correlation_matrices (
  id UUID DEFAULT gen_random_uuid() NOT NULL,
  station_id UUID NOT NULL,
  analysis_date DATE NOT NULL,
  period_days INTEGER NOT NULL,
  correlations JSONB NOT NULL,
  sample_size INTEGER,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  CONSTRAINT pk_correlation_matrices PRIMARY KEY (id),
  CONSTRAINT uq_correlation_matrices_unique UNIQUE (station_id, analysis_date),
  CONSTRAINT fk_correlation_matrices_station_id_stations
    FOREIGN KEY (station_id) REFERENCES catalog.stations (id)
);

CREATE TABLE IF NOT EXISTS analytics.health_impacts (
  id UUID DEFAULT gen_random_uuid() NOT NULL,
  station_id UUID NOT NULL,
  analysis_time TIMESTAMPTZ NOT NULL,
  period_hours INTEGER DEFAULT 48 NOT NULL,
  current_aqi NUMERIC(8, 2),
  avg_aqi NUMERIC(8, 2),
  max_aqi NUMERIC(8, 2),
  current_level VARCHAR(50),
  avg_level VARCHAR(50),
  risk_level VARCHAR(50),
  exposure_score NUMERIC(5, 1) NOT NULL,
  dominant_pollutant VARCHAR(50),
  time_in_levels JSONB,
  advice_vi VARCHAR(1000),
  advice_en VARCHAR(1000),
  pollutant_averages JSONB,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  CONSTRAINT pk_health_impacts PRIMARY KEY (id),
  CONSTRAINT uq_health_impacts_station_id UNIQUE (station_id),
  CONSTRAINT fk_health_impacts_station_id_stations
    FOREIGN KEY (station_id) REFERENCES catalog.stations (id)
);

CREATE TABLE IF NOT EXISTS analytics.seasonal_patterns (
  id UUID DEFAULT gen_random_uuid() NOT NULL,
  station_id UUID NOT NULL,
  metric VARCHAR(50) DEFAULT 'aqi' NOT NULL,
  analysis_date DATE NOT NULL,
  period_days INTEGER DEFAULT 30 NOT NULL,
  hourly_profile JSONB,
  daily_profile JSONB,
  peak_hours INTEGER[],
  off_peak_hours INTEGER[],
  best_dow INTEGER,
  worst_dow INTEGER,
  overall_avg NUMERIC(8, 2) NOT NULL,
  hourly_variation NUMERIC(8, 2) NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  CONSTRAINT pk_seasonal_patterns PRIMARY KEY (id),
  CONSTRAINT uq_seasonal_patterns_unique UNIQUE (station_id, metric, analysis_date),
  CONSTRAINT fk_seasonal_patterns_station_id_stations
    FOREIGN KEY (station_id) REFERENCES catalog.stations (id)
);

CREATE TABLE IF NOT EXISTS analytics.trend_analyses (
  id UUID DEFAULT gen_random_uuid() NOT NULL,
  station_id UUID NOT NULL,
  analysis_date DATE NOT NULL,
  period_days INTEGER NOT NULL,
  trends JSONB NOT NULL,
  overall_direction VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  CONSTRAINT pk_trend_analyses PRIMARY KEY (id),
  CONSTRAINT uq_trend_analyses_unique UNIQUE (station_id, analysis_date),
  CONSTRAINT fk_trend_analyses_station_id_stations
    FOREIGN KEY (station_id) REFERENCES catalog.stations (id)
);
