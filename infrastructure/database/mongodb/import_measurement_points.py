import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from infrastructure.database.mongodb.mongo import MongoDB
from infrastructure.database.mongodb.indexes import create_indexes
from domain.measurements import resolve_unit


REQUIRED_FIELDS = {
    "name",
    "code",
    "ip_address",
    "schedule_interval",
    "danger_threshold",
}


def load_measurement_points(file_path: Path) -> list[dict]:
    with file_path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("JSON root must be a list of measurement points.")

    seen_codes = set()

    for index, point in enumerate(data):
        if not isinstance(point, dict):
            raise ValueError(f"Item {index} must be a JSON object.")

        missing = REQUIRED_FIELDS - point.keys()

        if missing:
            raise ValueError(
                f"Item {index} is missing fields: {', '.join(sorted(missing))}"
            )

        code = point["code"]

        if not isinstance(code, str) or not code.strip():
            raise ValueError(f"Item {index} has an invalid code.")

        camera_code = code.strip().upper()

        if camera_code in seen_codes:
            raise ValueError(
                f"Duplicate camera code in JSON: {camera_code}"
            )

        seen_codes.add(camera_code)
        point["code"] = camera_code
        point["unit"] = resolve_unit(camera_code, point.get("unit"))

        name = point["name"]

        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Item {index} has an invalid name.")

        point["name"] = name.strip()

        rtsp_url = point["ip_address"]

        if (
            not isinstance(rtsp_url, str)
            or not rtsp_url.strip().startswith("rtsp://")
        ):
            raise ValueError(f"Item {index} has an invalid RTSP URL.")

        point["ip_address"] = rtsp_url.strip()

        interval = point["schedule_interval"]

        if (
            isinstance(interval, bool)
            or not isinstance(interval, (int, float))
            or not math.isfinite(interval)
            or interval <= 0
        ):
            raise ValueError(
                f"Item {index} has an invalid schedule_interval."
            )

        if point["unit"] == "ampere":
            point["schedule_interval"] = 60

        description = point.get("description", "")

        if not isinstance(description, str):
            raise ValueError(
                f"Item {index} has an invalid description."
            )

        point["description"] = description.strip()

    return data


def import_measurement_points(file_path: Path) -> None:
    points = load_measurement_points(file_path)

    mongodb = MongoDB()
    inserted = 0
    updated = 0

    try:
        mongodb.connect()
        database = mongodb.database
        collection = database["measurement_points"]

        existing_cameras = {}

        for camera in collection.find({}, {"camera_code": 1}):
            code = camera.get("camera_code")

            if not isinstance(code, str):
                continue

            normalized_code = code.strip().upper()

            existing_cameras.setdefault(
                normalized_code,
                [],
            ).append(camera["_id"])

        for point in points:
            camera_code = point["code"]
            matches = existing_cameras.get(camera_code, [])

            if len(matches) > 1:
                raise ValueError(
                    f"Multiple database records match {camera_code}. "
                    "Resolve duplicate records before importing."
                )

        create_indexes(database)
        now = datetime.now(timezone.utc)

        for point in points:
            camera_code = point["code"]
            matches = existing_cameras.get(camera_code, [])

            query = (
                {"_id": matches[0]}
                if matches
                else {"camera_code": camera_code}
            )

            document = {
                "camera_code": camera_code,
                "name": point["name"],
                "rtsp_url": point["ip_address"],
                "description": point["description"],
                "schedule_interval": point["schedule_interval"],
                "danger_threshold": point["danger_threshold"],
                "unit": point["unit"],
                "is_active": True,
                "updated_at": now,
            }

            result = collection.update_one(
                query,
                {
                    "$set": document,
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )

            if result.upserted_id is not None:
                inserted += 1
            elif result.modified_count > 0:
                updated += 1

        print("Import completed successfully.")
        print(f"Items in JSON: {len(points)}")
        print(f"New measurement points: {inserted}")
        print(f"Updated measurement points: {updated}")
        print("RTSP URLs were not printed.")

    finally:
        mongodb.close()


def main() -> None:
    if len(sys.argv) != 2:
        print(
            'Usage: python -m infrastructure.database.mongodb.import_measurement_points "path\\to\\cameras.json"'
        )
        raise SystemExit(2)

    file_path = Path(sys.argv[1]).expanduser()

    if not file_path.is_file():
        print("Error: JSON file not found.")
        raise SystemExit(1)

    try:
        import_measurement_points(file_path)
    except ValueError as exc:
        print(f"Import validation failed: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
