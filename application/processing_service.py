from __future__ import annotations
import io
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from typing import Any
import cv2
import numpy as np
import requests
from PIL import Image
from application.camera_worker import CameraCaptureError, CameraWorker, CapturedFrame
from application.preprocessing.engin import PreprocessingEngine
from application.dataset_collector import DatasetCollector
from domain.measurements import resolve_unit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = Path(
    os.getenv(
        "DATASET_DIR",
        str(PROJECT_ROOT / "infrastructure" / "storage" / "dataset"),
    )
).expanduser().resolve()

logger = logging.getLogger(__name__)
Camera = Mapping[str, Any]
DetectionResult = dict[str, Any]
ResultHandler = Callable[[CapturedFrame, DetectionResult], None]
CameraFailureHandler = Callable[[str, datetime], None]


class DetectionAPIClient:
    def __init__(self, base_url: str | None = None, *, connect_timeout: float = 5.0, read_timeout: float = 60.0) -> None:
        self._base_url = (base_url or os.getenv("DETECTION_API_URL", "http://127.0.0.1:8000")).rstrip("/")
        self._timeout = (connect_timeout, read_timeout)
        self._api_key = os.getenv("DETECTION_API_KEY", "")
        self._preprocessor = PreprocessingEngine()

    def predict(self, frame: CapturedFrame) -> DetectionResult:
        image_rgb = np.asarray(frame.image.convert("RGB"))
        image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

        processed_bgr = self._preprocessor.process(
            camera_code=frame.camera_code,
            image=image_bgr,
        )

        processed_rgb = cv2.cvtColor(processed_bgr, cv2.COLOR_BGR2RGB)
        processed_image = Image.fromarray(processed_rgb)

        with io.BytesIO() as image_buffer:
            processed_image.save(image_buffer, format="JPEG", quality=90)
            image_bytes = image_buffer.getvalue()

        with requests.post(
            f"{self._base_url}/predict/{frame.camera_code}",
            files={"file": ("frame.jpg", image_bytes, "image/jpeg")},
            headers={"X-API-Key": self._api_key} if self._api_key else {},
            timeout=self._timeout,
        ) as response:
            response.raise_for_status()
            result = response.json()

        if not isinstance(result, dict):
            raise ValueError("Detection API returned an invalid response.")

        self._collect_dataset(
            frame=frame,
            image_bytes=image_bytes,
            result=result,
        )

        return result

    def _collect_dataset(self, frame: CapturedFrame, image_bytes: bytes, result: DetectionResult) -> None:
        predictions = result.get("predictions")

        if not isinstance(predictions, list):
            logger.warning(
                "Dataset collection skipped for camera %s: invalid predictions.",
                frame.camera_code,
            )
            return

        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                dataset_image = image.convert("RGB")

            collector = DatasetCollector(
                location=RESULTS_DIR,
                camera_id=frame.camera_code,
            )

            entry = collector.collect(
                image=dataset_image,
                predictions=predictions,
                camera_code=frame.camera_code,
                captured_at=frame.captured_at,
                preprocessing=self._get_preprocessing_profile(frame.camera_code),
            )

            logger.debug(
                "Dataset sample saved: camera=%s sample_id=%s path=%s",
                frame.camera_code,
                entry["sample_id"],
                entry["sample_directory"],
            )

        except Exception:
            logger.exception(
                "Failed to collect dataset sample for camera %s.",
                frame.camera_code,
            )

    def _get_preprocessing_profile(self, camera_code: str) -> dict | None:
        normalized_code = camera_code.strip().upper()
        cameras = self._preprocessor.profiles.get("cameras", {})

        return next(
            (
                profile
                for code, profile in cameras.items()
                if code.strip().upper() == normalized_code
            ),
            None,
        )


class ProcessingService:
    def __init__(self, detection_client: DetectionAPIClient, *, max_workers: int = 32, poll_interval: float = 0.2, worker_factory: Callable[[Camera], CameraWorker] = CameraWorker, result_handler: ResultHandler | None = None, camera_failure_handler: CameraFailureHandler | None = None) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1.")

        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than zero.")

        self._detection_client = detection_client
        self._max_workers = max_workers
        self._poll_interval = poll_interval
        self._worker_factory = worker_factory
        self._result_handler = result_handler
        self._camera_failure_handler = camera_failure_handler
        self._stop_event = Event()
        self._workers: dict[str, CameraWorker] = {}

    def stop(self) -> None:
        self._stop_event.set()

    @staticmethod
    def _camera_interval(camera: Camera) -> float:
        if resolve_unit(camera["camera_code"], camera.get("unit")) == "ampere":
            return 60.0
        try:
            interval = float(camera.get("schedule_interval", 60))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid schedule_interval for {camera.get('camera_code', 'unknown camera')}."
            ) from exc

        if interval <= 0 or not np.isfinite(interval):
            raise ValueError(
                f"schedule_interval must be finite and positive for {camera.get('camera_code', 'unknown camera')}."
            )

        return interval

    def _process_camera(self, camera_code: str, worker: CameraWorker) -> None:
        started_at = time.monotonic()

        try:
            try:
                frame = worker.capture_frame()
            except CameraCaptureError:
                logger.warning("Camera capture failed: camera=%s; single attempt failed or timed out.", camera_code)
                if self._camera_failure_handler is not None:
                    self._camera_failure_handler(camera_code, datetime.now(timezone.utc))
                return
            captured_in = time.monotonic() - started_at
            result = self._detection_client.predict(frame)
            inferred_in = time.monotonic() - started_at - captured_in

            if self._result_handler is not None:
                self._result_handler(frame, result)

            elapsed = time.monotonic() - started_at

            logger.info(
                "Camera processed: camera=%s captured_at=%s capture=%.2fs inference=%.2fs total=%.2fs",
                camera_code, frame.captured_at.isoformat(), captured_in, inferred_in, elapsed,
            )
            if elapsed >= 60:
                logger.warning("Camera processing exceeded one minute: camera=%s duration=%.2fs", camera_code, elapsed)

        except Exception:
            logger.exception("Processing failed for camera %s.", camera_code)
            raise

    @staticmethod
    def _next_deadline(previous: float, now: float, interval: float) -> float:
        return previous + max(1, math.floor((now - previous) / interval) + 1) * interval

    def run_forever(self, cameras: Iterable[Camera]) -> None:
        camera_map: dict[str, Camera] = {}
        intervals: dict[str, float] = {}
        next_run: dict[str, float] = {}
        now = time.monotonic()

        for camera in cameras:
            raw_code = camera.get("camera_code")

            if not isinstance(raw_code, str) or not raw_code.strip():
                logger.warning("Skipping camera with an invalid code.")
                continue

            camera_code = raw_code.strip().upper()

            if camera_code in camera_map:
                logger.warning(
                    "Duplicate camera code %s; skipping duplicate.",
                    camera_code,
                )
                continue

            try:
                interval = self._camera_interval(camera)
                worker = self._worker_factory(camera)

            except Exception:
                logger.exception(
                    "Could not initialize camera %s.",
                    camera_code,
                )
                continue

            camera_map[camera_code] = camera
            intervals[camera_code] = interval
            next_run[camera_code] = now
            self._workers[camera_code] = worker

        if not camera_map:
            logger.warning("No cameras are available for processing.")
            return

        in_flight: dict[Future[None], str] = {}

        logger.info(
            "Starting processing for %d cameras with %d workers.",
            len(camera_map),
            self._max_workers,
        )

        try:
            with ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="camera",
            ) as executor:
                while not self._stop_event.is_set():
                    now = time.monotonic()
                    completed = [
                        future
                        for future in in_flight
                        if future.done()
                    ]

                    for future in completed:
                        camera_code = in_flight.pop(future)

                        try:
                            future.result()
                        except Exception:
                            pass

                    available_slots = self._max_workers - len(in_flight)

                    if available_slots > 0:
                        active_codes = set(in_flight.values())

                        due_cameras = sorted(
                            (
                                code
                                for code in camera_map
                                if code not in active_codes
                                and next_run[code] <= now
                            ),
                            key=lambda code: next_run[code],
                        )

                        for camera_code in due_cameras[:available_slots]:
                            if self._stop_event.is_set():
                                break

                            future = executor.submit(
                                self._process_camera,
                                camera_code,
                                self._workers[camera_code],
                            )

                            in_flight[future] = camera_code
                            next_run[camera_code] = self._next_deadline(
                                next_run[camera_code], now, intervals[camera_code],
                            )

                    self._stop_event.wait(self._poll_interval)

        finally:
            for camera_code, worker in self._workers.items():
                try:
                    worker.close()
                except Exception:
                    logger.exception(
                        "Failed to close camera worker %s.",
                        camera_code,
                    )

            self._workers.clear()
            logger.info("Camera processing service stopped.")
