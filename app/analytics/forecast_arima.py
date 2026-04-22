"""
ARIMA forecast — short-term prediction (6-12h).
Dùng statsmodels auto_arima qua pmdarima để tự chọn (p,d,q).
Phù hợp cho dự báo ngắn hạn khi chuỗi có tính dừng (stationary).
"""

import logging
import uuid
from datetime import timezone, datetime

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA

from app.db import fetch, get_session
from app.models.forecast import ForecastRun, ForecastPoint
from app.analytics.evaluation import compute_metrics

logger = logging.getLogger(__name__)

TRAINING_DAYS = 7
FORECAST_HOURS = 12
MIN_TRAINING_ROWS = 48  # ít nhất 2 ngày data hourly
VALID_METRICS = ["aqi", "pm25", "pm10", "o3", "no2", "so2", "co"]


async def run_arima_forecast(target_metric: str = "aqi") -> int:
    """ARIMA forecast cho mỗi station active."""
    logger.info("Starting ARIMA forecast for metric=%s", target_metric)

    if target_metric not in VALID_METRICS:
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
            logger.error("ARIMA failed for station %s: %s", station["name"], e)

    logger.info("ARIMA forecast done — %d stations processed", count)
    return count


async def _forecast_station(station_id: str, station_name: str, metric: str) -> bool:
    rows = await fetch(
        f"""
        SELECT observed_at AS ds, {metric} AS y
        FROM core.air_quality_observations
        WHERE station_id = $1
          AND observed_at > now() - INTERVAL '{TRAINING_DAYS} days'
          AND {metric} IS NOT NULL
        ORDER BY observed_at
        """,
        station_id,
    )

    if not rows or len(rows) < MIN_TRAINING_ROWS:
        return False

    df = pd.DataFrame(rows)
    df["ds"] = pd.to_datetime(df["ds"], utc=True)
    df["y"] = df["y"].astype(float)
    df = df.set_index("ds").resample("h").mean().dropna()

    if len(df) < MIN_TRAINING_ROWS:
        return False

    station_uuid = uuid.UUID(station_id) if isinstance(station_id, str) else station_id

    async with get_session() as session:
        # Tạo forecast_run
        run = ForecastRun(
            station_id=station_uuid,
            model_type="arima",
            target_metric=metric,
            horizon_hours=FORECAST_HOURS,
            training_rows=len(df),
            status="running",
        )
        session.add(run)
        await session.flush()  # Get run.id
        run_id = run.id

        try:
            series = df["y"].values

            # Cross-validation: 80/20 split
            split = int(len(series) * 0.8)
            train_data = series[:split]
            test_data = series[split:]

            # Fit ARIMA(2,1,2) — phổ biến cho AQI time series
            # Order có thể tune tùy metric, nhưng (2,1,2) là default tốt
            model = ARIMA(train_data, order=(2, 1, 2))
            fitted = model.fit()

            # Evaluate on test set
            mae, rmse, mape = None, None, None
            if len(test_data) >= 5:
                test_pred = fitted.forecast(steps=len(test_data))
                mae, rmse, mape = compute_metrics(test_data, test_pred)

            # Retrain on full data + forecast
            full_model = ARIMA(series, order=(2, 1, 2))
            full_fitted = full_model.fit()
            forecast_vals = full_fitted.forecast(steps=FORECAST_HOURS)

            # Confidence interval (approx ±1.96*stderr)
            se = full_fitted.bse.mean() if len(full_fitted.bse) > 0 else 0
            ci_width = np.arange(1, FORECAST_HOURS + 1) * se * 0.5  # growing uncertainty

            # Lưu forecast points
            last_ts = df.index[-1]
            for i, val in enumerate(forecast_vals):
                pred_at = last_ts + pd.Timedelta(hours=i + 1)
                lower = max(0, float(val) - float(ci_width[i]))
                upper = float(val) + float(ci_width[i])
                point = ForecastPoint(
                    forecast_run_id=run_id,
                    station_id=station_uuid,
                    target_metric=metric,
                    predicted_at=pred_at.to_pydatetime(),
                    predicted_value=round(float(val), 2),
                    lower_bound=round(lower, 2),
                    upper_bound=round(upper, 2),
                )
                session.add(point)

            # Cập nhật run status
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            run.mae = mae
            run.rmse = rmse
            run.mape = mape

            await session.commit()

            logger.info("ARIMA %s @ %s — MAE=%.2f", metric, station_name, mae or 0)
            return True

        except Exception as e:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)[:500]
            await session.commit()
            raise
