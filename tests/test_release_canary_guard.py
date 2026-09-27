"""scripts/release/canary_guard.py -- D2's guard (spec §4)."""

import json
import os
import shlex
import subprocess
import sys

import pytest

from tests.release_harness import ROOT
from tests.release_harness import commit_all
from tests.release_harness import git
from tests.release_harness import init_repo
from tests.release_harness import posix
from tests.release_harness import write

GUARD = ROOT / "scripts/release/canary_guard.py"
REPO = "o/r"

FAKE_GH = """
import json, os, sys
responses = json.load(open(os.environ["FAKE_GH_RESPONSES"], encoding="utf-8"))
path = sys.argv[2]
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as fh:
    fh.write(path + "\\n")
body = responses.get(path.split("?")[0], 404)
if body == 404:
    print("gh: Not Found (HTTP 404)", file=sys.stderr)
    sys.exit(1)
print(json.dumps(body))
"""


def run(
    sha, run_id, head_branch="master", event="push", path=".github/workflows/deploy.yml"
):
    return {
        "id": run_id,
        "head_sha": sha,
        "head_branch": head_branch,
        "event": event,
        "path": path,
        "created_at": f"2026-09-27T10:00:{run_id % 60:02d}Z",
    }


def job(conclusion, name="deploy"):
    return {"name": name, "conclusion": conclusion}


@pytest.fixture
def repo(tmp_path):
    r = init_repo(tmp_path / "r")
    write(r / "a", "a\n")
    on_master = commit_all(r, "on master")
    git(r, "update-ref", "refs/remotes/origin/master", on_master)
    git(r, "checkout", "-q", "-b", "side")
    write(r / "b", "b\n")
    off_master = commit_all(r, "off master")
    git(r, "checkout", "-q", "master")
    return r, on_master, off_master


def _guard(tmp_path, repo_dir, responses, *args):
    stub = tmp_path / "fake_gh.py"
    write(stub, FAKE_GH)
    resp = tmp_path / "responses.json"
    write(resp, json.dumps(responses))
    log = tmp_path / "gh.log"
    write(log, "")
    env = dict(
        os.environ,
        LIBLI_GH=shlex.join([posix(sys.executable), posix(stub)]),
        FAKE_GH_RESPONSES=str(resp),
        FAKE_GH_LOG=str(log),
        GITHUB_REPOSITORY=REPO,
    )
    env.pop("GITHUB_STEP_SUMMARY", None)
    result = subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, str(GUARD), *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        env=env,
    )
    return result, log.read_text(encoding="utf-8")


LIST = f"repos/{REPO}/actions/workflows/deploy.yml/runs"


def RUN(i):
    return f"repos/{REPO}/actions/runs/{i}"


def JOBS(i):
    return f"repos/{REPO}/actions/runs/{i}/jobs"


def test_listing_finds_a_green_master_push(tmp_path, repo):
    r, sha, _ = repo
    result, log = _guard(
        tmp_path,
        r,
        {
            LIST: {"workflow_runs": [run(sha, 7)]},
            JOBS(7): {"jobs": [job("success"), job("success", "publish")]},
        },
        sha,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "7"
    assert "filter=all" in log


def test_listing_refuses_a_red_deploy_job(tmp_path, repo):
    r, sha, _ = repo
    result, _ = _guard(
        tmp_path,
        r,
        {
            LIST: {"workflow_runs": [run(sha, 7)]},
            JOBS(7): {"jobs": [job("failure")]},
        },
        sha,
    )
    assert result.returncode != 0
    assert "no successful deploy" in result.stderr


def test_listing_refuses_when_there_is_no_run(tmp_path, repo):
    r, sha, _ = repo
    result, _ = _guard(tmp_path, r, {LIST: {"workflow_runs": []}}, sha)
    assert result.returncode != 0
    assert "no master deploy run" in result.stderr


def test_a_commit_not_on_master_is_refused(tmp_path, repo):
    """Mutant: drop the merge-base check."""
    r, _, off = repo
    result, _ = _guard(
        tmp_path,
        r,
        {
            LIST: {"workflow_runs": [run(off, 7)]},
            JOBS(7): {"jobs": [job("success")]},
        },
        off,
    )
    assert result.returncode != 0
    assert "not on master" in result.stderr


def test_a_skipped_jobs_success_run_from_a_feature_dispatch_is_refused(tmp_path, repo):
    """The run concludes `success` with every job skipped. Two independent
    defences stop it -- `head_branch == master` and the deploy JOB's
    conclusion -- so no single mutant turns this red. Mutant (both at once):
    drop the head_branch check AND read the run's own conclusion."""
    r, sha, _ = repo
    feature = dict(
        run(sha, 7, head_branch="feature", event="workflow_dispatch"),
        conclusion="success",
    )
    result, _ = _guard(
        tmp_path,
        r,
        {
            LIST: {"workflow_runs": [feature]},
            JOBS(7): {"jobs": [job("skipped")]},
        },
        sha,
    )
    assert result.returncode != 0
    assert "no master deploy run" in result.stderr


def test_by_id_passes_for_a_matching_run(tmp_path, repo):
    r, sha, _ = repo
    result, log = _guard(
        tmp_path,
        r,
        {
            RUN(9): run(sha, 9),
            JOBS(9): {"jobs": [job("success")]},
        },
        sha,
        "9",
    )
    assert result.returncode == 0, result.stderr
    assert "filter=all" in log


def test_by_id_refuses_a_run_for_another_commit(tmp_path, repo):
    r, sha, _ = repo
    result, _ = _guard(
        tmp_path,
        r,
        {
            RUN(9): run("f" * 40, 9),
            JOBS(9): {"jobs": [job("success")]},
        },
        sha,
        "9",
    )
    assert result.returncode != 0
    assert "is not a master deploy" in result.stderr


def test_by_id_refuses_a_run_of_another_workflow(tmp_path, repo):
    """deploy-release.yml also has a job named `deploy` that runs as a master
    workflow_dispatch. Mutant: drop the `path` check."""
    r, sha, _ = repo
    other = run(
        sha, 9, event="workflow_dispatch", path=".github/workflows/deploy-release.yml"
    )
    result, _ = _guard(
        tmp_path, r, {RUN(9): other, JOBS(9): {"jobs": [job("success")]}}, sha, "9"
    )
    assert result.returncode != 0
    assert "is not a master deploy" in result.stderr


def test_a_404_on_the_listing_is_a_refusal_not_a_traceback(tmp_path, repo):
    r, sha, _ = repo
    result, _ = _guard(tmp_path, r, {}, sha)
    assert result.returncode == 1
    assert "refuse: the deploy.yml runs listing was not found" in result.stderr
    assert "Traceback" not in result.stderr


def test_by_id_404_is_its_own_refusal(tmp_path, repo):
    r, sha, _ = repo
    result, _ = _guard(tmp_path, r, {}, sha, "9")
    assert result.returncode != 0
    assert "canary run 9 no longer exists" in result.stderr


@pytest.mark.parametrize("by_id", [False, True])
def test_a_later_failed_rerun_does_not_undo_a_green_attempt(tmp_path, repo, by_id):
    """Jobs are read with filter=all; any attempt's green deploy job counts.
    Mutant: require every deploy job entry to be green (or use filter=latest)."""
    r, sha, _ = repo
    responses = {
        LIST: {"workflow_runs": [run(sha, 7)]},
        RUN(7): run(sha, 7),
        JOBS(7): {"jobs": [job("success"), job("failure")]},
    }
    args = (sha, "7") if by_id else (sha,)
    result, _ = _guard(tmp_path, r, responses, *args)
    assert result.returncode == 0, result.stderr


def test_refusals_reach_the_step_summary(tmp_path, repo):
    r, sha, _ = repo
    summary = tmp_path / "summary.md"
    write(summary, "")
    stub = tmp_path / "fake_gh.py"
    write(stub, FAKE_GH)
    resp = tmp_path / "responses.json"
    write(resp, "{}")
    env = dict(
        os.environ,
        LIBLI_GH=shlex.join([posix(sys.executable), posix(stub)]),
        FAKE_GH_RESPONSES=str(resp),
        FAKE_GH_LOG=str(tmp_path / "log"),
        GITHUB_REPOSITORY=REPO,
        GITHUB_STEP_SUMMARY=str(summary),
    )
    subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, str(GUARD), sha, "9"],
        cwd=r,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "refuse: canary run 9 no longer exists" in summary.read_text(
        encoding="utf-8"
    )
