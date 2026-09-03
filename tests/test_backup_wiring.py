"""Guards for the backup, restore and image-publishing wiring.

Same rationale and shape as test_deploy_wiring.py: none of these files is
exercised by anything else in the suite -- they are consumed by GitHub Actions
and by a shell on a production host, so the only feedback a mistake produces is
a failed backup nobody notices, or a restore that destroys data before it fails.

Textual, not YAML-parsed: pyyaml is not a dependency.

Each assertion names the mutant that makes it fail. An assertion that cannot go
red is not a guard.
"""

import re
import shutil  # noqa: F401 -- used by guards Tasks 3 and 4 append to this file
import subprocess  # noqa: F401 -- used by guards Tasks 3 and 4 append to this file
from pathlib import Path

import pytest  # noqa: F401 -- used by guards Tasks 3 and 4 append to this file

ROOT = Path(__file__).resolve().parent.parent
DEPLOY_YML = ROOT / ".github/workflows/deploy.yml"
DEPLOY_SH = ROOT / "deploy.sh"
BACKUP_SH = ROOT / "backup.sh"
RESTORE_SH = ROOT / "restore.sh"
COMPOSE = ROOT / "docker-compose.prod.yml"
CADDYFILE = ROOT / "Caddyfile"
RUNBOOK = ROOT / "docs/deployment.md"


def test_publish_job_precedes_the_deploy_step():
    """A deploy that runs before the push tells the box to pull a tag that does
    not exist yet -- failing on the host rather than in CI, which is the slowest
    possible place to find out.

    Mutant: move the publish job below the ssh-action step.
    """
    text = DEPLOY_YML.read_text(encoding="utf-8")
    push = text.find("docker/build-push-action")
    ssh = text.find("appleboy/ssh-action")
    assert push != -1, "deploy.yml no longer publishes an image"
    assert ssh != -1, "deploy.yml no longer deploys"
    assert push < ssh, "the publish step must precede the deploy step"


def test_deploy_logs_in_before_it_pulls():
    """The GHCR package is private (it contains the application source), so an
    un-authenticated pull fails with an opaque `denied`.

    Mutant: delete the docker login line.
    """
    text = DEPLOY_SH.read_text(encoding="utf-8")
    login = text.find("docker login ghcr.io")
    pull = text.find("compose pull")
    assert login != -1, "deploy.sh no longer logs in to ghcr.io"
    assert pull != -1, "deploy.sh no longer pulls"
    assert login < pull, "the login must precede the pull"


def test_no_build_survives_anywhere():
    """The half-finished image switch presents as a box quietly building from
    source while everything else assumes it pulled.

    Mutant: leave a `--build` in deploy.sh or in the runbook's up blocks.
    """
    assert "--build" not in DEPLOY_SH.read_text(encoding="utf-8")
    assert "--build" not in RUNBOOK.read_text(encoding="utf-8")


def test_compose_pulls_a_pinned_tag_rather_than_building():
    """`build: .` on the app service is what this task removes. The tag is
    guarded with the bare `:?` form the file already uses for every mandatory
    value, so a blank fails at `up` rather than pulling something unintended.

    Mutant: restore `build: .`, or drop the `:?` guard.
    """
    text = COMPOSE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*build:\s*\.\s*$", text, re.MULTILINE), text
    assert "ghcr.io/krzyssikora/libli:${LIBLI_IMAGE_TAG:?}" in text, text
