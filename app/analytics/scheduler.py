"""
APScheduler cho analytics jobs.
Schedule:
  - Daily summary:      01:00 mỗi ngày
  - Anomaly detection:  mỗi 2 giờ
  - Prophet forecast:   02:00 mỗi ngày
  - ARIMA forecast:     02:30 mỗi ngày
  - Linear forecast:    03:00 mỗi ngày
  - Seasonal analysis:  03:30 mỗi ngày (chạy 1 lần/ngày là đủ)
  - Correlation:        04:00 mỗi ngày
  - Trend analysis:     04:30 mỗi ngày
  - Health impact:      mỗi 2 giờ (cùng anomaly, vì cần realtime)
"""

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    return _scheduler


# --- Job wrappers (lazy import để tránh circular) ---

async def _run_daily_summary():
    from app.analytics.daily_summary import compute_daily_summaries
    try:
        count = await compute_daily_summaries()
        logger.info("[Scheduler] Daily summary done — %d stations", count)
    except Exception as e:
        logger.error("[Scheduler] Daily summary failed: %s", e)


async def _run_anomaly_detection():
    from app.analytics.anomaly_detection import detect_anomalies
    try:
        count = await detect_anomalies()
        logger.info("[Scheduler] Anomaly detection done — %d anomalies", count)
    except Exception as e:
        logger.error("[Scheduler] Anomaly detection failed: %s", e)


async def _run_prophet_forecast():
    from app.analytics.forecast_prophet import run_prophet_forecast
    try:
        count = await run_prophet_forecast("aqi")
        logger.info("[Scheduler] Prophet forecast done — %d stations", count)
    except Exception as e:
        logger.error("[Scheduler] Prophet forecast failed: %s", e)


async def _run_arima_forecast():
    from app.analytics.forecast_arima import run_arima_forecast
    try:
        count = await run_arima_forecast("aqi")
        logger.info("[Scheduler] ARIMA forecast done — %d stations", count)
    except Exception as e:
        logger.error("[Scheduler] ARIMA forecast failed: %s", e)


async def _run_linear_forecast():
    from app.analytics.forecast_linear import run_linear_forecast
    try:
        count = await run_linear_forecast("aqi")
        logger.info("[Scheduler] Linear forecast done — %d stations", count)
    except Exception as e:
        logger.error("[Scheduler] Linear forecast failed: %s", e)


async def _run_seasonal():
    from app.analytics.seasonal import compute_seasonal_analysis
    try:
        count = await compute_seasonal_analysis("aqi")
        logger.info("[Scheduler] Seasonal analysis done — %d stations", count)
    except Exception as e:
        logger.error("[Scheduler] Seasonal analysis failed: %s", e)


async def _run_correlation():
    from app.analytics.correlation import compute_correlation_analysis
    try:
        count = await compute_correlation_analysis()
        logger.info("[Scheduler] Correlation analysis done — %d stations", count)
    except Exception as e:
        logger.error("[Scheduler] Correlation analysis failed: %s", e)


async def _run_trend():
    from app.analytics.trend import compute_trend_analysis
    try:
        count = await compute_trend_analysis()
        logger.info("[Scheduler] Trend analysis done — %d stations", count)
    except Exception as e:
        logger.error("[Scheduler] Trend analysis failed: %s", e)


async def _run_health_impact():
    from app.analytics.health_impact import compute_health_impact
    try:
        count = await compute_health_impact()
        logger.info("[Scheduler] Health impact done — %d stations", count)
    except Exception as e:
        logger.error("[Scheduler] Health impact failed: %s", e)


async def _run_grid_ingest():
    from app.grid_ingest.openmeteo_grid import run_grid_ingest
    try:
        stats = await run_grid_ingest()
        logger.info(
            "[Scheduler] Grid ingest done — total=%d, fetched=%d, inserted=%d",
            stats["total"], stats["fetched"], stats["inserted"],
        )
    except Exception as e:
        logger.error("[Scheduler] Grid ingest failed: %s", e)


def start_analytics_scheduler():
    """Khởi động scheduler. Gọi 1 lần trong app startup."""
    if os.environ.get("ANALYTICS_ENABLED", "true").lower() != "true":
        logger.info("Analytics scheduler disabled (ANALYTICS_ENABLED != true)")
        return

    scheduler = get_scheduler()

    # Daily summary — 01:00
    summary_cron = os.environ.get("ANALYTICS_SUMMARY_CRON", "0 1 * * *")
    scheduler.add_job(
        _run_daily_summary,
        CronTrigger.from_crontab(summary_cron),
        id="daily_summary",
        replace_existing=True,
    )

    # Anomaly detection — mỗi 2 giờ
    anomaly_cron = os.environ.get("ANALYTICS_ANOMALY_CRON", "0 */2 * * *")
    scheduler.add_job(
        _run_anomaly_detection,
        CronTrigger.from_crontab(anomaly_cron),
        id="anomaly_detection",
        replace_existing=True,
    )

    # Prophet forecast — 02:00
    prophet_cron = os.environ.get("ANALYTICS_PROPHET_CRON", "0 2 * * *")
    scheduler.add_job(
        _run_prophet_forecast,
        CronTrigger.from_crontab(prophet_cron),
        id="prophet_forecast",
        replace_existing=True,
    )

    # ARIMA forecast — 02:30
    arima_cron = os.environ.get("ANALYTICS_ARIMA_CRON", "30 2 * * *")
    scheduler.add_job(
        _run_arima_forecast,
        CronTrigger.from_crontab(arima_cron),
        id="arima_forecast",
        replace_existing=True,
    )

    # Linear forecast — 03:00
    linear_cron = os.environ.get("ANALYTICS_LINEAR_CRON", "0 3 * * *")
    scheduler.add_job(
        _run_linear_forecast,
        CronTrigger.from_crontab(linear_cron),
        id="linear_forecast",
        replace_existing=True,
    )

    # Seasonal analysis — 03:30
    seasonal_cron = os.environ.get("ANALYTICS_SEASONAL_CRON", "30 3 * * *")
    scheduler.add_job(
        _run_seasonal,
        CronTrigger.from_crontab(seasonal_cron),
        id="seasonal_analysis",
        replace_existing=True,
    )

    # Correlation — 04:00
    correlation_cron = os.environ.get("ANALYTICS_CORRELATION_CRON", "0 4 * * *")
    scheduler.add_job(
        _run_correlation,
        CronTrigger.from_crontab(correlation_cron),
        id="correlation_analysis",
        replace_existing=True,
    )

    # Trend analysis — 04:30
    trend_cron = os.environ.get("ANALYTICS_TREND_CRON", "30 4 * * *")
    scheduler.add_job(
        _run_trend,
        CronTrigger.from_crontab(trend_cron),
        id="trend_analysis",
        replace_existing=True,
    )

    # Health impact — mỗi 2 giờ (offset 30 phút so với anomaly)
    health_cron = os.environ.get("ANALYTICS_HEALTH_CRON", "30 */2 * * *")
    scheduler.add_job(
        _run_health_impact,
        CronTrigger.from_crontab(health_cron),
        id="health_impact",
        replace_existing=True,
    )

    # Grid ingest — mỗi 3 giờ (phút 5 để tránh đụng anomaly ở phút 0)
    grid_cron = os.environ.get("GRID_INGEST_CRON", "5 */3 * * *")
    scheduler.add_job(
        _run_grid_ingest,
        CronTrigger.from_crontab(grid_cron),
        id="grid_ingest",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Analytics scheduler started with %d jobs: "
        "summary=%s, anomaly=%s, prophet=%s, arima=%s, linear=%s, "
        "seasonal=%s, correlation=%s, trend=%s, health=%s, grid=%s",
        len(scheduler.get_jobs()),
        summary_cron, anomaly_cron, prophet_cron, arima_cron, linear_cron,
        seasonal_cron, correlation_cron, trend_cron, health_cron, grid_cron,
    )


def stop_analytics_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Analytics scheduler stopped")
    _scheduler = None
