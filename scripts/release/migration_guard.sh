#!/usr/bin/env bash
# Migration guard for release deploys (B2; spec §5 of
# docs/superpowers/specs/2026-09-27-b2-release-deploys-design.md).
#
#   migration_guard.sh <current-sha> <target-sha>
#   exit 0 = pass, non-zero = refuse; reasons on stderr.
#   Run with the current directory inside a clone that holds both commits.
#
# FROZEN CROSS-VERSION CONTRACT. deploy.sh runs the copy of this file found at
# OLD release tags, and old deploy.sh versions run the copy at newer ones. So:
# never change the arguments or the exit-code meaning, never source another
# file, never need anything beyond bash, git and coreutils (no jq), and never
# delete this file. Add checks; for anything else, add a new script name.
set -euo pipefail

refuse() {
  echo "migration guard: refuse: $*" >&2
  exit 1
}

[ "$#" -eq 2 ] || refuse "usage: migration_guard.sh <current-sha> <target-sha>"
current=$1
target=$2

# 1. A re-deploy of the version the box is on always passes. It is the failure
#    table's recovery path, so no later rule may block it.
if [ "$current" = "$target" ]; then
  echo "migration guard: same version, pass" >&2
  exit 0
fi

# 2. Both commits must exist here, before anything reads them.
git cat-file -e "$current^{commit}" 2>/dev/null || refuse "current commit unknown: $current"
git cat-file -e "$target^{commit}" 2>/dev/null || refuse "target commit unknown: $target"

# 3. Postgres major, in BOTH directions. The pgdata volume is initialised by one
#    major and refused by any other, so either direction takes the site down
#    after `up`. Anchored on `image: postgres:` -- a bare `postgres:` also
#    matches DATABASE_URL. Exactly one such line, with leading digits, or refuse.
pg_major() {
  git show "$1:docker-compose.prod.yml" 2>/dev/null | awk '
    /^[[:space:]]*image:[[:space:]]*postgres:/ {
      n++
      tag = $0
      sub(/^[[:space:]]*image:[[:space:]]*postgres:/, "", tag)
      sub(/[[:space:]].*$/, "", tag)
      sub(/\r$/, "", tag)
      if (match(tag, /^[0-9]+/)) major = substr(tag, 1, RLENGTH); else major = ""
    }
    END { if (n == 1 && major != "") print major }'
}
cur_pg="$(pg_major "$current")" || cur_pg=""
tgt_pg="$(pg_major "$target")" || tgt_pg=""
[ -n "$cur_pg" ] || refuse "cannot read the postgres image line at $current (docker-compose.prod.yml)"
[ -n "$tgt_pg" ] || refuse "cannot read the postgres image line at $target (docker-compose.prod.yml)"
[ "$cur_pg" = "$tgt_pg" ] \
  || refuse "postgres major changes ($cur_pg -> $tgt_pg); that is a manual dump-and-restore procedure, not a release deploy"

# 4. Ancestry. An upgrade is only an upgrade when current is an ancestor of
#    target -- "not a downgrade" is not the same thing.
if git merge-base --is-ancestor "$current" "$target"; then
  echo "migration guard: upgrade, pass" >&2
  exit 0
fi
if ! git merge-base --is-ancestor "$target" "$current"; then
  refuse "the two versions have diverged ($current vs $target); the box may hold migrations the target lacks"
fi

# A downgrade. uv.lock is in the list because Django contrib and allauth
# migrations live in the venv: a dependency bump can migrate the schema with no
# repo migration changing. Conservative on purpose (D3).
changed="$(git diff --name-only "$target" "$current" -- '*/migrations/*.py' uv.lock)"
if [ -n "$changed" ]; then
  {
    echo "migration guard: refuse: rolling back from $current to $target crosses:"
    printf '  %s\n' $changed
    echo "  Restore from a backup taken before the newer version instead: docs/backup-and-restore.md"
  } >&2
  exit 1
fi
echo "migration guard: downgrade with no migration between, pass" >&2
exit 0
