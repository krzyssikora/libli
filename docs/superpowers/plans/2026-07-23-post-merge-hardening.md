# Post-Merge Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Course-scope the two editor image resolvers that render author-submitted media pks on a rejected save, and add a catalog-health guard that catches an untranslated Polish string.

**Architecture:** Two unrelated changes. Issue B threads a course into two resolvers so they agree with the validators in the same forms — one gains an optional `course=None` parameter, the other scopes directly. Issue C adds one new test file owning every whole-catalog assertion, backed by a small hand-rolled `.po` parser, and deletes the duplicated assertion it replaces.

**Tech Stack:** Django 5.2, pytest, pytest-xdist, ruff.

**Spec:** `docs/superpowers/specs/2026-07-23-post-merge-hardening-design.md` — read it before starting.

## Global Constraints

- **Tests:** `uv run pytest <paths> -v`. `ruff`, `pytest` and `python` are **not on PATH** — always go through `uv run`.
- **Never** set `DJANGO_SETTINGS_MODULE` on a pytest invocation. `pyproject.toml` pins `config.settings.test`; forcing `local` breaks `tests/test_auth_styles.py` with a false failure.
- **Never add `-q`**, and never pipe pytest through `tail`/`head` (the harness then reports the pipe's exit code). Note `pyproject.toml` already sets `addopts = "-q -m 'not e2e'"`, so `-q` is baked in and adding another one only suppresses more output. A consequence worth knowing: a single `-v` merely cancels that baked-in `-q` back to *default* output, so it does **not** give per-test PASSED/FAILED lines. Where a step below needs to read which specific test failed and why, it uses **`-vv`**.
- **Never** run a bare `-m e2e` sweep — it spawns a browser per test. This plan needs no e2e.
- **Lint:** `uv run ruff check .` and `uv run ruff format --check .` must both be clean. CI gates on them separately.
- **Stage explicitly by path.** Never `git add -A` or `git add .`.
- **No migration.** Neither issue changes a model field.
- **Imports go in the file's existing top-of-file import block.** `pyproject.toml` selects `E` and `I`, so a mid-file import is an immediate `E402`/isort failure.
- **Every task is TDD:** write the failing test, run it and confirm it fails *for the stated reason*, implement, confirm green, commit.
- Issues B and C are independent. Tasks 1–2 (B) and Tasks 3–4 (C) share no code.
- **`tests/test_i18n_catalog.py` is a name trap — do not touch it.** Despite the name it tests the
  course *catalog page's* translation and has nothing to do with `.po` catalogs. It must not host the
  new guard and must not be modified by any task in this plan.

---

## File Structure

**Created:**
- `tests/test_i18n_po_health.py` — the `.po` parser and all three whole-catalog guards, plus their falsification fixtures.

**Modified:**
- `courses/models.py` — `FillTableElement.resolve_image_cells` gains `course=None`.
- `courses/element_forms.py` — `FillTableElementForm.resolved_grid_cells` passes `self.course`; `GalleryElementForm.editor_rows` scopes its own lookup.
- `tests/test_filltable_editor_partial.py` — two new B1 tests.
- `tests/test_gallery_editor_partial.py` — two new B2 tests.
- `tests/test_i18n_auth.py` — delete `test_po_catalog_clean` (keep `POFILE`, used elsewhere).
- `tests/test_i18n_notes.py` — delete `test_po_catalog_clean` **and** the now-dead `PO` constant.

---

### Task 1: Course-scope the fill-table image resolver (B1)

**Files:**
- Modify: `courses/models.py` (`FillTableElement.resolve_image_cells`)
- Modify: `courses/element_forms.py` (`FillTableElementForm.resolved_grid_cells`)
- Test: `tests/test_filltable_editor_partial.py` (append)

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `FillTableElement.resolve_image_cells(cells, course=None)` — a `@staticmethod` returning the same resolved-cells list as today. When `course` is not `None` the lookup is restricted to `MediaAsset` rows with `course=course` and `kind="image"`.

- [ ] **Step 1: Write the two failing tests**

Append to `tests/test_filltable_editor_partial.py`. `json`, `FORM_FOR_TYPE`, `FillTableElement`, `make_course` and `make_image_asset` are already imported at the top of that file — add nothing.

```python
def test_foreign_course_image_cell_does_not_resolve_in_the_editor():
    """A rejected save carrying ANOTHER course's image pk must not re-render
    that asset's URL.

    The payload is deliberately valid in every OTHER respect -- it carries a
    real answer cell -- so clean_data's earlier guards (caps, answer-cell
    presence, blank-answer) all pass and it reaches the img_ids course check,
    which is the rule that actually rejects it. Getting this wrong is easy: a
    payload with no answer cell is rejected by "Mark at least one answer cell"
    long before any media validation runs, and the test would then pass while
    exercising a different rejection path than its name claims."""
    mine = make_course()
    theirs = make_course()
    foreign = make_image_asset(theirs, filename="theirs.png")

    submitted = {
        "cells": [
            [
                {"kind": "image", "media": foreign.pk, "alt": "x"},
                {"kind": "answer", "answer": "1"},
            ]
        ]
    }
    form = FORM_FOR_TYPE["filltable"](
        data={"data": json.dumps(submitted)}, instance=FillTableElement(), course=mine
    )
    assert not form.is_valid(), form.errors
    # Pin WHY it was rejected, so the test cannot silently start passing for an
    # unrelated reason (an earlier guard firing) after a future edit.
    assert "not an image in this course" in str(form.errors)
    cell = form.resolved_grid_cells[0][0]
    # Falls into the EXISTING unresolved branch: empty static cell.
    assert cell["kind"] == "static" and cell["html"] == ""
    # The decisive assertion: the foreign asset's URL is nowhere in the output.
    assert foreign.file.url not in json.dumps(form.resolved_grid_cells, default=str)


def test_wrong_kind_media_does_not_resolve_in_the_editor():
    """clean_data requires an IMAGE in this course. An in-course asset of the
    wrong kind is rejected at save, so the resolver must not resolve it either
    -- otherwise the editor emits a video's URL inside an <img>. As above, the
    payload carries a real answer cell so the rejection comes from the media
    check and not from an earlier guard."""
    course = make_course()
    video = make_image_asset(course, filename="clip.png", kind="video")

    submitted = {
        "cells": [
            [
                {"kind": "image", "media": video.pk, "alt": "x"},
                {"kind": "answer", "answer": "1"},
            ]
        ]
    }
    form = FORM_FOR_TYPE["filltable"](
        data={"data": json.dumps(submitted)}, instance=FillTableElement(), course=course
    )
    assert not form.is_valid(), form.errors
    assert "not an image in this course" in str(form.errors)
    cell = form.resolved_grid_cells[0][0]
    assert cell["kind"] == "static" and cell["html"] == ""
    assert video.file.url not in json.dumps(form.resolved_grid_cells, default=str)
```

- [ ] **Step 2: Run them and confirm they fail for the right reason**

```
uv run pytest tests/test_filltable_editor_partial.py -k "foreign_course_image or wrong_kind_media" -vv
```

Expected: both FAIL on `assert cell["kind"] == "static"` — the cell resolves to the foreign/wrong-kind asset, so `kind` is still `"image"`.

Two ways this can fail for the WRONG reason; both mean stop and fix the payload rather than proceeding:
- a failure on `assert not form.is_valid()` — the payload was accepted, so the resolver branch is never reached;
- a failure on `assert "not an image in this course" in str(form.errors)` — the form was rejected by an *earlier* guard (caps, missing answer cell, blank answer) and the media check never ran.

- [ ] **Step 3: Add the `course` parameter to the resolver**

In `courses/models.py`, change `resolve_image_cells`'s signature and its lookup. Everything below `assets = ...` is unchanged.

```python
    @staticmethod
    def resolve_image_cells(cells, course=None):
        """A normalized cells grid with each image cell's `media` int pk replaced
        by its MediaAsset (one in_bulk pass). Unresolved pks degrade to an empty
        static cell -- dropping any colspan/rowspan/header the cell carried --
        so a dangling asset never 500s a lesson and never leaves a spanning gap
        with nothing spanning it. Static/answer cells pass through unchanged.

        Shared by resolved_cells (student render, resolves against self.data)
        and FillTableElementForm.resolved_grid_cells (editor, resolves against
        the submitted/stored grid_data on a rejected save) -- the two callers
        must not diverge on this fallback.

        `course` scopes the lookup to that course's IMAGE assets, matching what
        clean_data validates. The editor passes it because it resolves
        AUTHOR-SUBMITTED pks on a rejected save; the student render passes
        nothing, because its data already passed clean_data at save time and no
        course is threaded through the render chain. An out-of-scope pk simply
        fails to resolve and takes the existing unresolved branch -- no new
        branch, no second fallback shape.

        NOTE: a cell's `kind` ("static"/"answer"/"image") and MediaAsset.kind
        are different fields on different objects that happen to share the
        string "image". The comprehension below filters CELLS; the query
        filters ASSETS."""
        ids = [c["media"] for row in cells for c in row if c.get("kind") == "image"]
        if not ids:
            assets = {}
        elif course is None:
            assets = MediaAsset.objects.in_bulk(ids)
        else:
            assets = MediaAsset.objects.filter(
                course=course, kind="image", pk__in=ids
            ).in_bulk()
```

- [ ] **Step 4: Pass the course from the form**

In `courses/element_forms.py`, change the last line of `FillTableElementForm.resolved_grid_cells` and extend its docstring:

```python
    @property
    def resolved_grid_cells(self):
        """grid_data's cells with image pks resolved to MediaAsset, mirroring
        FillTableElement.resolved_cells but sourced from grid_data so a
        rejected save re-renders the SUBMITTED grid (see grid_data).

        Delegates to FillTableElement.resolve_image_cells so the editor and
        the student render cannot silently diverge on the unresolved-image
        fallback (it drops any colspan/rowspan/header the cell carried, same
        as the model).

        Passes self.course so a submitted pk from another course -- or an
        in-course asset of the wrong kind -- resolves to nothing and takes that
        same fallback, instead of rendering a foreign asset's URL."""
        return FillTableElement.resolve_image_cells(
            self.grid_data["cells"], course=self.course
        )
```

- [ ] **Step 5: Confirm green, and that the shared fallback was not forked**

```
uv run pytest tests/test_filltable_editor_partial.py tests/test_filltable_render.py tests/test_spanning_roundtrip.py -v
```

Expected: all pass. `test_unresolvable_image_cell_drops_spans_in_both_render_and_editor` must be **green and unmodified** — it is what proves the student and editor paths still share one fallback.

- [ ] **Step 6: Falsify**

Temporarily change Step 4's call back to `FillTableElement.resolve_image_cells(self.grid_data["cells"])`, re-run the two new tests, and confirm both go RED on the `kind == "static"` assertion. Restore the `course=self.course` argument.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add courses/models.py courses/element_forms.py tests/test_filltable_editor_partial.py
git commit -m "fix(filltable): course-scope image resolution on a rejected save"
```

---

### Task 2: Course-scope the gallery image resolver (B2)

**Files:**
- Modify: `courses/element_forms.py` (`GalleryElementForm.editor_rows`)
- Test: `tests/test_gallery_editor_partial.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1 — this is the same defect in a different form, with no shared code.
- Produces: `GalleryElementForm.editor_rows` unchanged in signature (a property returning `[{id, thumb_url, desc}]`); only its lookup is scoped.

- [ ] **Step 1: Write the two failing tests**

Append to `tests/test_gallery_editor_partial.py`. Add `import json` to that file's existing top-of-file import block if absent; `GalleryElementForm`, `GalleryElement`, `make_course` and `make_image_asset` are already imported.

```python
def test_foreign_course_image_is_not_resolved_into_editor_rows():
    """A rejected gallery save carrying ANOTHER course's image pk must not
    re-render that asset's thumbnail.

    The payload carries TWO images -- one legitimately in this course, one
    foreign -- for two reasons. First, GalleryElement.MIN_IMAGES is 2, so a
    single-image payload is rejected by "A gallery needs at least 2 images"
    before any media validation runs, and the test would then pass while
    exercising a rejection path unrelated to its name. Second, keeping a valid
    image proves the scoping is SELECTIVE: the in-course row survives while the
    foreign one disappears, which a blanket "resolve nothing" bug would fail."""
    mine = make_course()
    theirs = make_course()
    ok = make_image_asset(mine, filename="mine.png")
    foreign = make_image_asset(theirs, filename="theirs.png")

    submitted = {
        "desc_pos": "above",
        "images": [{"media": ok.pk, "desc": ""}, {"media": foreign.pk, "desc": ""}],
    }
    form = GalleryElementForm(
        data={"data": json.dumps(submitted)},
        instance=GalleryElement(),
        course=mine,
    )
    assert not form.is_valid(), form.errors
    # Pin WHY it was rejected, so an earlier guard firing cannot make this pass
    # for the wrong reason.
    assert "not an image in this course" in str(form.errors)
    rows = form.editor_rows
    # Gallery's OWN fallback is to DROP the row entirely -- not the fill-table's
    # degrade-to-empty-static. The two forms deliberately differ here.
    assert [r["id"] for r in rows] == [ok.pk]
    assert foreign.file.url not in json.dumps(rows)


def test_wrong_kind_media_is_not_resolved_into_editor_rows():
    """An in-course asset of the wrong kind is rejected by clean_data, so
    editor_rows must not resolve it either. Same two-image shape as above, for
    the same two reasons."""
    course = make_course()
    ok = make_image_asset(course, filename="ok.png")
    video = make_image_asset(course, filename="clip.png", kind="video")

    submitted = {
        "desc_pos": "above",
        "images": [{"media": ok.pk, "desc": ""}, {"media": video.pk, "desc": ""}],
    }
    form = GalleryElementForm(
        data={"data": json.dumps(submitted)},
        instance=GalleryElement(),
        course=course,
    )
    assert not form.is_valid(), form.errors
    assert "not an image in this course" in str(form.errors)
    rows = form.editor_rows
    assert [r["id"] for r in rows] == [ok.pk]
    assert video.file.url not in json.dumps(rows)
```

- [ ] **Step 2: Run them and confirm they fail for the right reason**

```
uv run pytest tests/test_gallery_editor_partial.py -k "foreign_course_image or wrong_kind_media" -vv
```

Expected: both FAIL on `assert [r["id"] for r in rows] == [ok.pk]` — the list holds two ids, because the unscoped `in_bulk` resolved the foreign/wrong-kind asset alongside the legitimate one.

A failure on `assert not form.is_valid()` (payload accepted) or on the `"not an image in this course"` assertion (rejected by an earlier guard, so the media check never ran) both mean the test is not exercising the intended path — stop and fix the payload.

- [ ] **Step 3: Scope the lookup**

In `courses/element_forms.py`, change the `assets = ...` line inside `GalleryElementForm.editor_rows` and extend the docstring. Every other line of the property is unchanged.

```python
    @property
    def editor_rows(self):
        """Resolved [{id, thumb_url, desc}] for the editor: from submitted data
        when bound (so an invalid re-render keeps the author's picks), else from
        the instance. Unresolved ids are dropped.

        The lookup is scoped to this course's IMAGE assets, matching what
        clean_data validates -- without it, a rejected save carrying another
        course's pk re-renders that asset's URL. Scoping is unconditional here,
        with no course=None carve-out, because clean_data in this same form
        filters unconditionally too (unlike FillTableElementForm's, which has an
        `is not None` guard). Resolver and validator agree by construction."""
        if self.is_bound:
            source = GalleryElement.normalize_data(self._raw_data_json())
        else:
            source = GalleryElement.normalize_data(getattr(self.instance, "data", {}))
        ids = [img["media"] for img in source["images"]]
        assets = MediaAsset.objects.filter(
            course=self.course, kind="image", pk__in=ids
        ).in_bulk()
```

- [ ] **Step 4: Confirm green**

```
uv run pytest tests/test_gallery_editor_partial.py tests/test_gallery_form.py tests/test_gallery_manage.py tests/test_gallery_render.py -v
```

Expected: all pass. The existing `test_partial_seeds_rows_and_controls` covers the legitimate same-course path and must stay green — it is what proves the scoping did not break normal rendering.

- [ ] **Step 5: Falsify**

Temporarily restore `assets = MediaAsset.objects.in_bulk(ids)`, re-run the two new tests, and confirm both go RED on `form.editor_rows == []`. Restore the scoped query.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add courses/element_forms.py tests/test_gallery_editor_partial.py
git commit -m "fix(gallery): course-scope image resolution on a rejected save"
```

---

### Task 3: The catalog-health guard (C)

**Files:**
- Create: `tests/test_i18n_po_health.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces: `_entries(path) -> list[dict]` with per-entry shape `{"msgid": str, "msgstrs": list[str], "fuzzy": bool, "obsolete": bool, "plural": bool}`; `_nplurals(path) -> int`; `_format_offenders(msgids) -> str`. Three test functions: `test_no_fuzzy_entries`, `test_no_obsolete_entries`, `test_pl_has_no_untranslated_msgid`.

- [ ] **Step 1: Create the file with the parser and all three guards**

This task writes the tests and their subject together, because the parser *is* the thing under test — the six falsification scenarios in Step 3 are what prove it works, and they are written here too.

Create `tests/test_i18n_po_health.py`:

```python
"""Whole-catalog health guards for the gettext .po files.

Owns every assertion about the catalogs AS FILES: no fuzzy entries, no obsolete
entries, and no untranslated Polish string. These previously existed as a
`test_po_catalog_clean` duplicated verbatim in tests/test_i18n_auth.py and
tests/test_i18n_notes.py -- two copies of one assertion about files belonging to
neither module. That orphaned ownership is why nobody ever extended them to
catch a blank msgstr, and a msgid once shipped untranslated as a result.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PL_PO = ROOT / "locale" / "pl" / "LC_MESSAGES" / "django.po"
EN_PO = ROOT / "locale" / "en" / "LC_MESSAGES" / "django.po"

# Failure-message formatting, shared by all three guards: every one of them can
# have many offenders at once (a bad sweep reintroduces dozens).
MAX_MSGID_CHARS = 80
MAX_LISTED = 20

_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _joined(lines):
    """The concatenated payload of one or more .po string lines.

    A .po value may be split across continuation lines, each its own quoted
    string; emptiness can only be judged after joining them."""
    return "".join(part for ln in lines for part in _QUOTED.findall(ln))


def _entries(path):
    """Parse a .po file into entries.

    Each entry is {msgid, msgstrs, fuzzy, obsolete, plural}. `msgstrs` holds one
    string for a singular entry and one per plural form for a plural entry, so
    emptiness is judged uniformly across both.

    Two deliberate decisions:

    * Obsolete (`#~`) entries are RETAINED and marked, never dropped.
      test_no_obsolete_entries must see them to flag them, while the
      untranslated scan filters them out. Dropping them here would leave the
      obsolete guard asserting over a list its own subject had been removed
      from -- passing vacuously.
    * The header entry (msgid "") is likewise retained, not skipped. msgmerge
      marks a stale HEADER `#, fuzzy`, and the assertion this file replaces
      (`"#, fuzzy" not in text`) would have caught that; skipping the header
      here would silently weaken the fuzzy guard. It is excluded from the
      untranslated scan only, by msgid emptiness.
    """
    text = path.read_text(encoding="utf-8")
    entries = []
    for block in re.split(r"\n[ \t]*\n", text):
        lines = block.splitlines()
        if not lines:
            continue
        fuzzy = any(re.match(r"#,.*\bfuzzy\b", ln) for ln in lines)
        obsolete = any(ln.startswith("#~") for ln in lines)
        # Strip the obsolete marker so one state machine handles both shapes,
        # and drop ordinary comment/flag/reference lines.
        body = []
        for ln in lines:
            if ln.startswith("#~"):
                body.append(ln[2:].lstrip())
            elif not ln.startswith("#"):
                body.append(ln)
        msgid_lines, msgstr_lines, plural, current = [], {}, False, None
        for ln in body:
            if ln.startswith("msgid_plural"):
                plural = True
                current = None  # the plural SOURCE text is not needed
            elif ln.startswith("msgid"):
                current = msgid_lines
                current.append(ln)
            elif ln.startswith("msgstr["):
                idx = int(ln[len("msgstr[") : ln.index("]")])
                current = msgstr_lines.setdefault(idx, [])
                current.append(ln)
            elif ln.startswith("msgstr"):
                current = msgstr_lines.setdefault(0, [])
                current.append(ln)
            elif ln.startswith('"') and current is not None:
                current.append(ln)
        if not msgid_lines:
            continue
        entries.append(
            {
                "msgid": _joined(msgid_lines),
                "msgstrs": [_joined(msgstr_lines[k]) for k in sorted(msgstr_lines)],
                "fuzzy": fuzzy,
                "obsolete": obsolete,
                "plural": plural,
            }
        )
    return entries


def _nplurals(path):
    """How many plural forms this catalog declares.

    Read from the Plural-Forms header rather than assumed: Polish declares 3 and
    English declares 2, so any hardcoded number is wrong for one of them."""
    m = re.search(r"nplurals\s*=\s*(\d+)", path.read_text(encoding="utf-8"))
    return int(m.group(1)) if m else 1


def _format_offenders(msgids):
    """A stable, bounded failure list, shared by all three guards."""
    shown = [
        (m[:MAX_MSGID_CHARS] + "…") if len(m) > MAX_MSGID_CHARS else m
        for m in msgids[:MAX_LISTED]
    ]
    out = "\n".join(f"  - {m!r}" for m in shown)
    if len(msgids) > MAX_LISTED:
        out += f"\n  … and {len(msgids) - MAX_LISTED} more"
    return out


def _untranslated(path):
    """Live entries whose translation is missing or partially missing."""
    required = _nplurals(path)
    bad = []
    for e in _entries(path):
        if e["obsolete"] or not e["msgid"]:
            continue  # obsolete entries and the header are not translations
        need = required if e["plural"] else 1
        if len(e["msgstrs"]) < need or any(not s for s in e["msgstrs"]):
            bad.append(e["msgid"])
    return bad


def test_no_fuzzy_entries():
    for path in (PL_PO, EN_PO):
        bad = [e["msgid"] for e in _entries(path) if e["fuzzy"]]
        assert not bad, (
            f"{path.name}: fuzzy entries present — review and clear the flag:\n"
            + _format_offenders(bad)
        )


def test_no_obsolete_entries():
    for path in (PL_PO, EN_PO):
        bad = [e["msgid"] for e in _entries(path) if e["obsolete"]]
        assert not bad, (
            f"{path.name}: obsolete entries present — delete them:\n"
            + _format_offenders(bad)
        )


def test_pl_has_no_untranslated_msgid():
    """Polish only, deliberately.

    English msgstrs are intentionally empty: gettext falls back to the msgid, so
    locale/en legitimately carries hundreds of blanks and a guard covering it
    would be permanently red. No test pins that count, and none should — it
    drifts with every string added or removed."""
    bad = _untranslated(PL_PO)
    assert not bad, (
        "untranslated Polish msgid(s) — add a msgstr for each:\n"
        + _format_offenders(bad)
    )
```

- [ ] **Step 2: Run the three guards against the real catalogs**

```
uv run pytest tests/test_i18n_po_health.py -v
```

Expected: 3 passed. The real catalogs are currently clean, so this proves only that the parser does not raise and does not produce false positives — it proves nothing about whether the guards can fail. Step 3 is what proves that.

- [ ] **Step 3: Add the six falsification scenarios**

The real catalogs contain zero fuzzy and zero obsolete entries, so two of the three guards would be **vacuously green forever** if a `_entries()` bug left those flags `False`. Each guard needs a fixture that makes it fire.

**These fixtures must never mutate the real catalogs.** CI runs `uv run python -m pytest -n auto`, so tests run across parallel xdist workers; editing `locale/pl/LC_MESSAGES/django.po` in place — even with a revert — would let a concurrent test observe a corrupted catalog, and a mid-test failure would damage a real translation file on disk. Every scenario writes its own `tmp_path` file.

Append to `tests/test_i18n_po_health.py`:

```python
# --- falsification fixtures -------------------------------------------------
# Each scenario writes a synthetic .po to tmp_path. Nothing real is touched, so
# nothing needs reverting and nothing races a parallel xdist worker.

_HEADER = (
    'msgid ""\n'
    'msgstr ""\n'
    '"MIME-Version: 1.0\\n"\n'
    '"Content-Type: text/plain; charset=UTF-8\\n"\n'
    '"Plural-Forms: nplurals=3; plural=(n==1 ? 0 : 1);\\n"\n'
)


def _po(tmp_path, body, name="django.po"):
    p = tmp_path / name
    p.write_text(_HEADER + "\n" + body, encoding="utf-8")
    return p


def test_untranslated_scan_flags_a_blank_msgstr(tmp_path):
    p = _po(tmp_path, 'msgid "Save"\nmsgstr ""\n')
    assert _untranslated(p) == ["Save"]


def test_untranslated_scan_flags_one_missing_plural_form(tmp_path):
    """The subtlest branch: forms 0 and 1 are filled, form 2 is not."""
    p = _po(
        tmp_path,
        'msgid "%d file"\n'
        'msgid_plural "%d files"\n'
        'msgstr[0] "%d plik"\n'
        'msgstr[1] "%d pliki"\n'
        'msgstr[2] ""\n',
    )
    assert _untranslated(p) == ["%d file"]


def test_untranslated_scan_ignores_an_obsolete_blank_entry(tmp_path):
    """The false-positive direction: an obsolete entry with an empty
    translation must NOT be reported as untranslated."""
    p = _po(tmp_path, '#~ msgid "Gone"\n#~ msgstr ""\n')
    assert _untranslated(p) == []


def test_untranslated_scan_never_reports_the_header(tmp_path):
    """The header (msgid "") must never reach the report -- and this is not
    covered incidentally, because the real header's msgstr is non-empty
    metadata. The body carries a genuine offender so the report is non-empty
    and we can assert the header is not the thing named."""
    p = _po(tmp_path, 'msgid "Real"\nmsgstr ""\n')
    assert _untranslated(p) == ["Real"]
    assert "" not in _untranslated(p)


def test_entries_marks_a_fuzzy_entry(tmp_path):
    """Proves test_no_fuzzy_entries can fail. Against the real catalogs it
    asserts over an empty set and would stay green even if fuzzy parsing were
    broken entirely."""
    p = _po(tmp_path, '#, fuzzy\nmsgid "Save"\nmsgstr "Zapisz"\n')
    assert [e["msgid"] for e in _entries(p) if e["fuzzy"]] == ["Save"]


def test_entries_marks_an_obsolete_entry(tmp_path):
    """Proves test_no_obsolete_entries can fail. Note this is the OPPOSITE
    direction from the ignore-obsolete scenario above: the untranslated scan
    must skip obsolete entries while this guard must detect them. Both hold
    only because _entries() retains and marks them rather than dropping them."""
    p = _po(tmp_path, '#~ msgid "Gone"\n#~ msgstr "Zniknęło"\n')
    assert [e["msgid"] for e in _entries(p) if e["obsolete"]] == ["Gone"]
```

- [ ] **Step 4: Run the whole file**

```
uv run pytest tests/test_i18n_po_health.py -v
```

Expected: 9 passed (3 guards + 6 scenarios).

- [ ] **Step 5: Falsify the parser itself**

Prove each scenario is load-bearing, one at a time, reverting after each:

1. In `_entries`, change `fuzzy = any(...)` to `fuzzy = False`. Run: `test_entries_marks_a_fuzzy_entry` must FAIL. Restore.
2. Change `obsolete = any(...)` to `obsolete = False`. Run: `test_entries_marks_an_obsolete_entry` must FAIL, **and** `test_untranslated_scan_ignores_an_obsolete_blank_entry` must also FAIL (the entry is no longer recognised as obsolete, so the scan reports it). Restore.
3. In `_untranslated`, drop `or not e["msgid"]` from the skip condition. Run: `test_untranslated_scan_never_reports_the_header` must FAIL. Restore.
4. In `_untranslated`, change `need = required if e["plural"] else 1` to `need = 1`. Run: `test_untranslated_scan_flags_one_missing_plural_form` must still pass (form 2 is present-but-empty, caught by the `any(not s ...)` clause) — then additionally delete the `msgstr[2] ""` line from that fixture and confirm it FAILS, proving the `len(...) < need` clause carries the missing-form case. Restore both.

Record in the commit message which falsifications were run.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add tests/test_i18n_po_health.py
git commit -m "test(i18n): guard against untranslated PL msgids and catalog rot"
```

---

### Task 4: Retire the duplicated catalog assertion (C)

**Files:**
- Modify: `tests/test_i18n_auth.py` (delete `test_po_catalog_clean`)
- Modify: `tests/test_i18n_notes.py` (delete `test_po_catalog_clean` **and** the `PO` constant)

**Interfaces:**
- Consumes: `tests/test_i18n_po_health.py` from Task 3 — the replacement coverage must exist and be green *before* these are removed, or the branch is briefly unguarded.

- [ ] **Step 1: Confirm the replacement is in place**

```
uv run pytest tests/test_i18n_po_health.py -v
```

Expected: 9 passed. Do not proceed otherwise — this task removes coverage that Task 3 replaces.

- [ ] **Step 2: Delete the copy in `tests/test_i18n_auth.py`**

Remove exactly this function. Leave `POFILE` — `test_old_refreshed_msgid_retired` still uses it.

```python
def test_po_catalog_clean():
    text = POFILE.read_text(encoding="utf-8")
    assert "#, fuzzy" not in text, "fuzzy entries present — review and clear"
    assert "#~" not in text, "obsolete entries present — drop them"
```

- [ ] **Step 3: Delete the copy in `tests/test_i18n_notes.py`, and its now-dead constant**

Remove this function:

```python
def test_po_catalog_clean():
    text = PO.read_text(encoding="utf-8")
    assert "#, fuzzy" not in text, "fuzzy entries present — review and clear"
    assert "#~" not in text, "obsolete entries present — drop them"
```

and this module-level line, which no other test in that file uses:

```python
PO = ROOT / "locale" / "pl" / "LC_MESSAGES" / "django.po"
```

Then handle the cascade, which `ruff` *will* catch even though it ignores the dead constants themselves. Run `grep -n "ROOT\|Path" tests/test_i18n_notes.py`. In the current file `ROOT` appears only on its own definition line and in the `PO` line — `PO` is its sole consumer — so `ROOT` must go too:

```python
ROOT = Path(__file__).resolve().parent.parent
```

and with `ROOT` gone, `Path` has no remaining use, so this import must go as well:

```python
from pathlib import Path
```

**Keep** `import pytest` and `from django.utils import translation` — the parametrized msgid tests still use both. `ruff`'s `F401` is enabled (`select = ["E", "F", "I", "UP", "B", "S"]`), so leaving the now-unused `Path` import behind fails `uv run ruff check .` at Step 5. The dead `PO`/`ROOT` names themselves would *not* be flagged — module-level variables escape `F401` — which is exactly why they have to be removed by reading rather than by trusting the linter.

- [ ] **Step 4: Confirm nothing else referenced them**

```
uv run pytest tests/test_i18n_auth.py tests/test_i18n_notes.py tests/test_i18n_po_health.py -v
```

Expected: all pass, with two fewer tests than before and no `NameError`.

- [ ] **Step 5: Full suite and lint**

```
uv run pytest -m "not e2e"
uv run ruff check . && uv run ruff format --check .
```

Expected: no failures, both lint gates clean. `ruff` will not flag a leftover unused module-level `PO`, so Step 3's deletion is verified by reading, not by the linter.

- [ ] **Step 6: Commit**

```bash
git add tests/test_i18n_auth.py tests/test_i18n_notes.py
git commit -m "test(i18n): retire the duplicated catalog-clean assertion"
```

---

## Done when

- A rejected fill-table or gallery save carrying another course's image pk — or an in-course asset of the wrong kind — renders no URL for it, and each fix has been shown red without its scoping.
- `resolve_image_cells`'s single unresolved-image fallback is unchanged, proven by `test_unresolvable_image_cell_drops_spans_in_both_render_and_editor` still passing unmodified.
- One file owns catalog health, every guard has been shown capable of failing, and no test mutates a real `.po`.
- Full non-e2e suite green; `ruff check` and `ruff format --check` both clean.
