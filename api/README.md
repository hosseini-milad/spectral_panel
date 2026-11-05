# Operations REST API

All new HTTP routing, validation, queueing, worker code and tests live in this root `api/` app. Existing scientific management commands/services are called unchanged. The old unused nested API code was moved to `api/legacy_ingestion`; `ingestion.urls` retains its import adapter, and the new public routes use the queued command API.

## Start locally

MongoDB must be running with the project's existing `siem_db` configuration. Install the updated `requirements.txt`. No SQL migration is needed for this API; jobs and the worker lock are in MongoDB.

In one terminal:

```console
python -u manage.py run_api_worker
```

In another terminal:

```console
python -u manage.py runserver 127.0.0.1:8000
```

Swagger: http://127.0.0.1:8000/swagger/

OpenAPI: http://127.0.0.1:8000/api/schema/

Swagger and action routes intentionally require no authentication in this initial version. Swagger assets are installed locally through the sidecar package, including with `DEBUG=False`; no CDN, login, `collectstatic` or Redis/Celery is required. To allow a different hostname, set `DJANGO_ALLOWED_HOSTS` as a comma-separated environment value.

## Actions and jobs

`GET /api/v1/actions/` lists every explicit action route, the underlying CLI command and its current options/defaults. `POST /api/v1/actions/<category>/<action>/` accepts JSON keys matching CLI destination names (`source_file`, `chunk_index`, `reference_bundle`, etc.). Scalar `--days` stays a string where the original command expects comma-separated input; `nargs` options use JSON arrays. Swagger request schemas derive from the actual command parsers, including defaults and choices. Unknown fields and invalid argument groups fail before queueing.

Submission returns HTTP **202**, a job ID and status/log URLs. It means queued, not finished. `run_api_worker` executes the original command using Django `call_command`, not a shell; it captures both `print` output and Django stdout/stderr. Paths containing spaces remain literal arguments. Original command errors become `failed` jobs with logs. Type/parser validation happens at submission; semantic/data validation still belongs to the original command and may fail during execution.

Send an optional `Idempotency-Key` header (1–128 characters) when retrying a submission. Same key and same normalized request returns the existing job; a changed request with that key gets HTTP 409. This is especially useful for explicit `force`/`apply` requests. These options retain their original destructive semantics and are false by default.

- `GET /api/v1/jobs/`: paginated/filterable history and worker heartbeat.
- `GET /api/v1/jobs/<id>/`: queued/running/succeeded/failed/cancelled/interrupted.
- `GET /api/v1/jobs/<id>/logs/?offset=0&limit=65536`: incremental UTF-8 logs with a byte `next_offset`.
- `POST /api/v1/jobs/<id>/cancel/`: cancels queued jobs only; running jobs return 409.
- `GET /api/v1/days/` and `/days/<day>/chunks/`: read-only day/chunk state.
- `GET /api/v1/artifacts/?path=<relative-document-directory>`: bounded directory listing.
- `GET /api/v1/artifacts/file/?path=<relative-document-file>`: download; PNG/JPEG/WebP can be displayed inline.
- `GET /api/v1/health/`: MongoDB and worker heartbeat status.

Reports remain in their original `document/...` locations printed by each command. API job logs and completion records are in `document/api/jobs/<job-id>/`. Artifact access is restricted to resolved paths inside `document/`; it cannot download arbitrary files outside it.

## Worker behavior

One global Mongo worker lock serializes API commands, including cross-day operations and resets. This lock coordinates **API workers only**: do not run overlapping CLI write operations against the same data concurrently. Existing CLI commands are not modified to acquire the API lock.

Closing the browser or HTTP server does not cancel a queued/running worker job. Stop the worker with Ctrl+C when necessary; an interrupted command can leave partial scientific output, exactly as with the CLI. There is no automatic retry, especially for force resets. On restart, dead same-host worker locks are checked against PID/process creation time; orphaned running jobs become interrupted or recover their already-written completion record. A live or unverifiable lock is never automatically stolen. Stop the worker before updating code or dependencies.

The API does not introduce a new model, normalization policy, calibration rule, alert decision or research ablation. Only the allowlisted operations in `registry.py` are executable.
