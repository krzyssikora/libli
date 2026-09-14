#!/usr/bin/env bash
# Run a manage.py command inside the production app container, from any directory:
#
#   bash /opt/libli/manage.sh shell_plus              # interactive shell
#   bash /opt/libli/manage.sh shell < query.py        # a script on stdin
#   bash /opt/libli/manage.sh purge_notifications     # cron, docs/deployment.md §7
#
# Invoked through `bash`, like deploy.sh: git on Windows records no execute bit.
set -euo pipefail

APP_DIR=/opt/libli
cd "$APP_DIR"

# A TTY only when stdin AND stdout are both a terminal. Interactive commands
# (shell_plus, init_platform) need one for their prompts; cron has none, and a
# script piped to stdin must reach python as plain input. Checking stdin alone is
# not enough: `x=$(bash manage.sh shell -c ...)` typed at a terminal still has a
# terminal stdin, and a TTY turns every "\n" of the output into "\r\n" -- so x
# would silently end in a carriage return.
tty_flag=()
if [ ! -t 0 ] || [ ! -t 1 ]; then
  tty_flag=(-T)
fi

# Deliberately not `exec docker ...`: tests/test_manage_wiring.py stubs docker as
# a shell function, which `exec` cannot run. The exit status reaches the caller
# either way, through `set -e`.
docker compose -f docker-compose.prod.yml --env-file .env.production \
  exec "${tty_flag[@]}" app /app/.venv/bin/python manage.py "$@"
