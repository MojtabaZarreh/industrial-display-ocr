# YourCompany digit OCR

Camera capture and per-source preprocessing feed the detection API (Paddle for
AMP sources, YOLO for SRC sources). Accepted readings are stored in MongoDB and
delivered to the existing SQL Server ERP through an outbox. Nonzero anomalies use
the previous accepted value for ERP; zeros and returns to the preceding running
range are accepted. Exhausted camera captures queue -2 without routine
tracebacks. See [reading policy](docs/reading-delivery.md).

## Local configuration

Copy `.env.example` to `.env`, and
`infrastructure/database/mongodb/cameras.example.json` to
`infrastructure/database/mongodb/cameras.json`. Replace the example RTSP URLs
with real URLs and configure database/model settings locally. URL-encode reserved
characters in URL passwords. Quote `.env` secrets containing `$` with single
quotes. Environment variables exported by the launching shell take precedence
over `.env`; configuration is loaded once, so restart processes after changes.

For a new MongoDB volume, set `MONGO_INITDB_ROOT_PASSWORD` and use the same
credentials in `MONGODB_URI`. Keep `MONGODB_DATABASE` consistent with the URI.
From the repository root:

```sh
docker compose --env-file .env -f infrastructure/database/mongodb/compose.yaml up -d --wait
python -m infrastructure.database.mongodb.import_measurement_points infrastructure/database/mongodb/cameras.json
```

Initialization credentials do not modify users in an existing MongoDB volume.
No volume deletion or production data migration is performed by this commit.

## Source units

Each source accepts one `unit` field:

| unit | Meaning |
| --- | --- |
| `celsius` | Temperature in degrees Celsius |
| `ampere` | Electric current in amperes |
| `kilogram` | Weight in kilograms |
| `meters_per_second` | Speed in meters per second |

Existing files without this field remain supported: SRC defaults to `celsius`
and AMP to `ampere`. An explicit unit overrides the prefix. Unknown prefixes
require an explicit supported unit. Re-running the import adds the inferred unit
to existing MongoDB sources without changing their `_id`. Legacy documents also
get the default unit on reads, before migration. Weight and speed are metadata
support; adding a new OCR camera prefix still requires an inference routing rule.

Example fragment:

```json
{"code": "SRC-001", "unit": "celsius"}
```

## Daily temperature report

The current displays/ERP store temperature in **tenths of a degree**: `217` is
reported as `21.70` degrees Celsius. The conversion is applied exactly once,
when generating the daily report, before min/max/mean. It is not inferred from
the magnitude of the value. Raw OCR, MongoDB history, outbox and ERP inserts
remain unchanged; ampere values are not divided. Zero is included in statistics;
the camera-failure sentinel `-2` and non-finite values are excluded.

The scheduled report selects active `celsius` sources by their ERP description;
ampere/weight/speed sources are excluded. Descriptions must match `RecordType`
in SQL Server. Without a source repository, the standalone service retains its
three legacy temperature locations. Do not feed already-converted Celsius data
to this raw-value report; mixed historical scales need separate reconciliation.

Set these values in your local `.env` and restart `main.py` to enable SMS:

```dotenv
DAILY_REPORT_ENABLED=true
GHASEDAK_API_KEY=YOUR_KEY
GHASEDAK_LINE_NUMBER=YOUR_LINE
DAILY_REPORT_RECIPIENTS=YOUR_RECIPIENTS
```

ERP connection settings are also required. Reports run at 06:01 Asia/Tehran for
the preceding Tehran calendar day. The example configuration disables automatic
SMS until explicitly enabled.

## Run

For the separate Docker worker/model images, external API access and deployment
commands, see [Docker deployment and logs](docs/docker.md).

Use the existing Pipenv environment (`pipenv sync`) for the model dependencies.
For a pip-based worker installation, `pip install -r requirements.txt` installs
the worker/report dependencies; the detection service additionally requires
its own requirements, PaddleOCR/PaddlePaddle and compatible model weights.

```sh
pipenv run python -m services.detection
pipenv run python main.py
```

Run these commands in separate terminals. Set the same local `DETECTION_API_KEY`
for both processes. Prediction requests require the `X-API-Key` header; health
checks are public. Use TLS through a reverse proxy when calling across untrusted
networks. The Docker model port is published on the host and is independently
callable without the worker or Compose.

## Test and project layout

```sh
python -m pip install -r tests/requirements-unit.txt
python -m pytest
```

`tests/unit/` is the default suite. It uses in-memory MongoDB and fake ERP/SMS
clients; socket connections are blocked during tests. It needs no production
credentials, running databases, model weights or Paddle/YOLO packages.
GitHub Actions runs compilation and this suite for pushes and pull requests
on Python 3.11 and 3.12, with read-only repository permissions and no secrets.

`scripts/manual/` contains opt-in checks for actual cameras, SQL Server, MongoDB
and SMS. Run only against your intended environment, for example:

```sh
pipenv run python -m scripts.manual.test_processing_service
```

Manual SMS scripts send real messages when explicitly executed. Obsolete tests
for a removed scheduling module were removed; the old latest-reading check now
tests the existing recent-history API. Runtime images/datasets, local settings,
Python caches and training checkpoints are ignored. Previously committed sample
capture images are removed from the current tree; model inference weights remain.

## Choose ERP or local file delivery

```env
YOURCOMPANY_ERP_ENABLED=false
YOURCOMPANY_EXPORT_DIR=infrastructure/storage/yourcompany_exports
```

`true` (default) sends new readings to YOURCOMPANY ERP using the existing SQL settings.
`false` writes new delivery records locally without constructing an ERP SQL
client or running ERP-backed daily reports. MongoDB is still required for source
configuration, readings and the durable delivery outbox. Restart the worker after
changing this flag; stop the old worker first.

Open `infrastructure/storage/yourcompany_exports/readings-YYYY-MM-DD.html` in a browser.
There is one self-contained report per Tehran observation day (Gregorian filename),
with a per-camera summary and a filterable record table. Counts include total
records, zero-valued deliveries (including zero selected by anomaly fallback)
and unavailable-camera markers (-2); active sources with
no records appear with zero counts. The table contains source code/name/description,
unit, readable value, raw ERP value, exact observation time and local file-write
time, both with the Tehran offset. Celsius raw 217 is displayed as 21.7; -2 stays
an unavailable marker. Only records selected by the existing ERP delivery policy
are exported: unvalidated/review OCR results remain in MongoDB as before.

A local `records.sqlite3` journal commits each event once before acknowledging the
outbox. Keep it with the HTML files: it prevents duplicate counts after retries
or restarts and rebuilds reports after interruptions. Reports refresh at most
once per 60 seconds, when the delivery worker next polls/processes an event, and
flush on graceful shutdown. Reopen/refresh the browser to see updates. The local
journal and generated reports are excluded from Git by the existing storage rule.
Back up the export directory if local records must be retained.

The destination is fixed when a new event is queued. File events are never sent
to ERP after switching back to `true`; remaining file events still drain locally.
Older ERP events (including legacy events without a destination field) pause
while `false` and resume through ERP when `true`. Already-delivered records are
not exported retroactively. No historical minute records or backfill are generated.

In Docker, reports and the journal live in `/app/storage/yourcompany_exports` on the
existing persistent `worker_data` volume. Copy them to the host when needed:

```sh
docker compose cp worker:/app/storage/yourcompany_exports ./yourcompany_exports
```

If the output directory is unwritable or a write fails, the delivery event remains
retryable in the outbox; there is no automatic SQL fallback in file mode. Atomic
HTML replacement preserves the previous complete report if rendering fails.


## Training notebook

The Colab notebook [PP_OCRv6_medium_3datasets.ipynb](notebooks/PP_OCRv6_medium_3datasets.ipynb)
contains the three-dataset training workflow, validation, export and inference
checks. All 45 source cells are included. Saved execution outputs and execution
metadata are cleared, and checkpoint inspection/recovery uses the configured run
rather than a fixed personal run directory. GPU training has not been rerun as
part of packaging this repository. Configure your own Drive folder and datasets
before running the notebook.

Camera examples use synthetic descriptions and reserved example hostnames.
Preprocessing profiles are disabled examples: set an appropriate ROI for your
own camera and enable the profile before collecting real measurements. Never
commit camera credentials, captures or exported reports.

Keep this repository private until code, dataset and model redistribution rights
have been reviewed. Upstream author credits and dataset URLs in the notebook
are retained; replacing a company name does not replace upstream licenses.
