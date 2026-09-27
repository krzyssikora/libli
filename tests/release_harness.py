"""Shared fixtures for the B2 release-deploy tests.

Real git everywhere: history, tags and ancestry ARE what these scripts judge,
so a stubbed git would test nothing. Files are written with write_bytes so a
Windows checkout cannot smuggle CRLF into a bash script, and every fixture repo
sets core.autocrlf=false for the same reason.
"""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")

COMPOSE_TMPL = (
    "services:\n"
    "  db:\n"
    "    image: postgres:{pg}\n"
    "  app:\n"
    "    image: ghcr.io/krzyssikora/libli:${{LIBLI_IMAGE_TAG:?}}\n"
    "    environment:\n"
    "      DATABASE_URL: postgres://u:p@db:5432/libli\n"
)


def posix(path):
    return str(path).replace("\\", "/")


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def git(cwd, *args):
    result = subprocess.run(  # noqa: S603 -- fixed argv
        ["git", *args],  # noqa: S607 -- git on PATH
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def init_repo(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "master")
    for key, value in (
        ("user.name", "test"),
        ("user.email", "test@example.com"),
        ("core.autocrlf", "false"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
    ):
        git(path, "config", key, value)
    return path


def commit_all(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    return git(repo, "rev-parse", "HEAD")
