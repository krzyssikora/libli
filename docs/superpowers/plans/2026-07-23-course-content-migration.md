# Course Content Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A management command that moves a course's content between two databases via the transfer engine's archive format — export each top-level part to a bundle, then graft the bundle into an existing target course.

**Architecture:** One command, three actions. `export` runs against the source database and writes one archive per part plus a media side table; `import` runs against the target database and grafts each archive as a subtree; `verify` reconciles tallies afterwards. A bundle directory on disk is the handoff, because a Django process binds one database.

**Tech Stack:** Django management command, the existing `courses/transfer/` engine, pytest.

**Spec:** `docs/superpowers/specs/2026-07-23-course-content-migration-design.md` — read it first. It went through 8 review rounds and six of its corrections were factual errors about the transfer engine's API; the signatures below are the verified ones.

## Global Constraints

- **This delivers a tested tool. No task may write to the real `libli` or to `libli_mat`.** The cutover is a separate, user-gated act.
- **Tests:** `uv run pytest <paths> -vv`. `ruff` / `pytest` / `python` are **not on PATH** — always `uv run`.
- **Never** set `DJANGO_SETTINGS_MODULE` on a pytest invocation. **Never add `-q`** (`addopts` already has it; one `-v` only cancels it back to default, so use `-vv`). Never pipe pytest through `tail`/`head`. Never run a bare `-m e2e` sweep.
- **Lint:** `uv run ruff check .` and `uv run ruff format --check .` must both be clean.
- **The code blocks below are NOT ruff-formatted.** They are written for readability — grouped
  arguments, compact `call_command(...)` calls — and ruff's magic-trailing-comma rule will reflow
  most of them onto one argument per line. This is expected and is not a defect to puzzle over.
  **Run `uv run ruff format .` after pasting and before every commit**, then `ruff format --check`
  to confirm. Do not hand-reflow the snippets to guess ruff's output.
- **Import each name in the task that first uses it, not earlier.** `ruff`'s `F401` fails the commit
  gate on an unused import, so hoisting `MediaAsset` into Task 1 to "avoid a later NameError" breaks
  Tasks 1 and 2 instead. Task 3 adds it when `verify` needs it.
- **Stage explicitly by path.** Never `git add -A` / `git add .`.
- No model changes, no migration. If one seems needed, stop and surface it.
- **Every task is TDD:** write the failing test, verify it fails *for the stated reason*, implement, verify green.

## Verified API facts (do not re-derive; these were wrong in six earlier drafts)

```python
build_export(course, node=None, source_host="", *, drop_missing_media=True)
    -> (manifest, document, media_assets, problems)   # FOUR values
    # media_assets is a list of (mid, asset, is_placeholder) triples

write_archive_from(manifest, document, media_assets, fileobj)   # writes the zip

@contextmanager
open_archive(fileobj, *, expected_kind)      # MUST be used in a `with` block
    -> yields (zf, manifest, document, media_entries)

validate_archive_document(zf, manifest, document, media_entries, *, kind, target_course=None)
    # `kind` and `target_course` are KEYWORD-ONLY

import_subtree(zf, manifest, document, media_entries, target_course, insertion_node, user)
    # ALL positional. insertion_node=None means top level.

from courses.transfer.schema import KIND_SUBTREE   # == "subtree"
from courses.transfer.schema import TransferError
```

`ContentNode.order` is **0-based** (`OrderField.pre_save` sets the first sibling to `0`). Every index in this plan — archive filenames, `--start-at`, side-table part indices — is that same `order`.

`_run_import` wraps **each** `import_subtree` call in its own `transaction.atomic()`, so N grafts are N independent transactions.

## File Structure

**Created:**
- `courses/management/commands/migrate_course_content.py` — the command: arg parsing/scoping plus the three actions.
- `tests/test_migrate_course_content.py` — all tests. Single test database; a synthetic source course and a synthetic target course.

**Not modified:** the transfer engine, its views, and every other file.

---

### Task 1: Command skeleton, argument scoping, and the `export` action

**Files:**
- Create: `courses/management/commands/migrate_course_content.py`
- Create: `tests/test_migrate_course_content.py`

**Interfaces:**
- Consumes: `build_export`, `write_archive_from` from `courses.transfer.export`.
- Produces: `migrate_course_content export --source-slug S --bundle-dir D [--allow-problems]`, writing `{order:02d}-{slug}.zip` per top-level part plus `media-parts.json` (the side table). Later tasks consume that bundle layout.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_migrate_course_content.py`:

```python
"""The migrate_course_content command: export a course's top-level parts to a
bundle, graft the bundle into an existing target course, verify the result."""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError
from django.core.management import call_command

from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import TextElement

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    # The import path writes real files through default_storage. Without this
    # redirect, tests pollute the repo's media/ dir -- the same guard
    # tests/test_transfer_subtree.py uses.
    settings.MEDIA_ROOT = tmp_path / "media"


def _mk_source(slug="src", parts=("P0", "P1")):
    """A parts->chapter->unit course with one text + one image per unit.

    Titles are deliberately plain except where a test overrides them; one part
    carries a __PLACEHOLDER-style chapter to pin verbatim title carry-over.
    """
    course = Course.objects.create(
        title="Source", slug=slug, uses_parts=True, uses_chapters=True
    )
    for i, title in enumerate(parts):
        part = ContentNode.objects.create(course=course, kind="part", title=title)
        chapter = ContentNode.objects.create(
            course=course, kind="chapter", title=f"__PLACEHOLDER chapter {i}__",
            parent=part,
        )
        unit = ContentNode.objects.create(
            course=course, kind="unit", title=f"U{i}", parent=chapter,
            unit_type="lesson",
        )
        asset = MediaAsset.objects.create(
            course=course, kind="image",
            file=SimpleUploadedFile(f"p{i}.png", b"\x89PNG fake"),
            original_filename=f"p{i}.png", name=f"Pic {i}",
        )
        Element.objects.create(
            unit=unit, title="T",
            content_object=TextElement.objects.create(body="<p>hi</p>"),
        )
        Element.objects.create(
            unit=unit, title="",
            content_object=ImageElement.objects.create(media=asset, alt="a"),
        )
    return course


def _mk_target(slug="dst"):
    """An EMPTY target that allows parts at top level, mirroring mat-pp."""
    return Course.objects.create(
        title="Target", slug=slug, uses_parts=True, uses_chapters=True
    )


def test_export_writes_one_archive_per_part_named_by_zero_based_order(tmp_path):
    _mk_source(parts=("Alpha", "Beta", "Gamma"))
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content", "export",
        "--source-slug", "src", "--bundle-dir", str(bundle),
    )
    names = sorted(p.name for p in bundle.glob("*.zip"))
    assert len(names) == 3
    # 0-based order, zero-padded, matching ContentNode.order.
    assert names[0].startswith("00-")
    assert names[1].startswith("01-")
    assert names[2].startswith("02-")


def test_export_writes_the_media_side_table_keyed_by_source_pk(tmp_path):
    course = _mk_source(parts=("Alpha", "Beta"))
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content", "export",
        "--source-slug", "src", "--bundle-dir", str(bundle),
    )
    table = json.loads((bundle / "media-parts.json").read_text(encoding="utf-8"))
    pks = {a.pk for a in MediaAsset.objects.filter(course=course)}
    # Every source asset appears, keyed by its own pk, mapped to part orders.
    assert {int(k) for k in table} == pks
    for parts in table.values():
        assert parts and all(isinstance(i, int) for i in parts)


def test_export_rejects_an_unknown_source_slug(tmp_path):
    with pytest.raises(CommandError, match="no course with slug"):
        call_command(
            "migrate_course_content", "export",
            "--source-slug", "nope", "--bundle-dir", str(tmp_path / "b"),
        )


def test_export_aborts_on_problems_and_allow_problems_overrides(tmp_path, monkeypatch):
    """The spec's central content-loss guard: build_export's 4th return value.

    Exporting 21 parts while silently accepting placeholdered media is the
    precise failure this whole effort exists to avoid, so the abort is default
    and the override must be explicit. build_export is monkeypatched because
    provoking a real `problems` entry depends on filesystem state; what is
    under test is the command's reaction, not the engine's detection.
    """
    from courses.management.commands import migrate_course_content as mod

    _mk_source(parts=("Only",))
    real = mod.build_export

    def fake(course, node=None, **kw):
        manifest, document, media_assets, _problems = real(course, node=node, **kw)
        return manifest, document, media_assets, ["missing media: x.png"]

    monkeypatch.setattr(mod, "build_export", fake)

    bundle = tmp_path / "bundle"
    with pytest.raises(CommandError, match="problem"):
        call_command(
            "migrate_course_content", "export",
            "--source-slug", "src", "--bundle-dir", str(bundle),
        )
    assert not list(bundle.glob("*.zip")) if bundle.exists() else True

    # The override lets the same export through.
    call_command(
        "migrate_course_content", "export",
        "--source-slug", "src", "--bundle-dir", str(bundle),
        "--allow-problems",
    )
    assert len(list(bundle.glob("*.zip"))) == 1


def test_export_rerun_overwrites_rather_than_duplicating(tmp_path):
    _mk_source(parts=("Alpha", "Beta"))
    bundle = tmp_path / "bundle"
    for _ in range(2):
        call_command(
            "migrate_course_content", "export",
            "--source-slug", "src", "--bundle-dir", str(bundle),
        )
    # Deterministic names mean the second run replaces the first's archives.
    assert len(list(bundle.glob("*.zip"))) == 2


def test_export_refuses_import_only_flags(tmp_path):
    _mk_source()
    with pytest.raises(CommandError, match="not valid for"):
        call_command(
            "migrate_course_content", "export",
            "--source-slug", "src", "--bundle-dir", str(tmp_path / "b"),
            "--force",
        )
```

- [ ] **Step 2: Run them and confirm they fail for the right reason**

```
uv run pytest tests/test_migrate_course_content.py -vv
```

Expected: all FAIL with `CommandError: Unknown command: 'migrate_course_content'` (Django raises this for a missing command). A failure with a different message means the command file was created early — remove it and re-run before implementing.

- [ ] **Step 3: Write the command with the `export` action**

Create `courses/management/commands/migrate_course_content.py`:

```python
"""Move a course's content between databases via the transfer engine.

Two phases with a bundle directory between them, because a Django process
binds one database: `export` runs against the source, `import` against the
target, and `verify` reconciles afterwards.

Content moves ONE TOP-LEVEL PART AT A TIME. That is not incidental --
import_course() would create a second course beside the prepared target, and
validate_document() caps each archive at TRANSFER_MAX_ELEMENTS/MEDIA_ENTRIES,
which a whole-course archive of a large course would breach outright.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from courses.models import ContentNode
from courses.models import Course
from courses.transfer.export import build_export
from courses.transfer.export import write_archive_from

SIDE_TABLE = "media-parts.json"

# Flags that belong to exactly one action. Anything used outside its action is
# rejected rather than silently ignored -- --allow-problems is a content-loss
# decision about EXPORT and must never double as an import override.
_ACTION_FLAGS = {
    "export": {"allow_problems"},
    "import": {"as_user", "dry_run", "force", "start_at"},
    "verify": set(),
}

# The "not supplied" value per flag, compared with `is` rather than `==`.
# `--start-at 0` is a LEGAL resume index, and `0 == False` in Python, so an
# equality check against a (None, False) tuple would silently let it through.
_FLAG_UNSET = {
    "allow_problems": False,
    "dry_run": False,
    "force": False,
    "as_user": None,
    "start_at": None,
}


class Command(BaseCommand):
    help = "Move course content between databases via the transfer engine."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("export", "import", "verify"))
        parser.add_argument("--source-slug")
        parser.add_argument("--target-slug")
        parser.add_argument("--bundle-dir", required=True)
        parser.add_argument("--allow-problems", action="store_true")
        parser.add_argument("--as-user")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--start-at", type=int)

    def handle(self, *args, **o):
        action = o["action"]
        self._reject_foreign_flags(action, o)
        if action == "export":
            self._export(o)
        else:  # pragma: no cover - later tasks
            raise CommandError(f"action not implemented yet: {action}")

    def _reject_foreign_flags(self, action, o):
        mine = _ACTION_FLAGS[action]
        for other, flags in _ACTION_FLAGS.items():
            if other == action:
                continue
            for flag in flags - mine:
                if o.get(flag) is not _FLAG_UNSET[flag]:
                    raise CommandError(
                        f"--{flag.replace('_', '-')} is not valid for the "
                        f"{action!r} action (it belongs to {other!r})."
                    )

    # --- export --------------------------------------------------------

    def _export(self, o):
        if not o.get("source_slug"):
            raise CommandError("export requires --source-slug")
        try:
            course = Course.objects.get(slug=o["source_slug"])
        except Course.DoesNotExist as exc:
            raise CommandError(f"no course with slug {o['source_slug']!r}") from exc

        bundle = Path(o["bundle_dir"])
        bundle.mkdir(parents=True, exist_ok=True)

        parts = list(
            ContentNode.objects.filter(
                course=course, parent__isnull=True
            ).order_by("order", "pk")
        )
        if not parts:
            raise CommandError(f"course {course.slug!r} has no top-level nodes")

        # pk -> [part order, ...]. Accumulated across ALL parts and written
        # once, only on full success: a partial table would make `verify`
        # under-report cross-part sharing and turn a legitimate media delta
        # into an apparent fault.
        side = {}

        for part in parts:
            manifest, document, media_assets, problems = build_export(
                course, node=part
            )
            if problems and not o.get("allow_problems"):
                raise CommandError(
                    f"part {part.order} ({part.title!r}) exported with "
                    f"{len(problems)} problem(s): {problems}. "
                    f"Re-run with --allow-problems to accept them."
                )
            for _mid, asset, _is_placeholder in media_assets:
                side.setdefault(str(asset.pk), []).append(part.order)

            name = f"{part.order:02d}-{course.slug}.zip"
            with open(bundle / name, "wb") as fh:
                write_archive_from(manifest, document, media_assets, fh)
            self.stdout.write(f"exported part {part.order}: {name}")

        (bundle / SIDE_TABLE).write_text(
            json.dumps(side, ensure_ascii=False), encoding="utf-8"
        )
        self.stdout.write(f"wrote {SIDE_TABLE} ({len(side)} asset(s))")
```

- [ ] **Step 4: Confirm green**

```
uv run pytest tests/test_migrate_course_content.py -vv
```

Expected: 6 passed (4 original + the problems-guard and export-rerun tests).

- [ ] **Step 5: Falsify the two guards this task introduces**

1. **Flag scoping** — delete the `_reject_foreign_flags(action, o)` call in `handle`. `test_export_refuses_import_only_flags` must FAIL (no `CommandError` raised). Restore.
2. **Side-table completeness** — change `side.setdefault(str(asset.pk), []).append(part.order)` to only record the first part (`side.setdefault(str(asset.pk), [part.order])`). Confirm `test_export_writes_the_media_side_table_keyed_by_source_pk` still passes — it does, because each asset here is referenced by one part — then note that cross-part accumulation is pinned by Task 3's shared-media test, not this one. Restore.
3. **The problems guard** — change `if problems and not o.get("allow_problems")` to `if False`. `test_export_aborts_on_problems_and_allow_problems_overrides` must FAIL on the `pytest.raises` (no `CommandError` at all). This is the spec's central content-loss guard; a falsification that does not go red here would mean the migration could silently ship placeholdered media. Restore.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format .          # the plan's snippets are not pre-formatted
uv run ruff check . && uv run ruff format --check .
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(transfer): migrate_course_content export phase"
```

---

### Task 2: The `import` action — grafting, guards, dry-run, resume

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py`
- Modify: `tests/test_migrate_course_content.py` (append)

**Interfaces:**
- Consumes: Task 1's bundle layout (`{order:02d}-*.zip` + `media-parts.json`).
- Produces: `migrate_course_content import --target-slug T --bundle-dir D --as-user EMAIL [--dry-run] [--force] [--start-at K]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_migrate_course_content.py`. Add `from django.contrib.auth import get_user_model` to the top-of-file import block (a mid-file import fails `E402`).

```python
def _export_bundle(tmp_path, parts=("P0", "P1", "P2")):
    _mk_source(parts=parts)
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content", "export",
        "--source-slug", "src", "--bundle-dir", str(bundle),
    )
    return bundle


def _user(email="mig@example.com"):
    return get_user_model().objects.create_user(
        username="mig", email=email, password="x"
    )


def test_import_grafts_every_part_at_top_level_in_source_order(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com",
    )
    tops = list(
        ContentNode.objects.filter(course=target, parent__isnull=True)
        .order_by("order", "pk")
        .values_list("title", flat=True)
    )
    assert tops == ["P0", "P1", "P2"]


def test_import_carries_placeholder_titles_verbatim(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com",
    )
    assert ContentNode.objects.filter(
        course=target, title="__PLACEHOLDER chapter 0__"
    ).exists()


def test_import_stamps_uploaded_by_from_as_user(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    target = _mk_target()
    u = _user()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com",
    )
    assets = MediaAsset.objects.filter(course=target)
    assert assets.exists()
    assert all(a.uploaded_by_id == u.pk for a in assets)


def test_import_rejects_an_unknown_as_user(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    _mk_target()
    with pytest.raises(CommandError, match="no user with email"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "ghost@example.com",
        )


def test_import_refuses_a_non_empty_target_without_force(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    target = _mk_target()
    _user()
    ContentNode.objects.create(course=target, kind="part", title="Squatter")
    with pytest.raises(CommandError, match="already has"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com",
        )


def test_dry_run_validates_every_archive_and_writes_nothing(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com", "--dry-run",
    )
    assert ContentNode.objects.filter(course=target).count() == 0
    assert MediaAsset.objects.filter(course=target).count() == 0


def test_start_at_grafts_only_the_remainder(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    # Simulate a run that already committed part 0.
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com", "--start-at", "0",
    )
    # Now only parts 1..2 remain; resume from 1 would duplicate nothing.
    ContentNode.objects.filter(
        course=target, parent__isnull=True
    ).exclude(title="P0").delete()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com", "--start-at", "1",
    )
    tops = list(
        ContentNode.objects.filter(course=target, parent__isnull=True)
        .order_by("order", "pk")
        .values_list("title", flat=True)
    )
    assert tops == ["P0", "P1", "P2"]


@pytest.mark.parametrize("bad", [0, 2])
def test_start_at_aborts_when_the_target_node_count_disagrees(tmp_path, bad):
    """--start-at K requires exactly K top-level nodes already present.

    With one part committed, K=1 is the only legal resume point; K=0 and K=2
    are the off-by-one mistypes this invariant exists to catch.
    """
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com", "--start-at", "0",
    )
    ContentNode.objects.filter(
        course=target, parent__isnull=True
    ).exclude(title="P0").delete()
    with pytest.raises(CommandError, match="expects the target to hold"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com", "--start-at", str(bad),
        )


def test_html_element_attributes_survive_the_round_trip(tmp_path):
    """Regression guard on the not-sanitized policy.

    _build_html stores HtmlElement.html verbatim -- the sandboxed iframe is the
    security boundary, not sanitisation. If someone later adds sanitisation
    there, the binary decision tree's data-binary-choose hooks would be
    stripped and it would migrate as intact-looking dead markup.
    """
    from courses.models import HtmlElement

    course = _mk_source(parts=("Only",))
    unit = ContentNode.objects.get(course=course, title="U0")
    Element.objects.create(
        unit=unit, title="",
        content_object=HtmlElement.objects.create(
            html='<button data-binary-choose="1.1">Tak</button>'
        ),
    )
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content", "export",
        "--source-slug", "src", "--bundle-dir", str(bundle),
    )
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com",
    )
    htmls = [
        h.html
        for h in HtmlElement.objects.all()
        if "data-binary-choose" in h.html
    ]
    assert len(htmls) == 2  # source's and the target's copy
    assert all('data-binary-choose="1.1"' in h for h in htmls)


def test_a_corrupt_archive_is_named_in_the_error(tmp_path):
    bundle = _export_bundle(tmp_path, parts=("Only",))
    _mk_target()
    _user()
    victim = next(bundle.glob("*.zip"))
    victim.write_bytes(b"not a zip at all")
    with pytest.raises(CommandError, match=victim.name):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com",
        )


def test_a_first_part_failure_reports_that_nothing_was_committed(tmp_path):
    """The degenerate K=0 boundary: no 'last part committed' exists to resume
    from, so the message must send the operator to a plain re-run."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    first = sorted(bundle.glob("*.zip"))[0]
    first.write_bytes(b"corrupt")
    with pytest.raises(CommandError, match="no parts committed"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com",
        )
    assert ContentNode.objects.filter(course=target).count() == 0


def test_force_lets_the_import_proceed_into_a_non_empty_target(tmp_path):
    """The refusal path is tested above; this pins that the override WORKS.

    A falsification proves the guard can fail; only this proves its bypass
    isn't inverted or ignored.
    """
    bundle = _export_bundle(tmp_path, parts=("Only",))
    target = _mk_target()
    _user()
    ContentNode.objects.create(course=target, kind="part", title="Squatter")
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com", "--force",
    )
    tops = set(
        ContentNode.objects.filter(course=target, parent__isnull=True)
        .values_list("title", flat=True)
    )
    assert tops == {"Squatter", "Only"}


def test_import_rejects_an_empty_bundle_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    _mk_target()
    _user()
    with pytest.raises(CommandError, match="no archives"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(empty),
            "--as-user", "mig@example.com",
        )
```

- [ ] **Step 2: Verify failure**

```
uv run pytest tests/test_migrate_course_content.py -vv -k "import or dry_run or start_at"
```

Expected: every one FAILS with `CommandError: action not implemented yet: import` (Task 1's placeholder). Any other failure means the bundle fixture is wrong — fix that before implementing.

- [ ] **Step 3: Implement the `import` action**

In `courses/management/commands/migrate_course_content.py`, add these imports to the existing top-of-file block:

```python
from django.contrib.auth import get_user_model

from courses.transfer.importer import import_subtree
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.schema import KIND_SUBTREE
from courses.transfer.schema import TransferError
```

Replace the `else:` placeholder branch in `handle` with `elif action == "import": self._import(o)`, and add:

```python
    # --- import --------------------------------------------------------

    def _bundle_archives(self, bundle):
        """Archives in part order, taken from the zero-padded filename prefix.

        Deterministic naming means order is recoverable without opening every
        archive to read its manifest.
        """
        archives = sorted(bundle.glob("*.zip"))
        if not archives:
            raise CommandError(
                f"no archives in {bundle} -- an import that grafts nothing "
                f"would be indistinguishable from a completed migration"
            )
        return archives

    def _import(self, o):
        if not o.get("target_slug"):
            raise CommandError("import requires --target-slug")
        if not o.get("as_user"):
            raise CommandError(
                "import requires --as-user: it is stamped on every "
                "re-materialised MediaAsset.uploaded_by"
            )
        try:
            target = Course.objects.get(slug=o["target_slug"])
        except Course.DoesNotExist as exc:
            raise CommandError(f"no course with slug {o['target_slug']!r}") from exc
        try:
            user = get_user_model().objects.get(email=o["as_user"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError(f"no user with email {o['as_user']!r}") from exc

        bundle = Path(o["bundle_dir"])
        archives = self._bundle_archives(bundle)

        existing = ContentNode.objects.filter(
            course=target, parent__isnull=True
        ).count()
        start_at = o.get("start_at")

        if start_at is None:
            # Double-run guard: grafting into a non-empty target would append a
            # SECOND copy of every part.
            if existing and not o.get("force"):
                raise CommandError(
                    f"target {target.slug!r} already has {existing} top-level "
                    f"node(s); pass --force to graft anyway, or --start-at to "
                    f"resume a partial run"
                )
            todo = archives
        else:
            # Resume: the operator supplies the intent, the command checks the
            # fact. A mistyped K would otherwise silently skip or duplicate a
            # part -- exactly what the double-run guard it bypasses prevents.
            if existing != start_at:
                raise CommandError(
                    f"--start-at {start_at} expects the target to hold exactly "
                    f"{start_at} top-level node(s), but it holds {existing}"
                )
            todo = [a for a in archives if int(a.name[:2]) >= start_at]

        committed = None
        for archive in todo:
            order = int(archive.name[:2])
            try:
                with open(archive, "rb") as fh:
                    with open_archive(fh, expected_kind=KIND_SUBTREE) as (
                        zf, manifest, document, media_entries,
                    ):
                        validate_archive_document(
                            zf, manifest, document, media_entries,
                            kind=KIND_SUBTREE, target_course=target,
                        )
                        n_nodes = len(document["nodes"])
                        n_els = len(document["elements"])
                        n_media = len(document["media"])
                        if o.get("dry_run"):
                            self.stdout.write(
                                f"[dry-run] {archive.name}: {n_nodes} nodes, "
                                f"{n_els} elements, {n_media} media"
                            )
                            continue
                        # insertion_node=None -> top level. All positional.
                        import_subtree(
                            zf, manifest, document, media_entries,
                            target, None, user,
                        )
            except TransferError as exc:
                # Recovery guidance belongs HERE, on the failure path -- a
                # trailing "no parts committed" line after the loop would be
                # unreachable, because this CommandError propagates out of it.
                if committed is None:
                    hint = "no parts committed; re-run import from the start"
                else:
                    hint = (
                        f"last part committed: {committed}; "
                        f"resume with --start-at {committed + 1}"
                    )
                raise CommandError(f"{archive.name}: {exc}
{hint}") from exc
            committed = order
            self.stdout.write(f"grafted part {order} from {archive.name}")

        if o.get("dry_run"):
            self.stdout.write("[dry-run] validated; nothing written")
        else:
            self.stdout.write(f"last part committed: {committed}")
```

- [ ] **Step 4: Confirm green**

```
uv run pytest tests/test_migrate_course_content.py -vv
```

Expected: **20 passed** — Task 1's 6 plus this task's 14 collected (13 named, with `test_start_at_aborts_when_the_target_node_count_disagrees` parametrized ×2).

- [ ] **Step 5: Falsify the three guards that protect the real database**

Run each, confirm the named test goes RED, then restore:

1. **Double-run guard** — change `if existing and not o.get("force")` to `if False`. `test_import_refuses_a_non_empty_target_without_force` must FAIL.
2. **`--start-at` invariant** — change `if existing != start_at` to `if False`. Both parametrisations of `test_start_at_aborts_when_the_target_node_count_disagrees` must FAIL.
3. **Dry-run writes nothing** — delete the `continue` after the dry-run `stdout.write`. `test_dry_run_validates_every_archive_and_writes_nothing` must FAIL on the node count.
4. **Archive named in the error** — change `raise CommandError(f"{archive.name}: {exc}
{hint}")` to omit `archive.name`. `test_a_corrupt_archive_is_named_in_the_error` must FAIL (its `match=` is the filename).
5. **The `no parts committed` hint is reachable** — change the `if committed is None` branch to always emit the resume hint. `test_a_first_part_failure_reports_that_nothing_was_committed` must FAIL. This one matters because the message was unreachable in an earlier draft: it sat after the loop, where the propagating `CommandError` never let it run.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format .
uv run ruff check . && uv run ruff format --check .
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(transfer): migrate_course_content import phase with guards"
```

---

### Task 3: The `verify` action

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py`
- Modify: `tests/test_migrate_course_content.py` (append)

**Interfaces:**
- Consumes: the bundle from Task 1, a populated target from Task 2.
- Produces: `migrate_course_content verify --target-slug T --bundle-dir D`.

- [ ] **Step 1: Write the failing tests**

```python
def test_verify_passes_after_a_complete_import(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com",
    )
    call_command(
        "migrate_course_content", "verify",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
    )  # must not raise


def test_verify_fails_when_a_part_is_missing(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com",
    )
    ContentNode.objects.filter(
        course=target, parent__isnull=True, title="P2"
    ).delete()
    with pytest.raises(CommandError, match="node count mismatch"):
        call_command(
            "migrate_course_content", "verify",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
        )


def test_verify_refuses_a_bundle_with_no_side_table(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    (bundle / "media-parts.json").unlink()
    with pytest.raises(CommandError, match="is missing from"):
        call_command(
            "migrate_course_content", "verify",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
        )


def test_shared_media_duplicates_and_is_accounted_for(tmp_path):
    """An asset referenced from two parts is exported into both archives and
    re-materialised twice, so the target's media count legitimately EXCEEDS the
    source's. The side table is what distinguishes that from a fault."""
    course = _mk_source(parts=("P0", "P1"))
    shared = MediaAsset.objects.filter(course=course).first()
    # Reference P0's asset from P1's unit too.
    other_unit = ContentNode.objects.get(course=course, title="U1")
    Element.objects.create(
        unit=other_unit, title="",
        content_object=ImageElement.objects.create(media=shared, alt="shared"),
    )
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content", "export",
        "--source-slug", "src", "--bundle-dir", str(bundle),
    )
    table = json.loads((bundle / "media-parts.json").read_text(encoding="utf-8"))
    assert sorted(table[str(shared.pk)]) == [0, 1]  # in BOTH parts

    _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com",
    )
    # Verify accepts the surplus because the table explains it.
    call_command(
        "migrate_course_content", "verify",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
    )
```

- [ ] **Step 2: Verify failure**

```
uv run pytest tests/test_migrate_course_content.py -vv -k "verify or shared_media"
```

(The `-k` expression must be quoted — unquoted, the shell splits it and pytest sees only `verify`.) Expected: FAIL with `action not implemented yet: verify`.

- [ ] **Step 3: Implement `verify`**

Add the one import `verify` needs to the command's top-of-file block — deliberately not added
earlier, because `ruff`'s `F401` would have failed Tasks 1 and 2 at their commit gates:

```python
from courses.models import MediaAsset
```

Then replace the remaining placeholder branch with `else: self._verify(o)` and add:

```python
    # --- verify --------------------------------------------------------

    def _verify(self, o):
        if not o.get("target_slug"):
            raise CommandError("verify requires --target-slug")
        try:
            target = Course.objects.get(slug=o["target_slug"])
        except Course.DoesNotExist as exc:
            raise CommandError(f"no course with slug {o['target_slug']!r}") from exc

        bundle = Path(o["bundle_dir"])
        table_path = bundle / SIDE_TABLE
        if not table_path.exists():
            # A missing table means the export that produced this bundle never
            # completed. Defaulting to "nothing is shared" would report
            # legitimate duplication as a fault -- the inversion the table
            # exists to prevent.
            raise CommandError(
                f"{SIDE_TABLE} is missing from {bundle}; the export that "
                f"produced this bundle did not complete, so a media delta "
                f"cannot be interpreted"
            )
        table = json.loads(table_path.read_text(encoding="utf-8"))

        archives = self._bundle_archives(bundle)
        expected_nodes = 0
        for archive in archives:
            with open(archive, "rb") as fh:
                with open_archive(fh, expected_kind=KIND_SUBTREE) as (
                    _zf, _manifest, document, _entries,
                ):
                    expected_nodes += len(document["nodes"])

        actual_nodes = ContentNode.objects.filter(course=target).count()
        if actual_nodes != expected_nodes:
            raise CommandError(
                f"node count mismatch: bundle declares {expected_nodes}, "
                f"target {target.slug!r} holds {actual_nodes}"
            )

        # Media is a FLOOR, not an exact match: an asset referenced from N
        # parts is re-materialised N times. The side table says how many.
        floor = len(table)
        expected_max = sum(len(parts) for parts in table.values())
        actual_media = MediaAsset.objects.filter(course=target).count()
        if not floor <= actual_media <= expected_max:
            raise CommandError(
                f"media count {actual_media} outside the range the bundle "
                f"explains ({floor}..{expected_max})"
            )
        shared = {k: v for k, v in table.items() if len(v) > 1}
        self.stdout.write(
            f"OK: {actual_nodes} nodes, {actual_media} media "
            f"({len(shared)} asset(s) shared across parts)"
        )
```

- [ ] **Step 4: Confirm green, then run the full suite**

```
uv run pytest tests/test_migrate_course_content.py -vv
uv run pytest -m "not e2e"
```

Expected: this file's tests all pass, and the full non-e2e suite has no new failures. Report the actual pass count rather than a remembered baseline — the suite has grown during this session.

- [ ] **Step 5: Falsify verify's two guards**

1. **Missing side table** — change `if not table_path.exists()` to `if False`. `test_verify_refuses_a_bundle_with_no_side_table` must FAIL (a `FileNotFoundError` escaping instead of a `CommandError` also counts as red, but the test expects `CommandError`, so make the guard raise it properly). Restore.
2. **Node reconciliation** — change `if actual_nodes != expected_nodes` to `if False`. `test_verify_fails_when_a_part_is_missing` must FAIL. Restore.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format .
uv run ruff check . && uv run ruff format --check .
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(transfer): migrate_course_content verify phase"
```

---

## Done when

- `migrate_course_content` supports `export`, `import` and `verify`, with flags scoped per action.
- Every guard that protects the real database — double-run, `--start-at` invariant, dry-run-writes-nothing, problems-abort, missing-side-table — has been shown able to fail.
- Media shared across parts duplicates on import and is *accounted for* by the side table rather than reported as a fault.
- Full non-e2e suite green; `ruff check` and `ruff format --check` both clean.
- Nothing in the repository writes to `libli_mat` or the real `libli`.
