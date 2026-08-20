# Locating nested elements in the editor preview — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the unit editor's click→preview scroll and hover→outline work for elements at every nesting depth, revealing hidden container state (tab, spoiler, before/after slot) so the target is actually visible.

**Architecture:** Two independent halves. **Part 1** is server-side: five container templates put `data-element-id` + the `prev-el` class on the `__child` wrapper divs they already emit, gated on `editor_preview`, so the existing JS selector starts matching nested elements with no JS change. **Part 2** is client-side: one new function in `editor.js` walks from the target up to `[data-scope="preview"]`, collects hiding ancestors, and reveals them outermost-first before the existing align runs.

**Tech Stack:** Django 5.2 templates, vanilla ES5-style JS (no build step), pytest + pytest-django, Playwright (e2e), ruff, `uv` for all tooling.

**Spec:** `docs/superpowers/specs/2026-08-20-preview-nested-element-locate-design.md` — 845 lines, 7 review rounds, 80 catches applied, 0 disputed. **The spec is authoritative.** Every mechanism claim in it was verified against source. Do not re-derive its conclusions or drop its prescriptions.

## Global Constraints

- **Worktree, not the main checkout.** Every git command must be `git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" …`. The session cwd is the main repo and the harness resets it after each command — use absolute paths, never `cd`. Branch: `pipeline/preview-nested-element-locate` off `origin/master`.
- **All tooling through `uv run`.** `ruff`, `pytest` and `python` are **not** on PATH. `uv run pytest …`, `uv run ruff …`, `uv run python …`.
- **Start the test-DB container before any pytest run.** Without it the run looks hung for ~4m21s. Check: `docker ps --filter name=libli-test-db`.
- **e2e needs `-m e2e`.** Without the marker every e2e test silently deselects and pytest exits 5.
- **Scope test runs narrowly per task.** Whole-repo sweeps are a branch gate (Task 11), never a per-task step.
- **`uv run ruff format .` runs LAST** (Task 11), after every other edit — it reflows files and `ruff format --check .` is a separate CI gate.
- **Never `git add -A`.** Stage explicit paths.
- **No locale files.** This work adds no translatable strings. If `locale/` shows in `git status`, something is wrong — stop.
- **Pinned emitted template shape** (verbatim, adapted per class name):
  ```
  <div class="tabs__child{% if editor_preview %} prev-el{% endif %}"{% if editor_preview %} data-element-id="{{ child.pk }}"{% endif %}>
  ```
  Two inline `{% if %}`s on one line; class-gate **inside** the quotes; attribute-gate contributes its own leading space. This is **test-pinned**, not stylistic: `courses/tests/test_spoiler_render.py:33,36` count the literal `class="spoiler__child"` on the student render, and that literal survives only with the gate inside the quotes.
- **Four requirements are deliberately unobservable — do NOT invent tests for them:** the `[data-scope="preview"]` climb bound; the synchronous-cascade ordering; un-scoping `ownToggle`; un-scoping `ownPanels`. The spec labels each and explains why. Writing a test for these produces an assertion that cannot fail.
- **Falsification is required.** Every task that adds a test names the mutant it must turn RED. Apply the mutant **by hand** (never `git checkout` to revert — that destroys work; edit it back out by hand), confirm RED, restore, confirm GREEN.

---

### Task 1: The marker in all five templates, with both render tests

**Files:**
- Modify: `templates/courses/elements/tabselement.html:41`
- Modify: `templates/courses/elements/twocolumnelement.html:14`
- Modify: `templates/courses/elements/spoilerelement.html:48`
- Modify: `templates/courses/elements/calloutelement.html:24`
- Modify: `templates/courses/elements/beforeafterelement.html:28`
- Test: `courses/tests/test_preview_nested_markers.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: the DOM contract Part 2 depends on — every nested child in the editor preview is a node matching `.prev-el[data-element-id="<join-row pk>"]`, at every depth.

- [ ] **Step 1: Pre-work sweep — prove no existing test breaks**

Run these and read the hits; each must still hold under the pinned shape:

```bash
cd "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate"
uv run python -c "print('sweep')"   # sanity: uv works
grep -rn "prev-el" tests/ courses/tests/
grep -rn "tabs__child\|twocolumn__child\|spoiler__child\|callout__child\|ba__child" tests/ courses/tests/
```

Known consumers and why each survives:
- `tests/test_manage_element_ops.py:320` — asserts `b'class="prev-el"'` on an **editor** response; the top-level `<section class="prev-el">` in `_preview.html` is untouched, so it still matches.
- `tests/test_e2e_media_manager.py:195` — `.prev-el img`; unaffected (top-level image).
- `courses/tests/test_spoiler_render.py:33,36` — counts `class="spoiler__child"` on a **bare `.render()`** (no `editor_preview`), so the gate collapses and the literal is exact.
- `courses/tests/test_nested_question_nojs_feedback.py` — `_child_slice` (line 184) builds `open_tag = f'<div class="{wrapper_class}">'` and calls `body.index(open_tag)`: an **exact literal match including the closing `>`**, *not* a prefix match. It survives only because every caller renders a **student** URL (`courses:check_answer` / `courses:lesson_unit`), where the gate collapses and the literal is exact. It would raise `ValueError` on any editor-page render.
- `courses/tests/test_reveal_gate_render.py:84` — `re.findall(r'class="[^"]*\btabs__child\b[^"]*"[^>]*>', html)`; a `\b`-delimited match inside the class list, so the added ` prev-el` is tolerated. Student render.
- `tests/test_e2e_reveal_gate.py:765` — `preview.locator(".tabs__child", …)`, an **editor-preview** locator; a class-list locator, unaffected by an added class.
- `tests/test_e2e_filltable_gate.py:344-349` — a comment asserting callout children have no `data-element-id`; **student** page, so still true. Read it and confirm it is a comment, not an assertion.
- `tests/test_e2e_depth3.py:281/427/501` and `tests/capture_nested_question_screenshots.py:78-85` — class-list locators; unaffected.

**All remaining hits** — roughly forty across ~20 files, including `tests/test_filltable_render.py:70-80`, `tests/test_e2e_nested_question.py:230,284`, `tests/test_e2e_spoiler_rule.py:90`, `tests/test_e2e_callout_container.py`, `courses/tests/test_reveal_gate_render.py:217/220/242`, `tests/test_e2e_reveal_gate.py:636`, `tests/test_e2e_depth3.py:274/528`, `courses/tests/test_beforeafter_css.py`, `courses/tests/test_render_seam.py:257-263` — are **class-list locators, CSS-file assertions, or comments**. None is an exact `class="…"` literal on an editor render, so all survive. Do not adjudicate them one by one.

**Rule for anything else:** any hit that is neither on the named list nor in that category must be evaluated and its outcome recorded before proceeding. A hit that contradicts the pinned shape → **stop and report**; do not adjust the shape.

- [ ] **Step 1b: Confirm the gate's safety argument — the three unscoped consumers are not loaded by the editor**

This is the entire reason it is safe to put `[data-element-id]` on nested nodes inside the editor page, and the spec explicitly refuses to be taken on trust here. Three scripts query `[data-element-id]` **unscoped**: `courses/static/courses/js/progress.js`, `courses/static/courses/js/slideshow.js`, `notes/static/notes/js/notes.js`. There is a standing invariant test at `courses/tests/test_image_size_render.py:41-49`.

```bash
grep -n "progress.js\|slideshow.js\|notes.js" templates/courses/manage/editor/editor.html
grep -n "{% extends" templates/courses/manage/editor/editor.html   # then grep the base too
```

Expected: **no hits** in the editor template or its base. Record the result in the commit message. If any of the three *is* loaded, **stop and report** — the gate is not sufficient and the design needs revisiting.

- [ ] **Step 1c: Confirm the propagation chain and the pk identity (read-only)**

The spec requires these be confirmed rather than assumed. Read and record:

1. `courses/templatetags/courses_extras.py:160-176` — `render_element` builds the `page` dict for `CONTAINER_MODELS` only; `editor_preview` is one of its seven keys.
2. `courses/models.py:471, 576, 679, 1936, 2060` — all five container `render()` methods spread `**(page or {})` into the child context, `page` first.
3. `courses/templatetags/courses_extras.py:74-75` — the recursive child render re-reads `editor_preview` from context when not passed explicitly, defaulting on **`is None`**, not `False`. This is the load-bearing line: a `False` default could never satisfy `is None`, which would make the fallback dead code and silently no-op the whole feature.
4. `alignTopInPane` (`courses/static/courses/js/editor.js:214-221`) does `el.closest(".pane-body")` — confirm that still resolves for a deeply nested target. Its failure mode is a **silent `return`** (no scroll at all), which no test distinguishes from "already at the top", so this is a read-and-record check, not a test.

Record all four findings in the commit message.

- [ ] **Step 2: Write the two failing render tests**

Create `courses/tests/test_preview_nested_markers.py`:

```python
"""Nested elements must be locatable in the EDITOR PREVIEW and invisible on the
STUDENT page. See docs/superpowers/specs/2026-08-20-preview-nested-element-locate-design.md.

SCOPING IS LOAD-BEARING AND DIFFERS PER TEST:
  * Editor page: the EDITOR pane also carries [data-element-id] (on the el-act-edit
    buttons in _element_row.html), so an unscoped assertion passes vacuously on a
    broken build. Parse ONCE and root the selector at [data-scope="preview"].
  * Student page: there IS NO [data-scope="preview"] node -- it exists only in the
    editor's _preview.html. Rooting there selects zero nodes and "neither half is
    present" is trivially true, leaving mutants c1 and c2 both alive. So the student
    test selects the .<container>__child wrappers directly and asserts the selection
    is NON-EMPTY first.
"""

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from courses.models import BeforeAfterElement
from courses.models import CalloutElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db

CHILD_CLASSES = [
    "tabs__child",
    "twocolumn__child",
    "spoiler__child",
    "callout__child",
    "ba__child",
]


def _text(body="x"):
    return TextElement.objects.create(body=f"<p>{body}</p>")


def _fixed_tabs_data():
    """default_data() mints ids with secrets.token_hex(3) (models.py:1785), which are
    rendered into data-tab-id, id="tabs-{eid}-{tid}-panel", the matching -label id and
    aria-labelledby. Two renders of the SAME tree would therefore differ every time,
    which would make Task 11's master-vs-master control diff impossible to satisfy.
    Overwrite the ids with fixed literals; the shape is taken from default_data() so
    this stays correct if the shape changes."""
    d = TabsElement.default_data()
    for i, t in enumerate(d["tabs"], start=1):
        t["id"] = f"t{i:06d}"
    return d


def _fixed_columns_data():
    """Same, for TwoColumnElement -- ids are minted with secrets.token_hex(3)
    (models.py:1971) and rendered into data-column-id."""
    d = TwoColumnElement.default_data()
    for i, c in enumerate(d["columns"], start=1):
        c["id"] = f"c{i:06d}"
    return d


def _containers(unit):
    """One of each of the five containers at top level, each holding one text child.

    Fixtures are built with DIRECT Element(parent=...) rows -- as
    test_image_size_render.py does -- NOT through builder.resolve_scope, whose
    clause 3/4 depth rules would couple this test to the nesting policy it is not
    testing.

    Returns {child_class: child_join_pk}.
    """
    out = {}

    tabs = TabsElement.objects.create(data=_fixed_tabs_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, parent=None)
    tab_id = tabs.data["tabs"][0]["id"]
    out["tabs__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-tab"), parent=tabs_join, tab_id=tab_id
    ).pk

    two = TwoColumnElement.objects.create(data=_fixed_columns_data())
    two_join = Element.objects.create(unit=unit, content_object=two, parent=None)
    col_id = two.data["columns"][0]["id"]
    out["twocolumn__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-col"), parent=two_join, tab_id=col_id
    ).pk

    sp = SpoilerElement.objects.create(label="s")
    sp_join = Element.objects.create(unit=unit, content_object=sp, parent=None)
    out["spoiler__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-spoiler"), parent=sp_join,
        tab_id=SpoilerElement.SLOT_ID,
    ).pk

    co = CalloutElement.objects.create(heading="C")
    co_join = Element.objects.create(unit=unit, content_object=co, parent=None)
    out["callout__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-callout"), parent=co_join,
        tab_id=CalloutElement.SLOT_ID,
    ).pk

    ba = BeforeAfterElement.objects.create()
    ba_join = Element.objects.create(unit=unit, content_object=ba, parent=None)
    out["ba__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-ba"), parent=ba_join,
        tab_id=BeforeAfterElement.SLOT_IDS[0],
    ).pk

    return out


def test_editor_preview_marks_every_nested_child(client):
    """Mutants: (a1) drop the marker from ONE template -> RED (all five asserted, not
    a sample). (a2) emit data-element-id WITHOUT the prev-el class -> RED (the pair is
    asserted on ONE node; the consumer selector is .prev-el[data-element-id=...], so
    the class is as load-bearing as the attribute)."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    pks = _containers(unit)

    html = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode()
    soup = BeautifulSoup(html, "html.parser")

    for cls in CHILD_CLASSES:
        sel = f'[data-scope="preview"] .{cls}.prev-el[data-element-id="{pks[cls]}"]'
        assert soup.select_one(sel) is not None, f"missing marker pair for .{cls}"


def test_editor_preview_marks_a_depth_3_child(client):
    """Depth 3 proves the recursion carries editor_preview across TWO
    CONTAINER_MODELS barriers. The pair is NAMED (tabs inside a spoiler) rather than
    left to choice: the pairs differ in risk (callout-in-callout is the mildest) and
    this mirrors the shape e2e 5 exercises."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    sp = SpoilerElement.objects.create(label="s")
    sp_join = Element.objects.create(unit=unit, content_object=sp, parent=None)
    tabs = TabsElement.objects.create(data=_fixed_tabs_data())
    tabs_join = Element.objects.create(
        unit=unit, content_object=tabs, parent=sp_join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    deep = Element.objects.create(
        unit=unit, content_object=_text("deep"), parent=tabs_join,
        tab_id=tabs.data["tabs"][0]["id"],
    )

    html = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode()
    soup = BeautifulSoup(html, "html.parser")
    sel = (
        f'[data-scope="preview"] .spoiler__child '
        f'.tabs__child.prev-el[data-element-id="{deep.pk}"]'
    )
    assert soup.select_one(sel) is not None


def test_student_page_carries_neither_marker_half(client):
    """Mutants: (c1) drop the {% if editor_preview %} gate -> RED.
    (c2) gate the ATTRIBUTE but not the CLASS -> RED (both halves asserted; a
    class-only leak would put prev-el on every student page while an
    attribute-only assertion stayed green).

    NOT scoped to [data-scope="preview"] -- see the module docstring."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _containers(unit)

    # The student lesson route is `courses:lesson_unit` (courses/urls.py:27) and its
    # kwarg is `node_pk`, NOT `pk` (views.py:807 `def lesson_unit(request, slug,
    # node_pk)`). This is the shape tests/test_e2e_tabs.py::_lesson_url already uses.
    html = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    soup = BeautifulSoup(html, "html.parser")

    wrappers = [n for cls in CHILD_CLASSES for n in soup.select(f".{cls}")]
    # Without this the whole test is vacuous for the same reason the preview-rooted
    # selector would be: an empty selection satisfies every "is absent" assertion.
    assert wrappers, "no child wrappers rendered -- fixture or URL is wrong"
    for n in wrappers:
        assert not n.has_attr("data-element-id"), f"leaked attribute on {n.get('class')}"
        assert "prev-el" not in (n.get("class") or []), f"leaked class on {n.get('class')}"
```

Also add this assertion to `test_editor_preview_marks_every_nested_child`, tying the marker to the **join-row** pk (not the content-object pk — the confusion the spec's `data-preview-el` section warns about):

```python
    # child.pk is the Element JOIN ROW pk -- the same identity the editor rows carry
    # as data-element, and the same one setHighlight/scrollPreviewTo are called with.
    row = soup.select_one(f'.el-row[data-element="{pks["callout__child"]}"]')
    assert row is not None, "the marker pk is not the editor row's data-element pk"
```

- [ ] **Step 2b: Run the tests to verify they FAIL**

```bash
docker ps --filter name=libli-test-db --format "{{.Names}} {{.Status}}"
uv run pytest courses/tests/test_preview_nested_markers.py -p no:randomly -q
```
Expected: **2 failed, 1 passed** — the two editor/depth tests FAIL (no `.prev-el` on child wrappers); the student test PASSES already, because nothing is emitted yet. That pass is correct and expected: the student test only becomes meaningful once Step 3 lands, which is why its mutants (c1, c2) are falsified in Step 5 rather than relied on here.

- [ ] **Step 3: Apply the pinned shape to all five templates**

Each is a one-line edit. Preserve the surrounding indentation exactly.

`templates/courses/elements/tabselement.html:41`:
```html
            <div class="tabs__child{% if editor_preview %} prev-el{% endif %}"{% if editor_preview %} data-element-id="{{ child.pk }}"{% endif %}>{% render_element child %}</div>
```

`templates/courses/elements/twocolumnelement.html:14`:
```html
        <div class="twocolumn__child{% if editor_preview %} prev-el{% endif %}"{% if editor_preview %} data-element-id="{{ child.pk }}"{% endif %}>{% render_element child %}</div>
```

`templates/courses/elements/spoilerelement.html:48`:
```html
        <div class="spoiler__child{% if editor_preview %} prev-el{% endif %}"{% if editor_preview %} data-element-id="{{ child.pk }}"{% endif %}>{% render_element child %}</div>
```

`templates/courses/elements/calloutelement.html:24`:
```html
        <div class="callout__child{% if editor_preview %} prev-el{% endif %}"{% if editor_preview %} data-element-id="{{ child.pk }}"{% endif %}>{% render_element child %}</div>
```

`templates/courses/elements/beforeafterelement.html:28` — this one is a **single-line `{% for %}` loop**; keep it on one line (a block-form `{% if %}` here would push newlines into student output):
```html
      {% for child in children %}<div class="ba__child{% if editor_preview %} prev-el{% endif %}"{% if editor_preview %} data-element-id="{{ child.pk }}"{% endif %}>{% render_element child %}</div>{% endfor %}
```

- [ ] **Step 4: Run the tests to verify they PASS**

```bash
uv run pytest courses/tests/test_preview_nested_markers.py -p no:randomly -q
```
Expected: **3 passed** (the module defines exactly three tests).

Also run the sweep's at-risk tests, narrowly:
```bash
uv run pytest courses/tests/test_spoiler_render.py tests/test_manage_element_ops.py -p no:randomly -q
```
Expected: all pass. If `test_spoiler_render.py` fails, the gate is outside the quotes — fix the shape, not the test.

- [ ] **Step 5: Falsify — four mutants, by hand**

For each: edit the mutant in **by hand**, run, confirm RED, then edit it back out by hand and confirm GREEN. **Never `git checkout` to revert** — it destroys uncommitted work (this repo has been bitten three times).

| Mutant | Edit | Must turn RED |
|---|---|---|
| a1 | delete ` prev-el` **and** the attribute gate from `calloutelement.html` only | `test_editor_preview_marks_every_nested_child` |
| a2 | in `tabselement.html`, drop `{% if editor_preview %} prev-el{% endif %}` but keep the attribute | `test_editor_preview_marks_every_nested_child` |
| c1 | in `spoilerelement.html`, remove both `{% if editor_preview %}`/`{% endif %}` pairs (emit unconditionally) | `test_student_page_carries_neither_marker_half` |
| c2 | in `spoilerelement.html`, keep the attribute gate but emit ` prev-el` unconditionally | `test_student_page_carries_neither_marker_half` |

Record each RED in the commit message.

- [ ] **Step 6: Commit**

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add templates/courses/elements/tabselement.html templates/courses/elements/twocolumnelement.html templates/courses/elements/spoilerelement.html templates/courses/elements/calloutelement.html templates/courses/elements/beforeafterelement.html courses/tests/test_preview_nested_markers.py
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "feat(editor): mark nested children in the live preview

Gated on editor_preview, on the __child wrappers the five container
templates already emit -- no new DOM node, because CSS reaches through
them (.callout__children > .callout__child:first-child > :first-child).
Reusing the prev-el class means zero JS/CSS change: the existing
.prev-el[data-element-id] selector starts matching at every depth.

Falsified: a1, a2, c1, c2 each RED."
```

---

### Task 2: CSS guard test — `.prev-el` must never declare `display`

**Files:**
- Test: `courses/tests/test_preview_marker_css.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: a standing tripwire; no runtime code.

**Why this exists:** once the child wrappers carry `.prev-el`, an author `display` on it would stop `.callout__child` / `.spoiler__child` / `.twocolumn__child` honouring the UA `[hidden]` rule — they are **absent** from the guard at `core/static/core/css/app.css:1179` (`.lesson-block[hidden], .tabs__child[hidden], .ba__child[hidden]`) — which in turn breaks `reveal.js`'s `gateWrap.hidden = true` in the editor preview. Reading it once is not enough for a cross-file invariant.

- [ ] **Step 1: Write the failing test**

Modelled directly on `courses/tests/test_beforeafter_css.py::test_panel_and_child_declare_no_display`, including its comment-stripping trap.

```python
"""`.prev-el` must never declare `display`.

The child wrappers .callout__child / .spoiler__child / .twocolumn__child are NOT in
app.css:1179's [hidden] guard -- they honour `hidden` only through the UA rule, which
an author `display` on .prev-el would beat. reveal.js's gateWrap.hidden = true then
stops working in the editor preview.

Comments are stripped FIRST: they name the very selectors this test looks for, so a
raw scan is green under its own mutant (the test_beforeafter_css precedent).
"""

import re
from pathlib import Path

EDITOR_CSS = "courses/static/courses/css/editor.css"


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rule_body(css, selector):
    """The declarations of ONE rule, so the invariant is not asserted against a
    whole block that legitimately contains other rules (.prev-el--hl has a
    box-shadow, which is fine and must not be mistaken for a violation)."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_prev_el_declares_no_display():
    """Mutant: add `display: block` to .prev-el -> RED."""
    css = _strip_comments(Path(EDITOR_CSS).read_text(encoding="utf-8"))
    body = _rule_body(css, ".prev-el")
    assert "border-radius" in body, "extracted the wrong rule"
    assert "display" not in body


def test_prev_el_hl_declares_no_display():
    """The highlight state is applied to the same wrappers, so it carries the same
    constraint. Mutant: add `display: block` to .prev-el--hl -> RED."""
    css = _strip_comments(Path(EDITOR_CSS).read_text(encoding="utf-8"))
    body = _rule_body(css, ".prev-el--hl")
    assert "box-shadow" in body, "extracted the wrong rule"
    assert "display" not in body
```

- [ ] **Step 2: Run to verify it passes on the current tree**

```bash
uv run pytest courses/tests/test_preview_marker_css.py -p no:randomly -q
```
Expected: 2 passed. (This is a guard test, not a red-to-green feature test — its value is the mutant below.)

- [ ] **Step 3: Falsify — mutant (l)**

By hand, add `display: block;` to `.prev-el` in `courses/static/courses/css/editor.css:826`. Run the test → must be **RED**. Remove it by hand → GREEN. Repeat for `.prev-el--hl`.

- [ ] **Step 4: Commit**

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add courses/tests/test_preview_marker_css.py
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "test(editor): guard that .prev-el declares no display

The child wrappers are absent from app.css:1179's [hidden] guard, so they
honour `hidden` only via the UA rule -- an author display on .prev-el
would beat it and break reveal.js's gateWrap.hidden in the preview.

Falsified: mutant (l) RED on both rules."
```

---

### Task 3: The walk — skeleton, plus the strip-tabs and spoiler reveal steps

**Files:**
- Modify: `courses/static/courses/js/editor.js` (add `ownNodes`, `revealAncestors`, `revealOne`; call from `scrollPreviewTo`)
- Test: `tests/test_e2e_preview_nested_locate.py` (create) — e2e 1 and e2e 3

**Interfaces:**
- Consumes: Task 1's `.prev-el[data-element-id]` on nested wrappers.
- Produces: `revealAncestors(targetEl)` — collects hiding ancestors from `targetEl` up to `[data-scope="preview"]` and reveals them outermost-first. Called synchronously from `scrollPreviewTo`. Tasks 4, 5 extend `revealOne` with the carousel and before/after branches.

- [ ] **Step 1: Write the failing e2e (cases 1 and 3)**

Create `tests/test_e2e_preview_nested_locate.py`. Model the seeding and login helpers on `tests/test_e2e_tabs.py` (read its header and `_seed_carousel` first).

**Mandatory precondition, applies to every tabs and two-column case:** nested editor rows start **collapsed**. `_element_row.html:82` opens a tab's row group only when the slot is in `open_slots`, or `clip_active`, or **`forloop.first`** — so a child in a non-first tab starts closed. `_element_row.html:141` (`columns-rows`) has **no** `forloop.first` clause, so *both* two-column slots start closed. In a fresh Playwright context nothing is restored, so clicking the nested row without opening the `<details>` first hangs on a not-visible locator. Spoiler, callout and before/after rows are always-open divs and need no such step.

**Name the click path in every case.** The row's visible label is itself a `<button class="el-select el-row__label">`, and the row-body handler excludes `button, a, input, …`, so a default centre-of-box `row.click()` lands on either path depending on layout. The two differ materially: `.el-select` (`editor.js:451`) rebuilds both panes and re-stamps `data-tabs-active` via `restoreActiveTabs` before the walk runs; the row-body path (`editor.js:463`) does neither. **At least one reveal case must run on each path.** Cases 1 and 3 below cover both.

```python
"""Playwright e2e: locating NESTED elements in the editor's live preview.

Spec: docs/superpowers/specs/2026-08-20-preview-nested-element-locate-design.md

Drives real gestures -- clicks the actual controls, never page.evaluate shortcuts.

STANDING TRAPS (the spec's "Assertion traps that make a test vacuous"):
  * Carousel slides are position:absolute; opacity:0 with an INTACT rect, and
    Playwright calls opacity:0 VISIBLE -- so never assert carousel reveal via
    visibility or geometry. Assert on the TARGET's own section: is-active gained,
    inert/aria-hidden lost, or data-tabs-active on the owning [data-tabs-eid].
  * show() adds is-active to the incoming slide synchronously but calls
    settleHidden(out) only after FADE_MS (320ms), so "exactly one .is-active" is
    flaky for 320ms. Never assert about the OUTGOING slide during the fade.
  * Capture any "before" tab value BEFORE the click: applyFragments'
    captureActiveTabs/restoreActiveTabs re-stamp the pre-click tab onto the rebuilt
    preview, so it cannot be inferred from the post-swap DOM.
  * Never assert prev-el--hl after a CLICK. That class comes only from setHighlight
    on mouseenter; on the .el-select path applyFragments destroys the highlighted
    node before scrollPreviewTo runs. Only the hover case (e2e 7) asserts it.
"""

import os

import pytest

from tests.test_e2e_tabs import _editor_url
from tests.test_e2e_tabs import _login
from tests.test_e2e_tabs import _make_pa_user
from tests.test_e2e_tabs import _seed_tabs_element
from tests.test_e2e_tabs import _seed_unit

# MANDATORY. There is no auto-marking hook -- neither conftest.py nor
# tests/conftest.py defines pytest_collection_modifyitems, and all 106 e2e modules
# declare this by hand. Without it `-m e2e` DESELECTS every case and pytest exits 5,
# which reads as "no failures" and would let a red step look green.
pytestmark = pytest.mark.e2e


# Per-module, NOT in a shared conftest -- every sibling e2e module defines its own
# (tests/test_e2e_tabs.py:44-48). Without it sync-ORM calls under Playwright can fail
# depending on collection order.
@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield
```

**Helpers: import, do not copy.** `tests/test_e2e_tabs.py` provides `_make_pa_user` (`:55`), `_login` (`:69`), **`_seed_unit(owner, slug)` (`:77`)** — returns `(course, unit)`; give each case a **distinct slug** — `_editor_url(live_server, course, unit)` (`:88`), `_lesson_url` (`:92`) and `_seed_tabs_element(unit, tabs, children, display=…, parent=…, tab_id=…)` (`:101`), the last already supporting nesting via `parent=`/`tab_id=`, which Tasks 4, 6, 9 and 10 need.

⚠️ **Do NOT model the carousel fixtures on `_seed_carousel` (`:717`)** — it seeds a **student lesson page**, not the editor. Carousel *editor* fixtures must go through `_seed_tabs_element(..., display="carousel")` plus `_editor_url`.

- [ ] **Step 1b: Define this module's shared seed helpers — the other tasks call them by name**

`test_e2e_tabs.py` seeds **tabs only**. Nothing there seeds a spoiler, callout, before/after, plain text, or a filler run — and Tasks 5, 7, 8, 9 and 10 all need them. Because execution is subagent-driven (each task is a separate context), leaving this to "conventions" means five tasks each inventing an incompatible ad-hoc seeder in the same file. Define them **once, here**:

```python
def _seed_container(unit, obj, children, parent=None, tab_id=""):
    """Create the container's join row, then one join row per child.

    `children` is a list of (content_object, slot_id). Mirrors the shape of
    courses/tests/test_preview_nested_markers.py::_containers -- direct
    Element(parent=...) rows, NOT builder.resolve_scope.

    Returns (container_join, [child_join, ...]).
    """
    from courses.models import Element

    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab_id
    )
    kids = [
        Element.objects.create(
            unit=unit, content_object=child, parent=join, tab_id=slot
        )
        for child, slot in children
    ]
    return join, kids


def _seed_text(body="x"):
    from courses.models import TextElement

    return TextElement.objects.create(body=f"<p>{body}</p>")


def _seed_filler(unit, n):
    """n top-level text elements, each tall enough to push the pane well past a
    viewport. Used by Tasks 7 and 9 to make a scroll observable."""
    from courses.models import Element

    for i in range(n):
        Element.objects.create(
            unit=unit,
            content_object=_seed_text(("filler %d<br>" % i) * 40),
            parent=None,
        )
```

Tasks 5–10 must call these rather than writing their own.

Write case 1 (strip tabs, `.el-select` path) and case 3 (spoiler, row-body path):

```python
@pytest.mark.django_db(transaction=True)
def test_click_reveals_a_child_in_a_non_first_strip_tab(page, live_server):
    """e2e 1. Mutant (b1): drop the strip reveal step -> RED.

    Click path: .el-select (the .el-row__label button), which rebuilds both panes.
    """
    # seed: tabs element, child TEXT in tab 2 (NOT tab 1 -- select() early-returns
    # on i === active, and a first-tab target is revealed by initOne anyway).
    # ... seeding per tests/test_e2e_tabs.py conventions ...
    page.goto(editor_url)
    eid = str(tabs_join.pk)
    tabs_sel = f'[data-scope="preview"] [data-tabs][data-tabs-eid="{eid}"]'
    before = page.get_attribute(tabs_sel, "data-tabs-active")   # BEFORE the click
    assert before == tab1_id

    # MANDATORY: the nested row lives in a collapsed <details class="tabs-rows">.
    page.click(f'details.tabs-rows[data-tab-id="{tab2_id}"] > summary')
    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')

    page.wait_for_function(
        """([sel, want]) => document.querySelector(sel)
              ?.getAttribute("data-tabs-active") === want""",
        arg=[tabs_sel, tab2_id],
    )
    box = page.locator(
        f'[data-scope="preview"] .prev-el[data-element-id="{child_join.pk}"]'
    ).bounding_box()
    assert box and box["height"] > 0 and box["width"] > 0


@pytest.mark.django_db(transaction=True)
def test_click_opens_a_closed_spoiler_around_the_child(page, live_server):
    """e2e 3. Mutant (b3): drop the spoiler `open = true` step -> RED.

    CLICK PATH: the ROW BODY (editor.js:463, NO fragment swap) -- this is the case
    that covers the second path, so the target must not be a button.

    Target `.el-tag` (a <span>), NOT `.el-row__top`: that is a display:flex row
    (editor.css:580) whose `.el-actions` carries margin-left:auto over ~250px of icon
    buttons (editor.css:606), so Playwright's centre-of-box click lands INSIDE
    .el-actions on a narrow nested row and routes to .el-select instead. A spoiler
    opens on either path, so the mis-route would be silent.
    """
    page.goto(editor_url)
    det = '[data-scope="preview"] details.spoiler'
    assert page.get_attribute(det, "open") is None      # closed to begin with

    # Prove NO fragment swap occurred: hold a handle on a preview node and assert it
    # is still connected afterwards. applyFragments replaces the whole pane, so a
    # swapped-in build detaches it.
    handle = page.query_selector('[data-scope="preview"]')
    page.click(f'.el-row[data-element="{child_join.pk}"] .el-tag')
    page.wait_for_selector(f"{det}[open]")
    assert page.evaluate("(n) => n.isConnected", handle), "unexpected fragment swap"
```

- [ ] **Step 2: Run to verify they FAIL**

```bash
docker ps --filter name=libli-test-db
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q
```
Expected: **2 failed** — case 1 times out waiting for `data-tabs-active` to become `tab2_id`; case 3 times out waiting for `details.spoiler[open]`.

⚠️ **`2 deselected` / exit 5 is NOT a pass.** If you see that, `pytestmark = pytest.mark.e2e` is missing from the module — fix it before reading anything into the result. This is why the expectation above names the *failure text* rather than just "FAIL".

- [ ] **Step 3: Implement the walk**

In `courses/static/courses/js/editor.js`, immediately **above** `function scrollPreviewTo(id)` (currently line 235), insert:

```js
  // --- Reveal a nested target's hiding ancestors ---------------------------------
  // Collection runs OUTWARD (target -> [data-scope="preview"]); reveal runs INWARD
  // (outermost first). Order is load-bearing, not cosmetic: select() calls
  // scrollIntoStrip(), which reads offsetLeft/offsetWidth/scrollLeft/clientWidth --
  // all zero while an outer ancestor is still display:none, leaving an inner strip
  // permanently mis-scrolled. The carousel's measure() reads geometry the same way.
  //
  // tabs.js's ownSections()/ownPart() and beforeafter.js's ownPanels()/ownToggle()
  // are closure-local and NOT exported, so this reimplements the predicate rather
  // than refactoring their exports. Ownership, not containment: a tabs element may
  // legally contain another (the depth-3 lift), and a descendant-wide lookup from
  // the outer container grabs the INNER instance's controls -- activating one hides
  // the outer panel that contains it and the element goes blank (tabs.js:33-43).
  function ownNodes(container, selector, ownerSelector) {
    var out = [];
    var all = container.querySelectorAll(selector);
    for (var i = 0; i < all.length; i++) {
      if (all[i].closest(ownerSelector) === container) out.push(all[i]);
    }
    return out;
  }

  // `s` is a FILTER over C's OWNED nodes -- never closest() from the target (which
  // returns the INNERMOST section for every ancestor in a stacked chain, so an outer
  // container indexes a section it does not own and reveals the wrong slide), and
  // never the child the climb passed through (that is .tabs__stage / .ba__panels --
  // neither a section nor a panel, no id, indexOf -> -1).
  function owningNode(container, selector, ownerSelector, target) {
    var owned = ownNodes(container, selector, ownerSelector);
    for (var i = 0; i < owned.length; i++) {
      if (owned[i].contains(target)) return { node: owned[i], all: owned };
    }
    return null;
  }

  function revealAncestors(target) {
    var stop = target.closest('[data-scope="preview"]');
    if (!stop) return;  // defensive; unobservable on today's page (see the spec)
    var chain = [];
    var node = target.parentElement;
    while (node && node !== stop) {
      if (node.tagName === "DETAILS") {
        if (!node.open) chain.push({ kind: "details", c: node });
      } else if (node.hasAttribute("data-tabs")) {
        // Collected UNCONDITIONALLY: select()/show() early-return on i === active,
        // so pre-checking would only risk skipping. "Hidden" is NOT decidable by the
        // [hidden] attribute here -- a carousel conceals by class/opacity/inert.
        var t = owningNode(node, ".tabs__section", "[data-tabs]", target);
        if (t) chain.push({ kind: "tabs", c: node, s: t.node, all: t.all });
      } else if (node.hasAttribute("data-beforeafter")) {
        var b = owningNode(node, ".ba__panel", "[data-beforeafter]", target);
        if (b && b.node.hasAttribute("hidden")) {
          chain.push({ kind: "ba", c: node, s: b.node });
        }
      }
      node = node.parentElement;
    }
    for (var k = chain.length - 1; k >= 0; k--) revealOne(chain[k]);  // outermost first
  }

  // Each step calls the element's own .click() -- a real DOM click, dispatching the
  // listener SYNCHRONOUSLY, so the step completes before the next ancestor inward is
  // measured. A missing control is SKIPPED, never thrown on: a throw would abort the
  // whole click handler and lose the scroll part 1 already earned.
  function revealOne(hit) {
    if (hit.kind === "details") {
      hit.c.open = true;
      // A <details> dispatches nothing of its own -- tabs.js's ResizeObserver is the
      // only other rescue. Dispatching here gives a nested carousel's scheduleMeasure
      // the signal it would otherwise miss.
      hit.c.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
      return;
    }
    if (hit.kind === "ba") {
      var toggle = ownNodes(hit.c, ".ba__toggle", "[data-beforeafter]")[0];
      if (toggle) toggle.click();
      return;
    }
    // Branch on the CONTAINER's data-display, exact "carousel" match, mirroring
    // tabs.js:83 (null / "" / a stale fragment / a future third mode all fall through
    // to the strip). Keying on [data-tab-panel] instead would match a carousel
    // target, find no button, hit the skip above, and silently never reach the
    // carousel branch -- while looking like correct defensive code.
    if (hit.c.getAttribute("data-display") === "carousel") {
      return;  // Task 4
    }
    // .tabs__section carries no id; the id [aria-controls] needs is on its panel.
    var panel = ownNodes(hit.s, "[data-tab-panel]", ".tabs__section")[0];
    if (!panel || !panel.id) return;
    // Document-rooted is safe: panel ids are namespaced by the join-row pk.
    var btn = document.querySelector('[aria-controls="' + panel.id + '"]');
    if (btn) btn.click();
  }
```

Then change `scrollPreviewTo`'s absent-target guard — the two lines quoted below, currently `editor.js:237-238` (`:235` is the `function` line and `:236` is `if (!id) return;`). Anchor on the snippet, not the numbers:

```js
    var sel = '.prev-el[data-element-id="' + id + '"]';
    if (!root.querySelector(sel)) return;  // absent (failed/empty swap or deleted) -> no-op
```

to:

```js
    var sel = '.prev-el[data-element-id="' + id + '"]';
    var target = root.querySelector(sel);
    if (!target) return;  // absent (failed/empty swap or deleted) -> no-op
    // SYNCHRONOUS, after the absent-target guard and BEFORE the rAF below: revealing
    // inside that callback would measure the pre-reveal layout on the first pass and
    // leave the smooth scroll animating toward a stale position.
    revealAncestors(target);
```

Leave the rest of `scrollPreviewTo` untouched — the existing rAF, the img/iframe `load` re-aligns and the 500 ms backstop all still apply.

- [ ] **Step 4: Run to verify they PASS**

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q
```
Expected: 2 passed.

- [ ] **Step 5: Falsify — mutants (b1) and (b3)**

By hand: (b1) make the strip branch `return;` before the button click → case 1 RED. (b3) delete `hit.c.open = true;` → case 3 RED. Restore each by hand; confirm GREEN.

- [ ] **Step 6: Commit**

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add courses/static/courses/js/editor.js tests/test_e2e_preview_nested_locate.py
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "feat(editor): reveal a nested target's hiding ancestors before scrolling

Collect outward to [data-scope=preview], reveal outermost-first. Strip
tabs and spoiler branches; carousel and before/after follow.

Falsified: b1, b3 each RED."
```

---

### Task 4: The carousel branch (e2e 2, e2e 9)

**Files:**
- Modify: `courses/static/courses/js/editor.js` (`revealOne`, the `data-display === "carousel"` branch)
- Modify: `tests/test_e2e_preview_nested_locate.py`

**Interfaces:**
- Consumes: Task 3's `revealOne` / `ownNodes`.
- Produces: nothing new; completes the tabs half.

- [ ] **Step 1: Write the failing e2e cases 2 and 9**

Case 2 — child in a non-first slide of a `display: "carousel"` tabs element. **Assert positively, on the target's own section only:**

```python
    sect_sel = (
        f'[data-scope="preview"] [data-tabs][data-tabs-eid="{eid}"] '
        f'.tabs__section:nth-of-type({idx + 1})'
    )
    page.wait_for_selector(f"{sect_sel}.is-active")
    assert page.get_attribute(sect_sel, "inert") is None
    assert page.get_attribute(sect_sel, "aria-hidden") is None
```

Case 9 — **the fixture for mutant (d), which no other case can kill.** An **outer carousel** with the target in a **non-first slide**, containing an **inner carousel** in that slide with at least as many slides as the outer's target index (so a wrong-instance click lands somewhere rather than no-oping). Assert the **outer** container's `data-tabs-active` equals **the `data-tab-id` of the target section's own `[data-tab-panel]`** — that is what `show()` stamps (`ids[idx]`), a model-level tab id, not the `tabs-<eid>-<tid>-panel` DOM id the strip lookup uses.

```python
    outer_sel = f'[data-scope="preview"] [data-tabs][data-tabs-eid="{outer_join.pk}"]'
    page.wait_for_function(
        """([sel, want]) => document.querySelector(sel)
              ?.getAttribute("data-tabs-active") === want""",
        arg=[outer_sel, outer_slide2_tab_id],
    )
```

On the un-scoped build the `.tabs__dot` query returns the **inner** nav's dots first — the outer's `nav` is appended after `.tabs__stage` — so the outer never advances.

- [ ] **Step 2: Run to verify they FAIL**

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q -k "carousel"
```
Expected: both new cases FAIL (the branch is a bare `return;`).

- [ ] **Step 3: Implement the carousel branch**

Replace `return;  // Task 4` with:

```js
      // Dots are index-keyed with NO id, and are positionally 1:1 with
      // ownSections(container) (initCarousel builds them as sections.map(...)).
      // Nothing in tabs.js names or pins that invariant, so this depends on it
      // explicitly -- and derives the dot list with the SAME ownership filter used
      // for the sections, never a separate query.
      var dots = ownNodes(hit.c, ".tabs__dot", "[data-tabs]");
      var dot = dots[hit.all.indexOf(hit.s)];
      if (dot) dot.click();
      return;
```

- [ ] **Step 4: Run to verify they PASS**

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q
```
Expected: 4 passed.

- [ ] **Step 5: Falsify — mutants (b2) and (d)**

(b2) delete the whole `data-display === "carousel"` block so the code falls through to the strip lookup (a "strip-mode-only implementation") → **case 2 RED**. (d) change `ownNodes(hit.c, ".tabs__dot", "[data-tabs]")` to `hit.c.querySelectorAll(".tabs__dot")` → **case 9 RED**, case 2 still green (a single carousel has no inner dots to grab — this is exactly why (d) needs case 9).

- [ ] **Step 6: Commit**

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add courses/static/courses/js/editor.js tests/test_e2e_preview_nested_locate.py
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "feat(editor): reveal a carousel slide containing the target

Branch on the container's data-display (exact 'carousel'), never on a
[data-tab-panel] ancestor -- the template emits that in BOTH modes, so
keying on it matches a carousel target, finds no button and silently
skips. Dots are index-keyed and own-scoped.

Falsified: b2 RED on e2e 2; d RED on e2e 9 (and green on e2e 2)."
```

---

### Task 5: The before/after branch (e2e 4)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`
- Verify (no edit expected): `courses/static/courses/js/editor.js` — Task 3 already wrote the `ba` branch

**Interfaces:**
- Consumes: Task 3's `revealOne` / `ownNodes`.
- Produces: nothing.

**Click path:** `.el-row__label` (the `.el-select` path). **No collapsed-`<details>` precondition** — before/after rows are always-open divs (`_element_row.html:233`), unlike tabs and two-column.

- [ ] **Step 1: Write the case**

Child in the **After** panel. Assert the toggle flipped: the After panel loses `hidden` and the Before panel gains it.

```python
@pytest.mark.django_db(transaction=True)
def test_click_flips_before_after_to_the_panel_holding_the_child(page, live_server):
    """e2e 4. Mutant (b4): drop the before/after toggle click -> RED.

    Click path: .el-row__label (.el-select). No <details> precondition -- ba rows are
    always-open divs.
    """
    # ... seed a BeforeAfterElement with a TEXT child in the AFTER slot
    #     (BeforeAfterElement.SLOT_IDS[1]) ...
    page.goto(editor_url)
    ba = f'[data-scope="preview"] [data-beforeafter]'
    after = f'{ba} .ba__panel[data-ba-side="after"]'
    before = f'{ba} .ba__panel:not([data-ba-side="after"])'
    page.wait_for_selector(f"{after}[hidden]")          # starts on Before

    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')

    page.wait_for_selector(f"{after}:not([hidden])")
    page.wait_for_selector(f"{before}[hidden]")
```

- [ ] **Step 2: Run to confirm it PASSES against the branch Task 3 already wrote**

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q -k "before_after"
```
Expected: 1 passed. (This is not a red-to-green step — the branch exists. Its value is the falsification below.)

- [ ] **Step 3: Falsify — mutant (b4)**

By hand, delete `if (toggle) toggle.click();` from `revealOne`'s `ba` branch. Run the command above → **RED**. Restore by hand → GREEN. Do not also comment out the whole branch — that is the same falsification with a wider blast radius, and every extra hand-edit/restore cycle is a chance to lose work.

**Do NOT add a mutant for un-scoping `ownToggle` or `ownPanels`.** Both are provably unobservable: the container's own `.ba__toggle` precedes any nested one in document order, and any nested `.ba__panel` containing the target is necessarily a *descendant* of one of `C`'s own panels, so document order returns the right node either way. An earlier spec draft carried a mutant (j) and a nested-before/after e2e for this; **both were deleted**. Do not reinstate them. Keep the ownership filter in the code regardless — it makes the result unique by construction rather than by relying on document order.

- [ ] **Step 4: Commit**

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add tests/test_e2e_preview_nested_locate.py
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "test(editor): e2e for revealing a before/after panel holding the target

Falsified: b4 RED."
```

---

### Task 6: Stacked ancestors (e2e 5) — mutants (e) and (f)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`

**Click path:** `.el-row__label` (`.el-select`).

**The fixture is tightly constrained; a looser one leaves both mutants alive.** All required:

1. **Two nested strip-mode tabs elements** — not spoiler + tabs. With one tabs ancestor, `target.closest(".tabs__section")` returns precisely the correct section and **(f) survives**.
2. **The inner tabs element must itself sit in a non-first tab of the outer.** `initOne` opens on tab 0, so if it sat in the outer's first tab the outer conceals nothing: the inner strip is already visible and measurable, `scrollIntoStrip` sets `scrollLeft > 0` even on the innermost-first build, and **(e) survives**.
3. **The outer must be strip mode**, not carousel — (e) depends on the outer *zeroing* the inner strip's geometry, which `display:none` does and a carousel does **not** (inactive slides keep intact rects at `opacity: 0`).
4. **The target in a late, non-first tab of the inner**, and **the inner strip overflowing** — enough tabs, or long enough labels, against the preview pane's width. `select()` early-returns on `i === active`, so a first-tab target proves nothing.

Seed with `_seed_tabs_element(unit, outer_tabs, …)` then `_seed_tabs_element(unit, inner_tabs, …, parent=outer_join, tab_id=<outer non-first tab id>)`.

- [ ] **Step 1: Write the case**

⚠️ **TWO nested `<details class="tabs-rows">` must be opened, outer first.** Constraint 2 puts the inner element in a non-first tab of the outer, so the outer's row group for that tab starts closed (`_element_row.html:82` opens only `open_slots` / `clip_active` / `forloop.first`); and the target in a late non-first tab of the inner means the inner's row group is closed too. Each is only reachable once the previous opens.

⚠️ **The overflow pre-flight must run AFTER the click, not before.** Constraint 2 means the inner subtree is `display:none` at load (strip mode puts `hidden` on the inactive `.tabs__panel`), so `scrollWidth` and `clientWidth` are both `0`, `0 > 0` is false, and a pre-click `wait_for_function` would time out **on a correct build**. Post-click both builds reveal both ancestors — only the *order* differs — so the overflow check still catches "the fixture stopped overflowing".

```python
    inner_scroller = (
        f'[data-scope="preview"] [data-tabs][data-tabs-eid="{inner_join.pk}"] '
        f'> .tabs__bar .tabs__scroller'
    )
    outer_sel = f'[data-scope="preview"] [data-tabs][data-tabs-eid="{outer_join.pk}"]'
    inner_sel = f'[data-scope="preview"] [data-tabs][data-tabs-eid="{inner_join.pk}"]'

    # Scope BOTH <details> clicks to their owning .el-row. `_seed_tabs_element`'s
    # docstring notes two elements may deliberately SHARE tab ids, and the inner
    # <details> is in the DOM (merely hidden) from load -- so an unscoped selector can
    # match two nodes and Playwright's strict mode raises. The fixture should also use
    # DISJOINT tab-id lists for outer and inner.
    page.click(
        f'.el-row[data-element="{outer_join.pk}"] '
        f'details.tabs-rows[data-tab-id="{outer_tab2_id}"] > summary'
    )
    page.click(
        f'.el-row[data-element="{inner_join.pk}"] '
        f'details.tabs-rows[data-tab-id="{inner_late_tab_id}"] > summary'
    )
    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')

    # BOTH ancestors revealed
    page.wait_for_function(
        """([sel, want]) => document.querySelector(sel)
              ?.getAttribute("data-tabs-active") === want""",
        arg=[outer_sel, outer_tab2_id],
    )
    page.wait_for_function(
        """([sel, want]) => document.querySelector(sel)
              ?.getAttribute("data-tabs-active") === want""",
        arg=[inner_sel, inner_late_tab_id],
    )
    # POST-CLICK pre-flight: if the strip stops overflowing this goes RED rather than
    # silently vacuous.
    assert page.evaluate(
        "(sel) => { const s = document.querySelector(sel);"
        "  return s.scrollWidth > s.clientWidth; }",
        inner_scroller,
    ), "fixture no longer overflows -- mutant (e) would be unfalsifiable"
    page.wait_for_function(
        "(sel) => document.querySelector(sel).scrollLeft > 0", arg=inner_scroller
    )
```

**Scope the scroller selector to the inner instance.** `scroller` is closure-local in `tabs.js`, so the test queries `.tabs__scroller`; and `initOne` does `container.insertBefore(bar, container.firstChild)`, so the **outer** instance's scroller comes **first** in DOM order — an unscoped `.first` reads the outer strip, whose `scrollLeft` is 0 on both builds. This is the **reverse** of the dot ordering (the carousel's `nav` is *appended*, so unscoped dots return the *inner* instance first); reasoning by analogy from one to the other gets it backwards.

- [ ] **Step 2: Run to verify it PASSES**

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q -k "stacked"
```

- [ ] **Step 3: Falsify — mutants (e) and (f)**

Run each with `-k "stacked"` so the RED being claimed is the pinned one.

- **(e)** reverse the reveal loop in `revealAncestors` to `for (var k = 0; k < chain.length; k++)` → RED on `scrollLeft > 0`.
- **(f)** in the tabs branch of `revealAncestors`, resolve `s` with `closest()` from the target instead of the ownership filter. Written concretely (the naive "replace the `owningNode(...)` call" leaves `t.all` referencing a dead binding and will not run):

  ```js
  } else if (node.hasAttribute("data-tabs")) {
    var all = ownNodes(node, ".tabs__section", "[data-tabs]");
    chain.push({ kind: "tabs", c: node, s: target.closest(".tabs__section"), all: all });
  }
  ```

  → RED: the **outer** container now resolves the **inner** section, so its `data-tabs-active` never advances.

Restore each by hand.

- [ ] **Step 4: Commit**

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add tests/test_e2e_preview_nested_locate.py
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "test(editor): e2e for a stacked tabs-in-tabs reveal chain

Pins outermost-first ordering and per-ancestor node resolution.

Falsified: e RED, f RED (both scoped -k stacked)."
```

---

### Task 7: The position assertion (e2e 6) — mutant (g)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`

**Click path:** `.el-row__label` (`.el-select`).

**Fixture — pin the container.** The target must sit in an **always-visible** nested position: a **callout child** (as Task 8 uses). It must **not** be in a tab, a carousel slide, a closed spoiler or an After panel — those give a zero or degenerate pre-click rect, so the pre-click `delta` comes out as roughly `-(paneTop + pad)`, i.e. negative, and the `> 400` probe fails **on a correct build**. This is the same trap Task 9 documents; case 6 must avoid it rather than handle it.

**Position-observability constraints:** the target must sit **well below the pane fold** **and** carry enough content after it that `.pane-body` can actually scroll it to the top. Without the first, both builds read "already at the top" and (g) survives; without the second, the target can never reach the top even on a correct build and the case goes falsely red.

Concretely: `_seed_filler(unit, 8)` **before** the callout and `_seed_filler(unit, 8)` **after** it (Task 3's helper — each filler element is ~40 lines tall, so 8 comfortably exceeds a viewport). The pre-click `> 400` probe self-checks the leading run; **add this assertion for the trailing run**, or a too-short tail makes the `|delta| <= 4` poll time out with a message that reads like a product bug rather than a fixture bug:

```python
    scrollable = page.evaluate(
        '() => { const b = document.querySelector(\'[data-scope="preview"] .pane-body\');'
        "  return b.scrollHeight - b.clientHeight; }"
    )
    assert scrollable > page.evaluate(delta, target_sel), (
        "trailing filler too short -- the target can never reach the pane top"
    )
```

**"The pane's content top"** is `.pane-body`'s rect top **plus its computed `padding-top`** — `alignTopInPane`'s own arithmetic. The bare bounding-box top is off by the padding, which can exceed the 4 px tolerance.

**Settling: this case polls.** It uses `wait_for_function` on the computed delta with a timeout comfortably past the 500 ms backstop. It does **not** use `prefers-reduced-motion`. Do not mix the two silently.

- [ ] **Step 1: Write the case**

```python
    delta = """(sel) => {
      const t = document.querySelector(sel);
      const b = t.closest(".pane-body");
      const pad = parseFloat(getComputedStyle(b).paddingTop) || 0;
      return t.getBoundingClientRect().top - b.getBoundingClientRect().top - pad;
    }"""
    target_sel = (
        f'[data-scope="preview"] .prev-el[data-element-id="{child_join.pk}"]'
    )
    assert page.evaluate(delta, target_sel) > 400   # pre-click: far from the top
    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')
    page.wait_for_function(
        f"(sel) => Math.abs(({delta})(sel)) <= 4", arg=target_sel, timeout=5000
    )
```

- [ ] **Step 2: Run to verify it PASSES**

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q -k "position"
```

- [ ] **Step 3: Falsify — mutant (g), scoped**

By hand, make `scrollPreviewTo` `return;` immediately after `revealAncestors(target)` (reveal only, no scroll). Run with **`-k "position"`** → RED.

Scoping matters: this mutant also reddens e2e 8's scroll assertion and any other position assertion, so an unscoped run reports several reds and it is not obvious which one is the falsification.

- [ ] **Step 4: Record the settle time**

While the case is green, note how long the delta takes to settle (add a temporary timing read, or observe the `wait_for_function` duration). **Record it in the PR body.** If it exceeds the 500 ms backstop for the nested-carousel case in Task 4/9, the **only permitted remedy** is an additional re-align bound to `libli:reveal` — never a longer or extra timeout. Remove any temporary timing code before committing.

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add tests/test_e2e_preview_nested_locate.py
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "test(editor): e2e pinning the scroll position after a nested reveal

Falsified: g RED (scoped -k position). Settle time recorded for the PR body."
```

---

### Task 8: Hover on a nested child (e2e 7) — mutant (h)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`

**No click path — this is the HOVER path** (`mouseenter` on `.el-row[data-element]`).

**Pin the target to a CALLOUT child.** Callout child rows render in an always-open `<div class="el-row__callout">`, so no `<details>` precondition applies. **Do not use two-column here:** `_element_row.html:141` wraps column children in `<details class="columns-rows">` whose only `open` clauses are `open_slots` and `clip_active` — **no `forloop.first`** — so in a fresh Playwright context *both* column slots start collapsed and `page.hover()` would time out on a not-visible locator. (The spec says this verbatim; an earlier draft of this task wrongly called two-column rows always-open.)

The child must also be **always visible in the preview**, which a callout child is: hover deliberately does **not** trigger the walk, so a hidden target would be outlined invisibly and the case would prove nothing.

Hover is fixed by Task 1 alone (`setHighlight` needs no change — the same selector now matches). But **a render test cannot prove `setHighlight` reaches a nested node**, which is why this case exists.

- [ ] **Step 1: Write the case**

```python
@pytest.mark.django_db(transaction=True)
def test_hover_outlines_a_nested_child(page, live_server):
    """e2e 7. Mutant (h): scope setHighlight to `.prev-inner > .prev-el` -> RED."""
    page.goto(editor_url)
    target = f'[data-scope="preview"] .prev-el[data-element-id="{child_join.pk}"]'
    page.hover(f'.el-row[data-element="{child_join.pk}"]')
    page.wait_for_selector(f"{target}.prev-el--hl")
```

- [ ] **Step 2: Run to verify it PASSES**

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q -k "hover"
```

- [ ] **Step 3: Falsify — mutant (h)**

By hand, change `setHighlight`'s selector from `'.prev-el[data-element-id="' + id + '"]'` to `'.prev-inner > .prev-el[data-element-id="' + id + '"]'` (top-level only). Run with `-k "hover"` → RED. Restore by hand.

- [ ] **Step 4: Commit**

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add tests/test_e2e_preview_nested_locate.py
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "test(editor): e2e for hover-outlining a nested child

A render test cannot prove setHighlight reaches a nested node.

Falsified: h RED."
```

---

### Task 9: Degraded ancestor (e2e 8) — mutant (i)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`

**Click path:** `.el-row__label` (`.el-select`). The target is inside a spoiler (always-open div row), so no `<details class="tabs-rows">` precondition applies.

**Fixture: a bailed carousel nested inside a closed spoiler.**

Force the bail with a bad `window.TABS_I18N` key — the same **accessor** injection `tests/test_e2e_tabs.py:1706-1740` uses. A plain global write is overwritten by the inline script that assigns `TABS_I18N` wholesale (`editor.html:212`) before the deferred `tabs.js`, so the carousel would initialise normally and the case would fail against a **correct** build.

⚠️ **`add_init_script` only affects navigations that happen AFTER it**, and `_login` itself calls `page.goto`. Place it before the editor navigation, exactly as below — putting it after `page.goto(editor_url)` leaves the carousel healthy, dots present, `dot.click()` never throwing, and **mutant (i) unfalsifiable while the case stays green**:

```python
    _login(page, live_server, "pa")
    page.add_init_script(
        """
      Object.defineProperty(window, "TABS_I18N", {
        configurable: true,
        get() { return this.__t; },
        set(v) { this.__t = Object.assign({}, v, {slidePos: 42}); },
      });
    """
    )
    page.goto(editor_url)          # AFTER the injection

    # PRE-FLIGHT: prove the bail actually took. If the injection ever stops biting
    # (a renamed i18n key, a t() that tolerates a non-string), the carousel
    # initialises, the walk clicks a real dot, this case passes -- and mutant (i)
    # can never go red because `dot` is never undefined.
    car = f'[data-scope="preview"] [data-tabs][data-tabs-eid="{carousel_join.pk}"]'
    page.wait_for_function(
        """(sel) => { const c = document.querySelector(sel);
             return !!c && c.dataset.tabsReady === "1"
                    && !c.classList.contains("tabs--carousel")
                    && !c.classList.contains("tabs--js"); }""",
        arg=car,
    )
    assert page.locator(f"{car} .tabs__dot").count() == 0, "carousel did not bail"
```

The injection is **global**, which is why the outer ancestor must be a **spoiler, not tabs** — it would bail an outer tabs instance too.

**Both other candidate fixtures are dead ends; do not substitute them.** `killOne` does `removeAttribute("hidden")` on **every** owned panel, so afterwards no `.ba__panel` carries `hidden`, the collection predicate never fires and the walk never reaches the missing-control branch. A single-slide carousel is **unreachable from data** (`TabsElement.MIN_TABS == 2`, `TabsElementForm.clean_data` rejects fewer, `normalize_data` pads to 2 on read).

**The scroll assertion is the discriminator, not the spoiler-open one.** Reveal runs outermost-first, so on the throwing build the spoiler has **already opened** before the inner carousel throws — that half passes on the broken build. So this case needs the **fixture-size half** of Task 7's constraints: filler content before the spoiler (several viewport heights) and after it.

**The pre-click probe differs from case 6.** The target starts inside a closed `<details>`, whose subtree is `content-visibility`-skipped, so its rect is stale or degenerate. Probe the **spoiler container** instead — and scope `.pane-body` to the preview, because the editor page has **two** (`_editor_scope.html:40` and `_preview.html:4`) and an unscoped `document.querySelector(".pane-body")` returns the editor scope's.

**Settling: this case polls**, exactly as Task 7 does. Same `delta` helper, same 4 px tolerance, same "do not mix with `prefers-reduced-motion`" rule.

- [ ] **Step 1: Write the case**

```python
    delta = """(sel) => {
      const t = document.querySelector(sel);
      const b = t.closest(".pane-body");
      const pad = parseFloat(getComputedStyle(b).paddingTop) || 0;
      return t.getBoundingClientRect().top - b.getBoundingClientRect().top - pad;
    }"""
    spoiler_sel = '[data-scope="preview"] details.spoiler'
    target_sel = f'[data-scope="preview"] .prev-el[data-element-id="{child_join.pk}"]'

    # PRE-CLICK probe: the target's own rect is unusable (closed <details>), so probe
    # the spoiler container, and scope .pane-body to the PREVIEW pane.
    assert page.evaluate(
        '() => document.querySelector(\'[data-scope="preview"] .pane-body\').scrollTop'
    ) == 0
    assert page.evaluate(delta, spoiler_sel) > 400

    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')

    page.wait_for_selector(f"{spoiler_sel}[open]")   # passes on BOTH builds
    # THE DISCRIMINATOR:
    page.wait_for_function(
        f"(sel) => Math.abs(({delta})(sel)) <= 4", arg=target_sel, timeout=5000
    )
```

- [ ] **Step 2: Run to verify it PASSES**

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q -k "degraded"
```

- [ ] **Step 3: Falsify — mutant (i), scoped**

By hand, in `revealOne`'s carousel branch replace `if (dot) dot.click();` with `dot.click();` (throws on the missing dot — `bail()` has removed the whole `nav`). Run with `-k "degraded"` → **RED on the scroll assertion** (the `[open]` wait still passes). Restore by hand.

- [ ] **Step 4: Commit**

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add tests/test_e2e_preview_nested_locate.py
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "test(editor): e2e for a bailed carousel inside a closed spoiler

The walk must SKIP a control-less ancestor, not throw. The scroll assertion
is the discriminator -- the spoiler-open half passes on the broken build.

Falsified: i RED (scoped -k degraded)."
```

---

### Task 10: The post-op path (e2e 10, e2e 11) — mutant (k)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`

⚠️ **Every `editor.js` line number below is pre-Task-3.** Task 3 inserts ~90 lines above `scrollPreviewTo`, so by the time this task runs each of these has shifted down by roughly that much. **Anchor on the code, never the number** — `applyFragments(res.text)` inside the `form[data-op]` submit handler, the `.el-select` handler, the row-body handler. (The same caution applies to Task 8's `setHighlight` mutant, which escapes only by sitting *above* the insertion point.)

There are **three** `scrollPreviewTo` call sites, and the walk lives inside it, so all three inherit it: `editor.js:367` (after **any** `form[data-op]` submit — save, move, duplicate, delete, incl. the 409/422 branches), `:451` (`.el-select`), `:463` (row body). **The post-op reveal is intended**: after saving or moving a nested element, revealing its own tab is the useful behaviour and matches the scroll that site already performs. `restoreActiveTabs` re-stamps the author's previous tab and the walk then overrides it, so after an op the visible tab is the **operated element's**. This is a deliberate behaviour change on every element op.

**The collapsed-`<details>` precondition applies to e2e 10 ONLY** — its target lives in a non-first tab, so open `details.tabs-rows[data-tab-id="<tab>"] > summary` first. **e2e 11 has no such precondition:** its target is inside a spoiler, and spoiler child rows render in an always-open `<div class="el-row__spoiler">` (`_element_row.html:192`) — there is no `details.tabs-rows` in that row at all, so adding the click would select zero nodes and fail on a correct build.

- [ ] **Step 1: Write e2e 10 — pins the behaviour change**

Assert the post-op `data-tabs-active` is the operated element's tab (A), not the author's previous one (B).

**The fixture ordering is load-bearing; the naive one is self-contaminating.** Saving a nested element requires first *opening* its edit form — which is the `.el-select` path, which itself runs the walk and stamps A. `applyFragments` then opens with `captureActiveTabs()`, so the submit carries A forward **even with the post-op walk deleted entirely**. Use **one** of:

- **(preferred) a move/duplicate `form[data-op]` from the row actions**, which reaches `editor.js:367` with **no form-open at all**, so nothing stamps A beforehand; or
- establish B **after** the edit form is open and before the submit, by clicking a preview `.tabs__tab`. That is verified not to re-enter `scrollPreviewTo`: the handlers at `editor.js:444` and `:462` require `.el-select` / `.el-row[data-element]` ancestry, which a preview tab button does not have.

Either way, **capture the pre-submit `data-tabs-active` and assert it is B**, so the case proves its own setup took rather than assuming it.

- [ ] **Step 2: Write e2e 11 — the fixture for mutant (k)**

Same `editor.js:367` path, but the nested element sits inside a **closed spoiler**. Assert the ancestor is revealed **after** the op (`details.spoiler[open]`).

**A tabs ancestor cannot kill (k)**: on the mutated build the walk runs against the *old* preview and `select()` stamps A there; `applyFragments` opens with `captureActiveTabs()`, reading that just-mutated pane, so `restoreActiveTabs` puts A on the rebuilt preview and `initOne` opens it — `data-tabs-active` and `aria-selected` end up byte-identical on both builds. A spoiler has no such carry (persistence is tabs-only, by decision), so a reveal done on the pre-swap DOM is discarded and the mutant goes red.

- [ ] **Step 3: Run to verify both PASS**

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q -k "post_op"
```

- [ ] **Step 4: Falsify — mutant (k), written concretely**

The mutant is "the walk runs against the pre-swap DOM on the op path". `revealAncestors` is called from inside `scrollPreviewTo`, and `applyFragments(res.text)` is at `editor.js:363` in the submit handler — so it cannot simply be "moved" without deciding the fate of the in-`scrollPreviewTo` call. **Apply it exactly like this**, by hand:

1. In the `form[data-op]` submit handler, **immediately before** `applyFragments(res.text)` (`editor.js:363`), insert:
   ```js
   revealAncestors(root.querySelector('.prev-el[data-element-id="' + keepId + '"]'));
   ```
2. In `scrollPreviewTo`, guard the existing call so it does **not** run twice:
   ```js
   if (!window.__mutantK) revealAncestors(target);
   ```
   and set `window.__mutantK = true;` at the top of the op handler, **clearing it (`window.__mutantK = false;`) in the same `.then` after `applyFragments` returns**. Without the reset the latch is page-lifetime: every later `scrollPreviewTo` on that page — including the `.el-select` and row-body paths — would also skip the walk. It happens not to matter (each case performs one op), but an uncleared latch does not do what this step claims. Any equivalent guard is fine; the point is that the walk runs **once**, against the **pre-swap** DOM, on this path only.

Do **not** simply delete the `scrollPreviewTo` call: that also reddens e2e 1, 3, 5 and 8, and the "e2e 11 RED, e2e 10 still green" asymmetry — which is the whole point of the two cases — stops being readable.

Run with **`-k "post_op"`** → **e2e 11 RED, e2e 10 still GREEN**. Restore both edits by hand.

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add tests/test_e2e_preview_nested_locate.py
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "test(editor): e2e for the post-op reveal and its pre-swap mutant

e2e 10 pins the deliberate behaviour change (the operated element's tab wins
over the author's previous one). e2e 11 uses a SPOILER because a tabs
ancestor cannot kill mutant (k) -- captureActiveTabs launders it.

Falsified: k RED on e2e 11, GREEN on e2e 10 (scoped -k post_op)."
```

---

### Task 11: Comment amendment, byte-identity, screenshots, format, branch gate

**Files:**
- Modify: `courses/static/courses/js/tabs.js` (the `libli:reveal` dispatcher comment, **line-count neutral**)

- [ ] **Step 1: Amend the now-false comment in `tabs.js`**

The walk makes `editor.js` a third `libli:reveal` dispatcher and makes a spoiler dispatch in the editor preview. The comment above `container.addEventListener("libli:reveal", scheduleMeasure)` currently reads:

```js
    // Reveal-gates and outer tab panels are the only two dispatchers in the codebase.
    // A <details>-based spoiler dispatches nothing — there the ResizeObserver is what
    // rescues the measurement when the subtree stops being skipped.
```

Replace with **exactly three lines** (line-count neutral, per this repo's citation-rot convention — a line-inserting diff rots citations in untouched files):

```js
    // Reveal-gates, outer tab panels, and editor.js's preview reveal-walk dispatch.
    // A <details>-based spoiler dispatches nothing of its own on a student page —
    // there the ResizeObserver rescues the measurement when the subtree unskips.
```

This repo already carries one stale-comment trap (`courses.css:1982-1985`, which the spec flags); do not create a second.

- [ ] **Step 2: Byte-identity pre-merge verification**

**Not a test** — a suite running on the post-change tree has no "before" render to diff against.

The diff **must be normalized first or it can never come out clean**: `templates/base.html:62` and `:139` each emit `{% csrf_token %}`, and `_lesson_article.html:26` a third, and Django re-masks the token with a fresh salt on **every** render.

**The mechanism, concretely** (the plan owes this — "diff master against the branch" is not executable on its own):

**Step 2a — write the render script.** Create `scripts/render_student_page.py` (untracked; delete it before the final commit). It renders a student lesson page holding all five container types and writes it to a path given in `RENDER_OUT`, with the CSRF tokens normalized.

This works **only because Task 1's `_containers` mints fixed slot ids** (`_fixed_tabs_data` / `_fixed_columns_data`). With `default_data()`'s `secrets.token_hex(3)` ids the control diff below could never come out empty, and the "fix" would be regexing out the very attributes near the wrappers under test.

```python
"""Throwaway: render a student lesson page to a file, CSRF-normalized.
Usage: uv run pytest scripts/render_student_page.py -p no:randomly -q -s
Writes to the path in env RENDER_OUT.
"""
import os
import re

import pytest
from django.urls import reverse

# reuse the fixture builder from the render tests
from courses.tests.test_preview_nested_markers import _containers
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_render(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _containers(unit)   # fixed slot ids -- see _fixed_tabs_data/_fixed_columns_data
    html = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    # CSRF is re-masked with a fresh salt on every render. Slot ids are already fixed
    # by the fixture. If the control diff below is not empty, add whatever else it
    # turns up here rather than trusting the result -- do NOT normalize away
    # data-element-id or the child class attributes, which are what is under test.
    html = re.sub(
        r'name="csrfmiddlewaretoken" value="[^"]*"',
        'name="csrfmiddlewaretoken" value="NORMALIZED"',
        html,
    )
    open(os.environ["RENDER_OUT"], "w", encoding="utf-8").write(html)
```

**Step 2b — get a master-side render.** A second worktree, detached at `origin/master`. ⚠️ **A fresh worktree has no `.env`** — copy it in, or the render dies on settings. Run every git command from the **main repo**, never from inside a worktree (master-side git is refused from a worktree session):

```bash
MAIN="C:/Users/krzys/Documents/Python/own/libli"
BASE="C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/byteid-master"
git -C "$MAIN" worktree add --detach "$BASE" origin/master
cp "$MAIN/.env" "$BASE/.env"
cp "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate/scripts/render_student_page.py" "$BASE/scripts/"
cp "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate/courses/tests/test_preview_nested_markers.py" "$BASE/courses/tests/"
```

(The test module is copied because master has no `_containers` helper. It only builds fixtures; it does not affect the render.)

**Step 2c — the control diff MUST come out empty first.** Two renders of the *same* tree. This is what proves the normalization sufficient; without it a clean branch diff means nothing and a dirty one is uninterpretable.

⚠️ **No `cd`** (the Global Constraints forbid it — the harness resets cwd between commands, and `uv run` resolves its project from cwd, so a failed `cd` would silently render the *branch* tree twice and make the control diff meaningless). Use `uv run --directory`.

⚠️ **No `/tmp`.** `RENDER_OUT` is consumed by CPython **for Windows**, where `/tmp/x.html` is drive-relative and resolves to `C:\tmp\x.html` (usually nonexistent → `FileNotFoundError`), while Git Bash's `diff` reads the MSYS `/tmp` mount — a different directory. Use absolute scratchpad paths.

```bash
OUT="C:/Users/krzys/AppData/Local/Temp/claude/C--Users-krzys-Documents-Python-own-libli/c028a1f9-227d-465d-9183-8748c462317a/scratchpad"
RENDER_OUT="$OUT/master_a.html" uv run --directory "$BASE" pytest scripts/render_student_page.py -p no:randomly -q
RENDER_OUT="$OUT/master_b.html" uv run --directory "$BASE" pytest scripts/render_student_page.py -p no:randomly -q
diff "$OUT/master_a.html" "$OUT/master_b.html" && echo "CONTROL DIFF EMPTY -- normalization sufficient"
```

If it is **not** empty, add the offending pattern to the normalizer and repeat. Do not proceed until it is empty.

**Step 2d — the real diff.**

```bash
WT="C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate"
RENDER_OUT="$OUT/branch.html" uv run --directory "$WT" pytest scripts/render_student_page.py -p no:randomly -q
diff "$OUT/master_a.html" "$OUT/branch.html" && echo "BYTE-IDENTICAL"
```

Expected: empty. **Record the outcome — control diff empty, branch diff empty — in the PR body.**

**Step 2e — clean up.** `git -C "$MAIN" worktree remove --force "$BASE"`, and delete `scripts/render_student_page.py` from the branch worktree. Confirm `git status --short` does not list it.

- [ ] **Step 3: Light + dark screenshots of the highlight ring**

`.prev-el--hl` is an outset double ring (`0 0 0 3px` + `0 0 0 5px`) that has only ever been drawn on top-level `<section class="prev-el">` nodes owning the full prose column. It will now be drawn on tightly-packed `.tabs__child` / `.twocolumn__child` / `.callout__child` boxes, where an outset ring can collide with a neighbour or its container's edge.

Take **light and dark** screenshots of a hovered nested child in at least a **two-column** and a **callout**. Judge the dark one on its own terms, not by assuming it follows the light one. For dark, drive it via `user.theme`, **not** the cookie.

**Model it on `tests/capture_nested_question_screenshots.py`**, which already enumerates the exact selectors needed (`.callout__children > .callout__child` and `.twocolumn__column:first-child > .twocolumn__child`, lines 78-85) and handles login + theming. Adapt it to: navigate to the **editor**, `page.hover()` the nested `.el-row`, then `page.screenshot()` while the hover is held (the hover persists until the pointer moves, so capture directly after — do not click anything in between).

⚠️ **The two-column shot needs an extra step the model does not have.** `capture_nested_question_screenshots.py` drives the **student** page, where no `<details>` exists. On the **editor** page the two-column child's row sits inside a closed `<details class="columns-rows">` (no `forloop.first` clause), so `page.hover()` times out before any screenshot is taken. Click `details.columns-rows[data-column-id="<id>"] > summary` first. The **callout** shot needs no such step (always-open div row).

Four expected files, written to the scratchpad directory (not the repo):
`hover-callout-light.png`, `hover-callout-dark.png`, `hover-twocolumn-light.png`, `hover-twocolumn-dark.png`.

Look at all four. What to judge: the outset ring (`0 0 0 3px` + `0 0 0 5px`) has only ever been drawn on top-level nodes owning the full prose column; on a tightly-packed child it can collide with a neighbour or the container's edge. Record the verdict in the PR body.

- [ ] **Step 4: Format and lint**

```bash
uv run ruff format .
uv run ruff check --no-cache .
uv run ruff format --check .
```
`ruff format` runs **last**, after every other edit; `--check` is a separate CI gate.

- [ ] **Step 5: Branch gate — the full suite**

```bash
docker ps --filter name=libli-test-db
uv run pytest -p no:randomly -q
uv run pytest -m e2e -n 2 -p no:randomly -q
```

**Grep the summary line — a backgrounded pytest has reported exit 0 with `1 failed`.** Do not trust the exit code alone. Use `-n 2` for e2e, not `-n 8` (teardown-bound; 8 is slower).

Confirm `git status --short` shows **no `locale/` changes**.

- [ ] **Step 6: Commit**

⚠️ **Stage every path `ruff format .` may have touched**, not just `tabs.js`. Tasks 1–10 committed three test modules *before* Step 4 ran, so any reflow ruff applied to them is sitting unstaged in the working tree — and would leave the branch tip failing the very `ruff format --check .` gate Step 4 just ran.

```bash
WT="C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate"
git -C "$WT" add courses/static/courses/js/tabs.js courses/static/courses/js/editor.js \
  courses/tests/test_preview_nested_markers.py courses/tests/test_preview_marker_css.py \
  tests/test_e2e_preview_nested_locate.py
git -C "$WT" commit -m "docs(tabs): editor.js's reveal-walk is a third libli:reveal dispatcher

Line-count neutral, per the citation-rot convention. Includes any ruff
format reflow of the test modules committed in earlier tasks."
```

- [ ] **Step 7: Confirm the tree is clean**

```bash
git -C "$WT" status --short
```
Expected: **empty**. A non-empty tree here means either a ruff reflow was missed above, or `scripts/render_student_page.py` was not deleted in Step 2e. Neither may be left behind.

---

## Mutant ↔ test map (the falsification ledger)

| Mutant | Description | Test that must go RED | Task |
|---|---|---|---|
| a1 | drop the marker from ONE container template | render test 1 | 1 |
| a2 | emit `data-element-id` without the `prev-el` class | render test 1 | 1 |
| c1 | drop the `{% if editor_preview %}` gate | render test 2 (student) | 1 |
| c2 | gate the attribute but not the class | render test 2 (student) | 1 |
| l1 | add `display: block` to `.prev-el` | `test_prev_el_declares_no_display` | 2 |
| l2 | add `display: block` to `.prev-el--hl` | `test_prev_el_hl_declares_no_display` | 2 |
| b1 | drop the strip reveal step | e2e 1 | 3 |
| b3 | drop the spoiler `open = true` step | e2e 3 | 3 |
| b2 | delete the carousel branch (strip-only impl) | e2e 2 | 4 |
| d | un-scope the `.tabs__dot` lookup | e2e 9 (**not** e2e 2) | 4 |
| b4 | drop the before/after toggle click | e2e 4 | 5 |
| e | reveal innermost-first | e2e 5 | 6 |
| f | resolve `s` with `closest()` from the target | e2e 5 | 6 |
| g | skip the scroll (reveal only) | e2e 6 | 7 |
| h | scope `setHighlight` to top-level | e2e 7 | 8 |
| i | throw instead of skip on a missing control | e2e 8 (**scroll** assertion) | 9 |
| k | run the walk before `applyFragments` | e2e 11 (**not** e2e 10) | 10 |

**Deliberately uncovered — do not invent tests:** the `[data-scope="preview"]` climb bound (nothing collectible sits above it on today's page); the synchronous-cascade ordering (identical settled state, only the transient differs); un-scoping `ownToggle`; un-scoping `ownPanels`.

**Falsification runs are `-k`-scoped** wherever a mutant reddens more than its pinned case — (e), (f), (g), (i), (k) all do. An unscoped run reports several reds and it stops being obvious which one is the falsification.

⚠️ **A `-k` filter is inert unless the test's NAME contains its token.** If a case is named something that misses the token, `-k` selects nothing and pytest reports exit 5 / "no tests ran" — the same false-green this plan warns about for the missing `e2e` marker. **These names are mandatory**, not suggestions:

| e2e | Mandated test function name | `-k` token |
|---|---|---|
| 1 | `test_click_reveals_a_child_in_a_non_first_strip_tab` | `strip_tab` |
| 2 | `test_click_reveals_a_child_in_a_non_first_carousel_slide` | `carousel` |
| 3 | `test_click_opens_a_closed_spoiler_around_the_child` | `spoiler` |
| 4 | `test_click_flips_before_after_to_the_panel_holding_the_child` | `before_after` |
| 5 | `test_stacked_tabs_reveal_outermost_first` | `stacked` |
| 6 | `test_position_aligns_the_nested_target_to_the_pane_top` | `position` |
| 7 | `test_hover_outlines_a_nested_child` | `hover` |
| 8 | `test_degraded_carousel_is_skipped_not_thrown_on` | `degraded` |
| 9 | `test_nested_carousel_reveals_the_outer_instance` | `nested_carousel` |
| 10 | `test_post_op_reveal_wins_over_the_restored_tab` | `post_op` |
| 11 | `test_post_op_reveal_through_a_spoiler` | `post_op` |

Note e2e 2 and e2e 9 both contain `carousel`, so Task 4's `-k "carousel"` selects both — which is what that task wants. Mutant (d) is scoped with `-k "nested_carousel"` to isolate e2e 9.

**Records owed to the PR body** (collected across tasks, assembled in Task 11): the Task 1 sweep outcome and the four Step-1c confirmations; the observed settle time from Task 7 (and, if it exceeds the 500 ms backstop, the `libli:reveal`-bound re-align as the **only** permitted remedy — never a longer timeout); the byte-identity control-diff-empty + branch-diff-empty result; and the four hover screenshots' verdict.

## Self-review notes

- **Spec coverage:** Part 1 → Task 1. CSS guard → Task 2. Part 2's four reveal branches → Tasks 3–5. Ordering/resolution → Task 6. Position → Task 7. Hover → Task 8. Degraded → Task 9. Post-op → Task 10. Comment/byte-identity/screenshots/format → Task 11. All 11 e2e cases, both render tests, the CSS guard and all 17 ledger rows are assigned (the spec's 16 mutants, with (l) split into l1/l2).
- **Naming consistency:** `ownNodes(container, selector, ownerSelector)`, `owningNode(container, selector, ownerSelector, target)`, `revealAncestors(target)`, `revealOne(hit)` — used identically in Tasks 3, 4, 5, 6, 9 and in the mutant table.
- **`hit.all`** is set only on the `tabs` branch and read only by the carousel step; the strip step uses `hit.s` alone.
