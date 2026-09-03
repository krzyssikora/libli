# Backups and restore

Read this if a school's box has died, you are moving a school to new hardware, or you are
handing a school its own server. It assumes `docs/deployment.md` §1-2 are done (SSH
hardened, Docker installed, DNS pointed) and works from there — it does **not** repeat
provisioning.

Three scripts, all at the repo root, all taking the same `flock` on
`/var/lock/libli-deploy.lock` so a deploy, a backup and a restore never collide:

- `backup.sh` — runs nightly from cron (`15 2 * * *` UTC), on every school box.
- `restore.sh` — the one script behind all four recovery paths below. It does **not** ship
  pre-installed on a fresh box; see the pre-flight.
- `deploy.sh` — CD, covered in `docs/deployment.md` §8; mentioned here only where it shares
  the lock.

---

## 1. What is backed up, and what is not

### The artifact

Every night, `backup.sh` writes to a Hetzner Storage Box under `schools/<slug>/`:

```
schools/<slug>/
  db/<ts>.dump.age             pg_dump -Fc, encrypted. Dated, pruned.
  env/<ts>.env.age             .env.production, encrypted. Dated, pruned.
  screenshots/**.age           per-file mirror, encrypted, erased on deletion
  media/**                     per-file mirror, plain, pruned at 90 days
  refs/<ts>.txt                the files this dump references; the pre-WIPE completeness check
  media-missing.tsv            path -> first-missing date; drives the media prune
  caddy/<ts>.tar.age           caddy_data, encrypted
  manifest/<ts>.json           what this backup is. NEVER pruned — outlives everything else
  wal/                         reserved for future WAL archiving; nothing writes here yet
```

`<ts>` is `YYYY-MM-DDTHHMMSS` in UTC — seconds, not minutes, so a manual rehearsal run
alongside cron does not collide. A run whose `<ts>` already exists **aborts rather than
overwrites**.

`db/`, `env/` and `caddy/` follow the retention rule below and eventually get pruned;
`manifest/` never does. That means `manifest/` lists more restore points than are actually
restorable — see *The manifest lies about what's restorable* under §3.

### The seven volumes

Every volume `docker-compose.prod.yml` declares must appear in `backup.sh`'s
`VOLUME_CLASS` array with a reason — a guard in `tests/test_backup_wiring.py` derives the
volume list from the compose file and fails the suite if a new volume shows up unclassified.
That is what stops this table from silently rotting:

| Volume | What happens to it | Why |
|---|---|---|
| `pgdata` | Dumped (`pg_dump -Fc`), never mirrored | A filesystem copy of a running postgres data directory is not a consistent backup |
| `media` | Plain per-file mirror, pruned at 90 days (`MIRROR_PRUNE_DAYS`) | The whole of `MEDIA_ROOT` — course content and branding, the bulk of the bytes; stays verifiable without the key |
| `support_screenshots` | Encrypted per-file mirror, **erased on deletion** | Personal data — an `IssueReport.screenshot` may carry another pupil's grades; an erasure the backup silently undid would not be an erasure |
| `caddy_data` | Encrypted tarball (`tar` piped through `age`) | Holds the ACME account key and every certificate's private key; kept to spare Let's Encrypt's rate-limit budget on repeated restores, not because it's big — it's kilobytes |
| `caddy_config` | **Not backed up** | Autosaved by Caddy, regenerated from the mounted Caddyfile on first boot |
| `transfer_staging` | **Not backed up** | In-flight uploads only, swept at 6 hours |
| `upload_tmp` | **Not backed up** | Transient Django upload spill |

Encrypted: DB dump, `.env.production`, `support_screenshots`, `caddy_data` — pupil data,
every secret, and TLS private keys. Plain: `media/` — course content and branding.
Encryption is `age` in public-key mode: every school box holds only the **public**
recipient, so a stolen box can write backups it cannot itself read. The private half lives
in the password manager plus one offline copy, and is never at rest on any server — see the
pre-flight below for how it reaches a box only for the duration of a restore.

### The two mirrors differ on purpose

`media/` **omits `--delete`**. libli's element deletion has no orphan table and no audit
trail, so an append-only mirror is the first thing that makes a mis-click recoverable —
that is also what §4 (single-file recovery) relies on. Because an unbounded mirror can't be
squared with a published retention promise, `backup.sh` tracks *time since a file was first
observed missing* in `media-missing.tsv` and prunes anything missing for more than
`MIRROR_PRUNE_DAYS` (90) — **not** the file's own mtime, which `rsync` copies from the
source and never touches again, so keying the prune on it would delete a two-year-old,
untouched file on the very next nightly run after it was deleted.

`support_screenshots/` has **no age-based rule at all**: a screenshot leaves the mirror the
same night it leaves the live tree, by an explicit `rm` of a computed list — RODO erasure
wins over recoverability here, deliberately.

### The ransomware horizon is 10 days, not 30+12

Two different things protect two different threats, and conflating them overstates the
weaker one:

| Threat | What actually stops it | Horizon |
|---|---|---|
| A file or element deleted by mistake | The `media/` mirror (no `--delete`) | 90 days |
| A volume wiped, or the box lost entirely | The nightly artifact | 30 daily + 12 monthly |
| **An adversary holding the box's own backup credential** | **Storage Box snapshots only** (daily, taken by the main account — the school box's sub-account cannot touch them) | **10 days** |

A Storage Box sub-account can be scoped to a subdirectory but **cannot be made
append-only**. Someone holding the box's own credential can delete or overwrite the
school's whole directory directly — omitting `--delete` does nothing against that. So the
real ransomware recovery window is the snapshot count, ten days, not the retention numbers
above. If you're ever asked "how far back can we go after a compromise," the answer is ten
days, not thirteen months.

---

## 2. The pre-flight checklist

### The five things a restore needs that a server cannot hand you

A restore can't bootstrap itself from the box: the Storage Box credential the box normally
uses lives *inside* the encrypted `.env.production`, so it can't be used to fetch that same
file. Get all five of these from the password manager before you start — none of them come
from any server:

1. **The `age` private key.** The shared identity, in the password manager plus one offline
   copy. Losing it loses every school's backups — accepted deliberately.
2. **A Storage Box credential for restores** — `--ssh-host` / `--ssh-user`, plus its own SSH
   key. This is **deliberately not** the credential the school box's own
   `.env.production` holds: that one is exactly what's compromised in the scenario a
   restore is for. Treat it with the same care as the `age` key.
3. **A GHCR read PAT**, only if needed. Provisioning already runs `docker login ghcr.io`,
   and that persists in `~/.docker/config.json` across a restore's `compose down
   --volumes` (that command touches volumes, not the Docker config) — so on a normally
   provisioned box you won't need this. You *will* need it for: a box provisioned before the
   token existed, a PAT that has since expired or been revoked, or a bare-metal rebuild
   where §1 hasn't run yet. `restore.sh` tries the existing login first; if the pull fails
   it **exits 1** naming the image it could not pull, and you re-invoke it with
   `--ghcr-token-file <path>` — it does not stop and prompt. Like the other two
   credentials the PAT is passed as a **tmpfs path, never as the token itself**: a secret
   on the command line is readable from `ps` by anyone on the box and lands in your shell
   history. `--ghcr-token` is refused, with those instructions.
4. **The school slug** (`--slug`). Needed to build the remote path `schools/<slug>/...`
   before anything can be fetched — a box that has had only §1-2 has no config at all yet,
   so there is nowhere else to read it from.
5. **The target `<ts>`.** Chosen by reading `manifest/` (step 2 below). Because
   `manifest/` is never pruned, some entries there are metadata-only — `restore.sh` will
   refuse a pruned one before it asks you anything, naming which of `db/`, `env/` or
   `caddy/` is missing.

### Step 0, in order

This is the part that's easy to get backwards. **`restore.sh` is not on a freshly
provisioned box.** The runbook's own `git clone` is `docs/deployment.md` §3, and everything
a restore needs from the repo — `restore.sh` itself, `docker-compose.prod.yml` (which
`vol_path()`'s `libli_` prefix, the postgres major and the volume list all come from), and
the `env_value()` helper — is on the far side of that clone. On the disaster-recovery,
resize and provider-move paths the box has only had §1-2 done to it. Do these five steps in
this order:

1. **Runbook §1-2** on the target box: SSH hardened, Docker installed, `age` and `rsync`
   installed, the clock set to UTC, and the Storage Box key file placed. (This is
   provisioning, not restore — see `docs/deployment.md` §1. `rsync` is not in Ubuntu's
   minimal cloud image and every Storage Box listing and fetch below needs it.)

2. **From your own machine**, using your local copy of the restore SSH key, list what's
   restorable and pick a `<ts>`:

   ```bash
   chmod 600 ~/.ssh/libli_restore_key   # wherever you saved it from the password manager
   rsync --list-only -e "ssh -i ~/.ssh/libli_restore_key" \
     <storage-box-user>@<storage-box-host>:schools/<slug>/manifest/
   scp -i ~/.ssh/libli_restore_key \
     <storage-box-user>@<storage-box-host>:schools/<slug>/manifest/<ts>.json /tmp/manifest.json
   cat /tmp/manifest.json
   ```

   Read `image` and `git_sha` off the manifest — you need them for the next step. (A
   Storage Box only speaks sftp/rsync/scp/borg, so this is `scp`, not an interactive shell.)

3. **Clone the repo, pinned to a commit — never to `master`:**

   ```bash
   git clone <repo-url> /opt/libli && cd /opt/libli
   git checkout <sha>
   ```

   `<sha>` is the manifest's own `git_sha` **by default** — restore the version the dump
   came from. Pass `--image-tag sha-<full-sha>` to `restore.sh` later only if you deliberately
   want to bring an *older* dump up on a *newer* image, in which case checkout the commit
   behind that tag instead. Why pinned rather than floating: the compose file you check out
   governs the postgres major, the volume names and the healthcheck, so a checkout newer
   than the image you start can disagree with it. `restore.sh` itself double-checks this —
   it compares its own `git rev-parse HEAD` against the image tag it resolves and refuses
   if they differ, naming both — but that refusal happens minutes into the run; cloning the
   right commit now avoids it.

4. **Deliver the two credentials to tmpfs on the target box** — never to disk:

   ```bash
   ssh <box> 'cat > /dev/shm/libli-restore.key' < ~/.age/libli.key
   ssh <box> 'cat > /dev/shm/libli-restore-ssh.key' < ~/.ssh/libli_restore_key
   ssh <box> 'chmod 600 /dev/shm/libli-restore.key /dev/shm/libli-restore-ssh.key'
   ```

   That redirection creates the files at **0644**, and `ssh` refuses to use a private key
   that permissive — hence the third line. `restore.sh` also applies the `chmod` itself,
   immediately after checking both files are present, so a delivery done some other way is
   covered too; the line above is here because a runbook that leaves a key world-readable
   on a shared box is wrong even when the script repairs it.

   If you also need the GHCR PAT (input 3 above), deliver it the same way and pass the
   path:

   ```bash
   ssh <box> 'cat > /dev/shm/libli-ghcr.token' < <your local copy>
   ssh <box> 'chmod 600 /dev/shm/libli-ghcr.token'
   # then add: --ghcr-token-file /dev/shm/libli-ghcr.token
   ```

   `restore.sh` refuses to start if either of the two mandatory credentials is absent, and
   installs traps on `EXIT`, `INT`, `TERM` and `HUP` that `shred` both on every exit path,
   success or failure. `EXIT` alone would not survive the box being rebooted or the run
   being `kill`ed mid-restore, which is exactly when a key left in `/dev/shm` matters. The
   GHCR token file is yours to remove — the script never touches a path you chose.

5. **Invoke it** (§3 below has the full flag set per path).

---

## 3. Restoring

Base invocation:

```bash
bash /opt/libli/restore.sh \
  --slug <slug> \
  --ts <ts> \
  --ssh-host <storage-box-host> \
  --ssh-user <storage-box-user> \
  [--image-tag sha-<full-sha>] \
  [--ghcr-token-file <path>] \
  [--pre-cutover] \
  [--rotate-secrets]
```

`--live` is the default and needs no flag. `--ghcr-token-file <path>` joins the list only
after a run has already failed at `docker pull` (input 3 above) — the script tries the
box's existing login first and exits 1 telling you to re-invoke, rather than prompting.

⚠️ **`--live` means DNS already points at this box.** It's the ordinary disaster-recovery
case — restore onto the same hostname the site already answers on. It is **not** the second
half of a two-phase cutover; see *Cutting over after `--pre-cutover`* below for why a resize
or provider move does not finish with a second `restore.sh --live` run.

The script runs fifteen named steps — LOCK, CREDENTIALS, CONFIRM, IDENTITY, VERSION, ENV,
DUMP, **WIPE**, MATERIALISE, DB UP, LOAD, FILES, APP UP, VERIFY, HANDOFF — all of them the
script's own work, none a manual step. Four things about that sequence are worth knowing
before you type the confirmation slug:

- **CONFIRM proves the artifact exists before it asks you anything.** It hard-refuses if
  `db/`, `env/` or `caddy/` for your `<ts>` are missing (no degraded mode — there's nothing
  to restore without them). It then diffs `refs/<ts>.txt` against the mirror and **prints**
  any gap, grouped by how serious it is (harmless derivatives, expected-old screenshots,
  or unrepairable missing originals) — but does not refuse on it, because an old dump
  legitimately outliving some of its media is normal. Typing the school slug is what
  accepts that printed gap; anything beyond it that turns up missing later is a genuine
  fault and fails the run.
- **DUMP happens before WIPE, and that is deliberate.** The dump is fetched from the
  Storage Box and decrypted *before* anything is destroyed, so a network fault, a truncated
  artifact or an `age` key that does not match this school's history all fail while the box
  is still intact and still serving. (The `.env.production` artifact is handled before WIPE
  for the same reason.) The decrypted dump lives in the script's temp directory, which the
  traps remove on every exit path — it is plaintext pupil data and must not outlive the run.
- **WIPE (`compose down --volumes`) is the point of no return**, and it takes all seven
  volumes, not just `pgdata` — that's what guarantees the restored `media/` contains
  *exactly* the referenced set rather than also resurrecting whatever the old box's tree
  held that nothing in the fresh database points at (Caddy would serve that file at its URL
  regardless). The cost is a full media re-fetch even on a same-box restore — for a school
  the size of the matematyka import, roughly 9 GB, over the fast, unmetered Storage-Box-to-box
  link, so it's slow rather than expensive.
- **If FILES fails after WIPE, you are not stranded.** The nightly artifact from before you
  started this restore is still on the Storage Box, and its own mirror still holds
  everything *it* references. Re-running against the newest `<ts>` puts the box back where
  it was this morning.

### The manifest lies about what's restorable

`manifest/` is kept forever on purpose (a few hundred bytes, and it feeds a future annual
storage report), but `db/`, `env/` and `caddy/` are pruned per the retention rule. So
`manifest/` will show you `<ts>` entries whose actual artifact is gone. CONFIRM's
existence check exists precisely to catch this before you've typed anything — if it refuses,
pick a `<ts>` inside the 30-day daily window or a monthly survivor instead.

### The four paths

| Path | Flags | Notes |
|---|---|---|
| **Restore** (disaster recovery, box lost or rebuilt, same hostname) | `--live` (default), usually no `--image-tag` | With no `--image-tag`, VERSION targets the manifest's own `image` — the check is a tautology here and is printed as skipped, which is honest about what it did and did not verify. |
| **Resize** (bigger/smaller box, same provider, same eventual hostname) | `--pre-cutover` **once** | Boot the new box through §1-2, run the pre-flight, then `restore.sh --pre-cutover`. That mode rewrites `SITE_ADDRESS=http://<hostname>` and sets `DJANGO_SECURE_SSL_REDIRECT=false`, so Caddy serves plain HTTP and never attempts ACME while DNS still points at the old box. Verify with `curl` against `127.0.0.1` and an explicit `Host:` header. Cut over with the small manual procedure below — **not** a second `restore.sh` run. |
| **Provider move** (leaving Hetzner) | identical to Resize | Nothing in the artifact is Hetzner-specific; the destination box just needs the same pre-flight. |
| **Handover** (school takes over ownership of its box) | none of `restore.sh`'s flags | Not a fifth mechanism, but not just paperwork either — see §6. It's a key *rotation* (re-encrypting the school's current artifact under a keypair only the school holds) plus a set of `.env.production` edits made in place, not a `restore.sh` run. |

`--rotate-secrets` is a **modifier**, addable to any of the four paths above when the
restore is itself a response to a compromise — see §5. It is never inferred: nothing about
a manifest or a box can tell the script whether this is a compromise restore, so the
operator states it explicitly.

### Cutting over after `--pre-cutover`

**Do not re-run `restore.sh` to cut over.** `restore.sh` is deliberately straight-line —
there is no partial-run mode — so a second invocation repeats all fifteen steps, including
WIPE and a full media re-fetch. That would destroy the restore you just verified and rebuild
it from scratch, and if that second pass fails partway (a transient network fault, a Storage
Box hiccup) you are left worse off than before you started. The ~9 GB re-transfer is the
smaller half of that cost; the wipe is the real one.

Cutover only ever touches the two keys `--pre-cutover` changed, with no wipe and no
re-fetch:

**Before running `restore.sh --pre-cutover`, capture the real `SITE_ADDRESS`.** ENV
overwrites it on disk to `http://<hostname>`, so the original value has to be read from the
artifact itself, before that happens — from the same age identity already on tmpfs from
pre-flight step 4:

```bash
scp -i /dev/shm/libli-restore-ssh.key -o StrictHostKeyChecking=accept-new \
  <storage-box-user>@<storage-box-host>:schools/<slug>/env/<ts>.env.age /dev/shm/env-preview.age
age -d -i /dev/shm/libli-restore.key -o /dev/shm/env-preview /dev/shm/env-preview.age
grep '^SITE_ADDRESS=' /dev/shm/env-preview      # write this value down — you'll need it below
rm -f /dev/shm/env-preview /dev/shm/env-preview.age
```

Then run `restore.sh --pre-cutover` and verify against `127.0.0.1` as the table above
describes. When DNS has actually been repointed and you're ready to go live:

```bash
# 1. Repoint DNS at the new box and wait for it to resolve there.
getent hosts <hostname>          # must return the NEW box's address

# 2. Undo the two keys --pre-cutover changed.
cd /opt/libli
sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=<the value you recorded above>|" .env.production
sed -i '/^DJANGO_SECURE_SSL_REDIRECT=false$/d' .env.production

# 3. Recreate so Caddy picks up the real address and requests a certificate.
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --wait

# 4. Now run the post-cutover checks against the public name.
curl -fsS https://<hostname>/healthz/ | grep -q '"status": *"ok"'
```

Step 2's delete is safe rather than lossy: `DJANGO_SECURE_SSL_REDIRECT` isn't normally set
in `.env.production` at all (it isn't one of the keys `.env.production.example` ships), and
`config/settings/production.py` defaults it to `true` when absent — so deleting the line
`--pre-cutover` added restores the same behaviour the box would have without ever having
seen that flag.

---

## 4. Recovering a single file

This is the everyday case — someone deleted a course image or a media element by mistake —
and it is **not** a `restore.sh` operation at all. It's justified by the one property that
makes `media/` different from every other mirror: `backup.sh` never passes `--delete` on
it, so a file survives on the Storage Box for up to 90 days after its row is gone from the
database (libli has no orphan table or undo for a hard element delete, so this mirror *is*
the undo).

Recovery is a plain `rsync` pull of one path, from the box's own already-configured backup
credential — no `age` decryption needed, because `media/` is stored plain:

```bash
cd /opt/libli
SSH_HOST="$(sed -n 's/^LIBLI_BACKUP_SSH_HOST=//p' .env.production)"
SSH_USER="$(sed -n 's/^LIBLI_BACKUP_SSH_USER=//p' .env.production)"
SSH_KEY="$(sed -n 's/^LIBLI_BACKUP_SSH_KEY_PATH=//p' .env.production)"
SLUG="$(sed -n 's/^LIBLI_SCHOOL_SLUG=//p' .env.production)"

rsync -a -e "ssh -i $SSH_KEY" \
  "$SSH_USER@$SSH_HOST:schools/$SLUG/media/<path-relative-to-MEDIA_ROOT>" \
  "$(docker volume inspect --format '{{.Mountpoint}}' libli_media)/<path-relative-to-MEDIA_ROOT>"
```

The path is whatever `MediaAsset.file` (or `Institution.logo`/`favicon`) points at in the
database — paths in the mirror are exact copies of `MEDIA_ROOT`, never renamed, because
libli's filenames aren't content-addressed and a rename would break the `FileField` that
points at them.

---

## 5. Rotation after a compromise

`.env.production` is restored **verbatim** at ENV, so a plain restore brings back every
credential the adversary already had — including the ones the box uses for its own nightly
backups. Without an explicit rotation step, the rebuilt box would quietly resume using a
credential someone else is known to hold, undoing the entire reason for the restore
credential (§2 input 2) being a different one in the first place.

Add `--rotate-secrets` to whichever of the four paths you're running. Three groups, by
*when* each can happen:

**At `.env.production`, done by the script — mandatory, because later is too late.**

- **`POSTGRES_PASSWORD` must be set before WIPE.** Postgres only accepts a new password
  while it's initialising an *empty* data directory, so `--rotate-secrets` writes the new
  value into `.env.production` at ENV, several steps before WIPE destroys `pgdata` and DB
  UP recreates it. Rotate it any later and the database keeps the old password while the
  app tries to use the new one — the exact footgun WIPE exists to avoid, reintroduced.
- **`DJANGO_SECRET_KEY`** — no timing constraint of its own, but it's the same file in the
  same pass. Rotating it logs everyone out and invalidates outstanding reset/invitation
  links, which on a compromise restore is the desired outcome.
- Both are printed once, to the terminal, with the instruction to save them to the
  password manager *immediately* — that echo is the only channel available, since at that
  moment they exist nowhere else: not in the artifact, not in any backup, only on a box
  that has just been rebuilt.

**After the restore, by a human, in the admin UI** — these live in the database, so they
survive the restore intact and `restore.sh` cannot touch them. HANDOFF prints them as
outstanding and exits non-zero until they're done:

- `SocialApp.secret` (the SSO client secret)
- `WebhookEndpoint.secret`

**Out of band, by a human, at the provider — before the box's first nightly run:**

- A **new Storage Box sub-account and key**, with the old one **revoked** at Hetzner (not
  merely stopped using), and `LIBLI_BACKUP_SSH_KEY_PATH`'s key file replaced on the box.
- A **new `LIBLI_GHCR_TOKEN`**, with the old PAT revoked at GitHub. Revoke the old PAT
  *before* the next restore, not after: the box's already-stored `docker login` keeps
  working right up until the old PAT actually dies, which is why out-of-band input 3
  (§2) exists at all — it's the fallback for the moment it stops.
- **`DJANGO_EMAIL_HOST_PASSWORD`**, reissued by the mail provider.
- The **shared `age` recipient**, only if the private key itself is suspect — that's a
  fleet-wide decision (it means re-encrypting every school's history), not a per-school
  reflex.

`restore.sh` cannot do any of the last two groups and does not pretend to: HANDOFF names
what's still outstanding and the run **exits non-zero** while anything remains, so a restore
that leaves known-compromised credentials in place can never read as a clean, finished run.

---

## 6. Handover

Handing a school the shared `age` private key would let it decrypt **every other school's**
backups — the single shared keypair was chosen for the routine case, and handover is its
one deliberate exception. The rule is **rotation, never disclosure**:

1. The school generates its **own** `age` keypair. Krzysztof never holds the private half.
2. Krzysztof re-encrypts **only that school's current artifact** under the school's new
   public key and delivers it. The school's older history is **not** transferred — it stays
   under the shared key and is deleted on the normal retention schedule. State this in the
   contract up front, not at handover time.
3. The Storage Box sub-account is replaced by a destination the school owns; the shared
   Storage Box credential is never disclosed either.
4. On the school's own box, these `.env.production` values change:

   | Key | Action |
   |---|---|
   | `DJANGO_SECRET_KEY` | Rotate — it appears in artifacts encrypted under the shared key |
   | `POSTGRES_PASSWORD` | Rotate |
   | `DJANGO_EMAIL_*` | Theirs now |
   | `LIBLI_BACKUP_*` | Their own destination and their own `age` recipient |
   | `SITE_ADDRESS`, `DJANGO_SITE_DOMAIN`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Only if the hostname changes |

None of this runs `restore.sh` — the box being handed over already holds its own data, so
there's nothing to wipe or reload. It's an `age`-encrypt of the current artifact plus a set
of edits to the file already on the box. Still, it's not something to reconstruct from
memory under pressure; use this checklist.

---

## 7. Rehearsal log

**This work is not complete when the scripts exist.** It is complete once a backup taken by
`backup.sh` has been restored by `restore.sh` onto a *fresh* box and every item below
passes. The textual guards in `tests/test_backup_wiring.py` only prove the wiring hasn't
drifted since the last rehearsal — they do not prove a restore actually works. Only running
one does.

**Pass checklist** (all nine, every rehearsal):

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

Record every rehearsal here, dated, whether it passed cleanly or not — a note of what went
wrong is worth more than a silent gap in the log. Recurrence is a **recurring quarterly
calendar entry** naming this document; a rehearsal without that mechanism becomes a one-off.

| Date | `<ts>` restored | Box | Outcome | Surprises |
|---|---|---|---|---|
| _(none yet — the first rehearsal is required before this work is considered complete; see the branch's PR checklist)_ | | | | |
