
from typing import Any, Literal
from pydantic import BaseModel, Field

class ImageInfo(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class DetectionPrediction(BaseModel):
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    class_name: str = Field(alias="class")
    class_id: int
    detection_id: str


class TextPrediction(BaseModel):
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class PredictionResponse(BaseModel):
    inference_id: str
    camera_code: str
    model: Literal["paddle", "yolo"]
    time: float = Field(ge=0)
    image: ImageInfo
    predictions: list[dict[str, Any]]
