from __future__ import annotations
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from PIL import Image


class DatasetCollector:
    def __init__(self, location: str | Path, camera_id: str):
        if not isinstance(camera_id, str) or not camera_id.strip():
            raise ValueError("camera_id must be a non-empty string.")

        self.location = Path(location).expanduser().resolve()
        self.camera_id = camera_id.strip()

    def collect(
        self,
        image: Image.Image,
        predictions: list[dict],
        camera_code: str,
        *,
        model_version: str | None = None,
        captured_at: datetime | None = None,
        preprocessing: dict | None = None,
    ) -> dict:
        if not isinstance(image, Image.Image):
            raise TypeError("image must be a PIL Image.")

        if image.width < 1 or image.height < 1:
            raise ValueError("image dimensions must be positive.")

        if not isinstance(predictions, list) or not all(
            isinstance(item, dict) for item in predictions
        ):
            raise TypeError("predictions must be a list of dictionaries.")

        if not isinstance(camera_code, str):
            raise TypeError("camera_code must be a string.")

        camera_code = camera_code.strip().upper()

        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,127}", camera_code):
            raise ValueError("camera_code contains unsupported characters.")

        timestamp = captured_at or datetime.now(timezone.utc)

        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware.")

        timestamp = timestamp.astimezone(timezone.utc)
        sample_id = uuid4().hex

        dataset_entry = {
            "schema_version": 1,
            "sample_id": sample_id,
            "camera_id": self.camera_id,
            "camera_code": camera_code,
            "captured_at": timestamp.isoformat(),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "model_version": model_version,
            "image_file": "image.png",
            "image_width": image.width,
            "image_height": image.height,
            "image_mode": image.mode,
            "predictions": predictions,
            "verified_label": None,
            "review_status": "pending",
            "preprocessing": preprocessing,
        }

        dataset_entry = json.loads(
            json.dumps(dataset_entry, ensure_ascii=False, allow_nan=False)
        )

        parent = (
            self.location
            / camera_code
            / timestamp.strftime("%Y-%m-%d")
        )
        parent.mkdir(parents=True, exist_ok=True)

        sample_directory = parent / sample_id
        temporary_directory = Path(
            tempfile.mkdtemp(prefix=".pending-", dir=parent)
        )

        try:
            image_path = temporary_directory / "image.png"
            image.save(image_path, format="PNG")

            dataset_entry["image_sha256"] = hashlib.sha256(
                image_path.read_bytes()
            ).hexdigest()

            metadata_path = temporary_directory / "metadata.json"
            metadata_path.write_text(
                json.dumps(
                    dataset_entry,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                ),
                encoding="utf-8",
            )

            temporary_directory.rename(sample_directory)

        except BaseException:
            shutil.rmtree(temporary_directory, ignore_errors=True)
            raise

        return {
            **dataset_entry,
            "sample_directory": str(sample_directory),
            "image_path": str(sample_directory / "image.png"),
            "metadata_path": str(sample_directory / "metadata.json"),
        }

    def _collect_dataset(
        self,
        image: Image.Image,
        predictions: list[dict],
        camera_code: str,
    ) -> dict:
        return self.collect(image, predictions, camera_code)
