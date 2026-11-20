FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PADDLE_DEVICE=cpu \
    PADDLE_MODEL_DIR=/opt/models/recognizer \
    YOLO_MODEL_PATH=/opt/models/detector/model.pt \
    YOLO_MODEL_TYPE=1 \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    YOLO_CONFIG_DIR=/home/app/.config/Ultralytics

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

COPY services/detection/requirements.txt /tmp/model-requirements.txt
RUN python -m pip install --no-cache-dir torch==2.15.0 torchvision==0.29.2 \
        --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir -r /tmp/model-requirements.txt

COPY config/settings.py config/logging.py config/
COPY services/detection/ services/detection/
COPY services/models/ services/models/
COPY services/weights/medium_digit_rec_v2/inference/ /opt/models/recognizer/
COPY services/weights/model1-new.pt /opt/models/detector/model.pt

USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["python", "-m", "services.detection"]
