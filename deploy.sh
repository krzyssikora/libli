#!/usr/bin/env bash
# CI-invoked deploy script for libli.
#
# Lives in the repo rather than being generated on the host, so every change to
# it goes through the normal PR/CI/review path. Invoked by
# .github/workflows/deploy.yml via appleboy/ssh-action:
#   bash /opt/libli/deploy.sh
#
# deploy.yml resets the checkout BEFORE invoking this file, so the copy bash
# parses is always the one the current commit ships -- a change here takes
# effect on the deploy that introduces it, not the one after. That ordering is
# also what bootstraps a host whose checkout predates this script existing.
# It is a real dependency, not a tidy-up candidate: see deploy.yml's comment.
#
# The reset below is therefore redundant under CI and load-bearing by hand --
# running `bash deploy.sh` on the box (the §8 rollback path) must still be
# correct on its own. bonnot's deploy/deploy.sh accepts a one-deploy lag here
# instead, because provision.sh seeds its copy; libli has no provision step.
set -euo pipefail

APP_DIR=/opt/libli
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

# Retry budget for the fetch below. Overridable so the host can widen it without
# a code change; the defaults are what CI runs.
GIT_FETCH_ATTEMPTS=${GIT_FETCH_ATTEMPTS:-3}
GIT_FETCH_DELAY=${GIT_FETCH_DELAY:-5}

compose() {
  docker compose -f docker-compose.prod.yml --env-file .env.production "$@"
}

# Reads one KEY=value out of .env.production. `sed -n s///p` rather than grep so
# a missing key yields an empty string instead of exit 1, which under `set -e`
# would abort the deploy over a value that is only used for verification.
env_value() {
  sed -n "s/^$1=//p" .env.production | head -1
}

# GitHub intermittently answers an ANONYMOUS fetch of this PUBLIC repo with a 401
# challenge, and git then dies on "could not read Username" because a deploy has
# no tty to prompt at. It killed three deploys in two days (#293, #295, #296).
# It is NOT a credential problem: a public fetch needs none, and in #296 the
# fetch 440 ms earlier had SUCCEEDED. Retrying turns it into a slower deploy
# rather than a red one -- and, because the run is red at the END of the retries
# and not at the start, the site is left on the previous commit either way.
fetch_master() {
  local attempt=1
  while true; do
    if git fetch origin master; then
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
  # #296, where the first was served and the second refused 440 ms later. CI sets
  # LIBLI_DEPLOY_SKIP_FETCH to drop it. The RESET is never skipped: it, not the
  # fetch, is what guarantees the tree matches origin/master. Run by hand (the
  # rollback path in docs/deployment.md) the variable is unset and the fetch
  # happens, which is what makes that path correct on its own.
  if [ -n "${LIBLI_DEPLOY_SKIP_FETCH:-}" ]; then
    echo "==> CI already fetched; resetting to the ref it fetched"
  else
    fetch_master
  fi
  git checkout master 2>/dev/null || true
  git reset --hard origin/master
}

echo "==> resetting the working tree to origin/master"
sync_working_tree

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

echo "==> pinning the image tag to this checkout"
# Written INTO .env.production, not exported: backup.sh reads it hours later
# under cron with env_value, the encrypted env in each artifact must carry the
# tag matching its manifest, and compose guards the key with `:?` so any `up`
# outside this script -- the runbook's §3 first boot, restore.sh, a manual
# `up -d` -- would abort without a persisted value.
image_tag="sha-$(git rev-parse HEAD)"
if grep -q '^LIBLI_IMAGE_TAG=' .env.production; then
  sed -i "s|^LIBLI_IMAGE_TAG=.*|LIBLI_IMAGE_TAG=${image_tag}|" .env.production
else
  printf 'LIBLI_IMAGE_TAG=%s\n' "$image_tag" >> .env.production
fi

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

echo "==> pulling and recreating the stack"
compose pull
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
