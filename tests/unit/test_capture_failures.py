import logging
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from PIL import Image

import main
from application.camera_worker import CameraCaptureError, CameraWorker, CapturedFrame
from application.delivery_worker import DeliveryWorker
from application.processing_service import ProcessingService
from application.reading_result_handler import ReadingResultHandler
from infrastructure.database.mongodb.repositories import (
    DeliveryOutboxRepository, MeasurementPointRepository, ReadingRepository,
)


@pytest.fixture
def source_handler(database):
    MeasurementPointRepository(database).create({
        "camera_code": "AMP-006", "name": "Test source",
        "description": "Production line", "rtsp_url": "rtsp://camera.example.invalid/stream",
        "schedule_interval": 60, "danger_threshold": 1000,
    })
    return ReadingResultHandler(
        ReadingRepository(database), MeasurementPointRepository(database), DeliveryOutboxRepository(database),
    )


def test_single_capture_attempt_queues_minus_two_without_traceback(database, source_handler, caplog):
    class FailedCapture:
        def isOpened(self):
            return True
        def set(self, *args):
            return True
        def read(self):
            return False, None
        def release(self):
            pass

    factory = Mock(side_effect=lambda *args: FailedCapture())
    worker = CameraWorker(
        {"camera_code": "AMP-006", "rtsp_url": "rtsp://camera.example.invalid/stream"},
        capture_factory=factory,
    )
    detection = Mock()
    service = ProcessingService(detection, result_handler=source_handler, camera_failure_handler=source_handler.handle_camera_failure)
    with caplog.at_level(logging.WARNING):
        service._process_camera("AMP-006", worker)
    worker.close()
    assert factory.call_count == 1
    detection.predict.assert_not_called()
    assert "Camera capture failed" in caplog.text
    assert len([record for record in caplog.records if record.levelno >= logging.WARNING]) == 1
    assert all(record.exc_info is None for record in caplog.records)
    assert "Traceback" not in caplog.text
    assert database.readings.count_documents({}) == 0
    assert database.measurement_states.count_documents({}) == 0
    event = database.delivery_outbox.find_one()
    assert event["erp_data"]["Temperature"] == -2
    assert event["scheduled_at"].tzinfo is not None
    erp = Mock()
    assert DeliveryWorker(DeliveryOutboxRepository(database), erp).run_once()
    assert erp.insert_temperature.call_args.args[0]["Temperature"] == -2


def test_recovery_zero_after_camera_failure_is_sent(database, source_handler):
    worker = Mock()
    worker.capture_frame.side_effect = [
        CameraCaptureError("capture attempts exhausted"),
        CapturedFrame("AMP-006", Image.new("RGB", (20, 10)), datetime.now(timezone.utc)),
    ]
    detection = Mock()
    detection.predict.return_value = {
        "camera_code": "AMP-006", "model": "paddle", "inference_id": "recovery",
        "predictions": [{"text": "0", "confidence": 0.99}],
    }
    service = ProcessingService(detection, result_handler=source_handler, camera_failure_handler=source_handler.handle_camera_failure)
    service._process_camera("AMP-006", worker)
    service._process_camera("AMP-006", worker)
    events = list(database.delivery_outbox.find().sort("created_at", 1))
    assert [event["erp_data"]["Temperature"] for event in events] == [-2, 0]
    assert database.measurement_states.find_one()["latest_value"] == 0
    assert database.readings.find_one()["status"] == "valid"


def test_model_failure_is_not_reported_as_camera_failure(caplog):
    worker = Mock()
    worker.capture_frame.return_value = CapturedFrame("AMP-006", Image.new("RGB", (20, 10)), datetime.now(timezone.utc))
    detection = Mock()
    detection.predict.side_effect = ConnectionError("Model API unavailable")
    failure_handler = Mock()
    service = ProcessingService(detection, camera_failure_handler=failure_handler)
    with pytest.raises(ConnectionError):
        service._process_camera("AMP-006", worker)
    failure_handler.assert_not_called()
    assert any(record.exc_info for record in caplog.records)


def test_unexpected_capture_bug_keeps_traceback(caplog):
    worker = Mock()
    worker.capture_frame.side_effect = RuntimeError("Unexpected capture bug")
    failure_handler = Mock()
    service = ProcessingService(Mock(), camera_failure_handler=failure_handler)
    with pytest.raises(RuntimeError):
        service._process_camera("AMP-006", worker)
    failure_handler.assert_not_called()
    assert any(record.exc_info for record in caplog.records)


def test_main_wires_camera_failure_reporting(database, source_handler, monkeypatch):
    mongo = Mock(database=database)
    monkeypatch.setattr(main, "MongoDB", lambda: mongo)
    monkeypatch.setattr(main, "create_erp_client", lambda: None)
    monkeypatch.setattr(main, "DetectionAPIClient", Mock())
    monkeypatch.setattr(main, "configure_logging", Mock())
    service = Mock()
    def service_factory(**kwargs):
        service.run_forever.side_effect = lambda cameras: kwargs["camera_failure_handler"]("AMP-006", datetime.now(timezone.utc))
        return service
    monkeypatch.setattr(main, "ProcessingService", service_factory)
    main.main()
    assert database.delivery_outbox.find_one()["erp_data"]["Temperature"] == -2
    service.stop.assert_called_once()
    mongo.close.assert_called_once()


def test_failed_capture_preserves_baseline_for_next_anomaly(database, source_handler):
    from datetime import timedelta
    repository = ReadingRepository(database)
    for index, value in enumerate([120, 124, 119]):
        repository.save(
            reading_id=f"accepted-{index}", camera_code="AMP-006",
            captured_at=datetime.now(timezone.utc) - timedelta(minutes=3-index),
            value=value, status="valid",
        )
    worker = Mock()
    worker.capture_frame.side_effect = CameraCaptureError("capture attempts exhausted")
    service = ProcessingService(Mock(), camera_failure_handler=source_handler.handle_camera_failure)
    service._process_camera("AMP-006", worker)
    assert database.measurement_states.find_one()["latest_value"] == 119
    frame = CapturedFrame("AMP-006", Image.new("RGB", (20, 10)), datetime.now(timezone.utc))
    source_handler(frame, {
        "camera_code": "AMP-006", "model": "paddle", "inference_id": "after-failure",
        "predictions": [{"text": "819", "confidence": 0.99}],
    })
    assert [row["erp_data"]["Temperature"] for row in database.delivery_outbox.find()] == [-2, 119]
    assert database.measurement_states.find_one()["latest_value"] == 119


def test_failure_to_queue_unavailable_marker_is_not_hidden(caplog):
    worker = Mock()
    worker.capture_frame.side_effect = CameraCaptureError("capture attempts exhausted")
    failure_handler = Mock(side_effect=ConnectionError("MongoDB unavailable"))
    service = ProcessingService(Mock(), camera_failure_handler=failure_handler)
    with pytest.raises(ConnectionError):
        service._process_camera("AMP-006", worker)
    assert any(record.exc_info for record in caplog.records)
