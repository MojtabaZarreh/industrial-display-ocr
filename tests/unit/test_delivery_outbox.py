
from datetime import datetime, timezone
from uuid import uuid4

import mongomock
from infrastructure.database.mongodb.indexes import create_indexes
from infrastructure.database.mongodb.repositories import (
    DeliveryOutboxRepository,
)


def test_outbox_lifecycle():
    mongo = mongomock.MongoClient()
    database = mongo["outbox_tests"]
    create_indexes(database)

    repository = DeliveryOutboxRepository(database)

    test_id = uuid4().hex[:8].upper()
    camera_code = f"TEST-OUTBOX-{test_id}"

    event_ids = [
        f"{camera_code}-SENT",
        f"{camera_code}-FAILED",
        f"{camera_code}-DUPLICATE",
    ]

    try:
        event_id = event_ids[0]

        created = repository.create_event(
            event_id=event_id,
            camera_code=camera_code,
            scheduled_at=datetime.now(timezone.utc),
            erp_data={
                "Date": "1405/08/16",
                "Time": "08:00:00",
                "Temperature": 24,
                "CreateDateTime": "2026-11-07 08:00:00",
                "RecordType": 1,
            },
        )

        assert created is True

        print("PASS: Outbox event created.")

        duplicate_created = repository.create_event(
            event_id=event_id,
            camera_code=camera_code,
            scheduled_at=datetime.now(timezone.utc),
            erp_data={
                "Date": "1405/08/16",
                "Time": "08:00:00",
                "Temperature": 24,
                "CreateDateTime": "2026-11-07 08:00:00",
                "RecordType": 1,
            },
        )

        assert duplicate_created is False

        print("PASS: Duplicate event prevented.")

        claimed_event = repository.claim_next_event()

        assert claimed_event is not None
        assert claimed_event["event_id"] == event_id
        assert claimed_event["status"] == "processing"
        assert claimed_event["attempts"] == 1

        print("PASS: Pending event claimed successfully.")

        sent = repository.mark_as_sent(event_id)

        assert sent is True

        saved_event = repository._collection.find_one({
            "event_id": event_id
        })

        assert saved_event is not None
        assert saved_event["status"] == "sent"
        assert saved_event["sent_at"] is not None

        print("PASS: Event marked as sent.")

        failed_event_id = event_ids[1]

        repository.create_event(
            event_id=failed_event_id,
            camera_code=camera_code,
            scheduled_at=datetime.now(timezone.utc),
            erp_data={
                "Date": "1405/08/16",
                "Time": "08:01:00",
                "Temperature": 25,
                "CreateDateTime": "2026-11-07 08:01:00",
                "RecordType": 1,
            },
        )

        failed_claim = repository.claim_next_event()

        assert failed_claim is not None
        assert failed_claim["event_id"] == failed_event_id

        failed = repository.mark_as_failed(
            failed_event_id,
            "Test ERP connection error",
        )

        assert failed is True

        failed_document = repository._collection.find_one({
            "event_id": failed_event_id
        })

        assert failed_document is not None
        assert failed_document["status"] == "pending"
        assert failed_document["attempts"] == 1
        assert failed_document["last_error"] == (
            "Test ERP connection error"
        )
        next_attempt_at = failed_document["next_attempt_at"]

        if next_attempt_at.tzinfo is None:
            next_attempt_at = next_attempt_at.replace(
                tzinfo=timezone.utc
            )

        assert next_attempt_at > datetime.now(timezone.utc)

        print("PASS: Failed event scheduled for retry.")

        result = repository.mark_as_failed(
            "NON-EXISTENT-EVENT",
            "Test error",
        )

        assert result is False

        print("PASS: Unknown event failure handled.")

        result = repository.mark_as_sent(
            "NON-EXISTENT-EVENT"
        )

        assert result is False

        print("PASS: Unknown event success handled.")

        print("\nAll DeliveryOutbox tests passed.")

    finally:
        repository._collection.delete_many({
            "event_id": {"$in": event_ids}
        })

        mongo.close()


if __name__ == "__main__":
    test_outbox_lifecycle()
