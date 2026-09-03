#!/usr/bin/env bash
set -euo pipefail
# libli nightly backup.
#
# STRAIGHT-LINE ON PURPOSE. Several guards in tests/test_backup_wiring.py are
# source-order assertions (the dump must precede the media mirror; refs must
# precede both mirrors). Refactoring these steps into functions would break them
# or, worse, pass them for the wrong reason. Keep the ordered steps inline.
#
# `set -euo pipefail` above is the first executable line and pipefail is
# load-bearing: without it a pg_dump that dies part-way while age exits 0
# produces a short, well-formed, encrypted file, a written manifest and a GREEN
# heartbeat -- the exact failure the verification exists to catch.

APP_DIR=/opt/libli
cd "$APP_DIR"

# Published in docs/public/privacy.md AND privacy.pl.md; a guard ties them to
# these three numbers. Changing one without the notices fails the suite.
# 30 days is a DETECTION window (a school holiday is two weeks); 12 months is the
# academic year; ~13 months total is the RODO ceiling and bounds a pupil's
# erasure tail. Storage cost plays no part -- the dump is small because media is
# not in Postgres.
RETAIN_DAILY_DAYS=30
RETAIN_MONTHLY_MONTHS=12
MIRROR_PRUNE_DAYS=90

# Shared with deploy.sh and restore.sh. backup.sh SKIPS when the lock is held:
# tonight's backup is the cheapest of the three to lose, and the heartbeat's
# absence alerts if it keeps happening.
LOCK_FILE=/var/lock/libli-deploy.lock

# Every volume in docker-compose.prod.yml must appear below with a reason, or
# test_every_compose_volume_is_classified goes red. Derived from the compose
# file, never hand-maintained beside it.
#
# pgdata: captured by pg_dump, never mirrored -- a filesystem copy of a running
#   postgres data directory is not a consistent backup.
# media: the whole of MEDIA_ROOT; plain mirror, pruned at MIRROR_PRUNE_DAYS.
# support_screenshots: personal data; encrypted per-file mirror, erased on deletion.
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

compose() {
  docker compose -f docker-compose.prod.yml --env-file .env.production "$@"
}

# `sed -n s///p` rather than grep so a missing key yields an empty string instead
# of exit 1, which under `set -e` would abort over a value only used for
# verification. Same helper shape as deploy.sh.
env_value() {
  sed -n "s/^$1=//p" .env.production | head -1
}

# media, support_screenshots and caddy_data are NAMED DOCKER VOLUMES, not bind
# mounts -- there is no /opt/libli/media on the host, so a bare `rsync media/`
# cannot work. The libli_ prefix is Docker's <project>_<volume> convention and
# comes from `name: libli` at the top of the compose file, which a guard pins.
vol_path() {
  docker volume inspect --format '{{.Mountpoint}}' "libli_$1"
}

# rsync exits 24 ("some files vanished before they could be transferred")
# routinely on a live media tree. Under `set -e` that would abort before the
# heartbeat and alert on a backup that is fine -- and repeated false alerts are
# how a real one gets ignored.
rsync_ok() {
  local code=0
  rsync "$@" || code=$?
  [ "$code" -eq 0 ] || [ "$code" -eq 24 ]
}

# grep exits 1 when it SELECTS NO LINES, which under `set -euo pipefail` is
# fatal -- and "no lines" is the ordinary case here: most schools have never
# had an IssueReport.screenshot, so the remote listing is empty every night.
# Aborting there would leave the run without a manifest (the artifact then has
# no restorable <ts> at all), without a prune, and without a heartbeat.
# Only status 1 is absorbed: a REAL grep failure (status 2 -- an unreadable
# file, a bad pattern) still returns non-zero and still aborts the run, so this
# tolerates the empty result without tolerating a fault.
grep_any() {
  grep "$@" || [ $? -eq 1 ]
}

require_env() {
  local value
  value="$(env_value "$1")"
  if [ -z "$value" ]; then
    echo "!! $1 is unset in .env.production; refusing to back up nowhere" >&2
    exit 1
  fi
  printf '%s' "$value"
}

# --- 1. lock -------------------------------------------------------------
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "==> a deploy or restore holds the lock; skipping tonight"
  exit 0
fi

SLUG="$(require_env LIBLI_SCHOOL_SLUG)"
RECIPIENT="$(require_env LIBLI_BACKUP_AGE_RECIPIENT)"
SSH_HOST="$(require_env LIBLI_BACKUP_SSH_HOST)"
SSH_USER="$(require_env LIBLI_BACKUP_SSH_USER)"
SSH_KEY="$(require_env LIBLI_BACKUP_SSH_KEY_PATH)"
HEARTBEAT="$(require_env LIBLI_BACKUP_HEARTBEAT_URL)"

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new"
REMOTE="$SSH_USER@$SSH_HOST"
BASE="schools/$SLUG"
TS="$(date -u +%Y-%m-%dT%H%M%S)"

# ⚠️ A Hetzner Storage Box is NOT a general-purpose shell. There is no awk, no
# GNU `date -d`, no mktemp, no loops -- only a restricted set plus sftp/rsync/
# scp/borg. So EVERY computation happens here on the school box, and the remote
# side only ever lists, transfers and deletes. Task 0 verified exactly what the
# endpoint accepts before any of this was written. Do not reintroduce
# `ssh $REMOTE "<script>"`: it works on your laptop and fails on the target.
#
# -8 (--8-bit-output) is MANDATORY under cron. rsync escapes bytes that are
# non-printable IN THE CURRENT LOCALE as \#303\#243, and cron runs in the C
# locale where EVERY high byte qualifies. Django keeps unicode word characters
# in an uploaded filename, so on a Polish maths platform `ćwiczenie_1.png` is
# entirely ordinary -- and escaped it would never match the raw bytes `find`
# reports for the same file, so it would be recorded gone every single night
# and, at a restore, reported to the operator as unrepairable content loss
# while sitting intact on the mirror.
#
# The name is cut off the listing by ONE sub(), not by blanking $1..$4: field
# assignment rebuilds $0 with OFS, which collapses every run of whitespace
# INSIDE the filename to a single space and strips leading ones. The listing is
# `perms <pad>size date time name` and the separator before the name is exactly
# one space, so everything after it survives verbatim.
remote_ls() {  # $1 = subdirectory under $BASE; prints file paths relative to it
  rsync --list-only -8 -r -e "ssh $SSH_OPTS" "$REMOTE:$BASE/$1/" 2>/dev/null \
    | awk '$1 !~ /^d/ { sub(/^[^ ]+ +[^ ]+ [^ ]+ [^ ]+ /, ""); print }'
}

# Targets the ACCOUNT ROOT and creates the parents itself. sftp cd's into its
# target at startup, so aiming this at "$REMOTE:$BASE/" fails before it runs a
# single mkdir on a Storage Box where schools/<slug>/ does not exist yet -- the
# `|| true` swallows that, and the very first backup a school ever takes then
# dies at the first scp with nowhere to put anything.
#
# Every line carries sftp's `-` prefix, which means "ignore this command's
# failure and carry on". mkdir on an existing directory IS the ordinary case
# from the second night onward, and without the prefix sftp stops at the first
# such failure -- so on a box where schools/ exists but schools/<slug>/ does
# not, the children would never be created.
remote_mkdir() {
  {
    printf '%s\n' "-mkdir schools" "-mkdir $BASE"
    for dir in "$@"; do
      printf '%s\n' "-mkdir $BASE/$dir"
    done
  } | sftp -b - $SSH_OPTS "$REMOTE:" > /dev/null 2>&1 || true
}

remote_rm() {  # reads $BASE-relative paths on stdin
  local batch
  batch="$(mktemp)"
  sed 's|^|rm |' > "$batch"
  if [ -s "$batch" ]; then
    sftp -b "$batch" $SSH_OPTS "$REMOTE:$BASE/" > /dev/null
  fi
  rm -f "$batch"
}

remote_exists() {  # $1 = $BASE-relative path
  printf 'ls %s\n' "$1" | sftp -b - $SSH_OPTS "$REMOTE:$BASE/" > /dev/null 2>&1
}

STAGING="$(mktemp -d)"
DUMP_TMP="$(mktemp)"
# EXIT ALONE IS NOT ENOUGH. Bash does not run an EXIT trap when the shell is
# killed by an untrapped SIGTERM -- a reboot, a `systemctl stop`, a plain
# `kill` -- which would leave the ENTIRE PUPIL DATABASE in plaintext in
# $DUMP_TMP under /tmp. The signal handler cleans up and then exits rather than
# only cleaning up: a bare handler returns control to the interrupted command
# and the run would carry on with its own staging directory deleted.
cleanup() { rm -rf "$STAGING" "$DUMP_TMP"; }
trap cleanup EXIT
trap 'cleanup; exit 1' INT TERM HUP

# Spelled out, not `mkdir -p $BASE/{db,env,...}`: brace expansion is a bash
# extension and the remote is not bash. Unexpanded it would create ONE directory
# literally named "{db,env,caddy,...}" and every later path would miss.
remote_mkdir db env caddy refs manifest media screenshots

# --- 2. never overwrite an existing timestamp ----------------------------
if remote_exists "db/$TS.dump.age"; then
  echo "!! $BASE/db/$TS.dump.age already exists; refusing to overwrite" >&2
  exit 1
fi

# --- 3. informational counts --------------------------------------------
# row_counts is INFORMATIONAL: it is read before the dump, so rows arrive in
# between and a pass/fail gate would go red on healthy backups. The migration
# set does NOT drift in seconds (the lock excludes a concurrent deploy), so it
# IS an exact gate, used by restore.sh.
PGUSER_VALUE="$(env_value POSTGRES_USER)"
PGDB_VALUE="$(env_value POSTGRES_DB)"
ROW_COUNTS="$(compose exec -T db psql -U "$PGUSER_VALUE" -d "$PGDB_VALUE" -At -F, -c "
  SELECT relname, n_live_tup FROM pg_stat_user_tables
  WHERE relname NOT IN ('auth_group','auth_permission','django_migrations','django_site')
  ORDER BY relname;")"
MIGRATIONS="$(compose exec -T db psql -U "$PGUSER_VALUE" -d "$PGDB_VALUE" -At -F. -c "
  SELECT app, name FROM django_migrations ORDER BY app, name;")"

# --- 4. dump -------------------------------------------------------------
# A compose exec, not a host command: there is no postgres client on the host.
# -T is load-bearing twice -- cron has no TTY, and a pty would corrupt the
# binary -Fc stream.
#
# NO `-e PGPASSWORD=...`. That would put the database password on `docker`'s
# own argv, where any user on the box can read it out of `ps` for as long as
# the dump runs -- and it buys nothing: this is a UNIX-SOCKET connection inside
# the container, and the postgres image's initdb writes `local all all trust`.
# The row_counts and migration queries above, the truncation detector below and
# the compose healthcheck all already connect with -U and no password.
compose exec -T db pg_dump -U "$PGUSER_VALUE" -Fc "$PGDB_VALUE" > "$DUMP_TMP"

# --- 5. refs, IMMEDIATELY ------------------------------------------------
# Must describe the database the DUMP captured. Written at the end of the run it
# would be read AFTER the screenshot erasure below and could agree with a mirror
# that same run just erased from, while the dump still referenced the file.
# `exec`, not `run --rm`: the app container IS up during a backup.
compose exec -T app /app/.venv/bin/python manage.py list_referenced_files > "$STAGING/refs.txt"
scp $SSH_OPTS "$STAGING/refs.txt" "$REMOTE:$BASE/refs/$TS.txt"

# --- 6. truncation detector ---------------------------------------------
# A truncated -Fc archive fails to list. Cheap, and it is why row_counts does
# not have to carry that weight.
compose exec -T db pg_restore --list < "$DUMP_TMP" > /dev/null

# --- 7. upload the dump --------------------------------------------------
# Public-key mode: this box holds only the recipient, so it writes a backup it
# cannot read. A stolen box yields no pupil data and no DJANGO_SECRET_KEY.
age -r "$RECIPIENT" -o "$STAGING/db.age" "$DUMP_TMP"
scp $SSH_OPTS "$STAGING/db.age" "$REMOTE:$BASE/db/$TS.dump.age"
rm -f "$DUMP_TMP"

# --- 8. upload the env ---------------------------------------------------
# The artifact's third component. Two secrets live in the DATABASE (SocialApp
# and WebhookEndpoint), three live only here -- a restore needs both halves.
age -r "$RECIPIENT" -o "$STAGING/env.age" .env.production
scp $SSH_OPTS "$STAGING/env.age" "$REMOTE:$BASE/env/$TS.env.age"

# --- 9. mirror media (NO --delete) ---------------------------------------
# Append-only so a hard-deleted element's file survives its row: element
# deletion in libli has no orphan table and no audit trail. Path-faithful,
# because MediaAsset filenames are not content-addressed and a rename breaks
# every FileField in the database.
MEDIA_DIR="$(vol_path media)"
rsync_ok -a -e "ssh $SSH_OPTS" "$MEDIA_DIR/" "$REMOTE:$BASE/media/"

# --- 10. screenshots: upload E\R, then erase R\(E u refs) ----------------
# UPLOAD AND ERASURE ARE TWO OPERATIONS. `rsync --delete` from a staging dir
# holding only tonight's new files would delete the ENTIRE screenshot history
# every night: --delete removes destination files absent from the SOURCE list,
# and --ignore-existing only suppresses re-transfer -- it exempts nothing from
# deletion.
SHOTS_DIR="$(vol_path support_screenshots)"
remote_ls screenshots | grep_any '\.age$' | sort > "$STAGING/remote.txt"
(cd "$SHOTS_DIR" && find . -type f | sed 's|^\./||') | sed 's|$|.age|' \
  | sort > "$STAGING/expected.txt"

# Upload set: expected minus remote. Names are immutable
# (screenshots/<YYYY>/<MM>/<uuid4>.<ext>), so a name already on the remote never
# needs re-encrypting.
mkdir -p "$STAGING/shots"
comm -23 "$STAGING/expected.txt" "$STAGING/remote.txt" | while read -r name; do
  src="$SHOTS_DIR/${name%.age}"
  [ -f "$src" ] || continue
  mkdir -p "$STAGING/shots/$(dirname "$name")"
  age -r "$RECIPIENT" -o "$STAGING/shots/$name" "$src"
done
rsync_ok -a -e "ssh $SSH_OPTS" "$STAGING/shots/" "$REMOTE:$BASE/screenshots/"

# Erase set: remote minus (expected union tonight's refs). The refs union closes
# an intra-run race -- a screenshot whose row was deleted after the dump was
# spooled is still referenced BY that dump, so erasing it here would let CONFIRM
# see no discrepancy while the restore would fail after WIPE.
awk -F'\t' '$1 == "support_screenshots" { print $2 ".age" }' "$STAGING/refs.txt" \
  | sort > "$STAGING/refs_shots.txt"
sort -u "$STAGING/expected.txt" "$STAGING/refs_shots.txt" > "$STAGING/keep_set.txt"
comm -23 "$STAGING/remote.txt" "$STAGING/keep_set.txt" > "$STAGING/erase.txt"
if [ -s "$STAGING/erase.txt" ]; then
  sed 's|^|screenshots/|' "$STAGING/erase.txt" | remote_rm
fi

# --- 11. caddy_data ------------------------------------------------------
# ACME account key and every certificate's private key -- encrypted for the same
# "every secret" reason as the dump. Kilobytes; kept to spare Let's Encrypt
# rate-limit budget on repeated restores.
tar -C "$(vol_path caddy_data)" -cf - . | age -r "$RECIPIENT" -o "$STAGING/caddy.age"
scp $SSH_OPTS "$STAGING/caddy.age" "$REMOTE:$BASE/caddy/$TS.tar.age"

# --- 12. media-missing.tsv and the manifest ------------------------------
# The prune CANNOT key on a file's own mtime: rsync preserves the SOURCE mtime
# and never touches it again once the source is gone, so a file uploaded two
# years ago and deleted today is already "older than 90 days" and would be
# pruned on the NEXT run. Track time since FIRST OBSERVED MISSING instead.
remote_ls media | sort > "$STAGING/remote_media.txt"
(cd "$MEDIA_DIR" && find . -type f | sed 's|^\./||') | sort > "$STAGING/live_media.txt"
scp $SSH_OPTS "$REMOTE:$BASE/media-missing.tsv" "$STAGING/missing.tsv" 2>/dev/null \
  || : > "$STAGING/missing.tsv"
TODAY="$(date -u +%Y-%m-%d)"
comm -23 "$STAGING/remote_media.txt" "$STAGING/live_media.txt" > "$STAGING/gone.txt"
# FILENAME == ARGV[1], NOT the usual `NR == FNR`. That idiom identifies the
# first file by "no records read yet", which is exactly wrong when the first
# file is EMPTY: on the very first run missing.tsv has no records, NR stays 0,
# so every line of gone.txt satisfies NR == FNR, is swallowed into the seen-map
# and nothing is printed. missing.tsv is then a fixed point at empty forever --
# no path ever gets a first-missing date, so the MIRROR_PRUNE_DAYS deletion
# below never has a row to act on and docs/public/privacy.md's published "and
# are then deleted too" is never performed. tests/test_backup_wiring.py runs
# this exact program against a two-file fixture, empty first file included.
awk -F'\t' -v today="$TODAY" '
  FILENAME == ARGV[1] { seen[$1] = $2; next }
  { print $1 "\t" (($1 in seen) ? seen[$1] : today) }
' "$STAGING/missing.tsv" "$STAGING/gone.txt" > "$STAGING/missing.new"
scp $SSH_OPTS "$STAGING/missing.new" "$REMOTE:$BASE/media-missing.tsv"

MEDIA_FILES="$(wc -l < "$STAGING/live_media.txt")"
MEDIA_BYTES="$(du -sb "$MEDIA_DIR" | cut -f1)"
SHOT_FILES="$(wc -l < "$STAGING/expected.txt")"
SHOT_BYTES="$(du -sb "$SHOTS_DIR" | cut -f1)"
{
  printf '{\n'
  printf '  "schema": 1,\n'
  printf '  "school": "%s",\n' "$SLUG"
  printf '  "taken_at": "%sZ",\n' "$(date -u +%Y-%m-%dT%H:%M:%S)"
  printf '  "image": "ghcr.io/krzyssikora/libli:%s",\n' "$(env_value LIBLI_IMAGE_TAG)"
  printf '  "git_sha": "%s",\n' "$(git rev-parse HEAD)"
  printf '  "postgres_major": %s,\n' "$(compose exec -T db psql -U "$PGUSER_VALUE" -At -c 'SHOW server_version' | cut -d. -f1)"
  # NOT `paste -sd'","'`: GNU paste treats a multi-character -d as a CYCLE of
  # single-character delimiters, so A B C D joins to  A"B,C"D  -- malformed
  # JSON, which restore.sh then parses into garbage tokens and the
  # migration-containment check silently stops gating anything. Verified by
  # hand. Same awk shape as row_counts below.
  printf '  "migrations": [%s],\n' "$(echo "$MIGRATIONS" | awk '{printf "%s\"%s\"", (NR>1?",":""), $0}')"
  printf '  "row_counts": {%s},\n' "$(echo "$ROW_COUNTS" | awk -F, '{printf "%s\"%s\":%s", (NR>1?",":""), $1, $2}')"
  printf '  "media": {"files": %s, "bytes": %s},\n' "$MEDIA_FILES" "$MEDIA_BYTES"
  printf '  "screenshots": {"files": %s, "bytes": %s}\n' "$SHOT_FILES" "$SHOT_BYTES"
  printf '}\n'
} > "$STAGING/manifest.json"
scp $SSH_OPTS "$STAGING/manifest.json" "$REMOTE:$BASE/manifest/$TS.json"

# --- 13. prune -----------------------------------------------------------
# Keep every artifact within RETAIN_DAILY_DAYS; older than that keep the
# EARLIEST of each calendar month for RETAIN_MONTHLY_MONTHS. Earliest, not
# latest: once a month's survivor is chosen it never changes, whereas "latest"
# would re-designate a different keeper every night while the month runs.
# manifest/ is NEVER pruned -- it is a few hundred bytes and the annual school
# statement wants the media.bytes series over years.
# Computed HERE, deleted there. The remote has no awk, no `date -d` and no
# loops; it only lists (rsync) and deletes (sftp).
cutoff="$(date -u -d "$RETAIN_DAILY_DAYS days ago" +%Y-%m-%d)"
monthly_cutoff="$(date -u -d "$RETAIN_MONTHLY_MONTHS months ago" +%Y-%m)"
for dir in db env caddy refs; do
  remote_ls "$dir" | sort > "$STAGING/have.txt"
  # <ts> is the filename up to the first dot, and <ts> sorts chronologically
  # because it is ISO-8601 -- which is why "the earliest of each month" is one
  # awk pass over a sorted list rather than a date comparison.
  sed 's/[.].*//' "$STAGING/have.txt" | sort -u > "$STAGING/stamps.txt"
  awk -v c="$cutoff" 'substr($0,1,10) >= c' "$STAGING/stamps.txt" > "$STAGING/keep.txt"
  awk -v c="$cutoff" 'substr($0,1,10) < c' "$STAGING/stamps.txt" \
    | awk -v m="$monthly_cutoff" 'substr($0,1,7) >= m' \
    | awk '!seen[substr($0,1,7)]++' >> "$STAGING/keep.txt"
  sort -u "$STAGING/keep.txt" -o "$STAGING/keep.txt"
  awk -v d="$dir" 'NR==FNR { keep[$0]; next }
       { stamp = $0; sub(/[.].*/, "", stamp)
         if (!(stamp in keep)) print d "/" $0 }' \
    "$STAGING/keep.txt" "$STAGING/have.txt" | remote_rm
done

prune_before="$(date -u -d "$MIRROR_PRUNE_DAYS days ago" +%Y-%m-%d)"
awk -F'\t' -v c="$prune_before" '$2 < c { print "media/" $1 }' \
  "$STAGING/missing.new" | remote_rm
awk -F'\t' -v c="$prune_before" '$2 >= c' "$STAGING/missing.new" \
  > "$STAGING/missing.kept"
scp $SSH_OPTS "$STAGING/missing.kept" "$REMOTE:$BASE/media-missing.tsv"

# --- 14. heartbeat, on success only --------------------------------------
# Alerts on ABSENCE, which is the only thing that detects a backup that stopped
# running. cron's MAILTO is unavailable: there is no MTA and Hetzner blocks
# outbound 25 by default.
curl -fsS -m 15 "$HEARTBEAT" > /dev/null
echo "==> backup complete: $BASE @ $TS"
