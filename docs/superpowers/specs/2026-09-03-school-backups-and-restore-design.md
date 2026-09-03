# School backups and restore — design

Sub-project **B1** of the school hosting model. Decided 2026-09-03.

## Why this exists

Backups are a stated requirement, not a follow-up: a school must not go live unbacked.
`docs/deployment.md` currently lists "No backups. No `pg_dump` cron, no snapshot policy"
under *Known constraints*, while `docs/public/privacy.md` already tells users that "the
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

- Point-in-time recovery. The default tier is nightly; `wal/` is reserved as a *naming*
  reservation so a school needing a tighter RPO can have WAL archiving added later without
  a redesign or a second destination. **No code in this work creates, writes or reads
  `wal/`**, and `restore.sh` does not care whether it exists.
- Per-school storage *quotas*. This work measures storage; it does not enforce it.
- Multi-host deploy targeting, release-tag promotion, canary. That is B2.

## Decisions taken

| Decision | Choice | Rationale |
|---|---|---|
| Destination | One Hetzner Storage Box (BX11, ~1 TB), one sub-account per school | ~EUR 3.80/mo for all schools; EU region; plain SSH/rsync, so restore works from anywhere and is not tied to an S3 SDK |
| Adversary layer | Storage Box snapshots (daily, 10 retained) | Taken by the *main* account, so a school box's sub-account credential cannot destroy them |
| Encryption | `age`, public-key mode | The box holds only the public key: it writes backups it cannot read |
| Encrypted | DB dump, `.env.production`, `support_screenshots`, `caddy_data` | Pupil data, every secret, and TLS/ACME private keys |
| Plain | `media/` (the whole of `MEDIA_ROOT`) | Course content and branding; the bulk of the bytes; stays verifiable without the key |
| App version | Pull a published image; stop building on the box | Restore must be able to start the version the dump came from |
| Timezone | The host is set to **UTC** during provisioning | So the cron slot, `<ts>` and `taken_at` are all the same clock |

### Threat model — be explicit about which layer stops what

The three protection layers are not interchangeable and it matters which stops which:

| Threat | What stops it | Horizon |
|---|---|---|
| A file or element deleted by mistake | The `media/` mirror retains it (`--delete` omitted) | `MIRROR_PRUNE_DAYS` = 90 |
| A volume wiped, or the box lost entirely | The nightly artifact | 30 daily + 12 monthly |
| An **adversary holding the box's own credential** | **Storage Box snapshots only** | **10 days** |

The third row is the one that is easy to get wrong. Omitting `--delete` does *not* protect
against an attacker — they hold a credential that can delete or overwrite the school's
directory directly. Hetzner sub-accounts can be scoped to a subdirectory but **cannot be
made append-only**. So the effective ransomware recovery horizon is **10 days**, the
snapshot count — not the 30+12 the retention rule implies. Recorded here so nobody reads
the retention numbers as a security property.

### Key custody

One `age` keypair for all schools. The **public** key is configured on each box. The
**private** key lives in the password manager plus one offline copy.

The invariant is **never at rest on a server** — not "never on a server". `restore.sh`
necessarily decrypts on the target box, so the identity is present *during* a restore:

- It is written to a tmpfs path (`/dev/shm/libli-restore.key`), never to disk.
- The operator supplies it out of band: `ssh <box> 'cat > /dev/shm/libli-restore.key' < ~/.age/libli.key`.
- `restore.sh` installs an `EXIT` trap that removes it on every exit path, including failure.
- `restore.sh` refuses to start if the identity is absent, rather than failing halfway.

Losing the private key loses every school's backups. Accepted deliberately: it is the
price of the box being unable to read its own history. Per-school keypairs were rejected
for the routine case — they multiply custody without changing its shape, since one
compromised laptop loses all of them anyway. **Handover is the exception; see below.**

### The complete out-of-band input set for a restore

Goal 1 says "nothing pulled from the original machine", and there is a bootstrap trap
hiding in it: the Storage Box credential lives *inside* the encrypted `.env.production`,
so it cannot be used to fetch that file. A restore therefore needs three things that come
from the password manager, not from any server:

1. The **`age` identity** (above).
2. A **Storage Box credential for restores** — the main account, or a per-school
   read-capable sub-account. Deliberately *not* the credential the school box itself
   holds: that one is compromised in exactly the scenario a restore is for.
3. The **school slug**, as `--slug`. It is needed to build the remote path
   `schools/<slug>/...` *before* anything can be fetched or decrypted, so it cannot come
   from `.env.production` — which is itself one of the things being fetched. Provisioning
   sections 1-2 install SSH and Docker and no configuration at all, so there is no earlier
   source for it either.
4. The **target `<ts>`**, chosen by reading `manifest/`.

Optionally `--image-tag`; see *Which image the checks compare against* below.

`docs/backup-and-restore.md` lists these as a pre-flight checklist.

## The artifact

```
schools/<slug>/
  db/<ts>.dump.age             pg_dump -Fc, encrypted. Dated, pruned.
  env/<ts>.env.age             .env.production, encrypted. Dated, pruned.
  screenshots/**.age           per-file mirror, encrypted, WITH --delete
  media/**                     per-file mirror, plain, pruned at 90 days
  caddy/<ts>.tar.age           caddy_data, encrypted
  manifest/<ts>.json           what this backup is
  wal/                         naming reservation only; no code touches it
```

`<ts>` is `YYYY-MM-DDTHHMMSS` in UTC. Seconds, not minutes: a manual rehearsal run
alongside cron would otherwise collide and silently overwrite. A run whose `<ts>` already
exists aborts rather than overwrites.

### Reaching a named volume

`media`, `support_screenshots`, `caddy_data` and `caddy_config` are **named Docker
volumes**, not bind mounts. There is no `/opt/libli/media` on the host, so a bare
`rsync media/` cannot work.

The scripts resolve each volume's host path at run time:

```sh
vol_path() { docker volume inspect --format '{{.Mountpoint}}' "libli_$1"; }
```

The `libli_` prefix is Docker's `<project>_<volume>` convention and comes from `name: libli`
at the top of `docker-compose.prod.yml`. That coupling is real, so the path-agreement guard
(test 6) asserts the compose file still declares that project name.

### Ordering is load-bearing: dump first, media second

`pg_dump` takes a consistent snapshot at T0; the media mirror runs at T1 > T0.

- **Dump then media** — a file created between T0 and T1 lands in the mirror with no row
  referencing it. A harmless orphan.
- **Media then dump** — a file created in between lands in the *dump* with no bytes in the
  mirror. A row pointing at nothing, which is a broken restore.

The safe direction is the one that risks orphans, never dangling references.

### Mirror retention, and why the two mirrors differ

**`media/` omits `--delete`** so that a hard-deleted element's file survives its row —
element deletion in libli has no orphan table and no audit trail, and this is the first
thing that makes a mis-click recoverable. But an unbounded mirror has *no retention*, which
cannot be squared with a published retention period. So it is pruned: **a file absent from
the live tree for more than `MIRROR_PRUNE_DAYS` (90) is deleted from the mirror.** Ninety
days is about a term — long enough to notice a mistake, short enough to state publicly.

**`screenshots/` uses `--delete`.** `IssueReport.screenshot` is personal data and may carry
another pupil's grades. A deletion is an erasure, and an erasure that the backup silently
undoes is not an erasure. Recoverability loses to RODO here, deliberately.

Screenshot names are immutable (`screenshots/<YYYY>/<MM>/<uuid4>.<ext>` — the client
filename is never used), which makes the encrypted mirror cheap: `--ignore-existing`
alongside `--delete` means only genuinely new files are encrypted and uploaded, and
nothing is ever re-encrypted. See *Per-file encryption* below.

### Media paths must be preserved exactly

`media/` is **the whole of `MEDIA_ROOT`**, which today holds three trees: `courses/media/`
(`MediaAsset.file`), `courses/media/derivatives/` (`thumb`, `web`) and `branding/`
(`Institution.logo`, `Institution.favicon`). The mirror is `MEDIA_ROOT`-wide rather than
per-tree, so a tree added later is covered without a change here.

`MediaAsset.file` is `upload_to="courses/media/"` with the **original filename**, plus
Django's random 7-character suffix on collision (`courses/models.py:795`). Names are *not*
content-addressed — `content_hash` is a database column only and paths cannot be rebuilt
from it. A restore that renames or re-lays-out media breaks every `FileField` in the
database. The mirror is therefore path-faithful.

Image derivatives *are* regenerable via `backfill_media_derivatives`, but are backed up
anyway: excluding them saves bytes on the cheapest resource in the system and costs CPU and
wall-clock on the restore, which is the moment that matters.

### Volume classification — all seven, machine-checkable

`backup.sh` carries this as a parsed array, with the reason on the preceding comment line.
Test 1 derives the volume list from `docker-compose.prod.yml` and requires every entry to
be classified here, so a volume added later fails the suite until someone decides.

```sh
# pgdata: captured by pg_dump, never mirrored -- a filesystem copy of a
#   running postgres data directory is not a consistent backup.
# media: the whole of MEDIA_ROOT; plain mirror, pruned at MIRROR_PRUNE_DAYS.
# support_screenshots: personal data; encrypted per-file mirror WITH --delete.
# caddy_data: ACME account key + issued certificate private keys; encrypted
#   tarball. Kept to spare Let's Encrypt rate-limit budget on repeated restores.
# caddy_config: NOT BACKED UP -- autosaved by Caddy, regenerated from the
#   mounted Caddyfile on first boot.
# transfer_staging: NOT BACKED UP -- in-flight uploads only, swept at 6h.
# upload_tmp: NOT BACKED UP -- transient Django upload spill.
VOLUME_CLASS=(
  "pgdata=dumped"
  "media=mirror-plain"
  "support_screenshots=mirror-encrypted"
  "caddy_data=archive-encrypted"
  "caddy_config=excluded"
  "transfer_staging=excluded"
  "upload_tmp=excluded"
)
```

`caddy_data` moved into the encrypted set on review: it holds the ACME account key and
every certificate's private key, which the "every secret" criterion covers and goal 3
requires. Its justification is rate-limit budget, not byte count — it is kilobytes.

### The manifest

Written every night, read by every restore. Every field has a stated purpose; fields that
did nothing were removed (`format_version` in particular — it is a course-transfer
constant and this work does not use the transfer format at all).

```json
{
  "schema": 1,
  "school": "<slug>",
  "taken_at": "2026-09-03T02:15:04Z",
  "image": "ghcr.io/krzyssikora/libli:sha-d45d67d1",
  "git_sha": "d45d67d1",
  "migrations": ["accounts.0007_...", "courses.0042_...", "institution.0011_..."],
  "postgres_major": 16,
  "row_counts": {"accounts_user": 412, "courses_contentnode": 8931},
  "media": {"files": 2914, "bytes": 9214773248},
  "screenshots": {"files": 37, "bytes": 5412233}
}
```

| Field | Purpose |
|---|---|
| `schema` | `restore.sh` refuses a major it does not know. Bumping it obliges the author to state the reader behaviour for the old value. |
| `school` | Guards against restoring school A's dump onto school B's box. Compared against `LIBLI_SCHOOL_SLUG`. |
| `taken_at` | Human selection of a restore point. |
| `image` | The **immutable** tag to pull. Never `:master`. |
| `git_sha` | Cross-check against the checkout; also what §8's rollback resets to. |
| `migrations` | The version-direction check. See below. |
| `postgres_major` | `restore.sh` refuses when the `db` image's major is lower. |
| `row_counts` | Informational, with a stated skew. See *Verification*. |
| `media.files` | Informational — the file-count half of the storage figure, beside `media.bytes`. It is **not** the media completeness gate; that gate is referenced-files-equals-fetched-files at restore time, which never reads this field. Recorded because a night-on-night drop in it is a visible symptom of a mirror losing files. |
| `media.bytes` | The per-school storage figure the pricing model needs. Written now, read by nobody in this work — `backup.sh` already walks the tree, so it is free here and expensive anywhere else. |

**The version check uses migration *sets*, not a single head.** Django has one leaf per
app, so recording a single `institution.0011` could not detect an image behind on a
`courses` migration — which is where nearly all schema change happens here. `migrations`
is the full set of applied migration names, and the rule is **containment**: the image's
migrations must be a superset of the manifest's. A dump restored onto a *newer* image
migrates forward and is fine; onto an older one it is broken.

Reading that set from an image that has not started needs no database — the migration
*files* are in the image:

```sh
docker run --rm --entrypoint sh <image> -c 'ls /app/*/migrations/[0-9]*.py'
```

That is what makes the check possible at step 4, before the database exists.

## `backup.sh`

Lives at the repo root beside `deploy.sh`, for the reason that file's own header gives: it
goes through the normal PR/CI/review path, and `deploy.sh`'s `git reset --hard` keeps the
host copy current for free. Reuses `deploy.sh`'s `env_value()` helper to read
`.env.production`.

**`set -euo pipefail`** — `pipefail` is load-bearing, not hygiene. Without it a `pg_dump`
that dies part-way while `age` exits 0 produces a short, well-formed, encrypted file, a
written manifest and a *green* heartbeat: the exact failure the verification exists to
catch, undetected until a restore is attempted. Test 5 asserts it.

**Straight-line, no function indirection around the ordered steps.** Tests 2-4 are
source-order assertions, so a refactor into `dump_db()` / `mirror_media()` would break them
or pass them for the wrong reason. That is a design constraint this spec owns rather than
smuggles in through a test; both scripts say so in their headers.

```
 1. flock on /var/lock/libli-deploy.lock, or exit 0 quietly
 2. abort if schools/<slug>/db/<ts>.* already exists
 3. row counts + migration set  (informational; skew stated below)
 4. compose exec -T db pg_dump -Fc  ->  a temp file on the host
 5. pg_restore --list on that file  <- the truncation detector
 6. age -r $RECIPIENT  -> upload db/<ts>.dump.age ; rm the temp file
 7. age -r $RECIPIENT .env.production -> env/<ts>.env.age
 8. mirror media/        (rsync, no --delete)
 9. mirror screenshots/  (encrypt-new-then-rsync --delete --ignore-existing)
10. tar caddy_data | age -> caddy/<ts>.tar.age
11. write manifest/<ts>.json
12. prune db/, env/, caddy/ per retention; prune media/ per MIRROR_PRUNE_DAYS
13. GET the heartbeat URL — on success only
```

**Step 4 is a compose exec, not a host command.** There is no postgres client on the host;
the database exists only inside the `db` container. `-T` is load-bearing twice over: cron
has no TTY, and a pseudo-TTY would corrupt the binary `-Fc` stream. Credentials come from
`env_value POSTGRES_USER` / `POSTGRES_DB` with `PGPASSWORD` from `env_value POSTGRES_PASSWORD`.

**Steps 4-6 use a temp file rather than a single pipe, and that buys the truncation check.**
The dump is *small* — media lives on disk, not in Postgres — so spooling it costs almost
nothing, and it lets `pg_restore --list` read the archive's table of contents before
upload. A truncated `-Fc` archive fails to list. That is a real, cheap integrity check on
the artifact itself, and it is why `row_counts` does not have to carry that weight.

**`pg_dump` of the single database, not `pg_dumpall`.** The `libli` role is created by the
postgres image from `POSTGRES_USER`/`POSTGRES_PASSWORD` on first init, not by the dump.

**rsync exit 24 is success.** `rsync` returns 24 ("some files vanished before they could be
transferred") whenever a file is deleted mid-run, which is routine on a live media tree.
Under `set -e` that would abort before step 13 and fire the heartbeat alert on a backup
that is fine — and repeated false alerts are how a real one gets ignored. The scripts wrap
rsync in a helper that treats **0 and 24** as success and every other code as failure.

### Per-file encryption of screenshots

`rsync` cannot transform files in flight, and `age` output is non-deterministic, so
rsync's size/mtime comparison is useless across the plain/encrypted boundary. The rule:

1. `rsync --list-only` the remote `screenshots/` to get the set of `<name>.age` already there.
2. For each live screenshot **not** in that set, encrypt into a staging directory that
   mirrors the tree, named `<name>.age`.
3. `rsync --delete --ignore-existing` the staging directory to the remote.
4. Remove the staging directory in an `EXIT` trap.

`--ignore-existing` is safe *because screenshot names are immutable* — a given path's bytes
never change. That is what keeps the run incremental without re-encrypting the world.

### Retention algorithm

Precise enough to implement, including the awkward cases:

- Keep **every** `db/`, `env/` and `caddy/` artifact whose `<ts>` is within
  `RETAIN_DAILY_DAYS` (30) of now.
- Older than that: keep the **earliest** artifact of each calendar month, for
  `RETAIN_MONTHLY_MONTHS` (12). Delete the rest.
- A missed night simply has no artifact; nothing special happens.
- Two runs in one day are both kept while inside the 30-day window; monthly promotion picks
  the earliest in the month. This is why the rule is date-based rather than "keep the newest
  30", which would retain 15 days if two runs landed daily.
- `media/`: delete any mirrored file whose path is absent from the live tree and whose
  mirror mtime is older than `MIRROR_PRUNE_DAYS` (90).

`RETAIN_DAILY_DAYS`, `RETAIN_MONTHLY_MONTHS` and `MIRROR_PRUNE_DAYS` are shell constants at
the top of `backup.sh` so the privacy-notice guard can read them (test 8).

### Schedule and alerting

**`15 2 * * *`** — deliberately *not* 03:30, which is the runbook's existing
`purge_notifications` slot; a dump competing with a retention purge for the same container
and disk is avoidable. The host is UTC (provisioning step), so cron, `<ts>` and `taken_at`
agree without conversion.

**Failure must be loud, and cron cannot be the channel.** There is no MTA on the box and
Hetzner blocks outbound 25 by default, so `MAILTO` is unavailable. Step 13 is an outbound
HTTPS ping to a dead-man's-switch (healthchecks.io free tier or equivalent), which alerts
on *absence* — the only thing that detects a backup that stopped running. **Period 24 h,
grace 6 h**: the grace must exceed one nightly interval plus the run's own duration, and a
first media sync on a 9 GB tree can take hours. Alerts go to Krzysztof by email and push.

### Overlap with a deploy

The `flock` at step 1 is taken on `/var/lock/libli-deploy.lock`, and **`deploy.sh` takes
the same lock**. A backup-only lock would have excluded a previous *backup* while leaving
the real hazard open: a merge to master mid-dump recreates the app container, restarts
postgres' dependents and prunes images. Test 7 asserts both scripts name the same lock
path — otherwise the risk table would claim a mitigation that does not exist.

## `restore.sh`

The same script serves all four paths. It runs on a box provisioned through sections 1-2 of
the runbook (SSH hardened, Docker installed).

```
 1. require the age identity at /dev/shm; install the EXIT trap
 2. fetch + print manifest/<ts>.json; require a typed confirmation
 3. refuse unknown manifest `schema`; refuse if manifest.school != --slug
 4. resolve the TARGET image (below); refuse if its migration set does not
    contain the manifest's; refuse if the db image's postgres major is lower
 5. decrypt env/<ts>.env.age -> .env.production, chmod 600, strip INIT_ADMIN_*,
    then rewrite LIBLI_IMAGE_TAG to the target resolved at step 4
 6. compose down --volumes          <- DESTRUCTIVE. Gated by step 2.
 7. compose up -d db                <- db ALONE. Not the app.
 8. decrypt + pg_restore the dump into the fresh database
 9. restore caddy/, media/ and screenshots/  <- three different paths; see below
10. compose up -d --wait            <- entrypoint migrates forward
11. verify; then the pre- or post-cutover checks per mode
12. if this restore followed a suspected compromise, rotate (below)
```

### Which image the checks compare against

Step 4 is only meaningful if the image being checked *can* differ from `manifest.image` —
comparing the manifest against itself would always pass and prove nothing. So the target is
an explicit input:

- **Default: `manifest.image`.** The disaster-recovery case — bring the site back exactly
  as it was. The check is a tautology here and is skipped with a printed note, which is
  honest about what it did and did not verify.
- **`--image-tag <tag>`: the override, and the only case worth guarding.** Restoring a
  three-week-old dump onto today's image is a normal and often *desirable* thing to do, and
  it is the case that can go wrong: forward is fine, backward is broken. This is where
  the migration-set containment check earns its place.

Step 4 resolves the target *before* `.env.production` exists, which is why it cannot read
`LIBLI_IMAGE_TAG` from the env — the env is one of the things being restored. Step 5 then
writes the resolved target into the restored file, so the persisted value matches what
actually gets pulled rather than what the old box happened to be running.

### Restoring the three data sets, which are three different mechanisms

Step 9 is one line in the list and three procedures in practice. Naming them separately
because the encrypted-per-file loop is easy to under-build:

| Set | Stored as | Restore path |
|---|---|---|
| `caddy/` | one `<ts>.tar.age` archive | `age -d` then `tar -x` into the `caddy_data` volume path |
| `media/` | plain per-file mirror | `rsync` **only** the paths `list_referenced_files` names |
| `screenshots/` | per-file `.age` | fetch only referenced paths, `age -d` each, strip the `.age` suffix, write into the `support_screenshots` volume path |

All three write to host paths resolved by `vol_path()`, and all three run *after* the
database is loaded, because the referenced-file list comes from it.

**Step 6 is the step whose absence would have been a silent data bug.** On the same-box
restore path the box already has a `pgdata` volume, and the postgres image reads
`POSTGRES_PASSWORD` **only when it initialises an empty data directory**. Restoring into an
existing volume would leave the database on the *old* password while the app used the
restored one — precisely the footgun `docs/deployment.md` documents. `down --volumes` is
what makes "a fresh `pgdata` initialised from the restored `.env.production`" true by
construction rather than by assumption. On the resize and provider-move paths it is a no-op.
Declining the confirmation at step 2 exits without touching anything.

**Step 7 must not be `up -d`.** The container entrypoint runs `migrate` on every boot
(`docker-entrypoint.sh`). Bringing the full stack up against an empty database creates the
schema, and the dump then collides with it. The database is loaded before the app container
ever starts. Test 6 asserts a qualified `up -d db` precedes the `pg_restore` line and that
no unqualified `up -d` appears before it.

**Step 9 restores only the files the restored database references.** Copying the whole
mirror back would resurrect every file deleted in the last 90 days — and because Caddy
serves `media/` directly from the volume, a resurrected file is reachable at its URL
whether or not any row points at it. So after the database is loaded, `restore.sh` asks it
what it needs:

```
manage.py list_referenced_files   # one MEDIA_ROOT/SUPPORT_SCREENSHOT_DIR-relative path per line
```

covering `MediaAsset.file`/`thumb`/`web`, `Institution.logo`/`favicon` and
`IssueReport.screenshot`. Exactly those are fetched. This is the only new Python in B1, it
is small, and unlike a shell script it is directly testable in pytest.

It also makes the media check *exact* rather than a tolerance: files fetched must equal
files referenced. Any that are missing from the mirror are listed by name and the restore
fails loudly — a missing derivative is repaired with `backfill_media_derivatives`, a
missing original is not repairable and the operator needs to know which.

**Single-file recovery** — the everyday use of the append-only mirror, and what justifies
it — is a documented `rsync` of one path out of `media/` into the volume. It does not
involve `restore.sh` at all.

### Verification, and the skew that is honestly stated

`row_counts` and the migration set are captured at step 3, *before* the dump at step 4, so
they describe the database a moment earlier. On a live site rows arrive in between. They
are therefore **informational**, printed for the operator to eyeball, and never a pass/fail
gate — a gate would go red on healthy backups and could still pass on a bad one if drift
happened to compensate.

The gates are the ones that can actually be exact:

- `pg_restore --list` on the artifact at backup time (truncation).
- Referenced-files-equals-fetched-files at restore time (media completeness).
- The migration-set containment check (version direction).

`row_counts` covers only tables the entrypoint does not touch — it excludes `auth_group`,
`auth_permission`, `django_migrations` and `django_site`, all of which `migrate`,
`setup_roles` and `set_site_domain` rewrite on boot at step 10. Step 5 strips
`INIT_ADMIN_*` from the restored env for the same reason and one worse: left in place, the
entrypoint's `init_platform` would mint an admin account on a production restore.

### Pre-cutover mode, or Caddy burns the rate limit before you need it

On the resize and provider-move paths, DNS still points at the *old* box when the new one
boots. Step 10 would start Caddy, which immediately attempts ACME for `SITE_ADDRESS`,
fails validation repeatedly, and eats Let's Encrypt's failed-validation budget — possibly
blocking issuance at the cutover, the worst possible moment. The section 4 checks would
also be meaningless, since the public hostname resolves to the other machine.

So `restore.sh` takes a mode:

- **`--pre-cutover`** — boots with `tls internal`, so Caddy uses its own CA and attempts no
  ACME. Checks run against `127.0.0.1` with an explicit `Host:` header, exactly as the
  container healthcheck already does. This validates the restore without touching DNS.
- **`--live`** (default) — the real `SITE_ADDRESS`, ACME as normal, and the full section 4
  checks against the public name. Run after DNS is repointed.

The runbook's restore section splits the section 4 checks into those two groups.

### Rotation after a compromise — step 12

The threat model names an adversary holding the box's own credential, and the restore
credential is deliberately a different one for that reason. But step 5 restores
`.env.production` **verbatim**, and that file still contains the `LIBLI_BACKUP_SSH_*`
values the adversary had. Without a rotation step the rebuilt box resumes nightly backups
using a credential someone else is known to hold — which would quietly undo the whole
point of having used a separate credential to recover.

So when a restore follows a suspected compromise, rotate before the first nightly run:

- `LIBLI_BACKUP_SSH_KEY` and the **Storage Box sub-account** itself (new sub-account, new
  key; the old one revoked at Hetzner, not merely unused).
- `POSTGRES_PASSWORD` — but note it can only change while `pgdata` is being re-initialised,
  so it must be set **at step 5**, before step 6's `down --volumes`, not afterwards.
- `DJANGO_SECRET_KEY`, and `EMAIL_HOST_PASSWORD` if one is configured.
- The SSO client secret in `SocialApp.secret` and `WebhookEndpoint.secret` — both live in
  the **database**, so they survive the restore and are rotated through the admin UI, not
  the env file. Easy to miss for exactly that reason.
- Optionally the shared `age` recipient, if the private key itself is suspect — which is a
  fleet-wide event, not a per-school one, and means re-encrypting every school's history.

This list is the disaster-recovery counterpart to the handover rotation below, and
`docs/backup-and-restore.md` carries both.

### How the four paths use it

- **Restore** — `--live`, same hostname. Step 6 is the destructive one.
- **Resize** — `--pre-cutover` on the larger box, repoint DNS, re-run `--live`.
- **Provider move** — identical to resize. Nothing in the artifact is Hetzner-specific.
- **Handover** — see below. Not a fifth mechanism, but *not* just documentation either.

The course transfer format (`courses/transfer/`, `FORMAT_VERSION = 13`) is explicitly
**not** used for any of these. Its archive carries `manifest.json`, `course.json` and media
bytes only — no users, enrollments, progress, grades, submissions, Institution config or
SSO. It is a content mover, not a site mover.

### Handover needs a key rotation, not a key disclosure

Handing a school the shared `age` private key would give them the ability to decrypt
**every other school's backups**. The single-keypair decision above did not anticipate
this, and handover is its one exception. The procedure:

1. The school generates its own `age` keypair; Krzysztof never holds the private half.
2. Krzysztof re-encrypts *that school's* current artifact under the new recipient and
   delivers it. The school's older history is **not** transferred — it stays under the
   shared key and is deleted on the agreed schedule. This is stated in the contract, not
   discovered at handover.
3. The Storage Box sub-account is replaced by a destination the school owns; the shared
   Storage Box credential is never disclosed either.
4. Values in `.env.production` that must be regenerated or re-pointed on handover:
   `DJANGO_SECRET_KEY` (rotate — it was in artifacts under the shared key),
   `POSTGRES_PASSWORD` (rotate), `EMAIL_HOST_*` (theirs now),
   `LIBLI_BACKUP_*` (their destination and recipient), and `SITE_ADDRESS` /
   `DJANGO_SITE_DOMAIN` / `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` if the
   hostname changes.

## The image switch

`docker-compose.prod.yml` moves `build: .` to
`image: ghcr.io/krzyssikora/libli:${LIBLI_IMAGE_TAG:?}` — the bare `:?` guard the file
already uses for every mandatory value. `deploy.sh` drops `--build` for a `pull`.

**Tag scheme, and why it keeps the existing rollback working.** B1 publishes exactly two
tags per build: `:master` (floating, for libli.pl's canary) and **`:sha-<short>`**
(immutable). `deploy.sh` **rewrites the `LIBLI_IMAGE_TAG=` line in `.env.production`
itself** — `sed`-in-place if the key is present, appended if not — to
`sha-$(git rev-parse --short HEAD)` from the checkout it just reset, *before* invoking
`compose up`. So the running image always corresponds to the checked-out commit.

**It must be persisted to the file, not exported for one shell.** Three things depend on
the key being readable later by a process deploy.sh never spawned:

- `backup.sh` runs hours later under cron and reads it with `env_value`; a transient export
  would make every nightly backup fail its own mandatory-key check.
- The encrypted `env/<ts>.env.age` in the artifact must carry the tag that matches the
  manifest's `image`, or "start the version this dump came from" has nothing to read.
- `compose` guards the key with the bare `:?`, so **any** `up` outside deploy.sh — the
  runbook's §3 first boot, `restore.sh` steps 7 and 10, a manual `up -d` after editing the
  env — would abort outright without a persisted value.

That has a pleasant consequence: `docs/deployment.md` §8's rollback is `git reset --hard
<last-good-sha>` followed by a recreate, and it **keeps working unchanged in meaning**,
because the tag follows the checkout. Without this the reset would silently become a no-op
that looked like it worked — the checkout would move and the running image would not.

The manifest records the immutable `sha-` tag, never `:master`; a floating tag cannot
satisfy "start the version this dump came from". Release-tag promotion (`:v1.4.0`), canary
and multi-host targeting stay in B2 — the example in the manifest above uses a tag B1
actually produces.

**Why this is in B1 at all:** restore depends on it. Without it, "bring up the version this
dump came from" is a source rebuild — the RAM spike that makes 4 GB a real floor, on a box
being brought back under pressure — and the manifest could record only a git sha rather
than something pullable.

**Existing test that must change:** `tests/test_deploy_wiring.py:174` asserts the
`compose up` line contains `--build`. It becomes `--wait` plus the pull step.

## Testing

The scripts run on a host, not in pytest, so most of this is textual wiring guards in the
style of `tests/test_deploy_wiring.py` — the established pattern for this exact problem, and
the file the new one sits beside. Each guard names the mutant that must turn it red.

`tests/test_backup_wiring.py`:

1. **Volume classification.** Parse the `volumes:` block of `docker-compose.prod.yml`;
   require every volume to appear in `VOLUME_CLASS` with a recognised class and a reason
   comment. *Mutant:* add a volume to the compose file → RED. The list is **derived** from
   the compose file, never hand-maintained beside it.
2. **Dump precedes media.** The `pg_dump` line appears before the media rsync line in
   `backup.sh`. *Mutant:* swap → RED.
3. **No `--delete` on the media mirror; `--delete` present on the screenshots mirror.**
   *Mutant:* either one flipped → RED. This is the RODO-vs-recoverability split, so it is
   pinned in both directions.
4. **The dump is verified before upload.** A `pg_restore --list` line appears between the
   `pg_dump` line and the `age` line. *Mutant:* remove it → RED.
5. **`set -euo pipefail`** is the first executable line of both scripts, in the shape of
   `test_ssh_action_stops_on_the_first_failing_line`. *Mutant:* drop `pipefail` → RED.
6. **`restore.sh` loads the database before the app starts.** A qualified `up -d db`
   precedes the `pg_restore` line; no unqualified `up -d` precedes it. *Mutant:* replace
   `up -d db` with `up -d` → RED.
7. **Lock agreement.** `backup.sh` and `deploy.sh` name the same lock path; the compose
   file still declares `name: libli` (which `vol_path()` depends on); the cron line in the
   runbook matches `backup.sh`'s path. Shaped after
   `test_deploy_yml_invokes_the_script_at_the_path_deploy_sh_assumes`.
8. **The privacy notices match the code.** `tests/test_public_pages_guards.py` exists so
   that "each asserts that a value the notice STATES still matches the code", in **both**
   languages. The retention periods stated in `privacy.md` and `privacy.pl.md` must match
   `RETAIN_DAILY_DAYS`, `RETAIN_MONTHLY_MONTHS` and `MIRROR_PRUNE_DAYS` in `backup.sh`.
   *Mutant:* change a constant without the notices → RED. Publishing a retention claim
   whose real value lives in a shell script is exactly the drift that file was written to
   prevent.
9. **Both scripts parse** (`bash -n`), matching the existing deploy guard.

`tests/test_list_referenced_files.py` — real unit tests, not textual: every file-bearing
field is covered (add a `FileField` to a model and the test should notice), blank fields are
skipped, and paths come out relative and forward-slashed.

### The rehearsal is part of the deliverable

B1 is not complete when the scripts exist. It is complete when a backup taken by
`backup.sh` has been restored by `restore.sh` onto a *fresh* box and this checklist passes:

- [ ] `pg_restore` completes with no errors
- [ ] referenced files fetched == referenced files listed
- [ ] the stack reaches healthy; `/healthz/` returns `"status": "ok"`
- [ ] the site answers over TLS on the restored hostname (`--live`) or the internal CA
      (`--pre-cutover`)
- [ ] a known course opens and renders a media element (proves paths survived)
- [ ] a Range request on a real `.mp4` returns 206 (the failure mode the runbook fears)
- [ ] a support screenshot decrypts and opens
- [ ] the Platform Admin can sign in, and no unexpected admin was created
- [ ] `Institution.load()` shows the school's own name, logo and signup policy

The textual guards above deliberately do not claim to prove the thing works — they prove it
has not drifted. Only the rehearsal proves it works.

**Evidence and recurrence:** each rehearsal is recorded, dated, in a *Rehearsal log*
section of `docs/backup-and-restore.md` — date, `<ts>` restored, box, outcome, anything
surprising. Recurrence is a **recurring calendar entry**, quarterly, naming that document.
Saying "rehearse quarterly" without naming the mechanism is how a quarterly rehearsal
becomes a one-off.

## Documentation

- **New `docs/backup-and-restore.md`** — the artifact, both scripts, key custody, the
  three out-of-band restore inputs, the four paths, the handover rotation, the single-file
  recovery procedure, and the rehearsal log. Separate from `docs/deployment.md`, which is
  already long; cross-linked from its §8.
- **`docs/deployment.md`** —
  - §1: install `age`; set the host clock to UTC.
  - §3: the first-boot `up -d --build` block becomes a pull. An operator following the
    current text on a fresh box would otherwise get no image at all.
  - §7: the cron entry, beside `purge_notifications` at a non-colliding slot, with the same
    one-physical-line and `exec -T` traps.
  - §8: the rollback block drops `--build` for a pull (the `git reset` keeps its meaning —
    see *The image switch*).
  - *Known constraints*: delete the "No backups" bullet; **rewrite the "No rollback"
    bullet** — pulling immutable tags makes an application rollback genuinely available for
    the first time, which is a real thing this work delivers. State what it cannot undo: an
    already-applied migration.
- **`.env.production.example`** (16 keys today) gains, with comments: `LIBLI_SCHOOL_SLUG`,
  `LIBLI_IMAGE_TAG`, `LIBLI_BACKUP_AGE_RECIPIENT`, `LIBLI_BACKUP_SSH_HOST`,
  `LIBLI_BACKUP_SSH_USER`, `LIBLI_BACKUP_SSH_KEY`, `LIBLI_BACKUP_HEARTBEAT_URL`. All are
  mandatory; `backup.sh` checks each with `env_value` and exits non-zero naming the missing
  key, since a blank value must not silently produce a backup that goes nowhere.
- **`docs/public/privacy.md` and `docs/public/privacy.pl.md`** — both, stating the same
  retention periods. `test_every_registered_page_has_both_language_files` treats them as a
  pair, and the Polish notice is the legally operative one for a Polish school.

## Risks

| Risk | Handling |
|---|---|
| Private `age` key lost | Accepted deliberately. Password manager plus one offline copy. |
| Backup silently stops | Dead-man's-switch, 24 h period / 6 h grace, alerting on absence. |
| Truncated dump | `pg_restore --list` before upload; a full restore at rehearsal. |
| Restore never rehearsed | A completion criterion with a checklist, then a quarterly calendar entry. |
| Backup overlaps a deploy | A `flock` **both** scripts take, guarded by test 7. |
| Adversary with the box's credential | Storage Box snapshots only; **10-day** horizon, recorded in the threat model. |
| Storage Box fills | See capacity below. |
| Correlated failure — servers and backups both Hetzner | Known and accepted. The artifact is provider-portable by design, so an off-Hetzner weekly copy is a second rsync target, not a redesign. |

### Capacity

Per school, roughly: ~9 GB steady-state media, plus 30 daily and 12 monthly dumps (small —
the database holds no media), plus the pruned mirror overhead. Call it ~12 GB. Storage Box
snapshots consume the same quota, so the practical figure is well below the nominal
1 TB / 12 GB. **Budget ~30-40 schools on a BX11 and revisit the tier at 20** — a threshold
"growth is visible before it bites" can actually be measured against, via `media.bytes`.

## Deferred, and where they attach

- **Off-Hetzner weekly copy.** A second rsync target; the artifact is already portable.
- **The five-input pricing estimator** for the school-facing page: pupil band, planned
  courses, videos per course, typical video length, number of creators. Needs an
  MB-per-minute constant **measured** against the matematyka corpus rather than guessed
  (`courses/models.py:803` records 232 video assets against a ~9 GB footprint). Note that
  images cost ~2.5x nominal because each stores `thumb` and `web` alongside the original,
  which is why the estimator folds images into a per-course baseline instead of asking.
- **The annual school statement** — planned versus actual, per school. Half of it is
  `media.bytes` from the manifest above; the rest are trivial queries against enrollments,
  `Course` rows, creator-role users and `IssueReport` rows. Support load is the cost that
  can actually hurt, so the tier states a bound on it.
- **WAL archiving** for a school needing a tighter RPO. Writes into the reserved `wal/`.
- **Per-school PWA** (sub-project C). Blocked on settling the service-worker update
  strategy first — a stale worker has already bitten this repo once, and install semantics
  on top of that is how a school gets pinned to a three-week-old build with no way to tell.
- **B2** release machinery: release-tag promotion, canary, multi-host CD.
