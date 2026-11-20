
import json
import logging
from pathlib import Path
from typing import Any
import cv2
import numpy as np


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "camera_preprocessing.json"


class PreprocessingEngine:
    def __init__(self, config_path: str | Path = DEFAULT_CONFIG) -> None:
        self.config_path = Path(config_path)
        self.profiles = self._load_profiles()

    def _load_profiles(self) -> dict[str, Any]:
        if not self.config_path.exists():
            logger.warning("Preprocessing config not found: %s", self.config_path)
            return {"cameras": {}}

        with self.config_path.open("r", encoding="utf-8") as file:
            config = json.load(file)

        if not isinstance(config, dict) or not isinstance(config.get("cameras", {}), dict):
            raise ValueError("Invalid camera preprocessing configuration.")

        return config

    def reload(self) -> None:
        self.profiles = self._load_profiles()

    def process(self, camera_code: str, image: np.ndarray) -> np.ndarray:
        if not isinstance(image, np.ndarray) or image.size == 0:
            raise ValueError("Input image is empty or invalid.")

        cameras = self.profiles.get("cameras", {})

        normalized_code = camera_code.strip().upper()

        profile = next(
            (
                value
                for key, value in cameras.items()
                if key.strip().upper() == normalized_code
            ),
            None,
        )

        if profile is None:
            logger.warning(
                "No preprocessing profile found for camera: %s",
                camera_code,
            )
            return image.copy()

        if not profile.get("enabled", True):
            logger.info(
                "Preprocessing is disabled for camera: %s",
                camera_code,
            )
            return image.copy()

        result = image.copy()

        for step in profile.get("pipeline", []):
            operation = step.get("operation")

            if operation == "crop":
                result = self._crop(result, step)

            elif operation == "mask":
                result = self._mask(result, step)

            elif operation == "weighted_adjustment":
                alpha = float(step.get("alpha", 1.0))
                beta = float(step.get("beta", 0.0))

                if not 0 <= alpha <= 5 or not -255 <= beta <= 255:
                    raise ValueError(
                        f"Invalid weighted adjustment for {camera_code}."
                    )

                result = cv2.convertScaleAbs(
                    result,
                    alpha=alpha,
                    beta=beta,
                )

            elif operation == "grayscale":
                result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
                result = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)

            elif operation == "denoise":
                result = cv2.medianBlur(result, 3)

            else:
                raise ValueError(
                    f"Unsupported preprocessing operation: {operation!r}"
                )

        logger.debug(
            "Preprocessing applied: camera=%s, output_shape=%s",
            camera_code,
            result.shape,
        )

        return result

    @staticmethod
    def _crop(image: np.ndarray, step: dict[str, Any]) -> np.ndarray:
        region = step.get("region")
        if not isinstance(region, list) or len(region) != 4:
            raise ValueError("Crop region must be [x1, y1, x2, y2].")

        x1, y1, x2, y2 = region
        height, width = image.shape[:2]

        if not (
            all(isinstance(v, int) and not isinstance(v, bool)
                for v in region)
            and 0 <= x1 < x2 <= width
            and 0 <= y1 < y2 <= height
        ):
            raise ValueError("Crop coordinates are outside the image.")

        return image[y1:y2, x1:x2].copy()

    @staticmethod
    def _mask(image: np.ndarray, step: dict[str, Any]) -> np.ndarray:
        result = image.copy()

        for rect in step.get("rectangles", []):
            x = int(rect["x"])
            y = int(rect["y"])
            width = int(rect["width"])
            height = int(rect["height"])

            if width <= 0 or height <= 0:
                raise ValueError("Mask rectangle dimensions must be positive.")

            cv2.rectangle(
                result,
                (x, y),
                (x + width, y + height),
                (0, 0, 0),
                thickness=-1,
            )

        return result
