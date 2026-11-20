from __future__ import annotations
import logging
import os
import threading
from config import settings
from config.logging import configure_logging
from application.processing_service import (
    DetectionAPIClient,
    ProcessingService,
)
from application.reading_result_handler import ReadingResultHandler
from application.delivery_worker import DeliveryWorker
from application.daily_report_scheduler import DailyReportScheduler
from application.temperature_report_service import TemperatureReportService
from infrastructure.database.mongodb.mongo import MongoDB
from infrastructure.database.mongodb.indexes import create_indexes
from infrastructure.database.mongodb.repositories import (
    MeasurementPointRepository,
    ReadingRepository,
    DeliveryOutboxRepository,
)
from infrastructure.yourcompany.erp_client import YourCompanyERPClient
from infrastructure.yourcompany.file_sink import LocalDeliveryFile
from infrastructure.notification.sms import GhasedakSmsClient


logger = logging.getLogger(__name__)

MAX_WORKERS = 32


def create_erp_client() -> YourCompanyERPClient | None:
    """Create ERP client if all required settings are available."""

    if not settings.YOURCOMPANY_ERP_ENABLED:
        logger.info("YOURCOMPANY ERP writes disabled; local file delivery enabled.")
        return None

    required_settings = {
        "host": os.getenv("YOURCOMPANY_DB_HOST"),
        "user": os.getenv("YOURCOMPANY_DB_USER"),
        "password": os.getenv("YOURCOMPANY_DB_PASSWORD"),
        "database": os.getenv("YOURCOMPANY_DB_NAME"),
    }

    missing = [
        name
        for name, value in required_settings.items()
        if not value
    ]

    if missing:
        logger.warning(
            "ERP integration disabled. Missing settings: %s",
            ", ".join(missing),
        )
        return None

    return YourCompanyERPClient(
        host=required_settings["host"],
        user=required_settings["user"],
        password=required_settings["password"],
        database=required_settings["database"],
    )


def create_daily_report_scheduler(
    erp_client: YourCompanyERPClient,
    measurement_repository: MeasurementPointRepository | None = None,
) -> DailyReportScheduler | None:
    """Create daily temperature report scheduler."""

    api_key = os.getenv("GHASEDAK_API_KEY")
    line_number = os.getenv("GHASEDAK_LINE_NUMBER")

    recipients_value = os.getenv(
        "DAILY_REPORT_RECIPIENTS",
        "",
    )

    recipients = [
        number.strip()
        for number in recipients_value.split(",")
        if number.strip()
    ]

    missing = []

    if not api_key:
        missing.append("GHASEDAK_API_KEY")

    if not line_number:
        missing.append("GHASEDAK_LINE_NUMBER")

    if not recipients:
        missing.append("DAILY_REPORT_RECIPIENTS")

    if missing:
        logger.warning(
            "Daily SMS report disabled. Missing settings: %s",
            ", ".join(missing),
        )
        return None

    sms_client = GhasedakSmsClient(
        api_key=api_key,
        line_number=line_number,
    )

    report_service = TemperatureReportService(
        erp_client=erp_client,
        sms_client=sms_client,
        recipients=recipients,
        measurement_repository=measurement_repository,
    )

    return DailyReportScheduler(
        report_job=report_service.send_yesterday_report,
    )


def main() -> None:
    configure_logging("worker")
    mongodb = MongoDB()

    service: ProcessingService | None = None
    delivery_worker: DeliveryWorker | None = None
    file_worker: DeliveryWorker | None = None
    file_thread: threading.Thread | None = None
    delivery_thread: threading.Thread | None = None
    daily_report_scheduler: DailyReportScheduler | None = None

    try:

        mongodb.connect()
        database = mongodb.database

        logger.info("MongoDB connection successful.")

        create_indexes(database)

        logger.info("MongoDB indexes created successfully.")

        camera_repository = MeasurementPointRepository(database)
        reading_repository = ReadingRepository(database)
        outbox_repository = DeliveryOutboxRepository(database)
        cancelled = outbox_repository.cancel_minute_policy_events()
        if cancelled:
            logger.warning("Cancelled obsolete minute-policy deliveries: count=%s", cancelled)

        if (not settings.YOURCOMPANY_ERP_ENABLED or outbox_repository.has_file_deliveries()
            or (settings.YOURCOMPANY_EXPORT_DIR / "records.sqlite3").is_file()):
            file_worker = DeliveryWorker(
                outbox_repository, file_sink=LocalDeliveryFile(settings.YOURCOMPANY_EXPORT_DIR, sources=camera_repository.list_active()),
            )
            file_thread = threading.Thread(target=file_worker.run_forever, name="File-Delivery-Worker", daemon=False)
            file_thread.start()
            logger.info("Local delivery reports: %s", settings.YOURCOMPANY_EXPORT_DIR)

        erp_client = create_erp_client()

        if erp_client is not None:
            delivery_worker = DeliveryWorker(
                outbox_repository=outbox_repository,
                erp_client=erp_client,
                poll_interval=2.0,
                lease_seconds=60,
            )

            delivery_thread = threading.Thread(
                target=delivery_worker.run_forever,
                name="ERP-Delivery-Worker",
                daemon=False,
            )

            delivery_thread.start()

            logger.info("ERP DeliveryWorker started.")

            if settings.DAILY_REPORT_ENABLED:
                daily_report_scheduler = create_daily_report_scheduler(
                    erp_client=erp_client,
                    measurement_repository=camera_repository,
                )

                if daily_report_scheduler is not None:
                    daily_report_scheduler.start()
                    logger.info("Daily temperature report scheduler started.")
            else:
                logger.info("Daily SMS report disabled by DAILY_REPORT_ENABLED.")

        elif settings.YOURCOMPANY_ERP_ENABLED:
            logger.warning("ERP delivery and daily report scheduler are unavailable: check YOURCOMPANY_DB settings.")
        else:
            logger.info("File delivery active; ERP delivery and ERP-backed daily reports are disabled.")

        cameras = camera_repository.list_active()

        logger.info(
            "Active cameras found: %s",
            len(cameras),
        )

        logger.info(
            "Maximum concurrent workers: %s",
            MAX_WORKERS,
        )

        for camera in cameras:
            logger.info(
                "Registered camera: %s",
                camera.get("camera_code"),
            )

        result_handler = ReadingResultHandler(
            repository=reading_repository,
            measurement_repository=camera_repository,
            outbox_repository=outbox_repository,
            destination="erp" if settings.YOURCOMPANY_ERP_ENABLED else "file",
        )

        detection_client = DetectionAPIClient()

        if cameras:
            service = ProcessingService(
                detection_client=detection_client,
                max_workers=MAX_WORKERS,
                result_handler=result_handler,
                camera_failure_handler=result_handler.handle_camera_failure,
            )

            logger.info(
                "Starting processing for all active cameras."
            )

            logger.info(
                "Total cameras: %s",
                len(cameras),
            )

        else:
            logger.warning(
                "No active cameras found. "
                "Background services will continue if enabled."
            )

        logger.info("All available services initialized.")
        logger.info("Press Ctrl+C to stop the application.")

        if service is not None:
            service.run_forever(cameras)

        elif (
            delivery_thread is not None
            or file_thread is not None
            or daily_report_scheduler is not None
        ):
            threading.Event().wait()

        else:
            logger.warning(
                "No active services available. Application will exit."
            )

    except KeyboardInterrupt:
        logger.info("Application shutdown requested.")

    except Exception:
        logger.exception("Application failed.")
        raise

    finally:

        if service is not None:
            logger.info("Stopping ProcessingService...")
            service.stop()

        if daily_report_scheduler is not None:
            logger.info("Stopping DailyReportScheduler...")
            daily_report_scheduler.stop()

        if delivery_worker is not None:
            logger.info("Stopping ERP DeliveryWorker...")
            delivery_worker.stop()

        if file_worker is not None:
            file_worker.stop()
        if file_thread is not None:
            file_thread.join()

        if delivery_thread is not None:
            delivery_thread.join()

        mongodb.close()

        logger.info("MongoDB connection closed.")
        logger.info("Application stopped.")


if __name__ == "__main__":
    main()
