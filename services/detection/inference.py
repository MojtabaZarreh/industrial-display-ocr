from PIL import Image

def select_model(camera_code: str) -> str:
    code = camera_code.strip().upper()

    if code.startswith("AMP-"):
        return "paddle"
    if code.startswith("SRC-"):
        return "yolo"

    raise ValueError(f"Unsupported camera code: {camera_code}")


def run_inference(camera_code: str, image: Image.Image) -> list[dict]:
    model_type = select_model(camera_code)

    if model_type == "paddle":
        from ..models.paddle_model import recognize_image
        return recognize_image(image)
    if model_type == "yolo":
        from ..models.yolo_model import detect_digits
        return detect_digits(image)

    raise ValueError(f"Unsupported model: {model_type}")
