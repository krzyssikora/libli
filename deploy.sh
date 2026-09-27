#!/usr/bin/env bash
# CI-invoked deploy script for libli.
#
# Lives in the repo rather than being generated on the host, so every change to
# it goes through the normal PR/CI/review path. Two callers:
#   - .github/workflows/deploy.yml on libli.pl, via appleboy/ssh-action:
#       bash /opt/libli/deploy.sh
#   - scripts/release/remote_deploy.sh on a school box (B2), which runs a TEMP
#     COPY of the deploy.sh at the target release tag.
#
# deploy.yml resets the checkout BEFORE invoking this file, so the copy bash
# parses is always the one the current commit ships -- a change here takes
# effect on the deploy that introduces it, not the one after. That ordering is
# also what bootstraps a host whose checkout predates this script existing.
# It is a real dependency, not a tidy-up candidate: see deploy.yml's comment.
#
# The reset below is therefore redundant under CI and load-bearing by hand --
# a by-hand `bash deploy.sh` on the box must still be correct on its own. (The
# §8 ROLLBACK is `LIBLI_DEPLOY_REF=<sha> bash deploy.sh`, the ref path; plain
# `bash deploy.sh` resets to master.)
#
# B2 inputs -- a FROZEN CROSS-VERSION CONTRACT: remote_deploy.sh comes from
# master while the deploy.sh it runs comes from an older release tag, so these
# names and meanings never change (spec §2 step 6):
#   LIBLI_DEPLOY_REF         a vX.Y.Z tag (any box) or a 40-hex sha (libli.pl only)
#   LIBLI_DEPLOY_EXPECT_SHA  the commit the caller verified; refuse on a mismatch
#   LIBLI_DEPLOY_SKIP_FETCH  the caller already fetched
#
# The whole body is main(), called on the LAST line as `main "$@"; exit`. bash
# reads a script file as it executes, and the ref path's checkout rewrites
# /opt/libli/deploy.sh under the running process; a function is parsed whole
# before it runs, and `exit` on the same line means nothing is read after it.
set -euo pipefail

APP_DIR=/opt/libli

# Retry budget for the fetches below. Overridable so the host can widen it
# without a code change; the defaults are what CI runs.
GIT_FETCH_ATTEMPTS=${GIT_FETCH_ATTEMPTS:-3}
GIT_FETCH_DELAY=${GIT_FETCH_DELAY:-5}

# Set by main(), read by on_exit.
REACHED_UP=0
RESTORE_SHA=""
RESTORE_NOTE=""

compose() {
  docker compose -f docker-compose.prod.yml --env-file .env.production "$@"
}

# Reads one KEY=value out of .env.production. `sed -n s///p` rather than grep so
# a missing key yields an empty string instead of exit 1, which under `set -e`
# would abort the deploy over a value that is only used for verification.
env_value() {
  sed -n "s/^$1=//p" .env.production | head -1
}

# To stderr, ignoring write errors: on_exit uses it, and the trap must not die
# of a closed pipe while cleaning up after one.
say() {
  printf '%s\n' "$*" >&2 2>/dev/null || true
}

die() {
  say "!! $*"
  exit 1
}

# The channel read rule (spec §3). DUPLICATED in scripts/release/preflight.sh --
# deliberately not a shared sourced helper, because this file runs as a temp
# copy at the target version and would source the CURRENT checkout's copy.
# tests/release_fixtures.py feeds both the same cases.
# Prints absent | release | invalid. A commented line naming the key counts as
# present-but-invalid: otherwise a by-hand run would reset a school to master.
channel_state() {
  awk '
    /^[[:space:]]*#.*LIBLI_DEPLOY_CHANNEL/ { n++; bad = 1; next }
    /^[[:space:]]*(export[[:space:]]+)?LIBLI_DEPLOY_CHANNEL[[:space:]]*=/ {
      n++
      if ($0 != "LIBLI_DEPLOY_CHANNEL=release") bad = 1
    }
    END {
      if (n == 0) print "absent"
      else if (n == 1 && !bad) print "release"
      else print "invalid"
    }
  ' "$1"
}

# The LIBLI_IMAGE_TAG read rule (spec §5). DUPLICATED in preflight.sh (see above).
# image_tag_read prints absent | invalid | "value <text>": exactly one line
# matching ^LIBLI_IMAGE_TAG= and no export-prefixed or indented variant.
# image_tag_state adds the shape check and prints absent | invalid | sha-<40 hex>
# (a trailing CR, a short sha or sha-v1.0.0 are all invalid).
image_tag_read() {
  awk '
    /^[[:space:]]*(export[[:space:]]+)?LIBLI_IMAGE_TAG[[:space:]]*=/ {
      any++
      if (index($0, "LIBLI_IMAGE_TAG=") == 1) { anchored++; val = substr($0, 17) }
    }
    END {
      if (any == 0) print "absent"
      else if (any != 1 || anchored != 1) print "invalid"
      else print "value " val
    }
  ' "$1"
}

image_tag_state() {
  local read value
  read="$(image_tag_read "$1")"
  case "$read" in
    "value "*)
      value="${read#value }"
      if [[ $value =~ ^sha-[0-9a-f]{40}$ ]]; then echo "$value"; else echo invalid; fi
      ;;
    *) echo "$read" ;;
  esac
}

# GitHub intermittently answers an ANONYMOUS fetch of this PUBLIC repo with a 401
# challenge, and git then dies on "could not read Username" because a deploy has
# no tty to prompt at. It killed three deploys in two days (#293, #295, #296).
# It is NOT a credential problem: a public fetch needs none, and in #296 the
# fetch 440 ms earlier had SUCCEEDED. Retrying turns it into a slower deploy
# rather than a red one. Arguments are passed to `git fetch origin`.
git_fetch_retry() {
  local attempt=1
  while true; do
    if git fetch origin "$@"; then
      return 0
    fi
    if [ "$attempt" -ge "$GIT_FETCH_ATTEMPTS" ]; then
      echo "==> git fetch failed $GIT_FETCH_ATTEMPTS times; refusing to deploy" >&2
      return 1
    fi
    echo "==> git fetch failed (attempt $attempt/$GIT_FETCH_ATTEMPTS); retrying in ${GIT_FETCH_DELAY}s"
    attempt=$((attempt + 1))
    sleep "$GIT_FETCH_DELAY"
  done
}

fetch_master() {
  git_fetch_retry master
}

sync_working_tree() {
  # fetch + reset --hard, never `git pull`:
  #   - the host checkout is a mirror of master by definition. Any local
  #     divergence is wrong and should be flattened, not merged.
  #   - `git pull` aborts on divergent branches and depends on pull.rebase config
  #     that varies across git versions.
  # .env.production is untracked (.gitignore's `.env*`), so the reset cannot
  # destroy the host's only copy of the secrets.
  #
  # deploy.yml fetches and resets before invoking this file, so this fetch is a
  # SECOND request to github.com inside a second -- and that pair is what tripped
  # #296. CI sets LIBLI_DEPLOY_SKIP_FETCH to drop it. The RESET is never skipped.
  if [ -n "${LIBLI_DEPLOY_SKIP_FETCH:-}" ]; then
    echo "==> CI already fetched; resetting to the ref it fetched"
  else
    fetch_master
  fi
  # D9: a run deploys ONLY its own commit. deploy.yml resets to whatever master
  # is when its job starts, so without this a run for X (or a re-run of X after
  # Y merged) would deploy Y under X's name -- and the canary guard reads a
  # green `deploy` job as "libli.pl ran X". Runs whether or not this run
  # fetched: deploy.yml always passes LIBLI_DEPLOY_SKIP_FETCH=1.
  if [ -n "${LIBLI_DEPLOY_EXPECT_SHA:-}" ]; then
    local tip
    tip="$(git rev-parse origin/master)"
    if [ "$tip" != "$LIBLI_DEPLOY_EXPECT_SHA" ]; then
      echo "!! superseded by $tip; the newer run deploys it (this run was for $LIBLI_DEPLOY_EXPECT_SHA)" >&2
      return 1
    fi
  fi
  git checkout master 2>/dev/null || true
  git reset --hard origin/master
}

# The embedded D3 guard on a release-channel box: BOTH copies -- the current
# release's and the target's -- must pass. On a downgrade the target is older
# and lacks any check added since, so its copy alone would drop exactly the
# newest protections. Every tag carries the guard (B2 containment).
run_migration_guards() {
  local current=$1 target=$2 at copy
  for at in "$current" "$target"; do
    copy="$(mktemp)"
    if ! git show "$at:scripts/release/migration_guard.sh" > "$copy" 2>/dev/null; then
      rm -f "$copy"
      die "no scripts/release/migration_guard.sh at $at; refusing"
    fi
    if ! bash "$copy" "$current" "$target"; then
      rm -f "$copy"
      die "the migration guard (copy at $at) refused; see docs/backup-and-restore.md"
    fi
    rm -f "$copy"
  done
}

# Any exit before `up` puts the checkout back to the commit the running image
# was built from (the persisted LIBLI_IMAGE_TAG), so a nightly backup never
# records a git_sha that disagrees with its own image -- the mismatch
# restore.sh refuses. EXIT, not ERR: without `set -E` an ERR trap does not fire
# inside functions (the pull runs inside compose()), and never on `exit 1`.
# Only if HEAD actually moved: an early refusal must not force-checkout over a
# hand-edited tracked file. (Keep the literal pull command out of comments
# above main(): test_backup_wiring.py finds its FIRST occurrence and requires
# the docker login to come before it.)
on_exit() {
  local rc=$? restored=0 head
  set +e
  # printf is a builtin: a write to a closed pipe would SIGPIPE this shell
  # itself. Ignored, the write fails with EPIPE instead and say() swallows it,
  # so the trap still exits with the deploy's own status.
  trap '' PIPE
  if [ "$rc" -ne 0 ] && [ "$REACHED_UP" != 1 ]; then
    head="$(git rev-parse HEAD 2>/dev/null)"
    if [ -z "$RESTORE_SHA" ]; then
      say "==> deploy failed before up (${RESTORE_NOTE:-no restore target}); the checkout is left as it is"
    elif [ "$head" != "$RESTORE_SHA" ]; then
      if git symbolic-ref -q HEAD > /dev/null 2>&1; then
        git reset -q --hard "$RESTORE_SHA" > /dev/null 2>&1 && restored=1
      else
        git checkout -q --force --detach "$RESTORE_SHA" > /dev/null 2>&1 && restored=1
      fi
      if [ "$restored" = 1 ]; then
        say "==> deploy failed before up; checkout restored to $RESTORE_SHA (the image still running)"
      else
        say "!! deploy failed before up AND the checkout restore FAILED: HEAD is $head, the running image is sha-$RESTORE_SHA; fix by hand before the next backup"
      fi
    fi
  fi
  exit "$rc"
}

main() {
  # An exported LIBLI_IMAGE_TAG (left from a manual first boot, say) would beat
  # .env.production at `up` -- the same shell-over-env-file precedence the pull
  # below relies on. The pull gets it per command; nothing else sees it.
  unset LIBLI_IMAGE_TAG

  cd "$APP_DIR"

  # Shared with backup.sh and restore.sh. A merge landing mid-dump would recreate
  # the app container, restart postgres' dependents and prune images underneath it.
  # deploy.sh WAITS rather than skipping: a silently dropped deploy would report
  # green in Actions having done nothing.
  #
  # Taken before anything else, including the fetch: the point is to hold the lock
  # for the whole run, not merely for the part that touches containers.
  exec 9>/var/lock/libli-deploy.lock
  flock 9

  local channel tag_state ref kind="" target image_tag ghcr_token site_domain
  channel="$(channel_state .env.production)"
  tag_state="$(image_tag_state .env.production)"

  # Spec §5's outcome table. A present-but-invalid channel line takes the
  # release column; the channel catch below refuses it anyway.
  if [ "$tag_state" != absent ] && [ "$tag_state" != invalid ]; then
    RESTORE_SHA="${tag_state#sha-}"
  elif [ "$channel" = invalid ]; then
    # The channel line is the thing to fix first; say so rather than sending
    # the operator down the first-boot path.
    die "LIBLI_DEPLOY_CHANNEL is present in .env.production but not exactly 'release', and LIBLI_IMAGE_TAG is $tag_state; fix both (docs/deployment.md §9)"
  elif [ "$channel" != absent ]; then
    if [ "$tag_state" = absent ]; then
      die "LIBLI_IMAGE_TAG absent in .env.production; a school box is first-booted by hand (docs/deployment.md §9)"
    fi
    die "LIBLI_IMAGE_TAG unreadable in .env.production (need exactly one line LIBLI_IMAGE_TAG=sha-<40 hex>)"
  elif [ "$tag_state" = absent ]; then
    RESTORE_NOTE="no restore target"
  else
    say "!! warning: LIBLI_IMAGE_TAG unreadable; a failure before up cannot restore the checkout"
    RESTORE_NOTE="cannot restore: LIBLI_IMAGE_TAG unreadable"
  fi

  trap on_exit EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM

  # The channel catch. Without it, `bash deploy.sh` by hand on a school box --
  # the natural manual-rollback reflex -- would silently move it onto master.
  ref="${LIBLI_DEPLOY_REF:-}"
  case "$channel" in
    invalid)
      die "LIBLI_DEPLOY_CHANNEL is present in .env.production but not exactly 'release'; fix it (docs/deployment.md §9)"
      ;;
    release)
      [ -n "$ref" ] || die "this is a release-channel box: pass LIBLI_DEPLOY_REF=vX.Y.Z (or use Deploy release); refusing to reset a school to master"
      ;;
  esac

  if [ -n "$ref" ]; then
    if [[ $ref =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      kind=tag
    elif [ "$channel" = absent ] && [[ $ref =~ ^[0-9a-f]{40}$ ]]; then
      kind=sha
    elif [ "$channel" = release ]; then
      die "LIBLI_DEPLOY_REF must be a vX.Y.Z tag on a release-channel box"
    else
      die "LIBLI_DEPLOY_REF must be a vX.Y.Z tag or a full 40-hex sha"
    fi

    if [ -z "${LIBLI_DEPLOY_SKIP_FETCH:-}" ]; then
      if [ "$kind" = tag ]; then
        # Forced: a re-cut tag must replace a stale local one, and a bare
        # `git fetch origin <tag>` writes only FETCH_HEAD.
        git_fetch_retry "+refs/tags/$ref:refs/tags/$ref"
      else
        git_fetch_retry "$ref"
      fi
    fi
    target="$(git rev-parse --verify --quiet "$ref^{commit}")" || die "$ref does not resolve to a commit"
    if [ -n "${LIBLI_DEPLOY_EXPECT_SHA:-}" ] && [ "$target" != "$LIBLI_DEPLOY_EXPECT_SHA" ]; then
      die "$ref resolves to $target, not the verified $LIBLI_DEPLOY_EXPECT_SHA (re-cut tag?); refusing"
    fi
    if [ "$channel" = release ]; then
      run_migration_guards "$RESTORE_SHA" "$target"
    fi
    echo "==> checking out $ref ($target)"
    git checkout -q --force --detach "$target"
    git reset -q --hard "$target"
  else
    echo "==> resetting the working tree to origin/master"
    sync_working_tree
  fi

  echo "==> validating the Caddyfile"
  # caddy has no healthcheck in docker-compose.prod.yml, so a syntax error here
  # produces a crash loop that `docker compose ps` still reports as `running` --
  # and `--wait` below therefore cannot catch it. Validating BEFORE `up` means a
  # bad Caddyfile fails the deploy with the running site still intact.
  # The Caddyfile opens its site block with {$SITE_ADDRESS}, so that variable has
  # to be set for the parse to succeed; use the real one when it is readable.
  docker run --rm -v "$APP_DIR/Caddyfile:/etc/caddy/Caddyfile:ro" \
    -e SITE_ADDRESS="$(env_value SITE_ADDRESS)" \
    caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile

  image_tag="sha-$(git rev-parse HEAD)"

  echo "==> logging in to ghcr.io"
  # The package is private: it contains the application source of a private repo.
  # An unauthenticated pull fails with an opaque `denied`.
  #
  # Checked explicitly rather than letting an empty value reach docker login: a
  # blank password produces "unauthorized" and, under pipefail, aborts the deploy
  # with an error that reads like a registry outage rather than a missing key.
  ghcr_token="$(env_value LIBLI_GHCR_TOKEN)"
  if [ -z "$ghcr_token" ]; then
    echo "!! LIBLI_GHCR_TOKEN is unset in .env.production." >&2
    echo "   Add a read:packages PAT to it; see docs/deployment.md section 1." >&2
    exit 1
  fi
  printf '%s' "$ghcr_token" | docker login ghcr.io -u krzyssikora --password-stdin

  echo "==> pulling $image_tag"
  # The tag reaches compose from the shell for the pull only (compose
  # interpolation prefers the shell over --env-file). It is persisted below,
  # just before `up`, so LIBLI_IMAGE_TAG always names the newest code that may
  # have run against this database -- what the migration guard reads as
  # "current", and what backup.sh records as the manifest's image.
  LIBLI_IMAGE_TAG="$image_tag" compose pull

  echo "==> pinning the image tag"
  # Written INTO .env.production, not exported: backup.sh reads it hours later
  # under cron with env_value, the encrypted env in each artifact must carry the
  # tag matching its manifest, and compose guards the key with `:?` so any `up`
  # outside this script would abort without a persisted value.
  # Write, THEN set the flag, THEN up: a failed write with the flag unset is a
  # pre-up exit and restores; nothing that can fail sits between flag and up.
  if grep -q '^LIBLI_IMAGE_TAG=' .env.production; then
    sed -i "s|^LIBLI_IMAGE_TAG=.*|LIBLI_IMAGE_TAG=${image_tag}|" .env.production
  else
    printf 'LIBLI_IMAGE_TAG=%s\n' "$image_tag" >> .env.production
  fi
  REACHED_UP=1
  echo "==> recreating the stack"
  compose up -d --wait

  echo "==> verifying the site through caddy"
  # Through the public name, not 127.0.0.1: this is the only step that exercises
  # Caddy, TLS and the proxy hop, and it is what distinguishes "the container is
  # healthy" from "the site is up". --retry covers the seconds Caddy needs to
  # rebind after a recreate.
  site_domain="$(env_value DJANGO_SITE_DOMAIN)"
  curl -fsS --retry 5 --retry-delay 3 --retry-connrefused \
    "https://${site_domain}/healthz/" | grep -q '"status": *"ok"'

  echo "==> pruning dangling images"
  # Every pull leaves the previous image's layers dangling, and nothing else on
  # this host reclaims them. The runbook's 50 GB floor is sized for a ~17 GB
  # import peak, so unbounded image garbage eventually breaks an import rather
  # than the deploy that caused it. Dangling only -- never `-a`, which would also
  # delete the pulled postgres and caddy images while their containers are down.
  docker image prune -f

  echo "==> deploy complete"
}

main "$@"; exit
