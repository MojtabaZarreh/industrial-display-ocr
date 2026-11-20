from __future__ import annotations
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo
import jdatetime
from application.camera_worker import CapturedFrame
from application.validation.anomaly_detector import AnomalyDetector
from application.validation.reading_extractor import ReadingExtractionError, ReadingExtractor
from application.validation.result_validator import ResultValidator
from infrastructure.database.mongodb.repositories import MeasurementPointRepository, ReadingRepository
from infrastructure.database.mongodb.repositories import DeliveryOutboxRepository

logger = logging.getLogger(__name__)
TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")

class ReadingResultHandler:
    def __init__(self, repository: ReadingRepository, measurement_repository: MeasurementPointRepository, outbox_repository: DeliveryOutboxRepository, *, destination: str = "erp") -> None:
        if destination not in {"erp", "file"}:
            raise ValueError("Unsupported delivery destination.")
        self._destination = destination
        self._repository = repository
        self._measurement_repository = measurement_repository
        self._outbox_repository = outbox_repository
        self._validator = ResultValidator()
        self._extractor = ReadingExtractor()
        self._anomaly_detector = AnomalyDetector()

    def __call__(self, frame: CapturedFrame, result: Mapping[str, Any]) -> None:
        camera_code = frame.camera_code.strip().upper()
        inference_id = result.get("inference_id")
        if not isinstance(inference_id, str) or not inference_id.strip():
            inference_id = str(uuid4())

        model = result.get("model")
        if not isinstance(model, str):
            model = None

        confidence = self._get_confidence(result)
        validation = self._validator.validate(camera_code, result)

        if not validation.is_valid:
            self._save(
                reading_id=inference_id,
                camera_code=camera_code,
                frame=frame,
                value=None,
                status="review",
                reasons=[
                    f"validation_{validation.status}",
                    *validation.reasons,
                ],
                inference_id=inference_id,
                model=model,
                confidence=confidence,
            )
            logger.warning(
                "Reading requires review: camera=%s reasons=%s",
                camera_code,
                validation.reasons,
            )
            return

        try:
            value = self._extractor.extract(result)
        except ReadingExtractionError as exc:
            self._save(
                reading_id=inference_id,
                camera_code=camera_code,
                frame=frame,
                value=None,
                status="review",
                reasons=[f"reading_extraction_failed: {exc}"],
                inference_id=inference_id,
                model=model,
                confidence=confidence,
            )
            logger.warning(
                "Reading extraction failed: camera=%s error=%s",
                camera_code,
                exc,
            )
            return

        history = [] if value == 0 else self._repository.get_recent_nonzero_valid_values(
            camera_code,
            limit=10,
            before=frame.captured_at,
        )

        anomaly = self._anomaly_detector.detect(
            current_value=value,
            history=history,
        )

        status = "anomaly" if anomaly.is_anomaly else "valid"
        reasons = [anomaly.reason] if anomaly.reason else []
        erp_value = value
        fallback_reading_id = None

        if anomaly.is_anomaly:
            previous = self._repository.get_latest_valid_reading(
                camera_code, before=frame.captured_at,
            )
            erp_value = int(previous["value"]) if previous is not None else None
            fallback_reading_id = previous.get("reading_id") if previous is not None else None
            reasons.append("previous_valid_value_used" if previous is not None else "no_previous_valid_value")

        self._save(
            reading_id=inference_id,
            camera_code=camera_code,
            frame=frame,
            value=value,
            status=status,
            reasons=reasons,
            inference_id=inference_id,
            model=model,
            confidence=confidence,
            is_anomaly=anomaly.is_anomaly,
            erp_value=erp_value,
            fallback_reading_id=fallback_reading_id,
        )

        if anomaly.is_anomaly:
            logger.warning(
                "Anomaly detected: camera=%s observed=%s erp_value=%s baseline=%s",
                camera_code,
                value,
                erp_value,
                anomaly.previous_value,
            )

        if erp_value is not None:
            self._enqueue_erp_record(
                camera_code=camera_code,
                captured_at=frame.captured_at,
                value=erp_value,
                event_id=f"reading:{inference_id}",
            )

        logger.info(
            "Reading processed: camera=%s value=%s status=%s anomaly=%s erp_value=%s",
            camera_code,
            value,
            status,
            anomaly.is_anomaly,
            erp_value,
        )

    def handle_camera_failure(
        self,
        camera_code: str,
        captured_at: datetime | None = None,
    ) -> None:
        camera_code = camera_code.strip().upper()

        self._enqueue_erp_record(
            camera_code=camera_code,
            captured_at=captured_at or datetime.now(timezone.utc),
            value=-2,
            event_id=f"camera-failure:{uuid4()}",
        )

        logger.debug(
            "Camera unavailable: camera=%s ERP value=-2",
            camera_code,
        )

    def _enqueue_erp_record(
        self,
        *,
        camera_code: str,
        captured_at: datetime,
        value: int,
        event_id: str,
    ) -> None:
        camera = self._measurement_repository.get_by_code(camera_code)

        if not camera:
            logger.error(
                "Camera not found in MongoDB: %s",
                camera_code,
            )
            return

        record_type = camera.get("description")

        if not isinstance(record_type, str) or not record_type.strip():
            logger.error(
                "Camera description is missing: %s",
                camera_code,
            )
            return

        local_datetime = self._to_tehran_datetime(captured_at)

        jalali_datetime = jdatetime.datetime.fromgregorian(
            datetime=local_datetime
        )

        date_str = jalali_datetime.strftime("%Y/%m/%d")
        time_str = jalali_datetime.strftime("%H:%M")

        erp_data = {
            "Date": date_str,
            "Time": time_str,
            "Temperature": value,
            "CreateDateTime": f"{date_str}-{time_str}",
            "RecordType": record_type.strip(),
        }

        created = self._outbox_repository.create_event(
            event_id=event_id,
            camera_code=camera_code,
            scheduled_at=captured_at,
            erp_data=erp_data,
            destination=self._destination,
            source={"name": camera.get("name", camera_code), "unit": camera.get("unit", "")},
        )

        if created:
            logger.debug(
                "ERP delivery queued: camera=%s value=%s event_id=%s",
                camera_code,
                value,
                event_id,
            )
        else:
            logger.debug(
                "ERP event already exists or was not created: event_id=%s",
                event_id,
            )

    def _save(
        self,
        *,
        reading_id: str,
        camera_code: str,
        frame: CapturedFrame,
        value: int | None,
        status: str,
        reasons: list[str],
        inference_id: str | None,
        model: str | None,
        confidence: float | None,
        is_anomaly: bool = False,
        erp_value: int | None = None,
        fallback_reading_id: str | None = None,
    ) -> None:
        self._repository.save(
            reading_id=reading_id,
            camera_code=camera_code,
            captured_at=frame.captured_at,
            value=value,
            status=status,
            reasons=reasons,
            inference_id=inference_id,
            model=model,
            confidence=confidence,
            is_anomaly=is_anomaly,
            erp_value=erp_value,
            fallback_reading_id=fallback_reading_id,
        )

    @staticmethod
    def _to_tehran_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=TEHRAN_TIMEZONE)
        return value.astimezone(TEHRAN_TIMEZONE)

    @staticmethod
    def _get_confidence(result: Mapping[str, Any]) -> float | None:
        predictions = result.get("predictions")
        if not isinstance(predictions, list) or not predictions:
            return None

        confidences: list[float] = []

        for prediction in predictions:
            if not isinstance(prediction, Mapping):
                return None

            confidence = prediction.get("confidence")

            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
            ):
                return None

            confidences.append(float(confidence))

        return min(confidences) if confidences else None
