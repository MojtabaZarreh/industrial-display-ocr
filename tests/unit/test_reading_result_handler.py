from datetime import datetime, timedelta, timezone
from uuid import uuid4

import mongomock
import pytest
from PIL import Image

from application.camera_worker import CapturedFrame
from application.delivery_worker import DeliveryWorker
from application.reading_result_handler import ReadingResultHandler
from infrastructure.database.mongodb.repositories import (
    DeliveryOutboxRepository, MeasurementPointRepository, ReadingRepository,
)

CAPTURED_AT = datetime(2026, 11, 17, 3, 30, tzinfo=timezone.utc)


class FakeERPClient:
    def __init__(self, fail_once=False):
        self.records = []
        self.fail_once = fail_once

    def insert_temperature(self, data):
        if self.fail_once:
            self.fail_once = False
            raise ConnectionError("ERP unavailable")
        self.records.append(dict(data))


@pytest.fixture
def database():
    client = mongomock.MongoClient(tz_aware=True)
    database = client["reading_tests"]
    database.readings.create_index("reading_id", unique=True)
    database.measurement_states.create_index("camera_code", unique=True)
    database.delivery_outbox.create_index("event_id", unique=True)
    yield database
    client.close()


@pytest.fixture
def repository(database):
    return ReadingRepository(database)


@pytest.fixture
def handler(database, repository):
    database.measurement_points.insert_many([
        {"camera_code": "AMP-001", "description": "Production line"},
        {"camera_code": "SRC-001", "description": "Server room"},
    ])
    return ReadingResultHandler(
        repository=repository,
        measurement_repository=MeasurementPointRepository(database),
        outbox_repository=DeliveryOutboxRepository(database),
    )


def make_result(model, value, confidence=0.99):
    camera_code = "AMP-001" if model == "paddle" else "SRC-001"
    predictions = (
        [{"text": str(value), "confidence": confidence}]
        if model == "paddle" else [
            {"class": f"D{digit}", "class_id": int(digit), "x": index * 10,
             "confidence": confidence}
            for index, digit in enumerate(str(value))
        ]
    )
    return {"inference_id": str(uuid4()), "camera_code": camera_code,
            "model": model, "predictions": predictions}


def process(handler, result, captured_at=CAPTURED_AT):
    handler(CapturedFrame(
        camera_code=result["camera_code"], image=Image.new("RGB", (20, 10)),
        captured_at=captured_at,
    ), result)


def seed_history(repository, camera_code):
    for offset in range(3, 0, -1):
        repository.save(
            reading_id=str(uuid4()), camera_code=camera_code,
            captured_at=CAPTURED_AT - timedelta(minutes=offset),
            value=100, status="valid",
        )


@pytest.mark.parametrize("model", ["paddle", "yolo"])
def test_stop_and_restart_reach_erp_without_gaps(model, database, repository, handler):
    camera_code = "AMP-001" if model == "paddle" else "SRC-001"
    seed_history(repository, camera_code)
    values = [0] * 12 + [100, 105, 110]
    erp = FakeERPClient()
    worker = DeliveryWorker(DeliveryOutboxRepository(database), erp)

    for index, value in enumerate(values):
        captured_at = CAPTURED_AT + timedelta(minutes=index)
        result = make_result(model, value)
        process(handler, result, captured_at)
        reading = database.readings.find_one({"reading_id": result["inference_id"]})
        assert reading["status"] == "valid"
        assert reading["value"] == value
        assert reading["captured_at"] == captured_at
        state = database.measurement_states.find_one({"camera_code": camera_code})
        assert state["latest_value"] == value
        assert state["latest_captured_at"] == captured_at
        event = database.delivery_outbox.find_one({"event_id": f"reading:{result['inference_id']}"})
        assert event["scheduled_at"] == captured_at
        assert event["erp_data"]["Temperature"] == value
        assert worker.run_once()

    assert [item["Temperature"] for item in erp.records] == values
    assert erp.records[0]["Time"] == "07:00"
    assert erp.records[-1]["Time"] == "07:14"
    assert database.delivery_outbox.count_documents({"status": "sent"}) == len(values)
    assert repository.get_recent_valid_values(camera_code, limit=3) == [100, 105, 110]
    first_zero = database.readings.find_one({"camera_code": camera_code, "value": 0})
    assert first_zero["is_anomaly"] is False
    assert "zero_reading" in first_zero["reasons"]
    assert reading["is_anomaly"] is False


@pytest.mark.parametrize("model", ["paddle", "yolo"])
def test_zero_without_history_is_delivered(model, database, handler):
    result = make_result(model, 0)
    process(handler, result)
    reading = database.readings.find_one()
    assert reading["value"] == 0
    assert reading["status"] == "valid"
    assert reading["is_anomaly"] is False
    assert database.delivery_outbox.find_one()["erp_data"]["Temperature"] == 0


def test_nonzero_jump_uses_previous_value(database, repository, handler):
    seed_history(repository, "AMP-001")
    result = make_result("paddle", 3000)
    process(handler, result)
    reading = database.readings.find_one({"reading_id": result["inference_id"]})
    assert reading["status"] == "anomaly"
    assert reading["is_anomaly"] is True
    assert reading["value"] == 3000
    assert reading["erp_value"] == 100
    assert reading["fallback_reading_id"] is not None
    assert database.delivery_outbox.find_one()["erp_data"]["Temperature"] == 100
    assert repository.get_recent_valid_values("AMP-001") == [100, 100, 100]
    assert database.measurement_states.find_one()["latest_value"] == 100


@pytest.mark.parametrize("model", ["paddle", "yolo"])
@pytest.mark.parametrize("confidence", [0.1, float("nan"), 1.1])
def test_invalid_confidence_is_not_zero(model, confidence, database, handler):
    process(handler, make_result(model, 0, confidence))
    assert database.readings.find_one()["status"] == "review"
    assert database.readings.find_one()["value"] is None
    assert database.delivery_outbox.count_documents({}) == 0
    assert database.measurement_states.count_documents({}) == 0


@pytest.mark.parametrize("text", ["", "abc", "0.0", "-2"])
def test_invalid_text_is_not_delivered(text, database, handler):
    process(handler, make_result("paddle", text))
    assert database.readings.find_one()["status"] == "review"
    assert database.delivery_outbox.count_documents({}) == 0


@pytest.mark.parametrize("model", ["paddle", "yolo"])
def test_missing_predictions_are_not_zero(model, database, handler):
    result = make_result(model, 0)
    result["predictions"] = []
    process(handler, result)
    assert database.readings.find_one()["value"] is None
    assert database.delivery_outbox.count_documents({}) == 0


def test_leading_zero_text_is_a_real_zero(database, handler):
    process(handler, make_result("paddle", "000"))
    assert database.readings.find_one()["value"] == 0
    assert database.delivery_outbox.find_one()["erp_data"]["Temperature"] == 0


def test_zero_survives_erp_retry(database, repository, handler):
    seed_history(repository, "AMP-001")
    process(handler, make_result("paddle", 0))
    erp = FakeERPClient(fail_once=True)
    worker = DeliveryWorker(DeliveryOutboxRepository(database), erp)
    assert worker.run_once()
    event = database.delivery_outbox.find_one()
    assert event["status"] == "pending"
    assert event["erp_data"]["Temperature"] == 0
    database.delivery_outbox.update_one(
        {"event_id": event["event_id"]},
        {"$set": {"next_attempt_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )
    assert worker.run_once()
    assert [item["Temperature"] for item in erp.records] == [0]
    assert database.delivery_outbox.find_one()["status"] == "sent"


def test_history_uses_capture_order_and_includes_zero(database, repository):
    for offset, value in [(2, 120), (0, 100), (1, 0)]:
        repository.save(
            reading_id=str(uuid4()), camera_code="AMP-001",
            captured_at=CAPTURED_AT + timedelta(minutes=offset),
            value=value, status="valid", is_anomaly=value == 0,
        )
    repository.save(
        reading_id=str(uuid4()), camera_code="AMP-001",
        captured_at=CAPTURED_AT + timedelta(minutes=3),
        value=None, status="review",
    )
    assert repository.get_recent_valid_values("AMP-001") == [100, 0, 120]


@pytest.mark.parametrize("model", ["paddle", "yolo"])
@pytest.mark.parametrize("values,expected", [
    ([120, 124, 119, 819, 121, 122], [120, 124, 119, 119, 121, 122]),
    ([120, 124, 119, 819, 820, 121], [120, 124, 119, 119, 119, 121]),
    ([120, 124, 119, 0, 819, 0, 120], [120, 124, 119, 0, 0, 0, 120]),
    ([120, 124, 119, 1, 0, 121], [120, 124, 119, 119, 0, 121]),
    ([0, 0, 0, 120], [0, 0, 0, 120]),
])
def test_delivery_policy_sequences(model, values, expected, database, repository, handler):
    erp = FakeERPClient()
    delivery = DeliveryWorker(DeliveryOutboxRepository(database), erp)
    last_valid_id = None
    last_valid_value = None
    for index, (observed, sent) in enumerate(zip(values, expected)):
        result = make_result(model, observed)
        captured_at = CAPTURED_AT + timedelta(minutes=index)
        process(handler, result, captured_at)
        reading = database.readings.find_one({"reading_id": result["inference_id"]})
        assert reading["value"] == observed
        assert reading["erp_value"] == sent
        if observed != sent:
            assert reading["status"] == "anomaly"
            assert reading["is_anomaly"] is True
            assert reading["fallback_reading_id"] == last_valid_id
        else:
            assert reading["status"] == "valid"
            assert reading["is_anomaly"] is False
            last_valid_id = result["inference_id"]
            last_valid_value = observed
        state = database.measurement_states.find_one({"camera_code": result["camera_code"]})
        assert state["latest_value"] == last_valid_value
        event = database.delivery_outbox.find_one({"event_id": f"reading:{result['inference_id']}"})
        assert event["scheduled_at"] == captured_at
        assert delivery.run_once()
    assert [row["Temperature"] for row in erp.records] == expected


def test_legacy_advisory_spikes_and_future_readings_do_not_contaminate_baseline(database, repository, handler):
    seed_history(repository, "AMP-001")
    repository.save(
        reading_id="legacy-spike", camera_code="AMP-001",
        captured_at=CAPTURED_AT - timedelta(seconds=1),
        value=9000, status="valid", is_anomaly=True,
    )
    repository.save(
        reading_id="future-reading", camera_code="AMP-001",
        captured_at=CAPTURED_AT + timedelta(days=1),
        value=10000, status="valid",
    )
    result = make_result("paddle", 819)
    process(handler, result)
    reading = database.readings.find_one({"reading_id": result["inference_id"]})
    assert reading["erp_value"] == 100
    assert reading["fallback_reading_id"] not in {"legacy-spike", "future-reading"}


def test_legacy_zero_remains_a_valid_fallback(database, repository, handler):
    seed_history(repository, "AMP-001")
    repository.save(
        reading_id="legacy-zero", camera_code="AMP-001",
        captured_at=CAPTURED_AT - timedelta(seconds=1),
        value=0, status="valid", is_anomaly=True,
    )
    result = make_result("paddle", 819)
    process(handler, result)
    reading = database.readings.find_one({"reading_id": result["inference_id"]})
    assert reading["erp_value"] == 0
    assert reading["fallback_reading_id"] == "legacy-zero"
    assert database.delivery_outbox.find_one()["erp_data"]["Temperature"] == 0


def test_replaced_anomaly_survives_erp_retry(database, repository, handler):
    seed_history(repository, "AMP-001")
    process(handler, make_result("paddle", 819))
    erp = FakeERPClient(fail_once=True)
    delivery = DeliveryWorker(DeliveryOutboxRepository(database), erp)
    assert delivery.run_once()
    event = database.delivery_outbox.find_one()
    assert event["status"] == "pending"
    assert event["erp_data"]["Temperature"] == 100
    database.delivery_outbox.update_one(
        {"event_id": event["event_id"]},
        {"$set": {"next_attempt_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )
    assert delivery.run_once()
    assert [row["Temperature"] for row in erp.records] == [100]
