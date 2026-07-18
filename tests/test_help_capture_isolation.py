"""The capture module must never run in CI (unit or e2e) but must be collectable on
explicit invocation. These checks shell out to `pytest --collect-only` in a subprocess
(an in-process test cannot observe another collection)."""

import subprocess
import sys

from django.conf import settings

CAP = "tests/capture_help_screenshots.py"
CAP_NODE = "test_capture_help_screenshots"


def _collect(args):
    # No -q: on this pytest version, --collect-only -q prints a per-file count
    # (e.g. "tests/capture_help_screenshots.py: 1") rather than node ids, so a
    # substring check for CAP_NODE would never match even when collection succeeds.
    # The verbose form lists full node ids and stays fast (~5s over the whole tree).
    proc = subprocess.run(  # noqa: S603 -- fixed args, not untrusted input
        [sys.executable, "-m", "pytest", "--collect-only", *args],
        cwd=str(settings.BASE_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    return proc.stdout + proc.stderr


def test_capture_not_collected_by_bare_run():
    # One full walk of tests/ (mirrors the unit CI job's bare auto-collection). The
    # capture file is not test_-prefixed, so it is absent. This is the ONLY check that
    # walks the whole tree; keep the timeout generous.
    out = _collect(["tests"])
    assert CAP_NODE not in out


def test_capture_deselected_under_e2e_marker():
    # Even on an explicit path, -m e2e deselects the unmarked capture fn (cheap: one
    # file, no tree walk). The `e2e` marker is registered in pyproject.toml (no
    # strict-markers), so `-m e2e` does not error.
    out = _collect(["-m", "e2e", CAP])
    assert CAP_NODE not in out


def test_capture_collected_on_explicit_path():
    # Explicit path bypasses the python_files filter; the test_-named fn is collected.
    out = _collect([CAP])
    assert CAP_NODE in out
