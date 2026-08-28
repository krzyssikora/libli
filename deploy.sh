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

compose() {
  docker compose -f docker-compose.prod.yml --env-file .env.production "$@"
}

# Reads one KEY=value out of .env.production. `sed -n s///p` rather than grep so
# a missing key yields an empty string instead of exit 1, which under `set -e`
# would abort the deploy over a value that is only used for verification.
env_value() {
  sed -n "s/^$1=//p" .env.production | head -1
}

echo "==> resetting the working tree to origin/master"
# fetch + reset --hard, never `git pull`:
#   - the host checkout is a mirror of master by definition. Any local
#     divergence is wrong and should be flattened, not merged.
#   - `git pull` aborts on divergent branches and depends on pull.rebase config
#     that varies across git versions.
# .env.production is untracked (.gitignore's `.env*`), so the reset cannot
# destroy the host's only copy of the secrets.
git fetch origin master
git checkout master 2>/dev/null || true
git reset --hard origin/master

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

echo "==> rebuilding and recreating the stack"
# --wait is the failure handling. It blocks on the app healthcheck -- which
# asserts the /healthz/ BODY, not merely that gunicorn accepted a socket -- and
# exits non-zero if the container never goes healthy. A failed migration or a
# broken build therefore turns the Actions run red rather than silently leaving
# a dead site behind a green checkmark.
compose up -d --build --wait

echo "==> verifying the site through caddy"
# Through the public name, not 127.0.0.1: this is the only step that exercises
# Caddy, TLS and the proxy hop, and it is what distinguishes "the container is
# healthy" from "the site is up". --retry covers the seconds Caddy needs to
# rebind after a recreate.
site_domain="$(env_value DJANGO_SITE_DOMAIN)"
curl -fsS --retry 5 --retry-delay 3 --retry-connrefused \
  "https://${site_domain}/healthz/" | grep -q '"status": *"ok"'

echo "==> pruning dangling images"
# Every --build leaves the previous image's layers dangling, and nothing else on
# this host reclaims them. The runbook's 50 GB floor is sized for a ~17 GB
# import peak, so unbounded build garbage eventually breaks an import rather
# than the deploy that caused it. Dangling only -- never `-a`, which would also
# delete the pulled postgres and caddy images while their containers are down.
docker image prune -f

echo "==> deploy complete"
