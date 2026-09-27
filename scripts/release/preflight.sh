#!/usr/bin/env bash
# Pre-flight for a school deploy (B2; spec §2 step 4). Sent over ssh on stdin:
#   ssh <box> bash -s -- <version> <target-sha> < scripts/release/preflight.sh
#   ssh <box> bash -s -- --read-only             < scripts/release/preflight.sh
#
# .env.production holds every box secret, so it is parsed HERE and never
# copied off the box. Output on stdout, exactly:
#   image_tag=sha-<40 hex>
#   channel=release          (not printed in --read-only mode)
# or one line `refuse: <reason>` and exit 1. No refusal echoes a line of the
# file, and none names the host.
set -euo pipefail

APP_DIR=/opt/libli
GIT_FETCH_ATTEMPTS=${GIT_FETCH_ATTEMPTS:-3}
GIT_FETCH_DELAY=${GIT_FETCH_DELAY:-5}

refuse() {
  echo "refuse: $*"
  exit 1
}

# channel_state, image_tag_read and image_tag_state are VERBATIM copies of
# deploy.sh's. Not a sourced helper on purpose (deploy.sh runs as a temp copy at
# the target release); tests/release_fixtures.py holds both to the same cases.
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

# A file saved on Windows makes every rule fail at once; say why.
crlf_hint() {
  if grep -q $'\r' .env.production; then
    echo " (.env.production has CRLF line endings; convert it to LF)"
  fi
}

main() {
  local mode=deploy version target_sha tag attempt got
  if [ "${1:-}" = --read-only ]; then
    mode=read
    shift
  fi
  cd "$APP_DIR" 2> /dev/null || refuse "no checkout at $APP_DIR"
  [ -r .env.production ] || refuse ".env.production is missing"

  tag="$(image_tag_state .env.production)"
  case "$tag" in
    absent) refuse "LIBLI_IMAGE_TAG absent in .env.production$(crlf_hint)" ;;
    invalid) refuse "LIBLI_IMAGE_TAG malformed in .env.production (need exactly one line LIBLI_IMAGE_TAG=sha-<40 hex>)$(crlf_hint)" ;;
  esac
  if [ "$mode" = read ]; then
    echo "image_tag=$tag"
    return 0
  fi

  version=${1:-}
  target_sha=${2:-}
  [[ $version =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || refuse "version is not vX.Y.Z"
  [[ $target_sha =~ ^[0-9a-f]{40}$ ]] || refuse "target sha is not 40 hex"
  [ "$(channel_state .env.production)" = release ] \
    || refuse "LIBLI_DEPLOY_CHANNEL is not exactly 'release' in .env.production (docs/deployment.md §9)$(crlf_hint)"

  # Forced: a tag deleted and re-cut under the same name must replace the box's
  # stale local one, or the box would deploy a commit the canary never checked.
  attempt=1
  until git fetch -q origin "+refs/tags/$version:refs/tags/$version" > /dev/null 2>&1; do
    if [ "$attempt" -ge "$GIT_FETCH_ATTEMPTS" ]; then
      refuse "cannot fetch $version after $GIT_FETCH_ATTEMPTS attempts: a transient GitHub refusal (re-run the workflow) or a missing/broken deploy key (docs/deployment.md §9)"
    fi
    attempt=$((attempt + 1))
    sleep "$GIT_FETCH_DELAY"
  done
  got="$(git rev-parse --verify --quiet "$version^{commit}")" || refuse "$version does not resolve to a commit on the box"
  [ "$got" = "$target_sha" ] || refuse "$version resolves to a different commit on the box than the one checked (was the tag re-cut?)"

  echo "image_tag=$tag"
  echo "channel=release"
}

main "$@"; exit
