# Architecture and data lifecycle

[README](../README.md) · [Models and training](models-and-training.md) · [Operations](operations.md)

## Service boundaries

The worker handles camera acquisition and business integration. The model API
handles inference without knowing RTSP addresses, MongoDB records or ERP
credentials. Their separate images allow a worker installation without Paddle,
Torch or model weights.

| Component | Responsibility | Implementation |
| --- | --- | --- |
| Camera worker | Read a fresh frame, record UTC observation time, release stream | `application/camera_worker.py` |
| Processing service | Schedule sources and coordinate image processing, API calls and callbacks | `application/processing_service.py` |
| Preprocessor | Execute ordered per-camera operations | `application/preprocessing/engin.py` |
| Model API | Authenticate requests, decode uploads, select/run a backend | `services/detection/` |
| Reading handler | Validate, extract digits, apply temporal policy, select delivery value | `application/reading_result_handler.py` |
| Repositories | Sources, history and outbox events | `infrastructure/database/mongodb/` |
| Delivery workers | Claim events and write to their destination | `application/delivery_worker.py` |
| Daily reports | Query ERP temperatures and send SMS | `application/temperature_report_service.py` |

The worker applies preprocessing, encodes JPEG at quality 90, and posts to
`/predict/{camera_code}` with `X-API-Key`. The API returns an inference ID, backend,
image dimensions, elapsed time and predictions. `AMP-*` selects Paddle sequence
recognition; `SRC-*` selects YOLO digit detection. The extractor sorts YOLO boxes
by horizontal center and joins their digits. The API does not apply camera ROIs;
external clients must supply suitable crops. Routing follows prefixes, not units.

## Concurrency and timing

| Layer | Current behavior |
| --- | --- |
| Camera pool | 32 threads in `main.py`; one outstanding job per camera. |
| Scheduling | Monotonic deadlines, 0.2-second polling, earliest due sources first. |
| Ampere interval | 60 seconds, including legacy 300/3600-second source configurations. |
| Other units | Positive finite `schedule_interval` from source configuration. |
| Capture | One fresh open/read attempt; 5-second FFmpeg open/read timeouts; immediate release. |
| HTTP | 5-second connect timeout and 60-second read timeout. |
| API admission | Async semaphore, default 4 requests; inference via `asyncio.to_thread`. |
| Model execution | A lock per lazy-loaded model instance serializes its predictions. |
| Delivery | Dedicated threads, independent of capture scheduling; default idle poll 2 seconds. |
| Reporting | APScheduler background job, one instance, coalesced missed runs, one-hour grace period. |

Completion does not advance a camera's deadline again. An overdue source can
run once its previous job finishes and a worker is free. Long overruns skip
expired slots instead of replaying imaginary measurements. More camera threads
cannot remove the model lock or accelerate a slow RTSP endpoint.

A 60-second target is not a sampling SLA. Watch capture/inference/total durations.
Anomalies and capture failures have explicit delivery policies; API failures or
review-only OCR may produce no delivery event. There is no historical minute
backfill or guarantee of 1,440 successful observations per camera per day.

## Validation and temporal decisions

Response validation and digit extraction precede anomaly detection. Invalid
OCR is not zero. The current extractor accepts unsigned integer readings;
YOLO boxes should represent one display row.

For a nonzero value, select up to ten preceding accepted nonzero readings by
capture time. With at least three references, the defaults are:

```text
baseline = median(reference_values)
allowed_change = max(abs(baseline) * 0.5, 0.0)
is_anomaly = abs(current_value - baseline) > allowed_change
```

Validated zeros are accepted/queued and excluded from that reference window.
They preserve the running baseline through a stop, permitting a normal return.
An arbitrary spike after zero is still tested. Anomalies retain their observed
value in history; the destination receives the latest preceding accepted value,
which may itself be zero. The delivery uses the current sample's timestamp,
not the fallback sample's timestamp. No usable fallback means no invented value.

Persistent out-of-range shifts are not automatically adopted as a new baseline.
See [the full policy](reading-delivery.md) for examples and legacy-history rules.

## Persistence and delivery guarantees

MongoDB stores source definitions, readings and outbox events. Delivery workers
atomically claim an event with a lease and acknowledge it after the destination
write. Failed events become retryable; current backoff grows from 2 seconds to
256 seconds. These are delivery retries, independent of single-attempt capture.

SQL delivery is **not a distributed exactly-once transaction**. A process failure
after SQL commit but before MongoDB acknowledgement can repeat an insert. The
supplied adapter has no destination event-ID uniqueness constraint. Add ERP-side
idempotency if required. Reading persistence and outbox queueing also are not a
cross-collection transaction; inspect persistence failures rather than assuming
a delivery exists.

The local sink deduplicates event IDs in SQLite and replaces rendered HTML
atomically. An output failure leaves an event retryable, without switching to
SQL. The destination is fixed at queue time: old ERP events pause in file mode;
file events can continue draining after ERP mode is restored.

Order by capture time when reconstructing history: destination insertion order
may differ after retries. Captures use UTC; ERP formatting/report boundaries use
Asia/Tehran. The existing ERP schema stores minute-precision time and a Jalali
date string. A failed capture gets its failure observation time.

## Dataset lifecycle

After a successful API response, the client decodes the exact posted JPEG and
passes those RGB pixels to `DatasetCollector`. Each sample contains:

| Artifact / field | Purpose |
| --- | --- |
| `image.png` | Preprocessed inference-input pixels without another lossy encode. |
| `metadata.json` | Schema version, UUID, camera ID/code, capture/collection times. |
| `image_sha256`, dimensions, mode | Integrity and image metadata. |
| `predictions` | Candidate labels and confidence/box information. |
| `preprocessing` | Profile used for this observation. |
| `verified_label`, `review_status` | Initially `null` / `pending`; external human review is required. |
| `model_version` | Supported by the collector, but not populated by the current caller. |

The sample is assembled in a temporary directory, then renamed into
`DATASET_DIR/CAMERA_CODE/YYYY-MM-DD/SAMPLE_ID/` after both files are written.
Collection precedes reading validation, so invalid/anomalous predictions may
also be saved. Collection errors are logged without discarding the API result.
Failed capture/API calls cannot provide a sample.

For training, correct labels, group related sessions, deduplicate images,
prepare the notebook manifest and freeze the split. Camera ROI processing need
not be repeated; model resize/normalization and deliberate augmentation remain
necessary. There is no automatic retraining or model promotion.
