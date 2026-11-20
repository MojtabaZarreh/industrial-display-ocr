import json
from unittest.mock import Mock

import pytest

from domain.measurements import resolve_unit
from infrastructure.database.mongodb import import_measurement_points as importer
from infrastructure.database.mongodb.repositories import MeasurementPointRepository


def point(code="SRC-001", **updates):
    return {
        "name": "Test camera", "code": code,
        "ip_address": "rtsp://camera.example.invalid/stream",
        "description": "Test source", "schedule_interval": 60,
        "danger_threshold": 30, **updates,
    }


def write_points(tmp_path, points):
    path = tmp_path / "cameras.json"
    path.write_text(json.dumps(points), encoding="utf-8")
    return path


@pytest.mark.parametrize("code,unit", [
    ("src-001", "celsius"), ("AMP-101", "ampere"),
])
def test_legacy_units_are_inferred(code, unit, tmp_path):
    result = importer.load_measurement_points(write_points(tmp_path, [point(code)]))
    assert result[0]["unit"] == unit
    assert result[0]["code"] == code.upper()


@pytest.mark.parametrize("unit", ["celsius", "ampere", "kilogram", "meters_per_second"])
def test_explicit_units_override_prefix_and_support_future_sources(unit, tmp_path):
    result = importer.load_measurement_points(
        write_points(tmp_path, [point("NEW-001", unit=unit)])
    )
    assert result[0]["unit"] == unit


@pytest.mark.parametrize("unit", ["temperature", "", 1, False])
def test_invalid_units_are_rejected(unit, tmp_path):
    with pytest.raises(ValueError):
        importer.load_measurement_points(write_points(tmp_path, [point(unit=unit)]))


def test_unknown_legacy_source_needs_unit():
    with pytest.raises(ValueError, match="explicit unit"):
        resolve_unit("NEW-001")


def test_duplicate_codes_are_rejected_after_normalization(tmp_path):
    with pytest.raises(ValueError, match="Duplicate camera code"):
        importer.load_measurement_points(write_points(tmp_path, [point("src-001"), point("SRC-001")]))


def test_import_backfills_unit_and_preserves_existing_document(tmp_path, database, monkeypatch):
    old_id = database.measurement_points.insert_one({"camera_code": "src-001"}).inserted_id
    mongo = Mock(database=database)
    monkeypatch.setattr(importer, "MongoDB", lambda: mongo)
    path = write_points(tmp_path, [point("SRC-001"), point("AMP-001")])
    importer.import_measurement_points(path)
    importer.import_measurement_points(path)
    assert database.measurement_points.count_documents({}) == 2
    assert database.measurement_points.find_one({"_id": old_id})["unit"] == "celsius"
    assert database.measurement_points.find_one({"camera_code": "AMP-001"})["unit"] == "ampere"
    assert mongo.close.call_count == 2


def test_repository_reads_legacy_sources_without_migration(database):
    database.measurement_points.insert_one({"camera_code": "SRC-001", "is_active": True})
    repository = MeasurementPointRepository(database)
    assert repository.get_by_code("src-001")["unit"] == "celsius"
    assert repository.list_active()[0]["unit"] == "celsius"


def test_repository_create_and_update_unit(database):
    repository = MeasurementPointRepository(database)
    source = point("amp-001")
    source["camera_code"] = source.pop("code")
    source["rtsp_url"] = source.pop("ip_address")
    repository.create(source)
    assert repository.get_by_code("AMP-001")["unit"] == "ampere"
    assert repository.update("amp-001", {"unit": " KILOGRAM "})
    assert repository.get_by_code("AMP-001")["unit"] == "kilogram"
    with pytest.raises(ValueError):
        repository.update("AMP-001", {"unit": "invalid"})
    assert repository.get_by_code("AMP-001")["unit"] == "kilogram"


def test_example_sources_all_have_valid_explicit_units():
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "infrastructure/database/mongodb/cameras.example.json"
    sources = importer.load_measurement_points(path)
    assert len(sources) == 20
    assert all(source["unit"] in {"celsius", "ampere"} for source in sources)
