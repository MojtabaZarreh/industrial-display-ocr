
from datetime import datetime, timezone
from infrastructure.database.mongodb.repositories import ReadingRepository

def test_get_latest_valid_reading(database):
    repository = ReadingRepository(database)

    camera_code = "TEST-LATEST-001"

    repository._readings.insert_many([
        {
            "reading_id": "reading-1",
            "camera_code": camera_code,
            "captured_at": datetime(2026, 11, 7, 8, 0, tzinfo=timezone.utc),
            "value": 24,
            "status": "valid",
        },
        {
            "reading_id": "reading-2",
            "camera_code": camera_code,
            "captured_at": datetime(2026, 11, 7, 8, 1, tzinfo=timezone.utc),
            "value": 900,
            "status": "review",
        },
        {
            "reading_id": "reading-3",
            "camera_code": camera_code,
            "captured_at": datetime(2026, 11, 7, 8, 2, tzinfo=timezone.utc),
            "value": 26,
            "status": "valid",
        },
    ])

    result = repository.get_recent_valid_values(camera_code)

    assert result == [24, 26]

    repository._readings.delete_many({"camera_code": camera_code})

    print("PASS: Latest valid reading retrieved successfully.")
