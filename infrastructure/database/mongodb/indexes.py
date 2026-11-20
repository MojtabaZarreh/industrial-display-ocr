
from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

def create_indexes(database: Database) -> None:
    database["measurement_points"].create_index(
        [("camera_code", ASCENDING)],
        unique=True,
        name="uq_measurement_points_camera_code",
    )

    database["readings"].create_index(
        [("reading_id", ASCENDING)],
        unique=True,
        name="uq_readings_reading_id",
    )

    database["readings"].create_index(
        [
            ("camera_code", ASCENDING),
            ("captured_at", DESCENDING),
        ],
        name="ix_readings_camera_captured_at",
    )

    database["measurement_states"].create_index(
        [("camera_code", ASCENDING)],
        unique=True,
        name="uq_measurement_states_camera_code",
    )

    database["delivery_outbox"].create_index(
        [("event_id", ASCENDING)],
        unique=True,
        name="uq_delivery_outbox_event_id",
    )

    database["delivery_outbox"].create_index(
        [
            ("status", ASCENDING),
            ("next_attempt_at", ASCENDING),
        ],
        name="ix_delivery_outbox_status_next_attempt",
    )

    database["delivery_outbox"].create_index(
        [("destination", ASCENDING), ("status", ASCENDING), ("next_attempt_at", ASCENDING)],
        name="ix_delivery_outbox_destination_status_next_attempt",
    )
