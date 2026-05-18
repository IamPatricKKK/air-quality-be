"""
Idempotent: tạo các bảng analytics còn thiếu từ ORM models lúc app khởi động.

Bối cảnh: seasonal_patterns / correlation_matrices / trend_analyses /
health_impacts CHỈ được định nghĩa dưới dạng SQLAlchemy model, KHÔNG có
migration nào tạo bảng → các job seasonal/correlation/trend/health_impact
ghi vào bảng không tồn tại và fail. create_all(checkfirst=True) chỉ tạo
bảng còn thiếu, KHÔNG đụng bảng đã có (daily_summaries, anomalies,
grid_aqi_observations...).

Nguồn DDL chính thức nay là Alembic migration
`alembic/versions/0001_analytics_be_tables.py` (`make migration-up`).
Hàm này chỉ còn là lưới an toàn runtime cho môi trường chưa chạy migration.
"""

from __future__ import annotations

import logging

from app.db import get_engine
from app.models.base import Base
import app.models.analytics  # noqa: F401  — register models vào metadata

logger = logging.getLogger(__name__)

# Chỉ những bảng analytics do be sở hữu mà thường thiếu DDL.
_MANAGED = {
    "analytics.seasonal_patterns",
    "analytics.correlation_matrices",
    "analytics.trend_analyses",
    "analytics.health_impacts",
}


async def ensure_analytics_tables() -> None:
    engine = get_engine()
    if engine is None:
        logger.warning("ensure_analytics_tables: DATABASE_URL chưa cấu hình — bỏ qua")
        return
    tables = [
        t for t in Base.metadata.sorted_tables
        if f"{t.schema}.{t.name}" in _MANAGED
    ]
    if not tables:
        return
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sc: Base.metadata.create_all(sc, tables=tables, checkfirst=True)
        )
    logger.info(
        "ensure_analytics_tables: verified %d analytics tables (created if missing)",
        len(tables),
    )
