from __future__ import annotations
from typing import Literal


ReadingStatus = Literal[
    "valid",
    "invalid",
    "capture_failed",
    "processing_failed",
]


def determine_erp_value(
    *,
    camera_connected: bool,
    reading_valid: bool,
    current_value: int | None,
    previous_valid_value: int | None,
) -> int:

    if not camera_connected:
        return -2

    if reading_valid and current_value is not None:
        return current_value

    if previous_valid_value is not None:
        return previous_valid_value

    return -2
