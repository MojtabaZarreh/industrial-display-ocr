from datetime import datetime, timezone, timedelta
from typing import Any, Mapping
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from collections.abc import Sequence
from pymongo import ReturnDocument
from domain.measurements import resolve_unit


class MeasurementPointRepository:
    def __init__(self, database: Database) -> None:
        self._collection: Collection = database["measurement_points"]

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        required_fields = {
            "camera_code",
            "name",
            "rtsp_url",
            "schedule_interval",
            "danger_threshold",
        }

        missing_fields = required_fields - data.keys()
        if missing_fields:
            raise ValueError(
                f"Missing required fields: {', '.join(sorted(missing_fields))}"
            )

        document = data.copy()
        document["camera_code"] = document["camera_code"].strip().upper()
        document["unit"] = resolve_unit(document["camera_code"], document.get("unit"))
        now = datetime.now(timezone.utc)

        document.setdefault("description", "")
        document.setdefault("is_active", True)
        document["created_at"] = now
        document["updated_at"] = now

        if document["schedule_interval"] <= 0:
            raise ValueError("schedule_interval must be greater than zero.")

        try:
            result = self._collection.insert_one(document)
        except DuplicateKeyError as exc:
            raise ValueError(
                f"Camera code '{document['camera_code']}' already exists."
            ) from exc

        document["_id"] = result.inserted_id
        return document

    def get_by_code(self, camera_code: str) -> dict[str, Any] | None:
        normalized_code = camera_code.strip().upper()
        camera = self._collection.find_one({
            "camera_code": normalized_code,
        })
        if camera is not None:
            camera["unit"] = resolve_unit(normalized_code, camera.get("unit"))
        return camera

    def list_active(self) -> list[dict[str, Any]]:
        cameras = list(
            self._collection.find({"is_active": True}).sort("camera_code", 1)
        )
        for camera in cameras:
            camera["unit"] = resolve_unit(camera["camera_code"], camera.get("unit"))
        return cameras

    def update(self, camera_code: str, updates: dict[str, Any]) -> bool:
        allowed_fields = {
            "name",
            "rtsp_url",
            "description",
            "schedule_interval",
            "danger_threshold",
            "is_active",
            "unit",
        }

        if not updates:
            raise ValueError("No updates were provided.")

        invalid_fields = updates.keys() - allowed_fields
        if invalid_fields:
            raise ValueError(
                f"Fields cannot be updated: {', '.join(sorted(invalid_fields))}"
            )

        if (
            "schedule_interval" in updates
            and updates["schedule_interval"] <= 0
        ):
            raise ValueError("schedule_interval must be greater than zero.")

        normalized_code = camera_code.strip().upper()
        updates = dict(updates)
        if "unit" in updates:
            if updates["unit"] is None:
                raise ValueError("unit cannot be null.")
            updates["unit"] = resolve_unit(normalized_code, updates["unit"])

        result = self._collection.update_one(
            {"camera_code": normalized_code},
            {
                "$set": {
                    **updates,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        return result.matched_count > 0

    def deactivate(self, camera_code: str) -> bool:
        return self.update(camera_code, {"is_active": False})


class ReadingRepository:
    def __init__(self, database: Database) -> None:
        self._readings: Collection = database["readings"]
        self._states: Collection = database["measurement_states"]

    def save(
        self,
        *,
        reading_id: str,
        camera_code: str,
        captured_at: datetime,
        value: int | None,
        status: str,
        reasons: Sequence[str] = (),
        inference_id: str | None = None,
        model: str | None = None,
        confidence: float | None = None,
        is_anomaly: bool = False,
        erp_value: int | None = None,
        fallback_reading_id: str | None = None,
    ) -> dict[str, Any]:
        allowed_statuses = {"valid", "anomaly", "review"}

        if status not in allowed_statuses:
            raise ValueError("Unsupported reading status.")

        if not reading_id.strip() or not camera_code.strip():
            raise ValueError("Reading ID and camera code are required.")

        if status in {"valid", "anomaly"} and value is None:
            raise ValueError("A numeric value is required for this status.")

        document = {
            "reading_id": reading_id,
            "camera_code": camera_code.strip().upper(),
            "captured_at": captured_at,
            "value": value,
            "status": status,
            "reasons": list(reasons),
            "inference_id": inference_id,
            "model": model,
            "confidence": confidence,
            "is_anomaly": is_anomaly,
            "erp_value": erp_value,
            "fallback_reading_id": fallback_reading_id,
            "created_at": datetime.now(timezone.utc),
        }

        self._readings.insert_one(document)

        if status == "valid":
            self._states.update_one(
                {"camera_code": document["camera_code"]},
                {
                    "$set": {
                        "camera_code": document["camera_code"],
                        "latest_value": value,
                        "latest_reading_id": reading_id,
                        "latest_captured_at": captured_at,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )

        return document

    def get_recent_valid_values(
        self,
        camera_code: str,
        *,
        limit: int = 10,
    ) -> list[int]:
        if limit < 1:
            raise ValueError("Limit must be at least 1.")

        cursor = (
            self._readings.find(
                {
                    "camera_code": camera_code.strip().upper(),
                    "status": "valid",
                    "value": {"$type": "number"},
                },
                {"_id": 0, "value": 1},
            )
            .sort("captured_at", -1)
            .limit(limit)
        )

        values = [int(item["value"]) for item in cursor]
        values.reverse()
        return values

    def get_latest_valid_reading(self, camera_code: str, *, before: datetime | None = None) -> dict[str, Any] | None:
        query = {
            "camera_code": camera_code.strip().upper(),
            "status": "valid",
            "value": {"$type": "number"},
            "$or": [{"is_anomaly": {"$ne": True}}, {"value": 0}],
        }
        if before is not None:
            query["captured_at"] = {"$lt": before}
        return self._readings.find_one(query, sort=[("captured_at", -1), ("_id", -1)])

    def get_recent_nonzero_valid_values(self, camera_code: str, *, limit: int = 10, before: datetime | None = None) -> list[int]:
        if limit < 1:
            raise ValueError("Limit must be at least 1.")

        query = {
            "camera_code": camera_code.strip().upper(),
            "status": "valid",
            "is_anomaly": {"$ne": True},
            "value": {"$type": "number", "$gt": 0},
        }
        if before is not None:
            query["captured_at"] = {"$lt": before}

        cursor = self._readings.find(query, {"_id": 0, "value": 1}).sort([
            ("captured_at", -1), ("_id", -1),
        ]).limit(limit)
        return list(reversed([int(item["value"]) for item in cursor]))

class DeliveryOutboxRepository:
    def __init__(self, database: Database) -> None:
        self._collection: Collection = database["delivery_outbox"]

    def create_event(
        self,
        *,
        event_id: str,
        camera_code: str,
        scheduled_at: datetime,
        erp_data: Mapping[str, Any],
        destination: str = "erp",
        source: Mapping[str, Any] | None = None,
    ) -> bool:
        if not event_id or not event_id.strip():
            raise ValueError("event_id cannot be empty.")

        if not camera_code or not camera_code.strip():
            raise ValueError("camera_code cannot be empty.")

        if not isinstance(erp_data, Mapping) or not erp_data:
            raise ValueError("erp_data must be a non-empty mapping.")

        if destination not in {"erp", "file"}:
            raise ValueError("Unsupported delivery destination.")

        now = datetime.now(timezone.utc)

        document = {
            "destination": destination,
            "source": dict(source or {}),
            "event_id": event_id,
            "camera_code": camera_code.strip().upper(),
            "scheduled_at": scheduled_at,
            "erp_data": dict(erp_data),
            "status": "pending",
            "attempts": 0,
            "next_attempt_at": now,
            "created_at": now,
            "updated_at": now,
            "sent_at": None,
            "last_error": None,
            "lease_until": None,
        }

        try:
            self._collection.insert_one(document)
            return True
        except DuplicateKeyError:
            return False

    def cancel_minute_policy_events(self) -> int:
        result = self._collection.update_many(
            {
                "event_id": {"$regex": "^minute:"},
                "erp_data.MinuteSlot": True,
                "status": {"$in": ["pending", "processing"]},
            },
            {"$set": {
                "status": "cancelled",
                "last_error": "minute_backfill_policy_removed",
                "lease_until": None,
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        return result.modified_count

    def has_file_deliveries(self) -> bool:
        return self._collection.find_one({"destination": "file", "status": {"$in": ["pending", "processing"]}}) is not None

    def claim_next_event(
        self,
        *,
        lease_seconds: int = 60,
        destination: str = "erp",
    ) -> dict[str, Any] | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive.")

        if destination not in {"erp", "file"}:
            raise ValueError("Unsupported delivery destination.")
        route = {"$or": [{"destination": "erp"}, {"destination": {"$exists": False}}]} if destination == "erp" else {"destination": "file"}
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=lease_seconds)

        event = self._collection.find_one_and_update(
            {
                "$and": [route],
                "$or": [
                    {
                        "status": "pending",
                        "next_attempt_at": {"$lte": now},
                    },
                    {
                        "status": "processing",
                        "lease_until": {"$lte": now},
                    },
                ]
            },
            {
                "$set": {
                    "status": "processing",
                    "lease_until": lease_until,
                    "updated_at": now,
                },
                "$inc": {
                    "attempts": 1,
                },
            },
            sort=[
                ("next_attempt_at", 1),
                ("created_at", 1),
            ],
            return_document=ReturnDocument.AFTER,
        )

        return event

    def mark_as_sent(self, event_id: str) -> bool:
        now = datetime.now(timezone.utc)

        result = self._collection.update_one(
            {
                "event_id": event_id,
                "status": "processing",
            },
            {
                "$set": {
                    "status": "sent",
                    "sent_at": now,
                    "updated_at": now,
                    "last_error": None,
                },
                "$unset": {
                    "lease_until": "",
                },
            },
        )

        return result.modified_count == 1

    def mark_as_failed(
        self,
        event_id: str,
        error: str,
    ) -> bool:
        event = self._collection.find_one(
            {
                "event_id": event_id,
                "status": "processing",
            },
            {
                "attempts": 1,
            },
        )

        if event is None:
            return False

        attempts = max(1, int(event.get("attempts", 1)))
        retry_seconds = min(2 ** min(attempts, 8), 300)
        now = datetime.now(timezone.utc)

        result = self._collection.update_one(
            {
                "event_id": event_id,
                "status": "processing",
            },
            {
                "$set": {
                    "status": "pending",
                    "next_attempt_at": now + timedelta(seconds=retry_seconds),
                    "updated_at": now,
                    "last_error": str(error)[:2000],
                },
                "$unset": {
                    "lease_until": "",
                },
            },
        )

        return result.modified_count == 1
