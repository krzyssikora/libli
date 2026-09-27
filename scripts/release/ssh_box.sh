#!/usr/bin/env bash
# The one ssh invocation for release deploys (B2; spec §2). Every option is
# pinned here so no workflow step can quietly drop one:
#   BatchMode, ConnectTimeout, ServerAlive*   fail fast and legibly, never hang
#   StrictHostKeyChecking=yes + UserKnownHostsFile
#                                             enforce the host_key pinned in
#                                             SCHOOL_HOSTS; never the lax
#                                             StrictHostKeyChecking modes,
#                                             which on an ephemeral runner
#                                             trust whatever answers
#   IdentitiesOnly                            offer only SCHOOLS_SSH_KEY
#
# Usage: ssh_box.sh <dir> <remote command...>
# <dir> holds host and known_hosts (inventory.py entry) and key (the workflow).
set -euo pipefail

dir=$1
shift
host="$(head -n 1 "$dir/host")"
exec ssh -i "$dir/key" \
  -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=4 \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$dir/known_hosts" \
  -o IdentitiesOnly=yes \
  "root@$host" "$@"
