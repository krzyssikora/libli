"""scripts/release/remote_deploy.sh -- the detached bootstrap (spec §2 step 6).

Real bash, setsid, nohup and tail: faking bash would leave the wrapper's quoting
unparsed, and faking setsid/nohup would remove the very detachment under test.
Only git history (real, in a fixture) and the target deploy.sh (a fake that
reports what it received) are stand-ins. Needs util-linux setsid and GNU
`tail --pid`: skipped on Git Bash for Windows, run in CI. Locally, in Linux
(python:3.13, as CI; on 3.12 `_run` fails with "I/O operation on closed file"):

    MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/src" -w /src python:3.13 bash -c \\
      "pip install -q pytest && git config --global user.email t@t \\
       && git config --global user.name t && python -m pytest -p no:cacheprovider \\
       -o addopts='' --noconftest tests/test_release_remote_deploy.py"
"""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from tests.release_harness import BASH
from tests.release_harness import ROOT
from tests.release_harness import Box
from tests.release_harness import posix
from tests.release_harness import write

SCRIPT = ROOT / "scripts/release/remote_deploy.sh"

pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("setsid") is None,
    reason="needs bash and util-linux setsid (Linux; runs in CI)",
)

FAKE_DEPLOY = """#!/usr/bin/env bash
# fake target deploy.sh -- knows LIBLI_DEPLOY_REF LIBLI_DEPLOY_EXPECT_SHA
# and LIBLI_DEPLOY_SKIP_FETCH
echo "SCRIPT=$0"
got="ref=$LIBLI_DEPLOY_REF expect=$LIBLI_DEPLOY_EXPECT_SHA"
echo "$got skip=$LIBLI_DEPLOY_SKIP_FETCH"
if read -r line; then echo "GOT-STDIN:$line"; else echo "STDIN-EOF"; fi
for i in $(seq 1 "${FAKE_LINES:-3}"); do echo "line $i"; done
sleep "${FAKE_SLEEP:-0}"
test -f "$0" && echo SELF-PRESENT
if [ -n "${FAKE_KILL_WRAPPER:-}" ]; then kill -9 "$PPID"; fi
echo FAKE-DONE
exit "${FAKE_RC:-0}"
"""


@pytest.fixture
def box(tmp_path):
    b = Box(tmp_path)
    sha = b.commit(extra={"deploy.sh": FAKE_DEPLOY}, msg="A")
    b.tag("v1.0.0", sha)
    b.clone(
        sha,
        detached=True,
        image_tag=f"sha-{sha}",
        channel_line="LIBLI_DEPLOY_CHANNEL=release",
    )
    b.sha = sha
    b.state = tmp_path / "state"
    b.logs = tmp_path / "logs"
    return b


def _text(box, *, pid_wait=None, start_cmd=None):
    text = (
        SCRIPT.read_text(encoding="utf-8")
        .replace("APP_DIR=/opt/libli", f"APP_DIR={posix(box.app)}")
        .replace("/var/lib/libli-deploy", posix(box.state))
        .replace("/var/log/libli-deploy", posix(box.logs))
    )
    if pid_wait is not None:
        text = text.replace("PID_WAIT_SECONDS=30", f"PID_WAIT_SECONDS={pid_wait}")
    if start_cmd is not None:
        text = text.replace("setsid nohup bash -c", f"{start_cmd} bash -c")
    return text


def _start(box, *, extra_stdin="", env=None, **text_kw):
    e = dict(os.environ)
    e.update(env or {})
    proc = subprocess.Popen(  # noqa: S603 -- fixed argv
        [BASH, "-s", "--", "v1.0.0", box.sha],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=e,
        start_new_session=True,
    )
    proc.stdin.write(_text(box, **text_kw) + extra_stdin)
    proc.stdin.close()
    return proc


def _run(box, **kw):
    proc = _start(box, **kw)
    out, err = proc.communicate(timeout=60)
    return proc.returncode, out, err


def _wait_for(predicate, seconds=15):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def _status_files(box):
    """Finished status files only: the wrapper writes status.X.tmp and renames
    it, and a poll that caught the .tmp could read it empty or lose it."""
    return sorted(p for p in box.state.glob("status.*") if p.suffix != ".tmp")


def _log_text(box):
    if not box.logs.is_dir():
        return ""
    return "".join(p.read_text() for p in sorted(box.logs.glob("*.log")))


def _deploy_started(box):
    """The detached run EXISTS: a non-empty pid file (the wrapper wrote it)
    and the fake deploy's first line in the log. The mktemp placeholder the
    script creates and deletes is empty, so matching the glob alone would
    race it and kill the session before setsid ran."""
    return _pid_written(box) and "SCRIPT=" in _log_text(box)


def _pid_written(box):
    return box.state.is_dir() and any(
        p.stat().st_size > 0 for p in box.state.glob("pid.*")
    )


def test_the_deploy_receives_ref_expected_sha_and_skip_fetch(box):
    """Mutant: drop the positional hand-off to the wrapper (use "$version" etc.
    inside the single-quoted body)."""
    rc, out, err = _run(box)
    assert rc == 0, err
    assert f"ref=v1.0.0 expect={box.sha} skip=1" in out


def test_the_deploy_reads_eof_not_the_rest_of_the_script(box):
    """remote_deploy.sh itself arrives on stdin. Mutant: replace `< /dev/null`
    with `<&0` (re-attach the session's stdin). Merely DROPPING `< /dev/null`
    cannot go red: a non-interactive bash already gives an `&` command
    /dev/null as stdin. The explicit redirect stays as documentation."""
    rc, out, err = _run(box, extra_stdin="\necho SWALLOWED-LINE\n")
    assert rc == 0, err
    assert "STDIN-EOF" in out and "GOT-STDIN" not in out


def test_killing_the_session_leaves_the_detached_run_to_finish(box):
    """The ssh session dying (job timeout, cancel) must not stop the deploy.
    Mutant: run deploy.sh in the foreground instead of under setsid nohup."""
    proc = _start(box, env={"FAKE_SLEEP": "2"})
    assert _wait_for(lambda: _deploy_started(box))
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)
    assert _wait_for(lambda: _status_files(box))
    assert _status_files(box)[0].read_text().strip() == "0"
    assert "FAKE-DONE" in _log_text(box)
    assert "SELF-PRESENT" in _log_text(box)


def test_a_closed_session_pipe_does_not_kill_the_run(box):
    """Mutant: drop the `>>"$log" 2>&1` redirect (the run inherits the
    session's stdout and dies of SIGPIPE when it closes). The start condition
    here is the pid file alone, NOT the log. Under the mutant the wrapper itself
    writes nothing to stdout, so it survives and records the fake deploy's
    SIGPIPE death as status 141: the RED must come from the `== "0"` status
    assertion -- the run died -- not from the log being empty."""
    proc = _start(box, env={"FAKE_SLEEP": "2"})
    assert _wait_for(lambda: _pid_written(box))
    time.sleep(0.5)
    proc.stdout.close()
    os.killpg(proc.pid, signal.SIGKILL)
    assert _wait_for(lambda: _status_files(box))
    assert _status_files(box)[0].read_text().strip() == "0"
    assert "FAKE-DONE" in _log_text(box)


def test_the_session_returns_promptly_and_cleans_up(box):
    start = time.time()
    rc, out, err = _run(box)
    assert rc == 0, err
    assert (
        time.time() - start < 20
    )  # tail --pid polls every second; generous under -n auto
    assert not list(box.state.glob("pid.*")) and not _status_files(box)


def test_a_non_zero_status_becomes_the_exit_code(box):
    rc, out, err = _run(box, env={"FAKE_RC": "3"})
    assert rc == 3


def test_no_recorded_status_exits_1(box):
    rc, out, err = _run(box, env={"FAKE_KILL_WRAPPER": "1"})
    assert rc == 1
    assert "no status" in err


def test_a_hung_up_session_leaves_the_script_for_the_run(box):
    """A real dropped session ends with a TRAPPABLE signal (HUP/PIPE/TERM),
    which runs the session's EXIT trap -- unlike the SIGKILL in the kill test.
    Mutant: remove the temp script from an EXIT trap in the SESSION instead of
    in the wrapper -> the detached run finds its script gone (no SELF-PRESENT)."""
    proc = _start(box, env={"FAKE_SLEEP": "2"})
    assert _wait_for(lambda: _deploy_started(box))
    os.killpg(proc.pid, signal.SIGHUP)
    proc.wait(timeout=10)
    assert _wait_for(lambda: _status_files(box))
    assert "SELF-PRESENT" in _log_text(box)


def test_the_temp_script_is_removed_by_the_wrapper(box):
    """Present while the run needs it, gone afterwards. Mutant: never remove
    it. (Removing it from a SESSION trap instead is caught by
    test_a_hung_up_session_leaves_the_script_for_the_run.)"""
    rc, out, err = _run(box)
    assert rc == 0, err
    assert "SELF-PRESENT" in out
    script = next(
        ln[len("SCRIPT=") :] for ln in out.splitlines() if ln.startswith("SCRIPT=")
    )
    assert not Path(script).exists(), script


def test_every_early_line_is_shown(box):
    """Mutant: `tail -f` without `-n +1` (starts at the last 10 lines)."""
    rc, out, err = _run(box, env={"FAKE_LINES": "40"})
    assert all(f"line {i}\n" in out for i in range(1, 41))


def test_logs_are_capped_at_twenty(box):
    box.logs.mkdir(parents=True)
    now = time.time()
    for i in range(25):
        p = box.logs / f"old-{i:02d}.log"
        write(p, "x\n")
        os.utime(p, (now - 1000 + i, now - 1000 + i))
    rc, out, err = _run(box)
    assert rc == 0, err
    remaining = sorted(p.name for p in box.logs.glob("*.log"))
    assert len(remaining) == 20
    assert "old-05.log" not in remaining and "old-06.log" in remaining


def test_stale_state_files_are_swept_at_start(box):
    box.state.mkdir(parents=True)
    stale = box.state / "status.stale"
    fresh = box.state / "status.fresh"
    write(stale, "0\n")
    write(fresh, "0\n")
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    rc, out, err = _run(box)
    assert rc == 0, err
    assert not stale.exists() and fresh.exists()


def test_a_wrapper_that_never_reports_its_pid_says_it_may_still_start(box):
    rc, out, err = _run(box, pid_wait=2, start_cmd="true")
    assert rc == 1
    assert "may still start" in err


def test_a_target_deploy_sh_missing_a_required_variable_is_refused(tmp_path):
    b = Box(tmp_path)
    old = FAKE_DEPLOY.replace("LIBLI_DEPLOY_EXPECT_SHA", "X")
    sha = b.commit(extra={"deploy.sh": old}, msg="old")
    b.tag("v1.0.0", sha)
    b.clone(
        sha,
        detached=True,
        image_tag=f"sha-{sha}",
        channel_line="LIBLI_DEPLOY_CHANNEL=release",
    )
    b.sha, b.state, b.logs = sha, tmp_path / "state", tmp_path / "logs"
    rc, out, err = _run(b)
    assert rc == 1
    assert "LIBLI_DEPLOY_EXPECT_SHA" in err
    assert not list(b.logs.glob("*.log"))


def test_both_state_directories_are_created(box):
    assert not box.state.exists() and not box.logs.exists()
    rc, out, err = _run(box)
    assert rc == 0, err
    assert box.state.is_dir() and box.logs.is_dir()
