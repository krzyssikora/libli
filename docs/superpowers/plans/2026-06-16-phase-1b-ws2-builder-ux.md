# Phase 1b — WS2 Course-builder UX Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the course-builder tree pane (connector lines, an always-visible per-row control cluster, contextual "+" add affordances, a clear Move UI, and pointer drag-and-drop) on top of the existing, unchanged backend.

**Architecture:** Pure frontend redesign — Django templates + `builder.css` + vanilla `builder.js`, reusing the existing `node_add` / `node_move`(reorder|reparent) endpoints and the optimistic-`updated`-token contract. A new `legal_child_kinds` helper (mirroring `ContentNode.RANK`) drives both the "+" affordances and drag-drop legality. The Move picker and drag-drop both map onto the existing `reparent` endpoint with a 0-based **insert-before** `position`.

**Tech Stack:** Django 5.2 server-rendered templates, vanilla JS (fetch + fragment swap), pytest + pytest-django, Playwright e2e (`-m e2e`).

**Spec:** `docs/superpowers/specs/2026-06-16-phase-1b-ws2-builder-ux-design.md`. **Accepted mockup:** `docs/mockups/builder_accepted.html`.

**Conventions (match existing libli):** run Python via `.venv/Scripts/python.exe -m pytest`; manage perms unchanged; the e2e marker is excluded by default (`addopts -m 'not e2e'`); after any static (CSS/JS) change the dev server needs `collectstatic` + hard refresh (not relevant to tests, which serve static directly). Use `make_pa(client)` from `tests/factories.py` for an authed Platform Admin.

**Sequencing (spec §9):** Tasks 1–4 = static tree + add (#5/#6/#11). Tasks 5–6 = Move UI (#8). Task 7 = drag-drop (#9c). Task 8 = i18n. Task 9 = final regression. Each task keeps the suite green and the no-JS fallback working.

---

## Task 1: Legal-kind helper + template tags

**Files:**
- Modify: `courses/ordering.py`
- Modify: `courses/templatetags/courses_manage_extras.py`
- Test: `tests/test_legal_kinds.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_legal_kinds.py`:

```python
from courses.ordering import PRIMARY_CHILD_KIND
from courses.ordering import legal_child_kinds


def test_legal_child_kinds_top_allows_all_in_rank_order():
    assert legal_child_kinds(None) == ["part", "chapter", "section", "unit"]


def test_legal_child_kinds_nested():
    assert legal_child_kinds("part") == ["chapter", "section", "unit"]
    assert legal_child_kinds("chapter") == ["section", "unit"]
    assert legal_child_kinds("section") == ["unit"]
    assert legal_child_kinds("unit") == []


def test_primary_child_kind_only_for_three_plus_legal():
    assert PRIMARY_CHILD_KIND.get(None) == "chapter"
    assert PRIMARY_CHILD_KIND.get("part") == "chapter"
    assert PRIMARY_CHILD_KIND.get("chapter") is None  # only 2 legal kinds -> no overflow
    assert PRIMARY_CHILD_KIND.get("section") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_legal_kinds.py -v`
Expected: FAIL with `ImportError: cannot import name 'legal_child_kinds'`.

- [ ] **Step 3: Implement the helper**

Add to the end of `courses/ordering.py` (it already imports `from courses.models import ContentNode`):

```python
# --- builder "+" affordances + drag-drop legality (WS2) ---------------------
# A child's kind must be strictly deeper (larger RANK) than its parent's; the top
# scope (parent_kind=None) allows all kinds. PRIMARY_CHILD_KIND is the one-click "+"
# kind for parents with >=3 legal kinds (top, part); the rest go to the "+…" overflow.
PRIMARY_CHILD_KIND = {None: "chapter", "part": "chapter"}


def legal_child_kinds(parent_kind):
    """Kinds a node of `parent_kind` (a kind string, or None for the top scope) may
    directly contain, in RANK order."""
    order = sorted(ContentNode.RANK, key=ContentNode.RANK.get)
    if parent_kind is None:
        return order
    parent_rank = ContentNode.RANK[parent_kind]
    return [k for k in order if ContentNode.RANK[k] > parent_rank]
```

- [ ] **Step 4: Add the template tags**

In `courses/templatetags/courses_manage_extras.py`, add imports near the top (after the existing imports) and two tags (anywhere after `register = template.Library()`):

```python
from courses.ordering import PRIMARY_CHILD_KIND
from courses.ordering import legal_child_kinds as _legal_child_kinds


@register.simple_tag
def legal_child_kinds(parent_kind):
    """List of kind strings (RANK order) a `parent_kind` scope may add. None = top."""
    return _legal_child_kinds(parent_kind)


@register.simple_tag
def primary_child_kind(parent_kind):
    """The one-click primary "+" kind for a >=3-legal-kind scope, else None."""
    return PRIMARY_CHILD_KIND.get(parent_kind)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_legal_kinds.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add courses/ordering.py courses/templatetags/courses_manage_extras.py tests/test_legal_kinds.py
git commit -m "feat(builder): legal_child_kinds + PRIMARY_CHILD_KIND helper + template tags (WS2 #11)"
```

---

## Task 2: Contextual "+" affordance — template + scope/view threading (no-JS static)

Replaces the persistent `_add_form.html` with `_add_affordance.html` hosted inside every `_scope.html`. **No JS yet** — each `+ Kind` is a real submit button (one `<form>` per scope, a submit button per legal kind, like `_move_buttons.html`); the JS inline-row comes in Task 4.

**Files:**
- Create: `templates/courses/manage/_add_affordance.html`
- Modify: `templates/courses/manage/_scope.html`
- Modify: `templates/courses/manage/_tree_node.html`
- Modify: `templates/courses/manage/builder.html`
- Modify: `courses/views_manage.py` (`builder`, `_render_scope`)
- Delete: `templates/courses/manage/_add_form.html`
- Test: `tests/test_manage_affordance.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_manage_affordance.py`:

```python
from courses.models import ContentNode
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa


def _course_with_section(client, username):
    # make_pa creates AND logs in a Platform Admin (holds courses.change_course, so it can
    # manage any course regardless of owner). Create data after, owned by that user.
    pa = make_pa(client, username)
    course = CourseFactory(slug=f"aff-{username}", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch1")
    sec = ContentNodeFactory(course=course, kind="section", unit_type=None, parent=ch, title="SecA")
    return course, ch, sec


def test_affordance_shows_only_legal_kinds_per_scope(client, db):
    course, ch, sec = _course_with_section(client, "pa")
    html = client.get(f"/manage/courses/{course.slug}/build/").content.decode()
    assert "+ Chapter" in html                     # top scope primary chip
    assert f'data-add-scope="{ch.pk}"' in html      # chapter scope has an affordance
    assert f'data-add-scope="{sec.pk}"' in html     # section scope has an affordance (+ Unit only)


def test_empty_chapter_still_shows_its_add_affordance(client, db):
    pa = make_pa(client, "pa2")
    course = CourseFactory(slug="empty", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch")
    html = client.get(f"/manage/courses/{course.slug}/build/").content.decode()
    assert f'data-add-scope="{ch.pk}"' in html       # empty chapter still exposes its + chips


def test_no_js_add_via_kind_button_creates_node(client, db):
    course, ch, sec = _course_with_section(client, "pa3")
    resp = client.post(
        f"/manage/courses/{course.slug}/build/node/add/",
        {"parent": str(sec.pk), "kind": "unit", "title": "L1",
         "unit_type": "lesson", "parent_token": sec.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert ContentNode.objects.filter(course=course, parent=sec, title="L1", kind="unit").exists()
```

> Verify the exact node-add URL with `grep -n "node/add\|manage_node_add" courses/urls*.py` and adjust the POST path if it differs from `…/build/node/add/`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manage_affordance.py -v`
Expected: FAIL (no `data-add-scope`; `_add_affordance.html` doesn't exist).

- [ ] **Step 3: Create `_add_affordance.html`**

`templates/courses/manage/_add_affordance.html` — one form, a submit button per legal kind. `scope_id` and `parent_token` come from the hosting `_scope.html`. (Task 4's JS enhances this; with JS off it submits directly.)

```django
{% load i18n courses_manage_extras %}
{% legal_child_kinds parent_kind as kinds %}
{% primary_child_kind parent_kind as primary %}
{% if kinds %}
<li class="tree__add-row">
  <form class="tree__add" method="post"
        action="{% url 'courses:manage_node_add' slug=course.slug %}"
        data-op="add" data-add-scope="{{ scope_id }}">
    {% csrf_token %}
    <input type="hidden" name="parent" value="{{ scope_id }}">
    <input type="hidden" name="parent_token" value="{{ scope_updated }}">
    {# Always sent, but node_add (views_manage.py `node_add`: `unit_type = ... if kind == UNIT
       else None`) nulls it for non-unit kinds, so a "+ Chapter" carrying unit_type=lesson is
       safe — do NOT rely on changing the backend. #}
    <input type="hidden" name="unit_type" value="lesson">
    {# JS hides this until a + chip is clicked; visible with JS off. `required` blocks a no-JS
       empty-title submit; the JS commit path only submits when non-empty AND the field is
       visible at submit time, so `required` never blocks a hidden (display:none) control. #}
    <input type="text" name="title" class="tree__add-title" required
           placeholder="{% trans 'New title' %}" data-add-title>
    {% for kind in kinds %}
      <button type="submit" name="kind" value="{{ kind }}"
              class="chip chip--add{% if kind == primary %} chip--primary{% endif %}{% if primary and kind != primary %} chip--overflow{% endif %}"
              data-add-kind="{{ kind }}">+ {{ kind|capfirst }}</button>
    {% endfor %}
    {% if primary %}<button type="button" class="chip chip--more" data-add-more aria-label="{% trans 'More kinds' %}">+&hellip;</button>{% endif %}
  </form>
</li>
{% endif %}
```

> The `kind|capfirst` renders "+ Chapter" etc. **These chip labels stay English in WS2** — exactly like the existing tree badges (`node.get_kind_display`): the model's `Kind` choice labels aren't `gettext`-wrapped, so translating the kind words is part of the **cross-cutting i18n sweep (#2)**, NOT this WS2 plan (Task 8 only covers the new `{% trans %}` strings). The e2e/test selectors key on `button[data-add-kind]` + the stable English `"+ Chapter"` text.

- [ ] **Step 4: Rewrite `_scope.html`**

`templates/courses/manage/_scope.html` — add `parent_kind`, host the affordance + empty hint, pass first/last to `_tree_node`:

```django
{% load i18n %}
<ol class="tree__scope" data-scope="{{ scope_id }}" data-updated="{{ scope_updated }}">
  {% for node in nodes %}
    {% include "courses/manage/_tree_node.html" with node=node children_map=children_map is_first=forloop.first is_last=forloop.last %}
  {% empty %}
    <li class="tree__empty">{% trans "No children yet." %}</li>
  {% endfor %}
  {% include "courses/manage/_add_affordance.html" with scope_id=scope_id scope_updated=scope_updated parent_kind=parent_kind course=course %}
</ol>
```

- [ ] **Step 5: Update `_tree_node.html` to thread `parent_kind` into its nested scope**

In `templates/courses/manage/_tree_node.html`, the nested include (currently around line 15) must pass `parent_kind=node.kind`, and drop the old `_add_form` include (line 16). Replace the `{% if node.kind != "unit" %}` block:

```django
  {% if node.kind != "unit" %}
    {% include "courses/manage/_scope.html" with scope_id=node.pk scope_updated=node.updated.isoformat nodes=children_map|get_item:node.pk children_map=children_map parent_kind=node.kind %}
  {% endif %}
```

(The `_move_buttons`/`Move…`/`Delete` action span stays for now; Task 3 restyles it into the cluster and uses `is_first`/`is_last` — which `_scope.html`'s `{% include … is_first=forloop.first is_last=forloop.last %}` forwards into `_tree_node.html`'s context automatically, so Task 3 reads them without further wiring.)

- [ ] **Step 6: Simplify `builder.html`**

In `templates/courses/manage/builder.html`, replace the `{% if top_nodes %}…{% endif %}` block + the top `_add_form` include (lines 11-17) with a single unconditional scope include passing `parent_kind=None`:

```django
  <div class="builder__tree">
    <h1 class="builder__title">{{ course.title }}</h1>
    {% include "courses/manage/_scope.html" with scope_id="top" scope_updated=course.updated.isoformat nodes=top_nodes children_map=children_map parent_kind=None %}
  </div>
```

- [ ] **Step 7: Thread `parent_kind` + drop `kind_choices` in the view**

In `courses/views_manage.py`, `_render_scope` — compute and pass `parent_kind`, drop `kind_choices`:

```python
def _render_scope(request, course, scope_ref):
    cmap = _children_map(course)
    if scope_ref == "top":
        nodes, updated, parent_kind = cmap.get(None, []), course.updated.isoformat(), None
    else:
        parent = ContentNode.objects.filter(pk=scope_ref, course=course).first()
        nodes = cmap.get(int(scope_ref), [])
        updated = parent.updated.isoformat() if parent else course.updated.isoformat()
        parent_kind = parent.kind if parent else None
    return render(
        request,
        "courses/manage/_scope.html",
        {"scope_id": scope_ref, "scope_updated": updated, "parent_kind": parent_kind,
         "nodes": nodes, "children_map": cmap, "course": course},
    )
```

In `builder` (the view), drop `kind_choices` from the context dict (the template no longer uses it). **Also drop it from `_builder_with_notice`** (the no-JS error re-render builds its own context with `kind_choices`, now dead — remove it there too to avoid a stale reference):

```python
    return render(request, "courses/manage/builder.html",
                  {"course": course, "children_map": cmap, "top_nodes": cmap.get(None, [])})
```

- [ ] **Step 8: Delete `_add_form.html`**

```bash
git rm templates/courses/manage/_add_form.html
```

- [ ] **Step 9: Rewrite the no-JS add e2e, then run the server tests**

`tests/test_e2e_builder.py::test_no_js_fallback_add` drives the now-deleted `select[name='kind']` form. With JS disabled the new affordance shows the title input + a submit button per legal kind (no `+…` collapse). Replace its add block:

```python
    add = page.locator('[data-add-scope="top"]').first
    add.locator("input[data-add-title]").fill("Part A")
    add.locator('button[data-add-kind="part"]').click()  # full-page POST -> 302 redirect
```

Then run: `.venv/Scripts/python.exe -m pytest tests/test_manage_affordance.py tests/test_manage_builder.py -v`
Expected: PASS. If `test_manage_builder.py` asserts the old `_add_form`/`kind_choices`, update those assertions to the new `[data-add-scope]`/`button[data-add-kind]` markup (they guard this surface).

- [ ] **Step 10: Run the full default suite (no e2e)**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS. Fix any test that asserted the old `_add_form` select **or the removed course-level empty-state copy**. Specifically, `tests/test_manage_builder.py::test_empty_course_shows_empty_state` (line 42) asserts `b"add your first"`/`b"first node"` — update it to assert the new per-scope copy `b"no children yet"` (the course-level "Empty course — add your first node." line is intentionally removed; the per-scope `"No children yet."` hint replaces it, spec §4.4).

- [ ] **Step 11: Commit**

```bash
git add courses/views_manage.py templates/courses/manage/ tests/test_manage_affordance.py
git commit -m "feat(builder): contextual + affordances in every scope; retire _add_form (WS2 #11)"
```

---

## Task 3: Control cluster + connectors + SVG sprite (CSS + markup)

Restyle `_tree_node.html`'s action span into the right-aligned icon cluster, add the SVG sprite to `builder.html`, disable ↑/↓ at boundaries, and write the connector + cluster CSS.

**Files:**
- Modify: `templates/courses/manage/builder.html` (sprite)
- Modify: `templates/courses/manage/_tree_node.html` (cluster markup + boundary)
- Modify: `templates/courses/manage/_move_buttons.html` (icon buttons + disabled attrs)
- Modify: `courses/static/courses/css/builder.css` (rewrite)
- Test: `tests/test_manage_affordance.py` (add a boundary assertion)

- [ ] **Step 1: Write the failing test (↑/↓ boundary disabling)**

Add to `tests/test_manage_affordance.py`:

```python
def test_reorder_buttons_disabled_at_boundaries(client, db):
    pa = make_pa(client, "pab")
    course = CourseFactory(slug="bnd", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="A")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="B")
    html = client.get(f"/manage/courses/{course.slug}/build/").content.decode()
    # First child A: up disabled; last child B: down disabled. Regex tolerant of other
    # attributes between value and disabled (robust against attribute reordering).
    import re
    assert re.search(r'value="up"[^>]*\bdisabled', html), "first child should disable up"
    assert re.search(r'value="down"[^>]*\bdisabled', html), "last child should disable down"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manage_affordance.py::test_reorder_buttons_disabled_at_boundaries -v`
Expected: FAIL (no `disabled` attribute yet).

- [ ] **Step 3: Add the SVG sprite to `builder.html`**

In `templates/courses/manage/builder.html`, add the sprite as the **first child of `.builder`** (sibling of both panes), right after the `<section class="builder" ...>` open tag:

```django
<svg width="0" height="0" class="builder__sprite" aria-hidden="true" focusable="false">
  <symbol id="bi-grip" viewBox="0 0 16 16"><g fill="currentColor"><circle cx="6" cy="4" r="1.1"/><circle cx="10" cy="4" r="1.1"/><circle cx="6" cy="8" r="1.1"/><circle cx="10" cy="8" r="1.1"/><circle cx="6" cy="12" r="1.1"/><circle cx="10" cy="12" r="1.1"/></g></symbol>
  <symbol id="bi-up" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="M4 10l4-4 4 4"/></symbol>
  <symbol id="bi-down" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="M4 6l4 4 4-4"/></symbol>
  <symbol id="bi-move" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="M2 8h8m-3-3l3 3-3 3M13.5 3.5v9"/></symbol>
  <symbol id="bi-trash" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="M3 4.5h10M6.5 4.5V3h3v1.5M4.7 4.5l.5 8.2a1 1 0 001 .9h3.6a1 1 0 001-.9l.5-8.2"/></symbol>
</svg>
```

- [ ] **Step 4: Rewrite the action cluster in `_tree_node.html`**

Replace the `<span class="tree__actions">…</span>` block (lines 7-13) with the cluster (grip + reorder form + move + delete as icon buttons), and pass boundary flags into `_move_buttons`:

```django
  <span class="tree__cluster">
    <button type="button" class="ica ica--grip" draggable="true" aria-label="{% trans 'Drag to move' %}" title="{% trans 'Drag to move' %}"><svg class="ic"><use href="#bi-grip"/></svg></button>
    {% include "courses/manage/_move_buttons.html" with node=node is_first=is_first is_last=is_last %}
    <a class="ica" href="{% url 'courses:manage_node_move' slug=node.course.slug %}?node={{ node.pk }}" data-move="{{ node.pk }}" aria-label="{% trans 'Move…' %}" title="{% trans 'Move…' %}"><svg class="ic"><use href="#bi-move"/></svg></a>
    <a class="ica ica--danger" href="{% url 'courses:manage_node_delete' slug=node.course.slug %}?node={{ node.pk }}" data-delete="{{ node.pk }}" aria-label="{% trans 'Delete' %}" title="{% trans 'Delete' %}"><svg class="ic"><use href="#bi-trash"/></svg></a>
  </span>
```

- [ ] **Step 5: Rewrite `_move_buttons.html` as icon buttons with boundary disabling**

```django
{% load i18n %}
<form class="tree__inline" method="post" action="{% url 'courses:manage_node_move' slug=node.course.slug %}" data-op="reorder">
  {% csrf_token %}
  <input type="hidden" name="mode" value="reorder">
  <input type="hidden" name="node" value="{{ node.pk }}">
  <input type="hidden" name="token" value="{{ node.updated.isoformat }}">
  <button class="ica" type="submit" name="direction" value="up"{% if is_first %} disabled{% endif %} aria-label="{% trans 'Move up' %}" title="{% trans 'Move up' %}"><svg class="ic"><use href="#bi-up"/></svg></button>
  <button class="ica" type="submit" name="direction" value="down"{% if is_last %} disabled{% endif %} aria-label="{% trans 'Move down' %}" title="{% trans 'Move down' %}"><svg class="ic"><use href="#bi-down"/></svg></button>
</form>
```

- [ ] **Step 6: Rewrite `builder.css`**

Replace `courses/static/courses/css/builder.css` with the WS2 layout (connectors, cluster always-visible/hover-emphasis, chips + overflow, inline-add, empty hint). Drag/picker rules are appended in Tasks 6–7. Use existing tokens only:

```css
.builder { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); position: relative; }
@media (max-width: 720px) { .builder { grid-template-columns: 1fr; } }
.builder__sprite { position: absolute; }
.builder__tree { border-right: 1px solid var(--border-default); padding-right: var(--space-4); }
.builder__title { font-weight: 700; letter-spacing: var(--heading-letter-spacing); }

/* #5 connectors */
.tree__scope { list-style: none; margin: 0; padding-left: 14px; border-left: 2px solid var(--border-default); margin-left: 7px; }
.builder__tree > .tree__scope { border-left-color: var(--border-strong); margin-left: 0; }

.tree__row { display: flex; align-items: center; gap: var(--space-2); padding: 3px 4px; border-radius: var(--radius-sm); }
.tree__row:hover { background: var(--surface-sunken); }
.tree__badge { font-size: .6rem; text-transform: uppercase; letter-spacing: .03em; border: 1px solid currentColor; border-radius: 8px; padding: 0 6px; }
.tree__badge--part, .tree__badge--chapter, .tree__badge--section { color: var(--primary); }
.tree__badge--unit { color: var(--accent); }
.tree__title { flex: 1; background: none; border: none; cursor: pointer; text-align: left; color: var(--text-primary); padding: 0; }
.tree__empty { list-style: none; color: var(--text-secondary); font-style: italic; padding: 3px 4px; }

/* #6 control cluster — always visible, subtle, brighten on hover/focus */
.tree__cluster { display: inline-flex; gap: 1px; align-items: center; opacity: .5; transition: opacity .12s; }
.tree__row:hover .tree__cluster, .tree__row:focus-within .tree__cluster { opacity: 1; }
.tree__inline { display: inline-flex; gap: 1px; margin: 0; }
.ica { background: none; border: none; padding: 3px; margin: 0; color: var(--text-tertiary); cursor: pointer; border-radius: 5px; line-height: 0; display: inline-flex; }
.ica:hover { background: var(--surface-sunken); color: var(--primary); }
.ica:disabled { opacity: .35; cursor: default; }
.ica--danger:hover { color: var(--danger); }
.ica--grip { cursor: grab; }
.ic { width: 15px; height: 15px; display: block; }

/* #11 contextual "+" affordance */
.tree__add-row { list-style: none; }
.tree__add { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); padding: 4px 0; margin: 0; }
.chip { font-size: .9rem; border-radius: var(--radius-sm); padding: 2px 8px; cursor: pointer; background: none; border: 1px dashed transparent; color: var(--primary); }
.chip:hover { border-color: var(--primary); }
.chip--primary { background: var(--primary); color: var(--text-inverse); border: none; }
.chip--more { border: 1px solid var(--border-strong); display: none; }   /* JS-only toggle */
.tree__add-title { flex: 1 1 8rem; min-width: 6rem; }
/* Progressive enhancement: with JS off, all kind chips + the title input show (no "+…").
   With JS on, hide the title until a chip is clicked, collapse overflow chips behind "+…". */
.js .chip--more { display: inline-block; }
.js .tree__add-title { display: none; }
.js .tree__add.is-adding .tree__add-title { display: inline-block; }
.js .chip--overflow { display: none; }
.js .tree__add.show-overflow .chip--overflow { display: inline-block; }
```

> The `.js` class is set by `builder.js` on `document.documentElement` at load (Task 4 adds `document.documentElement.classList.add("js")` first thing) so these progressive-enhancement rules only apply when JS runs.

- [ ] **Step 7: Run the boundary test + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manage_affordance.py -v && .venv/Scripts/python.exe -m pytest`
Expected: PASS. Update any `test_manage_builder.py`/`test_editor_styles.py` assertions that referenced the old `.tree__act`/action markup.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/manage/ courses/static/courses/css/builder.css tests/test_manage_affordance.py
git commit -m "feat(builder): connector lines + always-visible icon control cluster + SVG sprite (WS2 #5/#6)"
```

---

## Task 4: Inline new-row add interaction (builder.js)

Enhance the affordance: clicking a `+ Kind` chip reveals the inline title field instead of submitting; Enter/blur-with-text submits (via `requestSubmit(button)`); Esc/blur-empty cancels; `+…` toggles the overflow.

**Files:**
- Modify: `courses/static/courses/js/builder.js`
- Test: `tests/test_e2e_builder_ws2.py` (create)

- [ ] **Step 1: Write the failing e2e test**

Create `tests/test_e2e_builder_ws2.py` (reuse the helpers pattern from `tests/test_e2e_builder_reorder.py` — copy `_make_pa_user`, `_login`, the `_allow_sync_orm_under_playwright` fixture, `pytestmark = pytest.mark.e2e`):

```python
import os
import pytest
from tests.factories import TEST_PASSWORD, make_verified_user

pytestmark = pytest.mark.e2e

@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield

def _make_pa_user(username):
    from django.contrib.auth.models import Group
    from institution.roles import PLATFORM_ADMIN, seed_roles
    seed_roles()
    u = make_verified_user(username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD)
    u.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return u

def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_inline_add_creates_node(page, live_server):
    from tests.factories import ContentNodeFactory, CourseFactory
    from courses.models import ContentNode
    pa = _make_pa_user("pa9w1")
    course = CourseFactory(slug="ws2add", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch1")
    _login(page, live_server, "pa9w1")
    page.goto(f"{live_server.url}/manage/courses/ws2add/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    # In Ch1's scope, click "+ Unit", type a title, Enter.
    scope = page.locator(f'[data-add-scope="{ch.pk}"]')
    scope.locator('button[data-add-kind="unit"]').click()
    field = scope.locator('input[data-add-title]')
    field.fill("Intro")
    field.press("Enter")
    page.wait_for_selector("text=Intro")
    assert ContentNode.objects.filter(course=course, parent=ch, title="Intro", kind="unit").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_e2e_builder_ws2.py -m e2e -v`
Expected: FAIL (clicking `+ Unit` submits immediately / no inline field shown).

- [ ] **Step 3: Implement the inline-add lifecycle in `builder.js`**

At the very top of the IIFE (after `"use strict";`), add: `document.documentElement.classList.add("js");`

Add these handlers inside the IIFE (after the existing `change` listener). They intercept add-chip clicks and the `+…` toggle, manage a single open inline row, and submit via `requestSubmit(button)` so the existing submit handler posts it. (The pre-existing `change` listener that watched `[data-kind-select]`/`[data-unit-type]` is now **inert** — those lived only in the deleted `_add_form.html`; leave it as a harmless no-op or delete it, but do **not** repurpose it for the new chips.)

```javascript
  // --- WS2 inline "+" add ---------------------------------------------------
  function closeAdd(form) {
    if (!form) return;
    form.classList.remove("is-adding");
    var t = form.querySelector("[data-add-title]");
    if (t) t.value = "";
    delete form.dataset.pendingKind;
  }
  function openAdd(form, kind) {
    // one open row at a time: commit/cancel any other open row first
    root.querySelectorAll("form.tree__add.is-adding").forEach(function (f) {
      if (f !== form) commitOrCancel(f);
    });
    form.dataset.pendingKind = kind;
    form.classList.add("is-adding");
    var t = form.querySelector("[data-add-title]");
    if (t) { t.focus(); }
  }
  function commitOrCancel(form) {
    var t = form.querySelector("[data-add-title]");
    if (t && t.value.trim()) {
      var kind = form.dataset.pendingKind;
      var btn = form.querySelector('button[data-add-kind="' + kind + '"]');
      form.requestSubmit(btn);   // -> existing submit handler posts node_add
    } else {
      closeAdd(form);
    }
  }
  root.addEventListener("click", function (e) {
    var more = e.target.closest("[data-add-more]");
    if (more) { e.preventDefault(); more.closest(".tree__add").classList.toggle("show-overflow"); return; }
    var chip = e.target.closest("button[data-add-kind]");
    if (chip) {
      var form = chip.closest("form.tree__add");
      if (form.classList.contains("is-adding") && form.dataset.pendingKind === chip.value) {
        commitOrCancel(form);          // second click on the active kind = commit
      } else {
        e.preventDefault();            // first click = open inline row, don't submit
        openAdd(form, chip.value);
      }
    }
  });
  root.addEventListener("keydown", function (e) {
    var t = e.target.closest("[data-add-title]");
    if (!t) return;
    if (e.key === "Enter") { e.preventDefault(); commitOrCancel(t.closest("form.tree__add")); }
    if (e.key === "Escape") { e.preventDefault(); closeAdd(t.closest("form.tree__add")); }
  });
  root.addEventListener("focusout", function (e) {
    var t = e.target.closest("[data-add-title]");
    if (!t) return;
    var form = t.closest("form.tree__add");
    // let a click on the same form's button win before blur closes it
    setTimeout(function () { if (!form.contains(document.activeElement)) commitOrCancel(form); }, 120);
  });
```

> The existing `submit` handler already appends `e.submitter.name/value`, so `requestSubmit(btn)` posts `kind=<btn.value>`. The hidden `parent`/`parent_token`/`unit_type`/`title` ride along. On 200 the scope swaps (existing flow) and the transient row is gone with it.

- [ ] **Step 4: Run the e2e to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_e2e_builder_ws2.py -m e2e -v`
Expected: PASS.

- [ ] **Step 5: Rewrite the JS add e2e (`test_builder_full_flow`), then run the existing builder e2e**

`tests/test_e2e_builder.py::test_builder_full_flow` adds two top-level nodes via the deleted `select[name='kind']`. Rewrite both adds to the new inline affordance using the primary **chapter** chip (top's primary — avoids the `+…` overflow dance). The regression intent (two consecutive top-level adds without a spurious 409) is unchanged:

```python
    page.wait_for_selector('[data-scope="top"]', state="attached")
    add = page.locator('[data-add-scope="top"]').first
    add.locator('button[data-add-kind="chapter"]').click()      # opens the inline row
    add.locator("input[data-add-title]").fill("Foundations")
    add.locator("input[data-add-title]").press("Enter")
    page.wait_for_selector("text=Foundations")
    add.locator('button[data-add-kind="chapter"]').click()       # 2nd add, no reload
    add.locator("input[data-add-title]").fill("Appendix")
    add.locator("input[data-add-title]").press("Enter")
    page.wait_for_selector("text=Appendix")
```

The existing assertions (`course.nodes.filter(parent=None).count() == 2`, titles exist) still hold — they're kind-agnostic; update any "part" wording in the test's comments to "chapter".

Then run: `.venv/Scripts/python.exe -m pytest tests/test_e2e_builder.py tests/test_e2e_builder_reorder.py -m e2e -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/builder.js tests/test_e2e_builder_ws2.py tests/test_e2e_builder.py tests/test_e2e_builder_reorder.py
git commit -m "feat(builder): inline type-in-place add interaction + overflow menu (WS2 #11)"
```

---

## Task 5: Move picker rewrite — no-JS baseline + view context

Rewrite `_move_picker.html` so the no-JS form ships `position` `value=""` (append default) and the template also carries the data the JS slot-UI needs (each destination's children). Extend the `_move_picker` view to pass `children_map`.

**Files:**
- Modify: `templates/courses/manage/_move_picker.html`
- Modify: `courses/views_manage.py` (`_move_picker`)
- Test: `tests/test_manage_move_picker.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_manage_move_picker.py`:

```python
import pytest
from tests.factories import ContentNodeFactory, CourseFactory, make_pa
from courses.models import ContentNode


def test_move_picker_position_defaults_to_empty_append(client, db):
    pa = make_pa(client, "pamp")
    course = CourseFactory(slug="mp", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="U")
    url = f"/manage/courses/{course.slug}/build/node/move/?node={unit.pk}"
    html = client.get(url, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    import re
    m = re.search(r'<input[^>]*name="position"[^>]*>', html)
    assert m and 'value=""' in m.group(0), "position must default to empty (append), not 0"
    assert 'name="node_token"' in html
    # Ch is a legal destination for a unit (shallower kind), rendered with its data-updated.
    assert f'value="{ch.pk}"' in html


def test_no_js_reparent_empty_position_appends(client, db):
    # The headline value="" change: an empty position must APPEND (not prepend to index 0).
    pa = make_pa(client, "pamp2")
    course = CourseFactory(slug="mp2", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch")
    a = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="A")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="B")
    resp = client.post(
        f"/manage/courses/{course.slug}/build/node/move/",
        {"mode": "reparent", "node": str(a.pk), "new_parent": str(ch.pk),
         "position": "", "node_token": a.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    order = list(ContentNode.objects.filter(parent=ch).order_by("order", "pk")
                 .values_list("title", flat=True))
    assert order == ["B", "A"]   # A re-appended to the end of Ch (empty position -> append)
```

> Verify the move URL with `grep -n "node/move\|manage_node_move" courses/urls*.py`.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manage_move_picker.py -v`
Expected: FAIL (current picker ships `value="0"`).

- [ ] **Step 3: Extend the `_move_picker` view to pass `children_map`**

In `courses/views_manage.py`, `_move_picker` — add `children_map` (and keep `candidates`) so the JS slot-UI can render each destination's children:

```python
    cmap = _children_map(course)
    return render(
        request,
        "courses/manage/_move_picker.html",
        {"course": course, "node": node, "candidates": candidates,
         "children_map": cmap, "nodes_top": cmap.get(None, [])},
    )
```

- [ ] **Step 4: Rewrite `_move_picker.html`**

`templates/courses/manage/_move_picker.html` — keep the no-JS `<select>` + `position` (now `value=""`), add the moving-node chip, and emit a JS-consumable indented destination list with each destination's children (hidden until JS builds the slot UI). Each destination/anchor carries `data-updated` and `data-pk` for the JS:

```django
{% load i18n courses_manage_extras %}
<form class="move-picker" method="post" action="{% url 'courses:manage_node_move' slug=course.slug %}" data-op="reparent">
  {% csrf_token %}
  <input type="hidden" name="mode" value="reparent">
  <input type="hidden" name="node" value="{{ node.pk }}">
  <input type="hidden" name="node_token" value="{{ node.updated.isoformat }}">
  <div class="move-picker__head">{% trans "Move" %}:
    <span class="tree__badge tree__badge--{{ node.kind }}">{{ node.get_kind_display }}</span> {{ node.title }}</div>

  {# no-JS baseline: raw select + numeric position (append by default) #}
  <label class="move-picker__raw">{% trans "Destination" %}
    <select name="new_parent">
      <option value="top" data-updated="{{ course.updated.isoformat }}">{% trans "Top level" %}</option>
      {% for c in candidates %}<option value="{{ c.pk }}" data-updated="{{ c.updated.isoformat }}">{{ c.get_kind_display }}: {{ c.title }}</option>{% endfor %}
    </select>
  </label>
  <label class="move-picker__raw">{% trans "Position" %}
    <input type="number" name="position" min="0" value="" placeholder="{% trans 'end' %}"></label>

  {# JS-enhanced indented destination tree + slots (built by builder.js from this data) #}
  <div class="move-picker__tree" data-move-tree hidden>
    <button type="button" class="move-dest" data-dest="top" data-updated="{{ course.updated.isoformat }}">{% trans "Top level" %}</button>
    {% for c in candidates %}
      <div class="move-dest-wrap">
        <button type="button" class="move-dest move-dest--{{ c.kind }}" data-dest="{{ c.pk }}" data-updated="{{ c.updated.isoformat }}">
          <span class="tree__badge tree__badge--{{ c.kind }}">{{ c.get_kind_display }}</span> {{ c.title }}</button>
        <ol class="move-dest-children" hidden>
          {% for child in children_map|get_item:c.pk %}<li data-child-pk="{{ child.pk }}">{{ child.title }}</li>{% endfor %}
        </ol>
      </div>
    {% endfor %}
    <ol class="move-dest-children" data-children-for="top" hidden>
      {% for child in nodes_top %}<li data-child-pk="{{ child.pk }}">{{ child.title }}</li>{% endfor %}
    </ol>
  </div>

  <button class="btn btn--small move-picker__submit" type="submit">{% trans "Move here" %}</button>
</form>
```

> **Hierarchy display:** destinations are a flat `candidates` list (legal structural ancestors); convey hierarchy by **indenting on kind** via the `move-dest--{{ c.kind }}` class (CSS `padding-left` per kind in Task 6) rather than computing tree depth. The **top** destination owns its own children list `<ol data-children-for="top">` populated from `nodes_top` (passed by the view above) so top-level slots render; each candidate owns a sibling `<ol class="move-dest-children">` of its children. Every destination button carries `data-dest`/`data-updated`; every child `<li>` carries `data-child-pk`. **Every candidate emits its `.move-dest-children` `<ol>` even when it has no children** (an empty `<ol>`), so `renderSlots` always finds it and renders a single slot 0 — a childless destination must still be a valid placement target. The JS slot-UI (Task 6) reads exactly these.

- [ ] **Step 5: Run the test + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manage_move_picker.py tests/test_manage_node_ops.py -v && .venv/Scripts/python.exe -m pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/manage/_move_picker.html courses/views_manage.py tests/test_manage_move_picker.py
git commit -m "feat(builder): move picker no-JS append default + JS-consumable destination data (WS2 #8)"
```

---

## Task 6: Move picker JS — indented slots + moving highlight

Build the enhanced picker UI in `builder.js`: on open, hide the raw controls, show the indented destination tree; selecting a destination reveals its insertion slots (excluding the moving node); choosing a slot syncs the hidden `new_parent` + `position`; highlight the moving node; clear state on cancel/select-other/success.

**Files:**
- Modify: `courses/static/courses/js/builder.js`
- Modify: `courses/static/courses/css/builder.css` (picker + slot styles)
- Test: `tests/test_e2e_builder_ws2.py` (add the same-parent placement case)

- [ ] **Step 1: Write the failing e2e test (the C4/I1 off-by-one)**

Add to `tests/test_e2e_builder_ws2.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_move_picker_places_between_via_slot(page, live_server):
    from tests.factories import ContentNodeFactory, CourseFactory
    from courses.models import ContentNode
    pa = _make_pa_user("pa9w2")
    course = CourseFactory(slug="ws2mv", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch1")
    items = [ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title=f"L{i}") for i in range(1, 5)]
    _login(page, live_server, "pa9w2")
    page.goto(f"{live_server.url}/manage/courses/ws2mv/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    # Open the Move picker for L1; choose Ch1 as destination; pick the slot between L3 and L4.
    page.locator(f'a[data-move="{items[0].pk}"]').click()
    page.locator(f'[data-move-tree] [data-dest="{ch.pk}"]').wait_for(state="visible", timeout=5000)
    page.locator(f'[data-move-tree] [data-dest="{ch.pk}"]').click()
    # slot between L3 and L4: after excluding the moving L1, others=[L2,L3,L4]; insert-before L4 => position 2
    page.locator('[data-move-slot="2"]').click()
    page.locator('.move-picker__submit').click()
    # final order under Ch1 must be [L2, L3, L1, L4]
    page.wait_for_function(
        "([sel, want]) => {const ol=document.querySelector(sel); if(!ol) return false;"
        "const got=Array.from(ol.children).filter(li=>li.classList.contains('tree__row'))"
        ".map(li=>li.getAttribute('data-node')); return got.join(',')===want;}",
        arg=[f'[data-scope=\"{ch.pk}\"]', ",".join(str(items[i].pk) for i in (1, 2, 0, 3))],
        timeout=5000,
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_e2e_builder_ws2.py::test_move_picker_places_between_via_slot -m e2e -v`
Expected: FAIL (no `[data-move-slot]` UI yet).

- [ ] **Step 3: Implement the picker enhancement in `builder.js`**

The existing `click` handler loads the picker via `panel.innerHTML = html` on `[data-move]`. After that fetch resolves, initialize the enhanced UI. Add a `data-move` post-load hook and the slot logic. Key behaviors: hide `.move-picker__raw`, show `[data-move-tree]`, mark the moving node, wire destination + slot clicks that write the hidden `new_parent` select value (so `parent_token` syncs from its option's `data-updated`) and the hidden `position`. **The raw `select[name='new_parent']` and `input[name='position']` must stay in the DOM — hidden (`.hidden = true`), never removed** — because the existing submit handler reads the select's selected-option `data-updated` for `parent_token`, and the slot logic writes both.

```javascript
  var movingPk = null;
  function clearMoving() {
    if (movingPk == null) return;
    var r = root.querySelector('[data-node="' + movingPk + '"]');
    if (r) r.classList.remove("moving");
    movingPk = null;
  }
  function initPicker(nodePk) {
    var form = panel.querySelector("form.move-picker");
    if (!form) return;
    clearMoving();
    movingPk = nodePk;
    var row = root.querySelector('[data-node="' + nodePk + '"]');
    if (row) row.classList.add("moving");
    form.querySelectorAll(".move-picker__raw").forEach(function (n){ n.hidden = true; });
    var tree = form.querySelector("[data-move-tree]");
    if (tree) tree.hidden = false;
    var rawSelect = form.querySelector("select[name='new_parent']");
    var rawPos = form.querySelector("input[name='position']");
    tree.addEventListener("click", function (e) {
      var dest = e.target.closest(".move-dest");
      if (dest) {
        tree.querySelectorAll(".move-dest").forEach(function(d){ d.classList.remove("sel"); });
        tree.querySelectorAll(".move-dest-children").forEach(function(o){ o.hidden = true; });
        dest.classList.add("sel");
        rawSelect.value = dest.getAttribute("data-dest");            // syncs parent_token source
        var kids = dest.getAttribute("data-dest") === "top"
          ? tree.querySelector('[data-children-for="top"]')          // top owns its own <ol>
          : dest.parentElement.querySelector(".move-dest-children");  // candidate's sibling <ol>
        renderSlots(kids, nodePk, rawPos);
        return;
      }
      var slot = e.target.closest("[data-move-slot]");
      if (slot) {
        tree.querySelectorAll("[data-move-slot]").forEach(function(s){ s.classList.remove("sel"); });
        slot.classList.add("sel");
        rawPos.value = slot.getAttribute("data-move-slot");
      }
    });
  }
  function renderSlots(kidsOl, nodePk, rawPos) {
    if (!kidsOl) return;
    kidsOl.hidden = false;
    // children excluding the moving node => "others"; slots are insert-before indices 0..N
    var others = Array.prototype.slice.call(kidsOl.querySelectorAll("li"))
      .filter(function (li) { return li.getAttribute("data-child-pk") !== String(nodePk); });
    var frag = "";
    function slotHtml(i) { return '<li class="move-slot" data-move-slot="' + i + '">'
      + '<span class="move-slot__mark"></span></li>'; }
    frag += slotHtml(0);
    others.forEach(function (li, i) { frag += '<li class="move-anchor">' + li.textContent + '</li>' + slotHtml(i + 1); });
    kidsOl.innerHTML = frag;
    rawPos.value = "";   // until a slot is chosen, empty => append
  }
```

Hook `initPicker` after the picker loads. In the existing `[data-move]` click branch, change the `.then` that sets `panel.innerHTML` to also call `initPicker(parseInt(mv.getAttribute("data-move"), 10))` after assignment.

**Lifecycle clearing (exact edits).** `clearMoving`/`movingPk` are IIFE-scoped here; `clearMoving` is a hoisted `function` and `movingPk` initializes to `null` at load, so calling `clearMoving()` from the earlier-positioned submit handler is safe at runtime.
- (a) In the existing submit handler, immediately after the line `if (inPanel) refreshPanel(form);`, add `clearMoving();`.
- (b) In the existing `[data-select]` click branch (the one that does `panel.innerHTML = html`), add `clearMoving();` before its `fetch` — selecting another node ends any in-progress move.
- (c) Add a panel-scoped Escape handler: `root.addEventListener("keydown", function (e) { if (e.key === "Escape" && panel.querySelector("form.move-picker")) clearMoving(); });`

- [ ] **Step 4: Add picker CSS to `builder.css`**

```css
.move-picker__head { font-weight: 600; margin-bottom: var(--space-2); }
.js .move-picker__raw { display: none; }            /* hidden when JS builds the tree */
.move-dest { display: block; width: 100%; text-align: left; background: none; border: none; cursor: pointer; padding: 2px 6px; border-radius: var(--radius-sm); color: var(--text-primary); }
.move-dest--chapter { padding-left: 18px; }   /* indent by kind to convey hierarchy */
.move-dest--section { padding-left: 34px; }
.move-dest.sel { color: var(--primary); font-weight: 700; }
.move-dest-children { list-style: none; margin: 0; padding-left: 16px; }
.move-anchor { color: var(--text-secondary); padding: 1px 0; }
.move-slot { list-style: none; height: 8px; cursor: pointer; }
.move-slot__mark { display: block; height: 2px; background: transparent; border-radius: 2px; }
.move-slot:hover .move-slot__mark, .move-slot.sel .move-slot__mark { background: var(--primary); }
.tree__row.moving { outline: 2px solid var(--primary); border-radius: var(--radius-sm); }
```

- [ ] **Step 5: Rewrite the stale-picker e2e for the enhanced UI, then run**

`tests/test_e2e_builder_reorder.py::test_move_picker_not_left_stale_after_reparent` (from the #9 fix) drives the now-hidden raw `select[name='new_parent']` (`sel.wait_for(state="visible")` + `select_option`). Rewrite its two picker interactions to the enhanced UI (destination button → slot → submit), keeping the same stale-token / move-back assertions:

```python
    # First move: Intro -> Section A (was: select_option on the raw select)
    page.locator(f'a[data-move="{intro.pk}"]').click()
    dest = page.locator(f'[data-panel] [data-move-tree] [data-dest="{sec_a.pk}"]')
    dest.wait_for(state="visible", timeout=5000)
    dest.click()
    page.locator('[data-panel] [data-move-slot="0"]').click()
    page.locator('[data-panel] .move-picker__submit').click()
    # ... existing "Intro now under Section A" wait + the stale-picker assertion stay ...
    # Move back: Intro -> Top level via a FRESH picker
    page.locator(f'a[data-move="{intro.pk}"]').click()
    top = page.locator('[data-panel] [data-move-tree] [data-dest="top"]')
    top.wait_for(state="visible", timeout=5000)
    top.click()
    page.locator('[data-panel] [data-move-slot="0"]').click()
    page.locator('[data-panel] .move-picker__submit').click()
```

The stale-token assertion (`form[data-op="reparent"] input[name="node_token"][value="{stale_token}"]` count == 0) and the move-back / no-409 assertions are unchanged — the new picker still refreshes the panel after a successful move (the #9 fix).

Then run: `.venv/Scripts/python.exe -m pytest tests/test_e2e_builder_ws2.py tests/test_e2e_builder_reorder.py -m e2e -v`
Expected: PASS (incl. the [L2,L3,L1,L4] placement and the rewritten stale-picker test).

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/builder.js courses/static/courses/css/builder.css tests/test_e2e_builder_ws2.py tests/test_e2e_builder_reorder.py
git commit -m "feat(builder): move picker indented destinations + insertion slots + moving highlight (WS2 #8)"
```

---

## Task 7: Drag-and-drop (pointer devices)

Add pointer drag from the grip handle: dragover shows an insertion line + container highlight on legal targets only; drop POSTs `mode=reparent` with `new_parent` + insert-before `position` (excluding the dragged node).

**Files:**
- Modify: `templates/courses/manage/builder.html` (add `data-node-move-url` on `.builder`)
- Modify: `courses/static/courses/js/builder.js`
- Modify: `courses/static/courses/css/builder.css` (drag visuals)
- Test: `tests/test_e2e_builder_ws2.py` (drag reorder + reparent + illegal-refusal)

- [ ] **Step 1: Write the failing e2e test**

Add to `tests/test_e2e_builder_ws2.py` a drag test. Playwright drag uses `drag_to` or manual mouse moves; for HTML5 DnD use `page.drag_and_drop(source, target)`. Test same-parent reorder lands at the dropped slot and a cross-parent reparent works:

```python
@pytest.mark.django_db(transaction=True)
def test_drag_reparent_into_section(page, live_server):
    from tests.factories import ContentNodeFactory, CourseFactory
    from courses.models import ContentNode
    pa = _make_pa_user("pa9w3")
    course = CourseFactory(slug="ws2dnd", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch1")
    intro = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="Intro")
    sec = ContentNodeFactory(course=course, kind="section", unit_type=None, parent=ch, title="SecA")
    _login(page, live_server, "pa9w3")
    page.goto(f"{live_server.url}/manage/courses/ws2dnd/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    src = page.locator(f'li.tree__row[data-node="{intro.pk}"] .ica--grip')
    dst = page.locator(f'li.tree__row[data-node="{sec.pk}"]')
    src.drag_to(dst)
    page.wait_for_function(
        "([sel, pk]) => {const ol=document.querySelector(sel); return ol && "
        "Array.from(ol.children).some(li=>li.classList.contains('tree__row') && li.getAttribute('data-node')===pk);}",
        arg=[f'[data-scope=\"{sec.pk}\"]', str(intro.pk)],
        timeout=5000,
    )
    assert ContentNode.objects.get(pk=intro.pk).parent_id == sec.pk
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_e2e_builder_ws2.py::test_drag_reparent_into_section -m e2e -v`
Expected: FAIL (no drag wiring).

- [ ] **Step 3: Implement drag-and-drop in `builder.js`**

Use native HTML5 DnD. The grip has `draggable="true"`; on `dragstart` from a grip, record the dragged row's pk + kind + token. On `dragover` over a row/scope, compute the target container + insert-before index (excluding the dragged node), check legality via a JS RANK map, and draw the insertion line; on `drop`, POST `mode=reparent`. Add a RANK constant mirroring the server:

```javascript
  // --- WS2 drag-and-drop ----------------------------------------------------
  var RANK = { part: 0, chapter: 1, section: 2, unit: 3 };
  var drag = null;  // { pk, kind, token }
  root.addEventListener("dragstart", function (e) {
    var grip = e.target.closest(".ica--grip");
    if (!grip) return;
    var row = grip.closest(".tree__row");
    drag = { pk: row.getAttribute("data-node"), kind: row.getAttribute("data-kind"),
             token: row.getAttribute("data-updated") };
    e.dataTransfer.effectAllowed = "move";
  });
  function targetFor(y, scope) {
    // scope = the <ol data-scope>; rows = its direct .tree__row children excluding the dragged one
    var rows = Array.prototype.slice.call(scope.children)
      .filter(function (li) { return li.classList.contains("tree__row")
        && li.getAttribute("data-node") !== drag.pk; });
    var i = 0;
    for (; i < rows.length; i++) {
      var r = rows[i].getBoundingClientRect();
      if (y < r.top + r.height / 2) break;
    }
    return { index: i, before: rows[i] || null };   // insert-before index
  }
  function legal(parentKind) {
    return RANK[drag.kind] > (parentKind == null ? -1 : RANK[parentKind]);
  }
  function clearDropMarks() {
    root.querySelectorAll(".drop-target").forEach(function (n){ n.classList.remove("drop-target"); });
    root.querySelectorAll(".drop-line").forEach(function (n){ n.remove(); });
  }
  root.addEventListener("dragover", function (e) {
    if (!drag) return;
    var scope = e.target.closest(".tree__scope");
    if (!scope) return;
    var destPk = scope.getAttribute("data-scope");          // "top" or pk
    var destRow = scope.closest(".tree__row");               // the container row (null for top)
    var parentKind = destRow ? destRow.getAttribute("data-kind") : null;
    // forbid dropping into self/descendant: scope must not be inside the dragged row
    var draggedRow = root.querySelector('.tree__row[data-node="' + drag.pk + '"]');
    if (!legal(parentKind) || (draggedRow && draggedRow.contains(scope))) { clearDropMarks(); return; }
    e.preventDefault();
    clearDropMarks();
    scope.classList.add("drop-target");
    var t = targetFor(e.clientY, scope);
    var line = document.createElement("div");
    line.className = "drop-line";
    if (t.before) scope.insertBefore(line, t.before); else scope.appendChild(line);
    scope.dataset.dropIndex = t.index;
    scope.dataset.dropParent = destPk;
    scope.dataset.dropToken = scope.getAttribute("data-updated");
  });
  root.addEventListener("drop", function (e) {
    if (!drag) return;
    var scope = e.target.closest(".tree__scope.drop-target");
    if (!scope) { clearDropMarks(); drag = null; return; }
    e.preventDefault();
    var body = new FormData();
    body.append("mode", "reparent");
    body.append("node", drag.pk);
    body.append("node_token", drag.token);
    body.append("new_parent", scope.dataset.dropParent);
    body.append("position", scope.dataset.dropIndex);
    body.append("parent_token", scope.dataset.dropToken);
    clearDropMarks(); drag = null; clearMoving();
    fetch(root.getAttribute("data-node-move-url"), {
      method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: body,
    }).then(function (r) { return r.text().then(function (text) {
      if (r.status === 200 || r.status === 409) {
        applyFragment(text);
        if (r.status === 409) notice("This changed elsewhere — refreshed to the latest.");
        // A drag bypasses the submit handler's panel-refresh (#9 fix). If the panel holds a
        // token-bearing form (e.g. the dragged node's Move picker / rename), it is now stale —
        // clear it so reusing it can't spuriously 409.
        if (panel.querySelector("form[data-op]")) panel.innerHTML = "";
      } else if (r.status === 422) { notice("That move isn’t allowed here."); }
    }); }).catch(function () { notice("Network error — please try again."); });
  });
  root.addEventListener("dragend", function () { clearDropMarks(); drag = null; });
```

> **Add the URL source to `builder.html`:** put `data-node-move-url="{% url 'courses:manage_node_move' slug=course.slug %}"` on the `<section class="builder" …>` tag. The drag handler reads `root.getAttribute("data-node-move-url")` — one stable, slug-scoped URL, present even in an empty tree, avoiding a fragile first-match `querySelector('form.tree__inline').action`. The `parent_token` for a top drop is the top scope's `data-updated` (the course token), exactly as `data-updated` already carries it.

- [ ] **Step 4: Add drag CSS to `builder.css`**

```css
.tree__scope.drop-target { background: color-mix(in srgb, var(--primary) 12%, transparent); border-radius: var(--radius-sm); }
.drop-line { height: 0; border-top: 2px solid var(--primary); margin: 1px 0; }
.ica--grip:active { cursor: grabbing; }
```

- [ ] **Step 5: Run the drag e2e + full e2e regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_e2e_builder_ws2.py tests/test_e2e_builder.py tests/test_e2e_builder_reorder.py -m e2e -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/builder.js courses/static/courses/css/builder.css tests/test_e2e_builder_ws2.py
git commit -m "feat(builder): pointer drag-and-drop reorder/re-parent with legality + insertion line (WS2 #9c)"
```

---

## Task 8: i18n (Polish) for new strings

New **template** (`{% trans %}`) strings were added — `makemessages` extracts these: `No children yet.`, `New title`, `More kinds`, `Move`, `Destination`, `Position`, `end`, `Move here`, `Drag to move`, `Move up`, `Move down`, `Move…`, `Delete`. Extract and translate to PL.

**Out of scope (JS literals):** the `notice()` strings in `builder.js` (`"That move isn’t allowed here."`, `"This changed elsewhere — refreshed to the latest."`, `"Network error — please try again."`) are JS string literals — `makemessages` does **not** extract them, so they ship untranslated regardless. That is the known **#9b-i18n** gap (pass translated text into the DOM via a `data-` attribute on the builder root); leave it to that dedicated i18n item, not this task. Do not expect them in `django.po`. Likewise, the contextual-"+" **chip kind labels** (Part/Chapter/Section/Unit) are NOT translated here — they mirror the existing untranslated tree badges and belong to the i18n sweep (#2).

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: none (build step) — verified by `makemessages`/`compilemessages` succeeding and no new empty msgids for these screens.

- [ ] **Step 1: Extract messages**

Run (Bash tool / POSIX): `.venv/Scripts/python.exe manage.py makemessages -l pl`
Expected: new `msgid`s for the WS2 strings appear in `locale/pl/LC_MESSAGES/django.po`.

- [ ] **Step 2: Translate the new msgids**

Fill the `msgstr` for each new WS2 `msgid` in `locale/pl/LC_MESSAGES/django.po` (e.g. `"No children yet."` → `"Brak elementów."`, `"Move here"` → `"Przenieś tutaj"`, `"Drag to move"` → `"Przeciągnij, aby przenieść"`, etc.). Match the tone of existing PL strings.

- [ ] **Step 3: Compile and verify no empty PL entries for these screens**

Run: `.venv/Scripts/python.exe manage.py compilemessages -l pl`
Then sanity-check: `grep -nA1 'msgid "Move here"' locale/pl/LC_MESSAGES/django.po` shows a non-empty `msgstr`.
Expected: compile succeeds; the new WS2 msgids are translated.

- [ ] **Step 4: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(builder): Polish for WS2 builder strings"
```

---

## Task 9: Final regression + DoD gate

**Files:** none (verification).

- [ ] **Step 1: Full default suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: all pass (no e2e).

- [ ] **Step 2: All e2e**

Run: `.venv/Scripts/python.exe -m pytest -m e2e`
Expected: all pass — incl. `test_e2e_builder_ws2.py` (inline add, slot placement [L2,L3,L1,L4], drag reparent), `test_e2e_builder_reorder.py`, `test_e2e_builder.py`.

- [ ] **Step 3: Lint / format / migrations / static**

Run: `.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check . && .venv/Scripts/python.exe manage.py makemigrations --check && .venv/Scripts/python.exe manage.py check && .venv/Scripts/python.exe manage.py collectstatic --noinput`
Expected: all clean; **no migration** produced (WS2 has no model changes).

- [ ] **Step 4: DoD checklist against spec §8**

Confirm each holds: legal `+` kinds per scope (Section → only `+ Unit`; top → `+ Chapter` + overflow); inline add creates the right kind; cluster visible + ↑/↓ reorder with boundary disabling; Move picker indented + insertion slots; same-parent placement off-by-one correct ([2,3,1,4]); drag reorder + reparent + illegal-refusal; top-level + empty-scope affordances render; no-JS fallback works (add via kind button; picker select + empty position appends); light + dark visual sanity (`docs/mockups/builder_accepted.html`).

- [ ] **Step 5: Final commit (if any DoD fixups)**

```bash
git add -A && git commit -m "chore(builder): WS2 final regression + DoD fixups"
```

---

## Notes for the executor

- **No backend changes.** If a task tempts you to edit `courses/builder.py`/`ordering.py` beyond `legal_child_kinds`/`PRIMARY_CHILD_KIND`, stop — the endpoints and `place_node`/token contract are reused as-is.
- **Progressive enhancement is load-bearing.** Every interactive feature must degrade: no-JS add (kind submit buttons), no-JS move (select + empty position = append), reorder (real submit buttons). The `.js` class gate keeps the enhanced CSS from hiding no-JS controls.
- **e2e are excluded by default** (`-m 'not e2e'`); run them explicitly. They can be timing-sensitive on Windows — use the `wait_for_function`/`wait_for_selector` patterns already in `test_e2e_builder_reorder.py`.
- **Static refresh:** after CSS/JS edits, the dev server needs `collectstatic` + Ctrl+F5; tests serve static directly so they don't.
