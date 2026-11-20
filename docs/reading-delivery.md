# Reading delivery policy

OCR validation and numeric extraction run first. Empty, malformed and
low-confidence results remain `review`; they are not treated as zero and do not
produce a camera-failure marker.

## Accepted values, zeros and anomalous values

- A numeric zero that passes OCR validation is always accepted (`status="valid"`,
  `is_anomaly=false`). Every consecutive zero is retained and queued for ERP.
- For a nonzero reading, use up to ten preceding accepted **nonzero** readings
  from that camera, ordered by capture time. Exclude rejected anomalies, future
  readings and positive legacy readings explicitly flagged `is_anomaly=true`.
- With at least three reference readings, compare the current value to their
  median. The existing defaults allow a 50% relative change and zero absolute
  tolerance. With fewer than three reference readings, no anomaly is declared.
- Zeros do not erase the running baseline. Returning from a stop to the previous
  operating range is therefore accepted, including after a long stop. This is
  not a blanket exemption for every value after zero: a jump from zero to 819
  against a running baseline around 120 remains anomalous.
- An anomalous nonzero reading is stored as `status="anomaly"` with its observed
  value and reason. ERP receives the latest preceding accepted value, including
  a previous zero. The anomaly does not update the accepted measurement state
  or enter future reference history.
- `erp_value` records the selected ERP payload value;
  `fallback_reading_id` links to the accepted reading used for replacement.
  An anomalous reading without a usable previous reading is retained but not
  queued; no value is invented. This can happen if history is concurrently
  removed. No backfill or historical ERP correction is automatic.

Example:

| Observed | Selected ERP value | Decision |
| ---: | ---: | --- |
| 120 | 120 | accepted, startup |
| 124 | 124 | accepted, startup |
| 119 | 119 | accepted, startup |
| 819 | 119 | anomaly, previous accepted value |
| 0 | 0 | accepted zero |
| 819 | 0 | anomaly, previous accepted zero |
| 121 | 121 | accepted return to running range |

The raw anomaly/image is retained for review. No automatic alarm or repeated
recapture is added. Sustained nonzero shifts outside the configured operating
range continue to use the last accepted value; this rule does not automatically
promote a persistent anomalous value to a new baseline. Existing legacy
`status="anomaly"` records remain unchanged. Legacy `status="valid"` zeros
previously flagged as anomalies may still be used as the latest accepted zero.

## Camera capture failure

After a single CameraWorker capture attempt fails, ProcessingService
handles CameraCaptureError as an expected operational failure: a short WARNING
is logged without traceback. The production entry point explicitly wires the
camera-failure callback to ReadingResultHandler.handle_camera_failure, which
queues -2 for ERP through the existing durable outbox.

The -2 marker does not become an accepted OCR reading, does not replace the
latest accepted state and does not contaminate the anomaly baseline. The next
scheduled capture still runs. Model API failures and unexpected bugs are not
classified as camera disconnections and retain exception diagnostics. Failure
to persist a -2 event is also an unexpected error and is not silently hidden.
Diagnostic ProcessingService callers without a failure callback only log the
capture failure; the production main.py always supplies the callback.

## Time and delivery

An accepted reading or replacement uses the **current sample's capture time**
in `captured_at` and outbox `scheduled_at`, not the old replacement reading's
time. A capture-failure marker uses the failure observation time. ERP date/time
is derived from those UTC timestamps in Asia/Tehran and is preserved on retry.
The existing SQL schema stores time to minute precision; retries can change
insertion order. Outbox retries retain the selected replacement value or -2.
Missing source metadata and database failures can still prevent queueing.

## Tests

```sh
python -m pip install -r tests/requirements-unit.txt
python -m pytest
```

Tests use in-memory MongoDB, fake camera streams, fake models and fake ERP.
They cover both OCR formats, the 120/124/119/819 example, repeated anomalies,
zero-to-running recovery after long stops, zero as a fallback, chronological
reference selection, legacy anomaly filtering, ERP retry, single-attempt capture, recovery after a failure and production callback wiring. No production
camera, database or SMS service is contacted.

## Capture timing and rollback of minute backfill

Capture uses one open/read attempt with FFmpeg constructor timeouts of 5 seconds
for open and 5 seconds for read. Each capture opens a fresh stream and releases
it immediately after reading one frame, avoiding buffered frames from the
previous minute. No retry sleep or capture subprocess is used.

Ampere sources use 60-second intervals, including legacy 300/3600-second source
settings; other units retain their configured interval. Captures keep their
actual UTC observation time. ERP date/time is derived from that observation in
Asia/Tehran, never from midnight, a generated slot, or a scheduling deadline.

The scheduler no longer advances a camera's deadline when its previous job
finishes. If the next capture is already due, it runs immediately once that
camera's job finishes and a worker is available. Only submission advances the
next deadline to the next point in the fixed cadence. Long overruns do not cause
an artificial replay burst: one current capture is submitted, then scheduling
resumes on the next deadline. Each camera has at most one job in flight.

Successful processing logs the observation timestamp and capture, inference and
total durations. A job taking 60 seconds or more logs a warning. A configured
one-minute cadence cannot ensure a new real measurement every minute if the
camera/model/network takes longer than that; overdue work is visible in logs.

The minute-slot reconciler, backfill, checkpoint collection, generated -2 minute
records and special SQL insertion policy have been removed. On worker startup,
only unsent events created by the removed policy (`event_id` starting `minute:`
and `erp_data.MinuteSlot=true`) are marked `cancelled` before delivery starts.
Existing ordinary delivery events remain eligible. Stop old workers before
starting the updated version. Already-sent ERP rows remain in the ERP; this
rollback does not delete production data. The unused `minute_schedules` data is
not consulted.
