import asyncio
import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from application.camera_worker import CapturedFrame
from application import processing_service
from config import settings
from services.detection import app as app_module
from services.detection import router as routes


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (160, 48), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def api(monkeypatch, request):
    monkeypatch.setenv("DETECTION_API_KEY", "test-api-secret")
    monkeypatch.setattr(settings, "OCR_MAX_CONCURRENCY", getattr(request, "param", 4))
    monkeypatch.setattr(app_module, "configure_logging", lambda service: None)
    with TestClient(app_module.app) as client:
        yield client


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_predict_rejects_missing_or_wrong_key(api, monkeypatch, headers):
    inference = Mock()
    monkeypatch.setattr(routes, "run_inference", inference)
    response = api.post("/predict/AMP-001", files={"file": ("image.png", image_bytes())}, headers=headers)
    assert response.status_code == 401
    inference.assert_not_called()


def test_missing_server_key_disables_prediction(api, monkeypatch):
    monkeypatch.delenv("DETECTION_API_KEY")
    response = api.post("/predict/AMP-001", files={"file": ("image.png", image_bytes())})
    assert response.status_code == 503
    assert api.get("/health").status_code == 200


@pytest.mark.parametrize("code,model", [("amp-001", "paddle"), ("SRC-001", "yolo")])
def test_authenticated_prediction_keeps_response_contract(api, monkeypatch, code, model):
    inference = Mock(return_value=[{"text": "217", "confidence": 0.99}])
    monkeypatch.setattr(routes, "run_inference", inference)
    response = api.post(f"/predict/{code}", files={"file": ("image.png", image_bytes())}, headers={"X-API-Key": "test-api-secret"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["camera_code"] == code.upper()
    assert payload["model"] == model
    assert payload["image"] == {"width": 160, "height": 48}
    assert payload["predictions"][0]["text"] == "217"


def test_invalid_image_and_unsupported_source(api):
    headers = {"X-API-Key": "test-api-secret"}
    assert api.post("/predict/AMP-001", files={"file": ("bad.png", b"invalid")}, headers=headers).status_code == 400
    assert api.post("/predict/UNKNOWN", files={"file": ("image.png", image_bytes())}, headers=headers).status_code == 400


def test_upload_limit_is_enforced(api, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 10)
    response = api.post("/predict/AMP-001", files={"file": ("image.png", image_bytes())}, headers={"X-API-Key": "test-api-secret"})
    assert response.status_code == 413


@pytest.mark.parametrize("api", [1], indirect=True)
def test_inference_concurrency_is_bounded(api, monkeypatch):
    lock = threading.Lock()
    active = maximum = 0

    def inference(*args):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(0.02)
            return []
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(routes, "run_inference", inference)
    def predict(_):
        return api.post("/predict/AMP-001", files={"file": ("image.png", image_bytes())}, headers={"X-API-Key": "test-api-secret"}).status_code

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(predict, range(4))) == [200] * 4
    assert maximum == 1


def test_worker_forwards_api_key(monkeypatch):
    monkeypatch.setenv("DETECTION_API_KEY", "test-api-secret")
    preprocessor = Mock()
    preprocessor.process.side_effect = lambda **kwargs: kwargs["image"]
    monkeypatch.setattr(processing_service, "PreprocessingEngine", Mock(return_value=preprocessor))
    response = Mock()
    response.json.return_value = {"predictions": []}
    context = MagicMock()
    context.__enter__.return_value = response
    post = Mock(return_value=context)
    monkeypatch.setattr(processing_service.requests, "post", post)
    client = processing_service.DetectionAPIClient()
    monkeypatch.setattr(client, "_collect_dataset", Mock())
    frame = CapturedFrame("AMP-001", Image.new("RGB", (160, 48)), datetime.now(timezone.utc))
    client.predict(frame)
    assert post.call_args.kwargs["headers"] == {"X-API-Key": "test-api-secret"}
