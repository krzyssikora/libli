# Deploying course export/import

Operational notes for the course/subtree export-import feature (zip transfer
between courses or instances). See `config/settings/base.py` for the actual
settings referenced below.

## Proxy body-size and timeout limits must accommodate the transfer caps

The import endpoints (`courses:manage_course_import`,
`courses:manage_import_content`) accept an uploaded `.zip` archive up to
`TRANSFER_MAX_COMPRESSED_BYTES` (1 GiB by default). If libli sits behind a
reverse proxy (nginx, Caddy, an ALB, etc.), the proxy's own request body-size
limit and worker/read timeout must be raised to match, or large-but-legal
uploads will be rejected or dropped by the proxy **before Django ever sees
them** — the application-level check in `views_transfer._handle_upload` never
gets a chance to run.

- **nginx:** `client_max_body_size` (defaults to 1 MiB) must be at least
  `TRANSFER_MAX_COMPRESSED_BYTES`, and `proxy_read_timeout` /
  `proxy_send_timeout` need enough headroom for a slow client to finish
  uploading a large archive (and for the server to spool + validate it before
  responding — see `_stream_archive`, which fully builds the zip in a spooled
  temp file before streaming a response).
- **Gunicorn/uWSGI worker timeout:** the same applies to the app server's own
  request timeout, independent of the proxy.
- A course export (`courses:manage_course_export`,
  `courses:manage_node_export`) streams a `FileResponse` back to the browser;
  the same read/write timeouts apply on the way out for large courses with a
  lot of media.

## `TRANSFER_STAGING_DIR` must be shared storage and must never be web-served

Uploaded archives are staged to disk (`courses/transfer/staging.py`) between
the upload/preview step and the confirm step, keyed to the user's session.
Two deployment constraints follow directly from that:

- **Multi-host / multi-worker deployments:** if the app runs behind a load
  balancer across more than one host (or more than one container), the
  directory pointed to by `TRANSFER_STAGING_DIR` must be **shared storage**
  (e.g. a shared volume/NFS mount) reachable from every host/worker — the
  preview and the confirm requests for the same import can land on different
  workers, and the staged file must be visible to both. A local-disk-only
  staging dir works for a single-process/single-host deployment but will
  intermittently 422 ("expired or was not found") in a scaled-out one.
- **Never web-serve it.** `TRANSFER_STAGING_DIR` is deliberately kept outside
  `MEDIA_ROOT` (see the comment in `config/settings/base.py`) because staged
  archives are raw, not-yet-validated uploads — they must not be reachable via
  any static/media URL or web server alias. Don't add the staging directory
  to your web server's static file config, S3 bucket policy, or CDN origin.
- Staged files older than `TRANSFER_STAGING_MAX_AGE_HOURS` (default 6h) are
  cleaned up; make sure the process/user running the app has write+delete
  permission on the staging directory.

## Raising the caps for video-heavy courses

`TRANSFER_MAX_COMPRESSED_BYTES`, `TRANSFER_MAX_UNCOMPRESSED_BYTES`, and the
related `TRANSFER_MAX_*` limits in `config/settings/base.py` are deployment
guardrails, not hard product limits. If an instance hosts courses with a lot
of embedded video/media and needs to support larger export/import archives,
raise these settings — and raise the proxy/worker limits above **to match**,
since the settings-level check is only reached if the request survives the
proxy first.
