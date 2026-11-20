from __future__ import annotations
import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
import cv2
from PIL import Image

logger = logging.getLogger(__name__)


class CameraCaptureError(RuntimeError):
    """Raised when a camera frame cannot be captured."""


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """An image captured from a measurement camera."""

    camera_code: str
    image: Image.Image
    captured_at: datetime


class CameraWorker:
    def __init__(
        self, camera: Mapping[str, Any],
        *,
        open_timeout: float = 5.0,
        read_timeout: float = 5.0,
        capture_factory: Callable[..., Any] | None = None ) -> None:
        camera_code = camera.get("camera_code")
        rtsp_url = camera.get("rtsp_url")

        if not isinstance(camera_code, str) or not camera_code.strip():
            raise ValueError("Camera must have a valid camera_code.")

        if not isinstance(rtsp_url, str) or not rtsp_url.startswith("rtsp://"):
            raise ValueError("Camera must have a valid RTSP URL.")

        if any(not math.isfinite(value) or value <= 0 for value in (open_timeout, read_timeout)):
            raise ValueError("Capture timeouts must be finite and positive.")

        self.camera_code = camera_code.strip().upper()
        self._rtsp_url = rtsp_url
        self._open_timeout_ms = max(1, int(open_timeout * 1000))
        self._read_timeout_ms = max(1, int(read_timeout * 1000))
        self._capture_factory = capture_factory or cv2.VideoCapture

        self._capture: Any | None = None
        self._lock = Lock()
        self._closed = False

    def _connect(self) -> bool:
        """Open the RTSP stream if no usable connection exists."""
        if self._closed:
            raise CameraCaptureError(f"Camera worker {self.camera_code} is closed.")
        if self._capture is not None and self._capture.isOpened():
            return True

        self._disconnect()

        try:
            capture = self._capture_factory(self._rtsp_url, cv2.CAP_FFMPEG, [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self._open_timeout_ms,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, self._read_timeout_ms,
            ])
            if not capture.isOpened():
                capture.release()
                return False

            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._capture = capture
            return True

        except Exception:
            self._disconnect()
            logger.debug("Could not open camera stream for %s.", self.camera_code,)
            return False

    def _disconnect(self) -> None:
        capture, self._capture = self._capture, None

        if capture is not None:
            try:
                capture.release()
            except Exception:
                logger.debug("Error releasing camera stream for %s.",self.camera_code)

    def capture_frame(self) -> CapturedFrame:
        with self._lock:
            if self._closed:
                raise CameraCaptureError(f"Camera worker {self.camera_code} is closed.")

            self._disconnect()
            try:
                if self._connect():
                    success, frame = self._capture.read()
                    if success and frame is not None and frame.size > 0:
                        return CapturedFrame(
                            camera_code=self.camera_code,
                            image=Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
                            captured_at=datetime.now(timezone.utc),
                        )
            except Exception:
                logger.debug("Could not capture frame for %s.", self.camera_code)
            finally:
                self._disconnect()

            raise CameraCaptureError(f"Failed to capture a frame from camera {self.camera_code}.")

    def close(self) -> None:
        """Release the stream and prevent further captures."""
        with self._lock:
            self._disconnect()
            self._closed = True

    def __enter__(self) -> CameraWorker:
        if self._closed:
            raise CameraCaptureError(
                f"Camera worker {self.camera_code} is closed."
            )
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
