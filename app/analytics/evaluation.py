"""
G3.6 — Evaluation metrics: MAE, RMSE, MAPE.
Dùng cho forecast evaluation và model comparison.
"""

import numpy as np


def compute_metrics(
    actual: np.ndarray, predicted: np.ndarray
) -> tuple[float | None, float | None, float | None]:
    """
    Tính MAE, RMSE, MAPE từ actual vs predicted.
    Trả (mae, rmse, mape) hoặc (None, None, None) nếu data rỗng.
    """
    actual = np.asarray(actual, dtype=np.float64)
    predicted = np.asarray(predicted, dtype=np.float64)

    # Loại bỏ NaN
    mask = ~(np.isnan(actual) | np.isnan(predicted))
    actual = actual[mask]
    predicted = predicted[mask]

    if len(actual) == 0:
        return None, None, None

    errors = actual - predicted

    # MAE — Mean Absolute Error
    mae = float(np.mean(np.abs(errors)))

    # RMSE — Root Mean Squared Error
    rmse = float(np.sqrt(np.mean(errors ** 2)))

    # MAPE — Mean Absolute Percentage Error (tránh chia 0)
    nonzero = actual != 0
    if np.any(nonzero):
        mape = float(np.mean(np.abs(errors[nonzero] / actual[nonzero])) * 100)
    else:
        mape = None

    return round(mae, 3), round(rmse, 3), round(mape, 3) if mape is not None else None
