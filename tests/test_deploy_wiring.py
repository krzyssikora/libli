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
    match = re.search(r"^\s*(?:\S+=\S+ )?bash (\S+)$", text, re.MULTILINE)
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
    invoke = re.search(r"^\s*(?:\S+=\S+ )?bash \S+/deploy\.sh$", text, re.MULTILINE)
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
    assert "--build" in match.group(0), match.group(0)


def test_deploy_script_resets_rather_than_pulls():
    """`git pull` aborts on divergent branches and on local changes, both of which
    a hand-fixed production checkout accumulates. The failure is a deploy that
    goes red having changed nothing, repeatedly, until someone SSHes in.

    Mutant: replace the fetch/reset pair with `git pull origin master`.
    """
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert re.search(r"^\s*git reset --hard origin/master$", text, re.MULTILINE), text
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


# ---- the fetch retry -------------------------------------------------------
#
# These EXECUTE the shipped shell rather than reading it. A regex can confirm the
# word "retry" appears; only running it proves a second attempt is actually made,
# that the loop terminates, and -- the one that matters -- that a fetch which
# never succeeds stops the deploy instead of letting it run against stale code.
#
# `git` and `sleep` are replaced by shell FUNCTIONS in a prelude, not by files on
# PATH: a function shadows a PATH lookup on every platform, while an executable
# stub depends on an exec bit that Windows does not really set.


def _harness(calls_path, fail_fetches):
    """A bash prelude stubbing `git` and `sleep`.

    Every git invocation is logged to `calls_path`; the first `fail_fetches`
    fetches exit 128, which is what git returns for the credential prompt this
    retry exists to survive. `sleep` becomes a no-op so the shipped delay costs
    the suite nothing -- the real value is asserted separately, in
    test_deploy_retry_delay_is_not_instant.
    """
    log = str(calls_path).replace("\\", "/")
    return (
        "git() {\n"
        f'  echo "$@" >> "{log}"\n'
        '  if [ "$1" = fetch ]; then\n'
        f"    n=$(grep -c '^fetch' \"{log}\")\n"
        f'    if [ "$n" -le {fail_fetches} ]; then return 128; fi\n'
        "  fi\n"
        "  return 0\n"
        "}\n"
        "sleep() { :; }\n"
    )


def _run_bash(script):
    return subprocess.run(  # noqa: S603 -- fixed argv, generated script
        [shutil.which("bash"), "-c", script],
        capture_output=True,
        text=True,
    )


def _sh_settings():
    """deploy.sh's top-level GIT_FETCH_* assignments -- the retry budget the
    extracted functions read. Sourced with them so `set -u` sees them defined,
    and so the tests exercise the SHIPPED defaults rather than invented ones."""
    text = DEPLOY_SH.read_text(encoding="utf-8")
    found = re.findall(r"^GIT_FETCH_\w+=.*$", text, re.MULTILINE)
    assert found, "deploy.sh no longer defines its retry budget at the top level"
    return "\n".join(found)


def _sh_function(name):
    """One top-level `name() { ... }` block, verbatim, out of deploy.sh."""
    text = DEPLOY_SH.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{$.*?^\}}$", text, re.MULTILINE | re.DOTALL)
    assert match, f"deploy.sh no longer defines a top-level {name}()"
    return match.group(0)


def _deploy_yml_script():
    """deploy.yml's `script:` block, dedented -- the shell that runs on the host."""
    lines = DEPLOY_YML.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "script: |")
    indent = len(lines[start]) - len(lines[start].lstrip()) + 2
    out = []
    for ln in lines[start + 1 :]:
        if ln.strip() and not ln.startswith(" " * indent):
            break
        out.append(ln[indent:])
    return "\n".join(out)


def _yml_script_for(tmp_path, stub):
    """deploy.yml's script with the host paths pointed at tmp_path. The retry
    loop itself runs exactly as shipped."""
    app = _app_dir()
    return (
        _deploy_yml_script()
        .replace(f"bash {app}/deploy.sh", f'bash "{str(stub).replace(chr(92), "/")}"')
        .replace(f"cd {app}", f'cd "{str(tmp_path).replace(chr(92), "/")}"')
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_deploy_script_retries_a_fetch_that_fails(tmp_path):
    """GitHub answers an ANONYMOUS fetch of this public repo with a 401 challenge
    often enough to have failed three deploys in two days (#293, #295, #296); git
    then dies on "could not read Username" because there is no tty. Nothing is
    wrong with the checkout -- in #296 the fetch 440 ms earlier had SUCCEEDED.

    Mutant: drop the loop and call `git fetch origin master` once. The stub fails
    twice, so a single attempt returns 128 and the function reports failure.
    """
    calls = tmp_path / "calls"
    calls.write_text("")
    result = _run_bash(
        f"set -euo pipefail\n{_harness(calls, 2)}\n{_sh_settings()}\n"
        f"{_sh_function('fetch_master')}\nfetch_master"
    )
    assert result.returncode == 0, result.stderr
    assert calls.read_text().count("fetch") == 3, calls.read_text()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_deploy_script_gives_up_rather_than_retrying_forever(tmp_path):
    """The converse. A retry that never surrenders turns a GitHub outage into a
    deploy that hangs until command_timeout severs the session at 30m -- which
    reports a timeout while the host carries on, the exact failure mode the
    timeout comment warns about.

    Mutant: `while true` with no attempt cap, or `return 0` on exhaustion.
    """
    calls = tmp_path / "calls"
    calls.write_text("")
    result = _run_bash(
        f"set -uo pipefail\n{_harness(calls, 99)}\n{_sh_settings()}\n"
        f"{_sh_function('fetch_master')}\nfetch_master"
    )
    assert result.returncode != 0, "an exhausted retry must fail the deploy"
    attempts = calls.read_text().count("fetch")
    assert 2 <= attempts <= 5, f"expected a small capped retry, got {attempts}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_deploy_script_skips_its_own_fetch_when_ci_already_fetched(tmp_path):
    """deploy.yml fetches and resets before invoking deploy.sh, so deploy.sh's own
    fetch is a SECOND request to github.com within a second. That pair is what
    tripped #296: the first fetch succeeded, the second was refused 440 ms later.
    Under CI the second one buys nothing -- the reset still runs, so the invariant
    this function guarantees is unchanged.

    Mutant: ignore LIBLI_DEPLOY_SKIP_FETCH and always fetch.
    """
    calls = tmp_path / "calls"
    calls.write_text("")
    result = _run_bash(
        f"set -euo pipefail\n{_harness(calls, 0)}\n"
        f"{_sh_settings()}\n{_sh_function('fetch_master')}\n{_sh_function('sync_working_tree')}\n"
        "LIBLI_DEPLOY_SKIP_FETCH=1 sync_working_tree"
    )
    assert result.returncode == 0, result.stderr
    logged = calls.read_text()
    assert "fetch" not in logged, f"CI already fetched; deploy.sh refetched: {logged}"
    # The reset is NOT skipped -- it is what guarantees the tree matches master.
    assert "reset --hard origin/master" in logged, logged


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_deploy_script_still_fetches_when_run_by_hand(tmp_path):
    """The rollback path in docs/deployment.md is `bash deploy.sh` on the box,
    with no CI to have fetched first. Skipping the fetch there would silently
    deploy whatever origin/master pointed at last time.

    Mutant: skip the fetch unconditionally, or default the guard the other way.
    """
    calls = tmp_path / "calls"
    calls.write_text("")
    result = _run_bash(
        f"set -euo pipefail\n{_harness(calls, 0)}\n"
        f"{_sh_settings()}\n{_sh_function('fetch_master')}\n{_sh_function('sync_working_tree')}\n"
        "sync_working_tree"
    )
    assert result.returncode == 0, result.stderr
    assert "fetch origin master" in calls.read_text(), calls.read_text()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_deploy_yml_retries_its_own_fetch_before_invoking_the_script(tmp_path):
    """deploy.yml cannot borrow deploy.sh's retry: its fetch is what puts
    deploy.sh on a host that may not have it yet (the bootstrap this file already
    guards). So the loop is duplicated, and so is the test for it.

    Mutant: drop the loop from deploy.yml's script block.
    """
    calls = tmp_path / "calls"
    calls.write_text("")
    marker = tmp_path / "deployed"
    stub = tmp_path / "stub-deploy.sh"
    stub.write_text(f'touch "{str(marker).replace(chr(92), "/")}"\n')
    result = _run_bash(f"{_harness(calls, 2)}\n{_yml_script_for(tmp_path, stub)}")
    assert result.returncode == 0, result.stderr
    assert calls.read_text().count("fetch") == 3, calls.read_text()
    assert marker.exists(), "the deploy never ran after the fetch recovered"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
def test_deploy_yml_does_not_deploy_when_every_fetch_fails(tmp_path):
    """The load-bearing one. A retry loop that falls through on exhaustion would
    reset to a stale origin/master and deploy it -- the "green deploy against old
    code" this file exists to make impossible, now reachable through the very
    change meant to make deploys more reliable.

    Mutant: `break` instead of `exit 1` when the attempts run out.
    """
    calls = tmp_path / "calls"
    calls.write_text("")
    marker = tmp_path / "deployed"
    stub = tmp_path / "stub-deploy.sh"
    stub.write_text(f'touch "{str(marker).replace(chr(92), "/")}"\n')
    result = _run_bash(f"{_harness(calls, 99)}\n{_yml_script_for(tmp_path, stub)}")
    assert result.returncode != 0, "a fetch that never succeeds must fail the run"
    assert not marker.exists(), "deployed against a stale checkout"


def test_deploy_yml_tells_deploy_sh_that_it_already_fetched():
    """The two files agree on the variable name through nothing but this test --
    the same seam as the APP_DIR guard above. A typo on either side is invisible:
    deploy.sh simply fetches again, restoring the request pair that failed #296,
    and every deploy still goes green.

    Mutant: rename the variable in one file only.
    """
    yml = DEPLOY_YML.read_text(encoding="utf-8")
    invoke = re.search(r"^\s*(\S+)=1 bash \S+/deploy\.sh$", yml, re.MULTILINE)
    assert invoke, "deploy.yml no longer marks the fetch as already done"
    assert invoke.group(1) in DEPLOY_SH.read_text(encoding="utf-8")


def test_deploy_retry_waits_between_attempts():
    """Three attempts fired back to back inside a second would retry INSIDE the
    window that refused the first one. The stubbed `sleep` cannot see this, so it
    is asserted on the text.

    Mutant: delete the sleep, or set the delay to 0.
    """
    for path in (DEPLOY_SH, DEPLOY_YML):
        text = path.read_text(encoding="utf-8")
        literal = [int(m) for m in re.findall(r"^\s*sleep (\d+)$", text, re.MULTILINE)]
        named = [
            int(m)
            for m in re.findall(
                r"^GIT_FETCH_DELAY=\$\{GIT_FETCH_DELAY:-(\d+)\}$", text, re.MULTILINE
            )
        ]
        assert any(d >= 2 for d in literal + named), f"{path.name}: {literal}{named}"
