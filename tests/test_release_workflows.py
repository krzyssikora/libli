"""Wiring guards for the B2 workflows and ssh helper.

Textual, like test_deploy_wiring.py: pyyaml is not a dependency, and every
property here (a key's presence, one step preceding another) survives a regex.
"""

import re

import pytest

from tests.release_harness import ROOT

CUT = ROOT / ".github/workflows/cut-release.yml"
DEPLOY_RELEASE = ROOT / ".github/workflows/deploy-release.yml"
DEPLOY_YML = ROOT / ".github/workflows/deploy.yml"
SSH_BOX = ROOT / "scripts/release/ssh_box.sh"
MASTER = "github.ref == 'refs/heads/master'"
NEW_WORKFLOWS = [CUT]  # Task 12 adds DEPLOY_RELEASE


def jobs(text):
    lines = text.splitlines()
    start = lines.index("jobs:")
    out, name = {}, None
    for ln in lines[start + 1 :]:
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", ln)
        if m:
            name = m.group(1)
            out[name] = []
            continue
        if ln and not ln.startswith(" ") and not ln.startswith("#"):
            break
        if name:
            out[name].append(ln)
    return out


def job_if(block):
    found = [ln[len("    if: ") :] for ln in block if ln.startswith("    if: ")]
    assert len(found) == 1, f"a job must carry exactly one if:, found {found}"
    return found[0]


def steps(block):
    out, cur = [], None
    for ln in block:
        if re.match(r"^      - ", ln):
            cur = [ln]
            out.append(cur)
        elif cur is not None and (ln.startswith("        ") or not ln.strip()):
            cur.append(ln)
        elif ln.strip():
            cur = None
    return ["\n".join(s) for s in out]


def step_index(step_list, needle):
    hits = [i for i, s in enumerate(step_list) if needle in s]
    assert hits, f"no step contains {needle!r}"
    return hits[0]


def run_blocks(text):
    blocks = re.findall(r"run: \|\n((?:\s{10,}.*\n|\s*\n)+)", text)
    blocks += re.findall(r"run: (?!\|)(.+)", text)
    return blocks


def test_job_if_refuses_a_duplicate_key():
    """Two `if:` keys are a duplicate YAML key a parser collapses to the last;
    the helper must fail instead of picking one."""
    with pytest.raises(AssertionError):
        job_if(["    if: always()", f"    if: {MASTER}"])


@pytest.mark.parametrize("path", NEW_WORKFLOWS, ids=lambda p: p.name)
def test_every_job_is_master_gated(path):
    """workflow_dispatch can run the file from any branch, and the guard
    scripts come from that branch. Mutant: drop a job's if:."""
    for name, block in jobs(path.read_text(encoding="utf-8")).items():
        assert MASTER in job_if(block), name


@pytest.mark.parametrize("path", NEW_WORKFLOWS, ids=lambda p: p.name)
def test_nothing_inherits_the_repo_default_permissions(path):
    text = path.read_text(encoding="utf-8")
    assert re.search(r"^permissions: \{\}$", text, re.MULTILINE)


@pytest.mark.parametrize("path", NEW_WORKFLOWS, ids=lambda p: p.name)
def test_no_expression_inside_a_run_block(path):
    """Values reach the shell through env:. Mutant: `${{ inputs.version }}`
    inlined in a run: line."""
    for block in run_blocks(path.read_text(encoding="utf-8")):
        assert "${{" not in block, block


@pytest.mark.parametrize("path", NEW_WORKFLOWS, ids=lambda p: p.name)
def test_every_canary_guard_call_carries_gh_token(path):
    """gh does not pick up GITHUB_TOKEN by itself. Mutant: drop GH_TOKEN."""
    for block in jobs(path.read_text(encoding="utf-8")).values():
        for step in steps(block):
            if "canary_guard.py" in step:
                assert "GH_TOKEN: ${{ github.token }}" in step, step


@pytest.mark.parametrize("path", NEW_WORKFLOWS, ids=lambda p: p.name)
def test_every_guard_checkout_has_full_history(path):
    """Mutant: drop fetch-depth: 0 -- merge-base then misreports on a depth-1 clone."""
    text = path.read_text(encoding="utf-8")
    for name, block in jobs(text).items():
        joined = "\n".join(block)
        guarded = "release_checks.py" in joined or "migration_guard.sh" in joined
        if "actions/checkout" in joined and guarded:
            assert "fetch-depth: 0" in joined, name


def test_cut_release_is_a_button_only():
    text = CUT.read_text(encoding="utf-8")
    on = text[text.index("\non:") : text.index("\npermissions:")]
    assert "workflow_dispatch:" in on and "push:" not in on


def test_cut_release_permissions():
    block = jobs(CUT.read_text(encoding="utf-8"))["cut"]
    joined = "\n".join(block)
    assert "      contents: write" in joined and "      actions: read" in joined


def test_cut_release_validates_the_version_before_the_checkout():
    s = steps(jobs(CUT.read_text(encoding="utf-8"))["cut"])
    assert step_index(s, "Validate the version") < step_index(s, "actions/checkout")


def test_cut_release_runs_the_checks_in_order_then_tags():
    s = steps(jobs(CUT.read_text(encoding="utf-8"))["cut"])
    order = [
        step_index(s, "release_checks.py resolve"),
        step_index(s, "canary_guard.py"),
        step_index(s, "release_checks.py containment"),
        step_index(s, "git tag -a"),
    ]
    assert order == sorted(order)


def test_cut_release_sets_an_identity_and_records_the_canary_run():
    """A fresh runner has no identity; `git tag -a` would die after every
    guard passed. Mutant: drop the git config lines."""
    step = steps(jobs(CUT.read_text(encoding="utf-8"))["cut"])[-1]
    assert "git config user.name 'github-actions[bot]'" in step
    assert "41898282+github-actions[bot]@users.noreply.github.com" in step
    assert step.index("git config user.email") < step.index("git tag -a")
    assert '-m "canary-run: $RUN_ID"' in step


def test_the_commit_input_reaches_the_shell_through_env():
    s = steps(jobs(CUT.read_text(encoding="utf-8"))["cut"])
    step = s[step_index(s, "release_checks.py resolve")]
    assert "COMMIT: ${{ inputs.commit }}" in step


def test_ssh_box_pins_every_option():
    """Mutants: drop any option; add accept-new or StrictHostKeyChecking=no."""
    text = SSH_BOX.read_text(encoding="utf-8")
    for opt in (
        "BatchMode=yes",
        "ConnectTimeout=15",
        "ServerAliveInterval=30",
        "ServerAliveCountMax=4",
        "StrictHostKeyChecking=yes",
        'UserKnownHostsFile="$dir/known_hosts"',
        "IdentitiesOnly=yes",
    ):
        assert f"-o {opt}" in text, opt
    assert "accept-new" not in text and "StrictHostKeyChecking=no" not in text


def test_the_remote_bootstrap_never_moves_the_checkout():
    """Only deploy.sh, under the lock backup.sh also takes, may move HEAD
    (spec §2 step 6). Textual, so it runs everywhere, unlike the setsid tests.
    Mutants: add `git checkout`, `git reset` or `git fetch` to remote_deploy.sh;
    replace the `git show "refs/tags/...` extraction; replace mktemp with a
    fixed path."""
    source = (ROOT / "scripts/release/remote_deploy.sh").read_text(encoding="utf-8")
    body = [ln for ln in source.splitlines() if not ln.lstrip().startswith("#")]
    text = "\n".join(body)
    assert 'git show "refs/tags/$version:deploy.sh"' in text
    assert 'script="$(mktemp)"' in text
    for forbidden in ("git checkout", "git reset", "git fetch"):
        assert forbidden not in text, forbidden
    # The log exists before the run starts, so `tail -f` never meets a missing
    # file. Pinned textually: the session-side `>> "$log"` on the setsid line
    # also creates it before the pid is published, so no executed test can
    # tell the two apart. Mutant: delete the `: > "$log"` line.
    assert ': > "$log"' in text and "setsid nohup" in text
    assert text.index(': > "$log"') < text.index("setsid nohup")
    # The followed pid is the wrapper's, read from the pid file -- never $!.
    # In the tests (and on the box) setsid happens not to fork, so $! would
    # pass every executed test; pinned textually. Mutant: `pid=$!`.
    assert 'pid="$(head -n 1 "$pidf")"' in text
    assert "$!" not in text


RELEASE_SHELL_SCRIPTS = [
    "preflight.sh",
    "remote_deploy.sh",
    "ssh_box.sh",
    "migration_guard.sh",
]


@pytest.mark.parametrize("name", RELEASE_SHELL_SCRIPTS)
def test_release_shell_scripts_stop_on_the_first_error(name):
    lines = (ROOT / "scripts/release" / name).read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#!")
    code = [ln for ln in lines[1:] if ln.strip() and not ln.lstrip().startswith("#")]
    real = code[0]
    assert real == "set -euo pipefail", real
