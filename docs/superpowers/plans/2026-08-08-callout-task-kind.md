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
- **Never run the whole test suite.** Each task runs only its own files. The branch-wide selection is Task 8's job.
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
@pytest.mark.django_db
def test_persisted_task_callout_renders_kind_class():
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

Add `import re` at the top of `tests/test_callout_css.py`, then append:

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
        assert got == expected, f"{name}_SURFACES callout grounds drifted: {got ^ expected}"
```

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

- [ ] **Step 2: Fix the Polish entry and clear the fuzzy trap**

Find `msgid "Task"` in `locale/pl/LC_MESSAGES/django.po`. `msgmerge` will likely have pre-filled it from a similar short msgid and marked it fuzzy. Set the translation and delete **both** metadata lines:

```po
msgid "Task"
msgstr "Zadanie"
```

Delete the `#, fuzzy` flag line **and** the `#| msgid "..."` reference line. Deleting only the flag leaves a wrong-but-non-empty translation that no po-health guard can see.

In `locale/en/LC_MESSAGES/django.po`, leave `msgid "Task"` with an **empty** msgstr — that is the convention for the English catalog and why `test_pl_has_no_untranslated_msgid` is pl-scoped.

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
    # _entries() is obsolete-aware; a raw substring search would also match a
    # commented-out `#~ msgid "Task"` block and assert nothing about the msgstr.
    matches = [e for e in _entries(EN_PO) if e.msgid == "Task"]
    assert len(matches) == 1, "expected exactly one live `Task` entry in locale/en"
    assert matches[0].msgstrs == [""], "the en catalog entry must stay empty"
```

**Before writing this, open `tests/test_i18n_po_health.py`** and confirm the real names of `_entries` and the entry object's attributes (`msgid`, `msgstrs`). Adapt the two assertions to whatever that helper actually returns — the *shape* above is the requirement, the attribute names are to be verified, not assumed.

- [ ] **Step 5: Run the i18n tests**

```
uv run pytest tests/test_i18n_callout_task.py tests/test_i18n_po_health.py -v
```

Expected: PASS. `test_i18n_po_health` must report 0 fuzzy / 0 obsolete / 0 untranslated.

- [ ] **Step 6: Update both help manuals**

`docs/help/course-admin/content-editors.md` (~:116): "Choose a **Kind** (Example, Note, Tip, or Important —" becomes "Choose a **Kind** (Example, Note, Tip, Important, or Task —".

`docs/help/course-admin/content-editors.pl.md` (~:125-126): "Wybierz **Rodzaj** (Przykład, Notatka, Wskazówka lub Ważne —" becomes "Wybierz **Rodzaj** (Przykład, Notatka, Wskazówka, Ważne lub Zadanie —". The final item must match the `Zadanie` msgstr exactly.

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

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: the verified branch.

This task is the spec's Definition of Done. **Do not skip a step because an earlier task was green** — several of these checks exist precisely because the earlier green was not evidence.

- [ ] **Step 1: Capture the five-kind screenshots**

Create `tests/test_e2e_callout_kinds_shot.py`. Copy `_make_pa_user` and `_login` **verbatim** from `tests/test_e2e_html_element.py` (they are file-local helpers there, plus its `TEST_PASSWORD` import). Seed a course with a lesson unit holding one callout of **each of the five kinds**, then:

```python
@pytest.mark.e2e
@pytest.mark.django_db(transaction=True)
def test_capture_all_five_callout_kinds(live_server, page):
    user = _make_pa_user("shot_viewer")
    user.theme = "dark"      # authed User.theme wins -> deterministic baked data-theme
    user.save(update_fields=["theme"])
    url = _seed_five_callout_unit("shot-course", user)   # you write this helper
    _login(page, live_server, "shot_viewer")
    page.goto(f"{live_server.url}{url}")
    # Prove the capture really is dark, or a light render passes as "the dark shot".
    assert page.locator("html[data-theme='dark']").count() == 1
    page.screenshot(path=r"<SCRATCHPAD>/callout-kinds-dark.png", full_page=True)
```

Then repeat with `user.theme = "light"` for the light shot.

**It must be the STUDENT lesson-unit view, not the editor** — the glyph decision is scoped to the surface where no `✎` Edit affordance exists. Borrow the theme mechanism from the cited e2e files; do not borrow their editor destination.

Run it:

```
uv run pytest -m e2e tests/test_e2e_callout_kinds_shot.py -v
```

Without `-m e2e` the file silently deselects and pytest exits 5, which reads as success.

- [ ] **Step 2: Judge both screenshots and surface them**

Write the PNGs to the session scratchpad, **not** the repo. Show both to the human. Pass criteria, judged on each theme separately:

- (a) the five accents are mutually distinguishable at the real 3px spine and 18px chip — in particular the task chip must not read as a shade of Tip's green or as severity next to Important's amber;
- (b) the 0.75rem/700 uppercase eyebrow is legible against its tint;
- (c) the icon is identifiable as a pencil at 18px.

If an accent must change, **six sites move together**: the light rule, the dark rule, both `test_text_colour_css.py` surface entries, the two regex hex literals in `tests/test_callout_css.py`, and every hex and ratio in the spec's §4 (including the icon-chip paragraph, which sits outside any table).

- [ ] **Step 3: Delete the capture harness**

```bash
rm tests/test_e2e_callout_kinds_shot.py
```

Delete it **now**, before the ruff step, so the linter never has to pass over a throwaway file.

- [ ] **Step 4: Falsify every test against its named mutant**

Run each mutant with **only its named test selected** (`-k`), never the whole selection — several mutants redden more than one test, so a red *suite* is not evidence about the named row. Revert each mutant before the next.

| Mutant | `-k` target | Must go RED |
|---|---|---|
| remove `TASK` from `Kind` | `test_display_heading_falls_back_to_kind_default` | ✓ |
| remove `TASK` from `Kind` | `test_persisted_task_callout_renders_kind_class` | ✓ (save() coerces to example) |
| remove `TASK` from `Kind` | `test_edit_form_offers_the_task_kind` | ✓ |
| remove `TASK` from `Kind` | `test_save_round_trips_the_task_kind` | ✓ |
| remove `TASK` from `Kind` | `test_round_trip_preserves_the_task_kind` | ✓ (equality, not TransferError) |
| remove `TASK` from `Kind` | `test_every_callout_kind_has_a_ground_in_both_surface_lists` | ✓ |
| delete the `{% elif el.kind == "task" %}` branch | `test_task_render_emits_pencil_icon` | ✓ |
| move the pencil into the `{% else %}` fallback | `test_example_render_does_not_emit_pencil_icon` | ✓ |
| delete the light `.callout--task` rule | `test_callout_task_light_accent_is_pinned` | ✓ |
| delete the dark `.callout--task` rule | `test_callout_task_dark_accent_is_pinned` | ✓ |
| change either accent hex in `courses.css` | `test_surface_literals_still_match_the_css` | ✓ |
| omit both `callout-task` surface entries | `test_every_callout_kind_has_a_ground_in_both_surface_lists` | ✓ |
| delete the `en` `Task` entry | `test_en_catalog_has_the_task_msgid` | ✓ |
| set `msgstr "Task"` in the `en` catalog | `test_en_catalog_has_the_task_msgid` | ✓ |

**The Polish mutant needs a compile step or it is a no-op** — the test reads the compiled `.mo`, not the `.po`:

```bash
# edit locale/pl/LC_MESSAGES/django.po -> msgstr "Wskazówka"
uv run python manage.py compilemessages
uv run pytest -k test_task_kind_renders_zadanie_in_polish   # confirm RED
# restore the .po
uv run python manage.py compilemessages                     # do NOT skip
```

- [ ] **Step 5: Add the operational note to the cutover runbook**

Append to `docs/superpowers/plans/2026-07-27-internal-link-cutover.md`, under a clear heading:

> **Callout Task kind — sequencing constraint.** Do not author a Task callout in mat-pp until PROD is running code that contains the `TASK` enum member. `FORMAT_VERSION` was deliberately not bumped, so an archive containing a Task callout fails on an older PROD at that element with "unknown callout kind", which does not name the version as the cause. The gate is the **deployed code**, not migration `0056` (a state-only `AlterField` whose SQL is a no-op).

This file is a **live runbook** despite living under `docs/superpowers/plans/` — it is the artifact the cutover operator actually opens.

- [ ] **Step 6: Lint and format**

```
uv run ruff check .
uv run ruff format .
```

`ruff format --check .` is a real CI gate. Run this **after** every other edit, including the runbook.

- [ ] **Step 7: Revert every mutant, recompile, and re-verify green**

Confirm the tree is clean of mutations (`git status`, `git diff`), then:

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

Expected: all PASS. This step is not redundant with the per-task runs — Step 4 deliberately damaged shipped artifacts, and **none of the closing gates below can see a missing CSS rule, a missing template branch, or a stale compiled `.mo`**.

- [ ] **Step 8: Closing gates**

```
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run ruff format --check .
```

Expected: all clean.

- [ ] **Step 9: Commit**

```bash
git add docs/superpowers/plans/2026-07-27-internal-link-cutover.md
git commit -m "docs(cutover): note the Task-kind sequencing constraint for mat-pp"
```

---

## Self-Review

**Spec coverage.** §1 model → Task 1. §2 migration → Task 1 (Steps 6-7). §3 render → Task 2. §4 CSS + header comment → Task 3. §5 surface list → Task 4. §6 editor → Task 5. §7 transfer → Task 6. §8 i18n + help → Task 7. Testing rows 1-11 → Tasks 2-7, falsified in Task 8 Step 4. DoD 1-2 → Task 8 Step 8. DoD 3 → Step 7. DoD 4 → Step 4. DoD 4b → Step 7. DoD 5 → Step 6. DoD 6 → Task 7 Steps 1-3. DoD 7 → Steps 1-3. DoD 8 → Step 5 plus the PR body (pipeline phase 6). The `courses/views.py:187` do-not-change entry is honoured by no task touching that file.

**Placeholders.** One deliberate `<SCRATCHPAD>` token in Task 8 Step 1 (a session-specific path, not knowable at plan time) and one named-but-unwritten helper, `_seed_five_callout_unit`, whose contract is stated in the surrounding prose. Task 7 Step 4 deliberately instructs verification of `_entries`'s real attribute names rather than asserting them — the plan states the requirement and flags the assumption instead of inventing an API.

**Type consistency.** Test function names are identical between the task that creates them and Task 8's mutant table: `test_persisted_task_callout_renders_kind_class`, `test_task_render_emits_pencil_icon`, `test_example_render_does_not_emit_pencil_icon`, `test_callout_task_light_accent_is_pinned`, `test_callout_task_dark_accent_is_pinned`, `test_every_callout_kind_has_a_ground_in_both_surface_lists`, `test_edit_form_offers_the_task_kind`, `test_save_round_trips_the_task_kind`, `test_round_trip_preserves_the_task_kind`, `test_task_kind_renders_zadanie_in_polish`, `test_en_catalog_has_the_task_msgid`. The accent hexes `#a8318f` / `#ee9fd8` and the grounds `#FAF3F8` / `#383030` agree across Tasks 3, 4 and 8.
