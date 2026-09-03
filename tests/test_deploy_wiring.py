"""Guards for the continuous-deployment wiring: ci.yml, deploy.yml, deploy.sh.

None of these three files is exercised by anything else in the suite. They are
consumed by GitHub Actions and by a shell on the production host, so the only
feedback a mistake in them produces is a red deploy -- or, worse, a green one
that left the site down. The assertions here are the cheap half of that feedback,
run on every PR.

Textual, not YAML-parsed: pyyaml is not a dependency, and the properties worth
guarding (a trigger's presence, a path agreeing across three files) survive a
regex fine. Same approach as test_colour_glue_drift.py.

Each assertion below names the mutant that makes it fail. An assertion that
cannot go red is not a guard.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github/workflows/ci.yml"
DEPLOY_YML = ROOT / ".github/workflows/deploy.yml"
DEPLOY_SH = ROOT / "deploy.sh"
RUNBOOK = ROOT / "docs/deployment.md"


def _on_block(path):
    """The lines of a workflow's top-level `on:` mapping.

    Ends at the next line that starts in column 0 and is neither blank nor a
    comment -- i.e. the next top-level key. Comments are kept inside the block so
    a `push:` commented out rather than deleted is still visibly absent from the
    triggers but present in the file.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "on:")
    out = []
    for ln in lines[start + 1 :]:
        if ln and not ln[0].isspace() and not ln.startswith("#"):
            break
        out.append(ln)
    return out


def _app_dir():
    """The deploy checkout path, as deploy.sh itself defines it."""
    text = DEPLOY_SH.read_text(encoding="utf-8")
    match = re.search(r"^APP_DIR=(\S+)$", text, re.MULTILINE)
    assert match, "deploy.sh no longer assigns APP_DIR at the top level"
    return match.group(1)


def test_ci_does_not_run_on_master_push():
    """The duplication guard.

    ci.yml used to trigger on both `pull_request` and `push: branches: [master]`,
    so a squash-merge ran lint + unit + e2e twice for one tree. Deploying without
    a test job is only defensible while the PR run is the single gate; re-adding a
    master trigger silently reinstates the duplicate it was dropped to remove.

    Mutant: put `push:\n    branches: [master]` back into ci.yml's `on:` block.
    """
    triggers = [
        ln for ln in _on_block(CI_YML) if ln.strip() and not ln.strip().startswith("#")
    ]
    assert any(ln.strip() == "pull_request:" for ln in triggers), triggers
    assert not any(ln.strip().startswith("push:") for ln in triggers), triggers


def test_deploy_runs_on_master_push():
    """The converse: deploy.yml is the file that carries the master trigger.

    Mutant: remove `push:` from deploy.yml, and nothing deploys on merge at all --
    a failure mode with no error message anywhere, since a workflow that never
    fires produces no run to be red.
    """
    block = "\n".join(_on_block(DEPLOY_YML))
    assert re.search(r"^  push:$", block, re.MULTILINE), block
    assert re.search(r"^    branches: \[master\]$", block, re.MULTILINE), block
    # Manual redeploys (a host-side change with no commit) depend on this.
    assert re.search(r"^  workflow_dispatch:$", block, re.MULTILINE), block


def test_deploy_yml_invokes_the_script_at_the_path_deploy_sh_assumes():
    """deploy.sh `cd`s to a path it hard-codes; deploy.yml names that path in a
    second, unrelated string. Nothing but this test connects the two, and a
    mismatch is only discovered by a deploy that fails on the host with
    `No such file or directory`.

    Mutant: change APP_DIR in deploy.sh (or the `script:` path in deploy.yml)
    without changing the other.
    """
    text = DEPLOY_YML.read_text(encoding="utf-8")
    match = re.search(r"^\s*bash (\S+)$", text, re.MULTILINE)
    assert match, "deploy.yml no longer invokes a script over ssh"
    assert match.group(1) == f"{_app_dir()}/deploy.sh"
    # The `cd` in deploy.yml's own script block is a third copy of the path.
    assert re.search(rf"^\s*cd {re.escape(_app_dir())}$", text, re.MULTILINE), text


def test_deploy_yml_resets_before_invoking_the_script():
    """The bootstrap. deploy.sh is what fetches the repo, so a host whose
    checkout predates it has no deploy.sh to run -- the first deploy dies on
    `No such file or directory` with nothing to reset it into place. Resetting
    from the workflow first is what breaks that circle, and it is also what makes
    a change to deploy.sh take effect on the deploy that introduces it rather
    than the one after.

    Mutant: delete the fetch/reset lines from deploy.yml's script block, or move
    the `bash` line above them.
    """
    text = DEPLOY_YML.read_text(encoding="utf-8")
    reset = re.search(r"^\s*git reset --hard origin/master$", text, re.MULTILINE)
    invoke = re.search(r"^\s*bash \S+/deploy\.sh$", text, re.MULTILINE)
    assert reset, "deploy.yml no longer resets the checkout before deploying"
    assert invoke, "deploy.yml no longer invokes deploy.sh"
    assert reset.start() < invoke.start(), "the reset must precede the invocation"


def test_ssh_action_stops_on_the_first_failing_line():
    """drone-ssh runs the script as one remote shell and reports the exit code of
    the LAST command. Without `set -e` a failed fetch is followed by a deploy
    against stale code, reported green -- the exact failure this file exists to
    make impossible.

    It must be `set -e` inside the script, and it must come first. The action's
    `script_stop` input does NOT do this: v1 rejects it as an unknown input,
    warns, and carries on. The second assertion is the load-bearing one -- the
    first version of this guard asserted `script_stop: true` was present, which
    was true of the text and false of the behaviour, so its mutant went red
    while production had no protection at all.

    Mutant: delete the `set -e` line, move it below `cd`, or swap it back for
    `script_stop: true`.
    """
    text = DEPLOY_YML.read_text(encoding="utf-8")
    body = re.search(r"^\s*script: \|\n((?:\s+.*\n)+)", text, re.MULTILINE)
    assert body, "deploy.yml no longer has a literal-block script"
    first = next(ln.strip() for ln in body.group(1).splitlines() if ln.strip())
    assert first == "set -e", f"first script line is {first!r}, not 'set -e'"
    assert not re.search(r"^\s*script_stop:", text, re.MULTILINE), (
        "script_stop is not a v1 input -- it is ignored, and asserting it "
        "reads as protection that does not exist"
    )


def test_deploy_path_matches_the_runbook():
    """docs/deployment.md tells an operator where to clone. If deploy.sh resets a
    different directory, the first deploy after a fresh provision silently
    rebuilds nothing -- or fails on a directory that does not exist.

    Mutant: change APP_DIR to /srv/libli while the runbook still says /opt/libli.
    """
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert re.search(rf"git clone \S+ {re.escape(_app_dir())}\b", runbook), _app_dir()


def test_deploy_script_waits_for_health():
    """`--wait` is the whole of this deploy's failure handling: without it,
    `up -d` returns as soon as the containers are *created*, so a failed
    migration or a container that never becomes healthy still produces a green
    Actions run over a dead site.

    Mutant: drop `--wait` from the `compose up` line.
    """
    text = DEPLOY_SH.read_text(encoding="utf-8")
    match = re.search(r"^compose up .*$", text, re.MULTILINE)
    assert match, "deploy.sh no longer brings the stack up"
    assert "--wait" in match.group(0), match.group(0)
    # `--build` was removed when the box switched to pulling a published image;
    # tests/test_backup_wiring.py::test_no_build_survives_anywhere pins that.
    assert "compose pull" in text, text


def test_deploy_script_resets_rather_than_pulls():
    """`git pull` aborts on divergent branches and on local changes, both of which
    a hand-fixed production checkout accumulates. The failure is a deploy that
    goes red having changed nothing, repeatedly, until someone SSHes in.

    Mutant: replace the fetch/reset pair with `git pull origin master`.
    """
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert re.search(r"^git reset --hard origin/master$", text, re.MULTILINE), text
    assert not re.search(r"^\s*git pull\b", text, re.MULTILINE), text


def test_deploy_does_not_cancel_a_running_deploy():
    """A deploy cancelled between `migrate` and gunicorn leaves a half-applied
    stack. Queuing the second run is strictly better than racing it.

    Mutant: flip cancel-in-progress to true.
    """
    text = DEPLOY_YML.read_text(encoding="utf-8")
    assert re.search(r"^\s*group: deploy-production$", text, re.MULTILINE), text
    assert re.search(r"^\s*cancel-in-progress: false$", text, re.MULTILINE), text


def test_ssh_command_timeout_exceeds_the_action_default():
    """appleboy/ssh-action defaults to 10 minutes, and a rebuild plus `--wait` on
    a healthcheck with start_period 60s and 30 retries at 10s exceeds that on its
    own. The default does not fail cleanly: it severs the session mid-build and
    reports a timeout while the host carries on deploying.

    Mutant: delete the command_timeout line, or set it to 5m.
    """
    text = DEPLOY_YML.read_text(encoding="utf-8")
    match = re.search(r"^\s*command_timeout: (\d+)([smh])$", text, re.MULTILINE)
    assert match, "deploy.yml relies on appleboy/ssh-action's 10-minute default"
    seconds = int(match.group(1)) * {"s": 1, "m": 60, "h": 3600}[match.group(2)]
    assert seconds > 600, match.group(0)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_deploy_script_parses():
    """A syntax error in deploy.sh is otherwise found by the production host, at
    the one moment nothing is watching. `bash -n` parses without executing.

    Mutant: drop a closing brace from either helper function.
    """
    result = subprocess.run(  # noqa: S603 -- fixed argv, repo-relative path
        [shutil.which("bash"), "-n", str(DEPLOY_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
