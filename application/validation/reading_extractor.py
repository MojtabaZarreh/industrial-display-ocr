from __future__ import annotations
import math
import re
from typing import Any, Mapping


class ReadingExtractionError(ValueError):
    """Raised when a final numeric reading cannot be extracted."""


class ReadingExtractor:
    _DIGIT_PATTERN = re.compile(r"^\d+$")
    _YOLO_CLASS_PATTERN = re.compile(r"^D(\d)$")

    def extract(self, result: Mapping[str, Any]) -> int:
        model = result.get("model")
        predictions = result.get("predictions")

        if not isinstance(predictions, list) or not predictions:
            raise ReadingExtractionError("No predictions available.")

        if model == "paddle":
            return self._extract_paddle(predictions)

        if model == "yolo":
            return self._extract_yolo(predictions)

        raise ReadingExtractionError("Unsupported detection model.")

    def _extract_paddle(
        self,
        predictions: list[Any],
    ) -> int:
        if len(predictions) != 1:
            raise ReadingExtractionError(
                "Expected exactly one Paddle text prediction."
            )

        prediction = predictions[0]

        if not isinstance(prediction, Mapping):
            raise ReadingExtractionError("Invalid Paddle prediction.")

        text = prediction.get("text")

        if not isinstance(text, str):
            raise ReadingExtractionError("Paddle text is missing.")

        text = text.strip()

        if not self._DIGIT_PATTERN.fullmatch(text):
            raise ReadingExtractionError(
                "Paddle output is not a digits-only reading."
            )

        return int(text)

    def _extract_yolo(
        self,
        predictions: list[Any],
    ) -> int:
        digits: list[tuple[float, int]] = []

        for prediction in predictions:
            if not isinstance(prediction, Mapping):
                raise ReadingExtractionError("Invalid YOLO prediction.")

            x = prediction.get("x")

            if (
                isinstance(x, bool)
                or not isinstance(x, (int, float))
                or not math.isfinite(x)
            ):
                raise ReadingExtractionError(
                    "YOLO prediction has an invalid x coordinate."
                )

            class_name = prediction.get("class")
            match = (
                self._YOLO_CLASS_PATTERN.fullmatch(class_name)
                if isinstance(class_name, str)
                else None
            )

            if match is not None:
                digit = int(match.group(1))
            else:
                class_id = prediction.get("class_id")

                if (
                    isinstance(class_id, bool)
                    or not isinstance(class_id, int)
                    or not 0 <= class_id <= 9
                ):
                    raise ReadingExtractionError(
                        "YOLO prediction has an invalid digit class."
                    )

                digit = class_id

            digits.append((float(x), digit))

        digits.sort(key=lambda item: item[0])

        reading_text = "".join(str(digit) for _, digit in digits)

        return int(reading_text)
