# School Backups and Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every school box a nightly, encrypted, off-box backup and a single restore script that also serves resize, provider-move and handover.

**Architecture:** Two straight-line bash scripts (`backup.sh`, `restore.sh`) beside the existing `deploy.sh`, writing to one Hetzner Storage Box over plain SSH/rsync with `age` public-key encryption. The box is switched from building its own image to pulling a published GHCR one, because a restore must be able to start the exact version a dump came from. One new Django management command (`list_referenced_files`) tells the restore which files it actually needs. Everything that cannot be unit-tested is pinned by textual wiring guards in the style of `tests/test_deploy_wiring.py`.

**Tech Stack:** bash, Docker Compose, PostgreSQL 16 (`pg_dump -Fc`), `age`, rsync over SSH, GitHub Actions (`docker/build-push-action`), GHCR, Django 5.2 management commands, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-school-backups-and-restore-design.md`

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include these.

- **`backup.sh` and `restore.sh` are straight-line scripts.** No function indirection around the ordered steps — several guards are source-order assertions and a refactor into `dump_db()` / `mirror_media()` would break them or pass them for the wrong reason. Both scripts say so in their headers.
- **`set -euo pipefail` is the first executable line of all three scripts.** `pipefail` is load-bearing: without it a `pg_dump` that dies part-way while `age` exits 0 yields a short, well-formed, encrypted file and a *green* heartbeat.
- **`--delete` must appear nowhere in `backup.sh`.** `media/` keeps deleted files on purpose; `screenshots/` erases via an explicit `rm` of a computed list.
- **Media paths are preserved exactly.** `MediaAsset` filenames are not content-addressed; a rename breaks every `FileField` in the database.
- **The shared lock path is `/var/lock/libli-deploy.lock`** for all three scripts. Held-lock behaviour differs: `backup.sh` exits 0 quietly, `deploy.sh` waits then fails, `restore.sh` fails immediately and loudly.
- **Retention constants live at the top of `backup.sh`:** `RETAIN_DAILY_DAYS=30`, `RETAIN_MONTHLY_MONTHS=12`, `MIRROR_PRUNE_DAYS=90`. Both privacy notices state these and a guard ties them together.
- **`<ts>` is `YYYY-MM-DDTHHMMSS` in UTC.** The host clock is UTC.
- **The `.env.production` key for SMTP is `DJANGO_EMAIL_HOST_PASSWORD`**, not `EMAIL_HOST_PASSWORD` (that is only the Django setting name).
- **No code in this work creates, writes or reads `wal/`.** It is a naming reservation in documentation only.
- **Never run whole-repo pytest sweeps as a task step.** Scope each run to the named test file. A full sweep is a branch gate, not a task step.
- **Start the test-DB container before running pytest**, or the run looks hung for four minutes.
- **Never pass `-q` to pytest** — `addopts` already has it, and a second one suppresses the `N passed` summary line so the run reads as a hang.

---

### Task 1: `list_referenced_files` management command

The only new Python in B1. Both scripts need it: `backup.sh` writes its output to `refs/<ts>.txt`, and `restore.sh` uses it to fetch exactly the files the restored database references rather than the whole mirror (which would resurrect every deleted file — and Caddy serves `media/` directly, so a resurrected file is reachable at its URL with no row pointing at it).

Output is tab-separated `<volume>\t<relative-path>`, one per line. The volume name is the first column so the shell consumer maps straight to `vol_path()` with no translation table.

**Files:**
- Create: `courses/management/commands/list_referenced_files.py`
- Test: `tests/test_list_referenced_files.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `python manage.py list_referenced_files` printing lines of the form `media\tcourses/media/foo.png` and `support_screenshots\tscreenshots/2026/09/<uuid>.png`. Tasks 3 and 4 invoke it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_list_referenced_files.py`:

```python
"""The restore's file list. A missing field here means a restore silently
drops files -- the database references them, nothing fetches them, and the
gap surfaces only when a pupil opens the lesson.

Every file-bearing field in the project must appear. test_every_filefield_is_covered
is the drift guard: add a FileField to any model and it goes red until the
command is taught about it.
"""

from io import StringIO

import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import models

pytestmark = pytest.mark.django_db


def _run():
    out = StringIO()
    call_command("list_referenced_files", stdout=out)
    return [line.split("\t") for line in out.getvalue().splitlines()]


def test_media_asset_file_is_listed(image_asset):
    rows = _run()
    assert ["media", image_asset.file.name] in rows


def test_blank_fields_are_skipped(image_asset):
    image_asset.thumb = ""
    image_asset.web = ""
    image_asset.save(update_fields=["thumb", "web"])
    paths = [path for _, path in _run()]
    assert "" not in paths


def test_paths_are_relative_and_forward_slashed(image_asset):
    for volume, path in _run():
        assert volume in {"media", "support_screenshots"}
        assert not path.startswith("/")
        assert "\\" not in path


def test_every_filefield_is_covered():
    """Drift guard. The command enumerates a fixed list of (model, field)
    pairs; this asserts that list is the WHOLE set of FileFields in the
    project, so a new one cannot be silently omitted.

    Mutant: add a FileField to any model without updating SOURCES -> RED.
    """
    from courses.management.commands.list_referenced_files import SOURCES

    declared = {(model_label, field) for model_label, field in SOURCES}
    actual = set()
    for model in apps.get_models():
        if model._meta.app_label in {"admin", "auth", "contenttypes", "sessions"}:
            continue
        for field in model._meta.get_fields():
            if isinstance(field, models.FileField):
                actual.add((model._meta.label_lower, field.name))
    assert declared == actual, f"missing: {actual - declared}; stale: {declared - actual}"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_list_referenced_files.py -v
```

Expected: FAIL — `Unknown command: 'list_referenced_files'`.

If the `image_asset` fixture does not exist in `tests/conftest.py`, find the equivalent MediaAsset factory in `tests/factories.py` and use it; do not invent a new fixture name.

- [ ] **Step 3: Write the command**

Create `courses/management/commands/list_referenced_files.py`:

```python
"""Print every file the database references, as <volume>\\t<relative-path>.

Consumed by backup.sh (writes it to refs/<ts>.txt) and by restore.sh (fetches
exactly these paths rather than the whole mirror).

Fetching the whole mirror instead would resurrect every file deleted in the
last MIRROR_PRUNE_DAYS -- and Caddy serves /media/ straight off the volume, so
a resurrected file is reachable at its URL whether or not any row points at it.

SOURCES is a fixed list rather than a scan so the output is deterministic and
reviewable. tests/test_list_referenced_files.py asserts it is exhaustive.
"""

from django.apps import apps
from django.core.management.base import BaseCommand

# (model label, field name). The volume comes from VOLUME_BY_MODEL below and is
# emitted as the first column, so the shell consumer maps it straight to
# vol_path() with no translation table.
SOURCES = [
    ("courses.mediaasset", "file"),
    ("courses.mediaasset", "thumb"),
    ("courses.mediaasset", "web"),
    ("institution.institution", "logo"),
    ("institution.institution", "favicon"),
    ("support.issuereport", "screenshot"),
]

# Which volume each model's files live on. IssueReport.screenshot uses
# ScreenshotStorage (SUPPORT_SCREENSHOT_DIR); everything else is MEDIA_ROOT.
VOLUME_BY_MODEL = {
    "support.issuereport": "support_screenshots",
}


class Command(BaseCommand):
    help = "Print every file the database references, as <volume>\\t<path>."

    def handle(self, *args, **options):
        seen = set()
        for model_label, field_name in SOURCES:
            model = apps.get_model(model_label)
            volume = VOLUME_BY_MODEL.get(model_label, "media")
            for name in (
                model.objects.exclude(**{field_name: ""})
                .exclude(**{f"{field_name}__isnull": True})
                .values_list(field_name, flat=True)
                .iterator()
            ):
                if not name:
                    continue
                row = (volume, str(name).replace("\\", "/"))
                if row not in seen:
                    seen.add(row)
                    self.stdout.write(f"{row[0]}\t{row[1]}")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_list_referenced_files.py -v
```

Expected: PASS. Grep the summary line for `passed` — a pytest exit code of 0 can coexist with `1 failed`.

- [ ] **Step 5: Falsify the drift guard**

By hand (never with a script, and never revert with `git checkout` — edit it back by hand), add a temporary `FileField` to any model, e.g. in `institution/models.py`:

```python
    scratch = models.FileField(upload_to="scratch/", blank=True)
```

Run `uv run pytest tests/test_list_referenced_files.py::test_every_filefield_is_covered -v`. Expected: **FAIL**, naming `('institution.institution', 'scratch')` as missing. Then remove the line by hand and re-run to confirm PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --no-cache courses/management/commands/list_referenced_files.py tests/test_list_referenced_files.py
uv run ruff format --check courses/management/commands/list_referenced_files.py tests/test_list_referenced_files.py
git add courses/management/commands/list_referenced_files.py tests/test_list_referenced_files.py
git commit -m "feat(courses): list every file the database references

Consumed by the backup and restore scripts. Restoring the whole media
mirror instead would resurrect every recently-deleted file, and Caddy
serves /media/ straight off the volume -- so a resurrected file is
reachable at its URL with no row pointing at it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Aopus3KuLErHrHWKWeiKe"
```

---

### Task 2: Publish the image to GHCR and stop building on the box

Nothing in the repo builds or pushes an image today — `.github/workflows/` has only `ci.yml` (tests, on PRs) and `deploy.yml` (SSH + `deploy.sh`), and `deploy.sh` runs `compose up -d --build`. The whole pull-don't-build model has no producer until this task adds one.

This is in B1 because restore depends on it: without a pullable immutable tag, "start the version this dump came from" is a source rebuild — the RAM spike that makes 4 GB a real floor, on a box being brought back under pressure.

**Files:**
- Modify: `.github/workflows/deploy.yml` (add a `publish` job before the deploy job)
- Modify: `docker-compose.prod.yml` (the `app` service: `build: .` → `image:`)
- Modify: `deploy.sh` (login, pull, write `LIBLI_IMAGE_TAG`, drop `--build`)
- Modify: `.env.production.example` (add `LIBLI_IMAGE_TAG`, `LIBLI_GHCR_TOKEN`)
- Modify: `docs/deployment.md` (§1 login step, §3 first-boot block, §8 rollback block, *Known constraints* "No rollback" bullet)
- Modify: `tests/test_deploy_wiring.py:174` (the `--build` assertion)
- Test: `tests/test_backup_wiring.py` (new file — guards 10 and 18)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: images at `ghcr.io/krzyssikora/libli:master` and `ghcr.io/krzyssikora/libli:sha-<short>`; the `.env.production` key `LIBLI_IMAGE_TAG`; `vol_path()`'s `libli_` prefix stays valid because `name: libli` is untouched. Tasks 3 and 4 read `LIBLI_IMAGE_TAG`.

- [ ] **Step 1: Write the failing guards**

Create `tests/test_backup_wiring.py`:

```python
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
import shutil
import subprocess
from pathlib import Path

import pytest

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
```

- [ ] **Step 2: Run the guards to verify they fail**

```bash
uv run pytest tests/test_backup_wiring.py -v
```

Expected: all four FAIL — `deploy.yml no longer publishes an image`, `deploy.sh no longer logs in to ghcr.io`, `--build` still present, `build: .` still present.

- [ ] **Step 3: Add the publish job to `deploy.yml`**

Insert this job **before** the existing `deploy:` job, and make `deploy` depend on it. Replace the `jobs:` block's opening so it reads:

```yaml
jobs:
  # Builds on the runner, not on the school box. That is the point: it removes
  # the image build -- the RAM spike that makes 4 GB a real floor -- from every
  # box at once, and it is what lets a restore start the exact version a dump
  # came from rather than rebuilding it.
  #
  # In this workflow rather than a separate one: two workflows on the same
  # trigger would race, and the deploy must be strictly downstream of the push.
  publish:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/master'
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      # Two tags, both pushed every time. :master is the floating canary tag
      # libli.pl follows; :sha-<short> is immutable and is what a manifest
      # records -- a floating tag cannot pin a restore to a version.
      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ghcr.io/krzyssikora/libli:master
            ghcr.io/krzyssikora/libli:sha-${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy:
    needs: publish
    runs-on: ubuntu-latest
```

Leave the rest of the `deploy` job exactly as it is.

Note: the tag uses the **full** `github.sha`, and `deploy.sh` computes `sha-$(git rev-parse HEAD)` to match. Do not use `--short` in either place, or they will disagree.

- [ ] **Step 4: Switch the compose file to an image**

In `docker-compose.prod.yml`, in the `app` service, replace:

```yaml
    build: .
```

with:

```yaml
    # Pulled, never built here. A build on a school box is the RAM spike that
    # makes 4 GB a real floor, and a restore must be able to start the exact
    # version a dump came from -- which needs a pullable immutable tag, not a
    # source tree. deploy.sh writes LIBLI_IMAGE_TAG from the checkout it just
    # reset, so the running image always matches the checked-out commit and
    # docs/deployment.md §8's `git reset --hard` rollback keeps its meaning.
    # Bare `:?` for the same reason as POSTGRES_PASSWORD below.
    image: ghcr.io/krzyssikora/libli:${LIBLI_IMAGE_TAG:?}
```

- [ ] **Step 5: Update `deploy.sh`**

Replace the `==> rebuilding and recreating the stack` block with:

```bash
echo "==> pinning the image tag to this checkout"
# Written INTO .env.production, not exported: backup.sh reads it hours later
# under cron with env_value, the encrypted env in each artifact must carry the
# tag matching its manifest, and compose guards the key with `:?` so any `up`
# outside this script -- the runbook's §3 first boot, restore.sh, a manual
# `up -d` -- would abort without a persisted value.
image_tag="sha-$(git rev-parse HEAD)"
if grep -q '^LIBLI_IMAGE_TAG=' .env.production; then
  sed -i "s|^LIBLI_IMAGE_TAG=.*|LIBLI_IMAGE_TAG=${image_tag}|" .env.production
else
  printf 'LIBLI_IMAGE_TAG=%s\n' "$image_tag" >> .env.production
fi

echo "==> logging in to ghcr.io"
# The package is private: it contains the application source of a private repo.
# An unauthenticated pull fails with an opaque `denied`.
env_value LIBLI_GHCR_TOKEN | docker login ghcr.io -u krzyssikora --password-stdin

echo "==> pulling and recreating the stack"
compose pull
compose up -d --wait
```

Also add the shared lock as the first thing after `cd "$APP_DIR"`:

```bash
# Shared with backup.sh and restore.sh. A merge landing mid-dump would recreate
# the app container, restart postgres' dependents and prune images underneath it.
# deploy.sh WAITS rather than skipping: a silently dropped deploy would report
# green in Actions having done nothing.
exec 9>/var/lock/libli-deploy.lock
flock 9
```

- [ ] **Step 6: Add the two new env keys**

Append to `.env.production.example`:

```bash

# --- image ---
# Written by deploy.sh from the checked-out commit; set it by hand only on a
# first boot or a restore, to the sha-<full-sha> tag you intend to run.
LIBLI_IMAGE_TAG=
# A fine-grained GitHub PAT with read:packages. The GHCR package is private
# because the image contains this repo's source. ⚠️ PATs expire -- that is a
# dated, silent, fleet-wide failure, so put the expiry in the same calendar as
# the restore rehearsal.
LIBLI_GHCR_TOKEN=
```

- [ ] **Step 7: Update the runbook's three `--build` sites and the rollback bullet**

In `docs/deployment.md`:

- §1, after the Docker install block, add:

```bash
docker login ghcr.io -u krzyssikora    # paste a read:packages PAT
```

- §3, replace `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build` with `... up -d` and add a sentence above it: "Set `LIBLI_IMAGE_TAG` to the `sha-<full-sha>` tag you intend to run before this; every later deploy writes it for you."
- §8's rollback block, replace `up -d --build --wait` with `up -d --wait` and add: "`git reset --hard <sha>` still does what it always did — `deploy.sh` derives `LIBLI_IMAGE_TAG` from the checkout, so moving the checkout moves the image."
- *Known constraints*, replace the "**No rollback.**" bullet with:

```markdown
- **Rollback is one pull.** `git reset --hard <last-good-sha>` then `bash deploy.sh`: the
  tag follows the checkout, so the previous image is pulled rather than rebuilt. What this
  cannot undo is an **already-applied migration** — the schema stays ahead of the code, and
  that case needs a restore from `docs/backup-and-restore.md`, not a rollback.
```

- [ ] **Step 8: Update the existing deploy guard**

In `tests/test_deploy_wiring.py`, in `test_deploy_script_waits_for_health`, replace the `--build` assertion (line 174) and its docstring's mutant line:

```python
    assert "--wait" in match.group(0), match.group(0)
    # `--build` was removed when the box switched to pulling a published image;
    # tests/test_backup_wiring.py::test_no_build_survives_anywhere pins that.
    assert "compose pull" in text, text
```

- [ ] **Step 9: Run both guard files**

```bash
uv run pytest tests/test_backup_wiring.py tests/test_deploy_wiring.py -v
```

Expected: PASS. Grep the summary for `passed` and confirm `failed` is absent.

- [ ] **Step 10: Falsify one guard**

By hand, put `--build` back on the `compose up` line in `deploy.sh`. Run `uv run pytest tests/test_backup_wiring.py::test_no_build_survives_anywhere -v` — expected **FAIL**. Remove it by hand and re-run to confirm PASS.

- [ ] **Step 11: Commit**

```bash
git add .github/workflows/deploy.yml docker-compose.prod.yml deploy.sh .env.production.example docs/deployment.md tests/test_deploy_wiring.py tests/test_backup_wiring.py
git commit -m "feat(deploy): publish the image to GHCR and pull it on the box

Nothing in the repo built or pushed an image; deploy.sh built on the
serving host. A restore must be able to start the exact version a dump
came from, which needs a pullable immutable tag rather than a source
tree -- so this moves out of B2 and into the backup work.

The tag follows the checkout, so §8's git-reset rollback keeps its
meaning instead of silently becoming a no-op.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Aopus3KuLErHrHWKWeiKe"
```

---

### Task 3: `backup.sh`

The nightly job. Fourteen ordered steps, several of whose orderings are load-bearing and pinned by guards.

**Files:**
- Create: `backup.sh`
- Modify: `tests/test_backup_wiring.py` (guards 1-5, 7, 9, 16)
- Modify: `docs/deployment.md` §7 (the cron entry)

**Interfaces:**
- Consumes: `list_referenced_files` (Task 1); `LIBLI_IMAGE_TAG` (Task 2).
- Produces: the artifact layout under `schools/<slug>/` that Task 4 reads; the constants `RETAIN_DAILY_DAYS`, `RETAIN_MONTHLY_MONTHS`, `MIRROR_PRUNE_DAYS` that Task 5's privacy guard reads.

- [ ] **Step 1: Write the failing guards**

Append to `tests/test_backup_wiring.py`:

```python
def _volumes_declared_in_compose():
    """The names under the top-level `volumes:` key of the compose file.

    Derived, never restated: a volume added to compose must fail the
    classification guard below until someone decides what happens to it.
    """
    lines = COMPOSE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "volumes:")
    names = []
    for ln in lines[start + 1 :]:
        if ln and not ln[0].isspace():
            break
        match = re.match(r"^\s{2}(\w+):\s*$", ln)
        if match:
            names.append(match.group(1))
    return set(names)


def _volume_class():
    """The VOLUME_CLASS array in backup.sh, as {name: class}."""
    text = BACKUP_SH.read_text(encoding="utf-8")
    block = re.search(r"^VOLUME_CLASS=\((.*?)^\)", text, re.MULTILINE | re.DOTALL)
    assert block, "backup.sh no longer declares VOLUME_CLASS"
    return dict(re.findall(r'"(\w+)=([\w-]+)"', block.group(1)))


def test_every_compose_volume_is_classified():
    """Mutant: add a volume to docker-compose.prod.yml -> RED until classified.

    Teaches the detector rather than trimming a baseline: the expected set comes
    from the compose file itself.
    """
    classified = _volume_class()
    assert _volumes_declared_in_compose() == set(classified)
    allowed = {"dumped", "mirror-plain", "mirror-encrypted", "archive-encrypted", "excluded"}
    assert set(classified.values()) <= allowed, classified


def test_every_classification_carries_a_reason():
    """A class with no reason is a decision nobody recorded.

    Mutant: delete a `# <name>:` comment line above VOLUME_CLASS.
    """
    text = BACKUP_SH.read_text(encoding="utf-8")
    for name in _volume_class():
        assert re.search(rf"^# {name}:", text, re.MULTILINE), f"no reason for {name}"


def _line_index(path, pattern):
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        if re.search(pattern, ln):
            return i
    raise AssertionError(f"{path.name} has no line matching {pattern!r}")


def test_dump_precedes_the_media_mirror():
    """Dump at T0, media at T1: a file created in between is a harmless orphan.
    Reversed, a file created in between lands in the DUMP with no bytes in the
    mirror -- a row pointing at nothing, which is a broken restore.

    Mutant: swap the two steps.
    """
    assert _line_index(BACKUP_SH, r"pg_dump") < _line_index(BACKUP_SH, r"rsync.*media")


def test_refs_is_written_before_either_mirror_step():
    """refs/ must describe the database the DUMP captured. Written at the end it
    would be read AFTER the screenshot erasure and could agree with a mirror the
    same run just erased from, while the dump still referenced the file.

    Mutant: move list_referenced_files to the end of the script.
    """
    refs = _line_index(BACKUP_SH, r"list_referenced_files")
    assert _line_index(BACKUP_SH, r"pg_dump") < refs
    assert refs < _line_index(BACKUP_SH, r"rsync.*media")
    assert refs < _line_index(BACKUP_SH, r"xargs rm")


def test_the_erasure_keep_set_includes_refs():
    """Keeping only the live tree reopens the intra-run race: a screenshot whose
    row is deleted after the dump was spooled would be erased from the mirror and
    omitted from a live-DB reading of refs, so CONFIRM would see no discrepancy
    while the dump still pointed at it.

    Mutant: drop refs from the union.
    """
    text = BACKUP_SH.read_text(encoding="utf-8")
    assert re.search(r"keep_set.*refs|refs.*keep_set", text), text


def test_no_delete_anywhere_in_backup():
    """media/ keeps deleted files on purpose; screenshots/ erases by an explicit
    rm of a computed list. `--delete` against a staging dir holding only tonight's
    new files would delete the ENTIRE screenshot history every night --
    `--ignore-existing` suppresses re-transfer and exempts nothing from deletion.

    Mutant: add `--delete` to either rsync.
    """
    assert "--delete" not in BACKUP_SH.read_text(encoding="utf-8")


def test_the_dump_is_verified_before_upload():
    """A truncated -Fc archive fails to list. Without this the truncation is
    found at restore time.

    Mutant: remove the pg_restore --list line.
    """
    dump = _line_index(BACKUP_SH, r"pg_dump")
    verify = _line_index(BACKUP_SH, r"pg_restore --list")
    upload = _line_index(BACKUP_SH, r"age -r")
    assert dump < verify < upload


def test_all_three_scripts_fail_on_the_first_error_and_in_a_pipe():
    """pipefail is load-bearing: without it a pg_dump that dies part-way while
    age exits 0 yields a short, well-formed, encrypted file and a GREEN heartbeat.

    Mutant: drop `pipefail` from any of the three.
    """
    for path in (DEPLOY_SH, BACKUP_SH, RESTORE_SH):
        body = [
            ln
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
        assert body[0].startswith("#!"), path.name
        assert body[1] == "set -euo pipefail", f"{path.name}: {body[1]!r}"


def test_all_three_scripts_share_one_lock_path():
    """Otherwise the risk table claims a mitigation that does not exist.

    Mutant: give backup.sh its own lock file.
    """
    paths = set()
    for path in (DEPLOY_SH, BACKUP_SH, RESTORE_SH):
        found = re.findall(r"/var/lock/\S+\.lock", path.read_text(encoding="utf-8"))
        assert found, f"{path.name} takes no lock"
        paths |= set(found)
    assert len(paths) == 1, paths


def test_compose_still_declares_the_project_name_vol_path_depends_on():
    """vol_path() resolves `libli_<volume>`; that prefix is Docker's
    <project>_<volume> convention and comes from `name: libli`.

    Mutant: rename or delete the project name.
    """
    assert re.search(r"^name: libli$", COMPOSE.read_text(encoding="utf-8"), re.MULTILINE)


def test_the_runbook_cron_line_matches_the_script_path():
    """Mutant: move backup.sh without updating §7."""
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert "/opt/libli/backup.sh" in runbook, "the runbook does not schedule backup.sh"
    assert "15 2 * * *" in runbook, "the cron slot collides with purge_notifications"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.parametrize("script", ["deploy.sh", "backup.sh", "restore.sh"])
def test_scripts_parse(script):
    """Mutant: drop a closing brace from any helper."""
    result = subprocess.run(  # noqa: S603 -- fixed argv, repo-relative path
        [shutil.which("bash"), "-n", str(ROOT / script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run the guards to verify they fail**

```bash
uv run pytest tests/test_backup_wiring.py -v
```

Expected: the new tests FAIL (no `backup.sh`, no `restore.sh`). The Task 2 tests still pass.

- [ ] **Step 3: Write `backup.sh`**

Create `backup.sh` at the repo root:

```bash
#!/usr/bin/env bash
set -euo pipefail
# libli nightly backup.
#
# STRAIGHT-LINE ON PURPOSE. Several guards in tests/test_backup_wiring.py are
# source-order assertions (the dump must precede the media mirror; refs must
# precede both mirrors). Refactoring these steps into functions would break them
# or, worse, pass them for the wrong reason. Keep the ordered steps inline.
#
# `set -euo pipefail` above is the first executable line and pipefail is
# load-bearing: without it a pg_dump that dies part-way while age exits 0
# produces a short, well-formed, encrypted file, a written manifest and a GREEN
# heartbeat -- the exact failure the verification exists to catch.

APP_DIR=/opt/libli
cd "$APP_DIR"

# Published in docs/public/privacy.md AND privacy.pl.md; a guard ties them to
# these three numbers. Changing one without the notices fails the suite.
# 30 days is a DETECTION window (a school holiday is two weeks); 12 months is the
# academic year; ~13 months total is the RODO ceiling and bounds a pupil's
# erasure tail. Storage cost plays no part -- the dump is small because media is
# not in Postgres.
RETAIN_DAILY_DAYS=30
RETAIN_MONTHLY_MONTHS=12
MIRROR_PRUNE_DAYS=90

# Shared with deploy.sh and restore.sh. backup.sh SKIPS when the lock is held:
# tonight's backup is the cheapest of the three to lose, and the heartbeat's
# absence alerts if it keeps happening.
LOCK_FILE=/var/lock/libli-deploy.lock

# Every volume in docker-compose.prod.yml must appear below with a reason, or
# test_every_compose_volume_is_classified goes red. Derived from the compose
# file, never hand-maintained beside it.
#
# pgdata: captured by pg_dump, never mirrored -- a filesystem copy of a running
#   postgres data directory is not a consistent backup.
# media: the whole of MEDIA_ROOT; plain mirror, pruned at MIRROR_PRUNE_DAYS.
# support_screenshots: personal data; encrypted per-file mirror, erased on deletion.
# caddy_data: ACME account key + issued certificate private keys; encrypted
#   tarball. Kept to spare Let's Encrypt rate-limit budget on repeated restores.
# caddy_config: NOT BACKED UP -- autosaved by Caddy, regenerated from the
#   mounted Caddyfile on first boot.
# transfer_staging: NOT BACKED UP -- in-flight uploads only, swept at 6h.
# upload_tmp: NOT BACKED UP -- transient Django upload spill.
VOLUME_CLASS=(
  "pgdata=dumped"
  "media=mirror-plain"
  "support_screenshots=mirror-encrypted"
  "caddy_data=archive-encrypted"
  "caddy_config=excluded"
  "transfer_staging=excluded"
  "upload_tmp=excluded"
)

compose() {
  docker compose -f docker-compose.prod.yml --env-file .env.production "$@"
}

# `sed -n s///p` rather than grep so a missing key yields an empty string instead
# of exit 1, which under `set -e` would abort over a value only used for
# verification. Same helper shape as deploy.sh.
env_value() {
  sed -n "s/^$1=//p" .env.production | head -1
}

# media, support_screenshots and caddy_data are NAMED DOCKER VOLUMES, not bind
# mounts -- there is no /opt/libli/media on the host, so a bare `rsync media/`
# cannot work. The libli_ prefix is Docker's <project>_<volume> convention and
# comes from `name: libli` at the top of the compose file, which a guard pins.
vol_path() {
  docker volume inspect --format '{{.Mountpoint}}' "libli_$1"
}

# rsync exits 24 ("some files vanished before they could be transferred")
# routinely on a live media tree. Under `set -e` that would abort before the
# heartbeat and alert on a backup that is fine -- and repeated false alerts are
# how a real one gets ignored.
rsync_ok() {
  local code=0
  rsync "$@" || code=$?
  [ "$code" -eq 0 ] || [ "$code" -eq 24 ]
}

require_env() {
  local value
  value="$(env_value "$1")"
  if [ -z "$value" ]; then
    echo "!! $1 is unset in .env.production; refusing to back up nowhere" >&2
    exit 1
  fi
  printf '%s' "$value"
}

# --- 1. lock -------------------------------------------------------------
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "==> a deploy or restore holds the lock; skipping tonight"
  exit 0
fi

SLUG="$(require_env LIBLI_SCHOOL_SLUG)"
RECIPIENT="$(require_env LIBLI_BACKUP_AGE_RECIPIENT)"
SSH_HOST="$(require_env LIBLI_BACKUP_SSH_HOST)"
SSH_USER="$(require_env LIBLI_BACKUP_SSH_USER)"
SSH_KEY="$(require_env LIBLI_BACKUP_SSH_KEY_PATH)"
HEARTBEAT="$(require_env LIBLI_BACKUP_HEARTBEAT_URL)"

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new"
REMOTE="$SSH_USER@$SSH_HOST"
BASE="schools/$SLUG"
TS="$(date -u +%Y-%m-%dT%H%M%S)"

remote() { ssh $SSH_OPTS "$REMOTE" "$@"; }

STAGING="$(mktemp -d)"
DUMP_TMP="$(mktemp)"
trap 'rm -rf "$STAGING" "$DUMP_TMP"' EXIT

remote "mkdir -p $BASE/{db,env,caddy,refs,manifest,media,screenshots}"

# --- 2. never overwrite an existing timestamp ----------------------------
if remote "test -e $BASE/db/$TS.dump.age"; then
  echo "!! $BASE/db/$TS.dump.age already exists; refusing to overwrite" >&2
  exit 1
fi

# --- 3. informational counts --------------------------------------------
# row_counts is INFORMATIONAL: it is read before the dump, so rows arrive in
# between and a pass/fail gate would go red on healthy backups. The migration
# set does NOT drift in seconds (the lock excludes a concurrent deploy), so it
# IS an exact gate, used by restore.sh.
PGUSER_VALUE="$(env_value POSTGRES_USER)"
PGDB_VALUE="$(env_value POSTGRES_DB)"
ROW_COUNTS="$(compose exec -T db psql -U "$PGUSER_VALUE" -d "$PGDB_VALUE" -At -F, -c "
  SELECT relname, n_live_tup FROM pg_stat_user_tables
  WHERE relname NOT IN ('auth_group','auth_permission','django_migrations','django_site')
  ORDER BY relname;")"
MIGRATIONS="$(compose exec -T db psql -U "$PGUSER_VALUE" -d "$PGDB_VALUE" -At -F. -c "
  SELECT app, name FROM django_migrations ORDER BY app, name;")"

# --- 4. dump -------------------------------------------------------------
# A compose exec, not a host command: there is no postgres client on the host.
# -T is load-bearing twice -- cron has no TTY, and a pty would corrupt the
# binary -Fc stream.
PGPASSWORD_VALUE="$(env_value POSTGRES_PASSWORD)"
compose exec -T -e PGPASSWORD="$PGPASSWORD_VALUE" db \
  pg_dump -U "$PGUSER_VALUE" -Fc "$PGDB_VALUE" > "$DUMP_TMP"

# --- 5. refs, IMMEDIATELY ------------------------------------------------
# Must describe the database the DUMP captured. Written at the end of the run it
# would be read AFTER the screenshot erasure below and could agree with a mirror
# that same run just erased from, while the dump still referenced the file.
# `exec`, not `run --rm`: the app container IS up during a backup.
compose exec -T app /app/.venv/bin/python manage.py list_referenced_files > "$STAGING/refs.txt"
scp $SSH_OPTS "$STAGING/refs.txt" "$REMOTE:$BASE/refs/$TS.txt"

# --- 6. truncation detector ---------------------------------------------
# A truncated -Fc archive fails to list. Cheap, and it is why row_counts does
# not have to carry that weight.
pg_restore_list() { compose exec -T db pg_restore --list; }
pg_restore_list < "$DUMP_TMP" > /dev/null

# --- 7. upload the dump --------------------------------------------------
# Public-key mode: this box holds only the recipient, so it writes a backup it
# cannot read. A stolen box yields no pupil data and no DJANGO_SECRET_KEY.
age -r "$RECIPIENT" -o "$STAGING/db.age" "$DUMP_TMP"
scp $SSH_OPTS "$STAGING/db.age" "$REMOTE:$BASE/db/$TS.dump.age"
rm -f "$DUMP_TMP"

# --- 8. upload the env ---------------------------------------------------
# The artifact's third component. Two secrets live in the DATABASE (SocialApp
# and WebhookEndpoint), three live only here -- a restore needs both halves.
age -r "$RECIPIENT" -o "$STAGING/env.age" .env.production
scp $SSH_OPTS "$STAGING/env.age" "$REMOTE:$BASE/env/$TS.env.age"

# --- 9. mirror media (NO --delete) ---------------------------------------
# Append-only so a hard-deleted element's file survives its row: element
# deletion in libli has no orphan table and no audit trail. Path-faithful,
# because MediaAsset filenames are not content-addressed and a rename breaks
# every FileField in the database.
MEDIA_DIR="$(vol_path media)"
rsync_ok -a -e "ssh $SSH_OPTS" "$MEDIA_DIR/" "$REMOTE:$BASE/media/"

# --- 10. screenshots: upload E\R, then erase R\(E u refs) ----------------
# UPLOAD AND ERASURE ARE TWO OPERATIONS. `rsync --delete` from a staging dir
# holding only tonight's new files would delete the ENTIRE screenshot history
# every night: --delete removes destination files absent from the SOURCE list,
# and --ignore-existing only suppresses re-transfer -- it exempts nothing from
# deletion.
SHOTS_DIR="$(vol_path support_screenshots)"
remote "cd $BASE/screenshots && find . -type f -name '*.age' | sed 's|^\./||'" \
  | sort > "$STAGING/remote.txt"
(cd "$SHOTS_DIR" && find . -type f | sed 's|^\./||') | sed 's|$|.age|' \
  | sort > "$STAGING/expected.txt"

# Upload set: expected minus remote. Names are immutable
# (screenshots/<YYYY>/<MM>/<uuid4>.<ext>), so a name already on the remote never
# needs re-encrypting.
mkdir -p "$STAGING/shots"
comm -23 "$STAGING/expected.txt" "$STAGING/remote.txt" | while read -r name; do
  src="$SHOTS_DIR/${name%.age}"
  [ -f "$src" ] || continue
  mkdir -p "$STAGING/shots/$(dirname "$name")"
  age -r "$RECIPIENT" -o "$STAGING/shots/$name" "$src"
done
rsync_ok -a -e "ssh $SSH_OPTS" "$STAGING/shots/" "$REMOTE:$BASE/screenshots/"

# Erase set: remote minus (expected union tonight's refs). The refs union closes
# an intra-run race -- a screenshot whose row was deleted after the dump was
# spooled is still referenced BY that dump, so erasing it here would let CONFIRM
# see no discrepancy while the restore would fail after WIPE.
awk -F'\t' '$1 == "support_screenshots" { print $2 ".age" }' "$STAGING/refs.txt" \
  | sort > "$STAGING/refs_shots.txt"
sort -u "$STAGING/expected.txt" "$STAGING/refs_shots.txt" > "$STAGING/keep_set.txt"
comm -23 "$STAGING/remote.txt" "$STAGING/keep_set.txt" > "$STAGING/erase.txt"
if [ -s "$STAGING/erase.txt" ]; then
  sed "s|^|$BASE/screenshots/|" "$STAGING/erase.txt" \
    | remote "xargs -r rm -f"
fi

# --- 11. caddy_data ------------------------------------------------------
# ACME account key and every certificate's private key -- encrypted for the same
# "every secret" reason as the dump. Kilobytes; kept to spare Let's Encrypt
# rate-limit budget on repeated restores.
tar -C "$(vol_path caddy_data)" -cf - . | age -r "$RECIPIENT" -o "$STAGING/caddy.age"
scp $SSH_OPTS "$STAGING/caddy.age" "$REMOTE:$BASE/caddy/$TS.tar.age"

# --- 12. media-missing.tsv and the manifest ------------------------------
# The prune CANNOT key on a file's own mtime: rsync preserves the SOURCE mtime
# and never touches it again once the source is gone, so a file uploaded two
# years ago and deleted today is already "older than 90 days" and would be
# pruned on the NEXT run. Track time since FIRST OBSERVED MISSING instead.
remote "cd $BASE/media && find . -type f | sed 's|^\./||'" | sort > "$STAGING/remote_media.txt"
(cd "$MEDIA_DIR" && find . -type f | sed 's|^\./||') | sort > "$STAGING/live_media.txt"
scp $SSH_OPTS "$REMOTE:$BASE/media-missing.tsv" "$STAGING/missing.tsv" 2>/dev/null \
  || : > "$STAGING/missing.tsv"
TODAY="$(date -u +%Y-%m-%d)"
comm -23 "$STAGING/remote_media.txt" "$STAGING/live_media.txt" > "$STAGING/gone.txt"
awk -F'\t' -v today="$TODAY" '
  NR == FNR { seen[$1] = $2; next }
  { print $1 "\t" (($1 in seen) ? seen[$1] : today) }
' "$STAGING/missing.tsv" "$STAGING/gone.txt" > "$STAGING/missing.new"
scp $SSH_OPTS "$STAGING/missing.new" "$REMOTE:$BASE/media-missing.tsv"

MEDIA_FILES="$(wc -l < "$STAGING/live_media.txt")"
MEDIA_BYTES="$(du -sb "$MEDIA_DIR" | cut -f1)"
SHOT_FILES="$(wc -l < "$STAGING/expected.txt")"
SHOT_BYTES="$(du -sb "$SHOTS_DIR" | cut -f1)"
{
  printf '{\n'
  printf '  "schema": 1,\n'
  printf '  "school": "%s",\n' "$SLUG"
  printf '  "taken_at": "%sZ",\n' "$(date -u +%Y-%m-%dT%H:%M:%S)"
  printf '  "image": "ghcr.io/krzyssikora/libli:%s",\n' "$(env_value LIBLI_IMAGE_TAG)"
  printf '  "git_sha": "%s",\n' "$(git rev-parse HEAD)"
  printf '  "postgres_major": %s,\n' "$(compose exec -T db psql -U "$PGUSER_VALUE" -At -c 'SHOW server_version' | cut -d. -f1)"
  printf '  "migrations": ["%s"],\n' "$(echo "$MIGRATIONS" | paste -sd'","' -)"
  printf '  "row_counts": {%s},\n' "$(echo "$ROW_COUNTS" | awk -F, '{printf "%s\"%s\":%s", (NR>1?",":""), $1, $2}')"
  printf '  "media": {"files": %s, "bytes": %s},\n' "$MEDIA_FILES" "$MEDIA_BYTES"
  printf '  "screenshots": {"files": %s, "bytes": %s}\n' "$SHOT_FILES" "$SHOT_BYTES"
  printf '}\n'
} > "$STAGING/manifest.json"
scp $SSH_OPTS "$STAGING/manifest.json" "$REMOTE:$BASE/manifest/$TS.json"

# --- 13. prune -----------------------------------------------------------
# Keep every artifact within RETAIN_DAILY_DAYS; older than that keep the
# EARLIEST of each calendar month for RETAIN_MONTHLY_MONTHS. Earliest, not
# latest: once a month's survivor is chosen it never changes, whereas "latest"
# would re-designate a different keeper every night while the month runs.
# manifest/ is NEVER pruned -- it is a few hundred bytes and the annual school
# statement wants the media.bytes series over years.
remote "
  set -eu
  cd $BASE
  cutoff=\$(date -u -d '$RETAIN_DAILY_DAYS days ago' +%Y-%m-%d)
  monthly_cutoff=\$(date -u -d '$RETAIN_MONTHLY_MONTHS months ago' +%Y-%m)
  for dir in db env caddy refs; do
    keep=\$(mktemp)
    ls \$dir | sed 's/[.].*//' | sort > \$keep.all
    awk -v c=\"\$cutoff\" 'substr(\$0,1,10) >= c' \$keep.all > \$keep
    awk -v c=\"\$cutoff\" 'substr(\$0,1,10) < c' \$keep.all \
      | awk -v m=\"\$monthly_cutoff\" 'substr(\$0,1,7) >= m' \
      | awk '!seen[substr(\$0,1,7)]++' >> \$keep
    sort -u \$keep -o \$keep
    ls \$dir | while read -r f; do
      grep -qx \"\${f%%.*}\" \$keep || rm -f \$dir/\$f
    done
    rm -f \$keep \$keep.all
  done
  prune_before=\$(date -u -d '$MIRROR_PRUNE_DAYS days ago' +%Y-%m-%d)
  awk -F'\t' -v c=\"\$prune_before\" '\$2 < c { print \$1 }' media-missing.tsv \
    | while read -r p; do rm -f \"media/\$p\"; done
  awk -F'\t' -v c=\"\$prune_before\" '\$2 >= c' media-missing.tsv > media-missing.new \
    && mv media-missing.new media-missing.tsv
"

# --- 14. heartbeat, on success only --------------------------------------
# Alerts on ABSENCE, which is the only thing that detects a backup that stopped
# running. cron's MAILTO is unavailable: there is no MTA and Hetzner blocks
# outbound 25 by default.
curl -fsS -m 15 "$HEARTBEAT" > /dev/null
echo "==> backup complete: $BASE @ $TS"
```

- [ ] **Step 4: Add the six new env keys**

Append to `.env.production.example`:

```bash

# --- backup ---
# Identifies this school on the Storage Box: schools/<slug>/...
LIBLI_SCHOOL_SLUG=
# The age PUBLIC key. This box writes backups it cannot read; the private half
# lives in the password manager and NEVER on any server.
LIBLI_BACKUP_AGE_RECIPIENT=
LIBLI_BACKUP_SSH_HOST=
LIBLI_BACKUP_SSH_USER=
# ⚠️ A PATH, not the key. env_value reads ONE line, so a multi-line PEM here
# would be silently truncated to its -----BEGIN header: a config that parses,
# looks right, and cannot authenticate. Provisioning places the file, mode 0600.
LIBLI_BACKUP_SSH_KEY_PATH=/root/.ssh/libli_backup
# healthchecks.io ping URL. Period 24h, grace 6h.
LIBLI_BACKUP_HEARTBEAT_URL=
```

- [ ] **Step 5: Add the cron entry to the runbook**

In `docs/deployment.md` §7, after the `purge_notifications` entry, add:

````markdown
And the nightly backup — **one physical line**, same as above:

```cron
15 2 * * * bash /opt/libli/backup.sh >> /var/log/libli-backup.log 2>&1
```

`15 2`, deliberately not `30 3`: a dump competing with the retention purge for the
same container and disk is avoidable. The host clock is UTC, so this, the artifact
timestamps and `taken_at` are all the same clock.
````

- [ ] **Step 6: Run the guards**

```bash
uv run pytest tests/test_backup_wiring.py -v
```

Expected: everything except the `restore.sh` tests passes. The three `restore.sh`-dependent tests (`test_all_three_scripts_fail_on_the_first_error_and_in_a_pipe`, `test_all_three_scripts_share_one_lock_path`, `test_scripts_parse[restore.sh]`) still FAIL — that is correct; Task 4 closes them.

- [ ] **Step 7: Falsify two guards**

By hand, one at a time, reverting each by hand before the next:

1. Add `--delete` to the media rsync line → `test_no_delete_anywhere_in_backup` must FAIL.
2. Move the `list_referenced_files` line below the media rsync → `test_refs_is_written_before_either_mirror_step` must FAIL.

Read `git diff` after reverting to confirm the file is byte-identical to before.

- [ ] **Step 8: Commit**

```bash
git add backup.sh .env.production.example docs/deployment.md tests/test_backup_wiring.py
git commit -m "feat(ops): nightly encrypted backup to a Hetzner Storage Box

Straight-line by design: several guards are source-order assertions.
The two orderings that matter are the dump preceding the media mirror
(so a file created in between is a harmless orphan rather than a row
pointing at nothing) and refs preceding both mirrors (so the erasure
cannot remove what the dump still references).

No --delete anywhere: against a staging dir of only tonight's new
files it would delete the entire screenshot history every night.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Aopus3KuLErHrHWKWeiKe"
```

---

### Task 4: `restore.sh`

One script, four uses: restore, resize, provider-move, handover.

**Files:**
- Create: `restore.sh`
- Modify: `tests/test_backup_wiring.py` (guards 6, 11-15, 17)

**Interfaces:**
- Consumes: the artifact layout (Task 3); `list_referenced_files` (Task 1); `LIBLI_IMAGE_TAG` (Task 2).
- Produces: a restored box. Nothing later depends on it.

- [ ] **Step 1: Write the failing guards**

Append to `tests/test_backup_wiring.py`:

```python
def test_restore_loads_the_database_before_the_app_starts():
    """The entrypoint runs `migrate` on every boot, so bringing the full stack up
    against an empty database creates the schema and the dump then collides.

    Mutant: replace `up -d db` with `up -d`.
    """
    text = RESTORE_SH.read_text(encoding="utf-8")
    db_up = _line_index(RESTORE_SH, r"compose up -d db\b")
    load = _line_index(RESTORE_SH, r"pg_restore")
    assert db_up < load
    head = text.splitlines()[:load]
    assert not [ln for ln in head if re.search(r"compose up -d\s*$", ln)], head


def test_volumes_are_materialised_before_paths_are_resolved():
    """`up -d db` creates only pgdata; media, support_screenshots and caddy_data
    belong to app and caddy, which do not start until later -- so vol_path would
    fail on volumes that do not exist. `compose create` makes them WITH compose's
    labels; `docker volume create` would make unlabelled ones compose then
    refuses to adopt.

    Mutant: delete the compose create line.
    """
    # Anchored on the first CALL, not the definition: vol_path() is defined up
    # with the other helpers in the ENV section, which is before compose create.
    assert _line_index(RESTORE_SH, r"compose create") < _line_index(
        RESTORE_SH, r"vol_path caddy_data"
    )


def test_rotate_secrets_writes_before_it_wipes():
    """POSTGRES_PASSWORD is read by postgres ONLY while it initialises an empty
    data directory. Rotated after the wipe, the database keeps the old password
    while the app uses the new one.

    Mutant: move the generation below `compose down`.
    """
    gen = _line_index(RESTORE_SH, r"rotate_secrets|openssl rand")
    assert gen < _line_index(RESTORE_SH, r"compose down --volumes")


def test_confirm_proves_the_artifacts_exist_before_it_prompts():
    """Otherwise a never-pruned manifest/ lets an operator pick a <ts> whose
    artifacts are gone; it passes every early check and fails at ENV, after the
    confirmation has already been typed.

    Mutant: move the existence check below the read.
    """
    assert _line_index(RESTORE_SH, r"db/\$TS\.dump\.age") < _line_index(RESTORE_SH, r"^\s*read ")


def test_completeness_is_checked_before_the_wipe():
    """Mutant: move the refs diff after `compose down`."""
    assert _line_index(RESTORE_SH, r"refs/\$TS\.txt") < _line_index(
        RESTORE_SH, r"compose down --volumes"
    )


def test_a_missing_artifact_exits_but_a_refs_gap_does_not():
    """The asymmetry is the point. A refs gap is often LEGITIMATE -- media is
    pruned at 90 days and screenshots are erased on deletion, while dumps are
    kept 13 months -- so refusing on one would make every old-enough <ts>
    unrestorable. The typed slug IS the knowing acceptance.

    Mutant: make a refs gap exit non-zero.
    """
    text = RESTORE_SH.read_text(encoding="utf-8")
    missing_block = re.search(r"missing artefact.*?\n(.*?)\nfi", text, re.DOTALL)
    assert missing_block and "exit 1" in missing_block.group(1), text
    gap_block = re.search(r"refs gap.*?\n(.*?)\nfi", text, re.DOTALL)
    assert gap_block and "exit" not in gap_block.group(1), text


def test_the_checkout_must_match_the_image():
    """The compose file governs the postgres major, the volume names and the
    healthcheck, so a checkout newer than the image can disagree with it.

    Mutant: delete the comparison.
    """
    assert re.search(r"git rev-parse HEAD", RESTORE_SH.read_text(encoding="utf-8"))


def test_image_tag_is_format_checked():
    """"Never floating master" in a runbook is an instruction to a human. The
    checkout-sha comparison needs a sha to compare.

    Mutant: accept any string.
    """
    assert "^sha-[0-9a-f]" in RESTORE_SH.read_text(encoding="utf-8")


def test_pre_cutover_disables_acme_by_the_scheme():
    """The Caddyfile has NO tls directive -- automatic HTTPS is driven entirely
    by whether {$SITE_ADDRESS} parses as a domain. The http:// scheme plus
    DJANGO_SECURE_SSL_REDIRECT=false is the pair the runbook already documents
    for local smoke runs.

    Mutant: drop the scheme rewrite -> the restore attempts ACME against DNS
    still pointing at the old box, burning the failed-validation budget.
    """
    text = RESTORE_SH.read_text(encoding="utf-8")
    assert "SITE_ADDRESS=http://" in text, text
    assert "DJANGO_SECURE_SSL_REDIRECT=false" in text, text
    assert not re.search(r"^\s*tls\b", CADDYFILE.read_text(encoding="utf-8"), re.MULTILINE)
```

- [ ] **Step 2: Run the guards to verify they fail**

```bash
uv run pytest tests/test_backup_wiring.py -v
```

Expected: the nine new tests FAIL (no `restore.sh`).

- [ ] **Step 3: Write `restore.sh`**

Create `restore.sh` at the repo root:

```bash
#!/usr/bin/env bash
set -euo pipefail
# libli restore. The same script serves four paths: restore, resize,
# provider-move and handover.
#
# STRAIGHT-LINE ON PURPOSE, like backup.sh -- several guards are source-order
# assertions. Steps are named rather than numbered because renumbering rots
# every cross-reference in the spec and the runbook.
#
# STEP 0 IS NOT IN THIS FILE. The runbook's git clone is §3, so on a box that
# has had only §1-2 this script is not present. docs/backup-and-restore.md
# carries the pre-flight: §1-2, choose <ts> from your own machine, clone PINNED
# to the commit matching the target image tag, deliver credentials to tmpfs,
# then invoke this.

APP_DIR=/opt/libli
cd "$APP_DIR"

LOCK_FILE=/var/lock/libli-deploy.lock
AGE_KEY=/dev/shm/libli-restore.key
SSH_KEY=/dev/shm/libli-restore-ssh.key

MODE=live
ROTATE=0
SLUG=""
TS=""
IMAGE_TAG=""
GHCR_TOKEN=""
SSH_HOST=""
SSH_USER=""

while [ $# -gt 0 ]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2 ;;
    --ts) TS="$2"; shift 2 ;;
    --image-tag) IMAGE_TAG="$2"; shift 2 ;;
    --ssh-host) SSH_HOST="$2"; shift 2 ;;
    --ssh-user) SSH_USER="$2"; shift 2 ;;
    --ghcr-token) GHCR_TOKEN="$2"; shift 2 ;;
    --pre-cutover) MODE=pre-cutover; shift ;;
    --live) MODE=live; shift ;;
    --rotate-secrets) ROTATE=1; shift ;;
    *) echo "!! unknown argument: $1" >&2; exit 2 ;;
  esac
done

for required in SLUG TS SSH_HOST SSH_USER; do
  if [ -z "${!required}" ]; then
    echo "!! --${required,,} is required" >&2
    exit 2
  fi
done

# --- LOCK ----------------------------------------------------------------
# Fails LOUDLY rather than skipping. A silently skipped restore is the worst
# outcome in the set: the operator believes the site is being recovered while
# nothing is happening.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "!! a deploy or backup holds $LOCK_FILE; refusing to restore" >&2
  exit 1
fi

# --- CREDENTIALS ---------------------------------------------------------
# tmpfs, never disk, removed on every exit path including failure. The invariant
# is "never AT REST on a server" -- a restore necessarily decrypts here.
trap 'shred -u "$AGE_KEY" "$SSH_KEY" 2>/dev/null || rm -f "$AGE_KEY" "$SSH_KEY"' EXIT
for key in "$AGE_KEY" "$SSH_KEY"; do
  if [ ! -s "$key" ]; then
    echo "!! $key is absent. Deliver it out of band before running this:" >&2
    echo "   ssh <box> 'cat > $key' < <your local copy>" >&2
    exit 1
  fi
done

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new"
REMOTE="$SSH_USER@$SSH_HOST"
BASE="schools/$SLUG"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"; shred -u "$AGE_KEY" "$SSH_KEY" 2>/dev/null || rm -f "$AGE_KEY" "$SSH_KEY"' EXIT

remote() { ssh $SSH_OPTS "$REMOTE" "$@"; }

# --- CONFIRM -------------------------------------------------------------
scp $SSH_OPTS "$REMOTE:$BASE/manifest/$TS.json" "$WORK/manifest.json"
echo "=== manifest $TS ==="
cat "$WORK/manifest.json"

# Hard refuse: without the dump or the env there is nothing to restore and there
# is no degraded mode. manifest/ is never pruned, so it lists timestamps whose
# artefacts are gone -- without this the failure lands after the confirmation.
missing=""
for object in "db/$TS.dump.age" "env/$TS.env.age" "caddy/$TS.tar.age"; do
  remote "test -e $BASE/$object" || missing="$missing $object"
done
if [ -n "$missing" ]; then
  # missing artefact
  echo "!! pruned, not restorable:$missing" >&2
  echo "   choose a <ts> within the 30-day window, or a monthly survivor." >&2
  exit 1
fi

# Informational: a refs gap is often legitimate (media prunes at 90 days,
# screenshots erase on deletion, dumps live 13 months), so refusing here would
# make every old-enough <ts> unrestorable. The typed slug below IS the
# acceptance, and FILES honours it.
scp $SSH_OPTS "$REMOTE:$BASE/refs/$TS.txt" "$WORK/refs.txt"
remote "cd $BASE/media && find . -type f | sed 's|^\./||'" | sort > "$WORK/have_media.txt"
remote "cd $BASE/screenshots && find . -type f -name '*.age' | sed 's|^\./||;s|\.age$||'" \
  | sort > "$WORK/have_shots.txt"
awk -F'\t' '$1 == "media" { print $2 }' "$WORK/refs.txt" | sort > "$WORK/want_media.txt"
awk -F'\t' '$1 == "support_screenshots" { print $2 }' "$WORK/refs.txt" | sort > "$WORK/want_shots.txt"
comm -23 "$WORK/want_media.txt" "$WORK/have_media.txt" > "$WORK/gap_media.txt"
comm -23 "$WORK/want_shots.txt" "$WORK/have_shots.txt" > "$WORK/gap_shots.txt"
if [ -s "$WORK/gap_media.txt" ] || [ -s "$WORK/gap_shots.txt" ]; then
  # refs gap
  echo "=== files this dump references that the mirror no longer holds ==="
  grep -c 'derivatives/' "$WORK/gap_media.txt" | xargs printf '  %s derivative(s) -- harmless, backfill_media_derivatives regenerates them\n'
  wc -l < "$WORK/gap_shots.txt" | xargs printf '  %s screenshot(s) -- expected on an old <ts>; erased by design\n'
  grep -vc 'derivatives/' "$WORK/gap_media.txt" | xargs printf '  %s ORIGINAL(s) -- unrepairable content loss\n'
  echo "Typing the slug below accepts this gap."
fi

echo
echo "About to DESTROY every volume on this box and restore $SLUG @ $TS."
printf 'Type the school slug to continue: '
read -r typed
[ "$typed" = "$SLUG" ] || { echo "!! not confirmed" >&2; exit 1; }

# --- IDENTITY ------------------------------------------------------------
schema="$(sed -n 's/.*"schema": *\([0-9]*\).*/\1/p' "$WORK/manifest.json")"
[ "$schema" = "1" ] || { echo "!! unknown manifest schema $schema" >&2; exit 1; }
school="$(sed -n 's/.*"school": *"\([^"]*\)".*/\1/p' "$WORK/manifest.json")"
[ "$school" = "$SLUG" ] || { echo "!! manifest is school '$school', not '$SLUG'" >&2; exit 1; }

# --- VERSION -------------------------------------------------------------
manifest_image="$(sed -n 's/.*"image": *"\([^"]*\)".*/\1/p' "$WORK/manifest.json")"
if [ -z "$IMAGE_TAG" ]; then
  TARGET="$manifest_image"
  echo "==> target is the manifest's own image; the containment check is a tautology and is skipped"
else
  case "$IMAGE_TAG" in
    sha-*) ;;
    *) echo "!! --image-tag must match ^sha-[0-9a-f]{7,40}$; a floating tag names different code on different days and cannot pin a restore" >&2; exit 1 ;;
  esac
  echo "$IMAGE_TAG" | grep -Eq '^sha-[0-9a-f]{7,40}$' \
    || { echo "!! --image-tag must match ^sha-[0-9a-f]{7,40}$" >&2; exit 1; }
  TARGET="ghcr.io/krzyssikora/libli:$IMAGE_TAG"
fi

if [ -n "$GHCR_TOKEN" ]; then
  printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u krzyssikora --password-stdin
fi
docker pull "$TARGET" \
  || { echo "!! cannot pull $TARGET. Pass --ghcr-token if this box has no valid login." >&2; exit 1; }

# The compose file governs the postgres major, the volume names and the
# healthcheck, so a checkout that disagrees with the image can contradict it.
checkout_tag="sha-$(git rev-parse HEAD)"
target_tag="${TARGET##*:}"
if [ "$checkout_tag" != "$target_tag" ]; then
  echo "!! this checkout is $checkout_tag but the target image is $target_tag." >&2
  echo "   git checkout the matching commit (pre-flight step 3) and re-run." >&2
  exit 1
fi

# Django has one migration leaf PER APP, so a single "head" cannot detect an
# image behind on a courses migration. Set containment, read from the image's
# migration FILES -- which needs no database.
docker run --rm --entrypoint sh "$TARGET" -c 'ls /app/*/migrations/[0-9]*.py' \
  | sed 's|.*/\([^/]*\)/migrations/\([^.]*\)\.py|\1.\2|' | sort > "$WORK/image_migrations.txt"
sed -n 's/.*"migrations": \[\(.*\)\].*/\1/p' "$WORK/manifest.json" \
  | tr ',' '\n' | tr -d '" ' | sort > "$WORK/dump_migrations.txt"
if ! comm -23 "$WORK/dump_migrations.txt" "$WORK/image_migrations.txt" | grep -q .; then
  :
else
  echo "!! the target image is BEHIND the dump; restoring forward is safe, backward is not:" >&2
  comm -23 "$WORK/dump_migrations.txt" "$WORK/image_migrations.txt" >&2
  exit 1
fi

manifest_pg="$(sed -n 's/.*"postgres_major": *\([0-9]*\).*/\1/p' "$WORK/manifest.json")"
compose_pg="$(sed -n 's|.*image: postgres:\([0-9]*\).*|\1|p' docker-compose.prod.yml | head -1)"
[ "$compose_pg" -ge "$manifest_pg" ] \
  || { echo "!! compose runs postgres:$compose_pg, the dump is from $manifest_pg" >&2; exit 1; }

# --- ENV -----------------------------------------------------------------
scp $SSH_OPTS "$REMOTE:$BASE/env/$TS.env.age" "$WORK/env.age"
age -d -i "$AGE_KEY" -o .env.production "$WORK/env.age"
chmod 600 .env.production

# Left in place the entrypoint's init_platform would mint an admin account on a
# production restore.
sed -i '/^INIT_ADMIN_/d' .env.production
sed -i "s|^LIBLI_IMAGE_TAG=.*|LIBLI_IMAGE_TAG=$target_tag|" .env.production

if [ "$MODE" = "pre-cutover" ]; then
  # DNS still points at the OLD box, so ACME would fail validation repeatedly and
  # eat Let's Encrypt's failed-validation budget -- possibly blocking issuance at
  # the cutover. The Caddyfile has no tls directive; the http:// scheme is what
  # makes Caddy skip ACME, exactly as the runbook's local-smoke section documents.
  host="$(sed -n 's/^DJANGO_SITE_DOMAIN=//p' .env.production | head -1)"
  sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=http://$host|" .env.production
  if grep -q '^DJANGO_SECURE_SSL_REDIRECT=' .env.production; then
    sed -i 's|^DJANGO_SECURE_SSL_REDIRECT=.*|DJANGO_SECURE_SSL_REDIRECT=false|' .env.production
  else
    echo 'DJANGO_SECURE_SSL_REDIRECT=false' >> .env.production
  fi
fi

if [ "$ROTATE" = "1" ]; then
  # rotate_secrets: MUST happen here, before the wipe. Postgres accepts a new
  # password only while initialising an empty data directory.
  new_pg="$(openssl rand -base64 36 | tr -d '/+=' | head -c 32)"
  new_secret="$(openssl rand -base64 64 | tr -d '\n')"
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$new_pg|" .env.production
  sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$new_secret|" .env.production
  echo "=== SAVE THESE TO THE PASSWORD MANAGER NOW -- they exist nowhere else ==="
  echo "POSTGRES_PASSWORD=$new_pg"
  echo "DJANGO_SECRET_KEY=$new_secret"
fi

compose() {
  docker compose -f docker-compose.prod.yml --env-file .env.production "$@"
}
vol_path() { docker volume inspect --format '{{.Mountpoint}}' "libli_$1"; }
rsync_ok() {
  local code=0
  rsync "$@" || code=$?
  [ "$code" -eq 0 ] || [ "$code" -eq 24 ]
}

# --- WIPE ----------------------------------------------------------------
# Destroys ALL seven volumes, not just pgdata, and that is intended: it is what
# makes the media volume contain EXACTLY the referenced set. A surgical
# `docker volume rm libli_pgdata` would preserve the old media tree, and FILES
# only ADDS referenced files -- so any file the old tree held that the restored
# database does not reference would survive, unreferenced and still reachable at
# its URL through Caddy.
compose down --volumes

# --- MATERIALISE ---------------------------------------------------------
# `up -d db` creates only pgdata. compose create makes every volume WITH
# compose's labels and starts nothing; `docker volume create` would make
# unlabelled ones that compose then refuses to adopt.
compose create

# --- DB UP ---------------------------------------------------------------
# db ALONE. The entrypoint runs `migrate` on every boot, so a full `up` would
# create the schema and the dump would then collide with it.
compose up -d db
until compose exec -T db pg_isready -U "$(sed -n 's/^POSTGRES_USER=//p' .env.production | head -1)"; do
  sleep 2
done

# --- LOAD ----------------------------------------------------------------
scp $SSH_OPTS "$REMOTE:$BASE/db/$TS.dump.age" "$WORK/db.age"
age -d -i "$AGE_KEY" -o "$WORK/db.dump" "$WORK/db.age"
PGUSER_VALUE="$(sed -n 's/^POSTGRES_USER=//p' .env.production | head -1)"
PGDB_VALUE="$(sed -n 's/^POSTGRES_DB=//p' .env.production | head -1)"
PGPASSWORD_VALUE="$(sed -n 's/^POSTGRES_PASSWORD=//p' .env.production | head -1)"
compose exec -T -e PGPASSWORD="$PGPASSWORD_VALUE" db \
  pg_restore -U "$PGUSER_VALUE" -d "$PGDB_VALUE" --clean --if-exists < "$WORK/db.dump"

# --- FILES ---------------------------------------------------------------
# Three sets, three mechanisms. Only the files the RESTORED database references
# are fetched: copying the whole mirror back would resurrect every file deleted
# in the last 90 days, and Caddy serves media/ directly, so a resurrected file is
# reachable at its URL with no row pointing at it.
scp $SSH_OPTS "$REMOTE:$BASE/caddy/$TS.tar.age" "$WORK/caddy.age"
age -d -i "$AGE_KEY" "$WORK/caddy.age" | tar -C "$(vol_path caddy_data)" -xf -

compose run --rm --no-deps app /app/.venv/bin/python manage.py list_referenced_files \
  > "$WORK/restored_refs.txt"
awk -F'\t' '$1 == "media" { print $2 }' "$WORK/restored_refs.txt" | sort > "$WORK/need_media.txt"
awk -F'\t' '$1 == "support_screenshots" { print $2 }' "$WORK/restored_refs.txt" | sort > "$WORK/need_shots.txt"

rsync_ok -a --files-from="$WORK/need_media.txt" -e "ssh $SSH_OPTS" \
  "$REMOTE:$BASE/media/" "$(vol_path media)/"

SHOTS_DIR="$(vol_path support_screenshots)"
while read -r name; do
  remote "test -e $BASE/screenshots/$name.age" || continue
  mkdir -p "$SHOTS_DIR/$(dirname "$name")"
  scp $SSH_OPTS "$REMOTE:$BASE/screenshots/$name.age" "$WORK/shot.age"
  age -d -i "$AGE_KEY" -o "$SHOTS_DIR/$name" "$WORK/shot.age"
done < "$WORK/need_shots.txt"

# --- APP UP --------------------------------------------------------------
compose up -d --wait

# --- VERIFY --------------------------------------------------------------
# Exact, minus the gap CONFIRM declared and the operator accepted. Anything
# missing BEYOND that accepted set means the mirror lost a file between the check
# and the fetch -- a genuine fault rather than a known consequence.
(cd "$(vol_path media)" && find . -type f | sed 's|^\./||') | sort > "$WORK/got_media.txt"
comm -23 "$WORK/need_media.txt" "$WORK/got_media.txt" | sort > "$WORK/unfetched.txt"
comm -23 "$WORK/unfetched.txt" "$WORK/gap_media.txt" > "$WORK/unexpected.txt"
if [ -s "$WORK/unexpected.txt" ]; then
  echo "!! files missing that CONFIRM did not declare:" >&2
  cat "$WORK/unexpected.txt" >&2
  exit 1
fi

if [ "$MODE" = "pre-cutover" ]; then
  curl -fsS -H "Host: $(sed -n 's/^DJANGO_SITE_DOMAIN=//p' .env.production | head -1)" \
    http://127.0.0.1/healthz/ | grep -q '"status": *"ok"'
  echo "==> pre-cutover restore verified. Repoint DNS, then re-run with --live."
else
  site="$(sed -n 's/^DJANGO_SITE_DOMAIN=//p' .env.production | head -1)"
  curl -fsS --retry 5 --retry-delay 3 --retry-connrefused \
    "https://$site/healthz/" | grep -q '"status": *"ok"'
  echo "==> restore complete and verified over TLS."
fi

# --- HANDOFF -------------------------------------------------------------
if [ "$ROTATE" = "1" ]; then
  echo
  echo "=== NOT DONE. These cannot be rotated from this box: ==="
  echo "  - the Storage Box sub-account and key (revoke the old at Hetzner)"
  echo "  - LIBLI_GHCR_TOKEN (revoke the old PAT at GitHub)"
  echo "  - DJANGO_EMAIL_HOST_PASSWORD (reissued by the mail provider)"
  echo "  - SocialApp.secret and WebhookEndpoint.secret -- these live in the"
  echo "    DATABASE, survived the restore intact, and are rotated in the admin UI"
  echo "See docs/backup-and-restore.md. Exiting non-zero until these are done."
  exit 1
fi
```

- [ ] **Step 4: Run the guards**

```bash
uv run pytest tests/test_backup_wiring.py -v
```

Expected: all PASS, including the three `restore.sh` tests Task 3 left red.

- [ ] **Step 5: Falsify two guards**

By hand, reverting each before the next:

1. Change `compose up -d db` to `compose up -d` → `test_restore_loads_the_database_before_the_app_starts` must FAIL.
2. Move the two `openssl rand` lines below `compose down --volumes` → `test_rotate_secrets_writes_before_it_wipes` must FAIL.

Read `git diff` after each revert.

- [ ] **Step 6: Commit**

```bash
git add restore.sh tests/test_backup_wiring.py
git commit -m "feat(ops): one restore script for restore, resize, move and handover

The orderings that matter: the database is loaded before the app ever
starts (the entrypoint migrates on boot, so a full `up` would create the
schema the dump then collides with); volumes are materialised with
compose's own labels before any mountpoint is resolved; secrets are
rotated before the wipe, because postgres reads POSTGRES_PASSWORD only
while initialising an empty data directory.

Only files the restored database references are fetched -- Caddy serves
media/ directly, so restoring the whole mirror would make every
recently-deleted file reachable at its URL again.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Aopus3KuLErHrHWKWeiKe"
```

---

### Task 5: State the retention in both privacy notices, and guard it

`docs/public/privacy.md` already promises "the server and its backups" are kept safe — a live public claim about something that has not existed. This task makes it true and falsifiable.

**Files:**
- Modify: `docs/public/privacy.md` (*How long we keep it*)
- Modify: `docs/public/privacy.pl.md` (the same section)
- Modify: `tests/test_public_pages_guards.py`

**Interfaces:**
- Consumes: `RETAIN_DAILY_DAYS`, `RETAIN_MONTHLY_MONTHS`, `MIRROR_PRUNE_DAYS` from `backup.sh` (Task 3).
- Produces: nothing later depends on it.

- [ ] **Step 1: Write the failing guard**

Append to `tests/test_public_pages_guards.py`:

```python
BACKUP_SH = (DOCS_ROOT.parent / "backup.sh").read_text(encoding="utf-8")


def _backup_constant(name):
    match = re.search(rf"^{name}=(\d+)$", BACKUP_SH, re.MULTILINE)
    assert match, f"backup.sh no longer defines {name}"
    return int(match.group(1))


def test_backup_retention_matches_the_stated_periods():
    """Publishing a retention claim whose real value lives in a shell script is
    exactly the drift this file exists to prevent -- and this one is a legal
    statement in two languages, not a UI string.

    Mutant: change RETAIN_DAILY_DAYS in backup.sh without the notices.
    """
    assert _backup_constant("RETAIN_DAILY_DAYS") == 30
    assert _backup_constant("RETAIN_MONTHLY_MONTHS") == 12
    assert _backup_constant("MIRROR_PRUNE_DAYS") == 90
    for notice in (PRIVACY, PRIVACY_PL):
        assert "30" in notice and "12" in notice and "90" in notice, notice[:200]
    assert "13 months" in PRIVACY
    assert "13 miesięcy" in PRIVACY_PL
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_public_pages_guards.py::test_backup_retention_matches_the_stated_periods -v
```

Expected: FAIL — the notices say nothing about backups.

- [ ] **Step 3: Add the English wording**

In `docs/public/privacy.md`, at the end of *How long we keep it*:

```markdown
**Backups.** The server is backed up every night to encrypted storage in the European Union.
A nightly copy is kept for **30 days**, and one copy per month for a further **12 months** —
so no backup is older than about **13 months**, after which it is deleted permanently. Files
removed from a course stay in the backup for **90 days** so that an accidental deletion can
be undone, and are then deleted too. A screenshot you attached to a problem report is removed
from the backup on the same night it is deleted from the site, not after a delay.

Backups are encrypted with a key that is not held on the server, so someone who obtained the
server could not read them.
```

- [ ] **Step 4: Add the Polish wording**

In `docs/public/privacy.pl.md`, at the end of *Jak długo przechowujemy dane*:

```markdown
**Kopie zapasowe.** Serwer jest co noc kopiowany na zaszyfrowany nośnik w Unii Europejskiej.
Kopię nocną przechowujemy **30 dni**, a jedną kopię miesięczną przez kolejne **12 miesięcy** —
żadna kopia nie jest więc starsza niż około **13 miesięcy**, po czym zostaje trwale usunięta.
Pliki usunięte z kursu pozostają w kopii **90 dni**, aby można było cofnąć przypadkowe
usunięcie, i następnie również są usuwane. Zrzut ekranu dołączony do zgłoszenia problemu
znika z kopii tej samej nocy, w której usuniemy go z serwisu — bez opóźnienia.

Kopie są szyfrowane kluczem, którego nie ma na serwerze, więc osoba, która przejęłaby serwer,
nie mogłaby ich odczytać.
```

⚠️ Do **not** run `makemessages` for this — these are markdown documents, not msgids.

- [ ] **Step 5: Run the guard**

```bash
uv run pytest tests/test_public_pages_guards.py -v
```

Expected: PASS.

- [ ] **Step 6: Falsify it**

By hand, change `RETAIN_DAILY_DAYS=30` to `RETAIN_DAILY_DAYS=45` in `backup.sh`. Re-run — expected **FAIL**. Change it back by hand.

- [ ] **Step 7: Commit**

```bash
git add docs/public/privacy.md docs/public/privacy.pl.md tests/test_public_pages_guards.py
git commit -m "docs(privacy): state the backup retention in both notices

The notice already promised that 'the server and its backups' are kept
safe -- a live public claim about something that did not exist. The
guard ties the stated periods to backup.sh's constants so the claim
cannot quietly become a lie, in either language.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Aopus3KuLErHrHWKWeiKe"
```

---

### Task 6: `docs/backup-and-restore.md` and the runbook's remaining edits

**Files:**
- Create: `docs/backup-and-restore.md`
- Modify: `docs/deployment.md` (§1 `age` + UTC + key file, §8 cross-link, *Known constraints* "No backups" bullet)

**Interfaces:**
- Consumes: everything above.
- Produces: the operator-facing document. Nothing depends on it in code.

- [ ] **Step 1: Write `docs/backup-and-restore.md`**

Create it with these sections, in this order. Write real prose in each — this is the document someone reads at 2am:

1. **What is backed up, and what is not** — the artifact tree, and the seven-volume classification table with its reasons.
2. **The pre-flight checklist** — the five out-of-band inputs, then the ordered step 0: runbook §1-2 → choose `<ts>` from your own machine → `git clone` **pinned** to the commit matching the target image tag → deliver the age identity and SSH key to `/dev/shm` → invoke.
3. **Restoring** — the invocation, the four paths (restore / resize / provider-move / handover) and which flags each uses.
4. **Recovering a single file** — the everyday use of the append-only mirror, and what justifies it: `rsync` one path out of `media/` into `$(docker volume inspect --format '{{.Mountpoint}}' libli_media)`. It does not involve `restore.sh`.
5. **Rotation after a compromise** — the three timing groups (at ENV by the script; after the restore by a human in the admin UI; out of band at Hetzner and GitHub), stating that `POSTGRES_PASSWORD` must be set *before* the wipe.
6. **Handover** — key **rotation**, never disclosure: the school generates its own keypair, you re-encrypt only that school's current artifact under it, older history stays under the shared key and is deleted on the agreed schedule. Plus the `.env.production` values that change.
7. **Rehearsal log** — a table with columns `date | <ts> restored | box | outcome | surprises`, seeded with the nine-item pass checklist from the spec above it.

- [ ] **Step 2: Update the runbook's remaining sites**

In `docs/deployment.md`:

- §1, in the package install line, add `age` alongside `ca-certificates curl git`.
- §1, after the Docker install, add: `timedatectl set-timezone UTC` with the note that cron, the artifact timestamps and `taken_at` must be one clock.
- §1, add the Storage Box key placement: `install -m 600 /dev/null /root/.ssh/libli_backup` then paste the key.
- §8, add a cross-link line: `Backups and restores are in [docs/backup-and-restore.md](backup-and-restore.md).`
- *Known constraints*, **delete** the `- **No backups.** No pg_dump cron, no snapshot policy.` bullet.

- [ ] **Step 3: Verify no guard broke**

```bash
uv run pytest tests/test_backup_wiring.py tests/test_deploy_wiring.py tests/test_public_pages_guards.py -v
```

Expected: PASS. `test_no_build_survives_anywhere` reads the runbook, so a stray `--build` reintroduced by editing would surface here.

- [ ] **Step 4: Commit**

```bash
git add docs/backup-and-restore.md docs/deployment.md
git commit -m "docs(ops): the backup and restore runbook

Separate from deployment.md, which is already long. Carries the
pre-flight the runbook cannot: the git clone is deployment.md §3, so on
a box that has had only §1-2 restore.sh is not yet present.

Removes the 'No backups' known constraint.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Aopus3KuLErHrHWKWeiKe"
```

---

## Before the PR

- [ ] **Full unit sweep** (a branch gate, not a task step):

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest -m "not e2e"
```

Grep the summary for `passed` and confirm `failed` is absent — a pytest exit code of 0 can coexist with `1 failed`.

- [ ] **Both ruff gates:**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
```

- [ ] **The rehearsal.** ⚠️ **This work is not complete when the scripts exist.** It is complete when a backup taken by `backup.sh` has been restored by `restore.sh` onto a *fresh* box and the nine-item checklist in the spec passes. Textual guards prove the wiring has not drifted; only the rehearsal proves it works. Record it in the rehearsal log and set the quarterly calendar entry.

- [ ] **Calendar items that are not code:** order the Storage Box; create the healthchecks.io check (period 24h, grace 6h); note the GHCR PAT's expiry date beside the rehearsal reminder; and if any school wants mail from its own domain, file the Hetzner port-25 unblock request — it needs roughly a month's lead time.
