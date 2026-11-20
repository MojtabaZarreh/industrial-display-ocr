from concurrent.futures import Future
from datetime import datetime, timezone
from unittest.mock import Mock

import numpy as np
import pytest

import application.processing_service as module
from application.camera_worker import CameraCaptureError, CameraWorker
from application.processing_service import ProcessingService
from infrastructure.database.mongodb.indexes import create_indexes
from infrastructure.database.mongodb.repositories import DeliveryOutboxRepository


@pytest.mark.parametrize("interval", [60, 300, 3600])
def test_ampere_sources_use_one_minute(interval):
    assert ProcessingService._camera_interval({"camera_code": "AMP-108", "schedule_interval": interval}) == 60
    assert ProcessingService._camera_interval({"camera_code": "SRC-001", "schedule_interval": 1800}) == 1800


def test_single_attempt_uses_constructor_timeouts_and_releases_each_capture():
    capture = Mock()
    capture.isOpened.return_value = True
    capture.read.return_value = (True, np.zeros((2, 3, 3), dtype=np.uint8))
    factory = Mock(return_value=capture)
    worker = CameraWorker({"camera_code": "AMP-001", "rtsp_url": "rtsp://example.invalid/stream"}, capture_factory=factory)
    first = worker.capture_frame()
    second = worker.capture_frame()
    assert first.image.size == (3, 2)
    assert first.captured_at.tzinfo is not None
    assert second.captured_at >= first.captured_at
    assert factory.call_count == capture.read.call_count == capture.release.call_count == 2
    import cv2
    assert factory.call_args.args[2] == [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000]
    worker.close()


@pytest.mark.parametrize("error", [False, True])
def test_read_failure_is_one_attempt_and_releases(error):
    capture = Mock()
    capture.isOpened.return_value = True
    if error:
        capture.read.side_effect = RuntimeError("decoder failure")
    else:
        capture.read.return_value = (False, None)
    factory = Mock(return_value=capture)
    worker = CameraWorker({"camera_code": "AMP-001", "rtsp_url": "rtsp://example.invalid/stream"}, capture_factory=factory)
    with pytest.raises(CameraCaptureError):
        worker.capture_frame()
    factory.assert_called_once()
    capture.read.assert_called_once()
    capture.release.assert_called_once()


def test_job_finishing_after_deadline_is_dispatched_immediately_without_replaying_history(monkeypatch):
    clock = {"now": 0.0, "stopped": False}
    submitted = []
    futures = []
    class Executor:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def submit(self, *args):
            submitted.append(clock["now"])
            future = Future()
            futures.append(future)
            return future
    class StopEvent:
        def is_set(self):
            return clock["stopped"]
        def wait(self, timeout):
            if clock["now"] == 0:
                clock["now"] = 61
                futures[0].set_result(None)
            elif clock["now"] == 61:
                clock["now"] = 62
                futures[1].set_result(None)
            elif clock["now"] == 62:
                clock["now"] = 120
            elif clock["now"] == 120:
                clock["now"] = 600
                futures[2].set_result(None)
            else:
                clock["stopped"] = True
    monkeypatch.setattr(module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(module, "ThreadPoolExecutor", Executor)
    worker = Mock()
    service = ProcessingService(Mock(), worker_factory=lambda camera: worker)
    service._stop_event = StopEvent()
    service.run_forever([{"camera_code": "AMP-001", "schedule_interval": 60}])
    assert submitted == [0, 61, 120, 600]
    assert service._next_deadline(180, 600, 60) == 660
    worker.close.assert_called_once()


def test_rollback_cancels_only_unsent_events_from_removed_minute_policy(database):
    create_indexes(database)
    outbox = DeliveryOutboxRepository(database)
    for event_id, flagged in [("minute:pending", True), ("minute:processing", True), ("minute:sent", True), ("reading:actual", False), ("minute:ordinary", False)]:
        outbox.create_event(event_id=event_id, camera_code="AMP-001", scheduled_at=datetime.now(timezone.utc), erp_data={"Temperature": -2, "MinuteSlot": flagged})
    database.delivery_outbox.update_one({"event_id": "minute:processing"}, {"$set": {"status": "processing"}})
    database.delivery_outbox.update_one({"event_id": "minute:sent"}, {"$set": {"status": "sent"}})
    assert outbox.cancel_minute_policy_events() == 2
    assert outbox.cancel_minute_policy_events() == 0
    assert database.delivery_outbox.count_documents({"status": "cancelled"}) == 2
    assert database.delivery_outbox.find_one({"event_id": "minute:sent"})["status"] == "sent"
    assert {outbox.claim_next_event()["event_id"], outbox.claim_next_event()["event_id"]} == {"reading:actual", "minute:ordinary"}
    assert outbox.claim_next_event() is None


def test_erp_uses_actual_tehran_capture_time_despite_old_midnight_checkpoint(database):
    from PIL import Image
    from application.camera_worker import CapturedFrame
    from application.reading_result_handler import ReadingResultHandler
    from infrastructure.database.mongodb.repositories import MeasurementPointRepository, ReadingRepository
    create_indexes(database)
    database.measurement_points.insert_one({"camera_code": "AMP-001", "description": "Production line"})
    database.minute_schedules.insert_one({"_id": "AMP-001", "next_slot": datetime(2026, 11, 16, 20, 30, tzinfo=timezone.utc)})
    handler = ReadingResultHandler(ReadingRepository(database), MeasurementPointRepository(database), DeliveryOutboxRepository(database))
    captured_at = datetime(2026, 11, 17, 13, 30, 15, tzinfo=timezone.utc)
    handler(CapturedFrame("AMP-001", Image.new("RGB", (20, 10)), captured_at), {
        "camera_code": "AMP-001", "inference_id": "actual-1700", "model": "paddle",
        "predictions": [{"text": "0", "confidence": 0.99}],
    })
    event = database.delivery_outbox.find_one()
    assert database.delivery_outbox.count_documents({}) == 1
    assert event["event_id"] == "reading:actual-1700"
    assert event["scheduled_at"] == captured_at
    assert event["erp_data"]["Time"] == "17:00"
    assert event["erp_data"]["Temperature"] == 0
