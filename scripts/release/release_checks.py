#!/usr/bin/env python3
"""Release checks for B2 (spec §1, §2).

    release_checks.py resolve <version> <commit-ish>   -> sha=<40 hex>
    release_checks.py tag <version>                    -> target_sha=..., run_id=...
    release_checks.py containment <sha>                -> (nothing; exit 0)

Output lines are key=value, for $GITHUB_OUTPUT. Runs git in the current
directory, which must be a full clone (fetch-depth: 0) with tags.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _release_common import Refuse  # noqa: E402
from _release_common import git  # noqa: E402
from _release_common import run_main  # noqa: E402

VERSION_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
CANARY_RE = re.compile(r"canary-run: ([0-9]+)")
B2_MARKERS = ("LIBLI_DEPLOY_REF", "LIBLI_DEPLOY_EXPECT_SHA")


def check_version(version):
    if not VERSION_RE.fullmatch(version):
        raise Refuse("version must be vX.Y.Z (e.g. v1.0.0), with no spaces")


def _tag_exists(version):
    result = git("rev-parse", "--verify", "--quiet", f"refs/tags/{version}")
    return result.returncode == 0


def resolve(version, commitish):
    check_version(version)
    if _tag_exists(version):
        raise Refuse(f"tag {version} already exists")
    result = git("rev-parse", "--verify", "--quiet", f"{commitish}^{{commit}}")
    if result.returncode != 0:
        raise Refuse(f"{commitish} does not resolve to a commit")
    return {"sha": result.stdout.strip()}


def inspect_tag(version):
    check_version(version)
    if not _tag_exists(version):
        raise Refuse(f"no tag {version}")
    if git("cat-file", "-t", f"refs/tags/{version}").stdout.strip() != "tag":
        raise Refuse(
            f"{version} is a lightweight tag; releases are annotated tags made by "
            "Cut release"
        )
    contents = git("tag", "-l", "--format=%(contents)", version).stdout
    ids = [
        m.group(1)
        for ln in contents.splitlines()
        if (m := CANARY_RE.fullmatch(ln.rstrip()))
    ]
    if not ids:
        raise Refuse(f"tag {version} has no canary-run line")
    if len(ids) > 1:
        raise Refuse(f"tag {version} has more than one canary-run line")
    target = git("rev-parse", "--verify", f"{version}^{{commit}}").stdout.strip()
    return {"target_sha": target, "run_id": ids[0]}


def containment(sha):
    for marker in B2_MARKERS:
        if git("grep", "-q", marker, sha, "--", "deploy.sh").returncode != 0:
            raise Refuse(
                f"the deploy.sh at {sha} predates B2 (no {marker}); "
                "release a later commit"
            )
    guard_path = f"{sha}:scripts/release/migration_guard.sh"
    if git("cat-file", "-e", guard_path).returncode != 0:
        raise Refuse(
            f"{sha} has no scripts/release/migration_guard.sh; release a later commit"
        )


def main():
    args = sys.argv[1:]
    if args[:1] == ["resolve"] and len(args) == 3:
        out = resolve(args[1], args[2])
    elif args[:1] == ["tag"] and len(args) == 2:
        out = inspect_tag(args[1])
    elif args[:1] == ["containment"] and len(args) == 2:
        containment(args[1])
        return
    else:
        raise Refuse(
            "usage: release_checks.py resolve <v> <commit> | tag <v> | "
            "containment <sha>"
        )
    for key, value in out.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    run_main(main)
