import asyncio
import io
import logging
import os
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from PIL import Image, UnidentifiedImageError
from config import settings
from .inference import select_model, run_inference
from .schemas import PredictionResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("DETECTION_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Detection API authentication is not configured.")
    if not x_api_key or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@router.post("/predict/{camera_code}", response_model=PredictionResponse, dependencies=[Depends(require_api_key)])
async def predict(request: Request, camera_code: str, file: UploadFile = File(...)):
    try:
        try:
            model_type = select_model(camera_code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        contents = await file.read(settings.MAX_UPLOAD_BYTES + 1)
        if len(contents) > settings.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Uploaded image is too large.")
        with Image.open(io.BytesIO(contents)) as source:
            image = source.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image.") from exc
    finally:
        await file.close()

    camera_code = camera_code.strip().upper()
    start_time = time.perf_counter()
    inference_id = str(uuid.uuid4())
    try:
        async with request.app.state.inference_slots:
            result = await asyncio.to_thread(run_inference, camera_code, image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception:
        logger.exception("Inference failed: camera=%r model=%s inference_id=%s", camera_code, model_type, inference_id)
        raise

    elapsed_time = time.perf_counter() - start_time
    logger.info(
        "Inference completed: camera=%s model=%s duration_ms=%.0f predictions=%s inference_id=%s",
        camera_code, model_type, elapsed_time * 1000, len(result), inference_id,
    )

    return {
        "inference_id": inference_id, "camera_code": camera_code, "model": model_type,
        "time": round(elapsed_time, 4),
        "image": {"width": image.width, "height": image.height},
        "predictions": result,
    }
