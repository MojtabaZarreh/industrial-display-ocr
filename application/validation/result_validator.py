
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Mapping

@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    status: str
    reasons: tuple[str, ...]

class ResultValidator:
    def __init__(self, *, min_confidence: float = 0.3) -> None:
        if (
            isinstance(min_confidence, bool)
            or not isinstance(min_confidence, (int, float))
            or not math.isfinite(min_confidence)
            or not 0 <= min_confidence <= 1
        ):
            raise ValueError(
                "min_confidence must be between 0 and 1."
            )

        self._min_confidence = min_confidence

    def validate(self, expected_camera_code: str, result: Mapping[str, Any]) -> ValidationResult:
        reasons: list[str] = []

        if not expected_camera_code.strip():
            return ValidationResult(
                False, "invalid", ("invalid_expected_camera_code",)
            )

        if result.get("camera_code") != expected_camera_code:
            reasons.append("camera_code_mismatch")

        model = result.get("model")
        if model not in {"paddle", "yolo"}:
            reasons.append("unsupported_model")

        predictions = result.get("predictions")
        if not isinstance(predictions, list):
            reasons.append("predictions_not_a_list")
            return ValidationResult(False, "invalid", tuple(reasons))

        if not predictions:
            reasons.append("empty_predictions")
            return ValidationResult(False, "invalid", tuple(reasons))

        for index, prediction in enumerate(predictions):
            if not isinstance(prediction, Mapping):
                reasons.append(f"prediction_{index}_invalid")
                continue

            confidence = prediction.get("confidence")

            if confidence is not None:
                if (
                    isinstance(confidence, bool)
                    or not isinstance(confidence, (int, float))
                    or not math.isfinite(confidence)
                    or not 0 <= confidence <= 1
                ):
                    reasons.append(
                        f"prediction_{index}_invalid_confidence"
                    )
                    continue

                if confidence < self._min_confidence:
                    reasons.append(
                        f"prediction_{index}_low_confidence"
                    )

            if model == "paddle":
                text = prediction.get("text")
                if not isinstance(text, str) or not text.strip():
                    reasons.append(
                        f"prediction_{index}_empty_text"
                    )

            elif model == "yolo":
                class_name = prediction.get(
                    "class", prediction.get("class_name")
                )
                if class_name is None or not str(class_name).strip():
                    reasons.append(
                        f"prediction_{index}_missing_class"
                    )

                if confidence is None:
                    reasons.append(
                        f"prediction_{index}_missing_confidence"
                    )

        if reasons:
            return ValidationResult(False, "review", tuple(reasons))

        return ValidationResult(True, "valid", ())
