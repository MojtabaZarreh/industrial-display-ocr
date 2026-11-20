FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATASET_DIR=/app/storage/dataset

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY application/ application/
COPY config/ config/
COPY domain/ domain/
COPY infrastructure/ infrastructure/
COPY main.py ./
RUN mkdir -p /app/storage/dataset && chown -R app:app /app/storage

USER app
STOPSIGNAL SIGINT
CMD ["python", "main.py"]
