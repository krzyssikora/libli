#!/bin/sh
# libli container entrypoint. Ordered bootstrap, then either the command passed
# as arguments or the app server.
#
# Safe ONLY because there is exactly one app container: `migrate` here would
# race between replicas. Do not scale this service.
set -eu

VENV_PY=/app/.venv/bin/python

echo "==> waiting for the database"
i=0
until "$VENV_PY" -c "
import django
django.setup()
from django.db import connection
connection.ensure_connection()
"; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "!! database unreachable after 60 attempts; refusing to start" >&2
    exit 1
  fi
  sleep 2
done

echo "==> migrate"
"$VENV_PY" manage.py migrate --noinput

# Unconditional, even though init_platform also calls it. Permissions live as
# constants in institution/roles.py but are only ASSIGNED by seed_roles(); on an
# already-bootstrapped instance init_platform is skipped below, so this would be
# the only caller. No test can catch its omission -- tests/factories.py calls
# seed_roles() itself, so the suite passes either way.
echo "==> setup_roles"
"$VENV_PY" manage.py setup_roles

# Site #1 ships as example.com and build_accept_url builds invitation and
# password-reset links from it. A no-op when DJANGO_SITE_DOMAIN is unset.
echo "==> set_site_domain"
# --only-if-placeholder: DJANGO_SITE_DOMAIN is mandatory on this stack (compose
# guards it with :?), so without the flag this would rewrite the Site on EVERY
# boot -- silently reverting any correction a Platform Admin made through the
# settings UI, which restart: unless-stopped makes routine. Env seeds the value
# once; the UI owns it thereafter.
# --name too: Django ships Site #1 with name AND domain as "example.com", and
# allauth prefixes every account email subject with "[{site.name}] ". The
# ${VAR:+...} form omits the flag entirely when DJANGO_SITE_NAME is unset.
"$VENV_PY" manage.py set_site_domain --only-if-placeholder \
  ${DJANGO_SITE_NAME:+--name "$DJANGO_SITE_NAME"}

# Only when fully specified: init_platform fails fast on missing credentials
# when non-interactive, which must not stop a healthy instance from booting.
if [ -n "${INIT_ADMIN_USERNAME:-}" ] \
   && [ -n "${INIT_ADMIN_EMAIL:-}" ] \
   && [ -n "${INIT_ADMIN_PASSWORD:-}" ]; then
  echo "==> init_platform"
  "$VENV_PY" manage.py init_platform
else
  echo "==> init_platform skipped (INIT_ADMIN_* not fully set)"
fi

# `docker compose run app <cmd>` must run <cmd>, not silently boot a web server.
if [ "$#" -gt 0 ]; then
  echo "==> exec $*"
  exec "$@"
fi

echo "==> gunicorn"
# The venv binary directly, NOT `uv run gunicorn`: gunicorn must be PID 1 so it
# receives SIGTERM itself. With --timeout 1800 chosen so a 25-minute import is
# not killed, a TERM swallowed by an intermediate process is a data-loss path.
#
# --timeout 1800: a multi-GB course import occupies one worker for ~25 minutes
# of sustained upload; the 30s default would kill it mid-stage.
# --threads: keeps the site responsive while one worker is consumed by that import.
exec /app/.venv/bin/gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-1800}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-120}" \
  --access-logfile - \
  --error-logfile -
