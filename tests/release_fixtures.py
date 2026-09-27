"""The two .env.production read rules, as ONE set of cases.

deploy.sh and preflight.sh each carry their own copy of channel_state and
image_tag_state -- deliberately not a shared sourced helper, because deploy.sh
runs as a temp copy at the target release and would source the CURRENT
checkout's file (spec §2 step 4). These cases are what keeps the copies equal.
"""

import re
import subprocess

from tests.release_harness import BASH
from tests.release_harness import posix
from tests.release_harness import write

SHA = "0123456789abcdef0123456789abcdef01234567"

CHANNEL_CASES = [
    ("absent", "", "absent"),
    ("release", "LIBLI_DEPLOY_CHANNEL=release\n", "release"),
    ("export", "export LIBLI_DEPLOY_CHANNEL=release\n", "invalid"),
    ("indented", "  LIBLI_DEPLOY_CHANNEL=release\n", "invalid"),
    ("empty", "LIBLI_DEPLOY_CHANNEL=\n", "invalid"),
    ("typo", "LIBLI_DEPLOY_CHANNEL=relase\n", "invalid"),
    ("capital", "LIBLI_DEPLOY_CHANNEL=Release\n", "invalid"),
    ("trailing-space", "LIBLI_DEPLOY_CHANNEL=release \n", "invalid"),
    ("commented", "#LIBLI_DEPLOY_CHANNEL=release\n", "invalid"),
    ("crlf", "LIBLI_DEPLOY_CHANNEL=release\r\n", "invalid"),
    (
        "duplicate",
        "LIBLI_DEPLOY_CHANNEL=release\nLIBLI_DEPLOY_CHANNEL=release\n",
        "invalid",
    ),
    (
        "space-before-equals-duplicate",
        "LIBLI_DEPLOY_CHANNEL=release\nLIBLI_DEPLOY_CHANNEL =nope\n",
        "invalid",
    ),
]

IMAGE_TAG_CASES = [
    ("valid", f"LIBLI_IMAGE_TAG=sha-{SHA}\n", f"sha-{SHA}"),
    ("absent", "", "absent"),
    ("duplicate", f"LIBLI_IMAGE_TAG=sha-{SHA}\nLIBLI_IMAGE_TAG=sha-{SHA}\n", "invalid"),
    ("export", f"export LIBLI_IMAGE_TAG=sha-{SHA}\n", "invalid"),
    ("indented", f"  LIBLI_IMAGE_TAG=sha-{SHA}\n", "invalid"),
    ("crlf", f"LIBLI_IMAGE_TAG=sha-{SHA}\r\n", "invalid"),
    ("short", "LIBLI_IMAGE_TAG=sha-0123abc\n", "invalid"),
    ("tag-name", "LIBLI_IMAGE_TAG=sha-v1.0.0\n", "invalid"),
    (
        "space-before-equals-duplicate",
        f"LIBLI_IMAGE_TAG=sha-{SHA}\nLIBLI_IMAGE_TAG =nope\n",
        "invalid",
    ),
]


def extract_function(script_path, name):
    text = script_path.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{$.*?^\}}$", text, re.MULTILINE | re.DOTALL)
    assert match, f"{script_path.name} defines no top-level {name}()"
    return match.group(0)


def run_function(script_path, names, call, env_file):
    """Define `names` (in order) from script_path, then run `call <env_file>`."""
    body = "\n".join(extract_function(script_path, n) for n in names)
    result = subprocess.run(  # noqa: S603 -- fixed argv, generated script
        [BASH, "-c", f'set -euo pipefail\n{body}\n{call} "{posix(env_file)}"'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def env_file(tmp_path, text):
    path = tmp_path / "env"
    write(path, "OTHER=1\n" + text)
    return path
