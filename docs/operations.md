# Configuration, reports and operations

[README](../README.md) · [Architecture](architecture.md) · [Models and training](models-and-training.md)

## Configure sources and preprocessing

Copy `infrastructure/database/mongodb/cameras.example.json` to the ignored
`cameras.json` beside it. An illustrative source is:

```json
{
  "name": "Motor current display",
  "code": "AMP-001",
  "ip_address": "rtsp://USERNAME:PASSWORD@camera.example.invalid:554/STREAM_PATH",
  "description": "Current point 01",
  "schedule_interval": 60,
  "danger_threshold": 1000,
  "unit": "ampere"
}
```

Use uppercase codes matching preprocessing profiles. The importer maps `code`
to `camera_code` and `ip_address` to `rtsp_url` in `measurement_points`; it upserts
existing points. Run from the repository root in your intended environment:

```sh
python -m infrastructure.database.mongodb.import_measurement_points infrastructure/database/mongodb/cameras.json
```

Use the [quick start](../README.md#-quick-start) for the Compose equivalent.
Restart the worker after source changes; active sources are loaded at startup.
Avoid multiple production workers capturing the same source list.

| `unit` | Meaning | Scheduling |
| --- | --- | --- |
| `ampere` | Current; default for AMP | 60-second target cadence. |
| `celsius` | Temperature; default for SRC | Configured interval. |
| `kilogram` | Weight metadata | Configured interval. |
| `meters_per_second` | Speed metadata | Configured interval. |

Units do not create OCR routes; prefixes still select the backend.
`danger_threshold` is stored metadata, not an immediate SMS alarm trigger.

Profiles in `config/camera_preprocessing.json` have `enabled` and an ordered
`pipeline`. Supported operations: `crop`, `mask`, `weighted_adjustment`,
`grayscale`, `denoise`. Crop uses pixel `[x1, y1, x2, y2]` within the frame;
mask coordinates refer to the image at that step. For example:

```json
{
  "cameras": {
    "AMP-001": {
      "enabled": true,
      "pipeline": [
        {"operation": "crop", "region": [100, 200, 300, 280]},
        {"operation": "mask", "rectangles": []},
        {"operation": "weighted_adjustment", "alpha": 1.1, "beta": 0}
      ]
    }
  }
}
```

These coordinates are illustrative. Calibrate on your frames, including zeros
and confusing digits; excessive masks can remove identifying segments. The
repository profiles are disabled placeholders.

## Environment and API access

[`.env.example`](../.env.example) lists current settings. Both model and worker
need the same nonempty `DETECTION_API_KEY`. Generate one locally:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Prediction uses `X-API-Key`. No configured server key returns 503; wrong/missing
request key returns 401. Default upload limit is 10 MiB. Public `/health` checks
process liveness, not loaded-model readiness or accuracy.

Exported shell variables take precedence over `.env`; restart after edits.
Host `MONGODB_URI` and `MONGODB_DATABASE` must select the same intended database.
Within Compose, `DOCKER_MONGODB_URI` uses `mongodb`, not `localhost`.

For local execution, install worker/model dependencies or use the project
Pipenv environment, then run in separate terminals:

```sh
python -m services.detection
python main.py
```

The explicit Uvicorn equivalent for the model is:

```sh
uvicorn services.detection.app:app --host 0.0.0.0 --port 8000 --workers 1
```

Set `DETECTION_API_URL` accordingly. The module launcher also accepts `API_HOST`
and `API_PORT`. Multiple Uvicorn processes create independent model instances;
budget their memory/concurrency intentionally.

See [standalone Docker](docker.md#run-only-the-model-without-compose) for a model
without Compose. Bind `MODEL_API_BIND=127.0.0.1` for host-local access, or choose
the intended interface for a trusted network. Use TLS across untrusted networks.
URL-encode reserved password characters; keep real credentials in ignored local
configuration. New initialization variables do not reset users in an existing
MongoDB data volume.

## Delivery and local reports

ERP mode (`YOURCOMPANY_ERP_ENABLED=true`) needs `YOURCOMPANY_DB_HOST`,
`YOURCOMPANY_DB_USER`, `YOURCOMPANY_DB_PASSWORD`, `YOURCOMPANY_DB_NAME`.
The adapter inserts into `ServerRoomTemp` using `Date`, `Time`, `Temperature`,
`CreateDateTime`, `RecordType`. Adapt the schema for another ERP. Observations
are formatted in Asia/Tehran, and source descriptions identify record types.

File mode (`YOURCOMPANY_ERP_ENABLED=false`) creates no ERP client. MongoDB is
still required for sources, history and the outbox. Local output defaults to
`infrastructure/storage/yourcompany_exports`; Docker uses
`/app/storage/yourcompany_exports` on its worker data volume.

| Artifact | Contents |
| --- | --- |
| `records.sqlite3` | Persistent event journal with event-ID deduplication. |
| `readings-YYYY-MM-DD.html` | Self-contained report for a Tehran observation day; Gregorian filename. |
| Summary | Per-source delivered records, zeros and unavailable markers; known active sources without records show zero. |
| Table | Camera code/name/description, unit, readable/raw value, observation time and file-write time with offsets. |

Counts are policy-selected deliveries, not all attempted captures. A fallback
can deliver an earlier accepted zero even when the raw anomaly was nonzero;
use MongoDB raw observations for an exact audit.

Reports refresh at most once per 60 seconds when the file worker next processes
or polls; shutdown flushes them. Refresh the browser and keep the journal with
the HTML. Output errors remain retryable without automatic SQL fallback.

Destination is fixed when queued. ERP events pause in file mode; old file events
remain file-bound after switching back. Delivered ERP history is not exported
retroactively. SQL writes can repeat after interrupted acknowledgement; see
[delivery guarantees](architecture.md#persistence-and-delivery-guarantees).

## Daily SMS reports

At **06:01 Asia/Tehran**, the scheduler queries the previous Tehran calendar
day in SQL Server and formats a Jalali report date. Active Celsius source
descriptions select ERP record types. Each section reports minimum, maximum,
mean and count, or states that no data was recorded.

Enable ERP delivery, configure SQL settings and set:

```dotenv
DAILY_REPORT_ENABLED=true
GHASEDAK_API_KEY=YOUR_KEY
GHASEDAK_LINE_NUMBER=YOUR_LINE
DAILY_REPORT_RECIPIENTS=RECIPIENT_1,RECIPIENT_2
```

Recipients are comma-separated. The provider is Ghasedak; the current report
text is Persian. Restart after changes. File mode does not build SMS summaries
from local SQLite/HTML: ERP-backed reporting is disabled there.

Illustrative raw values `[217, 220, 230, -2]` become `[21.7, 22.0, 23.0]` °C:

```text
📍 Temperature point 01
🔺 بالاترین: 23.00 درجه سانتی‌گراد
🔻 کمترین: 21.70 درجه سانتی‌گراد
📊 میانگین: 22.23 درجه سانتی‌گراد
📝 تعداد رکورد: 3
```

Divide by ten once, before statistics. Stored OCR/ERP values stay raw; current
values are not divided. Zero counts; `-2`, booleans and non-finite values do not.
Do not feed already-converted Celsius readings into this report.

These are daily summaries, not immediate anomaly/threshold alarms. Deliveries
arriving in ERP after report generation may be absent; corrected historical
reports are not automatically resent.

## Logs and troubleshooting

`LOG_FORMAT=text` provides readable time/level/service/module logs; `json` is
available for collectors. Timezone defaults to Asia/Tehran. Reading results and
durations are visible at INFO; jobs taking at least 60 seconds emit a warning.

| Symptom | Check |
| --- | --- |
| Prediction 503 | Missing server-side `DETECTION_API_KEY`; set it and restart. |
| Prediction 401 | Wrong/missing `X-API-Key` or mismatched worker/model keys. |
| Camera not found | Normalized code, actual database/server and imported `measurement_points`. |
| MongoDB authentication failure | Credentials, `authSource` and users in the mounted volume. |
| Capture warning / `-2` | RTSP, network, connection limits and open/read durations. |
| Missing minute observations | Capture/API/total time and queueing; no synthetic minute backfill. |
| No daily SMS | ERP mode, report flag, Ghasedak, recipients and matching Celsius descriptions. |
| Incorrect crop | Profile calibration, enablement and actual frame dimensions. |

Capture failure is an expected short warning. API, persistence and unexpected
errors keep diagnostic tracebacks. Python logging redacts URL credentials and
configured long secrets; native libraries may print their own messages.
