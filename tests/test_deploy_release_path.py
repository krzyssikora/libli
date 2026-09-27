"""deploy.sh on a release-channel school box, and the by-hand ref path."""

from pathlib import Path

import pytest

from tests.release_harness import BASH
from tests.release_harness import Box
from tests.release_harness import calls
from tests.release_harness import env_at_up
from tests.release_harness import git
from tests.release_harness import head
from tests.release_harness import on_branch
from tests.release_harness import run_deploy
from tests.release_harness import write

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not on PATH")

RELEASE = "LIBLI_DEPLOY_CHANNEL=release"


@pytest.fixture
def school(tmp_path):
    """v1.0.0 = A (deployed), v1.1.0 = B (no migration), v1.2.0 = M (migration)."""
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    b = box.commit(extra={"README": "b\n"}, msg="B")
    box.tag("v1.1.0", b)
    m = box.commit(migrations=["0002_more"], msg="M")
    box.tag("v1.2.0", m)
    box.clone(a, detached=True, image_tag=f"sha-{a}", channel_line=RELEASE)
    return box, a, b, m


def test_no_ref_is_refused_before_any_fetch_or_docker(school):
    box, a, b, m = school
    result = run_deploy(box)
    assert result.returncode != 0
    assert "release-channel box" in result.stderr
    assert "docker " not in calls(box)
    assert head(box) == a


def test_an_early_refusal_leaves_a_hand_edited_file_alone(school):
    """HEAD never moved (it equals the persisted tag's commit), so the trap must
    not force-checkout: `git checkout --force` onto the SAME commit still
    discards local edits to tracked files.

    Mutant: drop the `!= RESTORE_SHA` comparison in on_exit and always restore.
    """
    box, a, b, m = school
    write(box.app / "Caddyfile", "# patched during an incident\n")
    result = run_deploy(box)
    assert result.returncode != 0
    assert (box.app / "Caddyfile").read_text() == "# patched during an incident\n"


@pytest.mark.parametrize("ref", ["master", "v1.0", "V1.1.0"])
def test_a_malformed_ref_is_refused(school, ref):
    box, a, b, m = school
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": ref})
    assert result.returncode != 0
    assert "vX.Y.Z" in result.stderr


def test_a_sha_ref_is_refused_on_a_release_box(school):
    box, a, b, m = school
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": b})
    assert result.returncode != 0
    assert "must be a vX.Y.Z tag on a release-channel box" in result.stderr


def test_an_upgrade_by_tag_deploys_it(school):
    box, a, b, m = school
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0"})
    assert result.returncode == 0, result.stderr
    assert head(box) == b and not on_branch(box)
    assert f"LIBLI_IMAGE_TAG=sha-{b}" in env_at_up(box)


def test_a_tag_present_only_after_the_fetch_is_guarded_and_deployed(school):
    """The clone predates v1.1.0 until deploy.sh fetches it. The guard must run
    AFTER the fetch. Mutant: move the `target="$(git rev-parse ...)"` line and
    the `run_migration_guards` call above the fetch block -- the tag is not yet
    in the clone, so the run goes RED on the return code ("does not resolve")."""
    box, a, b, m = school
    git(box.app, "tag", "-d", "v1.1.0")
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0"})
    assert result.returncode == 0, result.stderr
    assert head(box) == b


def test_a_downgrade_across_a_migration_is_refused_by_the_embedded_guard(tmp_path):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    m = box.commit(migrations=["0002_more"], msg="M")
    box.tag("v1.2.0", m)
    box.clone(m, detached=True, image_tag=f"sha-{m}", channel_line=RELEASE)
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.0.0"})
    assert result.returncode != 0
    assert "0002_more" in result.stderr
    assert "docker " not in calls(box)
    assert head(box) == m


def test_only_the_newer_guard_copy_refusing_is_enough(tmp_path):
    """The current release's guard refuses; the older target's would pass.

    Mutant: run only the target's copy in run_migration_guards.
    """
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    strict = "#!/usr/bin/env bash\necho 'newer guard: refuse' >&2\nexit 1\n"
    c = box.commit(guard=strict, extra={"README": "c\n"}, msg="C")
    box.tag("v1.3.0", c)
    box.clone(c, detached=True, image_tag=f"sha-{c}", channel_line=RELEASE)
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.0.0"})
    assert result.returncode != 0
    assert "newer guard: refuse" in result.stderr
    assert head(box) == c


def test_the_ref_fetch_retries(school):
    """The anonymous-401 flake hits tag fetches too. Mutant: call
    `git fetch origin "+refs/tags/..."` once instead of git_fetch_retry."""
    box, a, b, m = school
    git(box.app, "tag", "-d", "v1.1.0")
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0", "FAIL_FETCHES": "2"})
    assert result.returncode == 0, result.stderr
    assert head(box) == b
    assert Path(f"{box.log}.fetches").read_text().strip() == "3"


def test_a_stale_local_tag_is_replaced_by_the_forced_fetch(school):
    """Mutant: fetch with `git fetch origin tag <v>` (no +refspec)."""
    box, a, b, m = school
    git(box.app, "tag", "-f", "v1.1.0", a)
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0"})
    assert result.returncode == 0, result.stderr
    assert head(box) == b


def test_an_expected_sha_mismatch_is_refused(school):
    box, a, b, m = school
    result = run_deploy(
        box,
        env={"LIBLI_DEPLOY_REF": "v1.1.0", "LIBLI_DEPLOY_EXPECT_SHA": m},
    )
    assert result.returncode != 0
    assert "not the verified" in result.stderr
    assert head(box) == a


def test_an_absent_tag_on_a_release_box_is_refused_before_any_fetch(tmp_path):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    b = box.commit(extra={"README": "b\n"}, msg="B")
    box.clone(a, detached=True, image_tag=None, channel_line=RELEASE)
    box.tag("v1.1.0", b)  # on origin only, after the clone
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0"})
    assert result.returncode != 0
    assert "LIBLI_IMAGE_TAG absent" in result.stderr
    assert git(box.app, "tag", "-l", "v1.1.0") == ""


def test_a_duplicated_tag_line_on_a_release_box_is_refused(tmp_path):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(
        a,
        detached=True,
        image_tag=f"sha-{a}",
        channel_line=RELEASE,
        extra_env=f"LIBLI_IMAGE_TAG=sha-{a}\n",
    )
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.0.0"})
    assert result.returncode != 0
    assert "LIBLI_IMAGE_TAG unreadable" in result.stderr


@pytest.mark.parametrize(
    "line",
    [
        "#LIBLI_DEPLOY_CHANNEL=release",
        "LIBLI_DEPLOY_CHANNEL=",
        "export LIBLI_DEPLOY_CHANNEL=release",
        "  LIBLI_DEPLOY_CHANNEL=release",
        "LIBLI_DEPLOY_CHANNEL=relase",
        "LIBLI_DEPLOY_CHANNEL=Release",
    ],
)
def test_a_present_but_invalid_channel_line_is_refused(tmp_path, line):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(a, detached=True, image_tag=f"sha-{a}", channel_line=line)
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.0.0"})
    assert result.returncode != 0
    assert "not exactly 'release'" in result.stderr


def test_a_pull_failure_on_a_detached_box_restores_by_checkout(school):
    box, a, b, m = school
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": "v1.1.0", "FAIL_AT": "pull"})
    assert result.returncode != 0
    assert head(box) == a and not on_branch(box)


def test_libli_by_hand_sha_fetches_a_commit_the_clone_lacks(tmp_path):
    """The runbook's §8 recipe runs WITHOUT skip-fetch, through
    `git_fetch_retry "$ref"` with a bare sha. R is pushed after the clone (as
    master's tip, so the local bare origin advertises it).
    Mutant: fetch `"+refs/tags/$ref:refs/tags/$ref"` on the sha path too."""
    box = Box(tmp_path)
    p = box.commit(msg="P")
    box.clone(p, detached=False, image_tag=f"sha-{p}")
    r = box.commit(extra={"README": "r\n"}, msg="R")
    result = run_deploy(box, env={"LIBLI_DEPLOY_REF": r})
    assert result.returncode == 0, result.stderr
    assert head(box) == r


def test_libli_by_hand_sha_then_an_ordinary_run_returns_to_master(tmp_path):
    box = Box(tmp_path)
    p = box.commit(msg="P")
    q = box.commit(extra={"README": "q\n"}, msg="Q")
    box.clone(q, detached=False, image_tag=f"sha-{q}")
    git(box.app, "fetch", "-q", "origin")
    first = run_deploy(box, env={"LIBLI_DEPLOY_REF": p, "LIBLI_DEPLOY_SKIP_FETCH": "1"})
    assert first.returncode == 0, first.stderr
    assert head(box) == p and not on_branch(box)
    second = run_deploy(box)
    assert second.returncode == 0, second.stderr
    assert head(box) == q and on_branch(box)


def test_an_in_place_rewrite_of_the_running_script_changes_nothing(tmp_path):
    """While deploy.sh runs, its file is overwritten IN PLACE (same inode) with a
    version carrying, right after the `set` line, more blank lines than the
    whole old file is long and then one `echo NEW-FILE-EXECUTED` line. Without the
    `main "$@"; exit` wrapper bash resumes reading at its old byte offset --
    inside that block.

    Why in place rather than via `git checkout`: on Linux git replaces a file
    with a NEW inode, so a running bash keeps reading the old one and a
    checkout-based test could never go red. (On Windows git cannot replace an
    open file at all, and prompts interactively.) The wrapper is what makes
    every kind of rewrite safe; this pins it deterministically. Every other
    fixture commit shares a byte-identical deploy.sh, so no test checks out a
    different one while it runs.

    Mutant: delete `main() {`, its closing `}`, and `main "$@"; exit`, leaving
    the body at top level -- AND turn every `local` in that body into a plain
    assignment (`local` is an error outside a function, and `set -e` would
    exit before the rewrite happens). The RED must come from the
    NEW-FILE-EXECUTED assertion, not the return code; a mutant that fails
    only on the return code proves nothing about the wrapper.
    """
    box = Box(tmp_path)
    p = box.commit(msg="P")
    box.clone(p, detached=False, image_tag=f"sha-{p}")
    current = (box.app / "deploy.sh").read_text(encoding="utf-8")
    head_text, rest = current.split("set -euo pipefail\n", 1)
    # Blank lines longer than the whole old file, then ONE marker line: from
    # any old byte offset bash reads only empty commands until the marker. (A
    # block of repeated `echo` lines would usually be entered mid-line -- `cho
    # NEW...` exits 127 without printing the marker, a RED on the return code
    # alone, which proves nothing.)
    block = "\n" * (len(current) + 50) + "echo NEW-FILE-EXECUTED\n"
    replacement = box.tmp / "replacement.sh"
    write(replacement, head_text + "set -euo pipefail\n" + block + rest)
    result = run_deploy(
        box,
        env={
            "REWRITE_TARGET": str(box.app / "deploy.sh").replace("\\", "/"),
            "REWRITE_WITH": str(replacement).replace("\\", "/"),
        },
    )
    assert "NEW-FILE-EXECUTED" not in result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
