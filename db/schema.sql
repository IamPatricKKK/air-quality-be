-- ============================================================
-- Sky Pulse Monitor - PostgreSQL Base Schema
-- Target architecture: 4 repos / 2 FE / 2 BE
-- Schemas: iam, catalog, app, ingest, core, analytics, forecast, ops
-- ============================================================

-- ============================================================
-- EXTENSIONS
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- SCHEMAS
-- ============================================================

CREATE SCHEMA IF NOT EXISTS iam;
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS ingest;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS forecast;
CREATE SCHEMA IF NOT EXISTS ops;

-- ============================================================
-- ENUMS
-- ============================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_status_enum') THEN
    CREATE TYPE public.user_status_enum AS ENUM ('active', 'invited', 'disabled');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'area_level_enum') THEN
    CREATE TYPE public.area_level_enum AS ENUM ('province', 'district', 'ward');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'station_type_enum') THEN
    CREATE TYPE public.station_type_enum AS ENUM ('monitoring', 'reference', 'virtual');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'endpoint_kind_enum') THEN
    CREATE TYPE public.endpoint_kind_enum AS ENUM ('air_quality', 'weather', 'traffic', 'mixed');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'run_status_enum') THEN
    CREATE TYPE public.run_status_enum AS ENUM ('queued', 'running', 'success', 'partial', 'failed', 'cancelled');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'request_status_enum') THEN
    CREATE TYPE public.request_status_enum AS ENUM ('success', 'failed', 'throttled', 'timeout', 'skipped');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payload_format_enum') THEN
    CREATE TYPE public.payload_format_enum AS ENUM ('json', 'xml', 'csv', 'text');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'quality_status_enum') THEN
    CREATE TYPE public.quality_status_enum AS ENUM ('valid', 'suspect', 'invalid', 'estimated');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'analysis_type_enum') THEN
    CREATE TYPE public.analysis_type_enum AS ENUM ('daily_summary', 'trend', 'anomaly', 'correlation', 'root_cause', 'forecast_review');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'model_status_enum') THEN
    CREATE TYPE public.model_status_enum AS ENUM ('draft', 'training', 'validated', 'production', 'archived');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'prediction_target_enum') THEN
    CREATE TYPE public.prediction_target_enum AS ENUM ('aqi', 'pm25', 'pm10', 'o3', 'no2', 'so2', 'co');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notification_channel_enum') THEN
    CREATE TYPE public.notification_channel_enum AS ENUM ('in_app', 'email', 'push', 'sms');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'service_name_enum') THEN
    CREATE TYPE public.service_name_enum AS ENUM ('be_api', 'be_data', 'fe_admin', 'scheduler', 'system');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'actor_type_enum') THEN
    CREATE TYPE public.actor_type_enum AS ENUM ('user', 'service', 'system');
  END IF;
END$$;

-- ============================================================
-- COMMON FUNCTIONS
-- ============================================================

CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- IAM
-- ============================================================

CREATE TABLE iam.users (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email           CITEXT NOT NULL UNIQUE,
  password_hash   TEXT NOT NULL,
  status          public.user_status_enum NOT NULL DEFAULT 'active',
  last_login_at   TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE iam.roles (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code            TEXT NOT NULL UNIQUE,
  name            TEXT NOT NULL,
  description     TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE iam.user_profiles (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL UNIQUE REFERENCES iam.users(id) ON DELETE CASCADE,
  display_name    TEXT,
  avatar_url      TEXT,
  phone           TEXT,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE iam.user_roles (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
  role_id         UUID NOT NULL REFERENCES iam.roles(id) ON DELETE CASCADE,
  assigned_by     UUID REFERENCES iam.users(id) ON DELETE SET NULL,
  assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, role_id)
);

CREATE TABLE iam.refresh_sessions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
  refresh_token_hash  TEXT NOT NULL UNIQUE,
  ip_address          INET,
  user_agent          TEXT,
  expires_at          TIMESTAMPTZ NOT NULL,
  revoked_at          TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_iam_user_roles_user_id ON iam.user_roles (user_id);
CREATE INDEX idx_iam_refresh_sessions_user_id ON iam.refresh_sessions (user_id, created_at DESC);

CREATE TRIGGER trg_iam_users_updated_at
BEFORE UPDATE ON iam.users
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TRIGGER trg_iam_user_profiles_updated_at
BEFORE UPDATE ON iam.user_profiles
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- ============================================================
-- CATALOG
-- ============================================================

CREATE TABLE catalog.areas (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id       UUID REFERENCES catalog.areas(id) ON DELETE SET NULL,
  level           public.area_level_enum NOT NULL,
  code            TEXT NOT NULL,
  name            TEXT NOT NULL,
  sort_order      INTEGER NOT NULL DEFAULT 0,
  center_lat      DOUBLE PRECISION,
  center_lng      DOUBLE PRECISION,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (level, code)
);

CREATE TABLE catalog.stations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code            TEXT NOT NULL UNIQUE,
  name            TEXT NOT NULL,
  area_id         UUID REFERENCES catalog.areas(id) ON DELETE SET NULL,
  address         TEXT,
  lat             DOUBLE PRECISION NOT NULL,
  lng             DOUBLE PRECISION NOT NULL,
  elevation_m     DOUBLE PRECISION,
  station_type    public.station_type_enum NOT NULL DEFAULT 'monitoring',
  timezone        TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
  is_active       BOOLEAN NOT NULL DEFAULT true,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_catalog_stations_area_id ON catalog.stations (area_id);
CREATE INDEX idx_catalog_stations_active ON catalog.stations (is_active);
CREATE INDEX idx_catalog_stations_point ON catalog.stations USING GIST (point(lng, lat));

CREATE TRIGGER trg_catalog_areas_updated_at
BEFORE UPDATE ON catalog.areas
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TRIGGER trg_catalog_stations_updated_at
BEFORE UPDATE ON catalog.stations
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- ============================================================
-- APP
-- ============================================================

CREATE TABLE app.user_pinned_stations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
  station_id      UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  sort_order      INTEGER NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, station_id)
);

CREATE TABLE app.user_preferences (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL UNIQUE REFERENCES iam.users(id) ON DELETE CASCADE,
  notification_mode TEXT NOT NULL DEFAULT 'all',
  favorite_regions  TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  push_enabled      BOOLEAN NOT NULL DEFAULT true,
  email_enabled     BOOLEAN NOT NULL DEFAULT true,
  daily_report_enabled BOOLEAN NOT NULL DEFAULT true,
  location_lat      DOUBLE PRECISION,
  location_lng      DOUBLE PRECISION,
  metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (location_lat IS NULL OR (location_lat BETWEEN -90 AND 90)),
  CHECK (location_lng IS NULL OR (location_lng BETWEEN -180 AND 180))
);

CREATE TABLE app.user_alert_rules (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
  station_id      UUID REFERENCES catalog.stations(id) ON DELETE CASCADE,
  metric_code     TEXT NOT NULL,
  operator        TEXT NOT NULL DEFAULT '>=',
  threshold_value DOUBLE PRECISION NOT NULL,
  channels        public.notification_channel_enum[] NOT NULL DEFAULT ARRAY['in_app', 'email']::public.notification_channel_enum[],
  cooldown_minutes INTEGER NOT NULL DEFAULT 60,
  is_active       BOOLEAN NOT NULL DEFAULT true,
  context         JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_triggered_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app.notification_templates (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code            TEXT NOT NULL UNIQUE,
  name            TEXT NOT NULL,
  title_template  TEXT NOT NULL,
  body_template   TEXT NOT NULL,
  channels        public.notification_channel_enum[] NOT NULL DEFAULT ARRAY['in_app']::public.notification_channel_enum[],
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active       BOOLEAN NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app.notifications (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
  template_id     UUID REFERENCES app.notification_templates(id) ON DELETE SET NULL,
  station_id      UUID REFERENCES catalog.stations(id) ON DELETE SET NULL,
  category        TEXT NOT NULL DEFAULT 'system',
  title           TEXT NOT NULL,
  body            TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending',
  source_context  JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at         TIMESTAMPTZ,
  read_at         TIMESTAMPTZ
);

CREATE TABLE app.notification_deliveries (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  notification_id   UUID NOT NULL REFERENCES app.notifications(id) ON DELETE CASCADE,
  channel           public.notification_channel_enum NOT NULL,
  delivery_status   public.request_status_enum NOT NULL,
  provider_response JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_attempt_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered_at      TIMESTAMPTZ,
  UNIQUE (notification_id, channel)
);

CREATE INDEX idx_app_pinned_user_id ON app.user_pinned_stations (user_id, sort_order);
CREATE INDEX idx_app_user_preferences_user_id ON app.user_preferences (user_id);
CREATE INDEX idx_app_alert_rules_user_id ON app.user_alert_rules (user_id, is_active);
CREATE INDEX idx_app_notifications_user_id ON app.notifications (user_id, created_at DESC);

CREATE TRIGGER trg_app_user_preferences_updated_at
BEFORE UPDATE ON app.user_preferences
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TRIGGER trg_app_user_alert_rules_updated_at
BEFORE UPDATE ON app.user_alert_rules
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TRIGGER trg_app_notification_templates_updated_at
BEFORE UPDATE ON app.notification_templates
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- ============================================================
-- INGEST
-- ============================================================

CREATE TABLE ingest.source_providers (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code                  TEXT NOT NULL UNIQUE,
  name                  TEXT NOT NULL,
  category              TEXT NOT NULL,
  base_url              TEXT NOT NULL,
  auth_type             TEXT,
  rate_limit_per_minute INTEGER,
  timeout_seconds       INTEGER NOT NULL DEFAULT 30,
  is_active             BOOLEAN NOT NULL DEFAULT true,
  config                JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ingest.source_endpoints (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_id           UUID NOT NULL REFERENCES ingest.source_providers(id) ON DELETE CASCADE,
  code                  TEXT NOT NULL UNIQUE,
  name                  TEXT NOT NULL,
  kind                  public.endpoint_kind_enum NOT NULL,
  http_method           TEXT NOT NULL DEFAULT 'GET',
  path                  TEXT NOT NULL,
  schedule_expression   TEXT,
  schedule_timezone     TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
  parser_key            TEXT,
  is_active             BOOLEAN NOT NULL DEFAULT true,
  config                JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ingest.station_source_bindings (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id            UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  endpoint_id           UUID NOT NULL REFERENCES ingest.source_endpoints(id) ON DELETE CASCADE,
  external_object_id    TEXT NOT NULL,
  priority              SMALLINT NOT NULL DEFAULT 100,
  is_enabled            BOOLEAN NOT NULL DEFAULT true,
  config                JSONB NOT NULL DEFAULT '{}'::jsonb,
  valid_from            TIMESTAMPTZ,
  valid_to              TIMESTAMPTZ,
  updated_by_user_id    UUID REFERENCES iam.users(id) ON DELETE SET NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (station_id, endpoint_id)
);

CREATE TABLE ingest.pipeline_definitions (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code                  TEXT NOT NULL UNIQUE,
  name                  TEXT NOT NULL,
  pipeline_type         TEXT NOT NULL,
  owner_service         public.service_name_enum NOT NULL DEFAULT 'be_data',
  schedule_expression   TEXT,
  schedule_timezone     TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
  is_active             BOOLEAN NOT NULL DEFAULT true,
  config                JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ingest.pipeline_runs (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_definition_id UUID NOT NULL REFERENCES ingest.pipeline_definitions(id) ON DELETE CASCADE,
  source_endpoint_id    UUID REFERENCES ingest.source_endpoints(id) ON DELETE SET NULL,
  requested_by_user_id  UUID REFERENCES iam.users(id) ON DELETE SET NULL,
  trigger_type          TEXT NOT NULL DEFAULT 'scheduled',
  scope_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
  status                public.run_status_enum NOT NULL DEFAULT 'queued',
  input_window_from     TIMESTAMPTZ,
  input_window_to       TIMESTAMPTZ,
  metrics               JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_summary         TEXT,
  started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at           TIMESTAMPTZ,
  correlation_id        TEXT
);

CREATE TABLE ingest.outbound_requests (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_run_id       UUID NOT NULL REFERENCES ingest.pipeline_runs(id) ON DELETE CASCADE,
  source_provider_id    UUID NOT NULL REFERENCES ingest.source_providers(id) ON DELETE CASCADE,
  source_endpoint_id    UUID NOT NULL REFERENCES ingest.source_endpoints(id) ON DELETE CASCADE,
  station_id            UUID REFERENCES catalog.stations(id) ON DELETE SET NULL,
  request_url           TEXT NOT NULL,
  request_method        TEXT NOT NULL DEFAULT 'GET',
  request_params        JSONB NOT NULL DEFAULT '{}'::jsonb,
  http_status           INTEGER,
  status                public.request_status_enum,
  retry_count           INTEGER NOT NULL DEFAULT 0,
  request_started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  response_received_at  TIMESTAMPTZ,
  latency_ms            INTEGER,
  response_size_bytes   INTEGER,
  error_message         TEXT,
  correlation_id        TEXT
);

CREATE TABLE ingest.raw_payloads (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_run_id       UUID NOT NULL REFERENCES ingest.pipeline_runs(id) ON DELETE CASCADE,
  outbound_request_id   UUID REFERENCES ingest.outbound_requests(id) ON DELETE SET NULL,
  source_provider_id    UUID NOT NULL REFERENCES ingest.source_providers(id) ON DELETE CASCADE,
  source_endpoint_id    UUID NOT NULL REFERENCES ingest.source_endpoints(id) ON DELETE CASCADE,
  station_id            UUID REFERENCES catalog.stations(id) ON DELETE SET NULL,
  payload_format        public.payload_format_enum NOT NULL DEFAULT 'json',
  payload_hash          TEXT NOT NULL,
  payload_json          JSONB,
  payload_text          TEXT,
  storage_uri           TEXT,
  observed_at           TIMESTAMPTZ,
  fetched_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (source_provider_id, payload_hash),
  CHECK (
    payload_json IS NOT NULL
    OR payload_text IS NOT NULL
    OR storage_uri IS NOT NULL
  )
);

CREATE TABLE ingest.normalize_runs (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_run_id       UUID NOT NULL REFERENCES ingest.pipeline_runs(id) ON DELETE CASCADE,
  raw_payload_id        UUID NOT NULL REFERENCES ingest.raw_payloads(id) ON DELETE CASCADE,
  parser_key            TEXT,
  parser_version        TEXT,
  status                public.run_status_enum NOT NULL DEFAULT 'queued',
  records_in            INTEGER NOT NULL DEFAULT 0,
  records_out           INTEGER NOT NULL DEFAULT 0,
  warnings              JSONB NOT NULL DEFAULT '[]'::jsonb,
  error_message         TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ingest_source_endpoints_provider_id ON ingest.source_endpoints (provider_id, is_active);
CREATE INDEX idx_ingest_station_bindings_station_id ON ingest.station_source_bindings (station_id, is_enabled);
CREATE INDEX idx_ingest_pipeline_runs_status ON ingest.pipeline_runs (status, started_at DESC);
CREATE INDEX idx_ingest_pipeline_runs_definition ON ingest.pipeline_runs (pipeline_definition_id, started_at DESC);
CREATE INDEX idx_ingest_outbound_requests_run_id ON ingest.outbound_requests (pipeline_run_id, request_started_at DESC);
CREATE INDEX idx_ingest_raw_payloads_run_id ON ingest.raw_payloads (pipeline_run_id, fetched_at DESC);
CREATE INDEX idx_ingest_normalize_runs_run_id ON ingest.normalize_runs (pipeline_run_id, created_at DESC);

CREATE TRIGGER trg_ingest_source_providers_updated_at
BEFORE UPDATE ON ingest.source_providers
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TRIGGER trg_ingest_source_endpoints_updated_at
BEFORE UPDATE ON ingest.source_endpoints
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TRIGGER trg_ingest_station_source_bindings_updated_at
BEFORE UPDATE ON ingest.station_source_bindings
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TRIGGER trg_ingest_pipeline_definitions_updated_at
BEFORE UPDATE ON ingest.pipeline_definitions
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- ============================================================
-- CORE
-- ============================================================

CREATE TABLE core.air_quality_observations (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id            UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  source_provider_id    UUID NOT NULL REFERENCES ingest.source_providers(id) ON DELETE RESTRICT,
  source_endpoint_id    UUID NOT NULL REFERENCES ingest.source_endpoints(id) ON DELETE RESTRICT,
  pipeline_run_id       UUID NOT NULL REFERENCES ingest.pipeline_runs(id) ON DELETE RESTRICT,
  raw_payload_id        UUID REFERENCES ingest.raw_payloads(id) ON DELETE SET NULL,
  normalize_run_id      UUID REFERENCES ingest.normalize_runs(id) ON DELETE SET NULL,
  external_record_id    TEXT,
  observed_at           TIMESTAMPTZ NOT NULL,
  fetched_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  aqi                   INTEGER NOT NULL CHECK (aqi >= 0),
  pm25                  DOUBLE PRECISION CHECK (pm25 IS NULL OR pm25 >= 0),
  pm10                  DOUBLE PRECISION CHECK (pm10 IS NULL OR pm10 >= 0),
  o3                    DOUBLE PRECISION CHECK (o3 IS NULL OR o3 >= 0),
  no2                   DOUBLE PRECISION CHECK (no2 IS NULL OR no2 >= 0),
  so2                   DOUBLE PRECISION CHECK (so2 IS NULL OR so2 >= 0),
  co                    DOUBLE PRECISION CHECK (co IS NULL OR co >= 0),
  temperature_c         DOUBLE PRECISION,
  humidity_pct          DOUBLE PRECISION CHECK (humidity_pct IS NULL OR humidity_pct BETWEEN 0 AND 100),
  wind_speed_mps        DOUBLE PRECISION CHECK (wind_speed_mps IS NULL OR wind_speed_mps >= 0),
  quality_status        public.quality_status_enum NOT NULL DEFAULT 'valid',
  lineage               JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (station_id, observed_at, source_endpoint_id)
);

CREATE TABLE core.weather_observations (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id            UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  source_provider_id    UUID NOT NULL REFERENCES ingest.source_providers(id) ON DELETE RESTRICT,
  source_endpoint_id    UUID NOT NULL REFERENCES ingest.source_endpoints(id) ON DELETE RESTRICT,
  pipeline_run_id       UUID NOT NULL REFERENCES ingest.pipeline_runs(id) ON DELETE RESTRICT,
  raw_payload_id        UUID REFERENCES ingest.raw_payloads(id) ON DELETE SET NULL,
  normalize_run_id      UUID REFERENCES ingest.normalize_runs(id) ON DELETE SET NULL,
  observed_at           TIMESTAMPTZ NOT NULL,
  fetched_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  temperature_c         DOUBLE PRECISION,
  feels_like_c          DOUBLE PRECISION,
  humidity_pct          DOUBLE PRECISION CHECK (humidity_pct IS NULL OR humidity_pct BETWEEN 0 AND 100),
  wind_speed_mps        DOUBLE PRECISION CHECK (wind_speed_mps IS NULL OR wind_speed_mps >= 0),
  wind_direction_deg    DOUBLE PRECISION CHECK (wind_direction_deg IS NULL OR wind_direction_deg BETWEEN 0 AND 360),
  pressure_hpa          DOUBLE PRECISION,
  visibility_km         DOUBLE PRECISION CHECK (visibility_km IS NULL OR visibility_km >= 0),
  precipitation_mm      DOUBLE PRECISION CHECK (precipitation_mm IS NULL OR precipitation_mm >= 0),
  cloud_cover_pct       DOUBLE PRECISION CHECK (cloud_cover_pct IS NULL OR cloud_cover_pct BETWEEN 0 AND 100),
  weather_code          TEXT,
  quality_status        public.quality_status_enum NOT NULL DEFAULT 'valid',
  lineage               JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (station_id, observed_at, source_endpoint_id)
);

CREATE TABLE core.traffic_observations (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  area_id               UUID REFERENCES catalog.areas(id) ON DELETE CASCADE,
  station_id            UUID REFERENCES catalog.stations(id) ON DELETE CASCADE,
  source_provider_id    UUID NOT NULL REFERENCES ingest.source_providers(id) ON DELETE RESTRICT,
  source_endpoint_id    UUID NOT NULL REFERENCES ingest.source_endpoints(id) ON DELETE RESTRICT,
  pipeline_run_id       UUID NOT NULL REFERENCES ingest.pipeline_runs(id) ON DELETE RESTRICT,
  raw_payload_id        UUID REFERENCES ingest.raw_payloads(id) ON DELETE SET NULL,
  normalize_run_id      UUID REFERENCES ingest.normalize_runs(id) ON DELETE SET NULL,
  segment_key           TEXT NOT NULL DEFAULT 'global',
  road_name             TEXT,
  observed_at           TIMESTAMPTZ NOT NULL,
  fetched_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  congestion_index      INTEGER CHECK (congestion_index IS NULL OR congestion_index BETWEEN 0 AND 100),
  avg_speed_kmh         DOUBLE PRECISION CHECK (avg_speed_kmh IS NULL OR avg_speed_kmh >= 0),
  free_flow_speed_kmh   DOUBLE PRECISION CHECK (free_flow_speed_kmh IS NULL OR free_flow_speed_kmh >= 0),
  travel_time_minutes   DOUBLE PRECISION CHECK (travel_time_minutes IS NULL OR travel_time_minutes >= 0),
  quality_status        public.quality_status_enum NOT NULL DEFAULT 'valid',
  lineage               JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (area_id IS NOT NULL OR station_id IS NOT NULL)
);

CREATE INDEX idx_core_aq_station_time ON core.air_quality_observations (station_id, observed_at DESC);
CREATE INDEX idx_core_aq_run_id ON core.air_quality_observations (pipeline_run_id);
CREATE INDEX idx_core_weather_station_time ON core.weather_observations (station_id, observed_at DESC);
CREATE INDEX idx_core_weather_run_id ON core.weather_observations (pipeline_run_id);
CREATE INDEX idx_core_traffic_area_time ON core.traffic_observations (area_id, observed_at DESC);
CREATE INDEX idx_core_traffic_station_time ON core.traffic_observations (station_id, observed_at DESC);
CREATE INDEX idx_core_traffic_run_id ON core.traffic_observations (pipeline_run_id);
CREATE UNIQUE INDEX uq_core_traffic_scope_time
  ON core.traffic_observations (COALESCE(area_id::text, station_id::text), segment_key, observed_at, source_endpoint_id);

-- ============================================================
-- ANALYTICS
-- ============================================================

CREATE TABLE analytics.feature_snapshots (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  station_id            UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  built_from_pipeline_run_id UUID REFERENCES ingest.pipeline_runs(id) ON DELETE SET NULL,
  source_window_from    TIMESTAMPTZ NOT NULL,
  source_window_to      TIMESTAMPTZ NOT NULL,
  feature_set_version   TEXT NOT NULL,
  features              JSONB NOT NULL,
  label_target_aqi      INTEGER,
  built_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE analytics.analysis_runs (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_run_id       UUID NOT NULL UNIQUE REFERENCES ingest.pipeline_runs(id) ON DELETE CASCADE,
  analysis_type         public.analysis_type_enum NOT NULL,
  station_id            UUID REFERENCES catalog.stations(id) ON DELETE CASCADE,
  area_id               UUID REFERENCES catalog.areas(id) ON DELETE CASCADE,
  algorithm_key         TEXT,
  algorithm_version     TEXT,
  period_from           TIMESTAMPTZ NOT NULL,
  period_to             TIMESTAMPTZ NOT NULL,
  status                public.run_status_enum NOT NULL DEFAULT 'queued',
  summary               JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE analytics.station_daily_summaries (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_run_id       UUID NOT NULL REFERENCES analytics.analysis_runs(id) ON DELETE CASCADE,
  station_id            UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  summary_date          DATE NOT NULL,
  avg_aqi               DOUBLE PRECISION,
  max_aqi               INTEGER,
  min_aqi               INTEGER,
  dominant_pollutant    TEXT,
  unhealthy_hours       INTEGER,
  metrics               JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (station_id, summary_date)
);

CREATE TABLE analytics.anomaly_events (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_run_id       UUID NOT NULL REFERENCES analytics.analysis_runs(id) ON DELETE CASCADE,
  station_id            UUID REFERENCES catalog.stations(id) ON DELETE CASCADE,
  detected_at           TIMESTAMPTZ NOT NULL,
  metric_code           TEXT NOT NULL,
  metric_value          DOUBLE PRECISION,
  severity              SMALLINT NOT NULL CHECK (severity BETWEEN 1 AND 5),
  reason                TEXT,
  context               JSONB NOT NULL DEFAULT '{}'::jsonb,
  status                TEXT NOT NULL DEFAULT 'open',
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE analytics.analysis_reports (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_run_id       UUID NOT NULL REFERENCES analytics.analysis_runs(id) ON DELETE CASCADE,
  station_id            UUID REFERENCES catalog.stations(id) ON DELETE CASCADE,
  area_id               UUID REFERENCES catalog.areas(id) ON DELETE CASCADE,
  report_type           public.analysis_type_enum NOT NULL,
  title                 TEXT NOT NULL,
  report_payload        JSONB NOT NULL,
  generated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_analytics_feature_snapshots_station_time ON analytics.feature_snapshots (station_id, built_at DESC);
CREATE INDEX idx_analytics_analysis_runs_status ON analytics.analysis_runs (status, created_at DESC);
CREATE INDEX idx_analytics_analysis_runs_station ON analytics.analysis_runs (station_id, period_from DESC);
CREATE INDEX idx_analytics_anomaly_station_time ON analytics.anomaly_events (station_id, detected_at DESC);

-- ============================================================
-- FORECAST
-- ============================================================

CREATE TABLE forecast.model_registry (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code                  TEXT NOT NULL UNIQUE,
  name                  TEXT NOT NULL,
  target                public.prediction_target_enum NOT NULL,
  station_id            UUID REFERENCES catalog.stations(id) ON DELETE CASCADE,
  area_id               UUID REFERENCES catalog.areas(id) ON DELETE CASCADE,
  owner_service         public.service_name_enum NOT NULL DEFAULT 'be_data',
  status                public.model_status_enum NOT NULL DEFAULT 'draft',
  horizon_hours         INTEGER NOT NULL DEFAULT 48 CHECK (horizon_hours > 0),
  feature_set_version   TEXT,
  metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE forecast.model_versions (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  model_id              UUID NOT NULL REFERENCES forecast.model_registry(id) ON DELETE CASCADE,
  version               TEXT NOT NULL,
  artifact_uri          TEXT,
  training_library      TEXT,
  hyperparameters       JSONB NOT NULL DEFAULT '{}'::jsonb,
  metrics               JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_production         BOOLEAN NOT NULL DEFAULT false,
  released_at           TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (model_id, version)
);

CREATE TABLE forecast.training_runs (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_run_id       UUID NOT NULL UNIQUE REFERENCES ingest.pipeline_runs(id) ON DELETE CASCADE,
  model_version_id      UUID NOT NULL REFERENCES forecast.model_versions(id) ON DELETE CASCADE,
  trained_from          TIMESTAMPTZ,
  trained_to            TIMESTAMPTZ,
  sample_count          INTEGER,
  feature_snapshot_count INTEGER,
  metrics               JSONB NOT NULL DEFAULT '{}'::jsonb,
  status                public.run_status_enum NOT NULL DEFAULT 'queued',
  error_message         TEXT,
  started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at           TIMESTAMPTZ
);

CREATE TABLE forecast.prediction_runs (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_run_id       UUID NOT NULL UNIQUE REFERENCES ingest.pipeline_runs(id) ON DELETE CASCADE,
  model_version_id      UUID NOT NULL REFERENCES forecast.model_versions(id) ON DELETE CASCADE,
  station_id            UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  base_time             TIMESTAMPTZ NOT NULL,
  horizon_hours         INTEGER NOT NULL CHECK (horizon_hours > 0),
  status                public.run_status_enum NOT NULL DEFAULT 'queued',
  summary               JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE forecast.predictions (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  prediction_run_id     UUID NOT NULL REFERENCES forecast.prediction_runs(id) ON DELETE CASCADE,
  model_version_id      UUID REFERENCES forecast.model_versions(id) ON DELETE SET NULL,
  station_id            UUID NOT NULL REFERENCES catalog.stations(id) ON DELETE CASCADE,
  target                public.prediction_target_enum NOT NULL DEFAULT 'aqi',
  predicted_for         TIMESTAMPTZ NOT NULL,
  predicted_value       DOUBLE PRECISION NOT NULL,
  lower_bound           DOUBLE PRECISION,
  upper_bound           DOUBLE PRECISION,
  confidence_score      DOUBLE PRECISION CHECK (confidence_score IS NULL OR confidence_score BETWEEN 0 AND 1),
  features_snapshot_id  UUID REFERENCES analytics.feature_snapshots(id) ON DELETE SET NULL,
  explanation           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (prediction_run_id, station_id, target, predicted_for)
);

CREATE INDEX idx_forecast_model_versions_model_id ON forecast.model_versions (model_id, is_production);
CREATE INDEX idx_forecast_training_runs_model_version ON forecast.training_runs (model_version_id, started_at DESC);
CREATE INDEX idx_forecast_prediction_runs_station ON forecast.prediction_runs (station_id, created_at DESC);
CREATE INDEX idx_forecast_predictions_station_time ON forecast.predictions (station_id, predicted_for ASC);

CREATE TRIGGER trg_forecast_model_registry_updated_at
BEFORE UPDATE ON forecast.model_registry
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- ============================================================
-- OPS
-- ============================================================

CREATE TABLE ops.service_configs (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  service_name          public.service_name_enum NOT NULL,
  config_key            TEXT NOT NULL,
  scope_key             TEXT NOT NULL DEFAULT 'global',
  value                 JSONB NOT NULL,
  updated_by_user_id    UUID REFERENCES iam.users(id) ON DELETE SET NULL,
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (service_name, config_key, scope_key)
);

CREATE TABLE ops.service_health_checks (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  service_name          public.service_name_enum NOT NULL,
  status                TEXT NOT NULL,
  latency_ms            INTEGER,
  details               JSONB NOT NULL DEFAULT '{}'::jsonb,
  checked_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ops.audit_logs (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_type            public.actor_type_enum NOT NULL,
  actor_user_id         UUID REFERENCES iam.users(id) ON DELETE SET NULL,
  actor_service         public.service_name_enum,
  target_service        public.service_name_enum,
  action                TEXT NOT NULL,
  resource_type         TEXT NOT NULL,
  resource_id           UUID,
  before_data           JSONB NOT NULL DEFAULT '{}'::jsonb,
  after_data            JSONB NOT NULL DEFAULT '{}'::jsonb,
  context               JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ops_service_health_checks_service ON ops.service_health_checks (service_name, checked_at DESC);
CREATE INDEX idx_ops_audit_logs_actor_user_id ON ops.audit_logs (actor_user_id, created_at DESC);
CREATE INDEX idx_ops_audit_logs_target_service ON ops.audit_logs (target_service, created_at DESC);

CREATE TRIGGER trg_ops_service_configs_updated_at
BEFORE UPDATE ON ops.service_configs
FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- ============================================================
-- VIEWS
-- ============================================================

CREATE VIEW app.v_station_latest_air_quality AS
SELECT
  s.id AS station_id,
  s.code AS station_code,
  s.name AS station_name,
  s.area_id,
  s.lat,
  s.lng,
  s.is_active,
  aq.observed_at,
  COALESCE(aq.fetched_at, weather.fetched_at) AS fetched_at,
  aq.aqi,
  aq.pm25,
  aq.pm10,
  aq.o3,
  aq.no2,
  aq.so2,
  aq.co,
  COALESCE(aq.temperature_c, weather.temperature_c) AS temperature_c,
  COALESCE(aq.humidity_pct, weather.humidity_pct) AS humidity_pct,
  COALESCE(aq.wind_speed_mps, weather.wind_speed_mps) AS wind_speed_mps,
  aq.quality_status,
  sp.code AS source_provider_code,
  se.code AS source_endpoint_code
FROM catalog.stations s
LEFT JOIN LATERAL (
  SELECT *
  FROM core.air_quality_observations a
  WHERE a.station_id = s.id
  ORDER BY a.observed_at DESC
  LIMIT 1
) aq ON TRUE
LEFT JOIN LATERAL (
  SELECT *
  FROM core.weather_observations w
  WHERE w.station_id = s.id
  ORDER BY w.observed_at DESC
  LIMIT 1
) weather ON TRUE
LEFT JOIN ingest.source_providers sp ON sp.id = aq.source_provider_id
LEFT JOIN ingest.source_endpoints se ON se.id = aq.source_endpoint_id
WHERE s.is_active = TRUE;

CREATE VIEW ops.v_pipeline_run_overview AS
SELECT
  pr.id,
  pd.code AS pipeline_code,
  pd.name AS pipeline_name,
  pd.pipeline_type,
  pr.status,
  pr.trigger_type,
  pr.started_at,
  pr.finished_at,
  se.code AS endpoint_code,
  se.name AS endpoint_name,
  pr.error_summary,
  pr.metrics
FROM ingest.pipeline_runs pr
JOIN ingest.pipeline_definitions pd ON pd.id = pr.pipeline_definition_id
LEFT JOIN ingest.source_endpoints se ON se.id = pr.source_endpoint_id;

CREATE VIEW ops.v_station_source_latest AS
SELECT
  s.id AS station_id,
  s.code AS station_code,
  s.name AS station_name,
  aq.observed_at,
  aq.fetched_at,
  aq.aqi,
  sp.code AS source_provider_code,
  se.code AS source_endpoint_code,
  aq.pipeline_run_id,
  aq.raw_payload_id,
  aq.normalize_run_id
FROM catalog.stations s
LEFT JOIN LATERAL (
  SELECT *
  FROM core.air_quality_observations a
  WHERE a.station_id = s.id
  ORDER BY a.observed_at DESC
  LIMIT 1
) aq ON TRUE
LEFT JOIN ingest.source_providers sp ON sp.id = aq.source_provider_id
LEFT JOIN ingest.source_endpoints se ON se.id = aq.source_endpoint_id;

-- ============================================================
-- SEED DATA
-- ============================================================

INSERT INTO iam.roles (code, name, description) VALUES
  ('super_admin', 'Super Admin', 'Toan quyen he thong'),
  ('admin', 'Admin', 'Quan tri business va van hanh'),
  ('operator', 'Operator', 'Van hanh pipeline va source'),
  ('analyst', 'Analyst', 'Xem bao cao phan tich va du bao'),
  ('user', 'User', 'Nguoi dung cuoi')
ON CONFLICT (code) DO NOTHING;

INSERT INTO ingest.source_providers (
  code,
  name,
  category,
  base_url,
  auth_type,
  rate_limit_per_minute,
  timeout_seconds,
  is_active
) VALUES
  ('openmeteo', 'Open-Meteo', 'environmental', 'https://open-meteo.com', 'none', 600, 30, TRUE),
  ('waqi', 'WAQI', 'air_quality', 'https://api.waqi.info', 'token', 60, 30, FALSE),
  ('openaq', 'OpenAQ', 'air_quality', 'https://api.openaq.org/v3', 'api_key', 60, 30, FALSE),
  ('openweather', 'OpenWeather', 'weather', 'https://api.openweathermap.org', 'api_key', 120, 30, FALSE),
  ('tomtom', 'TomTom', 'traffic', 'https://api.tomtom.com', 'api_key', 120, 30, FALSE)
ON CONFLICT (code) DO NOTHING;

INSERT INTO ingest.pipeline_definitions (code, name, pipeline_type, owner_service, schedule_expression, config) VALUES
  ('fetch_air_quality', 'Fetch air quality from providers', 'ingest', 'be_data', '*/30 * * * *', '{}'::jsonb),
  ('fetch_weather', 'Fetch weather from providers', 'ingest', 'be_data', '0 * * * *', '{}'::jsonb),
  ('fetch_traffic', 'Fetch traffic from providers', 'ingest', 'be_data', '*/30 * * * *', '{}'::jsonb),
  ('analyze_daily', 'Generate daily analytics', 'analysis', 'be_data', '15 0 * * *', '{}'::jsonb),
  ('predict_aqi_48h', 'Generate 48h AQI forecast', 'forecast', 'be_data', '10 * * * *', '{"horizon_hours":48}'::jsonb),
  ('normalize_air_quality', 'Parse raw AQI into canonical', 'normalize', 'be_data', NULL, '{}'::jsonb),
  ('normalize_weather', 'Parse raw weather into canonical', 'normalize', 'be_data', NULL, '{}'::jsonb),
  ('build_features', 'Build ML feature snapshots', 'analysis', 'be_data', '15 * * * *', '{}'::jsonb),
  ('analyze_weekly', 'Generate weekly report', 'analysis', 'be_data', '0 2 * * 1', '{}'::jsonb),
  ('train_models', 'Retrain ML models', 'train', 'be_data', '0 3 * * 0', '{}'::jsonb)
ON CONFLICT (code) DO NOTHING;

-- Default system configs
INSERT INTO ops.service_configs (service_name, config_key, scope_key, value) VALUES
  ('be_data',  'aqi_fetch_interval_min',     'global', '30'::jsonb),
  ('be_data',  'weather_fetch_interval_min',  'global', '60'::jsonb),
  ('be_data',  'traffic_fetch_interval_min',  'global', '30'::jsonb),
  ('be_data',  'prediction_horizon_hours',    'global', '48'::jsonb),
  ('be_data',  'retrain_cron',               'global', '"0 3 * * 0"'::jsonb),
  ('be_data',  'data_retention_days',        'global', '365'::jsonb),
  ('be_api',   'jwt_access_ttl_minutes',     'global', '15'::jsonb),
  ('be_api',   'jwt_refresh_ttl_days',       'global', '7'::jsonb),
  ('be_api',   'alert_cooldown_minutes',     'global', '60'::jsonb),
  ('be_api',   'max_notifications_per_day',  'global', '50'::jsonb),
  ('system',   'maintenance_mode',           'global', 'false'::jsonb)
ON CONFLICT (service_name, config_key, scope_key) DO NOTHING;


-- ============================================================
-- ADMIN LINEAGE VIEWS
-- Cho phep Admin truy vet toan bo chuoi du lieu
-- observation -> normalize -> raw_payload -> request -> pipeline -> endpoint -> provider
-- prediction -> model_version -> training_run -> feature_snapshot
-- ============================================================

-- View: Observation full lineage
-- "Du lieu AQI nay lay tu dau, luc nao, parse version nao?"
CREATE VIEW ops.v_observation_full_lineage AS
SELECT
  aq.id                       AS observation_id,
  aq.station_id,
  s.code                      AS station_code,
  s.name                      AS station_name,
  aq.aqi,
  aq.pm25,
  aq.quality_status,
  aq.observed_at,
  aq.fetched_at,
  -- Provider & Endpoint
  sp.id                       AS provider_id,
  sp.code                     AS provider_code,
  sp.name                     AS provider_name,
  se.id                       AS endpoint_id,
  se.code                     AS endpoint_code,
  se.name                     AS endpoint_name,
  se.kind                     AS endpoint_kind,
  -- Pipeline Run
  pr.id                       AS pipeline_run_id,
  pd.code                     AS pipeline_code,
  pr.status                   AS pipeline_status,
  pr.trigger_type,
  pr.started_at               AS pipeline_started_at,
  pr.finished_at              AS pipeline_finished_at,
  pr.metrics                  AS pipeline_metrics,
  -- Outbound Request
  orq.id                      AS request_id,
  orq.request_url,
  orq.http_status,
  orq.status                  AS request_status,
  orq.latency_ms              AS request_latency_ms,
  orq.response_size_bytes,
  orq.request_started_at,
  -- Raw Payload
  rp.id                       AS raw_payload_id,
  rp.payload_format,
  rp.payload_hash,
  rp.storage_uri              AS payload_storage_uri,
  rp.fetched_at               AS payload_fetched_at,
  -- Normalize Run
  nr.id                       AS normalize_run_id,
  nr.parser_key,
  nr.parser_version,
  nr.status                   AS normalize_status,
  nr.records_in               AS normalize_records_in,
  nr.records_out              AS normalize_records_out,
  nr.warnings                 AS normalize_warnings
FROM core.air_quality_observations aq
JOIN catalog.stations s               ON s.id  = aq.station_id
LEFT JOIN ingest.source_providers sp  ON sp.id = aq.source_provider_id
LEFT JOIN ingest.source_endpoints se  ON se.id = aq.source_endpoint_id
LEFT JOIN ingest.pipeline_runs pr     ON pr.id = aq.pipeline_run_id
LEFT JOIN ingest.pipeline_definitions pd ON pd.id = pr.pipeline_definition_id
LEFT JOIN ingest.raw_payloads rp      ON rp.id = aq.raw_payload_id
LEFT JOIN ingest.normalize_runs nr    ON nr.id = aq.normalize_run_id
LEFT JOIN LATERAL (
  SELECT * FROM ingest.outbound_requests
  WHERE pipeline_run_id = pr.id
    AND source_endpoint_id = se.id
  ORDER BY request_started_at DESC
  LIMIT 1
) orq ON pr.id IS NOT NULL;

-- ---

-- View: Prediction full lineage
-- "Du doan nay dung model nao, train luc nao, data gi?"
CREATE VIEW ops.v_prediction_full_lineage AS
SELECT
  p.id                        AS prediction_id,
  p.station_id,
  s.code                      AS station_code,
  s.name                      AS station_name,
  p.target,
  p.predicted_for,
  p.predicted_value,
  p.lower_bound,
  p.upper_bound,
  p.confidence_score,
  p.created_at                AS prediction_created_at,
  -- Prediction Run
  prun.id                     AS prediction_run_id,
  prun.base_time,
  prun.horizon_hours,
  prun.status                 AS pred_run_status,
  -- Pipeline Run (prediction)
  ppr.id                      AS pred_pipeline_run_id,
  ppd.code                    AS pred_pipeline_code,
  ppr.started_at              AS pred_pipeline_started_at,
  -- Model
  mr.code                     AS model_code,
  mr.name                     AS model_name,
  mr.target                   AS model_target,
  mr.status                   AS model_status,
  -- Model Version
  mv.id                       AS model_version_id,
  mv.version                  AS model_version,
  mv.training_library,
  mv.hyperparameters,
  mv.metrics                  AS model_metrics,
  mv.is_production,
  mv.released_at,
  -- Training Run (most recent successful for this version)
  tr.id                       AS training_run_id,
  tr.trained_from,
  tr.trained_to,
  tr.sample_count             AS training_samples,
  tr.metrics                  AS training_metrics,
  tr.status                   AS training_status,
  tr.started_at               AS training_started_at,
  tr.finished_at              AS training_finished_at,
  -- Feature Snapshot
  fs.id                       AS feature_snapshot_id,
  fs.feature_set_version,
  fs.source_window_from       AS feature_window_from,
  fs.source_window_to         AS feature_window_to,
  fs.built_at                 AS features_built_at
FROM forecast.predictions p
JOIN catalog.stations s                    ON s.id = p.station_id
JOIN forecast.prediction_runs prun         ON prun.id = p.prediction_run_id
JOIN forecast.model_versions mv            ON mv.id = COALESCE(p.model_version_id, prun.model_version_id)
JOIN forecast.model_registry mr            ON mr.id = mv.model_id
LEFT JOIN ingest.pipeline_runs ppr         ON ppr.id = prun.pipeline_run_id
LEFT JOIN ingest.pipeline_definitions ppd  ON ppd.id = ppr.pipeline_definition_id
LEFT JOIN analytics.feature_snapshots fs   ON fs.id = p.features_snapshot_id
LEFT JOIN LATERAL (
  SELECT * FROM forecast.training_runs
  WHERE model_version_id = mv.id AND status = 'success'
  ORDER BY finished_at DESC NULLS LAST
  LIMIT 1
) tr ON true;

-- ---

-- View: Analysis run lineage
-- "Bao cao phan tich nay dung thuat toan gi, data khoang nao?"
CREATE VIEW ops.v_analysis_run_lineage AS
SELECT
  ar.id                       AS analysis_run_id,
  ar.analysis_type,
  ar.algorithm_key,
  ar.algorithm_version,
  ar.station_id,
  s.code                      AS station_code,
  s.name                      AS station_name,
  a.name                      AS area_name,
  ar.period_from,
  ar.period_to,
  ar.status                   AS analysis_status,
  ar.summary                  AS analysis_summary,
  -- Pipeline Run
  pr.id                       AS pipeline_run_id,
  pd.code                     AS pipeline_code,
  pr.status                   AS pipeline_status,
  pr.started_at               AS pipeline_started_at,
  pr.finished_at              AS pipeline_finished_at,
  -- Output counts
  (SELECT COUNT(*) FROM analytics.station_daily_summaries sds
   WHERE sds.analysis_run_id = ar.id)   AS daily_summaries_count,
  (SELECT COUNT(*) FROM analytics.anomaly_events ae
   WHERE ae.analysis_run_id = ar.id)    AS anomalies_found,
  (SELECT COUNT(*) FROM analytics.analysis_reports rep
   WHERE rep.analysis_run_id = ar.id)   AS reports_generated
FROM analytics.analysis_runs ar
LEFT JOIN catalog.stations s        ON s.id = ar.station_id
LEFT JOIN catalog.areas a           ON a.id = ar.area_id
JOIN ingest.pipeline_runs pr        ON pr.id = ar.pipeline_run_id
JOIN ingest.pipeline_definitions pd ON pd.id = pr.pipeline_definition_id;

-- ---

-- View: Station bindings — tram nao lay tu nguon nao, data moi nhat la gi
CREATE VIEW ops.v_station_bindings_overview AS
SELECT
  s.id                        AS station_id,
  s.code                      AS station_code,
  s.name                      AS station_name,
  s.is_active                 AS station_active,
  sb.id                       AS binding_id,
  sb.external_object_id,
  sb.priority,
  sb.is_enabled               AS binding_enabled,
  sb.valid_from,
  sb.valid_to,
  sp.code                     AS provider_code,
  sp.name                     AS provider_name,
  sp.is_active                AS provider_active,
  se.code                     AS endpoint_code,
  se.name                     AS endpoint_name,
  se.kind                     AS endpoint_kind,
  se.schedule_expression,
  se.is_active                AS endpoint_active,
  latest_obs.observed_at      AS latest_observation_at,
  latest_obs.aqi              AS latest_aqi,
  latest_obs.quality_status   AS latest_quality
FROM catalog.stations s
LEFT JOIN ingest.station_source_bindings sb ON sb.station_id = s.id
LEFT JOIN ingest.source_endpoints se        ON se.id = sb.endpoint_id
LEFT JOIN ingest.source_providers sp        ON sp.id = se.provider_id
LEFT JOIN LATERAL (
  SELECT observed_at, aqi, quality_status
  FROM core.air_quality_observations
  WHERE station_id = s.id
    AND source_endpoint_id = se.id
  ORDER BY observed_at DESC
  LIMIT 1
) latest_obs ON se.id IS NOT NULL;

-- ---

-- View: Provider health — dashboard card cho admin
CREATE VIEW ops.v_provider_health AS
SELECT
  sp.id                       AS provider_id,
  sp.code                     AS provider_code,
  sp.name                     AS provider_name,
  sp.is_active,
  COALESCE(stats.total_requests, 0)   AS requests_24h,
  COALESCE(stats.success_count, 0)    AS success_24h,
  COALESCE(stats.failed_count, 0)     AS failed_24h,
  CASE WHEN COALESCE(stats.total_requests, 0) > 0
    THEN ROUND((stats.success_count::NUMERIC / stats.total_requests) * 100, 1)
    ELSE 0
  END                                 AS success_rate_pct,
  stats.avg_latency_ms,
  stats.p95_latency_ms,
  stats.total_bytes_24h,
  bindings.active_count               AS active_bindings,
  last_ok.last_success_at
FROM ingest.source_providers sp
LEFT JOIN LATERAL (
  SELECT
    COUNT(*)                                                  AS total_requests,
    COUNT(*) FILTER (WHERE status = 'success')                AS success_count,
    COUNT(*) FILTER (WHERE status IN ('failed','timeout'))    AS failed_count,
    ROUND(AVG(latency_ms)::NUMERIC)::INTEGER                  AS avg_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::INTEGER AS p95_latency_ms,
    SUM(response_size_bytes)                                  AS total_bytes_24h
  FROM ingest.outbound_requests
  WHERE source_provider_id = sp.id
    AND request_started_at > now() - INTERVAL '24 hours'
) stats ON true
LEFT JOIN LATERAL (
  SELECT COUNT(*) FILTER (WHERE sb.is_enabled) AS active_count
  FROM ingest.station_source_bindings sb
  JOIN ingest.source_endpoints se ON se.id = sb.endpoint_id
  WHERE se.provider_id = sp.id
) bindings ON true
LEFT JOIN LATERAL (
  SELECT MAX(request_started_at) AS last_success_at
  FROM ingest.outbound_requests
  WHERE source_provider_id = sp.id AND status = 'success'
) last_ok ON true;

-- ---

-- View: Model production status — model nao dang chay, train luc nao, ket qua ra sao
CREATE VIEW ops.v_model_production_status AS
SELECT
  mr.id                       AS model_id,
  mr.code                     AS model_code,
  mr.name                     AS model_name,
  mr.target,
  mr.status                   AS model_status,
  s.code                      AS station_code,
  s.name                      AS station_name,
  mv.id                       AS version_id,
  mv.version,
  mv.training_library,
  mv.metrics                  AS version_metrics,
  mv.released_at,
  lt.started_at               AS last_trained_at,
  lt.status                   AS last_training_status,
  lt.sample_count,
  lt.metrics                  AS training_metrics,
  lpr.created_at              AS last_prediction_at,
  lpr.status                  AS last_prediction_status
FROM forecast.model_registry mr
LEFT JOIN catalog.stations s ON s.id = mr.station_id
LEFT JOIN forecast.model_versions mv ON mv.model_id = mr.id AND mv.is_production = true
LEFT JOIN LATERAL (
  SELECT * FROM forecast.training_runs
  WHERE model_version_id = mv.id
  ORDER BY started_at DESC LIMIT 1
) lt ON mv.id IS NOT NULL
LEFT JOIN LATERAL (
  SELECT * FROM forecast.prediction_runs
  WHERE model_version_id = mv.id
  ORDER BY created_at DESC LIMIT 1
) lpr ON mv.id IS NOT NULL;


-- ============================================================
-- DATABASE ROLES
-- ============================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'svc_be_api') THEN
    CREATE ROLE svc_be_api LOGIN PASSWORD 'CHANGE_ME_be_api';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'svc_be_data') THEN
    CREATE ROLE svc_be_data LOGIN PASSWORD 'CHANGE_ME_be_data';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'svc_readonly') THEN
    CREATE ROLE svc_readonly LOGIN PASSWORD 'CHANGE_ME_readonly';
  END IF;
END $$;

-- svc_be_api: RW iam/catalog/app/ops, READ core/analytics/forecast/ingest
GRANT USAGE ON SCHEMA iam, catalog, app, ops, core, analytics, forecast, ingest TO svc_be_api;
GRANT ALL    ON ALL TABLES IN SCHEMA iam      TO svc_be_api;
GRANT ALL    ON ALL TABLES IN SCHEMA catalog  TO svc_be_api;
GRANT ALL    ON ALL TABLES IN SCHEMA app      TO svc_be_api;
GRANT ALL    ON ALL TABLES IN SCHEMA ops      TO svc_be_api;
GRANT SELECT ON ALL TABLES IN SCHEMA core      TO svc_be_api;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO svc_be_api;
GRANT SELECT ON ALL TABLES IN SCHEMA forecast  TO svc_be_api;
GRANT SELECT ON ALL TABLES IN SCHEMA ingest    TO svc_be_api;

ALTER DEFAULT PRIVILEGES IN SCHEMA iam      GRANT ALL    ON TABLES TO svc_be_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog  GRANT ALL    ON TABLES TO svc_be_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA app      GRANT ALL    ON TABLES TO svc_be_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops      GRANT ALL    ON TABLES TO svc_be_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA core      GRANT SELECT ON TABLES TO svc_be_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO svc_be_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA forecast  GRANT SELECT ON TABLES TO svc_be_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA ingest    GRANT SELECT ON TABLES TO svc_be_api;

-- svc_be_data: RW ingest/core/analytics/forecast/ops, READ catalog, iam(limited)
GRANT USAGE ON SCHEMA ingest, core, analytics, forecast, ops, catalog, iam TO svc_be_data;
GRANT ALL    ON ALL TABLES IN SCHEMA ingest    TO svc_be_data;
GRANT ALL    ON ALL TABLES IN SCHEMA core      TO svc_be_data;
GRANT ALL    ON ALL TABLES IN SCHEMA analytics TO svc_be_data;
GRANT ALL    ON ALL TABLES IN SCHEMA forecast  TO svc_be_data;
GRANT ALL    ON ALL TABLES IN SCHEMA ops       TO svc_be_data;
GRANT SELECT ON ALL TABLES IN SCHEMA catalog   TO svc_be_data;
GRANT SELECT ON iam.users, iam.user_roles, iam.roles TO svc_be_data;

ALTER DEFAULT PRIVILEGES IN SCHEMA ingest    GRANT ALL    ON TABLES TO svc_be_data;
ALTER DEFAULT PRIVILEGES IN SCHEMA core      GRANT ALL    ON TABLES TO svc_be_data;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT ALL    ON TABLES TO svc_be_data;
ALTER DEFAULT PRIVILEGES IN SCHEMA forecast  GRANT ALL    ON TABLES TO svc_be_data;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops       GRANT ALL    ON TABLES TO svc_be_data;
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog   GRANT SELECT ON TABLES TO svc_be_data;

-- svc_readonly: SELECT everywhere (BI / reporting)
GRANT USAGE ON SCHEMA iam, catalog, app, ingest, core, analytics, forecast, ops TO svc_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA iam       TO svc_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA catalog   TO svc_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA app       TO svc_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA ingest    TO svc_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA core      TO svc_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO svc_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA forecast  TO svc_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA ops       TO svc_readonly;

-- Sequences
GRANT USAGE ON ALL SEQUENCES IN SCHEMA iam, catalog, app, ops TO svc_be_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ingest, core, analytics, forecast, ops TO svc_be_data;
