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
so it cannot be used to fetch that file. A restore therefore needs these, from the
password manager rather than from any server:

1. The **`age` identity** (above).
2. A **Storage Box credential for restores** — the main account, or a per-school
   read-capable sub-account. Deliberately *not* the credential the school box itself
   holds: that one is compromised in exactly the scenario a restore is for. It gets the
   *same* treatment as the age identity, because it has the same bootstrap problem and is
   equally sensitive: `--ssh-host` and `--ssh-user` as flags, and the key delivered to
   `/dev/shm/libli-restore-ssh.key` by the same `ssh <box> 'cat > ...'` route, removed by
   the same `EXIT` trap. `restore.sh` refuses to start if either the age identity or this
   key is absent.
3. A **GHCR read credential** — but **only when the box has no valid login already**.
   Provisioning §1 performs `docker login ghcr.io`, and that persists in
   `~/.docker/config.json`, which `compose down --volumes` does not touch. So on a
   normally-provisioned box VERSION's `docker run` just works and this input is not needed.
   It *is* needed in three real cases: a box provisioned before the token existed, a PAT
   that has since expired or been revoked (including by the rotation list below), and a
   bare-metal rebuild where §1 has not run yet. `restore.sh` therefore tries the existing
   login first and falls back to `--ghcr-token`, failing with that instruction rather than
   an opaque `denied` from the registry.
4. The **school slug**, as `--slug`. It is needed to build the remote path
   `schools/<slug>/...` *before* anything can be fetched or decrypted, so it cannot come
   from `.env.production` — which is itself one of the things being fetched. Provisioning
   sections 1-2 install SSH and Docker and no configuration at all, so there is no earlier
   source for it either.
5. The **target `<ts>`**, chosen by reading `manifest/` — which outlives the artifacts it
   describes, so not every entry is restorable. CONFIRM refuses a pruned one before
   asking anything of the operator; see *Retention algorithm*.

Optionally `--image-tag`; see *Which image the checks compare against* below.

`docs/backup-and-restore.md` lists these as a pre-flight checklist.

## The artifact

```
schools/<slug>/
  db/<ts>.dump.age             pg_dump -Fc, encrypted. Dated, pruned.
  env/<ts>.env.age             .env.production, encrypted. Dated, pruned.
  screenshots/**.age           per-file mirror, encrypted, erased on deletion
  media/**                     per-file mirror, plain, pruned at 90 days
  refs/<ts>.txt                the files this dump references; CONFIRM's pre-WIPE check
  media-missing.tsv            path -> first-missing date; drives the media prune
  caddy/<ts>.tar.age           caddy_data, encrypted
  manifest/<ts>.json           what this backup is. NEVER pruned -- so it
                               outlives the artifacts it describes
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

⚠️ **"Absent from the live tree for 90 days" cannot be measured from the file's own
mtime.** `rsync` preserves the *source's* mtime on the mirrored copy and never touches it
again once the source is gone — so a course image uploaded two years ago and never edited
already has an mtime far older than 90 days on the day it is deleted. A prune keyed on that
mtime deletes it on the **very next nightly run**, collapsing the window from 90 days to
"until tonight" — and doing so precisely for the long-lived, never-modified files most
likely to be deleted by mistake. The guarantee would read correct and be worthless.

What has to be tracked is *time since first observed missing*, which nothing on disk
records. So `backup.sh` keeps one small state file beside the mirror,
`schools/<slug>/media-missing.tsv`, of `path<TAB>first-missing-date`. Each run:

- a mirrored path absent from the live tree and **not** in the file gains a row dated today;
- a path that has reappeared has its row dropped (an accidental deletion that got fixed
  restarts the clock, which is the desired behaviour);
- a path whose row is older than `MIRROR_PRUNE_DAYS` is deleted from the mirror and the row
  removed.

A lost or corrupted state file is not a data-loss event: every missing path simply gets
today's date and the window restarts. Failing *long* is the right direction for a prune.

**`screenshots/` is erased on deletion.** `IssueReport.screenshot` is personal data and may
carry another pupil's grades. A deletion is an erasure, and an erasure the backup silently
undoes is not an erasure. Recoverability loses to RODO here, deliberately — and note this
is done by an explicit `rm` of a computed list, **not** by `rsync --delete`; see *Per-file
encryption* below for why that distinction is load-bearing.

Screenshot names are immutable (`screenshots/<YYYY>/<MM>/<uuid4>.<ext>` — the client
filename is never used), which is what keeps the encrypted mirror cheap: a name already on
the remote never needs re-encrypting.

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
| `school` | Guards against restoring school A's dump onto school B's box. **Written** by `backup.sh` from `LIBLI_SCHOOL_SLUG` (the env exists on a running box); **compared** by `restore.sh` against `--slug`, because at IDENTITY the env has not been decrypted yet. Two different sources by necessity, so neither side should reach for the other's. |
| `taken_at` | Human selection of a restore point. |
| `image` | The **immutable** tag to pull. Never `:master`. |
| `git_sha` | Cross-check against the checkout; also what §8's rollback resets to. |
| `migrations` | The version-direction check. See below. |
| `postgres_major` | `restore.sh` refuses when the `db` image's major is lower. |
| `row_counts` | Informational, with a stated skew. **Derived, not curated:** every table in the `public` schema from `information_schema.tables`, minus the four exclusions named under *Verification*. Derived so it cannot rot as migrations add models — the same reasoning as test 1 deriving the volume list from the compose file rather than restating it. The two tables in the example are an excerpt, not the set. |
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

That is what makes the VERSION check possible before the database exists.

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
 5. write refs/<ts>.txt IMMEDIATELY (list_referenced_files, via exec -T app)
 6. pg_restore --list on the dump  <- the truncation detector
 7. age -r $RECIPIENT  -> upload db/<ts>.dump.age ; rm the temp file
 8. age -r $RECIPIENT .env.production -> env/<ts>.env.age
 9. mirror media/        (rsync, no --delete)
10. screenshots: upload E\R encrypted (NO --delete), then rm R\(E u refs)
11. tar caddy_data | age -> caddy/<ts>.tar.age
12. update media-missing.tsv; write manifest/<ts>.json
13. prune db/, env/, caddy/ + refs/ per retention; prune media/ per the tsv
14. GET the heartbeat URL — on success only
```

**The dump is a compose exec, not a host command.** There is no postgres client on the host;
the database exists only inside the `db` container. `-T` is load-bearing twice over: cron
has no TTY, and a pseudo-TTY would corrupt the binary `-Fc` stream. Credentials come from
`env_value POSTGRES_USER` / `POSTGRES_DB` with `PGPASSWORD` from `env_value POSTGRES_PASSWORD`.

**The dump goes to a temp file rather than a single pipe, and that buys the truncation check.**
The dump is *small* — media lives on disk, not in Postgres — so spooling it costs almost
nothing, and it lets `pg_restore --list` read the archive's table of contents before
upload. A truncated `-Fc` archive fails to list. That is a real, cheap integrity check on
the artifact itself, and it is why `row_counts` does not have to carry that weight.

**`pg_dump` of the single database, not `pg_dumpall`.** The `libli` role is created by the
postgres image from `POSTGRES_USER`/`POSTGRES_PASSWORD` on first init, not by the dump.

**rsync exit 24 is success.** `rsync` returns 24 ("some files vanished before they could be
transferred") whenever a file is deleted mid-run, which is routine on a live media tree.
Under `set -e` that would abort before the heartbeat and alert on a backup
that is fine — and repeated false alerts are how a real one gets ignored. The scripts wrap
rsync in a helper that treats **0 and 24** as success and every other code as failure.

### Per-file encryption of screenshots

`rsync` cannot transform files in flight, and `age` output is non-deterministic, so
rsync's size/mtime comparison is useless across the plain/encrypted boundary. The rule:

⚠️ **Upload and erasure MUST be two separate operations.** The obvious one-liner —
`rsync --delete --ignore-existing` from a staging directory holding only tonight's new
files — is catastrophically wrong. `--delete` removes destination files that have no
counterpart **in the source file list**, and `--ignore-existing` only suppresses
re-*transfer* of files that do match; it exempts nothing from deletion. A sparse staging
directory therefore tells rsync that every previously-uploaded screenshot no longer exists,
and **every nightly run would delete the entire screenshot history except that night's
batch.** Silent, and the exact opposite of what the RODO reasoning above asks for.

So: compute both sets explicitly and act on them separately.

1. `rsync --list-only` the remote `screenshots/` → the remote set **R** of `<name>.age`.
2. Walk the live tree → the expected set **E** = `{<path>.age for each live screenshot}`.
3. **Upload `E \ R`.** Encrypt just those into a staging directory mirroring the tree, then
   `rsync` the staging directory **without `--delete`**.
4. **Erase `R \ (E ∪ refs)`.** Delete exactly those paths on the remote, by explicit name —
   a batched `ssh … 'xargs rm -f'` over the computed list, never a `--delete` sweep.
   The keep-set includes **tonight's `refs/<ts>.txt`**, not just the live tree, and that
   union closes an intra-run race that is otherwise invisible: a screenshot whose
   `IssueReport` row is deleted *after* the dump was spooled but *before* this step would
   be absent from the live tree here, erased from the mirror, and then absent from a
   live-DB reading of `refs` too — so the mirror and `refs` would agree the file is gone
   while the dump still pointed at it, CONFIRM would see no discrepancy, and FILES would
   fail *after* WIPE. Keeping anything tonight's dump references costs at most one extra
   day of retention (tomorrow's dump no longer references it, so tomorrow's run erases it)
   and makes CONFIRM's guarantee exact for the newest backup.
5. Remove the staging directory in an `EXIT` trap.

Step 3 is incremental *because screenshot names are immutable* — a given path's bytes never
change, so a name already in **R** never needs re-encrypting. Step 4 is what actually
implements erasure, and because it names paths derived from **R** minus **E**, it can only
ever remove something the live tree no longer has.

Test 3 pins this: the media rsync must not carry `--delete`, and the screenshots rsync must
not carry it either — the erasure is the explicit `rm`, and a `--delete` appearing anywhere
in `backup.sh` is the bug this section exists to prevent. *Mutant:* reintroduce
`--delete --ignore-existing` on the staging sync → RED.

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
- `media/`: delete any mirrored file whose row in `media-missing.tsv` is older than
  `MIRROR_PRUNE_DAYS` (90) — **never** keyed on the file's own mtime, for the reason given
  under *Mirror retention* above.
- `screenshots/`: no age-based rule at all. A screenshot leaves the mirror when it leaves
  the live tree, on the same run.
- **`manifest/` is never pruned.** Each file is a few hundred bytes, and the deferred annual
  school statement wants the `media.bytes` series over years — far longer than any artifact
  is kept. Keeping them is nearly free and deliberately outlives the thing they describe.

⚠️ **Which means `manifest/` lists more timestamps than are restorable, and that is a trap
with teeth.** The operator chooses a restore point *by reading* `manifest/` (out-of-band
input 5), so once the 30-day window has passed there are entries whose `db/`, `env/` and
`caddy/` artifacts have been pruned. Every early check — CONFIRM printing the manifest,
IDENTITY comparing `school`, VERSION comparing migration sets — reads only the manifest and
would pass happily for one of those ghosts. The failure would land at ENV, five steps in,
after the operator has already typed the confirmation slug: the fail-halfway behaviour this
design rejects for the age identity.

So **CONFIRM checks that the target's `db/`, `env/` and `caddy/` objects all exist before it
asks for the confirmation**, and refuses up front naming which are missing. The same listing
marks each manifest entry restorable or metadata-only, so the choice is informed rather than
corrected afterwards.

`RETAIN_DAILY_DAYS`, `RETAIN_MONTHLY_MONTHS` and `MIRROR_PRUNE_DAYS` are shell constants at
the top of `backup.sh` so the privacy-notice guard can read them (test 8).

### Schedule and alerting

**`15 2 * * *`** — deliberately *not* 03:30, which is the runbook's existing
`purge_notifications` slot; a dump competing with a retention purge for the same container
and disk is avoidable. The host is UTC (provisioning step), so cron, `<ts>` and `taken_at`
agree without conversion.

**Failure must be loud, and cron cannot be the channel.** There is no MTA on the box and
Hetzner blocks outbound 25 by default, so `MAILTO` is unavailable. The final step is an outbound
HTTPS ping to a dead-man's-switch (healthchecks.io free tier or equivalent), which alerts
on *absence* — the only thing that detects a backup that stopped running.

**Period 24 h, grace 6 h.** The switch alerts once `period + grace` has elapsed since the
last ping, and the ping happens at the *end* of a successful run — so the gap between
consecutive pings is one interval plus however much the run's duration **changed**. The
rule is therefore **grace > how much a run can lengthen between nights**. Not grace > a
run's duration, and definitely not grace > interval + duration, which 6 h could never
satisfy and which an earlier draft of this line wrongly asserted. Six hours covers a media
tree that grew by a course import overnight; the first run is long in absolute terms but
has no prior ping to be late against. Alerts go to Krzysztof by email and push.

### Overlap with a deploy

The `flock` is taken on `/var/lock/libli-deploy.lock`, and **`deploy.sh` takes
the same lock**. A backup-only lock would have excluded a previous *backup* while leaving
the real hazard open: a merge to master mid-dump recreates the app container, restarts
postgres' dependents and prunes images.

**All three scripts take it** — `restore.sh` too. A restore is the longest-running of the
three (a full `media/` re-fetch is bandwidth-shaped, tens of minutes to hours) and so is
the one most likely to still be running when the 02:15 cron fires or a merge lands. Without
the lock, a nightly `pg_dump` could read a database mid-`pg_restore`, or a deploy's recreate
could race `compose down --volumes`.

But the three differ in **how** they respond to a held lock, and that difference matters:

| Script | Lock held | Why |
|---|---|---|
| `backup.sh` | exit 0, quietly | Tonight's backup is skippable; the heartbeat's absence alerts if it keeps happening. |
| `deploy.sh` | wait, then fail | A deploy must not be silently dropped — CD would report green having done nothing. |
| `restore.sh` | **fail immediately and loudly** | A silently skipped restore is the worst outcome in the set: the operator believes the site is being recovered while nothing is happening. |

Test 7 asserts all three name the same lock path — otherwise the risk table would claim a
mitigation that does not exist.

## `restore.sh`

The same script serves all four paths.

### Step 0: getting `restore.sh` onto the box at all

⚠️ **This is a bootstrap gap that has to be closed explicitly, because the runbook does not
close it.** `restore.sh` runs on a box provisioned through runbook §1-2 — SSH hardened,
Docker installed — and §1-2 deliberately install *no* configuration, which is the same fact
that forces `--slug` to be a flag. But the `git clone <repo-url> /opt/libli` is in **§3**,
and everything the restore needs from the repo is on the far side of it: `restore.sh`
itself, `docker-compose.prod.yml` (which `vol_path()`'s `libli_` prefix, the `db` image's
postgres major and the volume list all come from), and the `env_value()` helper. On the
disaster-recovery-onto-new-hardware, resize and provider-move paths the box has only had
§1-2, so the operator would be running a script that by this design's own reasoning is not
there yet.

So the pre-flight in `docs/backup-and-restore.md` is, in order:

1. Runbook §1-2 (SSH, Docker, `age`, UTC clock, the Storage Box key file).
2. Read `manifest/` **from your own machine** and choose `<ts>` and the target version.
3. `git clone` the repo to `/opt/libli` and **`git checkout` the commit that corresponds to
   the target image tag** — the manifest's `git_sha` by default, or the sha behind
   `--image-tag` when overriding. Never floating `master`.
4. Deliver the age identity and restore SSH key to tmpfs.
5. `bash /opt/libli/restore.sh --slug … --ts … [--image-tag …] [--rotate-secrets]`.

Step 3 pinning to a *commit* rather than a branch is not tidiness. The compose file governs
the postgres major, the volume names and the healthcheck, so a checkout newer than the image
being started can disagree with it — a `postgres:17` line in a compose file restoring a
`postgres:16` dump, for instance. To keep that honest, **`restore.sh` compares its own
checkout's sha against the target it resolves at VERSION and refuses when they differ**,
naming both. That turns "the operator cloned the wrong thing" from a subtle mid-restore
failure into a refusal before anything is touched.

```
 1. LOCK        flock the shared lock -- fail LOUDLY if held, never skip
 2. CREDENTIALS require the age identity + restore SSH key on tmpfs; EXIT trap
 3. CONFIRM     fetch + print manifest/<ts>.json; HARD REFUSE unless db/, env/
                and caddy/ exist. Diff refs/<ts>.txt against the mirror and
                PRINT any gap (it may be legitimate) -- then TYPE the slug,
                which accepts that gap and records it for FILES
 4. IDENTITY    refuse an unknown `schema`; refuse manifest.school != --slug
 5. VERSION     resolve the TARGET image; refuse unless its migration set
                contains the manifest's; refuse a lower postgres major;
                refuse if this checkout's sha != the target's (see step 0)
 6. ENV         decrypt env/<ts>.env.age -> .env.production, chmod 600, strip
                INIT_ADMIN_*, write the VERSION target into LIBLI_IMAGE_TAG;
                with --rotate-secrets, mint the two generatable secrets HERE
 7. WIPE        compose down --volumes    <- DESTRUCTIVE. Gated by CONFIRM.
 8. MATERIALISE compose create            <- makes all volumes, starts nothing
 9. DB UP       compose up -d db          <- db ALONE. Not the app.
10. LOAD        decrypt + pg_restore the dump into the fresh database
11. FILES       restore caddy/, media/, screenshots/ -- three paths; see below
12. APP UP      compose up -d --wait      <- entrypoint migrates forward
13. VERIFY      then the pre- or post-cutover checks per mode
14. HANDOFF     print what the script could NOT do; exit non-zero if any
                --rotate-secrets follow-up is outstanding
```

**All fourteen are `restore.sh`'s own execution.** Nothing in the list is a human step, and
that is deliberate — an earlier draft ended with "the database-side rotation, admin UI",
which put a manual task in the same numbered sequence as `compose` invocations and left a
reader unable to tell which of the steps the script actually performs. The manual follow-ups
now live only in the rotation section, and HANDOFF is the script *telling* the operator
about them rather than pretending to do them.

### Which image the checks compare against

The VERSION step is only meaningful if the image being checked *can* differ from `manifest.image` —
comparing the manifest against itself would always pass and prove nothing. So the target is
an explicit input:

- **Default: `manifest.image`.** The disaster-recovery case — bring the site back exactly
  as it was. The check is a tautology here and is skipped with a printed note, which is
  honest about what it did and did not verify.
- **`--image-tag <tag>` must match `^sha-[0-9a-f]{7,40}$`, and `restore.sh` enforces it**
  before VERSION does anything else. "Never floating `master`" in the pre-flight is an
  instruction to a human, and the checkout-sha comparison needs a sha to compare: given
  `--image-tag master` there is nothing to extract, so the guard would either die on a
  failed match or pass vacuously — an undefined boundary of exactly the kind IDENTITY,
  CONFIRM and the postgres-major check all refuse to leave open. A floating tag is also
  wrong on its own terms: it names different code on different days, so it cannot pin a
  restore to a version. The refusal says so rather than just rejecting the pattern.
- **`--image-tag <tag>`: the override, and the only case worth guarding.** Restoring a
  three-week-old dump onto today's image is a normal and often *desirable* thing to do, and
  it is the case that can go wrong: forward is fine, backward is broken. This is where
  the migration-set containment check earns its place.

VERSION resolves the target *before* `.env.production` exists, which is why it cannot read
`LIBLI_IMAGE_TAG` from the env — the env is one of the things being restored. ENV then
writes the resolved target into the restored file, so the persisted value matches what
actually gets pulled rather than what the old box happened to be running.

### Restoring the three data sets, which are three different mechanisms

FILES is one line in the list and three procedures in practice. Naming them separately
because the encrypted-per-file loop is easy to under-build:

| Set | Stored as | Restore path |
|---|---|---|
| `caddy/` | one `<ts>.tar.age` archive | `age -d` then `tar -x` into the `caddy_data` volume path |
| `media/` | plain per-file mirror | `rsync` **only** the paths `list_referenced_files` names |
| `screenshots/` | per-file `.age` | fetch only referenced paths, `age -d` each, strip the `.age` suffix, write into the `support_screenshots` volume path |

All three write to host paths resolved by `vol_path()`, and all three run *after* the
database is loaded, because the referenced-file list comes from it.

### The completeness check has to happen before WIPE, not at FILES

⚠️ **The obvious placement of the media completeness check is past the point of no return.**
FILES compares referenced files against fetched files and fails loudly — but it runs at step
11, and WIPE is step 7. The referenced-file list appeared to require the *restored* database,
which does not exist until LOAD. So on the same-box restore path — the one case where WIPE
destroys data that was still live and good — an old `<ts>` could pass CONFIRM, IDENTITY and
VERSION, get wiped, load its dump, and only then discover that originals it references are
gone and not repairable.

And this is a *reachable* state, not a theoretical one, precisely because of two other
deliberate decisions: `media/` prunes files missing for more than 90 days, `screenshots/`
erases on deletion with no grace at all, and the retention rule keeps monthly dumps for
twelve months. A ten-month-old dump legitimately references files the mirror is equally
legitimately no longer holding.

**The fix is to move the knowledge earlier, not to move the check later.** `backup.sh` runs
while the app container is up and the database is live, so it can produce the referenced-file
list at backup time — `compose exec -T app` rather than the `run --rm` the restore needs —
and store it as `refs/<ts>.txt`. CONFIRM then diffs that list against a remote listing of
`media/` and `screenshots/`, needing **no database at all**, and shows the gap before WIPE
naming the missing paths.

`refs/` is pruned on the same clock as `db/`, `env/` and `caddy/`, since it is meaningless
without them.

**`refs/<ts>.txt` is written immediately after the dump, before either mirror step**, so it
describes the same database the dump captured rather than the database as it stood minutes
later. Written at the end of the run instead, it would be read *after* the screenshot
erasure and could agree with a mirror from which the dump's own references had just been
removed. The erasure's keep-set unions in tonight's `refs` for the same reason; see
*Per-file encryption of screenshots*.

**An older dump referencing an erased screenshot is genuinely not fully restorable, and
that is the design.** RODO erasure was chosen over recoverability for `screenshots/`
deliberately, so a twelve-month-old dump can legitimately reference files that no longer
exist anywhere. Only the intra-run race above is a bug; the long-horizon gap is a stated
consequence.

### CONFIRM's two checks are not the same kind of check

Which means CONFIRM cannot treat both of its inputs the same way, and saying it "refuses"
on either would make every sufficiently old `<ts>` permanently unrestorable — contradicting
the paragraph above.

| Check | Behaviour | Why |
|---|---|---|
| `db/`, `env/`, `caddy/` exist | **Hard refuse, no override** | Without the dump or the env there is nothing to restore. There is no degraded mode. |
| `refs/<ts>.txt` vs the mirror | **Print the gap, then proceed to the prompt** | A gap here is often correct, and a restore missing some media is still worth doing — the database, the users, the grades and the marking are all intact. |

So **the typed slug is what constitutes knowing acceptance of the gap.** The summary is
printed immediately above the prompt, grouped by consequence, because the three kinds are
not equally serious:

- **missing derivatives** — harmless; `backfill_media_derivatives` regenerates them.
- **missing screenshots** — expected on an old `<ts>`; erased by design.
- **missing originals** (`MediaAsset.file`, `Institution.logo`/`favicon`) — real content
  loss, unrepairable, and the only group worth hesitating over.

**FILES then honours that acceptance.** CONFIRM records the accepted set, and FILES fails
loudly only on files missing that CONFIRM did *not* already declare — an unexpected gap
means the mirror lost something between the check and the fetch, which is a genuine fault.
Without this the split would be pointless: the operator would accept a gap at CONFIRM and
the restore would die at FILES over the same files anyway, post-WIPE.

FILES still recomputes the list from the restored database and stays the authoritative
check. The two can differ by files created in the seconds between the list and the dump —
the same skew `row_counts` has — so a small discrepancy is reported rather than fatal, while
a missing *original* is still a hard failure. CONFIRM is the cheap predictor; FILES is the
truth.

**And if FILES fails anyway, the box is not stranded.** The nightly artifact taken before
the restore began is still on the Storage Box, and the mirror still holds every file *it*
references. Re-running against the newest `<ts>` returns the box to where it was this
morning. Worth stating explicitly, because "WIPE has run and FILES just failed" otherwise
reads like an unrecoverable position at the worst possible moment.

**CONFIRM does two things, in this order: it proves the artifacts exist, then it asks.**
Checking existence *after* the confirmation would be the same fail-halfway shape, just
one step later. Only once the target is known to be restorable does it require the
operator to type the school slug — not `y` or Enter.

 WIPE is
irreversible and the two ways to get a restore wrong are the wrong `<ts>` and the wrong
box; a keystroke confirms neither. Typing the slug forces the operator to read what is on
screen, and it is the value that distinguishes one school's box from another's.

**WIPE is the step whose absence would have been a silent data bug.** On the same-box
restore path the box already has a `pgdata` volume, and the postgres image reads
`POSTGRES_PASSWORD` **only when it initialises an empty data directory**. Restoring into an
existing volume would leave the database on the *old* password while the app used the
restored one — precisely the footgun `docs/deployment.md` documents. `down --volumes` is
what makes "a fresh `pgdata` initialised from the restored `.env.production`" true by
construction rather than by assumption. On the resize and provider-move paths it is a no-op.
Declining at CONFIRM exits without touching anything.

**It clears all seven volumes, not just `pgdata`, and that is intended.** `down --volumes`
removes every named volume in the compose file (none are `external`). Taking them in turn:
`caddy_config`, `transfer_staging` and `upload_tmp` are the excluded three and regenerate
themselves; `caddy_data`, `media` and `screenshots` are restored at FILES. So the outcome
is correct — but the *reason* to want the wider wipe is stronger than "FILES puts it back":

- It is what makes the media volume contain **exactly** the referenced set. A surgical
  `docker volume rm libli_pgdata` would preserve the old media tree, and FILES only *adds*
  referenced files — so any file the old tree held that the restored database does not
  reference would survive, unreferenced and still reachable at its URL through Caddy. That
  is the resurrection hole again, arriving by a different door.
- The cost is a full re-fetch of `media/` even on a same-box restore where the files were
  untouched — roughly 9 GB for a school with the matematyka import. That is intra-Hetzner
  traffic between the box and the Storage Box: fast and not billed. Paying it to get an
  exactly-correct volume is the right trade, and it is worth knowing before the first
  rehearsal that a restore is bandwidth-shaped rather than instant.

**MATERIALISE exists because `up -d db` creates only `db`'s volumes.** `compose up` brings
into existence just the named volumes attached to the services it starts, and `db` mounts
only `pgdata`. After WIPE has destroyed all seven, `media`, `support_screenshots` and
`caddy_data` belong to `app` and `caddy` — which do not start until APP UP. So FILES would
call `vol_path()` on volumes that do not exist and fail on `docker volume inspect`, with
nothing in the sequence having created them.

`compose create` is the fix rather than `docker volume create`: it materialises every
volume **with Compose's own labels** and starts no containers. Hand-created volumes carry
no `com.docker.compose.*` labels, and Compose then refuses to adopt a same-named volume it
did not create, demanding `external: true` — so the apparently simpler command would trade
a missing volume for a failing `up`.

**DB UP must not be `up -d`.** The container entrypoint runs `migrate` on every boot
(`docker-entrypoint.sh`). Bringing the full stack up against an empty database creates the
schema, and the dump then collides with it. The database is loaded before the app container
ever starts. Test 6 asserts a qualified `up -d db` precedes the `pg_restore` line and that
no unqualified `up -d` appears before it.

**FILES restores only the files the restored database references.** Copying the whole
mirror back would resurrect every file deleted in the last 90 days — and because Caddy
serves `media/` directly from the volume, a resurrected file is reachable at its URL
whether or not any row points at it. So after the database is loaded, `restore.sh` asks it
what it needs:

```sh
# `run --rm`, NOT `exec`: at FILES the app container has not started yet (APP UP does
# that), so there is nothing to exec into. `run` starts a throwaway container against the
# already-running db service, which is exactly what is available at this point.
compose run --rm --no-deps app /app/.venv/bin/python manage.py list_referenced_files
# one MEDIA_ROOT / SUPPORT_SCREENSHOT_DIR-relative path per line
```

`--no-deps` because `db` is already up and `depends_on` would otherwise pull `caddy` into
the picture. The entrypoint is bypassed by naming the interpreter directly, so this does
not re-run `migrate` as a side effect of asking a question.

covering `MediaAsset.file`/`thumb`/`web`, `Institution.logo`/`favicon` and
`IssueReport.screenshot`. Exactly those are fetched. This is the only new Python in B1, it
is small, and unlike a shell script it is directly testable in pytest.

It also makes the media check *exact* rather than a tolerance: files fetched must equal
files referenced, **minus the gap CONFIRM already declared and the operator already
accepted** by typing the slug. Anything missing beyond that accepted set is listed by name
and the restore fails loudly, because it means the mirror lost a file between the check and
the fetch — a genuine fault rather than a known consequence. A missing derivative is
repaired with `backfill_media_derivatives`; a missing original is not repairable and the
operator needs to know which. See *CONFIRM's two checks are not the same kind of check*.

**Single-file recovery** — the everyday use of the append-only mirror, and what justifies
it — is a documented `rsync` of one path out of `media/` into the volume. It does not
involve `restore.sh` at all.

### Verification, and the skew that is honestly stated

**`row_counts` is informational — the migration set is not.** Both are captured before the
dump, but only one of them drifts in that window, and conflating them would misrepresent
the version check the whole restore depends on.

- **`row_counts`** describes the database a moment before the dump, and on a live site rows
  arrive in between. So it is printed for the operator to eyeball and is **never a
  pass/fail gate** — a gate would go red on healthy backups and could still pass on a bad
  one if drift happened to compensate.
- **The migration set does not drift in seconds.** Migrations are applied by a deploy or by
  the entrypoint on boot, and the lock means neither can be running concurrently with a
  backup. So the set captured before the dump is the set the dump contains, and the
  containment check at VERSION is an **exact, restore-blocking gate**.

The gates are the ones that can actually be exact:

- `pg_restore --list` on the artifact at backup time (truncation).
- Referenced-files-equals-fetched-files at restore time (media completeness).
- The migration-set containment check (version direction).

`row_counts` covers only tables the entrypoint does not touch — it excludes `auth_group`,
`auth_permission`, `django_migrations` and `django_site`, all of which `migrate`,
`setup_roles` and `set_site_domain` rewrite on boot at APP UP. ENV strips
`INIT_ADMIN_*` from the restored env for the same reason and one worse: left in place, the
entrypoint's `init_platform` would mint an admin account on a production restore.

### Pre-cutover mode, or Caddy burns the rate limit before you need it

On the resize and provider-move paths, DNS still points at the *old* box when the new one
boots. APP UP would start Caddy, which immediately attempts ACME for `SITE_ADDRESS`,
fails validation repeatedly, and eats Let's Encrypt's failed-validation budget — possibly
blocking issuance at the cutover, the worst possible moment. The section 4 checks would
also be meaningless, since the public hostname resolves to the other machine.

So `restore.sh` takes a mode:

- **`--pre-cutover`** — at ENV, rewrite two keys in the restored `.env.production`:
  `SITE_ADDRESS=http://<hostname>` (note the explicit `http://` scheme) and
  `DJANGO_SECURE_SSL_REDIRECT=false`. Caddy then serves plain HTTP and **attempts no ACME
  at all**. Checks run against `127.0.0.1` with an explicit `Host:` header, exactly as the
  container healthcheck already does. This validates the restore without touching DNS.
- **`--live`** (default) — the real `SITE_ADDRESS`, ACME as normal, and the full section 4
  checks against the public name. Run after DNS is repointed. Re-running `restore.sh` in
  `--live` mode after the DNS change is what restores both keys.

**Why the scheme rather than a `tls` directive.** An earlier draft said pre-cutover "boots
with `tls internal`", which was a mechanism that does not exist: the `Caddyfile` has **no
`tls` directive at all**, and Caddy's automatic HTTPS is driven entirely by whether
`{$SITE_ADDRESS}` parses as a domain. Making `tls` variable-driven would mean a new env
var, a Caddyfile edit, a compose default and another guard — to reach a state the repo can
already express. `docs/deployment.md`'s local-smoke section already documents exactly this
pair of overrides for exactly this effect ("Caddy then serves plain HTTP and skips ACME
entirely"), so pre-cutover mode reuses a path that is already exercised rather than
inventing one. `DJANGO_ALLOWED_HOSTS` needs no change — it is the production value and
already contains the hostname.

The runbook's restore section splits the section 4 checks into those two groups: what can
be proved over plain HTTP against `127.0.0.1` before the cutover, and what can only be
proved against the public name afterwards (TLS, the certificate, and the Range check
through the real hostname).

### Rotation after a compromise — split by when it can happen

The threat model names an adversary holding the box's own credential, and the restore
credential is deliberately a different one for that reason. But ENV restores
`.env.production` **verbatim**, and that file still contains the `LIBLI_BACKUP_SSH_*`
values the adversary had. Without a rotation step the rebuilt box resumes nightly backups
using a credential someone else is known to hold — which would quietly undo the whole
point of having used a separate credential to recover.

**It is not a fifth path and not a mode the script guesses.** A compromise restore is any
of the four paths plus the flag **`--rotate-secrets`**. There is no heuristic and no prompt:
the operator knows whether they are recovering from a compromise, and nothing about a
manifest or a box can tell the script.

**What the flag does, and the sharp line through the middle of it.** Exactly two of the
secrets can be generated on the box, because they are arbitrary random strings that nothing
external has to agree with:

```sh
POSTGRES_PASSWORD   openssl rand -base64 36 | tr -d '/+=' | head -c 32
DJANGO_SECRET_KEY   openssl rand -base64 64 | tr -d '\n'
```

`--rotate-secrets` writes both into the decrypted `.env.production` at ENV — before WIPE,
which is the whole reason the flag exists rather than a post-restore checklist — and then
**prints them once**, with the instruction to save them to the password manager
immediately. They exist nowhere else at that moment: not in the artifact, not in any
backup, only in a file on a box that has just been rebuilt. That echo is unpleasant but it
is the only channel available, and §3 of the runbook already generates secrets this way.

Everything else **cannot** be generated locally, because an external system has to issue it
and agree to it: `DJANGO_EMAIL_HOST_PASSWORD` (the mail provider), `LIBLI_GHCR_TOKEN` (GitHub),
`LIBLI_BACKUP_SSH_KEY_PATH`'s key and the Storage Box sub-account (Hetzner), and the two
secrets that live in the database. So the flag does not pretend to handle them. Instead
HANDOFF prints them as an explicit outstanding list and **exits non-zero**, so a restore
that leaves known-compromised credentials in place cannot end in a green terminal and be
mistaken for finished.

Three groups, by when each is possible:

**At ENV, by the script — mandatory, because later is too late.**

- **`POSTGRES_PASSWORD`.** Postgres accepts a new password only while it is initialising an
  empty data directory, so the new value has to be in `.env.production` *before* WIPE
  destroys `pgdata` and DB UP recreates it. Rotate it after WIPE and the database keeps
  the old password while the app uses the new one — the same footgun WIPE exists to
  avoid, reintroduced by good intentions.
- `DJANGO_SECRET_KEY` — no timing constraint of its own, but it is an edit to the same
  file in the same pass, and it is generatable. Rotating it logs everyone out and
  invalidates outstanding reset and invitation links, which on a compromise restore is
  the desired outcome rather than a cost.
- `DJANGO_EMAIL_HOST_PASSWORD` is **not** in this group despite also being an env-file edit: the
  mail provider has to issue it, so it belongs to the out-of-band group below. It is the
  one entry where "same file" and "same actor" pull in different directions, and the
  actor wins.

**After the restore, by a human — because these live in the database and only exist once
it is restored.** `restore.sh` does not do this; HANDOFF names it.

- `SocialApp.secret` (the SSO client secret) and `WebhookEndpoint.secret`. Neither is in
  the env file, so both survive the restore intact and neither is touched by anything
  above. Rotated through the admin UI with the app running. Easy to miss for exactly that
  reason: a rotation pass that only edits `.env.production` leaves two live secrets in the
  adversary's hands.

**Out of band, by a human, before the first nightly run — at the provider, not on the
box.** `restore.sh` cannot do any of these and does not try; HANDOFF lists them and exits
non-zero while any remain.

- A **new Storage Box sub-account** and key, with the old one **revoked** at Hetzner rather
  than merely unused, and `LIBLI_BACKUP_SSH_KEY_PATH`'s key file replaced.
- A new `LIBLI_GHCR_TOKEN`, with the old PAT revoked at GitHub. ⚠️ Revoking it before the
  next restore is why out-of-band input 3 exists: the box's stored `docker login` stops
  working the moment the old PAT dies.
- `DJANGO_EMAIL_HOST_PASSWORD`, reissued by the mail provider.
- The shared `age` recipient **only** if the private key itself is suspect. That is a
  fleet-wide event rather than a per-school one: it means re-encrypting every school's
  history, so it is a decision to take deliberately, not a reflex.

`docs/backup-and-restore.md` carries this as a checklist beside the handover rotation below;
they are the same shape and neither should be reconstructed from memory under pressure.

### How the four paths use it

- **Restore** — `--live`, same hostname. WIPE is the destructive one.
  Add `--rotate-secrets` when recovering from a compromise; it is a modifier on this path
  (or any other), not a path of its own.
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
   `POSTGRES_PASSWORD` (rotate), `DJANGO_EMAIL_*` (theirs now),
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
  runbook's §3 first boot, `restore.sh`'s DB UP and APP UP, a manual `up -d` after editing the
  env — would abort outright without a persisted value.

### Publishing the image — nothing does this today

`.github/workflows/` contains `ci.yml` (tests, on pull requests) and `deploy.yml` (SSHes in
and runs `deploy.sh`). **Neither builds or pushes an image**, and `deploy.sh` builds locally
with `compose up -d --build`. So the entire pull-don't-build model has no producer until one
is added, and every consumer of it — `deploy.sh`'s pull, `restore.sh`'s VERSION `docker run`,
the manifest's `image` field — has nothing to read. This is B1 work, not an assumption.

- **A new `publish` job**, in `deploy.yml` ahead of the deploy step so the image provably
  exists before any box is told to pull it. Not a separate workflow: two workflows on the
  same trigger would race, and the deploy must be strictly downstream of the push.
- **Tags:** `:master` and `:sha-<short>`, both pushed every time, using
  `docker/build-push-action` with GitHub Actions layer caching.
- **Auth:** the job's own `GITHUB_TOKEN` with `permissions: packages: write`. No PAT needed
  for pushing.
- **The package stays private**, because the image contains the application source of a
  private repo. A public package would publish that source, which is not a trade this
  makes. The consequence is a real one and it is why credential 3 exists above: **each
  school box needs a GHCR read credential** — a fine-grained PAT with `read:packages`,
  stored as `LIBLI_GHCR_TOKEN` and used for a `docker login ghcr.io` before the pull.
  `deploy.sh` performs that login; `restore.sh` needs one before VERSION.
- ⚠️ **`docker/build-push-action` builds on the runner, not on the box** — which is the
  point. It removes the RAM spike that makes 4 GB a real floor from every school box at
  once, and it is what makes the sizing table in the hosting model honest.

A PAT expires. That is a silent, dated failure mode for every school at once, so its expiry
goes in the same calendar as the restore rehearsal.

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
3. **No `--delete` anywhere in `backup.sh`.** Neither mirror may use it: `media/` keeps
   deleted files on purpose, and `screenshots/` erases by an explicit `rm` of a computed
   list. *Mutant:* add `--delete` to either rsync → RED. This is the single guard
   standing between the RODO erasure path and a nightly job that deletes the whole
   screenshot history, so it is pinned as an absolute rather than per-mirror.
4. **The dump is verified before upload.** A `pg_restore --list` line appears between the
   `pg_dump` line and the `age` line. *Mutant:* remove it → RED.
5. **`set -euo pipefail`** is the first executable line of all three scripts (`deploy.sh`
   already has it; the guard stops it regressing), in the shape of
   `test_ssh_action_stops_on_the_first_failing_line`. *Mutant:* drop `pipefail` → RED.
6. **`restore.sh` loads the database before the app starts.** A qualified `up -d db`
   precedes the `pg_restore` line; no unqualified `up -d` precedes it. *Mutant:* replace
   `up -d db` with `up -d` → RED.
7. **Lock agreement.** `backup.sh`, `deploy.sh` **and `restore.sh`** name the same lock
   path; the compose
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
9. **All three scripts parse** (`bash -n`), matching the existing deploy guard.
10. **The publish job precedes the deploy step**, and both live in `deploy.yml`. Assert the
    build-push step appears before the `appleboy/ssh-action` step, and that `deploy.sh`
    performs a `docker login ghcr.io` before its `pull`. *Mutant:* reorder the jobs, or
    drop the login → RED. Without this a deploy can tell a box to pull a tag that does not
    exist yet, which fails on the box rather than in CI — the slowest possible place to
    find out.
11. **`--rotate-secrets` writes before it wipes.** In `restore.sh`, the secret-generation
    lines appear before the `compose down` line. *Mutant:* move them after → RED. This is
    the one ordering error that produces a database whose password nothing knows.
12. **CONFIRM proves the artifacts exist before it prompts.** In `restore.sh`, the
    existence check for `db/`/`env/`/`caddy/` appears before the confirmation read.
    *Mutant:* move the check after the prompt, or delete it → RED. Guards the one
    failure a never-pruned `manifest/` makes reachable.
13. **The checkout matches the image.** `restore.sh` compares its own `git rev-parse`
    against the resolved target tag and refuses on a mismatch. *Mutant:* delete the
    comparison → RED. Without it a stale checkout's compose file can contradict the
    image it starts, and the runbook's §3 clone is the step that makes that reachable.
14. **`--image-tag` is format-checked.** `restore.sh` refuses a tag not matching
    `^sha-[0-9a-f]{7,40}$` before VERSION runs. *Mutant:* accept any string → RED,
    because the checkout-sha comparison then has nothing well-formed to parse.
15. **Completeness is checked before the wipe, and the two checks differ.** In
    `restore.sh` the `refs/` diff appears before the `compose down` line.
    *Mutant:* delete the diff, or move it after `down` → RED. Also assert the
    asymmetry: a missing `db/`/`env/`/`caddy/` object exits non-zero, while a `refs/`
    gap alone reaches the confirmation prompt. *Mutant:* make a refs gap exit → RED,
    because that would make every dump old enough to have a legitimate gap
    unrestorable.
16. **`refs/` is written before either mirror step.** In `backup.sh`, the
    `list_referenced_files` line appears after the `pg_dump` line and before both the
    media rsync and the screenshot `rm`. *Mutant:* move it to the end of the script →
    RED. Also assert the erasure keep-set names `refs`, not just the live tree;
    *mutant:* drop `refs` from the union → RED. Together these pin the intra-run race
    that would otherwise let CONFIRM pass a dump whose screenshots were just erased.
17. **`--pre-cutover` disables ACME by the scheme, not by a `tls` directive.** Assert
    `restore.sh` writes `SITE_ADDRESS=http://` and `DJANGO_SECURE_SSL_REDIRECT=false`
    in that mode, and that the `Caddyfile` still contains no `tls` directive (so a
    future edit that hardcodes one is caught). *Mutant:* drop the scheme rewrite →
    RED, because the restore would then attempt ACME against DNS pointing elsewhere.
18. **No `--build` survives anywhere.** Assert `--build` appears in neither `deploy.sh` nor
    the `up` blocks of `docs/deployment.md` §3 and §8. *Mutant:* leave one behind → RED.
    This is the guard that catches the half-finished image switch, which would otherwise
    present as a box quietly building from source while everything else assumed it pulled.

`tests/test_list_referenced_files.py` — real unit tests, not textual: every file-bearing
field is covered (add a `FileField` to a model and the test should notice), blank fields are
skipped, and paths come out relative and forward-slashed.

### The rehearsal is part of the deliverable

B1 is not complete when the scripts exist. It is complete when a backup taken by
`backup.sh` has been restored by `restore.sh` onto a *fresh* box and this checklist passes:

- [ ] `pg_restore` completes with no errors
- [ ] referenced files fetched == referenced files listed
- [ ] the stack reaches healthy; `/healthz/` returns `"status": "ok"`
- [ ] the site answers on the restored hostname over TLS (`--live`), or over plain HTTP at
      `127.0.0.1` with a `Host:` header (`--pre-cutover`)
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

- **New `docs/backup-and-restore.md`** — the artifact, all three scripts, key custody, the
  **step-0 pre-flight** (§1-2, choose `<ts>`, pinned clone, credentials to tmpfs, invoke),
  the out-of-band input set, the four paths, both rotation checklists (compromise and
  handover), the single-file recovery procedure, and the rehearsal log. Separate from
  `docs/deployment.md`, which is already long; cross-linked from its §8.
- **`docs/deployment.md`** —
  - §1: install `age`; set the host clock to UTC; place the Storage Box key file at
    `/root/.ssh/libli_backup` mode 0600; `docker login ghcr.io` with `LIBLI_GHCR_TOKEN`.
  - §8's *One-time setup*: the `publish` job's GHCR permissions, and the fine-grained
    `read:packages` PAT each box needs — beside the three existing `SSH_*` secrets.
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
  `LIBLI_IMAGE_TAG`, `LIBLI_GHCR_TOKEN`, `LIBLI_BACKUP_AGE_RECIPIENT`,
  `LIBLI_BACKUP_SSH_HOST`, `LIBLI_BACKUP_SSH_USER`, **`LIBLI_BACKUP_SSH_KEY_PATH`** and
  `LIBLI_BACKUP_HEARTBEAT_URL`. All are mandatory; `backup.sh` checks each with `env_value`
  and exits non-zero naming the missing key, since a blank value must not silently produce
  a backup that goes nowhere.

  ⚠️ **`_PATH`, not the key material.** `env_value()` is
  `sed -n "s/^$1=//p" … | head -1` — it reads exactly one line, and every existing key in
  this file is single-line. An OpenSSH private key is a multi-line PEM block, so storing it
  inline would be silently truncated to its `-----BEGIN…` header: a config that parses,
  looks right, and cannot authenticate. So the env holds a **path**
  (`/root/.ssh/libli_backup`, mode 0600), and provisioning places the key file there as its
  own documented step in §1. Base64-encoding it into one line was the alternative and was
  rejected — it hides the key's shape from anyone reading the file and adds a decode step to
  two scripts to save one provisioning line.
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
  (the `MediaAsset.width` comment in `courses/models.py` records 232 video assets against a
  ~9 GB footprint). Note that
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
