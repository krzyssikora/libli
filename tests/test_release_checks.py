"""scripts/release/release_checks.py -- version, tag and B2-containment checks."""

import os
import subprocess
import sys

import pytest

from tests.release_harness import ROOT
from tests.release_harness import commit_all
from tests.release_harness import git
from tests.release_harness import init_repo
from tests.release_harness import write

CHECKS = ROOT / "scripts/release/release_checks.py"


def _run(repo, *args):
    env = dict(os.environ)
    env.pop("GITHUB_STEP_SUMMARY", None)
    return subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, str(CHECKS), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


def _b2_tree(repo, *, ref=True, expect=True, guard=True):
    body = "#!/usr/bin/env bash\n"
    body += "# LIBLI_DEPLOY_REF\n" if ref else ""
    body += "# LIBLI_DEPLOY_EXPECT_SHA\n" if expect else ""
    write(repo / "deploy.sh", body)
    if guard:
        write(repo / "scripts/release/migration_guard.sh", "#!/usr/bin/env bash\n")


@pytest.fixture
def repo(tmp_path):
    r = init_repo(tmp_path / "r")
    _b2_tree(r)
    sha = commit_all(r, "b2")
    return r, sha


@pytest.mark.parametrize(
    "bad", [" v1.0.0", "v1.0.0 ", "V1.0.0", "1.0.0", "v1.0", "v1.0.0-rc1"]
)
def test_a_malformed_version_is_refused_with_the_format_message(repo, bad):
    """Review focus 2."""
    r, sha = repo
    for args in (("resolve", bad, sha), ("tag", bad)):
        result = _run(r, *args)
        assert result.returncode != 0
        assert "vX.Y.Z" in result.stderr


def test_resolve_turns_a_short_sha_into_the_full_one(repo):
    r, sha = repo
    result = _run(r, "resolve", "v1.0.0", sha[:8])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"sha={sha}"


def test_resolve_refuses_an_existing_tag(repo):
    r, sha = repo
    git(r, "tag", "-a", "v1.0.0", sha, "-m", "x")
    result = _run(r, "resolve", "v1.0.0", sha)
    assert result.returncode != 0
    assert "already exists" in result.stderr


def test_tag_peels_an_annotated_tag_to_its_commit(repo):
    r, sha = repo
    git(r, "tag", "-a", "v1.0.0", sha, "-m", "Release v1.0.0", "-m", "canary-run: 42")
    result = _run(r, "tag", "v1.0.0")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"target_sha={sha}", "run_id=42"]


def test_a_lightweight_tag_is_refused_even_if_its_commit_says_canary_run(tmp_path):
    """Mutant: drop the cat-file -t check (%(contents) then reads the commit)."""
    r = init_repo(tmp_path / "r")
    _b2_tree(r)
    sha = commit_all(r, "canary-run: 42")
    git(r, "tag", "v1.0.0", sha)
    result = _run(r, "tag", "v1.0.0")
    assert result.returncode != 0
    assert "lightweight" in result.stderr


def test_an_annotated_tag_without_the_line_is_refused(repo):
    r, sha = repo
    git(r, "tag", "-a", "v1.0.0", sha, "-m", "Release v1.0.0")
    result = _run(r, "tag", "v1.0.0")
    assert result.returncode != 0
    assert "no canary-run line" in result.stderr


def test_two_canary_run_lines_are_refused_and_trailing_space_is_tolerated(repo):
    """Review focus 5."""
    r, sha = repo
    git(r, "tag", "-a", "v1.0.0", sha, "-m", "R", "-m", "canary-run: 1\ncanary-run: 2")
    assert "more than one" in _run(r, "tag", "v1.0.0").stderr
    # --cleanup=verbatim: git tag's default cleanup strips trailing whitespace,
    # which would leave the .rstrip() in inspect_tag untested.
    git(
        r,
        "tag",
        "--cleanup=verbatim",
        "-a",
        "v1.0.1",
        sha,
        "-m",
        "R\n\ncanary-run: 7   ",
    )
    result = _run(r, "tag", "v1.0.1")
    assert result.returncode == 0, result.stderr
    assert "run_id=7" in result.stdout


def test_a_missing_tag_is_refused(repo):
    r, sha = repo
    result = _run(r, "tag", "v9.9.9")
    assert result.returncode != 0
    assert "no tag v9.9.9" in result.stderr


def test_containment_passes_a_b2_commit(repo):
    r, sha = repo
    assert _run(r, "containment", sha).returncode == 0


@pytest.mark.parametrize(
    "missing,kw",
    [
        ("LIBLI_DEPLOY_REF", {"ref": False}),
        ("LIBLI_DEPLOY_EXPECT_SHA", {"expect": False}),
        ("migration_guard.sh", {"guard": False}),
    ],
)
def test_containment_refuses_a_pre_b2_commit(tmp_path, missing, kw):
    """Mutants: drop each of the three checks."""
    r = init_repo(tmp_path / "r")
    _b2_tree(r, **kw)
    sha = commit_all(r, "old")
    result = _run(r, "containment", sha)
    assert result.returncode != 0
    assert missing in result.stderr
