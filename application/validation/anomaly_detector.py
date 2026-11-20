
from __future__ import annotations
import math
from dataclasses import dataclass
from statistics import median
from typing import Sequence


@dataclass(frozen=True)
class AnomalyResult:
    is_anomaly: bool
    reason: str | None
    previous_value: float | None
    current_value: float

class AnomalyDetector:
    def __init__(
        self,
        *,
        min_history: int = 3,
        max_relative_change: float = 0.5,
        absolute_tolerance: float = 0.0,
    ) -> None:
        if min_history < 1:
            raise ValueError("min_history must be at least 1.")

        if (
            not math.isfinite(max_relative_change)
            or max_relative_change < 0
        ):
            raise ValueError(
                "max_relative_change must be finite and non-negative."
            )

        if (
            not math.isfinite(absolute_tolerance)
            or absolute_tolerance < 0
        ):
            raise ValueError(
                "absolute_tolerance must be finite and non-negative."
            )

        self._min_history = min_history
        self._max_relative_change = max_relative_change
        self._absolute_tolerance = absolute_tolerance

    def detect(
        self,
        current_value: float,
        history: Sequence[float],
    ) -> AnomalyResult:
        if (
            isinstance(current_value, bool)
            or not isinstance(current_value, (int, float))
            or not math.isfinite(current_value)
        ):
            raise ValueError("current_value must be finite.")

        clean_history: list[float] = []

        for value in history:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value == 0
            ):
                continue

            clean_history.append(float(value))

        current = float(current_value)

        if current == 0:
            return AnomalyResult(
                is_anomaly=False,
                reason="zero_reading",
                previous_value=clean_history[-1] if clean_history else None,
                current_value=current,
            )

        if len(clean_history) < self._min_history:
            return AnomalyResult(
                is_anomaly=False,
                reason="insufficient_history",
                previous_value=(
                    clean_history[-1] if clean_history else None
                ),
                current_value=current,
            )

        baseline = float(median(clean_history))
        difference = abs(current - baseline)

        allowed_change = max(
            abs(baseline) * self._max_relative_change,
            self._absolute_tolerance,
        )

        if difference > allowed_change:
            return AnomalyResult(
                is_anomaly=True,
                reason="unusual_change_from_history",
                previous_value=baseline,
                current_value=current,
            )

        return AnomalyResult(
            is_anomaly=False,
            reason=None,
            previous_value=baseline,
            current_value=current,
        )
