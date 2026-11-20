# Separate worker and model images

The worker image contains camera capture, preprocessing, dataset collection,
MongoDB/outbox delivery and daily reports. It has no Paddle, Torch, Ultralytics
or model weights. The CPU model image contains the existing PP-OCRv6 medium v2
recognizer and YOLO weights and provides the detection HTTP API. It needs no
MongoDB, cameras, ERP connection or Compose network to serve inference.

The root Compose file runs `worker`, `model-api` and MongoDB. The worker calls
`http://model-api:8000`; the API is also published on host port 8000, by default
on all host interfaces. MongoDB remains published only on loopback.

## Configure and start

Keep your existing local camera configuration and `.env`. Add/set:

```dotenv
DETECTION_API_KEY=YOUR_LONG_RANDOM_KEY
MONGO_INITDB_ROOT_USERNAME=admin
MONGO_INITDB_ROOT_PASSWORD=YOUR_DATABASE_PASSWORD
DOCKER_MONGODB_URI=mongodb://admin:YOUR_URL_ENCODED_PASSWORD@mongodb:27017/digit_ocr7?authSource=admin
MONGODB_DATABASE=digit_ocr7
MONGODB_VOLUME_NAME=mongodb_mongodb_data
MODEL_API_BIND=0.0.0.0
MODEL_API_PORT=8000
LOG_LEVEL=INFO
LOG_FORMAT=text
LOG_COLOR=auto
LOG_TIMEZONE=Asia/Tehran
```

Use the same API key in external requests. Generate a key with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`. Store the key only
in your ignored local `.env` or a secret store. Quote `.env` values containing
`$` with single quotes. Keep the host-side `MONGODB_URI` using localhost; the
Docker-specific URI uses `mongodb`, not localhost. ERP IP addresses/hostnames
must also be reachable from the worker container.

Before replacing the old MongoDB Compose deployment, inspect its data mount:

```sh
docker ps
docker inspect YOUR_OLD_MONGO_CONTAINER --format '{{json .Mounts}}'
```

Set `MONGODB_VOLUME_NAME` to the exact existing `/data/db` volume name. The
default matches the old nested Compose project's usual `mongodb_mongodb_data`
name, but verify it. Stop the old Mongo container before starting the new one;
two Mongo processes must never open the same volume. Do not use `down -v`.
Keep existing credentials for an existing volume; initialization variables do
not reset users. Switching volume names selects different data.

The local `infrastructure/database/mongodb/cameras.json` must exist. For a fresh
installation, copy the example and populate real RTSP URLs first. The worker
mounts this file and `config/camera_preprocessing.json` read-only. Its UID is
10001, so those files must be readable by the container user. Inference weights
are baked into the model image, not mounted from a Windows-specific path.

From the repository root:

```sh
docker compose build
docker compose up -d --wait mongodb model-api
docker compose run --rm --no-deps worker python -m infrastructure.database.mongodb.import_measurement_points infrastructure/database/mongodb/cameras.json
docker compose up -d worker
docker compose logs -f --tail 100 worker model-api
```

Dataset samples persist in the worker data volume at `/app/storage/dataset`.
Changing model weights requires rebuilding/recreating `model-api`; worker
changes require rebuilding/recreating `worker`. For a routine code update:

```sh
docker compose up -d --build
```

## Call the API from outside Compose

Health: `http://localhost:8000/health`. Interactive API docs:
`http://localhost:8000/docs`. Supply `X-API-Key` on prediction requests:

```sh
curl -X POST http://localhost:8000/predict/AMP-001 -H "X-API-Key: YOUR_LONG_RANDOM_KEY" -F "file=@sample.jpg"
```

On PowerShell use `curl.exe`. From another machine, replace localhost with the
Docker host's IP/DNS and allow the published port on the relevant network.
Use TLS through a reverse proxy for traffic crossing an untrusted network.
Set `MODEL_API_BIND=127.0.0.1` if only host-local access is needed.

`AMP-*` selects Paddle recognition and `SRC-*` selects YOLO digit detection.
Camera code is a routing selector; the model API does not query source records.
Image inputs must already be cropped/preprocessed as in the worker pipeline.
Without a configured key `/predict` returns 503; missing/wrong keys return 401.
The health endpoint does not require a key and reports process liveness, not
model accuracy or model warmup. Models load lazily on the first matching request;
allow for the initial CPU load time. Requests are limited by
`OCR_MAX_CONCURRENCY` (default 4) and `MAX_UPLOAD_BYTES` (default 10 MiB).

## Run only the model without Compose

Build from the repository root so Docker can copy both selected weight sets:

```sh
docker build -f services/detection/Dockerfile -t yourcompany-ocr-model:local .
docker run -d --name yourcompany-model --restart unless-stopped -p 8000:8000 -e DETECTION_API_KEY=YOUR_LONG_RANDOM_KEY yourcompany-ocr-model:local
```

Both images run as a non-root user. No `.env`, live RTSP configuration, datasets
or training checkpoints are copied into the images. The model image is CPU-only;
it does not require a GPU or CUDA. The root Compose deployment rotates Docker
logs at 10 MiB, keeping three files per service.

## Logging

Text logs use Tehran timestamps with timezone, level, service, module and message:

```text
2026-11-17T14:00:00.000+03:30 | INFO     | worker    | application.reading_result_handler | Reading processed: camera=AMP-001 value=0 status=valid anomaly=False erp_value=0
```

Use `LOG_LEVEL=DEBUG` for dataset/preprocessing/queue details. Routine duplicate
success messages are debug-level; reading results, ERP delivery results and
inference timings remain visible at INFO. `LOG_FORMAT=json` emits one JSON record
per line for log collectors. `LOG_COLOR=always` forces colored levels when wanted;
auto mode avoids ANSI escapes in Docker's non-TTY logs. Python application logs
redact URL credentials and configured long secrets, including exception text;
native ML libraries can still emit their own startup messages.

GitHub Actions builds both images and exercises both model routes through a
published host port in a standalone container on PRs/main pushes. Unit tests use
fake models and additionally cover authentication, upload limits, concurrency,
client headers and log formatting/redaction. No production camera, database or
SMS service is used by these checks.
