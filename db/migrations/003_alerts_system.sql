-- ============================================================
-- Migration 003: Alerts system
-- Bảng: alert_rules, alerts, alert_deliveries
-- Hỗ trợ cảnh báo tự động khi AQI vượt ngưỡng
-- ============================================================

-- 1) Alert rules — mỗi user tạo rule theo trạm / chỉ số / ngưỡng
CREATE TABLE IF NOT EXISTS app.alert_rules (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
  station_id    UUID REFERENCES catalog.stations(id) ON DELETE CASCADE,
  metric        TEXT NOT NULL DEFAULT 'aqi',          -- aqi | pm25 | pm10 | o3 | no2 | so2 | co
  operator      TEXT NOT NULL DEFAULT 'gte',          -- gte | lte | gt | lt
  threshold     NUMERIC NOT NULL DEFAULT 100,
  channels      TEXT[] NOT NULL DEFAULT '{in_app}',   -- in_app | email
  cooldown_min  INT NOT NULL DEFAULT 360,             -- tối thiểu N phút giữa 2 lần cảnh báo cùng rule
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_user ON app.alert_rules(user_id);
CREATE INDEX IF NOT EXISTS idx_alert_rules_active ON app.alert_rules(is_active) WHERE is_active;

-- 2) Alerts — mỗi lần rule kích hoạt tạo 1 alert
CREATE TABLE IF NOT EXISTS app.alerts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_id         UUID NOT NULL REFERENCES app.alert_rules(id) ON DELETE CASCADE,
  user_id         UUID NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
  station_id      UUID REFERENCES catalog.stations(id) ON DELETE SET NULL,
  metric          TEXT NOT NULL,
  threshold       NUMERIC NOT NULL,
  actual_value    NUMERIC NOT NULL,
  aqi_category    TEXT,
  title           TEXT NOT NULL,
  message         TEXT NOT NULL,
  is_read         BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alerts_user ON app.alerts(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_rule ON app.alerts(rule_id, created_at DESC);

-- 3) Alert deliveries — track giao hàng (email, push, in_app)
CREATE TABLE IF NOT EXISTS app.alert_deliveries (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  alert_id      UUID NOT NULL REFERENCES app.alerts(id) ON DELETE CASCADE,
  channel       TEXT NOT NULL,                         -- in_app | email
  status        TEXT NOT NULL DEFAULT 'pending',       -- pending | sent | failed
  error_message TEXT,
  sent_at       TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deliveries_alert ON app.alert_deliveries(alert_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_status ON app.alert_deliveries(status) WHERE status = 'pending';

-- 4) Mở rộng bảng notifications hiện tại: thêm trường is_read + alert_id nếu chưa có
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'app' AND table_name = 'notifications' AND column_name = 'is_read'
  ) THEN
    ALTER TABLE app.notifications ADD COLUMN is_read BOOLEAN NOT NULL DEFAULT FALSE;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'app' AND table_name = 'notifications' AND column_name = 'alert_id'
  ) THEN
    ALTER TABLE app.notifications ADD COLUMN alert_id UUID REFERENCES app.alerts(id) ON DELETE SET NULL;
  END IF;
END $$;
