#!/usr/bin/env bash
# Detached deploy bootstrap for a school box (B2; spec §2 step 6). Sent over ssh:
#   ssh <box> bash -s -- <version> <target-sha> < scripts/release/remote_deploy.sh
#
# Runs the deploy.sh that the TARGET tag ships (bash must parse that version),
# without moving the checkout itself: only deploy.sh does that, under the lock
# backup.sh also takes. The run is DETACHED from this session, so a dropped ssh
# connection (job timeout, cancel) cannot kill it mid-pull or mid-up: a non-pty
# session sends the command no signal, and it would otherwise die of SIGPIPE at
# its next write. This session only follows the log and relays the status.
#
# The env names handed to deploy.sh are a FROZEN CROSS-VERSION CONTRACT: this
# file comes from master, the deploy.sh it runs from an older release tag.
set -euo pipefail

APP_DIR=/opt/libli
STATE_DIR=/var/lib/libli-deploy
LOG_DIR=/var/log/libli-deploy
PID_WAIT_SECONDS=30

# A rollback to a release whose deploy.sh predates a variable this script
# passes would silently drop it, so refuse instead.
REQUIRED_VARS="LIBLI_DEPLOY_REF LIBLI_DEPLOY_EXPECT_SHA LIBLI_DEPLOY_SKIP_FETCH"

main() {
  local version=${1:-} target_sha=${2:-}
  local script var status pidf log pid rc i
  [[ $version =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "!! version is not vX.Y.Z" >&2; exit 1; }
  [[ $target_sha =~ ^[0-9a-f]{40}$ ]] || { echo "!! target sha is not 40 hex" >&2; exit 1; }

  cd "$APP_DIR"
  # Neither exists on a freshly provisioned box.
  mkdir -p -m 700 "$STATE_DIR" "$LOG_DIR"
  # Status/pid files left by a session that dropped before collecting them.
  find "$STATE_DIR" -maxdepth 1 -type f -mmin +60 -delete
  # Deploy logs name the school's domain -- an unmasked copy on the box, so
  # keep only the newest 19 before adding this run's (at most 20 exist).
  find "$LOG_DIR" -maxdepth 1 -type f -name '*.log' -printf '%T@ %p\n' \
    | sort -rn | tail -n +20 | cut -d' ' -f2- | xargs -r rm -f --

  script="$(mktemp)"
  if ! git show "refs/tags/$version:deploy.sh" > "$script" 2> /dev/null; then
    rm -f "$script"
    echo "!! no deploy.sh at $version in the box's clone; refusing" >&2
    exit 1
  fi
  for var in $REQUIRED_VARS; do
    if ! grep -q "$var" "$script"; then
      rm -f "$script"
      echo "!! the deploy.sh at $version does not know $var; refusing (it predates this machinery)" >&2
      exit 1
    fi
  done

  # Unique paths, created by the wrapper, not here: an absent status file is
  # how a run that died without recording one is recognised.
  status="$(mktemp "$STATE_DIR/status.XXXXXX")"
  pidf="$(mktemp "$STATE_DIR/pid.XXXXXX")"
  rm -f "$status" "$pidf"
  # Created BEFORE the run starts, so the follower below never races a missing
  # file (plain `tail -f` exits at once on one).
  log="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ)-$version.log"
  : > "$log"

  # Everything the wrapper needs arrives as POSITIONAL ARGUMENTS: a
  # single-quoted body cannot see this shell's unexported variables. No fd is
  # shared with the session: this script itself is on the session's stdin, so
  # an inherited stdin would let any child swallow the rest of it, and an
  # inherited stdout both holds sshd's session open and brings back SIGPIPE.
  # The wrapper's own pid ($$) is what the follower waits on -- never $! of
  # setsid, which forks when its caller leads a process group.
  setsid nohup bash -c '
    echo "$$" > "$4"
    LIBLI_DEPLOY_REF="$2" LIBLI_DEPLOY_EXPECT_SHA="$3" LIBLI_DEPLOY_SKIP_FETCH=1 bash "$1"
    rc=$?
    rm -f "$1"
    echo "$rc" > "$5.tmp" && mv "$5.tmp" "$5"
  ' remote-deploy-wrapper "$script" "$version" "$target_sha" "$pidf" "$status" \
    < /dev/null >> "$log" 2>&1 &

  i=0
  until [ -s "$pidf" ]; do
    i=$((i + 1))
    if [ "$i" -gt $((PID_WAIT_SECONDS * 10)) ]; then
      # The temp script is deliberately left in place: a late-starting wrapper
      # still needs it, and removes it itself when done. If the wrapper never
      # starts, one small file stays in /tmp -- accepted.
      echo "!! the detached run has not reported its pid after ${PID_WAIT_SECONDS} s -- it may still start; check the box's LIBLI_IMAGE_TAG and the deploy log $log" >&2
      exit 1
    fi
    sleep 0.1
  done
  pid="$(head -n 1 "$pidf")"

  tail -n +1 --pid="$pid" -f "$log"

  rm -f "$pidf"
  if [ ! -s "$status" ]; then
    echo "!! the detached run recorded no status; check the box's LIBLI_IMAGE_TAG and the deploy log $log" >&2
    exit 1
  fi
  rc="$(head -n 1 "$status")"
  rm -f "$status"
  exit "$rc"
}

main "$@"; exit
