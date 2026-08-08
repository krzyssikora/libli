# Callout Task/Zadanie Kind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth `CalloutElement` kind — stored `"task"`, labelled "Task" / "Zadanie" — with a magenta accent and a Lucide pencil icon.

**Architecture:** One new `TextChoices` member drives everything. The editor `<select>`, the transfer validator, and `KIND_DEFAULT_HEADING` are all data-driven off the enum and need no code change; the only hand-written additions are one icon branch, two CSS declarations, and the test/catalog/doc updates that keep the existing normative lists honest.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + pytest-django + pytest-xdist, Playwright (e2e), ruff, Django i18n (`makemessages`/`compilemessages`), `uv` for all tooling.

**Spec:** `docs/superpowers/specs/2026-08-08-callout-task-kind-design.md` — read it before starting. It carries the rationale for every non-obvious instruction below.

## Global Constraints

- **`FORMAT_VERSION` stays at 9.** Do not bump it; do not edit any `FORMAT_VERSION` assertion in any test. (Spec D2.)
- **No model comment is added** by this change. (Spec D1 / §8.)
- **Every tool call goes through `uv run`** — ruff, pytest and `manage.py` are not on PATH.
- **Start the test DB before any pytest run:** `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. If it is down the suite looks hung for ~4m21s before erroring.
- **`uv run ruff format .` runs LAST**, after every other edit in the whole plan (Task 8). Running it earlier means running it twice.
- **Never run the whole test suite.** Each task runs only its own files; Task 8 runs the 12-file DoD 3 floor twice (baseline and post-mutant). **That floor plus CI is the branch gate** — the whole-repo sweep is CI's job, not a step in this plan. `scripts/affected_tests.py` may be used to widen the floor from the diff if you want extra assurance, but it is optional and the floor is the requirement.
- **`-m e2e` is mandatory** for any e2e file, or pytest silently deselects and exits 5.
- Stored value is `"task"`; English label `"Task"`; Polish `"Zadanie"`; light accent `#a8318f`; dark accent `#ee9fd8`.

---

### Task 1: Model enum member + migration

**Files:**
- Modify: `courses/models.py` (the `CalloutElement.Kind` class and the `CalloutElement` docstring)
- Create: `courses/migrations/0056_alter_calloutelement_kind.py` (generated, not hand-written)
- Test: `courses/tests/test_callout_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CalloutElement.Kind.TASK` with value `"task"` and label `"Task"`. Every later task depends on this member existing. `KIND_DEFAULT_HEADING["task"]` becomes `"Task"` automatically — it is built at module level from `Kind` *after* the class body, so it needs no edit.

- [ ] **Step 1: Write the failing test**

Extend the existing function in `courses/tests/test_callout_model.py` — do **not** add a new one:

```python
def test_display_heading_falls_back_to_kind_default():
    # gettext_lazy under the EN catalog renders the English label.
    assert str(CalloutElement(kind="example").display_heading) == "Example"
    assert str(CalloutElement(kind="note").display_heading) == "Note"
    assert str(CalloutElement(kind="tip").display_heading) == "Tip"
    assert str(CalloutElement(kind="warning").display_heading) == "Important"
    assert str(CalloutElement(kind="task").display_heading) == "Task"
```

This resolves to English regardless of catalog state: `conftest.py` pins the active language to `settings.LANGUAGE_CODE` (`"en"`) around every test, so Task 7 is not a prerequisite.

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest courses/tests/test_callout_model.py::test_display_heading_falls_back_to_kind_default -v
```

Expected: FAIL. `CalloutElement(kind="task").display_heading` falls through `KIND_DEFAULT_HEADING.get(...)` to the `"example"` default, so the assertion reads `'Example' == 'Task'`.

- [ ] **Step 3: Add the enum member**

In `courses/models.py`, inside `class Kind(models.TextChoices)`, append after the `WARNING` line:

```python
        TASK = "task", _("Task")
```

Leave the `WARNING` value and its two-line guard comment exactly as they are.

- [ ] **Step 4: Update the class docstring**

In the same class, change `(Example/Note/Tip/Important)` to `(Example/Note/Tip/Important/Task)`.

- [ ] **Step 5: Run test to verify it passes**

```
uv run pytest courses/tests/test_callout_model.py -v
```

Expected: PASS (all tests in the file).

- [ ] **Step 6: Generate the migration**

```
uv run python manage.py makemigrations courses
```

Expected: creates `courses/migrations/0056_alter_calloutelement_kind.py` containing a single `AlterField` on `calloutelement.kind`. Confirm the number by listing `courses/migrations/` — the current head is `0055_beforeafterelement_alter_element_content_type`. Do **not** hand-write this file, and do **not** use `showmigrations` to check the head (it reports *applied* state and needs a live DB).

The SQL is a no-op — Django never emits a PG CHECK for `choices` — but the migration is required: `choices` is part of the field's deconstruction, and CI runs `makemigrations --check --dry-run`.

- [ ] **Step 7: Verify no migration is outstanding**

```
uv run python manage.py makemigrations --check --dry-run
```

Expected: exit 0, "No changes detected".

- [ ] **Step 8: Commit**

```bash
git add courses/models.py courses/migrations/0056_alter_calloutelement_kind.py courses/tests/test_callout_model.py
git commit -m "feat(callout): add the Task kind to CalloutElement.Kind"
```

---

### Task 2: Pencil icon branch + render tests

**Files:**
- Modify: `templates/courses/elements/_callout_icon.html`
- Test: `courses/tests/test_callout_render.py`

**Interfaces:**
- Consumes: `CalloutElement.Kind.TASK` from Task 1.
- Produces: a `task` branch in the icon chain. The pencil's distinguishing path data is `m15 5 4 4`; later tasks do not depend on it.

- [ ] **Step 1: Write the three failing tests**

Append to `courses/tests/test_callout_render.py`:

```python
def test_persisted_task_callout_renders_kind_class():
    # No django_db decorator needed: this module already sets
    # `pytestmark = pytest.mark.django_db` at :5. (test_callout_transfer.py is the
    # one callout module that marks per-test -- see Task 6.)
    #
    # PERSISTED deliberately: the template interpolates el.kind directly, so an
    # unsaved instance renders callout--task even with the enum member absent.
    # Only save()'s coercion (task -> example) makes the mutant bite.
    el = CalloutElement.objects.create(kind="task", body="<p>hi</p>")
    html = el.render()
    assert "callout--task" in html


def test_task_render_emits_pencil_icon():
    html = CalloutElement(kind="task", body="").render()
    # The path is the pencil's distinguishing geometry...
    assert "m15 5 4 4" in html
    # ...and the chip must still be styled and hidden from assistive tech.
    # NOTE: these two do NOT fall to the delete-the-elif mutant -- the {% else %}
    # book-open SVG carries the identical class and aria-hidden. They have their
    # own mutant in Task 8 Step 4 ("strip aria-hidden in the task branch only").
    assert 'class="callout__icon"' in html
    assert 'aria-hidden="true"' in html


def test_example_render_does_not_emit_pencil_icon():
    # Guards against putting the pencil in the {% else %} fallback, which serves
    # `example` -- that mistake leaves the previous test green.
    html = CalloutElement(kind="example", body="").render()
    assert "m15 5 4 4" not in html
```

- [ ] **Step 2: Run them to verify they fail**

```
uv run pytest courses/tests/test_callout_render.py -v
```

Expected: `test_persisted_task_callout_renders_kind_class` PASSES already (Task 1 landed, so `save()` no longer coerces) — that is fine and expected at this point; its mutant is the enum member, verified in Task 8. The two icon tests FAIL: the render falls through to the book-open `{% else %}`, so `m15 5 4 4` is absent.

- [ ] **Step 3: Add the icon branch**

In `templates/courses/elements/_callout_icon.html`, insert immediately **before** the `{% else %}` line:

```
{% elif el.kind == "task" %}
  <svg class="callout__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>
```

Match the existing branches exactly: one line per `<svg>`, same attribute order.

- [ ] **Step 4: Update the stale comment**

In `courses/tests/test_callout_render.py`, line ~22, change "The four kinds emit four distinct icon markers" to "The five kinds emit five distinct icon markers".

- [ ] **Step 5: Run tests to verify they pass**

```
uv run pytest courses/tests/test_callout_render.py -v
```

Expected: PASS, all tests in the file.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/elements/_callout_icon.html courses/tests/test_callout_render.py
git commit -m "feat(callout): render the pencil icon for the Task kind"
```

---

### Task 3: Accent CSS + stylesheet tests

**Files:**
- Modify: `courses/static/courses/css/courses.css` (the header comment at ~:1774 and the per-kind blocks at ~:1849-1857)
- Test: `tests/test_callout_css.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `.callout--task` (`#a8318f`) and `[data-theme="dark"] .callout--task` (`#ee9fd8`). Task 4 recomputes both hexes out of this file, so the values must match exactly.

- [ ] **Step 1: Write the two failing tests**

The file currently opens with `from pathlib import Path`. Ruff's isort (`I` is selected,
`force-single-line = true`) puts plain `import x` **above** `from x import y` in the stdlib
section, so the import block must end up exactly:

```python
import re
from pathlib import Path
```

Then append:

```python
def test_callout_task_light_accent_is_pinned():
    css = CSS.read_text(encoding="utf-8")
    # ^-anchored: without it this pattern also matches inside the dark selector,
    # so deleting the light rule would leave the test green.
    assert re.search(
        r"^\.callout--task\s*\{\s*--callout-accent:\s*#a8318f", css, re.M
    ), "light .callout--task accent missing or changed"


def test_callout_task_dark_accent_is_pinned():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(
        r'^\[data-theme="dark"\]\s+\.callout--task\s*\{\s*--callout-accent:\s*#ee9fd8',
        css,
        re.M,
    ), "dark .callout--task accent missing or changed"
```

Also append `".callout--task"` to the existing class list in `test_courses_css_defines_callout_element`. That is **additive only** — it is the bare-substring form these two regexes exist to replace, and it cannot fail the light-rule mutant on its own.

- [ ] **Step 2: Run them to verify they fail**

```
uv run pytest tests/test_callout_css.py -v
```

Expected: all three FAIL (two regexes find nothing; the class-list loop asserts the missing `.callout--task`).

- [ ] **Step 3: Add the accent rules**

In `courses/static/courses/css/courses.css`, extend the two existing blocks so they read exactly:

```css
.callout--example { --callout-accent: #2563c9; }
.callout--note    { --callout-accent: #55606b; }
.callout--tip     { --callout-accent: #1f8a52; }
.callout--warning { --callout-accent: #b06f0f; }
.callout--task    { --callout-accent: #a8318f; }

[data-theme="dark"] .callout--example { --callout-accent: #7db0f7; }
[data-theme="dark"] .callout--note    { --callout-accent: #aabac8; }
[data-theme="dark"] .callout--tip     { --callout-accent: #5cd193; }
[data-theme="dark"] .callout--warning { --callout-accent: #e8b761; }
[data-theme="dark"] .callout--task    { --callout-accent: #ee9fd8; }
```

**Two placement rules, both load-bearing** (Task 4's drift check depends on them):
1. The light rule must appear **before** the dark block. That check's light pass is unanchored and takes the first match in the file; `[data-theme="dark"] .callout--task {` contains `.callout--task {` as a substring.
2. Align padding only **before** the `{`. Never insert extra spaces between `]` and `.callout--task` — the dark pass matches an `re.escape`'d single space there.

- [ ] **Step 4: Update the block's header comment**

At ~:1774, change `(Example / Note / Tip / Important)` to `(Example / Note / Tip / Important / Task)`. This site is easy to miss — it is ~74 lines above the rules you just edited, and it contains neither the word "four" nor the unspaced label form, so neither stale-prose grep finds it.

- [ ] **Step 5: Run tests to verify they pass**

```
uv run pytest tests/test_callout_css.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_callout_css.py
git commit -m "feat(callout): magenta accent for the Task kind, light and dark"
```

---

### Task 4: Normative surface list

**Files:**
- Modify: `tests/test_text_colour_css.py` (docstring line 2, comment lines ~20-21, both surface dicts, the kind tuple at ~:126, plus one new function)

**Interfaces:**
- Consumes: the two accent hexes from Task 3 and `CalloutElement.Kind` from Task 1.
- Produces: nothing downstream.

**Why this task exists:** the file's own header says *"The surface list is the specification"*. A fifth kind is a new ground rich text can sit on. Skipping this task is **silent** — see Step 1.

- [ ] **Step 1: Write the failing membership test**

Append to `tests/test_text_colour_css.py`:

```python
def test_every_callout_kind_has_a_ground_in_both_surface_lists():
    # Derived from the enum, NOT a second hardcoded list: that is what makes a
    # sixth kind fail loudly here instead of silently escaping the AA sweep.
    from courses.models import CalloutElement

    expected = {f"callout-{value}" for value in CalloutElement.Kind.values}
    for name, surfaces in (("LIGHT", LIGHT_SURFACES), ("DARK", DARK_SURFACES)):
        got = {k for k in surfaces if not k.startswith("--")}
        assert got == expected, (
            f"{name}_SURFACES callout grounds drifted: {got ^ expected}"
        )
```

The assertion message is pre-wrapped deliberately: on one line it is 92 characters, over
ruff's default 88 (`pyproject.toml` selects `E` and sets no `line-length` override), which
would fail `ruff check .` in Task 8.

This closes a hole the drift loop cannot: adding the dict entries but forgetting the tuple at `:126` is green (the loop skips the kind), and forgetting **both** is also green. Only the reverse partial reddens.

- [ ] **Step 2: Run it to verify it fails**

```
uv run pytest tests/test_text_colour_css.py::test_every_callout_kind_has_a_ground_in_both_surface_lists -v
```

Expected: FAIL — `LIGHT_SURFACES callout grounds drifted: {'callout-task'}`.

- [ ] **Step 3: Add both grounds**

Add to `LIGHT_SURFACES`, after `"callout-warning"`:

```python
    "callout-task": "#FAF3F8",
```

Add to `DARK_SURFACES`, after `"callout-warning"`:

```python
    "callout-task": "#383030",
```

These are `color-mix(in srgb, <accent> 6%, --surface-raised)` with per-channel `round()` — `#a8318f` over `#FFFFFF` and `#ee9fd8` over `#2C2925`. The drift test recomputes them from `courses.css`, so a typo here fails Step 5 rather than passing silently.

- [ ] **Step 4: Add the kind to the drift loop and fix both counts**

At ~:126, change:

```python
        for kind in ("example", "note", "tip", "warning"):
```

to:

```python
        for kind in ("example", "note", "tip", "warning", "task"):
```

Docstring line 2: "which is ten surfaces, not two" → "which is eleven surfaces, not two".
Comment line ~20: "recomputes the four callout grounds from courses.css" → "the five callout grounds".

- [ ] **Step 5: Run the whole file to verify it passes**

```
uv run pytest tests/test_text_colour_css.py -v
```

Expected: PASS. The AA sweep now measures all four `--tc-*` slots against the two new grounds; the binding case is `--tc-red` `#EA8A82` on `#383030` at 5.18:1, clear of the 4.5:1 threshold, so nothing should redden.

- [ ] **Step 6: Commit**

```bash
git add tests/test_text_colour_css.py
git commit -m "test(callout): register the Task grounds in the normative surface list"
```

---

### Task 5: Editor form coverage

**Files:**
- Test: `courses/tests/test_callout_authoring.py` (no production file changes — the form and template are data-driven)

**Interfaces:**
- Consumes: `Kind.TASK` from Task 1.
- Produces: nothing downstream.

**Why this task exists:** the kind `<select>` is the only surface through which an author can reach this feature, and **no existing test iterates `CalloutElement.Kind` or the form's choices** — the authoring tests all hardcode `"warning"`.

- [ ] **Step 1: Write the two failing tests**

Append to `courses/tests/test_callout_authoring.py`:

```python
def test_edit_form_offers_the_task_kind(client):
    # Fixture kind is deliberately NOT task: a task-kind callout would render
    # <option value="task" selected> and fail this exact-string assert.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el = CalloutElement.objects.create(kind="example", heading="", body="")
    join = Element.objects.create(unit=unit, content_object=el)
    resp = client.get(
        reverse(
            "courses:manage_element_form",
            kwargs={"slug": course.slug, "pk": join.pk},
        ),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    # Exact string: two separate `'value="task"' in html` / `'Task' in html`
    # asserts would both pass with the label wrong.
    assert '<option value="task">Task</option>' in resp.content.decode()


def test_save_round_trips_the_task_kind(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "callout",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "kind": "task",
            "heading": "",
            "body": "<p>x</p>",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    # Status first: without the enum member the form rejects the POST, nothing is
    # saved, and the .get() below raises DoesNotExist instead of asserting.
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert el.content_object.kind == "task"
```

The POST envelope (`type`, `element="new"`, `unit`, `unit_token`, `HTTP_X_REQUESTED_WITH`) mirrors `test_save_round_trips_kind_heading_body`. Omitting `unit_token` returns **409** from `_check_token`, which reads as a feature defect.

- [ ] **Step 2: Run them**

```
uv run pytest courses/tests/test_callout_authoring.py -v
```

Expected: PASS immediately — Task 1 already added the enum member, and the form/template are data-driven. These are regression pins, not red-first tests; their falsification is Task 8's enum-removal mutant.

- [ ] **Step 3: Commit**

```bash
git add courses/tests/test_callout_authoring.py
git commit -m "test(callout): pin the Task kind in the editor form and save path"
```

---

### Task 6: Transfer round trip

**Files:**
- Test: `courses/tests/test_callout_transfer.py` (no production changes — `_val_callout` reads `Kind.values`)

**Interfaces:**
- Consumes: `Kind.TASK` from Task 1.
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_callout_transfer.py`, mirroring `test_round_trip_preserves_fields`:

```python
@pytest.mark.django_db  # this module marks per-test; there is NO module pytestmark
def test_round_trip_preserves_the_task_kind():
    el = CalloutElement.objects.create(kind="task", heading="", body="<p>hi</p>")
    _model, ser = SERIALIZERS["callout"]

    class _Ids:
        def register(self, *a, **k):  # unused by callout
            return None

    data = ser(el, _Ids())
    assert data["kind"] == "task"
    VALIDATORS["callout"](data, "e1", set())
    rebuilt, _refs = BUILDERS["callout"](data, {})
    assert rebuilt.kind == "task"
```

**The payload must come from a persisted instance through `SERIALIZERS`** — not a hand-written `{"kind": "task"}` dict. With the enum reverted, `save()` coerces to `example` *before* serialization, so `_val_callout` **accepts** the payload and the test reddens on the equality assertion. A hand-written dict would instead raise `TransferError`, i.e. the opposite mechanism.

`FORMAT_VERSION` is untouched — do not edit any version assertion in this file or any other.

- [ ] **Step 2: Run it**

```
uv run pytest courses/tests/test_callout_transfer.py -v
```

Expected: PASS (regression pin; falsified in Task 8).

- [ ] **Step 3: Commit**

```bash
git add courses/tests/test_callout_transfer.py
git commit -m "test(callout): round-trip the Task kind through the transfer registries"
```

---

### Task 7: Catalogs, help manual, i18n tests

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`, `locale/en/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.mo`
- Modify: `docs/help/course-admin/content-editors.md` (~:116), `docs/help/course-admin/content-editors.pl.md` (~:125-126)
- Create: `tests/test_i18n_callout_task.py`

**Interfaces:**
- Consumes: `_("Task")` from Task 1 — extraction reads it out of the source, so Task 1 must already be committed.
- Produces: nothing downstream.

- [ ] **Step 1: Extract both catalogs**

```
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

Expect catalog-wide `#:` reference-line and `POT-Creation-Date` churn. That is normal extraction noise, not scope creep.

**Accepted downstream noise:** Task 8's `ruff format .` may reflow Python files after these `#:` line references were written, staling some of them. Nothing tests reference lines and the only cost is diff noise at the next extraction, so this is accepted rather than worked around — do not re-run `makemessages` after formatting just to refresh them, because that would undo the deliberate ordering in Step 3.

- [ ] **Step 2: Fix the entries and clear the fuzzy trap in BOTH catalogs**

`msgmerge` marks a new short msgid fuzzy in **both** catalogs, and `test_no_fuzzy_entries` iterates `CATALOGS = {"pl": PL_PO, "en": EN_PO}` — so a leftover flag in `en` reddens that guard just as surely as one in `pl`.

In `locale/pl/LC_MESSAGES/django.po`:

```po
msgid "Task"
msgstr "Zadanie"
```

In `locale/en/LC_MESSAGES/django.po`, leave the msgstr **empty** — that is the convention for the English catalog and why `test_pl_has_no_untranslated_msgid` is pl-scoped:

```po
msgid "Task"
msgstr ""
```

**In both files** delete the `#, fuzzy` flag line **and** the `#| msgid "..."` reference line. Deleting only the flag leaves a wrong-but-non-empty translation that no po-health guard can see — that is exactly the failure Testing row 9 exists to catch.

- [ ] **Step 3: Compile**

```
uv run python manage.py compilemessages
```

Both `.mo` files are tracked in git and **CI has no `compilemessages` step**, so the committed binary is what CI reads. Regenerating without staging it is green locally and red in CI.

- [ ] **Step 4: Write the two i18n tests**

Create `tests/test_i18n_callout_task.py`:

```python
"""Pins the Polish label and the English catalog entry for the Callout Task kind.

No django_db mark: the CalloutElement is never saved.
"""

from django.utils import translation

from courses.models import CalloutElement
from tests.test_i18n_po_health import EN_PO
from tests.test_i18n_po_health import _entries


def test_task_kind_renders_zadanie_in_polish():
    # override(), NOT activate(): a bare activate leaks the language into every
    # later test in this xdist worker.
    with translation.override("pl"):
        assert str(CalloutElement(kind="task").display_heading) == "Zadanie"


def test_en_catalog_has_the_task_msgid():
    # _entries() returns dicts, and it RETAINS obsolete entries with a flag rather
    # than dropping them -- so the `not e["obsolete"]` filter is what makes "live"
    # in the message below actually true. Without it a commented-out
    # `#~ msgid "Task"` block would count, exactly like a raw substring search.
    matches = [
        e for e in _entries(EN_PO) if e["msgid"] == "Task" and not e["obsolete"]
    ]
    assert len(matches) == 1, "expected exactly one live `Task` entry in locale/en"
    assert matches[0]["msgstrs"] == [""], "the en catalog entry must stay empty"
```

`_entries()` appends plain dicts with keys `msgid`, `msgstrs`, `fuzzy`, `obsolete`, `plural` (`tests/test_i18n_po_health.py:95-103`) — verified, use them as written.

- [ ] **Step 5: Run the i18n tests**

```
uv run pytest tests/test_i18n_callout_task.py tests/test_i18n_po_health.py -v
```

Expected: PASS. `test_i18n_po_health` must report 0 fuzzy / 0 obsolete / 0 untranslated.

- [ ] **Step 6: Update both help manuals**

`docs/help/course-admin/content-editors.md` (~:116): "Choose a **Kind** (Example, Note, Tip, or Important —" becomes "Choose a **Kind** (Example, Note, Tip, Important, or Task —".

`docs/help/course-admin/content-editors.pl.md`: **the phrase is wrapped across two physical lines**, so a single-line find-and-replace will not match. Lines 125-126 currently read:

```
wyróżnić na tle otaczającego tekstu. Wybierz **Rodzaj** (Przykład, Notatka,
Wskazówka lub Ważne — każdy z własnym kolorem akcentu i ikoną), opcjonalny
```

Replace those two lines with:

```
wyróżnić na tle otaczającego tekstu. Wybierz **Rodzaj** (Przykład, Notatka,
Wskazówka, Ważne lub Zadanie — każdy z własnym kolorem akcentu i ikoną), opcjonalny
```

The final item must match the `Zadanie` msgstr exactly.

Keep both edits **inside** the existing `{el:callout}` paragraph — `core/help.py:89` parses it positionally with `<p>\s*\{el:slug\}\s*(.*?)</p>`, and `tests/test_help.py` renders every doc.

- [ ] **Step 7: Run the help tests**

```
uv run pytest tests/test_help.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo \
        locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo \
        docs/help/course-admin/content-editors.md \
        docs/help/course-admin/content-editors.pl.md \
        tests/test_i18n_callout_task.py
git commit -m "i18n(callout): Zadanie for the Task kind, plus help manual entries"
```

---

### Task 8: Falsification, screenshots, and the branch gate

**Files:**
- Create (temporarily, then delete): `tests/test_e2e_callout_kinds_shot.py`
- Modify: `docs/superpowers/plans/2026-07-27-internal-link-cutover.md`
- Create: `<SCRATCHPAD>/pr-body-note.md`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: the verified branch, plus the PR-body paragraph the pipeline's PR phase copies verbatim.

This task is the spec's Definition of Done. **Do not skip a step because an earlier task was green** — several of these checks exist precisely because the earlier green was not evidence.

- [ ] **Step 1: Establish the combined green baseline**

Before mutating anything, prove the whole selection is green with the compiled `.mo` in place. Without this, a "must go RED" in Step 5 is not attributable — you would not know the test was green to begin with.

```
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
uv run pytest courses/tests/test_callout_model.py courses/tests/test_callout_render.py \
  courses/tests/test_callout_form.py courses/tests/test_callout_authoring.py \
  courses/tests/test_callout_transfer.py tests/test_callout_css.py \
  tests/test_text_colour_css.py tests/test_i18n_po_health.py \
  tests/test_i18n_callout_task.py tests/test_help.py \
  courses/tests/test_callout_editor_row.py courses/tests/test_callout_nesting_css.py
```

Expected: all PASS. This is the spec's DoD 3, and the baseline-before-mutants ordering is the point.

**The full executed order in this task is `6 → 3 → 7 → delete harness → 4 → 8 → 5`**, i.e. the screenshots (Steps 2-4) run *before* the mutants (Step 6), swapping the spec's `4 → 7`. That is a deliberate, safe reorder: the throwaway harness is then already deleted by the time the tree is deliberately damaged, so no mutant can interact with it and the linter never sees it. Everything else follows the spec's sequence.

- [ ] **Step 2: Write the screenshot harness**

Create `tests/test_e2e_callout_kinds_shot.py`. It needs **four** things carried over from `tests/test_e2e_html_element.py`, not two — copying only the helpers yields `NameError` and an async-unsafe ORM error:

```python
import os

import pytest

from tests.factories import TEST_PASSWORD          # used by _login
from tests.factories import make_verified_user     # used by _make_pa_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield
```

Then copy `_make_pa_user` and `_login` verbatim from that file.

Write `_seed_five_callout_unit(slug, viewer)` yourself. **Its contract, in full** — the access half is load-bearing, because `courses/views.py`'s `lesson_unit` calls `can_access_course`, which resolves to *enrolled OR `is_staff` OR owner* (`courses/access.py:32`), and `_make_pa_user` grants the `PLATFORM_ADMIN` **group**, which is model permissions, **not** `is_staff`. A course the viewer neither owns nor is enrolled in raises `PermissionDenied` and no screenshot is possible:

1. create the course with `owner=viewer` (simplest satisfying branch — an `Enrollment` for the viewer also works);
2. create a `ContentNode` lesson unit under it;
3. create five `CalloutElement`s, one per `CalloutElement.Kind.values`, each with a short body, and attach each via `Element.objects.create(unit=unit, content_object=el)`;
4. return the `courses:lesson_unit` path for that unit.

- [ ] **Step 3: Capture both themes, each with its own guard**

```python
@pytest.mark.django_db(transaction=True)
def test_capture_all_five_callout_kinds_dark(live_server, page):
    user = _make_pa_user("shot_dark")
    user.theme = "dark"      # authed User.theme wins -> deterministic baked data-theme
    user.save(update_fields=["theme"])
    url = _seed_five_callout_unit("shot-course-dark", user)
    _login(page, live_server, "shot_dark")
    page.goto(f"{live_server.url}{url}")
    # Prove the capture really is dark, or a light render passes as "the dark shot".
    assert page.locator("html[data-theme='dark']").count() == 1
    # ...and prove it is the RIGHT page. base.html bakes data-theme on EVERY page,
    # including the 403 lesson_unit raises on a course-access mistake, so the theme
    # guard alone would happily screenshot a page with zero callouts on it.
    page.wait_for_selector(".callout--task")
    assert page.locator(".callout").count() == 5
    page.screenshot(path=r"<SCRATCHPAD>/callout-kinds-dark.png", full_page=True)


@pytest.mark.django_db(transaction=True)
def test_capture_all_five_callout_kinds_light(live_server, page):
    user = _make_pa_user("shot_light")
    user.theme = "light"
    user.save(update_fields=["theme"])
    url = _seed_five_callout_unit("shot-course-light", user)
    _login(page, live_server, "shot_light")
    page.goto(f"{live_server.url}{url}")
    # The mirror guard, written out rather than left as "repeat with light": a
    # hardcoded 'dark' selector here would either fail or assert the wrong theme.
    assert page.locator("html[data-theme='light']").count() == 1
    page.wait_for_selector(".callout--task")
    assert page.locator(".callout").count() == 5
    page.screenshot(path=r"<SCRATCHPAD>/callout-kinds-light.png", full_page=True)
```

**Both must capture the STUDENT lesson-unit view, not the editor** — the glyph decision is scoped to the surface where no `✎` Edit affordance exists. Borrow the theme mechanism from the cited e2e file; do not borrow its editor destination.

Run it:

```
uv run pytest -m e2e tests/test_e2e_callout_kinds_shot.py -v
```

Without `-m e2e` the file silently deselects and pytest exits 5, which reads as success.

- [ ] **Step 4: Judge both screenshots and surface them**

Write the PNGs to the session scratchpad, **not** the repo.

**This step has a named actor and a deterministic outcome — it is not "show someone and hope".** This plan is executed autonomously, so "show it to the human" alone would silently no-op, and DoD 7 is the *only* evidence behind the whole magenta decision. Concretely:

1. **`Read` both PNGs yourself.** You can see images; do not delegate the judgement to a human who may not be at the keyboard.
2. **Record an explicit verdict per theme** — light and dark separately — against each criterion, in the run log:
   - (a) the five accents are mutually distinguishable at the real 3px spine and 18px chip — in particular the task chip must not read as a shade of Tip's green or as severity next to Important's amber (the two failure modes that eliminated teal and rose);
   - (b) the 0.75rem/700 uppercase eyebrow is legible against its tint;
   - (c) the icon is identifiable as a pencil at 18px.
3. **Surface both images to the human** as well, and say which verdict you recorded. Confirmation is solicited, but **the run proceeds on your recorded verdict** — an unanswered prompt is not a failure and not a pass, it is simply not a gate.
4. **On a fail against any criterion, take the accent-change branch below.** Do not proceed to the mutants with a failed DoD 7.

**Accent-change branch (only if step 4 fires).** Edit sites: the light rule, the dark rule, both `test_text_colour_css.py` surface entries, the two regex hex literals in `tests/test_callout_css.py`, and **every hex and ratio in spec §4 and §5** — including the icon-chip paragraph (`#EFD8E9` / `#514048`, 4.48:1 / 4.86:1) and the spine-adjacency paragraph (5.32:1 / 8.92:1), neither of which sits in a table.

Then **loop back, or the contingency terminates in an edit list rather than a verified state**:

1. recompute both `callout-task` grounds through `test_text_colour_css.py`'s own `_mix()` with the new accent, and recompute every affected ratio with the WCAG formula in spec §4;
2. re-run `uv run pytest tests/test_callout_css.py tests/test_text_colour_css.py`;
3. re-capture both themes (Step 3) and re-judge them (this step) before continuing.

- [ ] **Step 5: Delete the capture harness**

```bash
rm tests/test_e2e_callout_kinds_shot.py
```

Delete it **now**, before the ruff step, so the linter never has to pass over a throwaway file.

- [ ] **Step 6: Falsify every test against its named mutant**

Run each mutant with **only its named test selected**, and **always name the owning file** — a bare `-k` still collects every module in the repo, fourteen times over. Revert each mutant before the next.

| Mutant | Command | Must go RED |
|---|---|---|
| remove `TASK` from `Kind` | `uv run pytest courses/tests/test_callout_model.py -k test_display_heading_falls_back_to_kind_default` | ✓ |
| remove `TASK` from `Kind` | `uv run pytest courses/tests/test_callout_render.py -k test_persisted_task_callout_renders_kind_class` | ✓ (save() coerces to example) |
| remove `TASK` from `Kind` | `uv run pytest courses/tests/test_callout_authoring.py -k test_edit_form_offers_the_task_kind` | ✓ |
| remove `TASK` from `Kind` | `uv run pytest courses/tests/test_callout_authoring.py -k test_save_round_trips_the_task_kind` | ✓ |
| remove `TASK` from `Kind` | `uv run pytest courses/tests/test_callout_transfer.py -k test_round_trip_preserves_the_task_kind` | ✓ (equality, not TransferError) |
| remove `TASK` from `Kind` | `uv run pytest tests/test_text_colour_css.py -k test_every_callout_kind_has_a_ground_in_both_surface_lists` | ✓ |
| delete the `{% elif el.kind == "task" %}` branch | `uv run pytest courses/tests/test_callout_render.py -k test_task_render_emits_pencil_icon` | ✓ (path assertion only) |
| **strip `aria-hidden="true"` from the NEW task branch only** | `uv run pytest courses/tests/test_callout_render.py -k test_task_render_emits_pencil_icon` | ✓ — this is the mutant for the `class=` / `aria-hidden` assertions, which the delete-the-elif mutant leaves green because the `{% else %}` book-open SVG carries both identically |
| move the pencil into the `{% else %}` fallback | `uv run pytest courses/tests/test_callout_render.py -k test_example_render_does_not_emit_pencil_icon` | ✓ |
| delete the light `.callout--task` rule | `uv run pytest tests/test_callout_css.py -k test_callout_task_light_accent_is_pinned` | ✓ |
| delete the dark `.callout--task` rule | `uv run pytest tests/test_callout_css.py -k test_callout_task_dark_accent_is_pinned` | ✓ |
| change either accent hex in `courses.css` | `uv run pytest tests/test_text_colour_css.py -k test_surface_literals_still_match_the_css` | ✓ |
| omit both `callout-task` surface entries | `uv run pytest tests/test_text_colour_css.py -k test_every_callout_kind_has_a_ground_in_both_surface_lists` | ✓ |
| delete the `en` `Task` entry | `uv run pytest tests/test_i18n_callout_task.py -k test_en_catalog_has_the_task_msgid` | ✓ |
| set `msgstr "Task"` in the `en` catalog | `uv run pytest tests/test_i18n_callout_task.py -k test_en_catalog_has_the_task_msgid` | ✓ |

**The Polish mutant needs a compile step or it is a no-op** — the test reads the compiled `.mo`, not the `.po`:

```bash
# edit locale/pl/LC_MESSAGES/django.po -> msgstr "Wskazówka"
uv run python manage.py compilemessages
uv run pytest tests/test_i18n_callout_task.py -k test_task_kind_renders_zadanie_in_polish   # RED
# restore the .po
uv run python manage.py compilemessages                                                      # do NOT skip
```

- [ ] **Step 7: Verify every mutant is reverted**

Check **only the mutated paths**, not the whole tree — Step 8's runbook edit and Step 9's PR-body file are legitimately pending at this point, so a bare `git status` cannot distinguish "a mutant survived" from "expected work in progress":

```bash
git diff -- courses/models.py \
            templates/courses/elements/_callout_icon.html \
            courses/static/courses/css/courses.css \
            tests/test_text_colour_css.py \
            locale/
```

Expected: **empty**. Anything here is a surviving mutant.

- [ ] **Step 8: Add the operational note to the cutover runbook**

Append to `docs/superpowers/plans/2026-07-27-internal-link-cutover.md`, under a clear heading:

> **Callout Task kind — sequencing constraint.** Do not author a Task callout in mat-pp until PROD is running code that contains the `TASK` enum member. `FORMAT_VERSION` was deliberately not bumped, so an archive containing a Task callout fails on an older PROD at that element with "unknown callout kind", which does not name the version as the cause. The gate is the **deployed code**, not migration `0056` (a state-only `AlterField` whose SQL is a no-op).

This file is a **live runbook** despite living under `docs/superpowers/plans/` — it is the artifact the cutover operator actually opens.

- [ ] **Step 9: Write the PR-body paragraph to a file the PR phase can copy**

The spec's DoD 8 requires this note in **two** places, both mandatory. Step 8 covered the runbook; this covers the PR body. Write the exact text to `<SCRATCHPAD>/pr-body-note.md` so the PR-opening phase copies a file rather than reconstructing it from memory:

```markdown
## Operational constraint for the mat-pp cutover

`FORMAT_VERSION` is deliberately **not** bumped by this PR (see the spec's D2: the version
gate is archive-wide, and the repo's encoded rule is that a new element *type* has never
bumped it). The consequence: an archive containing a Task callout will fail to import on a
PROD that predates this build, at that element, with "unknown callout kind" — a message that
does not name the version as the cause.

**Do not author a Task callout in mat-pp until PROD is running code containing the `TASK`
enum member.** The gate is the deployed code, not migration `0056` (a state-only `AlterField`
whose SQL is a no-op). Archives without a Task callout are unaffected.
```

Then **echo the resolved absolute path of that file into the run log**. The scratchpad is
session-specific, so a relative mention is not a durable pointer, and Step 14 is the only
consumer.

- [ ] **Step 10: Verify the stale-prose sweep is still complete**

The spec turns a verification procedure into this plan's fixed list of update sites; run the sweep to confirm master has not added a new one under the branch:

**The three greps have three different expected outputs. "Zero hits" is the wrong gate for two of them** — grep #2 in particular returns the very sites this plan updates, so reading it as "anything found is a miss" would flag correct work.

```bash
# 1 -- count statements. Case-sensitive, so "FOURTH" does not appear.
grep -rn "four" --include=*.py --include=*.html --include=*.css --include=*.md . | grep -i callout
```

Expected outside `docs/superpowers/`: **exactly one** hit, `tests/test_e2e_callout_container.py:4` ("These four tests…"), which counts tests, not kinds. `courses/tests/test_callout_render.py:22` and `tests/test_text_colour_css.py:20` must have already been rewritten to "five" by Tasks 2 and 4 and so must **not** appear. Anything else is a missed site.

```bash
# 2 -- the label sequence. These are UPDATE sites, not misses.
grep -rEn "Note\s*[/,]\s*Tip" --include=*.py --include=*.html --include=*.css --include=*.md .
```

Expected outside `docs/superpowers/`: **exactly three** hits, and the check is *"does each one already contain `Task`"* — not "are there zero":

| Hit | Must read |
|---|---|
| `courses/models.py:458` | `(Example/Note/Tip/Important/Task)` |
| `courses/static/courses/css/courses.css:1775` | `(Example / Note / Tip / Important / Task)` |
| `docs/help/course-admin/content-editors.md:116` | `(Example, Note, Tip, Important, or Task` |

A fourth hit is a missed site. A listed hit lacking `Task` is an incomplete edit.

```bash
# 3 -- the Polish sequence. Line-scoped.
grep -rEn "Notatka.*Wskazówka" --include=*.md .
```

Expected **before** Task 7: nothing outside `docs/superpowers/`, because `content-editors.pl.md` wraps the phrase across lines 125-126. **After** Task 7's rewrite a hit on `content-editors.pl.md` is **expected and correct** if the rewrap puts both words on one line — verify it reads `Przykład, Notatka, Wskazówka, Ważne lub Zadanie`, and treat its absence as equally fine (the phrase may still be wrapped).

- [ ] **Step 11: Lint, format, and COMMIT THE RESULT**

```
uv run ruff check .
uv run ruff format .
```

**Then commit whatever the formatter touched, together with the runbook.** This is not optional bookkeeping: Tasks 1-7 each committed their files *before* the formatter ever ran, so without this step the working tree is formatted while `HEAD` is not. Step 12's `ruff format --check .` inspects the **working tree** and would pass, while CI (`.github/workflows/ci.yml:20-21`) runs the same check against the **pushed commit** and fails, with nothing in the diff to explain it. The same hole would swallow any `.mo` byte change from a recompile.

```bash
git add -u
git add docs/superpowers/plans/2026-07-27-internal-link-cutover.md
git status            # confirm nothing unexpected is staged, and NOTHING is left unstaged
git commit -m "chore(callout): formatting pass and the cutover sequencing note"
```

- [ ] **Step 12: Re-verify green on the committed tree**

```
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
uv run python manage.py compilemessages
uv run pytest courses/tests/test_callout_model.py courses/tests/test_callout_render.py \
  courses/tests/test_callout_form.py courses/tests/test_callout_authoring.py \
  courses/tests/test_callout_transfer.py tests/test_callout_css.py \
  tests/test_text_colour_css.py tests/test_i18n_po_health.py \
  tests/test_i18n_callout_task.py tests/test_help.py \
  courses/tests/test_callout_editor_row.py courses/tests/test_callout_nesting_css.py
```

Expected: all PASS. This is the spec's DoD 4b and is **not** redundant with Step 1 — Step 6 deliberately damaged shipped artifacts, and none of the closing gates below can see a missing CSS rule, a missing template branch, or a stale compiled `.mo`.

If `compilemessages` changed a `.mo` byte, commit it now — Step 13 requires an empty working tree, so this branch must be executed exactly:

```bash
git add locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.mo
git commit -m "chore(i18n): recompile catalogs after the falsification pass"
```

- [ ] **Step 13: Closing gates**

```
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run ruff format --check .
git status --short
```

Expected: the three commands clean, and `git status --short` **empty** — an empty working tree is what proves the checked tree and the committed tree are the same one.

- [ ] **Step 14: Hand the PR-body note to the PR-opening phase**

**When the PR is opened, paste the full contents of `<SCRATCHPAD>/pr-body-note.md` into the PR body verbatim, under its own heading.**

This step exists because Step 9 had a producer and no consumer. DoD 8 requires the constraint in *two* places and argues explicitly that a note no artifact carries is not communicated at all — a file written to a session scratchpad that nobody is instructed to read reproduces exactly that failure one level down. The runbook half (Step 8) is committed and safe; this half is not, until it is pasted.

## Self-Review

**Spec coverage.** §1 model → Task 1. §2 migration → Task 1 (Steps 6-7). §3 render → Task 2. §4 CSS + header comment → Task 3. §5 surface list → Task 4. §6 editor → Task 5. §7 transfer → Task 6. §8 i18n + help → Task 7. Testing rows 1-11 → Tasks 2-7, falsified in Task 8 Step 6. DoD 1-2 → Task 8 Step 13. DoD 3 → Task 8 Step 1 (baseline, before the mutants — the spec's `6 → 3 → 4` order). DoD 4 → Step 6. DoD 4b → Step 12. DoD 5 → Step 11. DoD 6 → Task 7 Steps 1-3. DoD 7 → Task 8 Steps 2-4. DoD 8 → **both halves**: Step 8 (runbook) and Step 9 (the PR-body paragraph written verbatim to the scratchpad, so the PR phase copies a file rather than reconstructing it). The `courses/views.py:187` do-not-change entry is honoured by no task touching that file, and Step 10 re-runs the spec's three prescribed greps so the fixed site list is verified rather than trusted.

**Placeholders.** One deliberate `<SCRATCHPAD>` token (a session-specific path, not knowable at plan time) and one named-but-unwritten helper, `_seed_five_callout_unit`, whose contract is now stated in full as a four-point list in Task 8 Step 2 — including the course-access requirement, without which `lesson_unit` raises `PermissionDenied` and no screenshot is possible. `_entries()`'s return shape is verified (plain dicts, keys `msgid`/`msgstrs`/`fuzzy`/`obsolete`/`plural`) and used as such; the earlier "verify the attribute names yourself" hedge is gone.

**Commit integrity.** Every file the formatter touches is committed in Step 11, *before* Step 13's `ruff format --check .`, and Step 13 additionally asserts `git status --short` is empty. That pairing is what makes the checked tree and the pushed tree provably the same one — a `--check` that passes against a working tree while `HEAD` holds unformatted source is the failure mode this guards.

**Type consistency.** Test function names are identical between the task that creates them and Task 8's mutant table: `test_persisted_task_callout_renders_kind_class`, `test_task_render_emits_pencil_icon`, `test_example_render_does_not_emit_pencil_icon`, `test_callout_task_light_accent_is_pinned`, `test_callout_task_dark_accent_is_pinned`, `test_every_callout_kind_has_a_ground_in_both_surface_lists`, `test_edit_form_offers_the_task_kind`, `test_save_round_trips_the_task_kind`, `test_round_trip_preserves_the_task_kind`, `test_task_kind_renders_zadanie_in_polish`, `test_en_catalog_has_the_task_msgid`. The accent hexes `#a8318f` / `#ee9fd8` and the grounds `#FAF3F8` / `#383030` agree across Tasks 3, 4 and 8.
