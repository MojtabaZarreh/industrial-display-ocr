from __future__ import annotations
import logging
from collections.abc import Callable
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
TEHRAN_TIMEZONE = pytz.timezone("Asia/Tehran")

class DailyReportScheduler:
    def __init__(self, report_job: Callable[[], None]) -> None:
        self._report_job = report_job
        self._scheduler = BackgroundScheduler(timezone=TEHRAN_TIMEZONE)

    def start(self) -> None:
        if self._scheduler.running:
            logger.warning("Daily report scheduler is already running.")
            return

        self._scheduler.add_job(
            func=self._execute_report,
            trigger=CronTrigger(hour=6, minute=1, timezone=TEHRAN_TIMEZONE),
            id="daily_temperature_report",
            name="Daily Temperature Report",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
            replace_existing=True,
        )

        self._scheduler.start()

        logger.info(
            "Daily report scheduler started. "
            "Next execution: every day at 06:01 Asia/Tehran."
        )

    def _execute_report(self) -> None:
        logger.info("Starting daily temperature report.")
        try:
            self._report_job()
            logger.info("Daily temperature report completed successfully.")
        except Exception:
            logger.exception("Daily temperature report failed.")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Daily report scheduler stopped.")
