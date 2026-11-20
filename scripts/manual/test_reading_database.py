
import logging
from datetime import datetime, timezone
from uuid import uuid4
from infrastructure.database.mongodb.mongo import MongoDB
from infrastructure.database.mongodb.repositories import ReadingRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

def main() -> None:
    mongodb = MongoDB()
    reading_id = str(uuid4())
    camera_code = f"TEST-{uuid4().hex[:8].upper()}"

    try:
        mongodb.connect()
        logger.info("MongoDB connection successful.")

        repository = ReadingRepository(mongodb.database)

        repository.save(
            reading_id=reading_id,
            camera_code=camera_code,
            captured_at=datetime.now(timezone.utc),
            value=6575,
            status="anomaly",
            reasons=["database_test"],
            inference_id=str(uuid4()),
            model="paddle",
            confidence=0.9999,
        )

        saved_reading = mongodb.database["readings"].find_one(
            {"reading_id": reading_id}
        )

        assert saved_reading is not None, "Reading was not saved."
        assert saved_reading["camera_code"] == camera_code
        assert saved_reading["value"] == 6575
        assert saved_reading["status"] == "anomaly"

        logger.info("Reading saved and verified successfully.")
        logger.info("Reading ID: %s", reading_id)
        logger.info("Camera code: %s", camera_code)
        logger.info("Value: %s", saved_reading["value"])
        logger.info("Status: %s", saved_reading["status"])

    except Exception:
        logger.exception("Database reading test failed.")
        raise

    finally:
        try:
            mongodb.close()
        except Exception:
            logger.exception("Failed to close MongoDB connection.")


if __name__ == "__main__":
    main()
