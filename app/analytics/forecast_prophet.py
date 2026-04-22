"""
Prophet forecast training + prediction.
Train Prophet trên observations 14 ngày, predict 24h tới.

DB columns: aqi, pm25, pm10, o3, no2, so2, co
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
from prophet import Prophet

from app.db import fetch, get_session
from app.models.forecast import ForecastRun, ForecastPoint
from app.analytics.evaluation import compute_metrics

logger = logging.getLogger(__name__)

TRAINING_DAYS = 14
FORECAST_HOURS = 24
MIN_TRAINING_ROWS = 20

# DB column names — dùng trực tiếp, KHÔNG map sang tên khác
VALID_METRICS = ["aqi", "pm25", "pm10", "o3", "no2", "so2", "co"]


async def run_prophet_forecast(target_metric: str = "aqi") -> int:
    """Train Prophet cho mỗi station active, predict 24h tới."""
    logger.info("Starting Prophet forecast for metric=%s", target_metric)

    if target_metric not in VALID_METRICS:
        logger.warning("Invalid metric '%s', falling back to 'aqi'", target_metric)
        target_metric = "aqi"

    stations = await fetch(
        "SELECT id, name FROM catalog.stations WHERE is_active = TRUE"
    )
    if not stations:
        return 0

    count = 0
    for station in stations:
        try:
            ok = await _forecast_station(station["id"], station["name"], target_metric)
            if ok:
                count += 1
        except Exception as e:
            logger.error("Prophet failed for station %s: %s", station["name"], e)

    logger.info("Prophet forecast done — %d stations processed", count)
    return count


async def _forecast_station(
    station_id: str, station_name: str, target_metric: str
) -> bool:
    """Train + predict cho 1 station. Trả True nếu thành công."""

    # Lấy dữ liệu training — dùng tên cột trực tiếp từ DB
    rows = await fetch(
        f"""
        SELECT observed_at AS ds, {target_metric} AS y
        FROM core.air_quality_observations
        WHERE station_id = $1
          AND observed_at > now() - INTERVAL '{TRAINING_DAYS} days'
          AND {target_metric} IS NOT NULL
        ORDER BY observed_at
        """,
        station_id,
    )

    if not rows or len(rows) < MIN_TRAINING_ROWS:
        logger.debug("Skip %s — only %d rows", station_name, len(rows) if rows else 0)
        return False

    df = pd.DataFrame(rows)
    df["ds"] = pd.to_datetime(df["ds"], utc=True).dt.tz_localize(None)
    df["y"] = df["y"].astype(float)

    station_uuid = uuid.UUID(station_id) if isinstance(station_id, str) else station_id

    async with get_session() as session:
        # Tạo forecast_run
        run = ForecastRun(
            station_id=station_uuid,
            model_type="prophet",
            target_metric=target_metric,
            horizon_hours=FORECAST_HOURS,
            training_rows=len(df),
            status="running",
        )
        session.add(run)
        await session.flush()  # Get run.id
        run_id = run.id

        try:
            # Train Prophet (suppress verbose logging)
            model = Prophet(
                daily_seasonality=True,
                weekly_seasonality=True,
                yearly_seasonality=False,
                changepoint_prior_scale=0.05,
            )
            model.fit(df)

            # Future dataframe
            future = model.make_future_dataframe(periods=FORECAST_HOURS, freq="h")
            forecast = model.predict(future)

            # Tách phần dự báo mới (sau thời điểm cuối training)
            last_train_ts = df["ds"].max()
            future_only = forecast[forecast["ds"] > last_train_ts].copy()

            if future_only.empty:
                raise ValueError("No future predictions generated")

            # Cross-validation đơn giản: 80/20 split
            split = int(len(df) * 0.8)
            train_part = df.iloc[:split]
            test_part = df.iloc[split:]

            mae, rmse, mape = None, None, None
            if len(test_part) >= 5:
                m2 = Prophet(
                    daily_seasonality=True,
                    weekly_seasonality=True,
                    yearly_seasonality=False,
                    changepoint_prior_scale=0.05,
                )
                m2.fit(train_part)
                test_future = m2.make_future_dataframe(periods=len(test_part), freq="h")
                test_pred = m2.predict(test_future)
                test_pred_vals = test_pred.iloc[-len(test_part):]["yhat"].values
                test_actual = test_part["y"].values
                mae, rmse, mape = compute_metrics(test_actual, test_pred_vals)

            # Lưu forecast points
            for _, row in future_only.iterrows():
                point = ForecastPoint(
                    forecast_run_id=run_id,
                    station_id=station_uuid,
                    target_metric=target_metric,
                    predicted_at=row["ds"].to_pydatetime().replace(tzinfo=timezone.utc),
                    predicted_value=round(float(row["yhat"]), 2),
                    lower_bound=round(float(row["yhat_lower"]), 2) if pd.notna(row["yhat_lower"]) else None,
                    upper_bound=round(float(row["yhat_upper"]), 2) if pd.notna(row["yhat_upper"]) else None,
                )
                session.add(point)

            # Cập nhật run status
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            run.mae = mae
            run.rmse = rmse
            run.mape = mape

            await session.commit()

            logger.info(
                "Prophet %s @ %s — %d points, MAE=%.2f, RMSE=%.2f",
                target_metric, station_name, len(future_only),
                mae or 0, rmse or 0,
            )
            return True

        except Exception as e:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)[:500]
            await session.commit()
            raise
