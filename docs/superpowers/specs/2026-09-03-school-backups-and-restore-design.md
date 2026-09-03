# School backups and restore — design

Sub-project **B1** of the school hosting model. Decided 2026-09-03.

## Why this exists

Backups are a stated requirement, not a follow-up: a school must not go live unbacked.
`docs/deployment.md` currently lists "No backups. No `pg_dump` cron, no snapshot policy"
under *Known constraints*, while `docs/public/privacy.md:217` already tells users that "the
server and its backups" are kept safe. The public promise is live; the mechanism is not.

The design is driven by one observation: **the restore path is also the resize path, the
provider-move path, and the eventual hand-a-school-its-own-box path.** Build it once and
four problems close. That is what rules out a provider snapshot as the load-bearing half —
a Hetzner snapshot restores only onto Hetzner, and three of the four paths need to leave.

## Goals

1. A school box can be recreated from scratch on any provider, from the backup artifact
   plus a published image, with nothing pulled from the original machine.
2. Nightly, unattended, with a failure that is *noticed*.
3. The artifact is useless to whoever steals it.
4. The list of what gets backed up cannot silently rot when a volume is added.

## Non-goals

- Point-in-time recovery. The default tier is nightly; the layout reserves a `wal/`
  directory so a school needing a tighter RPO can have WAL archiving added later without
  a redesign or a second destination. Nothing writes to it in this work.
- Per-school storage *quotas*. This work measures storage; it does not enforce it.
- Multi-host deploy targeting, release-tag promotion, canary. That is B2.

## Decisions taken

| Decision | Choice | Rationale |
|---|---|---|
| Destination | One Hetzner Storage Box (BX11, ~1 TB), one sub-account per school | ~EUR 3.80/mo for all schools; EU region; plain SSH/rsync, so restore works from anywhere and is not tied to an S3 SDK |
| History | Storage Box snapshots (daily, 10 retained) | Taken by the *main* account. A compromised school box holds a sub-account credential that cannot destroy them. |
| Encryption | `age`, public-key mode | The box holds only the public key: it writes backups it cannot read. |
| Encrypted set | DB dump, `.env.production`, `support_screenshots` | These carry pupil data and every secret. |
| Plain set | `media/`, `caddy/` | Teacher-authored course content and TLS material; the bulk of the bytes, and it stays verifiable without the key. |
| App version | Pull a published image; stop building on the box | Restore must be able to bring up the version the dump came from. |

### Key custody

One `age` keypair for all schools. The **public** key is baked into each box's
configuration. The **private** key lives in the password manager plus one offline copy,
and is never on any server.

This is a real single point of failure and it is accepted deliberately: losing the private
key loses every school's backups. It is the price of the box being unable to read its own
history. Per-school keypairs were rejected — they multiply the custody problem without
changing its shape, since one compromised laptop loses all of them anyway.

## The artifact

```
schools/<slug>/
  db/<ts>.dump.age             pg_dump -Fc, encrypted. Dated, pruned.
  env/<ts>.env.age             .env.production, encrypted. Dated, pruned.
  screenshots/**.age           per-file mirror, encrypted, append-only
  media/**                     per-file mirror, plain, append-only
  caddy/                       ACME account key + issued certs
  manifest/<ts>.json           what this backup is
  wal/                         reserved. Empty in this work.
```

`<ts>` is `YYYY-MM-DDTHHMM` in UTC.

### Ordering is load-bearing: dump first, media second

`pg_dump` takes a consistent snapshot at T0; the media rsync runs at T1 > T0.

- **Dump then media** — a file created between T0 and T1 lands in the mirror without a row
  referencing it. A harmless orphan.
- **Media then dump** — a file created in between lands in the *dump* with no bytes in the
  mirror. A row pointing at nothing, which is a broken restore.

The safe direction is the one that risks orphans, never dangling references.

### The mirrors are append-only

`rsync` runs **without `--delete`**. Two reasons:

1. Element deletion in libli is a hard delete with no orphan table and no audit trail. An
   append-only mirror means the file survives even when the row does not, which makes a
   mis-click recoverable for the first time.
2. A wiped `media` volume cannot propagate into the backup.

Cost is unbounded growth of deleted files on the Storage Box. Accepted: media deletion is
rare, and the space is far cheaper than the alternative.

### Media paths must be preserved exactly

`MediaAsset.file` is `upload_to="courses/media/"` with the **original filename**, plus
Django's random 7-character suffix on collision (`courses/models.py:795`). Names are *not*
content-addressed — `content_hash` is a database column only and paths cannot be rebuilt
from it. A restore that renames or re-lays-out media breaks every `FileField` in the
database. The mirror is therefore path-faithful and the rsync preserves relative paths.

Image derivatives (`thumb`, `web`, `courses/models.py:808-813`) *are* regenerable via
`backfill_media_derivatives`, but are backed up anyway: excluding them saves bytes on the
cheapest resource in the system and costs CPU and wall-clock on the restore, which is the
moment that matters.

### The manifest

Written every night, read by every restore:

```json
{
  "schema": 1,
  "taken_at": "2026-09-03T03:30:00Z",
  "school": "<slug>",
  "image": "ghcr.io/krzyssikora/libli:v1.4.0",
  "git_sha": "d45d67d1",
  "format_version": 13,
  "postgres_version": "16.4",
  "django_migration_head": "institution.0011_alter_institution_signup_policy",
  "row_counts": {"auth_user": 412, "courses_contentnode": 8931, "...": 0},
  "media": {"files": 2914, "bytes": 9214773248},
  "screenshots": {"files": 37, "bytes": 5412233}
}
```

Three of these fields do real work:

- `image` / `django_migration_head` — a dump restored onto a **newer** app migrates
  forward and is fine; onto an **older** one it is broken. `restore.sh` refuses when the
  image it is about to start is behind the dump, rather than discovering it during
  `migrate`.
- `row_counts` and `media.files` — the restore compares against them. Without this, a
  truncated dump is discovered at the moment it is needed.
- `media.bytes` — written now, read by nobody in this work. It is the per-school storage
  figure the pricing model needs, and `backup.sh` already walks the tree, so it is free
  here and expensive anywhere else. See *Deferred* below.

## `backup.sh`

Lives at the repo root beside `deploy.sh`, for the reason that file's own header gives:
it goes through the normal PR/CI/review path, and `deploy.sh`'s `git reset --hard` keeps
the host copy current for free.

Reuses `deploy.sh`'s `env_value()` helper shape to read `.env.production`.

```
1. flock, or exit 0 quietly       (never overlap a previous run)
2. pg_dump -Fc | age -r $PUBKEY   -> db/<ts>.dump.age
3. age -r $PUBKEY .env.production -> env/<ts>.env.age
4. rsync media/       -> media/       (no --delete)
5. rsync screenshots/ -> screenshots/ (per-file age)
6. rsync caddy data   -> caddy/
7. write manifest/<ts>.json
8. prune db/ and env/ beyond retention
9. GET the dead-man's-switch URL on success only
```

`pg_dump` of the single database, not `pg_dumpall`: the `libli` role is created by the
postgres image from `POSTGRES_USER`/`POSTGRES_PASSWORD` on first init, not by the dump.
This also defuses the documented `POSTGRES_PASSWORD` footgun — a restore initialises a
*fresh* `pgdata` using the password from the *restored* `.env.production`, so the two
agree by construction.

**Retention:** 30 daily plus 12 monthly for `db/` and `env/`. Mirrors are append-only.
Storage Box snapshots supply the layer a compromised sub-account cannot touch.

**Failure must be loud.** A backup that silently stops is the classic failure of this
whole category. Cron's `MAILTO` is not available — there is no MTA on the box and Hetzner
blocks outbound 25 by default. So step 9 is an outbound HTTPS ping to a dead-man's-switch
(healthchecks.io free tier or equivalent), which alerts on *absence*. This detects a
backup that stopped running, which `set -e` alone cannot.

## `restore.sh`

The same script serves all four paths. It runs on a box provisioned through sections 1–2
of the runbook (SSH hardened, Docker installed, DNS pointed).

```
1. fetch manifest/<ts>.json; print it; require confirmation
2. fetch + decrypt env/<ts>.env.age -> .env.production, chmod 600
3. refuse if the image about to start is older than the manifest's
4. docker compose up -d db          <- db ALONE. Not the app.
5. pg_restore --clean --if-exists into the fresh database
6. rsync media/, screenshots/ (decrypting), caddy/ into the named volumes
7. docker compose up -d --wait      <- entrypoint migrates forward
8. verify: row counts and media file count against the manifest
9. print the runbook's section 4 checks
```

Step 4 is the one that is easy to get wrong and is why this is a script rather than a
runbook section. The container entrypoint runs `migrate` on every boot
(`docker-entrypoint.sh`). Bringing the full stack up against an empty database creates the
schema, and the dump then collides with it. The database must be loaded **before** the app
container ever starts.

### How the four paths use it

- **Restore** — the sequence above, same hostname.
- **Resize** — the sequence on a larger box, then repoint DNS.
- **Provider move** — identical to resize. Nothing in the artifact is Hetzner-specific.
- **Handover** — the sequence, run by the school's IT, plus handing over the `age` private
  key and the Storage Box sub-account. Documentation, not a fifth mechanism.

The course transfer format (`courses/transfer/`, `FORMAT_VERSION = 13`) is explicitly
**not** used for any of these. Its archive carries `manifest.json`, `course.json` and media
bytes only — no users, enrollments, progress, grades, submissions, Institution config or
SSO. It is a content mover, not a site mover.

## The image switch

`docker-compose.prod.yml` moves `build: .` to `image: ghcr.io/krzyssikora/libli:<tag>`, and
`deploy.sh` drops `--build` for a `pull`.

Scope here is minimal — build and push on merge to master, tagged `:master` and `:<sha>`.
Release-tag promotion, canary and multi-host targeting are B2.

It is in B1 because restore depends on it. Without it, "bring up the version this dump came
from" is a source rebuild: the RAM spike that makes 4 GB a real floor, on a box being
brought back under pressure, and the manifest can only record a git sha rather than a
pullable tag.

**This changes an existing test.** `tests/test_deploy_wiring.py::test_deploy_script_waits_for_health`
asserts the `compose up` line contains both `--wait` and `--build`. It becomes `--wait`
plus the pull step.

## Testing

The scripts run on a host, not in pytest, so most of the suite here is textual wiring
guards in the style of `tests/test_deploy_wiring.py` — which is the established pattern
for exactly this problem and the file the new one should sit beside.

`tests/test_backup_wiring.py`:

1. **The volume classification guard.** Parse the `volumes:` block of
   `docker-compose.prod.yml`. Every volume must appear either in `backup.sh`'s backed-up
   set or in an explicit not-backed-up list *with a stated reason*. Adding a volume fails
   the suite until it is classified.
   *Mutant:* add a volume to the compose file; the test must go RED. This teaches the
   detector rather than trimming a baseline — the list is derived from the compose file,
   never hand-maintained alongside it.
2. **Dump precedes media.** Assert the `pg_dump` line appears before the media `rsync` line
   in `backup.sh`. *Mutant:* swap them; RED.
3. **No `--delete` on the media or screenshots rsync.** *Mutant:* add it; RED.
4. **`restore.sh` brings up `db` alone before loading.** Assert a `up -d db` line precedes
   the `pg_restore` line, and that no unqualified `up -d` appears before it.
   *Mutant:* replace `up -d db` with `up -d`; RED.
5. **`backup.sh` and `restore.sh` parse** (`bash -n`), matching assertion 11 of the
   existing deploy guard.
6. **Paths agree** across `backup.sh`, `restore.sh`, the cron line in the runbook and
   `docker-compose.prod.yml`, in the style of the existing
   `test_deploy_yml_invokes_the_script_at_the_path_deploy_sh_assumes`.

**Nothing in the suite currently reads `docker-compose.prod.yml`.** Guard 1 would be the
first, so the parsing helper is new and should be written for that one job.

### The rehearsal is part of the deliverable

B1 is not complete when the scripts exist. It is complete when a backup taken by
`backup.sh` has been restored by `restore.sh` onto a *fresh* box and verified against its
manifest. A backup that has never been restored is not a backup, and the textual guards
above deliberately do not claim to prove the thing works — they prove it has not drifted.

Rehearse quarterly thereafter.

## Documentation

- New `docs/backup-and-restore.md` — the artifact, the two scripts, key custody, the
  restore sequence, and the four paths. Separate from `docs/deployment.md`, which is
  already long; cross-linked from its section 8.
- `docs/deployment.md` — delete the "No backups" bullet from *Known constraints*; add the
  cron entry beside the existing `purge_notifications` one (same one-physical-line and
  `exec -T` traps); note the `age` package in section 1's install step.
- `docs/public/privacy.md` — state the backup retention period, which RODO requires and
  which the page currently gestures at without specifics.

## Risks

| Risk | Handling |
|---|---|
| Private `age` key lost | Accepted, deliberately. Password manager plus one offline copy. |
| Backup silently stops | Dead-man's-switch alerting on absence (step 9). |
| Restore never rehearsed | Rehearsal is a completion criterion, then quarterly. |
| Backup overlaps a deploy | `flock`; a collided run exits and the switch alerts if it recurs. |
| Storage Box fills | 1 TB shared; `media.bytes` in the manifest makes growth visible before it bites. |
| Correlated failure — servers and backups are both Hetzner | Known and accepted for now. The artifact is provider-portable by design, so an off-Hetzner weekly copy can be added later without touching anything above. |

## Deferred, and where they attach

- **Off-Hetzner weekly copy.** The artifact is already portable; this is a second rsync
  target, not a redesign.
- **The five-input pricing estimator** for the school-facing page. Needs an MB-per-minute
  constant *measured* against the matematyka corpus (`courses/models.py:803` records 232
  video assets against a ~9 GB steady-state footprint) rather than guessed.
- **The annual school statement** — planned versus actual, per school. Half of it is
  `media.bytes` from the manifest above; the rest are trivial queries against enrollments,
  `Course` rows, creator-role users and `IssueReport` rows.
- **WAL archiving** for a school needing a tighter RPO. Writes into the reserved `wal/`.
- **Per-school PWA** (sub-project C) and **B2** release machinery.
