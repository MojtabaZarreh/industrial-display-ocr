
import os
import uuid
from pathlib import Path
from threading import Lock
from PIL import Image
from ultralytics import YOLO


CLASS_MAP_TYPE_1 = {
    f"D{i}": i for i in range(10)
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CLASS_MAP_TYPE_2 = {
    str(i): i for i in range(10)
}

class YoloDetector:
    def __init__(self) -> None:
        model_path = os.getenv("YOLO_MODEL_PATH")

        if not model_path:
            raise RuntimeError("YOLO_MODEL_PATH is not configured.")

        path = Path(model_path).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.is_file():
            raise FileNotFoundError(
                f"YOLO model file not found: {model_path}"
            )

        self.model_type = int(os.getenv("YOLO_MODEL_TYPE", "1"))
        self.model = YOLO(str(path.resolve()))
        self._prediction_lock = Lock()

    def predict(self, image: Image.Image) -> list[dict]:
        with self._prediction_lock:
            results = self.model.predict(image, conf=0.5, iou=0.4, verbose=False)
        predictions = []

        for result in results:
            if result.boxes is None:
                continue

            for row in result.boxes.data.tolist():
                x1, y1, x2, y2, confidence, class_id = row
                class_id = int(class_id)
                class_name = self.model.names[class_id]

                class_map = (
                    CLASS_MAP_TYPE_1
                    if self.model_type == 1
                    else CLASS_MAP_TYPE_2
                )

                mapped_class_id = class_map.get(
                    str(class_name),
                    class_id,
                )

                predictions.append({
                    "x": round((x1 + x2) / 2, 1),
                    "y": round((y1 + y2) / 2, 1),
                    "width": round(x2 - x1, 1),
                    "height": round(y2 - y1, 1),
                    "confidence": float(confidence),
                    "class": str(class_name),
                    "class_id": mapped_class_id,
                    "detection_id": str(uuid.uuid4()),
                })

        return predictions

_detector = None
_detector_lock = Lock()

def get_yolo_detector() -> YoloDetector:
    global _detector

    with _detector_lock:
        if _detector is None:
            _detector = YoloDetector()
        return _detector

def detect_digits(image: Image.Image) -> list[dict]:
    return get_yolo_detector().predict(image)
