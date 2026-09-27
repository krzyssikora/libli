"""scripts/release/preflight.sh -- the on-box pre-flight (spec §2 step 4)."""

import os
import subprocess
import sys

import pytest

from tests.release_fixtures import CHANNEL_CASES
from tests.release_fixtures import IMAGE_TAG_CASES
from tests.release_fixtures import env_file
from tests.release_fixtures import extract_function
from tests.release_fixtures import run_function
from tests.release_harness import BASH
from tests.release_harness import ROOT
from tests.release_harness import Box
from tests.release_harness import git
from tests.release_harness import posix

PREFLIGHT = ROOT / "scripts/release/preflight.sh"
DEPLOY_SH = ROOT / "deploy.sh"

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not on PATH")

# Git for Windows' awk strips \r from each input line (measured: length("ab\r")
# == 2), so the CRLF cases below can never see the value they exist to check
# on this machine. They are correct and pass on Linux/CI; skip only here.
_win_crlf_skip = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Git for Windows awk strips \\r; CI (Linux) runs this",
)


def _mark_crlf(cases):
    return [
        pytest.param(*case, marks=_win_crlf_skip) if case[0] == "crlf" else case
        for case in cases
    ]


@pytest.mark.parametrize("name", ["channel_state", "image_tag_read", "image_tag_state"])
def test_the_read_rule_functions_are_textually_identical(name):
    """A shared case list only catches a divergence its cases happen to exercise
    (e.g. dropping the optional whitespace before `=` in one copy's regex changes
    the verdict only on a `KEY =value` line paired with a valid one -- a shape most
    case lists never think to add). Textual identity closes that gap outright.

    Mutant: in preflight.sh's channel_state, drop `[[:space:]]*` before the `=` in
    `LIBLI_DEPLOY_CHANNEL[[:space:]]*=` (same edit works for image_tag_read's
    `LIBLI_IMAGE_TAG[[:space:]]*=`).
    """
    assert extract_function(PREFLIGHT, name) == extract_function(DEPLOY_SH, name)


@pytest.mark.parametrize(
    "case_id,text,expected",
    _mark_crlf(CHANNEL_CASES),
    ids=[c[0] for c in CHANNEL_CASES],
)
def test_the_channel_rule_is_identical_in_both_scripts(
    tmp_path, case_id, text, expected
):
    """Mutant: edit either copy's regex (e.g. accept an `export` prefix)."""
    f = env_file(tmp_path, text)
    for script in (DEPLOY_SH, PREFLIGHT):
        got = run_function(script, ["channel_state"], "channel_state", f)
        assert got == expected, script.name


@pytest.mark.parametrize(
    "case_id,text,expected",
    _mark_crlf(IMAGE_TAG_CASES),
    ids=[c[0] for c in IMAGE_TAG_CASES],
)
def test_the_image_tag_rule_is_identical_in_both_scripts(
    tmp_path, case_id, text, expected
):
    f = env_file(tmp_path, text)
    for script in (DEPLOY_SH, PREFLIGHT):
        names = ["image_tag_read", "image_tag_state"]
        got = run_function(script, names, "image_tag_state", f)
        assert got == expected, script.name


def _script(box):
    return PREFLIGHT.read_text(encoding="utf-8").replace(
        "APP_DIR=/opt/libli", f"APP_DIR={posix(box.app)}"
    )


def _preflight(box, *args):
    return subprocess.run(  # noqa: S603 -- fixed argv
        [BASH, "-s", "--", *args],
        input=_script(box),
        capture_output=True,
        text=True,
        env=dict(os.environ, GIT_FETCH_DELAY="0"),
        timeout=60,
    )


@pytest.fixture
def school(tmp_path):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    b = box.commit(extra={"README": "b\n"}, msg="B")
    box.tag("v1.1.0", b)
    box.clone(
        a,
        detached=True,
        image_tag=f"sha-{a}",
        channel_line="LIBLI_DEPLOY_CHANNEL=release",
    )
    return box, a, b


def test_success_prints_exactly_two_lines(school):
    box, a, b = school
    result = _preflight(box, "v1.1.0", b)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [f"image_tag=sha-{a}", "channel=release"]


def test_read_only_prints_one_line_and_does_not_fetch(school):
    box, a, b = school
    git(box.app, "remote", "set-url", "origin", "/nonexistent/origin.git")
    result = _preflight(box, "--read-only")
    assert result.returncode == 0, result.stdout
    assert result.stdout.splitlines() == [f"image_tag=sha-{a}"]


def test_a_box_without_the_channel_line_is_refused(tmp_path):
    """Mutant: drop the channel check from preflight.sh."""
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(a, detached=True, image_tag=f"sha-{a}")
    result = _preflight(box, "v1.0.0", a)
    assert result.returncode != 0
    assert result.stdout.startswith("refuse: ")
    assert "LIBLI_DEPLOY_CHANNEL" in result.stdout


def test_an_absent_tag_is_refused(tmp_path):
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(
        a,
        detached=True,
        image_tag=None,
        channel_line="LIBLI_DEPLOY_CHANNEL=release",
    )
    result = _preflight(box, "v1.0.0", a)
    assert result.returncode != 0
    assert "LIBLI_IMAGE_TAG absent" in result.stdout


def test_no_refusal_ever_echoes_the_file(tmp_path):
    """The box's .env.production holds every secret. A sentinel secret sits next
    to a malformed tag line whose VALUE is also a sentinel.

    Mutant: include the offending line in the refusal message.
    """
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(
        a,
        detached=True,
        image_tag="sha-SENTINEL-TAG-77",
        channel_line="LIBLI_DEPLOY_CHANNEL=release",
    )
    for args in (("v1.0.0", a), ("--read-only",)):
        result = _preflight(box, *args)
        assert result.returncode != 0
        out = result.stdout + result.stderr
        assert "SENTINEL" not in out, out


@_win_crlf_skip
def test_a_crlf_env_file_is_refused_with_a_reason_that_says_so(tmp_path):
    """Review focus 1: an env file saved on Windows."""
    box = Box(tmp_path)
    a = box.commit(msg="A")
    box.tag("v1.0.0", a)
    box.clone(
        a,
        detached=True,
        image_tag=f"sha-{a}",
        channel_line="LIBLI_DEPLOY_CHANNEL=release",
    )
    path = box.app / ".env.production"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    result = _preflight(box, "v1.0.0", a)
    assert result.returncode != 0
    assert "CRLF" in result.stdout


def test_a_stale_local_tag_is_replaced_by_the_forced_fetch(school):
    """Mutant: fetch `refs/tags/<v>:refs/tags/<v>` without the leading `+`."""
    box, a, b = school
    git(box.app, "tag", "-f", "v1.1.0", a)
    result = _preflight(box, "v1.1.0", b)
    assert result.returncode == 0, result.stdout


def test_a_tag_resolving_to_another_commit_is_refused(school):
    """Mutant: drop the target-sha comparison."""
    box, a, b = school
    result = _preflight(box, "v1.1.0", a)
    assert result.returncode != 0
    assert "different commit" in result.stdout


GIT_FLAKE_STUB = """git() {
  if [ "$1" = fetch ]; then
    n=$(( $(cat "@@COUNTER@@" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "@@COUNTER@@"
    if [ "$n" -le 2 ]; then return 128; fi
  fi
  command git "$@"
}
"""


def test_the_tag_fetch_retries(school):
    """The first two fetches fail (the anonymous-401 flake), the third works.
    Mutant: a single `git fetch` with no loop."""
    box, a, b = school
    git(box.app, "tag", "-d", "v1.1.0")
    counter = box.tmp / "fetches"
    stub = GIT_FLAKE_STUB.replace("@@COUNTER@@", posix(counter))
    result = subprocess.run(  # noqa: S603 -- fixed argv
        [BASH, "-s", "--", "v1.1.0", b],
        input=stub + _script(box),
        capture_output=True,
        text=True,
        env=dict(os.environ, GIT_FETCH_DELAY="0"),
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert counter.read_text().strip() == "3"


def test_an_unfetchable_tag_names_both_causes(school):
    box, a, b = school
    git(box.app, "remote", "set-url", "origin", "/nonexistent/origin.git")
    result = _preflight(box, "v1.1.0", b)
    assert result.returncode != 0
    assert "re-run" in result.stdout and "deploy key" in result.stdout


@pytest.mark.parametrize("args", [("v1.1", "a" * 40), ("v1.1.0", "abc")])
def test_malformed_arguments_are_refused(school, args):
    box, a, b = school
    result = _preflight(box, *args)
    assert result.returncode != 0
    assert result.stdout.startswith("refuse: ")
