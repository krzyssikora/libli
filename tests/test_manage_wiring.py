"""Guards for manage.sh: the host-side wrapper that runs manage.py in the app container.

Like deploy.sh, it is consumed only by a shell on the production host -- by hand and
from cron -- so nothing else in the suite runs it. A broken wrapper shows up as a
cron job that stopped doing its work with nobody watching.

The executed tests run the SHIPPED script with `cd` and `docker` replaced by shell
functions. A function shadows both a builtin and a PATH lookup on every platform,
while an executable stub depends on an exec bit Windows does not really set -- the
same reasoning as test_deploy_wiring.py's fetch harness.

Each assertion names the mutant that makes it fail.
"""

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANAGE_SH = ROOT / "manage.sh"
DEPLOY_SH = ROOT / "deploy.sh"

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")


def _posix(path):
    return str(path).replace("\\", "/")


def _app_dir(path):
    match = re.search(
        r"^APP_DIR=(\S+)$", path.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert match, f"{path.name} no longer assigns APP_DIR at the top level"
    return match.group(1)


def _deploy_compose_prefix():
    """The `docker compose ...` arguments deploy.sh's compose() helper passes, read
    from deploy.sh rather than restated here -- the compose file and env file the
    stack was actually brought up with."""
    text = DEPLOY_SH.read_text(encoding="utf-8")
    match = re.search(r"^compose\(\) \{\n\s*docker (.+) \"\$@\"$", text, re.MULTILINE)
    assert match, "deploy.sh no longer defines compose() as a docker compose call"
    return shlex.split(match.group(1))


def _run(tmp_path, *args, docker_rc=0):
    """Run manage.sh with stdin and stdout both NON-terminals: the cron and pipe case.

    Returns the completed process, the directory `cd` was given, and the argv
    `docker` received, one element per list item so argument boundaries are visible.
    """
    cd_log = tmp_path / "cd"
    docker_log = tmp_path / "docker"
    prelude = (
        f'cd() {{ printf "%s\\n" "$@" > "{_posix(cd_log)}"; }}\n'
        f'docker() {{ printf "%s\\n" "$@" > "{_posix(docker_log)}"; '
        f"return {docker_rc}; }}\n"
    )
    script = (
        f"{prelude}set -- {' '.join(shlex.quote(a) for a in args)}\n"
        f'source "{_posix(MANAGE_SH)}"\n'
    )
    result = subprocess.run(  # noqa: S603 -- fixed argv, generated script
        [shutil.which("bash"), "-c", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )

    def lines(p):
        return p.read_text().splitlines() if p.exists() else []

    return result, lines(cd_log), lines(docker_log)


@needs_bash
def test_manage_script_parses():
    """A syntax error is otherwise found on the production host, by cron, at night.

    Mutant: drop the closing `fi`.
    """
    result = subprocess.run(  # noqa: S603 -- fixed argv, repo-relative path
        [shutil.which("bash"), "-n", str(MANAGE_SH)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@needs_bash
def test_without_a_terminal_the_command_reaches_the_app_container(tmp_path):
    """The cron/pipe path end to end: the deploy checkout, deploy.sh's compose
    flags, `-T`, the app service, and every argument intact.

    Mutants: drop the `-T` branch (cron gets a TTY it does not have); pass `$*`
    instead of "$@" (`print(1, 2)` splits in two); name a different env file or
    service; delete the `cd` (compose cannot find its file from another directory).
    """
    result, cd_args, argv = _run(tmp_path, "shell", "-c", "print(1, 2)")
    assert result.returncode == 0, result.stderr
    assert cd_args == [_app_dir(DEPLOY_SH)], cd_args
    assert argv == [
        *_deploy_compose_prefix(),
        "exec",
        "-T",
        "app",
        "/app/.venv/bin/python",
        "manage.py",
        "shell",
        "-c",
        "print(1, 2)",
    ], argv


@needs_bash
def test_a_failing_command_fails_the_script(tmp_path):
    """Cron and `set -e` callers only see the wrapper's status. A wrapper that
    swallows it turns a broken purge into a green one -- on a job whose silent
    failure leaves live demo logins on prod (docs/deployment.md §7).

    Mutant: append `|| true` to the docker call.
    """
    result, _, _ = _run(tmp_path, "demo_access", "purge", docker_rc=3)
    assert result.returncode == 3, (result.returncode, result.stderr)


def test_a_tty_needs_both_stdin_and_stdout_to_be_a_terminal():
    """The TTY branch cannot be executed here -- there is no pseudo-terminal on
    Windows or in CI -- so this one reads the text.

    A check on stdin alone passes every executed test above, yet
    `x=$(bash manage.sh shell -c ...)` typed at a terminal would get a TTY and a
    trailing carriage return in x.

    Mutant: drop the `[ ! -t 1 ]` half of the condition (or the `[ ! -t 0 ]` half).
    """
    code = "\n".join(
        ln
        for ln in MANAGE_SH.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )
    condition = re.search(r"^if (.+); then\n\s*tty_flag=\(-T\)$", code, re.MULTILINE)
    assert condition, code
    assert "! -t 0" in condition.group(1), condition.group(1)
    assert "! -t 1" in condition.group(1), condition.group(1)
