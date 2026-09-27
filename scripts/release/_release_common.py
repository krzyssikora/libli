"""Helpers shared by the runner-side release tools (B2).

A refusal is ONE line that is safe to print into a (possibly public) Actions
log: never a host, a domain, a school name or a line of .env.production.
"""

import os
import subprocess
import sys


class Refuse(Exception):
    """Stop, with a message safe to print."""


def refuse_and_exit(message):
    line = f"refuse: {message}"
    print(line, file=sys.stderr)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"**{line}**\n")
    sys.exit(1)


def run_main(fn):
    try:
        fn()
    except Refuse as exc:
        refuse_and_exit(str(exc))


def git(*args):
    """git in the current directory. Returns the CompletedProcess; never raises."""
    return subprocess.run(  # noqa: S603 -- fixed argv
        ["git", *args],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
    )
