"""
Linear Regression baseline forecast.
Dùng làm baseline so sánh với Prophet và ARIMA.
Features: hour_of_day, day_of_week, rolling_mean_6h, rolling_std_6h.
"""

import logging
import uuid
from datetime import timezone, datetime

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from app.db import fetch, get_session
from app.models.forecast import ForecastRun, ForecastPoint
from app.analytics.evaluation import compute_metrics

logger = logging.getLogger(__name__)

TRAINING_DAYS = 14
FORECAST_HOURS = 24
MIN_TRAINING_ROWS = 48
VALID_METRICS = ["aqi", "pm25", "pm10", "o3", "no2", "so2", "co"]


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Tạo features từ timestamp."""
    features = pd.DataFrame(index=df.index)
    features["hour"] = df.index.hour
    features["day_of_week"] = df.index.dayofweek
    features["hour_sin"] = np.sin(2 * np.pi * features["hour"] / 24)
    features["hour_cos"] = np.cos(2 * np.pi * features["hour"] / 24)
    features["dow_sin"] = np.sin(2 * np.pi * features["day_of_week"] / 7)
    features["dow_cos"] = np.cos(2 * np.pi * features["day_of_week"] / 7)

    # Rolling statistics
    if "y" in df.columns:
        features["rolling_mean_6h"] = df["y"].rolling(6, min_periods=1).mean()
        features["rolling_std_6h"] = df["y"].rolling(6, min_periods=1).std().fillna(0)
        features["rolling_mean_24h"] = df["y"].rolling(24, min_periods=1).mean()
        features["lag_1h"] = df["y"].shift(1).bfill()
        features["lag_24h"] = df["y"].shift(24).bfill()

    return features.fillna(0)


async def run_linear_forecast(target_metric: str = "aqi") -> int:
    """Linear Regression forecast cho mỗi station."""
    logger.info("Starting Linear Regression forecast for metric=%s", target_metric)

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
            logger.error("Linear failed for station %s: %s", station["name"], e)

    logger.info("Linear forecast done — %d stations processed", count)
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
            model_type="linear",
            target_metric=metric,
            horizon_hours=FORECAST_HOURS,
            training_rows=len(df),
            status="running",
        )
        session.add(run)
        await session.flush()  # Get run.id
        run_id = run.id

        try:
            features = _build_features(df)
            X = features.values
            y = df["y"].values

            # 80/20 split
            split = int(len(X) * 0.8)
            X_train, X_test = X[:split], X[split:]
            y_train, y_test = y[:split], y[split:]

            model = LinearRegression()
            model.fit(X_train, y_train)

            mae, rmse, mape = None, None, None
            if len(y_test) >= 5:
                y_pred_test = model.predict(X_test)
                mae, rmse, mape = compute_metrics(y_test, y_pred_test)

            # Retrain full
            model.fit(X, y)

            # Forecast future hours
            last_ts = df.index[-1]
            future_idx = pd.date_range(last_ts + pd.Timedelta(hours=1), periods=FORECAST_HOURS, freq="h")
            future_df = pd.DataFrame({"y": [df["y"].iloc[-1]] * FORECAST_HOURS}, index=future_idx)

            # Iterative forecast: dùng prediction trước làm input cho lần sau
            predictions = []
            last_val = df["y"].iloc[-1]
            rolling_vals = list(df["y"].values[-24:])

            for i, ts in enumerate(future_idx):
                feat = {
                    "hour": ts.hour,
                    "day_of_week": ts.dayofweek,
                    "hour_sin": np.sin(2 * np.pi * ts.hour / 24),
                    "hour_cos": np.cos(2 * np.pi * ts.hour / 24),
                    "dow_sin": np.sin(2 * np.pi * ts.dayofweek / 7),
                    "dow_cos": np.cos(2 * np.pi * ts.dayofweek / 7),
                    "rolling_mean_6h": np.mean(rolling_vals[-6:]),
                    "rolling_std_6h": np.std(rolling_vals[-6:]) if len(rolling_vals) >= 6 else 0,
                    "rolling_mean_24h": np.mean(rolling_vals[-24:]),
                    "lag_1h": last_val,
                    "lag_24h": rolling_vals[-24] if len(rolling_vals) >= 24 else last_val,
                }
                X_fut = np.array([list(feat.values())])
                pred = float(model.predict(X_fut)[0])
                pred = max(0, pred)  # AQI cannot be negative
                predictions.append(pred)
                rolling_vals.append(pred)
                last_val = pred

            # Residual-based confidence interval
            y_train_pred = model.predict(X)
            residual_std = float(np.std(y - y_train_pred))

            for i, (ts, val) in enumerate(zip(future_idx, predictions)):
                ci = residual_std * (1 + i * 0.05)  # growing uncertainty
                point = ForecastPoint(
                    forecast_run_id=run_id,
                    station_id=station_uuid,
                    target_metric=metric,
                    predicted_at=ts.to_pydatetime(),
                    predicted_value=round(val, 2),
                    lower_bound=round(max(0, val - 1.96 * ci), 2),
                    upper_bound=round(val + 1.96 * ci, 2),
                )
                session.add(point)

            # Cập nhật run status
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            run.mae = mae
            run.rmse = rmse
            run.mape = mape

            await session.commit()

            logger.info("Linear %s @ %s — MAE=%.2f", metric, station_name, mae or 0)
            return True

        except Exception as e:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)[:500]
            await session.commit()
            raise
