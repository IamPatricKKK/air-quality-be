"""baseline: analytics tables owned by air-quality-be

seasonal_patterns / correlation_matrices / trend_analyses / health_impacts —
trước đây chỉ được tạo runtime bởi app/models/ensure.py (và file rời
db/001_analytics_missing_tables.sql). Migration này đưa chúng vào pipeline
Alembic chính thức (`make migration-up`). Dùng IF NOT EXISTS để idempotent,
an toàn cả khi ensure.py đã tạo bảng từ trước.

Lưu ý: schema `analytics` và `catalog.stations` do air-quality-api sở hữu và
phải tồn tại trước khi chạy migration này.

Revision ID: 0001_analytics_be
Revises:
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "0001_analytics_be"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # asyncpg dùng prepared statements → mỗi op.execute chỉ được 1 câu lệnh.
    op.execute(
        """
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
        )
        """
    )
    op.execute(
        """
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
        )
        """
    )
    op.execute(
        """
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
        )
        """
    )
    op.execute(
        """
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
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analytics.trend_analyses")
    op.execute("DROP TABLE IF EXISTS analytics.seasonal_patterns")
    op.execute("DROP TABLE IF EXISTS analytics.health_impacts")
    op.execute("DROP TABLE IF EXISTS analytics.correlation_matrices")
