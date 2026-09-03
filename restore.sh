#!/usr/bin/env bash
set -euo pipefail
# libli restore. The same script serves four paths: restore, resize,
# provider-move and handover.
#
# STRAIGHT-LINE ON PURPOSE, like backup.sh -- several guards are source-order
# assertions. Steps are named rather than numbered because renumbering rots
# every cross-reference in the spec and the runbook.
#
# STEP 0 IS NOT IN THIS FILE. The runbook's git clone is §3, so on a box that
# has had only §1-2 this script is not present. docs/backup-and-restore.md
# carries the pre-flight: §1-2, choose <ts> from your own machine, clone PINNED
# to the commit matching the target image tag, deliver credentials to tmpfs,
# then invoke this.

APP_DIR=/opt/libli
cd "$APP_DIR"

LOCK_FILE=/var/lock/libli-deploy.lock
AGE_KEY=/dev/shm/libli-restore.key
SSH_KEY=/dev/shm/libli-restore-ssh.key

MODE=live
ROTATE=0
SLUG=""
TS=""
IMAGE_TAG=""
GHCR_TOKEN=""
SSH_HOST=""
SSH_USER=""

while [ $# -gt 0 ]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2 ;;
    --ts) TS="$2"; shift 2 ;;
    --image-tag) IMAGE_TAG="$2"; shift 2 ;;
    --ssh-host) SSH_HOST="$2"; shift 2 ;;
    --ssh-user) SSH_USER="$2"; shift 2 ;;
    --ghcr-token) GHCR_TOKEN="$2"; shift 2 ;;
    --pre-cutover) MODE=pre-cutover; shift ;;
    --live) MODE=live; shift ;;
    --rotate-secrets) ROTATE=1; shift ;;
    *) echo "!! unknown argument: $1" >&2; exit 2 ;;
  esac
done

# The literal flag spellings, not ${name,,}: that lowercases the VARIABLE name
# and would print "--ssh_host is required" for a flag the case block above only
# accepts as --ssh-host. Telling an operator at 2am to pass a flag the script
# then rejects as an unknown argument is worse than saying nothing.
[ -n "$SLUG" ]     || { echo "!! --slug is required" >&2; exit 2; }
[ -n "$TS" ]       || { echo "!! --ts is required" >&2; exit 2; }
[ -n "$SSH_HOST" ] || { echo "!! --ssh-host is required" >&2; exit 2; }
[ -n "$SSH_USER" ] || { echo "!! --ssh-user is required" >&2; exit 2; }

# --- LOCK ----------------------------------------------------------------
# Fails LOUDLY rather than skipping. A silently skipped restore is the worst
# outcome in the set: the operator believes the site is being recovered while
# nothing is happening.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "!! a deploy or backup holds $LOCK_FILE; refusing to restore" >&2
  exit 1
fi

# --- CREDENTIALS ---------------------------------------------------------
# tmpfs, never disk, removed on every exit path including failure. The invariant
# is "never AT REST on a server" -- a restore necessarily decrypts here.
trap 'shred -u "$AGE_KEY" "$SSH_KEY" 2>/dev/null || rm -f "$AGE_KEY" "$SSH_KEY"' EXIT
for key in "$AGE_KEY" "$SSH_KEY"; do
  if [ ! -s "$key" ]; then
    echo "!! $key is absent. Deliver it out of band before running this:" >&2
    echo "   ssh <box> 'cat > $key' < <your local copy>" >&2
    exit 1
  fi
done

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new"
REMOTE="$SSH_USER@$SSH_HOST"
BASE="schools/$SLUG"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"; shred -u "$AGE_KEY" "$SSH_KEY" 2>/dev/null || rm -f "$AGE_KEY" "$SSH_KEY"' EXIT

# Same constraint as backup.sh: the Storage Box is not a shell. List with
# rsync, test and delete with sftp, and compute everything here.
remote_ls() {
  rsync --list-only -r -e "ssh $SSH_OPTS" "$REMOTE:$BASE/$1/" 2>/dev/null \
    | awk '$1 !~ /^d/ { $1=$2=$3=$4=""; sub(/^ +/, ""); print }'
}

remote_exists() {
  printf 'ls %s\n' "$1" | sftp -b - $SSH_OPTS "$REMOTE:$BASE/" > /dev/null 2>&1
}

# grep exits 1 when it SELECTS NO LINES, and `grep -c` prints 0 and STILL exits
# 1 -- both fatal under `set -euo pipefail`, and both are ordinary outcomes
# here. A school that never had an IssueReport.screenshot has an empty
# screenshots/ listing (so it could not be restored at all), and a refs gap made
# entirely of derivatives has a zero ORIGINAL count (so the gap report died
# while printing that the gap was harmless). Only status 1 is absorbed: a real
# grep failure (status 2) still returns non-zero and still aborts.
grep_any() {
  grep "$@" || [ $? -eq 1 ]
}

# --- CONFIRM -------------------------------------------------------------
scp $SSH_OPTS "$REMOTE:$BASE/manifest/$TS.json" "$WORK/manifest.json"
echo "=== manifest $TS ==="
cat "$WORK/manifest.json"

# Hard refuse: without the dump or the env there is nothing to restore and there
# is no degraded mode. manifest/ is never pruned, so it lists timestamps whose
# artefacts are gone -- without this the failure lands after the confirmation.
missing=""
for object in "db/$TS.dump.age" "env/$TS.env.age" "caddy/$TS.tar.age"; do
  remote_exists "$object" || missing="$missing $object"
done
if [ -n "$missing" ]; then
  # missing artefact
  echo "!! pruned, not restorable:$missing" >&2
  echo "   choose a <ts> within the 30-day window, or a monthly survivor." >&2
  exit 1
fi

# Informational: a refs gap is often legitimate (media prunes at 90 days,
# screenshots erase on deletion, dumps live 13 months), so refusing here would
# make every old-enough <ts> unrestorable. The typed slug below IS the
# acceptance, and FILES honours it.
scp $SSH_OPTS "$REMOTE:$BASE/refs/$TS.txt" "$WORK/refs.txt"
remote_ls media | sort > "$WORK/have_media.txt"
remote_ls screenshots | grep_any '\.age$' | sed 's|\.age$||' | sort > "$WORK/have_shots.txt"
awk -F'\t' '$1 == "media" { print $2 }' "$WORK/refs.txt" | sort > "$WORK/want_media.txt"
awk -F'\t' '$1 == "support_screenshots" { print $2 }' "$WORK/refs.txt" | sort > "$WORK/want_shots.txt"
comm -23 "$WORK/want_media.txt" "$WORK/have_media.txt" > "$WORK/gap_media.txt"
comm -23 "$WORK/want_shots.txt" "$WORK/have_shots.txt" > "$WORK/gap_shots.txt"
if [ -s "$WORK/gap_media.txt" ] || [ -s "$WORK/gap_shots.txt" ]; then
  # refs gap
  # Counted into variables through grep_any, not piped straight to xargs: a
  # zero count exits 1 from grep, so the ALL-derivatives gap -- the common case
  # this very message calls harmless -- used to abort the run on the ORIGINAL
  # line, and a gap with no derivatives aborted on the line above it.
  gap_derivatives="$(grep_any -c 'derivatives/' "$WORK/gap_media.txt")"
  gap_originals="$(grep_any -vc 'derivatives/' "$WORK/gap_media.txt")"
  gap_shots="$(wc -l < "$WORK/gap_shots.txt")"
  echo "=== files this dump references that the mirror no longer holds ==="
  printf '  %s derivative(s) -- harmless, backfill_media_derivatives regenerates them\n' "$gap_derivatives"
  printf '  %s screenshot(s) -- expected on an old <ts>; erased by design\n' "$gap_shots"
  printf '  %s ORIGINAL(s) -- unrepairable content loss\n' "$gap_originals"
  echo "Typing the slug below accepts this gap."
fi

echo
echo "About to DESTROY every volume on this box and restore $SLUG @ $TS."
printf 'Type the school slug to continue: '
read -r typed
[ "$typed" = "$SLUG" ] || { echo "!! not confirmed" >&2; exit 1; }

# --- IDENTITY ------------------------------------------------------------
schema="$(sed -n 's/.*"schema": *\([0-9]*\).*/\1/p' "$WORK/manifest.json")"
[ "$schema" = "1" ] || { echo "!! unknown manifest schema $schema" >&2; exit 1; }
school="$(sed -n 's/.*"school": *"\([^"]*\)".*/\1/p' "$WORK/manifest.json")"
[ "$school" = "$SLUG" ] || { echo "!! manifest is school '$school', not '$SLUG'" >&2; exit 1; }

# --- VERSION -------------------------------------------------------------
manifest_image="$(sed -n 's/.*"image": *"\([^"]*\)".*/\1/p' "$WORK/manifest.json")"
if [ -z "$IMAGE_TAG" ]; then
  TARGET="$manifest_image"
  echo "==> target is the manifest's own image; the containment check is a tautology and is skipped"
else
  echo "$IMAGE_TAG" | grep -Eq '^sha-[0-9a-f]{7,40}$' \
    || { echo "!! --image-tag must match ^sha-[0-9a-f]{7,40}$; a floating tag names different code on different days and cannot pin a restore" >&2; exit 1; }
  TARGET="ghcr.io/krzyssikora/libli:$IMAGE_TAG"
fi

if [ -n "$GHCR_TOKEN" ]; then
  printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u krzyssikora --password-stdin
fi
docker pull "$TARGET" \
  || { echo "!! cannot pull $TARGET. Pass --ghcr-token if this box has no valid login." >&2; exit 1; }

# The compose file governs the postgres major, the volume names and the
# healthcheck, so a checkout that disagrees with the image can contradict it.
checkout_tag="sha-$(git rev-parse HEAD)"
target_tag="${TARGET##*:}"
if [ "$checkout_tag" != "$target_tag" ]; then
  echo "!! this checkout is $checkout_tag but the target image is $target_tag." >&2
  echo "   git checkout the matching commit (pre-flight step 3) and re-run." >&2
  exit 1
fi

# Django has one migration leaf PER APP, so a single "head" cannot detect an
# image behind on a courses migration. Set containment, read from the image's
# migration FILES -- which needs no database.
docker run --rm --entrypoint sh "$TARGET" -c 'ls /app/*/migrations/[0-9]*.py' \
  | sed 's|.*/\([^/]*\)/migrations/\([^.]*\)\.py|\1.\2|' | sort > "$WORK/image_migrations.txt"
sed -n 's/.*"migrations": \[\(.*\)\].*/\1/p' "$WORK/manifest.json" \
  | tr ',' '\n' | tr -d '" ' | sort > "$WORK/dump_migrations.txt"
if ! comm -23 "$WORK/dump_migrations.txt" "$WORK/image_migrations.txt" | grep -q .; then
  :
else
  echo "!! the target image is BEHIND the dump; restoring forward is safe, backward is not:" >&2
  comm -23 "$WORK/dump_migrations.txt" "$WORK/image_migrations.txt" >&2
  exit 1
fi

manifest_pg="$(sed -n 's/.*"postgres_major": *\([0-9]*\).*/\1/p' "$WORK/manifest.json")"
compose_pg="$(sed -n 's|.*image: postgres:\([0-9]*\).*|\1|p' docker-compose.prod.yml | head -1)"
[ "$compose_pg" -ge "$manifest_pg" ] \
  || { echo "!! compose runs postgres:$compose_pg, the dump is from $manifest_pg" >&2; exit 1; }

# --- ENV -----------------------------------------------------------------
scp $SSH_OPTS "$REMOTE:$BASE/env/$TS.env.age" "$WORK/env.age"
age -d -i "$AGE_KEY" -o .env.production "$WORK/env.age"
chmod 600 .env.production

# Left in place the entrypoint's init_platform would mint an admin account on a
# production restore.
sed -i '/^INIT_ADMIN_/d' .env.production
sed -i "s|^LIBLI_IMAGE_TAG=.*|LIBLI_IMAGE_TAG=$target_tag|" .env.production

if [ "$MODE" = "pre-cutover" ]; then
  # DNS still points at the OLD box, so ACME would fail validation repeatedly and
  # eat Let's Encrypt's failed-validation budget -- possibly blocking issuance at
  # the cutover. The Caddyfile has no tls directive; the http:// scheme is what
  # makes Caddy skip ACME, exactly as the runbook's local-smoke section documents.
  host="$(sed -n 's/^DJANGO_SITE_DOMAIN=//p' .env.production | head -1)"
  sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=http://$host|" .env.production
  if grep -q '^DJANGO_SECURE_SSL_REDIRECT=' .env.production; then
    sed -i 's|^DJANGO_SECURE_SSL_REDIRECT=.*|DJANGO_SECURE_SSL_REDIRECT=false|' .env.production
  else
    echo 'DJANGO_SECURE_SSL_REDIRECT=false' >> .env.production
  fi
fi

if [ "$ROTATE" = "1" ]; then
  # rotate_secrets: MUST happen here, before the wipe. Postgres accepts a new
  # password only while initialising an empty data directory.
  new_pg="$(openssl rand -base64 36 | tr -d '/+=' | head -c 32)"
  new_secret="$(openssl rand -base64 64 | tr -d '\n')"
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$new_pg|" .env.production
  sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$new_secret|" .env.production
  echo "=== SAVE THESE TO THE PASSWORD MANAGER NOW -- they exist nowhere else ==="
  echo "POSTGRES_PASSWORD=$new_pg"
  echo "DJANGO_SECRET_KEY=$new_secret"
fi

compose() {
  docker compose -f docker-compose.prod.yml --env-file .env.production "$@"
}
vol_path() { docker volume inspect --format '{{.Mountpoint}}' "libli_$1"; }
rsync_ok() {
  local code=0
  rsync "$@" || code=$?
  [ "$code" -eq 0 ] || [ "$code" -eq 24 ]
}

# --- WIPE ----------------------------------------------------------------
# Destroys ALL seven volumes, not just pgdata, and that is intended: it is what
# makes the media volume contain EXACTLY the referenced set. A surgical
# `docker volume rm libli_pgdata` would preserve the old media tree, and FILES
# only ADDS referenced files -- so any file the old tree held that the restored
# database does not reference would survive, unreferenced and still reachable at
# its URL through Caddy.
compose down --volumes

# --- MATERIALISE ---------------------------------------------------------
# `up -d db` creates only pgdata. compose create makes every volume WITH
# compose's labels and starts nothing; `docker volume create` would make
# unlabelled ones that compose then refuses to adopt.
compose create

# --- DB UP ---------------------------------------------------------------
# db ALONE. The entrypoint runs `migrate` on every boot, so a full `up` would
# create the schema and the dump would then collide with it.
compose up -d db
until compose exec -T db pg_isready -U "$(sed -n 's/^POSTGRES_USER=//p' .env.production | head -1)"; do
  sleep 2
done

# --- LOAD ----------------------------------------------------------------
scp $SSH_OPTS "$REMOTE:$BASE/db/$TS.dump.age" "$WORK/db.age"
age -d -i "$AGE_KEY" -o "$WORK/db.dump" "$WORK/db.age"
PGUSER_VALUE="$(sed -n 's/^POSTGRES_USER=//p' .env.production | head -1)"
PGDB_VALUE="$(sed -n 's/^POSTGRES_DB=//p' .env.production | head -1)"
PGPASSWORD_VALUE="$(sed -n 's/^POSTGRES_PASSWORD=//p' .env.production | head -1)"
compose exec -T -e PGPASSWORD="$PGPASSWORD_VALUE" db \
  pg_restore -U "$PGUSER_VALUE" -d "$PGDB_VALUE" --clean --if-exists < "$WORK/db.dump"

# --- FILES ---------------------------------------------------------------
# Three sets, three mechanisms. Only the files the RESTORED database references
# are fetched: copying the whole mirror back would resurrect every file deleted
# in the last 90 days, and Caddy serves media/ directly, so a resurrected file is
# reachable at its URL with no row pointing at it.
scp $SSH_OPTS "$REMOTE:$BASE/caddy/$TS.tar.age" "$WORK/caddy.age"
age -d -i "$AGE_KEY" "$WORK/caddy.age" | tar -C "$(vol_path caddy_data)" -xf -

compose run --rm --no-deps app /app/.venv/bin/python manage.py list_referenced_files \
  > "$WORK/restored_refs.txt"
awk -F'\t' '$1 == "media" { print $2 }' "$WORK/restored_refs.txt" | sort > "$WORK/need_media.txt"
awk -F'\t' '$1 == "support_screenshots" { print $2 }' "$WORK/restored_refs.txt" | sort > "$WORK/need_shots.txt"

# rsync exits 23 when a --files-from entry is ABSENT ON THE SENDER, and the gap
# CONFIRM printed is precisely a set of absent entries -- so fetching
# need_media.txt verbatim aborted the accepted-gap path here, after WIPE, which
# made the whole accept-and-reconcile design unreachable. Adding 23 to
# rsync_ok's tolerated list would instead make a genuinely partial transfer read
# as success. The fetch list is therefore intersected with what the mirror
# actually holds, leaving gap_media.txt the single declared exception.
#
# Listed AGAIN rather than reusing CONFIRM's have_media.txt: that is what keeps
# VERIFY able to do its stated job. A file the mirror lost BETWEEN the check and
# the fetch is simply not fetched here, and VERIFY then names it as missing
# beyond the declared gap -- whereas reusing the older listing would put it back
# in the --files-from and abort on 23 again.
remote_ls media | sort > "$WORK/have_media_now.txt"
comm -12 "$WORK/need_media.txt" "$WORK/have_media_now.txt" > "$WORK/fetch_media.txt"
rsync_ok -a --files-from="$WORK/fetch_media.txt" -e "ssh $SSH_OPTS" \
  "$REMOTE:$BASE/media/" "$(vol_path media)/"

SHOTS_DIR="$(vol_path support_screenshots)"
while read -r name; do
  remote_exists "screenshots/$name.age" || continue
  mkdir -p "$SHOTS_DIR/$(dirname "$name")"
  scp $SSH_OPTS "$REMOTE:$BASE/screenshots/$name.age" "$WORK/shot.age"
  age -d -i "$AGE_KEY" -o "$SHOTS_DIR/$name" "$WORK/shot.age"
done < "$WORK/need_shots.txt"

# --- APP UP --------------------------------------------------------------
compose up -d --wait

# --- VERIFY --------------------------------------------------------------
# Exact, minus the gap CONFIRM declared and the operator accepted. Anything
# missing BEYOND that accepted set means the mirror lost a file between the check
# and the fetch -- a genuine fault rather than a known consequence.
(cd "$(vol_path media)" && find . -type f | sed 's|^\./||') | sort > "$WORK/got_media.txt"
comm -23 "$WORK/need_media.txt" "$WORK/got_media.txt" | sort > "$WORK/unfetched.txt"
comm -23 "$WORK/unfetched.txt" "$WORK/gap_media.txt" > "$WORK/unexpected.txt"
if [ -s "$WORK/unexpected.txt" ]; then
  echo "!! files missing that CONFIRM did not declare:" >&2
  cat "$WORK/unexpected.txt" >&2
  exit 1
fi

if [ "$MODE" = "pre-cutover" ]; then
  curl -fsS -H "Host: $(sed -n 's/^DJANGO_SITE_DOMAIN=//p' .env.production | head -1)" \
    http://127.0.0.1/healthz/ | grep -q '"status": *"ok"'
  echo "==> pre-cutover restore verified. Repoint DNS, then re-run with --live."
else
  site="$(sed -n 's/^DJANGO_SITE_DOMAIN=//p' .env.production | head -1)"
  curl -fsS --retry 5 --retry-delay 3 --retry-connrefused \
    "https://$site/healthz/" | grep -q '"status": *"ok"'
  echo "==> restore complete and verified over TLS."
fi

# --- HANDOFF -------------------------------------------------------------
if [ "$ROTATE" = "1" ]; then
  echo
  echo "=== NOT DONE. These cannot be rotated from this box: ==="
  echo "  - the Storage Box sub-account and key (revoke the old at Hetzner)"
  echo "  - LIBLI_GHCR_TOKEN (revoke the old PAT at GitHub)"
  echo "  - DJANGO_EMAIL_HOST_PASSWORD (reissued by the mail provider)"
  echo "  - SocialApp.secret and WebhookEndpoint.secret -- these live in the"
  echo "    DATABASE, survived the restore intact, and are rotated in the admin UI"
  echo "See docs/backup-and-restore.md. Exiting non-zero until these are done."
  exit 1
fi
