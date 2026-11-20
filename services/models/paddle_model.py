import os
from pathlib import Path
from threading import Lock
import numpy as np
from PIL import Image, ImageOps
from paddleocr import TextRecognition


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class PaddleRecognizer:
    def __init__(self) -> None:
        model_dir = os.getenv("PADDLE_MODEL_DIR", "").strip()

        if not model_dir:
            raise RuntimeError("PADDLE_MODEL_DIR is not configured.")

        path = Path(model_dir).expanduser()

        if not path.is_absolute():
            path = PROJECT_ROOT / path

        path = path.resolve()

        if not path.is_dir():
            raise FileNotFoundError(
                f"Paddle model directory not found: {path}"
            )

        for filename in (
            "inference.json",
            "inference.pdiparams",
            "inference.yml",
        ):
            model_file = path / filename

            if not model_file.is_file():
                raise FileNotFoundError(
                    f"Required model file not found: {model_file}"
                )

        device = os.getenv("PADDLE_DEVICE", "cpu").strip() or "cpu"

        self.model = TextRecognition(
            model_name="PP-OCRv6_medium_rec",
            model_dir=str(path),
            device=device,
        )

        self._prediction_lock = Lock()

    def predict(self, image: Image.Image) -> list[dict]:
        if not isinstance(image, Image.Image):
            raise TypeError("image must be a PIL Image.")

        image = ImageOps.exif_transpose(image).convert("RGB")

        if image.width == 0 or image.height == 0:
            raise ValueError("The input image is empty.")

        image_array = np.ascontiguousarray(
            np.asarray(image)[:, :, ::-1]
        )

        predictions = []

        with self._prediction_lock:
            results = self.model.predict(input=image_array)

            for result in results:
                data = getattr(result, "json", result)

                if callable(data):
                    data = data()

                if not isinstance(data, dict):
                    raise TypeError(
                        "The recognition result must be a dictionary."
                    )

                data = data.get("res", data)

                if not isinstance(data, dict):
                    raise TypeError(
                        "The recognition result payload is invalid."
                    )

                text = data.get("rec_text", "")
                score = data.get("rec_score")

                predictions.append({
                    "text": str(text) if text is not None else "",
                    "confidence": (
                        float(score) if score is not None else None
                    ),
                })

        return predictions


_recognizer: PaddleRecognizer | None = None
_recognizer_lock = Lock()


def get_paddle_recognizer() -> PaddleRecognizer:
    global _recognizer

    with _recognizer_lock:
        if _recognizer is None:
            _recognizer = PaddleRecognizer()

        return _recognizer


def recognize_image(image: Image.Image) -> list[dict]:
    return get_paddle_recognizer().predict(image)
