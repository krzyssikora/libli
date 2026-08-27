# Demo deployment: containerised install

## Purpose

libli has never been deployed. There is no production database, no Dockerfile, no
provisioning, no WSGI server in `pyproject.toml`, and nothing that serves `MEDIA_ROOT`
when `DEBUG=False`. The roadmap lists "Non-technical deployment/install" as an unresolved
cross-cutting concern (`docs/roadmap.md:175`), and the accumulated "at first deploy, do
X" notes live only in memory files.

This design builds the first deployment: a containerised install (`app`, `db`, `caddy`)
that stands up a working instance on a single Contabo VPS (Ubuntu), plus fixes for the two defects
a real deployment exposes.

The immediate output is a demo box carrying the **matematyka** course (1,010 nodes,
1,194 media assets, 3.8 GB) and a second smaller course. The durable output is an install
path a school could follow. Fake students and analytics data are a separate piece of work
(see Non-goals).

**The demo content is not part of the installer.** A school installing libli gets an
empty instance; loading matematyka is a separate, optional step. Nothing in the image or
the compose file carries course content.

### Two problems this necessarily fixes

**1. `/media/` is not served in production.** `config/urls.py:37` gates the media route
on `settings.DEBUG`, and `config/settings/base.py:162-166` says so explicitly:
"production must serve MEDIA via the web server". With `DEBUG=False` every image and
every video 404s. Worse, `core/media_serve.py::serve_media` — which adds the HTTP Range
handling Django lacks entirely, and without which a browser will not let a student seek
inside a `<video>` — lives inside that same DEBUG-only branch.

**2. Invitation and password-reset links are dead on a fresh install.**
`accounts/invitations.py:build_accept_url` builds links from
`django.contrib.sites.Site`, deliberately, so they cannot be host-spoofed. Django ships
Site #1 as `example.com`. Nothing in the first-run wizard touches `Site` — there is no
reference to it in `institution/views_setup.py`, `institution/forms.py`, or
`institution/models.py` — so `docs/local-development.md`'s statement that this "should be
captured by the first-run setup wizard (Phase 5e)" describes an intention, not a
behaviour. No test catches it and the admin sees no warning.

### Non-goals

Explicitly out of scope, not to be added opportunistically during implementation:

- **Publishing an image to a registry.** The droplet builds from source
  (`docker compose up --build`). Publishing to GHCR is a later, additive change.
- **Multi-host or multi-replica deployment.** Exactly one `app` container. This is what
  makes `migrate` in the entrypoint safe and lets `TRANSFER_STAGING_DIR` be a local
  volume rather than shared storage (`docs/deployment-course-transfer.md`).
- **A CLI course importer.** The web UI import is the chosen path; see "Loading
  matematyka". A management command wrapping `importer.import_course()` is the documented
  escape hatch if the upload proves unworkable, not a deliverable.
- **Backups.** No `pg_dump` cron, no snapshot policy. A demo box.
- **Raising the shipped transfer-cap defaults.** They become env-overridable; their
  values do not change.
- **Object storage / CDN for media.** Local volume served by Caddy.
- **`ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` configurable at runtime.** They are settings;
  see component 4 for why the wizard cannot own them.
- **Async email or a task queue.** Unchanged; notification email stays synchronous.
- **The demo-activity seeder (`seed_demo_activity`).** Split out after three plan-review
  rounds. Every other part of this design went quiet after round 1; the seeder produced
  new CRITICAL defects in all three, each time because generating *semantically valid*
  quiz data is coupled to domain rules that only surface when run against real content —
  the score must be derived from the answer, `_quiz_review_maps` derives `total_review`
  from a unit's REVIEW **elements** so a skipped question drops the whole submission, and
  quiz attempts cannot be gated on lesson progress. It gets its own spec written **after**
  matematyka is imported, when the question types in play can be audited rather than
  assumed. Consequence: the analytics matrix on matematyka is empty until that lands.

## Sizing

Measured against the local instance, not estimated:

| | value |
|---|---|
| Postgres database | 25 MB |
| `media/` total | 3.8 GB |
| — 241 `.mp4` | 3.7 GB (largest single file 71 MB) |
| — 6,124 `.png` + 12 `.jpg` + 18 `.gif` | ~57 MB |
| matematyka | 1,010 nodes, 1,194 `MediaAsset` rows |

The database is irrelevant to sizing. The videos are the entire footprint.

**RAM is not the constraint.** `staging.stage()` writes via `uploaded_file.chunks()`
(`courses/transfer/staging.py`), and the exporter spools to disk past 32 MB
(`courses/views_transfer.py:59`). Neither end holds the archive in memory.

**Disk is the constraint**, because a UI import lands the archive on disk three times
concurrently:

| stage | cost |
|---|---|
| Django `TemporaryUploadedFile` in `/tmp` (default in-memory spool is 2.5 MB) | 3.8 GB |
| `staging.stage()` copy in `transfer_staging/`, retained up to 6 h | 3.8 GB |
| media extracted into `MEDIA_ROOT` | 3.8 GB |
| OS + image + venv + Postgres | ~5 GB |

**Peak ≈ 17 GB, steady ≈ 9 GB.** A 25 GB droplet works right up until the import and
then fails on disk. **50 GB is the floor**. The chosen host is Contabo, whose tiers all clear it comfortably; the equivalent DigitalOcean tier for reference is ~$12/mo (2 GB RAM /
1 vCPU / 50 GB) or any Contabo tier, all of which exceed it comfortably.

## Architecture

```
                    :443  Caddy  (auto-TLS, streams request bodies)
                      ├── /media/*  → file_server from the media volume
                      └── /*        → reverse_proxy app:8000
                                        │
                                     gunicorn ─ Django ─ /static/ via whitenoise
                                        │
                                     db (postgres:16)
```

Ten artifacts, of which nine remain in scope (8 is split out — see Non-goals). Three of
those nine are application changes (4, 5, 7); the rest are new infrastructure files.

### 1. `Dockerfile`

`python:3.13-slim` (matching `requires-python = ">=3.13"`), uv for dependency install to
match CI (`.github/workflows/ci.yml` uses `astral-sh/setup-uv@v6`), then `collectstatic`
as a **build step**.

`collectstatic` must run at build time, not at boot: `STORAGES["staticfiles"]` is
`whitenoise.storage.CompressedManifestStaticFilesStorage`
(`config/settings/base.py:156-161`), which is manifest-based — the hashed manifest has to
exist in the image or every `{% static %}` reference raises at runtime.

`locale/*/LC_MESSAGES/*.mo` are committed, so no `compilemessages` step is required.

### 2. `docker-compose.prod.yml`

Named `.prod.` so a bare `docker compose` in the repo root cannot pick it up alongside
the existing `docker-compose.test.yml`.

Three services. Four persistent paths, three of them volumes:

| Path (`BASE_DIR / …`) | Volume | Web-served? |
|---|---|---|
| `media/` | yes, ~5 GB | **yes**, by Caddy |
| `transfer_staging/` | yes, ~4 GB | **never** — raw unvalidated uploads |
| `support_screenshots/` | yes, small | **never** — may carry other students' grades |
| `staticfiles/` | no — baked into the image | via whitenoise |

`TRANSFER_STAGING_DIR` and `SUPPORT_SCREENSHOT_DIR` are deliberately outside `MEDIA_ROOT`
(`config/settings/base.py:183-188`) and must not appear in any Caddy route. The media
volume is the only one Caddy can see.

### 3. `Caddyfile`

Two behaviours that are load-bearing rather than incidental:

- **`file_server` for `/media/*`.** Caddy implements HTTP Range natively, so video
  seeking works without `core/media_serve.py`, and 3.7 GB of mp4 traffic never touches a
  gunicorn worker.
- **Caddy, not nginx.** nginx buffers the entire request body to disk before proxying
  (`proxy_request_buffering on` by default), which would add a **fourth** 3.8 GB copy to
  the peak-disk table above. Caddy streams request bodies.

Static is **not** routed here. Whitenoise keeps `/static/` inside the app so the hashed
manifest stays authoritative.

`request_body max_size` is set explicitly to match the configured upload cap.

### 4. Application change: `Site` domain (`DJANGO_SITE_DOMAIN` + wizard field)

Two halves, because the two audiences differ.

**Entrypoint half.** A `DJANGO_SITE_DOMAIN` env var applied after `migrate`, so an
install is never *born* broken. This is the same hostname the operator already supplies
for `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` — nothing new to know.

**Wizard half.** The Identity step of the first-run wizard (`institution/views_setup.py`,
`STEPS`) gains a public-hostname field: initial value read from
`Site.objects.get_current().domain`, validated as a host with optional `:port` and no
scheme or path, written back on save. This is the non-technical surface; a school admin
must not need a shell to fix their own email links.

**The field fixes email links only, and its help text must say so.** `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS` are settings and cannot change at runtime. This is not a gap: by
definition the admin reached the wizard over that hostname, so those values were already
correct. Implying the field configures the domain would be worse than omitting it.

Note the form is not a plain `ModelForm` on `Institution` — `Site` is a different model
in a different app, so the field is declared explicitly and saved alongside the existing
`BrandingForm` instance.

### 5. Application change: transfer caps become env-overridable

Three constants in `config/settings/base.py` become `env.int(...)` reads **keeping their
current values**:

| setting | current default |
|---|---|
| `TRANSFER_MAX_COMPRESSED_BYTES` | 1 GiB |
| `TRANSFER_MAX_UNCOMPRESSED_BYTES` | 1.5 GiB |
| `TRANSFER_MAX_MEDIA_ENTRIES` | 1000 |

The defaults are deliberate guardrails — `config/settings/base.py:172-174` calls them
exactly that — and a school installing libli must not silently inherit a 4 GB upload
ceiling. Only the demo's own `.env` raises them.

matematyka exceeds all three: 1,194 media entries against a cap of 1,000, and ~3.8 GB
against caps of 1 GiB compressed and 1.5 GiB uncompressed (mp4 does not compress). The
caps are enforced at `courses/transfer/importer.py:244,258,275,304` and
`courses/transfer/schema.py:213`, with a pre-stage check at
`courses/views_transfer.py:118`.

`DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000` (`config/settings/base.py:239`) is a field count,
not a body size, and needs no proxy counterpart.

### 6. `docker-entrypoint.sh`

```
wait for db (bounded Django connection.ensure_connection() probe; fail loud, never
  start gunicorn on failure. NOT pg_isready: it is not in the app image, and the Django
  probe additionally proves DATABASE_URL and the settings module resolve)
  → migrate
  → setup_roles
  → set Site domain from DJANGO_SITE_DOMAIN
  → init_platform            (only when INIT_ADMIN_* are all set)
  → exec gunicorn --timeout 1800 --workers 2 --threads 4
```

**`setup_roles` runs unconditionally**, even though `init_platform` also calls it
(`accounts/management/commands/init_platform.py`, step 1). `init_platform` is conditional;
role seeding must not be. Permissions live as constants in `institution/roles.py` but are
only *assigned* by `seed_roles()`, so omitting this grants nothing on a migrated database
— and **no test can catch the omission**, because `tests/factories.py` calls
`seed_roles()` itself and the suite passes either way.

`init_platform` is skipped unless all three `INIT_ADMIN_*` vars are present: it fails
fast with "Missing required credential(s)" when non-interactive and unset, which must not
abort the boot of an already-bootstrapped instance. It is idempotent when they are set.

**Gunicorn's flags are load-bearing.** A 3.8 GB upload occupies one worker for roughly 25
minutes of sustained transfer; the default 30-second timeout would kill it mid-stage.
Threaded workers keep the site responsive while one is consumed by the import.

`migrate` in the entrypoint is safe **only** because there is exactly one app container.
The runbook states this rather than generalising it.

### 7. `pyproject.toml`: add `gunicorn`

No WSGI server is currently a dependency. Production group, not dev.

### 8. `seed_demo_activity` management command — SPLIT OUT, see Non-goals

This section described a seeder generating ~20 fake students and enough quiz activity to
populate the analytics matrix. **It was removed from this deployment's scope after three
plan-review rounds** and will get its own spec and plan, to be written after matematyka
is imported. See the Non-goals entry above for why, and
`docs/superpowers/plans/2026-08-26-demo-deployment.md` § "Deliberately out of scope" for
the detail. The restructured draft survives at commit `8dae86e3`.


### 9. `.env.production.example`

Annotated in the style of the existing `.env.example`, covering the production block that
file already documents plus `DJANGO_SITE_DOMAIN` and the three cap overrides.

### 10. `docs/deployment.md`

The runbook. Ordered, with the verification checks below inline.

## Loading matematyka

Via the **web UI export/import**, deliberately: the UI and CLI paths share `_run_import`,
so what is unique to the UI is the upload and staging half
(`courses/views_transfer.py::_handle_upload`, `courses/transfer/staging.py`) — precisely
the half that is untested at this scale and precisely what a school would hit.

The instance must keep `signup_policy = "invite"` (the `init_platform` default) so a
public URL cannot accrue real signups.

`seed_demo_course` supplies the second, smaller course. It is already written and
idempotent: one runbook line, not a build item.

## Verification

### Falsifiable in pytest

| Test | Mutant that must turn it red |
|---|---|
| caps read from env | restore the hardcoded constant → red |
| wizard writes `Site` | drop the `Site.save()` → red |
| wizard field rejects a scheme/path | accept `https://x/y` → red |

Each test must be shown RED against its mutant before the implementation is accepted; a
test that cannot fail is not evidence.

### Not testable in pytest, and not pretended otherwise

The container stack is verified by executing a real deployment. The runbook carries these
checks:

```bash
curl -s -o /dev/null -D - -r 0-100 https://<host>/media/<file>.mp4
# MUST be 206 Partial Content with Accept-Ranges. A GET with the body discarded,
# NOT a HEAD: Range-on-HEAD is a file-server implementation detail, whereas a
# <video> element issues a GET.
# A 200 means seeking is silently broken for every student.

curl -sI https://<host>/static/<hashed>.css   # 200 — whitenoise manifest intact
curl -sI https://<host>/                      # 200 over TLS, HTTP redirects to HTTPS
df -h                                          # before import: ≥17 GB free
```

The Range check is the one that must not be skipped. A 200 there is exactly the failure
mode where the page looks correct and only a student trying to replay a passage
discovers it.

After a successful import, the staged 3.8 GB archive is deleted rather than left to age
out over `TRANSFER_STAGING_MAX_AGE_HOURS` (6 h).

## Accepted risks

- **The 3.8 GB upload may fail** on a dropped connection, with no resume. If it fails
  repeatedly, the escape hatch is a small management command wrapping
  `importer.import_course()` — added then, not now.
- **Peak disk ~17 GB** during import, against a 50 GB floor. The runbook checks `df -h`
  first.
- **No backups**, by choice, for a demo box.
- **Notification email remains synchronous.** Unchanged by this work, but a first
  deployment is where the latency becomes observable.

## Follow-up

After this deploys successfully, the memory file `no-deployment-no-prod-db` becomes false
and must be rewritten, not left asserting there is no production database. The deferred
items in `first-deployment-checklist` (migration 0060 + `FORMAT_VERSION 13`, the
internal-link cutover runbook) become live at that point.
