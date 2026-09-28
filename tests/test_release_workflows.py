"""Wiring guards for the B2 workflows and ssh helper.

Textual, like test_deploy_wiring.py: pyyaml is not a dependency, and every
property here (a key's presence, one step preceding another) survives a regex.
"""

import os
import re
import subprocess
import sys

import pytest

from tests.release_harness import BASH
from tests.release_harness import ROOT
from tests.release_harness import posix
from tests.release_harness import write

CUT = ROOT / ".github/workflows/cut-release.yml"
DEPLOY_RELEASE = ROOT / ".github/workflows/deploy-release.yml"
DEPLOY_YML = ROOT / ".github/workflows/deploy.yml"
SSH_BOX = ROOT / "scripts/release/ssh_box.sh"
MASTER = "github.ref == 'refs/heads/master'"
NEW_WORKFLOWS = [CUT, DEPLOY_RELEASE]


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
    """Every run: body, block or one-line. Any block scalar header counts --
    `|`, `>`, with a chomping (`-`/`+`) or indentation indicator, or a trailing
    comment -- so no header spelling lets a body escape the guards."""
    header = r"run:[ \t]+[|>][-+0-9]*[ \t]*(?:#.*)?\n"
    blocks = re.findall(header + r"((?:\s{10,}.*\n|\s*\n)+)", text)
    blocks += re.findall(r"run:[ \t]+(?![ \t|>])(.+)", text)
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


def test_every_deploy_release_checkout_drops_its_credentials():
    """Nothing in deploy-release fetches or pushes after the checkout, so no
    job keeps the token in .git/config beside the SSH key. Derived per job:
    a new job's checkout is covered too. Mutant: drop any one of the lines."""
    seen = 0
    for name, block in jobs(_dr()).items():
        for step in steps(block):
            if "actions/checkout" in step:
                seen += 1
                assert "persist-credentials: false" in step, name
    assert seen >= 3


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
    """Mutants: drop any option; add accept-new or StrictHostKeyChecking=no;
    change =yes to =off (or =No); add a lax -o before the =yes one (ssh keeps
    the FIRST value of an option)."""
    text = SSH_BOX.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    # An allowlist, not a denylist: option names are case-insensitive to ssh,
    # so count them case-insensitively, and the single use must be =yes.
    shkc = re.findall(r"stricthostkeychecking", code, re.IGNORECASE)
    assert len(shkc) == 1, f"StrictHostKeyChecking must occur once, found {len(shkc)}"
    assert re.search(r"-o StrictHostKeyChecking=yes(?=\s)", code)
    for opt in (
        "BatchMode=yes",
        "ConnectTimeout=15",
        "ServerAliveInterval=30",
        "ServerAliveCountMax=4",
        "StrictHostKeyChecking=yes",
        'UserKnownHostsFile="$dir/known_hosts"',
        "GlobalKnownHostsFile=/dev/null",
        "IdentitiesOnly=yes",
    ):
        assert f"-o {opt}" in code, opt
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


def _dr():
    return DEPLOY_RELEASE.read_text(encoding="utf-8")


def test_report_runs_always_but_only_on_master():
    """One expression. Mutants: drop `always()` (report is skipped exactly when
    plan refused or a leg failed); drop the ref check."""
    expr = job_if(jobs(_dr())["report"])
    assert "always()" in expr and MASTER in expr


def test_plan_orders_its_checks():
    s = steps(jobs(_dr())["plan"])
    assert step_index(s, "Validate the version") == 0
    checkout = step_index(s, "actions/checkout")
    assert step_index(s, "release_checks.py tag") == checkout + 1
    assert (
        checkout
        < step_index(s, "canary_guard.py")
        < step_index(s, "release_checks.py containment")
    )
    assert step_index(s, "release_checks.py containment") < step_index(
        s, "inventory.py plan"
    )


def test_plan_passes_the_tags_run_id_to_the_canary_guard():
    step = steps(jobs(_dr())["plan"])[
        step_index(steps(jobs(_dr())["plan"]), "canary_guard.py")
    ]
    assert "RUN_ID: ${{ steps.tag.outputs.run_id }}" in step
    assert '"$SHA" "$RUN_ID"' in step


def test_the_deploy_matrix_is_isolated_per_school():
    joined = "\n".join(jobs(_dr())["deploy"])
    assert "fail-fast: false" in joined
    assert "code: ${{ fromJSON(needs.plan.outputs.codes) }}" in joined
    assert "group: deploy-school-${{ matrix.code }}" in joined
    assert "cancel-in-progress: false" in joined
    assert "timeout-minutes: 45" in joined


def test_masks_come_before_any_ssh():
    """Mutant: move the inventory step below pre-flight."""
    s = steps(jobs(_dr())["deploy"])
    entry = step_index(s, "inventory.py entry")
    assert "ssh_box.sh" not in s[entry]
    assert all(i > entry for i, st in enumerate(s) if "ssh_box.sh" in st)


def test_no_step_before_the_mask_carries_the_inventory():
    """Mutant: put SCHOOL_HOSTS in the checkout step's env: (its values would
    be in the log before any ::add-mask::)."""
    s = steps(jobs(_dr())["deploy"])
    entry = step_index(s, "inventory.py entry")
    assert not any("SCHOOL_HOSTS" in st for st in s[:entry])


def test_plan_and_deploy_call_the_release_scripts_rather_than_inlining_them():
    """Every run: step except the version check delegates to scripts/release/.
    Mutant: inline a guard's logic into a run: block."""
    for job in ("plan", "deploy"):
        for st in steps(jobs(_dr())[job]):
            if "run:" in st and "Validate the version" not in st:
                assert "scripts/release/" in st, st


def test_no_value_is_handed_on_through_the_environment_file():
    """A value in $GITHUB_ENV appears in every later step's env: header,
    printed before that step's commands -- before any mask. Checked on the
    whole file, comments included, so comments must not name it either.
    Mutant: `echo "HOST=..." >> "$GITHUB_ENV"` in any step."""
    assert "GITHUB_ENV" not in _dr()


def test_every_ssh_goes_through_the_pinned_helper():
    """Mutant: a step calls `ssh -o StrictHostKeyChecking=accept-new root@...`
    directly (or reads now_on with plain ssh)."""
    text = _dr()
    assert "accept-new" not in text and "StrictHostKeyChecking=no" not in text
    for block in run_blocks(text):
        stripped = block.replace("scripts/release/ssh_box.sh", "")
        assert not re.search(r"(?<![\w/.-])ssh\s", stripped), block


def test_the_box_env_file_never_leaves_the_box():
    """Whole file, comments included.
    Mutant: `scp root@...:/opt/libli/.env.production .`"""
    text = _dr()
    assert "scp" not in text and ".env.production" not in text
    assert "< scripts/release/preflight.sh" in text


def test_the_deploy_leg_runs_the_guard_and_the_detached_bootstrap():
    s = steps(jobs(_dr())["deploy"])
    guard = step_index(s, "migration_guard.sh")
    deploy = step_index(s, "remote_deploy.sh")
    assert step_index(s, "preflight.sh") < guard < deploy
    assert "id: deploy" in s[deploy]


def test_the_outcome_is_always_recorded_and_uploaded():
    s = steps(jobs(_dr())["deploy"])
    rec = s[step_index(s, "report.py outcome")]
    assert "if: always()" in rec
    assert "DEPLOY_OUTCOME: ${{ steps.deploy.outcome }}" in rec
    assert (
        'if [ "$MASKED" = success ]' in rec
        and "MASKED: ${{ steps.entry.outcome }}" in rec
    )
    up = s[step_index(s, "actions/upload-artifact")]
    assert "if: always()" in up and "overwrite: true" in up
    assert "name: outcome-${{ matrix.code }}" in up


def test_report_tolerates_zero_artifacts():
    s = steps(jobs(_dr())["report"])
    assert "continue-on-error: true" in s[step_index(s, "actions/download-artifact")]


def test_job_permissions_are_least_privilege():
    j = jobs(_dr())
    assert "      contents: read\n      actions: read" in "\n".join(j["plan"])
    deploy = "\n".join(j["deploy"])
    assert "      contents: read" in deploy and "actions:" not in deploy
    assert "      contents: read\n      actions: read" in "\n".join(j["report"])


def test_libli_and_schools_never_share_secrets():
    """Mutant: aim either workflow at the other's host or key."""
    school = ("SCHOOL_HOSTS", "SCHOOLS_SSH_KEY", "HEALTHCHECKS_SCHOOL_DEPLOY_URL")
    assert not any(s in DEPLOY_YML.read_text(encoding="utf-8") for s in school)
    assert not re.search(r"secrets\.SSH_(HOST|KEY)\b", _dr())


def _report_script(tmp_path):
    s = steps(jobs(_dr())["report"])
    step = s[step_index(s, "report.py summarise")]
    body = step.split("run: |\n", 1)[1]
    lines = [
        ln[10:] if ln.startswith(" " * 10) else ln.strip() for ln in body.splitlines()
    ]
    return "\n".join(lines).replace(
        "scripts/release/report.py", posix(ROOT / "scripts/release/report.py")
    )


@pytest.mark.skipif(BASH is None, reason="bash not on PATH")
@pytest.mark.parametrize(
    "plan_result,codes,hc_url,expect_ping",
    [
        ("failure", "", "https://hc.example/u", "https://hc.example/u/fail"),
        (
            "success",
            '["school-01"]',
            "https://hc.example/u",
            "https://hc.example/u/fail",
        ),
        ("failure", "", "", None),
        ("success", '["school-01"]', "https://hc.example/u", "https://hc.example/u"),
    ],
)
def test_the_report_shell_pings_fail_on_a_refusal(
    tmp_path, plan_result, codes, hc_url, expect_ping
):
    """A plan refusal (no matrix, no artifacts) must still produce a summary
    row and a /fail ping; no artifact for a planned code is a /fail; an unset
    secret pings nothing and does not fail; and a fully green run pings the
    PLAIN url (the last row writes a this-attempt ✅ artifact).
    Mutant: hard-code `endpoint="$HC_URL/fail"` -- the check could then never
    recover from its first failure."""
    summary = tmp_path / "summary.md"
    write(summary, "")
    if expect_ping == "https://hc.example/u":
        write(
            tmp_path / "outcomes/outcome-school-01.json",
            '{"code": "school-01", "run_attempt": 1, "from": "sha-a", '
            '"to": "v1.1.0", "result": "success", "now_on": "sha-b"}',
        )
    calls = tmp_path / "curl"
    write(calls, "")
    prelude = (
        f'python3() {{ "{posix(sys.executable)}" "$@"; }}\n'
        f'curl() {{ echo "$@" >> "{posix(calls)}"; return 7; }}\n'
    )
    env = dict(
        os.environ,
        PLAN_RESULT=plan_result,
        CODES=codes,
        RUN_ATTEMPT="1",
        HC_URL=hc_url,
        RUN_URL="https://run/1",
        GITHUB_STEP_SUMMARY=str(summary),
    )
    result = subprocess.run(  # noqa: S603 -- fixed argv, generated script
        [BASH, "-e", "-c", prelude + _report_script(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    if expect_ping:
        assert calls.read_text().strip().endswith(expect_ping)
        if not expect_ping.endswith("/fail"):
            assert "/fail" not in calls.read_text()
    else:
        assert calls.read_text().strip() == ""
    if plan_result == "failure":
        assert "plan refused" in summary.read_text(encoding="utf-8")
