from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_compose_separates_worker_and_externally_published_api():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    worker = compose["services"]["worker"]
    api = compose["services"]["model-api"]
    assert worker["environment"]["DETECTION_API_URL"] == "http://model-api:8000"
    assert "ports" not in worker
    assert api["ports"] == ["${MODEL_API_BIND:-0.0.0.0}:${MODEL_API_PORT:-8000}:8000"]
    assert worker["depends_on"]["model-api"]["condition"] == "service_healthy"
    assert worker["environment"]["DETECTION_API_KEY"] == api["environment"]["DETECTION_API_KEY"]
    assert compose["volumes"]["mongodb_data"]["name"] == "${MONGODB_VOLUME_NAME:-mongodb_mongodb_data}"
    assert api["logging"]["options"]["max-size"] == "10m"


def test_worker_image_does_not_include_models_or_runtime_secrets():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "COPY services" not in dockerfile
    assert "USER app" in dockerfile
    patterns = (ROOT / ".dockerignore").read_text().splitlines()
    assert ".env" in patterns
    assert "infrastructure/database/mongodb/cameras.json" in patterns
