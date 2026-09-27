"""deploy.sh on libli.pl (no LIBLI_DEPLOY_CHANNEL line): the canary path.

Goal 6 of the spec: the trigger and target are unchanged; three deliberate
behaviour changes (D9 superseded refusal, LIBLI_IMAGE_TAG persisted just before
`up`, restore on a pre-`up` failure) and three no-op additions.
"""

import pytest

from tests.release_harness import BASH
from tests.release_harness import TOKEN_LINE
from tests.release_harness import Box
from tests.release_harness import calls
from tests.release_harness import env_at_up
from tests.release_harness import head
from tests.release_harness import on_branch
from tests.release_harness import run_deploy

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not on PATH")


@pytest.fixture
def libli(tmp_path):
    """P deployed and persisted; X and Y merged after it. HEAD on master at P."""
    box = Box(tmp_path)
    p = box.commit(msg="P")
    x = box.commit(extra={"README": "x\n"}, msg="X")
    y = box.commit(extra={"README": "y\n"}, msg="Y")
    box.clone(p, detached=False, image_tag=f"sha-{p}")
    return box, p, x, y


def test_an_ordinary_run_deploys_master_and_persists_the_tag_just_before_up(libli):
    """Mutant: persist LIBLI_IMAGE_TAG after `compose up` instead of before."""
    box, p, x, y = libli
    result = run_deploy(box)
    assert result.returncode == 0, result.stderr
    assert head(box) == y and on_branch(box)
    assert f"pull-tag=sha-{y}" in calls(box)
    assert f"LIBLI_IMAGE_TAG=sha-{y}" in env_at_up(box)


def test_a_pull_failure_restores_the_checkout_and_keeps_the_tag(libli):
    """The bootstrap already moved HEAD to Y; the old image still runs, so a
    backup must not see HEAD=Y. Branch form: reset --hard on master.

    Mutant: drop the EXIT trap (or key it on ERR, which misses compose()).
    """
    box, p, x, y = libli
    box.bootstrap_to(y)
    result = run_deploy(box, env={"FAIL_AT": "pull", "LIBLI_DEPLOY_SKIP_FETCH": "1"})
    assert result.returncode != 0
    assert head(box) == p and on_branch(box)
    assert f"LIBLI_IMAGE_TAG=sha-{p}" in (box.app / ".env.production").read_text()


def test_a_missing_ghcr_token_restores_the_checkout(libli):
    """The token check leaves through an explicit `exit 1`, which an ERR trap
    never sees. Mutant: ERR trap instead of EXIT."""
    box, p, x, y = libli
    env = (box.app / ".env.production").read_text().replace(TOKEN_LINE + "\n", "")
    (box.app / ".env.production").write_bytes(env.encode())
    box.bootstrap_to(y)
    result = run_deploy(box, env={"LIBLI_DEPLOY_SKIP_FETCH": "1"})
    assert result.returncode != 0
    assert head(box) == p
    assert f"LIBLI_IMAGE_TAG=sha-{p}" in (box.app / ".env.production").read_text()


def test_a_failure_of_up_does_not_restore(libli):
    """After `up` starts, the new image's migrate may have run: HEAD and the tag
    must both name the new version.

    Mutant: a trap that ignores reached_up and always restores.
    """
    box, p, x, y = libli
    result = run_deploy(box, env={"FAIL_AT": "up"})
    assert result.returncode != 0
    assert head(box) == y
    assert f"LIBLI_IMAGE_TAG=sha-{y}" in (box.app / ".env.production").read_text()


def test_a_hangup_before_up_restores(libli):
    """Mutant: drop the HUP trap."""
    box, p, x, y = libli
    box.bootstrap_to(y)
    result = run_deploy(box, env={"FAIL_AT": "hup", "LIBLI_DEPLOY_SKIP_FETCH": "1"})
    assert result.returncode != 0
    assert head(box) == p


def test_an_exported_bogus_tag_never_reaches_up(libli):
    """Mutant: drop `unset LIBLI_IMAGE_TAG`."""
    box, p, x, y = libli
    result = run_deploy(box, env={"LIBLI_IMAGE_TAG": "sha-bogus"})
    assert result.returncode == 0, result.stderr
    assert "up-shell-tag=<unset>" in calls(box)


def test_d9_a_superseded_run_refuses_and_the_trap_restores(libli):
    """The run was for X, but master moved to Y and the bootstrap reset to Y.
    LIBLI_DEPLOY_SKIP_FETCH=1 is what deploy.yml always passes.

    Mutants: skip the check on the unset-ref path; put it inside the fetch branch.
    """
    box, p, x, y = libli
    box.bootstrap_to(y)
    result = run_deploy(
        box, env={"LIBLI_DEPLOY_EXPECT_SHA": x, "LIBLI_DEPLOY_SKIP_FETCH": "1"}
    )
    assert result.returncode != 0
    assert f"superseded by {y}" in result.stderr
    assert "docker " not in calls(box)
    assert head(box) == p
    assert f"LIBLI_IMAGE_TAG=sha-{p}" in (box.app / ".env.production").read_text()


def test_d9_a_current_run_proceeds_exactly_as_today(libli):
    box, p, x, y = libli
    box.bootstrap_to(y)
    result = run_deploy(
        box, env={"LIBLI_DEPLOY_EXPECT_SHA": y, "LIBLI_DEPLOY_SKIP_FETCH": "1"}
    )
    assert result.returncode == 0, result.stderr
    assert head(box) == y


def test_an_absent_tag_proceeds_with_no_restore_target(tmp_path):
    box = Box(tmp_path)
    p = box.commit(msg="P")
    y = box.commit(extra={"README": "y\n"}, msg="Y")
    box.clone(p, detached=False, image_tag=None)
    box.bootstrap_to(y)
    result = run_deploy(box, env={"FAIL_AT": "pull", "LIBLI_DEPLOY_SKIP_FETCH": "1"})
    assert result.returncode != 0
    assert "no restore target" in result.stderr
    assert head(box) == y


def test_a_malformed_tag_warns_and_proceeds(tmp_path):
    box = Box(tmp_path)
    p = box.commit(msg="P")
    box.clone(p, detached=False, image_tag="sha-short")
    result = run_deploy(box)
    assert result.returncode == 0, result.stderr
    assert "LIBLI_IMAGE_TAG unreadable" in result.stderr


def test_a_successful_run_prints_nothing_from_the_exit_trap(libli):
    """Goal 6: the trap, the unset and the signal traps are no-ops on success."""
    box, p, x, y = libli
    result = run_deploy(box)
    assert result.returncode == 0
    assert "restor" not in result.stderr.lower()
