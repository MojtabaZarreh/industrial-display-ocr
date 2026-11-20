
import logging
from application.processing_service import DetectionAPIClient, ProcessingService
from infrastructure.database.mongodb.mongo import MongoDB
from infrastructure.database.mongodb.repositories import MeasurementPointRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> None:
    mongodb = MongoDB()
    service = None

    try:
        mongodb.connect()

        repository = MeasurementPointRepository(mongodb.database)
        cameras = repository.list_active()

        service = ProcessingService(
            detection_client=DetectionAPIClient(),
            max_workers=16,
        )

        logger_message = f"Active cameras loaded: {len(cameras)}"
        print(logger_message)
        print("Press Ctrl+C to stop.")

        service.run_forever(cameras)

    except KeyboardInterrupt:
        print("Stopping camera processing...")

    finally:
        if service is not None:
            service.stop()

        mongodb.close()


if __name__ == "__main__":
    main()
