#!/usr/bin/env python3
"""Canary guard (B2, spec §4): refuse unless libli.pl deployed <commit> green.

    canary_guard.py <commit>            Cut release: find the run; prints its id
    canary_guard.py <commit> <run-id>   Deploy release: check that exact run

<commit> is a 40-hex COMMIT sha -- callers peel tags first.

"libli.pl ran X" is measured as: a deploy.yml run for X, on master, from a push
or a dispatch, whose `deploy` JOB succeeded in any attempt. The run's own
conclusion is not enough (a feature-branch dispatch skips every job and still
concludes `success`), and the check is only sound because of D9: deploy.yml
passes LIBLI_DEPLOY_EXPECT_SHA, so a green deploy job can only have deployed
its own head_sha.

Runs `gh` (or the command in LIBLI_GH), which needs GH_TOKEN in Actions.
"""

import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _release_common import Refuse  # noqa: E402
from _release_common import git  # noqa: E402
from _release_common import run_main  # noqa: E402

WORKFLOW_PATH = ".github/workflows/deploy.yml"
SHA_RE = re.compile(r"[0-9a-f]{40}")


class NotFound(Exception):
    pass


def repo():
    return os.environ.get("GITHUB_REPOSITORY", "krzyssikora/libli")


def gh_api(path):
    cmd = shlex.split(os.environ.get("LIBLI_GH", "gh")) + ["api", path]
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603 -- LIBLI_GH/gh on PATH
    if result.returncode != 0:
        if "404" in result.stderr or "Not Found" in result.stderr:
            raise NotFound(path)
        raise Refuse(f"the GitHub API call for {path.split('?')[0]} failed")
    return json.loads(result.stdout)


def is_master_deploy(run, commit):
    return (
        str(run.get("path", "")).split("@")[0] == WORKFLOW_PATH
        and run.get("head_sha") == commit
        and run.get("head_branch") == "master"
        and run.get("event") in ("push", "workflow_dispatch")
    )


def deploy_job_succeeded(jobs):
    return any(
        j.get("name") == "deploy" and j.get("conclusion") == "success" for j in jobs
    )


def jobs_for(run_id):
    return gh_api(
        f"repos/{repo()}/actions/runs/{run_id}/jobs?filter=all&per_page=100"
    ).get("jobs", [])


def check(commit, run_id=None):
    if not SHA_RE.fullmatch(commit):
        raise Refuse("the commit must be a full 40-hex sha")
    if git("merge-base", "--is-ancestor", commit, "origin/master").returncode != 0:
        raise Refuse(f"{commit} is not on master")
    if run_id is None:
        try:
            runs = gh_api(
                f"repos/{repo()}/actions/workflows/deploy.yml/runs?head_sha={commit}&per_page=100"
            ).get("workflow_runs", [])
        except NotFound:
            raise Refuse("the deploy.yml runs listing was not found") from None
        candidates = [r for r in runs if is_master_deploy(r, commit)]
        if not candidates:
            raise Refuse(
                f"no master deploy run of {commit} (a commit inside a multi-commit "
                "push never gets its own run -- tag the tip instead)"
            )
        for run in sorted(
            candidates, key=lambda r: r.get("created_at", ""), reverse=True
        ):
            try:
                jobs = jobs_for(run["id"])
            except NotFound:
                continue  # deleted between the listing and this call
            if deploy_job_succeeded(jobs):
                return str(run["id"])
        raise Refuse(f"libli.pl has no successful deploy of {commit}")
    if not re.fullmatch(r"[0-9]+", run_id):
        raise Refuse("the canary run id must be a number")
    try:
        run = gh_api(f"repos/{repo()}/actions/runs/{run_id}")
        jobs = jobs_for(run_id)
    except NotFound:
        raise Refuse(f"canary run {run_id} no longer exists") from None
    if not is_master_deploy(run, commit):
        raise Refuse(f"run {run_id} is not a master deploy of {commit}")
    if not deploy_job_succeeded(jobs):
        raise Refuse(f"libli.pl has no successful deploy of {commit} (run {run_id})")
    return run_id


def main():
    args = sys.argv[1:]
    if len(args) not in (1, 2):
        raise Refuse("usage: canary_guard.py <commit> [<run-id>]")
    print(check(*args))


if __name__ == "__main__":
    run_main(main)
