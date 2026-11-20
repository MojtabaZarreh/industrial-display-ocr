from enum import Enum


class MeasurementUnit(str, Enum):
    CELSIUS = "celsius"
    AMPERE = "ampere"
    KILOGRAM = "kilogram"
    METERS_PER_SECOND = "meters_per_second"


def resolve_unit(camera_code: str, unit: str | None = None) -> str:
    if unit is not None:
        if not isinstance(unit, str):
            raise ValueError("unit must be a supported measurement unit.")
        try:
            return MeasurementUnit(unit.strip().lower()).value
        except ValueError as exc:
            raise ValueError(f"Unsupported measurement unit: {unit!r}") from exc

    code = camera_code.strip().upper()

    if code.startswith("SRC-"):
        return MeasurementUnit.CELSIUS.value
    if code.startswith("AMP-"):
        return MeasurementUnit.AMPERE.value

    raise ValueError(f"An explicit unit is required for camera {camera_code!r}.")
