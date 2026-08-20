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
- `courses/tests/test_nested_question_nojs_feedback.py` — slices on child-class names; the class attribute still *starts* with the same literal.

Record the outcome in the commit message. If any hit contradicts the above, **stop and report** — do not adjust the pinned shape.

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


def _containers(unit):
    """One of each of the five containers at top level, each holding one text child.

    Fixtures are built with DIRECT Element(parent=...) rows -- as
    test_image_size_render.py does -- NOT through builder.resolve_scope, whose
    clause 3/4 depth rules would couple this test to the nesting policy it is not
    testing.

    Returns {child_class: child_join_pk}.
    """
    out = {}

    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, parent=None)
    tab_id = tabs.data["tabs"][0]["id"]
    out["tabs__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-tab"), parent=tabs_join, tab_id=tab_id
    ).pk

    two = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
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
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
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

    html = client.get(
        reverse("courses:unit_detail", kwargs={"slug": course.slug, "pk": unit.pk})
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

> **If `courses:unit_detail` is not the student URL name**, find it with
> `grep -rn "name=\"unit_detail\"\|def unit_detail" courses/urls.py courses/views.py`
> and use the real one. Do not invent a URL.

- [ ] **Step 2b: Run the tests to verify they FAIL**

```bash
docker ps --filter name=libli-test-db --format "{{.Names}} {{.Status}}"
uv run pytest courses/tests/test_preview_nested_markers.py -p no:randomly -q
```
Expected: the three editor/depth tests FAIL (no `.prev-el` on child wrappers); the student test PASSES already (nothing is emitted yet — that is correct and expected; it becomes meaningful only once Step 3 lands, and its mutants are falsified in Step 5).

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
Expected: 4 passed.

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
```

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

    Click path: the ROW BODY (no fragment swap), so this case covers the second
    path. Target a non-button region of the row, per the module docstring.
    """
    page.goto(editor_url)
    det = f'[data-scope="preview"] details.spoiler'
    assert page.get_attribute(det, "open") is None      # closed to begin with
    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__top')
    page.wait_for_selector(f"{det}[open]")
```

- [ ] **Step 2: Run to verify they FAIL**

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q
```
Expected: both FAIL — the tab never changes, the `<details>` never opens.

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

Then change `scrollPreviewTo`'s guard (line 236-237) from:

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
- Modify: `courses/static/courses/js/editor.js` — no change needed if Task 3's `ba` branch is complete; **verify** it is
- Modify: `tests/test_e2e_preview_nested_locate.py`

- [ ] **Step 1: Write the failing e2e case 4** — child in the **After** panel; assert the toggle flipped (the After panel loses `hidden`, the Before panel gains it).

- [ ] **Step 2: Run to verify it FAILS** — temporarily comment out the `ba` branch body in `revealOne` by hand to confirm the case is discriminating, then restore. (The branch already exists from Task 3, so this step is a *verification that the test can fail*, not a red-to-green.)

```bash
uv run pytest tests/test_e2e_preview_nested_locate.py -m e2e -p no:randomly -q -k "before_after"
```

- [ ] **Step 3: Confirm it PASSES with the branch restored**

- [ ] **Step 4: Falsify — mutant (b4)** — delete the `toggle.click()` line → case 4 RED.

**Do NOT add a mutant for un-scoping `ownToggle` or `ownPanels`.** Both are provably unobservable (the container's own toggle precedes any nested one in document order; any nested `.ba__panel` containing the target is necessarily a descendant of one of `C`'s own panels, so document order returns the right node either way). An earlier spec draft carried a mutant (j) and a nested-before/after e2e for this; both were **deleted**. Do not reinstate them. Keep the ownership filter in the code regardless — it makes the result unique by construction rather than by relying on document order.

- [ ] **Step 5: Commit**

---

### Task 6: Stacked ancestors (e2e 5) — mutants (e) and (f)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`

**The fixture is tightly constrained; a looser one leaves both mutants alive.** All of the following are required:

1. **Two nested strip-mode tabs elements** — not a spoiler + tabs. With only one tabs ancestor, `target.closest(".tabs__section")` returns precisely the correct section and **(f) survives**.
2. **The inner tabs element must itself sit in a non-first tab of the outer.** `initOne` opens on tab 0, so if it sat in the outer's first tab the outer conceals nothing: the inner strip is already visible and measurable, `scrollIntoStrip` sets `scrollLeft > 0` even on the innermost-first build, and **(e) survives**.
3. **The outer must be strip mode**, not carousel — (e) depends on the outer *zeroing* the inner strip's geometry, which `display:none` does and a carousel does **not** (inactive slides keep intact rects at `opacity: 0`).
4. **The target in a late, non-first tab of the inner**, and **the inner strip overflowing** (`scroller.scrollWidth > scroller.clientWidth`) — enough tabs, or long enough labels, against the preview pane's width. The only geometry `select()` writes is `scroller.scrollLeft`; on the broken build every term is 0, but on the **correct** build it also stays 0 unless the strip overflows *and* the target tab lies outside the visible range.

- [ ] **Step 1: Write the case with a pre-flight overflow assertion**

```python
    inner = (
        f'[data-scope="preview"] [data-tabs][data-tabs-eid="{inner_join.pk}"] '
        f'> .tabs__bar .tabs__scroller'
    )
    # PRE-FLIGHT: if the strip stops overflowing, this test must go RED rather than
    # silently vacuous.
    page.wait_for_function(
        "(sel) => { const s = document.querySelector(sel);"
        "  return s && s.scrollWidth > s.clientWidth; }",
        arg=inner,
    )
    # ... open the nested <details>, click the row ...
    page.wait_for_function(
        "(sel) => document.querySelector(sel).scrollLeft > 0", arg=inner
    )
```

**Scope the scroller selector to the inner instance.** `scroller` is closure-local in `tabs.js`, so the test queries `.tabs__scroller`; and `initOne` does `container.insertBefore(bar, container.firstChild)`, so the **outer** instance's scroller comes **first** in DOM order — an unscoped `.first` reads the outer strip, whose `scrollLeft` is 0 on both builds. This is the **reverse** of the dot ordering (the carousel's `nav` is *appended*, so unscoped dots return the *inner* instance first); reasoning by analogy from one to the other gets it backwards.

Also assert **both** ancestors revealed (outer `data-tabs-active` and inner `data-tabs-active`).

- [ ] **Step 2: Run to verify it PASSES** on the current (correct) build.

- [ ] **Step 3: Falsify — mutants (e) and (f)**

(e) reverse the reveal loop to `for (var k = 0; k < chain.length; k++)` (innermost-first) → RED on the `scrollLeft > 0` assertion.
(f) replace `owningNode(...)` for the tabs branch with `target.closest(".tabs__section")` → RED.

- [ ] **Step 4: Commit**

---

### Task 7: The position assertion (e2e 6) — mutant (g)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`

**Fixture constraints (position-observability):** the target must sit **well below the pane fold** (several viewport heights of preceding content) **and** carry enough content after it that `.pane-body` can actually scroll it to the top. Assert **pre-click** that `y` is far from the content top. Without the first, both builds read "already at the top" and (g) survives; without the second, the target can never reach the top even on a correct build and the case goes falsely red.

**"The pane's content top"** is `.pane-body`'s rect top **plus its computed `padding-top`** — `alignTopInPane`'s own arithmetic. The bare bounding-box top is off by the padding, which can exceed the 4 px tolerance.

**Settling:** name the mechanism. Either poll the computed delta (`expect.poll`-shaped) with a timeout comfortably past the 500 ms backstop, **or** run under `prefers-reduced-motion: reduce`. State which; do not mix silently. Fixed sleeps are forbidden.

- [ ] **Step 1: Write the case**

```python
    delta = """(sel) => {
      const t = document.querySelector(sel);
      const b = t.closest(".pane-body");
      const pad = parseFloat(getComputedStyle(b).paddingTop) || 0;
      return t.getBoundingClientRect().top - b.getBoundingClientRect().top - pad;
    }"""
    assert page.evaluate(delta, target_sel) > 400   # pre-click: far from the top
    # ... click ...
    page.wait_for_function(f"(sel) => Math.abs(({delta})(sel)) <= 4", arg=target_sel)
```

- [ ] **Step 2: Run to verify it PASSES.**
- [ ] **Step 3: Falsify — mutant (g):** make `scrollPreviewTo` return immediately after `revealAncestors(target)` (reveal only, no scroll) → RED.
- [ ] **Step 4: Commit**

---

### Task 8: Hover on a nested child (e2e 7) — mutant (h)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`

Hover is fixed by Task 1 alone (`setHighlight` needs no change — the same selector now matches). But **a render test cannot prove `setHighlight` reaches a nested node**, so this case exists.

Use an **always-visible** nested child (callout or two-column, which need no reveal) — hover deliberately does **not** trigger the walk, so a hidden target would be outlined invisibly.

- [ ] **Step 1: Write the case** — hover the nested editor row, assert `prev-el--hl` lands on the **nested** preview node.
- [ ] **Step 2: Run to verify it PASSES.**
- [ ] **Step 3: Falsify — mutant (h):** change `setHighlight`'s selector to `'.prev-inner > .prev-el[data-element-id="' + id + '"]'` (top-level only) → RED.
- [ ] **Step 4: Commit**

---

### Task 9: Degraded ancestor (e2e 8) — mutant (i)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`

**Fixture: a bailed carousel nested inside a closed spoiler.**

Force the bail with a bad `window.TABS_I18N` key — the same **accessor** injection `tests/test_e2e_tabs.py:1706-1740` uses (a plain global write is overwritten by the inline script that assigns `TABS_I18N` wholesale before the deferred `tabs.js`, so the carousel would initialise normally and the case would fail against a **correct** build):

```python
    page.add_init_script(
        """
      Object.defineProperty(window, "TABS_I18N", {
        configurable: true,
        get() { return this.__t; },
        set(v) { this.__t = Object.assign({}, v, {slidePos: 42}); },
      });
    """
    )
```

The injection is **global**, which is why the outer ancestor must be a **spoiler, not tabs** — it would bail an outer tabs instance too.

**Both other candidate fixtures are dead ends; do not substitute them.** `killOne` does `removeAttribute("hidden")` on **every** owned panel, so afterwards no `.ba__panel` carries `hidden`, the collection predicate never fires and the walk never reaches the missing-control branch. A single-slide carousel is **unreachable from data** (`TabsElement.MIN_TABS == 2`, `TabsElementForm.clean_data` rejects fewer, `normalize_data` pads to 2 on read).

**The scroll assertion is the discriminator, not the spoiler-open one.** Reveal runs outermost-first, so on the throwing build the spoiler has **already opened** before the inner carousel throws — that half passes on the broken build. This case must therefore satisfy the **fixture-size half** of Task 7's constraints (tall fixture, trailing content).

**The pre-click probe differs from case 6.** The target starts inside a closed `<details>`, whose subtree is `content-visibility`-skipped, so its rect is stale or degenerate. Probe instead: assert `.pane-body.scrollTop === 0` **and** that the **spoiler container's own** rect sits several viewport heights below the pane content top.

- [ ] **Step 1: Write the case.**
- [ ] **Step 2: Run to verify it PASSES.**
- [ ] **Step 3: Falsify — mutant (i):** in `revealOne`'s carousel branch, replace `if (dot) dot.click();` with `dot.click();` (throws on the missing dot) → RED on the scroll assertion.
- [ ] **Step 4: Commit**

---

### Task 10: The post-op path (e2e 10, e2e 11) — mutant (k)

**Files:**
- Modify: `tests/test_e2e_preview_nested_locate.py`

There are **three** `scrollPreviewTo` call sites, and the walk lives inside it, so all three inherit it: `editor.js:367` (after **any** `form[data-op]` submit — save, move, duplicate, delete, incl. the 409/422 branches), `:451` (`.el-select`), `:463` (row body). **The post-op reveal is intended**: after saving or moving a nested element, revealing its own tab is the useful behaviour and matches the scroll that site already performs. `restoreActiveTabs` re-stamps the author's previous tab and the walk then overrides it, so after an op the visible tab is the **operated element's**. This is a deliberate behaviour change on every element op.

**e2e 10 — pins the behaviour change.** Assert the post-op `data-tabs-active` is the operated element's tab (A), not the author's previous one (B).

**The fixture ordering is load-bearing; the naive one is self-contaminating.** Saving a nested element requires first *opening* its edit form — which is the `.el-select` path, which itself runs the walk and stamps A. `applyFragments` then opens with `captureActiveTabs()`, so the submit carries A forward **even with the post-op walk deleted entirely**. So either:
- establish B **after** the edit form is open and before the submit (click a preview tab button — verified not to re-enter `scrollPreviewTo`, since `.tabs__tab` has neither `.el-select` nor `.el-row[data-element]` ancestry), or
- use a `form[data-op]` op needing no form-open — **move or duplicate** from the row actions, which reach the same `editor.js:367` site.

Either way **capture the pre-submit `data-tabs-active` and assert it is B**, so the case proves its own setup took.

**e2e 11 — the fixture for mutant (k).** Same `editor.js:367` path, but the nested element sits inside a **closed spoiler**. Assert the ancestor is revealed **after** the op.

**A tabs ancestor cannot kill (k)**: on the mutated build the walk runs against the *old* preview and `select()` stamps A there; `applyFragments` opens with `captureActiveTabs()`, reading that just-mutated pane, so `restoreActiveTabs` puts A on the rebuilt preview and `initOne` opens it — `data-tabs-active` and `aria-selected` end up byte-identical on both builds. A spoiler has no such carry (persistence is tabs-only, by decision), so a reveal done on the pre-swap DOM is discarded and the mutant goes red.

- [ ] **Step 1: Write both cases.**
- [ ] **Step 2: Run to verify they PASS.**
- [ ] **Step 3: Falsify — mutant (k):** move the `revealAncestors(target)` call in `scrollPreviewTo` to fire before `applyFragments` on the `:367` path (i.e. call it against the pre-swap DOM) → **e2e 11 RED, e2e 10 still green** (that asymmetry is the point).
- [ ] **Step 4: Commit**

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

1. Normalize: replace every `name="csrfmiddlewaretoken" value="…"` with a constant, plus anything else the control diff turns up.
2. **Run a control diff of master against master first and require it to be empty.** This is what proves the normalization sufficient; without it a clean branch diff means nothing.
3. Only then diff master against the branch, on a student lesson page containing all five container types.

Record the result in the PR body.

- [ ] **Step 3: Light + dark screenshots of the highlight ring**

`.prev-el--hl` is an outset double ring (`0 0 0 3px` + `0 0 0 5px`) that has only ever been drawn on top-level `<section class="prev-el">` nodes owning the full prose column. It will now be drawn on tightly-packed `.tabs__child` / `.twocolumn__child` / `.callout__child` boxes, where an outset ring can collide with a neighbour or its container's edge.

Take **light and dark** screenshots of a hovered nested child in at least a **two-column** and a **callout**. Judge the dark one on its own terms, not by assuming it follows the light one. For dark, drive it via `user.theme`, not the cookie. Record in the PR body.

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

```bash
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" add courses/static/courses/js/tabs.js
git -C "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/preview-nested-element-locate" commit -m "docs(tabs): editor.js's reveal-walk is a third libli:reveal dispatcher

Line-count neutral, per the citation-rot convention."
```

---

## Mutant ↔ test map (the falsification ledger)

| Mutant | Description | Test that must go RED | Task |
|---|---|---|---|
| a1 | drop the marker from ONE container template | render test 1 | 1 |
| a2 | emit `data-element-id` without the `prev-el` class | render test 1 | 1 |
| c1 | drop the `{% if editor_preview %}` gate | render test 2 (student) | 1 |
| c2 | gate the attribute but not the class | render test 2 (student) | 1 |
| l | add `display: block` to `.prev-el` | CSS guard test | 2 |
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

## Self-review notes

- **Spec coverage:** Part 1 → Task 1. CSS guard → Task 2. Part 2's four reveal branches → Tasks 3–5. Ordering/resolution → Task 6. Position → Task 7. Hover → Task 8. Degraded → Task 9. Post-op → Task 10. Comment/byte-identity/screenshots/format → Task 11. All 11 e2e cases, both render tests, the CSS guard and all 16 mutant rows are assigned.
- **Naming consistency:** `ownNodes(container, selector, ownerSelector)`, `owningNode(container, selector, ownerSelector, target)`, `revealAncestors(target)`, `revealOne(hit)` — used identically in Tasks 3, 4, 5, 6, 9 and in the mutant table.
- **`hit.all`** is set only on the `tabs` branch and read only by the carousel step; the strip step uses `hit.s` alone.
