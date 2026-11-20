import argparse
import logging
from datetime import datetime
from pathlib import Path
import cv2
from PIL import Image
from application.preprocessing.engin import PreprocessingEngine
from infrastructure.database.mongodb.mongo import MongoDB
from infrastructure.database.mongodb.repositories import MeasurementPointRepository
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "infrastructure" / "storage"


def capture_frame(rtsp_url: str) -> Image.Image:
    cap = cv2.VideoCapture(rtsp_url)

    try:
        if not cap.isOpened():
            raise RuntimeError("Failed to connect to camera.")

        success, frame = cap.read()

        if not success or frame is None:
            raise RuntimeError("Failed to capture camera frame.")

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame_rgb)

    finally:
        cap.release()


def main(camera_code: str) -> None:
    mongodb = MongoDB()
    mongodb.connect()

    try:
        repository = MeasurementPointRepository(mongodb.database)
        camera = repository.get_by_code(camera_code)

        if not camera:
            raise ValueError(
                f"Camera {camera_code!r} was not found in MongoDB."
            )

        if not camera.get("is_active", False):
            raise ValueError(f"Camera {camera_code} is inactive.")

        rtsp_url = camera.get("rtsp_url")
        if not rtsp_url:
            raise ValueError(
                f"Camera {camera_code} has no RTSP URL configured."
            )

        logger.info("Camera found: %s", camera.get("name", camera_code))

        original_image = capture_frame(rtsp_url)

        preprocessor = PreprocessingEngine()

        image_array = np.asarray(original_image)
        image_bgr = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)

        processed_bgr = preprocessor.process(
            camera_code=camera_code,
            image=image_bgr,
        )

        processed_rgb = cv2.cvtColor(processed_bgr, cv2.COLOR_BGR2RGB)
        processed_image = Image.fromarray(processed_rgb)

        if not isinstance(processed_image, Image.Image):
            raise TypeError(
                "Preprocessor output must be a PIL Image."
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = OUTPUT_DIR / camera_code / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)

        original_path = output_dir / "original.jpg"
        processed_path = output_dir / "processed.jpg"

        original_image.save(original_path, quality=95)
        processed_image.save(processed_path, quality=95)

        logger.info("Original image saved: %s", original_path)
        logger.info("Processed image saved: %s", processed_path)
        logger.info("Original dimensions: %s", original_image.size)
        logger.info("Processed dimensions: %s", processed_image.size)

        print("Test completed successfully.")
        print(f"Camera code: {camera_code}")
        print(f"Original image: {original_path}")
        print(f"Processed image: {processed_path}")

    finally:
        mongodb.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--camera",
        required=True,
        help="Camera code stored in MongoDB.",
    )
    args = parser.parse_args()
    main(args.camera)
