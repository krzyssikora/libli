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

## The caps: counts are generous, bytes are deliberate

The `TRANSFER_MAX_*` limits in `config/settings/base.py` are deployment
guardrails, not hard product limits, and they are sized on two **opposite**
principles. Read this before raising one.

**Count caps** — `TRANSFER_MAX_NODES`, `TRANSFER_MAX_ELEMENTS`,
`TRANSFER_MAX_MEDIA_ENTRIES`, `TRANSFER_MAX_COURSE_JSON_BYTES` — are
memory-bound and reachable only by a user who already holds the import
permission. They are sized so they are **never the binding constraint on a real
course**: the largest real course measures 1,021 nodes / 20,608 elements /
1,191 media / 5.79 MiB of `course.json`, and does not yet cover a full national
curriculum, so the defaults leave roughly 5× headroom over it. *A count cap that
a legitimate course trips is a bug in the cap* — report it rather than working
around it.

`TRANSFER_MAX_COURSE_JSON_BYTES` is what actually bounds import memory: it is a
byte cap on the decoded document, so no count cap can let an unbounded document
through. That is **why** the count caps can be generous, and
`tests/test_transfer_caps_env.py` pins the ratio so a future raise cannot
quietly make a count cap the memory bound again.

**Byte caps** — `TRANSFER_MAX_COMPRESSED_BYTES`,
`TRANSFER_MAX_UNCOMPRESSED_BYTES` — cost real disk on the host: staging, the
upload spill dir and the media volume each need room for one archive. They stay
deliberately modest. Raise them only after sizing the storage **and** the
proxy/worker limits above to match, since the settings-level check is only
reached if the request survives the proxy first.

**A course too large for one archive is not a reason to raise a byte cap.**
Move it with `migrate_course_content`, whose per-part archives are each far
under these limits, and which preserves internal links across parts through its
deferred rewrite pass. Inflating the byte caps to push a multi-GB archive
through one HTTP upload trades a working path for a fragile one.

All six caps are env-overridable (`LIBLI_TRANSFER_MAX_*`).
`TRANSFER_MAX_COURSE_JSON_BYTES` and `TRANSFER_MAX_NODES` were previously fixed,
justified by headroom against a course that has since grown into it — a cap with
no escape hatch is the one an operator cannot route around at 3am.

## Export tells you before the upload, not after

The caps are enforced on **import**. Without help that means an oversize archive
is diagnosed only after it has been built, downloaded and uploaded again.

`build_export` therefore reports every count against the **local** caps before
writing a byte, through its `report["limits"]` out-param:

- **Browser export** shows the pre-flight page (the same one the missing-media
  path uses) naming what the archive needs, what this instance accepts, and the
  environment variable that raises each limit. "Export anyway" still works.
- **`migrate_course_content export`** prints each part's counts inline and flags
  any part over a limit, then completes the bundle regardless.

This reporting is **advisory in both places, and must stay that way**: the caps
that decide belong to the *importing* deployment, which the exporting instance
cannot see. An archive over this instance's limits may be perfectly importable
into one that raised its own. Nothing derived from `report["limits"]` may refuse
an export, and it is deliberately kept out of `build_export`'s `problems` list,
which `migrate_course_content --allow-problems` treats as fatal to the whole
bundle.

One number there is an estimate, and only one: `archive_bytes`. The zip is not
written when the check runs, so the compressed size is unknown; media dominates
it and is already compressed (mp4/png), which makes the uncompressed media total
a close lower bound. It is compared against whichever byte cap binds first —
both apply to the same archive, so the smaller is the real ceiling, and it is
that cap's variable the report names.
