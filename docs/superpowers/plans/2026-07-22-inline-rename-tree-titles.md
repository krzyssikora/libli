# Inline Rename of Tree Node Titles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every course-builder tree row's title directly editable in place — for parts, chapters, sections **and units** — replacing the detail panel's rename form.

**Architecture:** The title `<button>` in each tree row becomes a one-field `<form data-op="rename">` wrapping a text `<input>`, riding the existing `builder.js` fetch interceptor. Crucially, a tree-row rename does **not** re-render a tree scope: `node_rename` returns a tiny `_rename_result.html` fragment and the JS patches the row in place (title, tooltip, and every DOM carrier of the node's `updated` token). Nothing is destroyed, so there is no focus loss, no restoration, and no concurrency gate. The input is `readOnly` for the duration of the round trip, which makes mid-flight edits impossible rather than recoverable.

**Tech Stack:** Django 5.2 templates + views, vanilla ES5-style JS (no build step, no framework), plain CSS with design tokens, pytest + pytest-django, Playwright for e2e.

## Global Constraints

- Read the spec before starting: `docs/superpowers/specs/2026-07-22-inline-rename-tree-titles-design.md`. It carries the reasoning behind every non-obvious rule here.
- **Tooling:** bare `pytest` / `ruff` / `python` are **not** on PATH. Always `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`.
- **This worktree runs concurrently with others.** Export a unique `DATABASE_URL` before running tests, or you will collide with another worktree on the Postgres `test_libli` database. Example: `export DATABASE_URL=postgres://postgres:postgres@localhost:5432/libli_rename`.
- **Falsify every test before accepting it.** Break the thing the test guards and require RED. A passing test that never fails proves nothing. Where a step names a specific falsification, perform it.
- **JS style:** `builder.js` is a single IIFE using `var`, `function`, and `Array.prototype.slice.call`. Match it. No `let`/`const`/arrow functions/optional chaining — and note `form.querySelector(...)?.readOnly = false` is a *syntax error* regardless.
- **Django template comments** must be `{% comment %}…{% endcomment %}` for anything multi-line; `{# #}` is single-line only or it renders visibly.
- **i18n:** any module-level translatable string uses `gettext_lazy`. Do not leave obsolete `#~` entries in `.po` files — the catalog tests reject them.
- Commit after each task. Do not push; the pipeline handles that.

---

### Task 1: Server-side title normalization, shared by rename and add

**Files:**
- Modify: `courses/builder.py` (add helper; call from `add_node` ~line 146-156 and `rename_node` ~line 163-190)
- Test: `tests/test_manage_node_ops.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `courses.builder._clean_title(title) -> str` — strips leading/trailing whitespace from a title. Called by `add_node` and `rename_node` *before* `full_clean()`.

**Why:** `ContentNode.title` is `CharField(max_length=200)` and `ContentNode.clean()` validates only parent/kind/unit_type. `full_clean()` rejects `""`, but `"   "` is **not** in Django's `EMPTY_VALUES`, so a whitespace-only title currently validates and persists. Client-side trimming cannot fix this because the no-JS path posts whatever was typed.

Normalization must live in these service functions, **not** in `ContentNode.clean()`: `full_clean()` runs `clean_fields()` (which enforces `blank`) *before* `clean()`, so stripping inside `clean()` would let `"   "` pass the blank check and then persist as `""`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_manage_node_ops.py`:

```python
@pytest.mark.django_db
def test_rename_strips_surrounding_whitespace(client):
    _, course = _setup(client)
    node = ContentNodeFactory(course=course, kind="part", parent=None, title="Old")
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": node.pk, "token": _tok(node), "title": "  Fractions  "},
        **FETCH,
    )
    assert resp.status_code == 200
    node.refresh_from_db()
    assert node.title == "Fractions"


@pytest.mark.django_db
def test_rename_rejects_whitespace_only_title(client):
    _, course = _setup(client)
    node = ContentNodeFactory(course=course, kind="part", parent=None, title="Old")
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": node.pk, "token": _tok(node), "title": "   "},
        **FETCH,
    )
    assert resp.status_code == 422
    node.refresh_from_db()
    assert node.title == "Old"


@pytest.mark.django_db
def test_add_strips_surrounding_whitespace(client):
    _, course = _setup(client)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {
            "parent": "top",
            "parent_token": course.updated.isoformat(),
            "kind": "part",
            "title": "  Foo  ",
        },
        **FETCH,
    )
    assert resp.status_code == 200
    assert ContentNode.objects.filter(course=course, title="Foo").exists()


@pytest.mark.django_db
def test_strip_happens_before_length_validation(client):
    # A 200-char title wrapped in spaces must persist intact: only possible if the
    # strip runs BEFORE full_clean()'s max_length check. Service/POST-level only --
    # maxlength="200" in the browser counts the untrimmed string, so this case is
    # unreachable by typing into the tree input.
    _, course = _setup(client)
    node = ContentNodeFactory(course=course, kind="part", parent=None, title="Old")
    exact = "x" * 200
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": node.pk, "token": _tok(node), "title": "  " + exact + "  "},
        **FETCH,
    )
    assert resp.status_code == 200
    node.refresh_from_db()
    assert node.title == exact

    too_long = "y" * 201
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": node.pk, "token": _tok(node), "title": too_long},
        **FETCH,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_type_only_toggle_still_preserves_title(client):
    # Guards the _UNSET branch: normalization must not turn "leave the title alone"
    # into "set the title to ''".
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Keep me"
    )
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {
            "node": unit.pk,
            "token": _tok(unit),
            "type_only": "1",
            "unit_type": "quiz",
        },
        **FETCH,
    )
    assert resp.status_code == 200
    unit.refresh_from_db()
    assert unit.unit_type == "quiz"
    assert unit.title == "Keep me"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_manage_node_ops.py -k "strip or whitespace_only or length_validation" -v
```

Expected: `test_rename_strips_surrounding_whitespace` FAILS (title is `"  Fractions  "`), `test_rename_rejects_whitespace_only_title` FAILS (200, title `"   "`), `test_add_strips_surrounding_whitespace` FAILS, `test_strip_happens_before_length_validation` FAILS.

- [ ] **Step 3: Add the helper and call it from both writers**

In `courses/builder.py`, add near the other module-level helpers (above `add_node`):

```python
def _clean_title(title):
    """Normalize a node title before validation.

    Strips surrounding whitespace so a whitespace-only title becomes "" and is
    rejected by full_clean()'s blank check on EVERY path -- JS, no-JS, and the
    editor settings form. This deliberately does NOT live in ContentNode.clean():
    full_clean() runs clean_fields() (which enforces blank) BEFORE clean(), so
    stripping there would let "   " pass the blank check and persist as "".

    Not applied by course import/transfer, which builds ContentNode directly
    rather than going through add_node/rename_node.
    """
    return title.strip()
```

In `add_node`, change the `ContentNode(...)` construction:

```python
    node = ContentNode(
        course=course,
        parent=parent,
        kind=kind,
        title=_clean_title(title),
        unit_type=(unit_type or None),
    )
```

In `rename_node`, change the title branch:

```python
    if title is not _UNSET:
        node.title = _clean_title(title)
        fields.append("title")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_manage_node_ops.py -v
```

Expected: all PASS, including the pre-existing rename/add tests.

- [ ] **Step 5: Falsify**

Temporarily change `_clean_title` to `return title`. Re-run: the four new tests must go RED. Then change it back and confirm GREEN. Separately, move the `.strip()` to *after* `node.full_clean()` in `rename_node` and confirm `test_strip_happens_before_length_validation` goes RED — that is the case that ordering test exists for.

- [ ] **Step 6: Commit**

```bash
git add courses/builder.py tests/test_manage_node_ops.py
git commit -m "feat(builder): strip node titles in add_node and rename_node

Whitespace-only titles previously validated and persisted: full_clean()
rejects "" but "   " is not in Django's EMPTY_VALUES. A shared _clean_title
helper runs before full_clean() on both writers, so every path -- JS, no-JS
and the editor settings form -- rejects them."
```

---

### Task 2: The narrow rename response

**Files:**
- Create: `templates/courses/manage/_rename_result.html`
- Modify: `courses/views_manage.py` (`node_rename` success tail, ~lines 341-349)
- Test: `tests/test_manage_node_ops.py`

**Interfaces:**
- Consumes: `_clean_title` from Task 1 (indirectly, via `rename_node`).
- Produces: the fragment contract the JS depends on in Task 7 — a 200 response body containing
  `<data data-rename-for="{pk}" data-updated="{iso8601}" value="{new title}"></data>`.

**Why:** Every other builder op changes tree *structure*, so it responds with a re-rendered scope that `applyFragment` swaps in. A rename changes one label and one token — swapping a scope would destroy the `<input>` being typed in. This response is what makes the whole in-place design possible.

Once Task 3 deletes the panel's rename form, the plain-rename fragment branch has exactly one caller: a tree row. (`ctx=editor` is checked first, and both editor posters send it as full-page POSTs, so `_wants_fragment` is false for them.)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_manage_node_ops.py`:

```python
@pytest.mark.django_db
def test_tree_rename_returns_narrow_fragment_not_a_scope(client):
    # The pivot of the design: a tree-row rename must NOT return a [data-scope]
    # tree fragment, or the JS would swap away the input being typed in.
    _, course = _setup(client)
    node = ContentNodeFactory(course=course, kind="part", parent=None, title="Old")
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": node.pk, "token": _tok(node), "title": "New"},
        **FETCH,
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    node.refresh_from_db()
    assert "data-scope" not in body
    assert f'data-rename-for="{node.pk}"' in body
    assert f'data-updated="{node.updated.isoformat()}"' in body
    assert 'value="New"' in body


@pytest.mark.django_db
def test_tree_rename_fragment_escapes_the_title(client):
    _, course = _setup(client)
    node = ContentNodeFactory(course=course, kind="part", parent=None, title="Old")
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": node.pk, "token": _tok(node), "title": 'A "quoted" & <b>bold</b>'},
        **FETCH,
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "<b>bold</b>" not in body
    assert "&quot;quoted&quot;" in body or "&#x27;" in body or "&amp;" in body


@pytest.mark.django_db
def test_no_js_rename_still_redirects_to_the_builder(client):
    _, course = _setup(client)
    node = ContentNodeFactory(course=course, kind="part", parent=None, title="Old")
    resp = client.post(  # no FETCH header
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": node.pk, "token": _tok(node), "title": "New"},
    )
    assert resp.status_code == 302
    assert resp.url == reverse("courses:manage_builder", kwargs={"slug": "c1"})
    node.refresh_from_db()
    assert node.title == "New"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_manage_node_ops.py -k "narrow_fragment or fragment_escapes" -v
```

Expected: FAIL — the body currently contains `data-scope` and no `data-rename-for`. (`test_no_js_rename_still_redirects_to_the_builder` should already PASS; it is a regression guard.)

- [ ] **Step 3: Create the fragment template**

Create `templates/courses/manage/_rename_result.html`:

```html
{% comment %}Narrow response for a tree-row rename. A rename changes no tree structure --
only one label and one optimistic-lock token -- so responding with a re-rendered scope
would destroy the <input> the author is typing in. builder.js reads these attributes and
patches the row in place. See the design doc, "The central design decision".{% endcomment %}
<data data-rename-for="{{ node.pk }}"
      data-updated="{{ node.updated.isoformat }}"
      value="{{ node.title }}"></data>
```

- [ ] **Step 4: Return it from the view**

In `courses/views_manage.py`, replace the tail of `node_rename` (the two lines after the `is_settings` branch):

```python
    # a unit-settings change re-renders the unit panel; a plain rename re-renders scope
    if is_settings and node.kind == ContentNode.Kind.UNIT:
        return _render_unit_panel(request, node)
    # rename changes only the node row; re-render its parent scope so the label updates
    return _render_scope(request, course, _scope_ref(node.parent_id))
```

with:

```python
    # a unit-settings change re-renders the unit panel
    if is_settings and node.kind == ContentNode.Kind.UNIT:
        return _render_unit_panel(request, node)
    # A plain rename now has exactly one fragment caller: a builder tree row. It changes
    # no structure, so it returns the new title + token for that row and builder.js
    # patches in place -- re-rendering the scope would destroy the focused input.
    return render(request, "courses/manage/_rename_result.html", {"node": node})
```

`render` is already imported in this module.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/test_manage_node_ops.py tests/test_manage_element_ops.py -v
```

Expected: all PASS. The three pre-existing `manage_node_rename` tests in `test_manage_element_ops.py` assert only status + DB state, so they stay green.

- [ ] **Step 6: Falsify**

Revert the view tail to `_render_scope(...)`. `test_tree_rename_returns_narrow_fragment_not_a_scope` must go RED. Restore.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/_rename_result.html courses/views_manage.py tests/test_manage_node_ops.py
git commit -m "feat(builder): narrow response for tree-row renames

A rename changes no tree structure, so re-rendering the parent scope would
destroy the input being typed in. Return the new title + token for that one
row instead; builder.js will patch it in place."
```

---

### Task 3: The editable tree-row title

**Files:**
- Modify: `templates/courses/manage/_tree_node.html` (lines 12-13)
- Modify: `templates/courses/manage/_node_panel.html` (remove the include)
- Delete: `templates/courses/manage/_rename_form.html`
- Modify: `tests/test_tree_badge.py` (line 23 regex)
- Test: `tests/test_manage_builder.py`

**Interfaces:**
- Consumes: the `courses:manage_node_rename` URL (unchanged).
- Produces: the DOM contract Tasks 5-7 depend on — `form.tree__rename[data-op="rename"]` containing hidden `node` + `token` and `input.tree__title[data-panel-url]`, inside `li.tree__row[data-node][data-updated] > .tree__rowhead`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_manage_builder.py` (match the existing imports/fixtures in that file; it already logs in an owner and requests the builder page):

```python
@pytest.mark.django_db
@pytest.mark.parametrize(
    "kind,unit_type",
    [("part", None), ("chapter", None), ("section", None), ("unit", "lesson")],
)
def test_every_tree_row_title_is_an_editable_form(client, kind, unit_type):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    node = ContentNodeFactory(
        course=course, kind=kind, unit_type=unit_type, parent=None, title="Fractions"
    )
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "c1"})
    ).content.decode()
    assert 'class="tree__rename"' in html
    assert 'data-op="rename"' in html
    assert f'<input type="hidden" name="node" value="{node.pk}">' in html
    assert f'value="{node.updated.isoformat()}"' in html
    assert 'class="tree__title" type="text" name="title" value="Fractions"' in html
    assert "required" in html
    assert 'maxlength="200"' in html
    assert 'autocomplete="off"' in html
    assert 'spellcheck="false"' in html
    # data-select had exactly two readers (the click branch and refreshPanel); both are
    # removed by this change, so it must not be carried on ~800 rows for nothing.
    assert "data-select" not in html


@pytest.mark.django_db
def test_tree_title_has_a_static_accessible_name_and_a_title_tooltip(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(course=course, kind="part", parent=None, title="Fractions")
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "c1"})
    ).content.decode()
    assert 'aria-label="Title"' in html
    assert 'title="Fractions"' in html


@pytest.mark.django_db
def test_hidden_rename_submit_is_out_of_the_tab_order(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(course=course, kind="part", parent=None, title="Fractions")
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "c1"})
    ).content.decode()
    # .visually-hidden uses the clip pattern, which keeps the element FOCUSABLE --
    # without tabindex="-1" every row would gain a second tab stop.
    assert 'class="visually-hidden" type="submit" tabindex="-1"' in html


@pytest.mark.django_db
def test_node_panel_no_longer_offers_a_rename_form(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    node = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    html = client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "c1", "pk": node.pk}),
        HTTP_X_REQUESTED_WITH="fetch",
    ).content.decode()
    assert 'data-op="rename"' not in html


def test_rename_form_partial_is_deleted():
    from pathlib import Path

    p = (
        Path(__file__).resolve().parent.parent
        / "templates"
        / "courses"
        / "manage"
        / "_rename_form.html"
    )
    assert not p.exists(), "_rename_form.html is dead code once the panel form is gone"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_manage_builder.py -k "editable_form or accessible_name or tab_order or no_longer_offers or partial_is_deleted" -v
```

Expected: all FAIL.

- [ ] **Step 3: Replace the title button with the rename form**

In `templates/courses/manage/_tree_node.html`, replace lines 12-13:

```html
    <button class="tree__title" type="button" data-select="{{ node.pk }}" title="{{ node.title }}"
            data-panel-url="{% url 'courses:manage_node_panel' slug=node.course.slug pk=node.pk %}">{{ node.title }}</button>
```

with:

```html
    {% comment %}The form wraps ONLY the title, so it sits inside .tree__rowhead as a
       sibling of .tree__cluster and never nests the duplicate/reorder forms that live
       within that cluster (nested forms are invalid HTML). The hidden submit exists so
       the no-JS path can commit; tabindex="-1" keeps it out of the tab order, since
       .visually-hidden uses clip and stays focusable.{% endcomment %}
    <form class="tree__rename" method="post" action="{% url 'courses:manage_node_rename' slug=node.course.slug %}" data-op="rename">
      {% csrf_token %}
      <input type="hidden" name="node" value="{{ node.pk }}">
      <input type="hidden" name="token" value="{{ node.updated.isoformat }}">
      <input class="tree__title" type="text" name="title" value="{{ node.title }}"
             title="{{ node.title }}" aria-label="{% trans 'Title' %}"
             required maxlength="200" autocomplete="off" spellcheck="false"
             data-panel-url="{% url 'courses:manage_node_panel' slug=node.course.slug pk=node.pk %}">
      <button class="visually-hidden" type="submit" tabindex="-1">{% trans "Rename" %}</button>
    </form>
```

The accessible name is a static `Title` rather than an interpolated kind or title: a text input's *value* is announced alongside its name so the value already distinguishes rows; interpolating the kind would need a Polish genitive (`Tytuł rozdziału`) that `get_kind_display` cannot supply, and interpolating the title would go stale the moment the author types.

- [ ] **Step 4: Remove the panel's rename form and delete the partial**

In `templates/courses/manage/_node_panel.html`, delete line 4:

```html
  {% include "courses/manage/_rename_form.html" with node=node %}
```

leaving:

```html
{% load i18n %}
<div class="panel" data-panel-for="{{ node.pk }}">
  <h2>{{ node.get_kind_display }}: {{ node.title }}</h2>
</div>
```

Then:

```bash
git rm templates/courses/manage/_rename_form.html
```

`_node_panel.html:4` was its only consumer anywhere in the repo — `editor/_unit_settings.html` carries its own form markup rather than including it.

- [ ] **Step 5: Retarget the tree-badge regex**

In `tests/test_tree_badge.py` line 23, change:

```python
TITLE_BTN_RE = re.compile(r'<button class="tree__title"[^>]*\btitle="([^"]*)"')
```

to:

```python
TITLE_BTN_RE = re.compile(r'<input class="tree__title"[^>]*\btitle="([^"]*)"')
```

The `\b` before `title=` is what stops `name="title"` from false-matching; keep it.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/test_manage_builder.py tests/test_tree_badge.py -v
```

Expected: all PASS.

- [ ] **Step 7: Falsify**

Wrap the new form in `{% if node.kind != "unit" %}`. The `unit` parametrization of `test_every_tree_row_title_is_an_editable_form` must go RED — that is the exact regression this feature exists to prevent. Remove the guard.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/manage/_tree_node.html templates/courses/manage/_node_panel.html tests/test_manage_builder.py tests/test_tree_badge.py
git commit -m "feat(builder): editable title input on every tree row

Replaces the title button with a one-field rename form, and removes the
detail panel's rename form (and its now-dead partial). Units gain in-tree
renaming for the first time; previously they required a trip to the editor."
```

---

### Task 4: Styling the input so the tree does not become a wall of boxes

**Files:**
- Modify: `courses/static/courses/css/builder.css` (line 38)
- Test: `tests/test_builder_styles.py`

**Interfaces:**
- Consumes: the `input.tree__title` / `.tree__rename` markup from Task 3.
- Produces: nothing consumed by later tasks.

**Two things break when a button becomes an input:**

1. **Cascade.** `core/static/core/css/app.css:136` sets `input[type=text], … { width: 100%; padding: …; background: var(--surface-sunken); border: 1px solid var(--border-strong); border-radius: … }`. That selector is specificity (0,1,1), so a bare `.tree__title` — (0,1,0) — loses outright and every row renders as a bordered, sunken-filled box. Qualifying to `input.tree__title` raises it to (0,1,1): a **tie**, not a win, resolved by source order — which resolves correctly because `base.html:46` loads `app.css` and `builder.html:4` injects `builder.css` in the later `{% block extra_css %}`. This is why the test below asserts *declarations*, not a specificity relationship that does not exist.
2. **Font.** An `<input>` does not inherit `font-family`/`font-size`; it falls back to the UA default (~13.33px Arial). `font: inherit` is required or every tree label silently changes typeface.

- [ ] **Step 1: Write the failing tests**

In `tests/test_builder_styles.py`, replace `test_tree_title_truncates_with_ellipsis` with the version below and append the two new tests:

```python
def test_tree_title_truncates_with_ellipsis():
    css = _css()
    assert re.search(r"\.tree__title\s*\{[^}]*text-overflow:\s*ellipsis", css), (
        ".tree__title must truncate with an ellipsis"
    )
    assert re.search(r"\.tree__title\s*\{[^}]*min-width:\s*0", css), (
        ".tree__title needs min-width:0 to shrink below content width"
    )
    assert re.search(r"\.tree__title\s*\{[^}]*white-space:\s*nowrap", css), (
        ".tree__title needs white-space:nowrap for single-line truncation"
    )


def test_tree_title_input_neutralises_the_global_form_control_rule():
    # app.css:136 styles input[type=text] with a sunken background, a strong border and
    # padding. It ties input.tree__title on specificity (0,1,1) and is only beaten by
    # builder.css loading later, so the rule must explicitly reset each property --
    # assert the DECLARATIONS, not specificity.
    css = _css()
    rule = re.search(r"input\.tree__title\s*\{[^}]*\}", css)
    assert rule, "the rule must be written literally as `input.tree__title { ... }`"
    body = rule.group(0)
    assert re.search(r"font:\s*inherit", body), (
        "an <input> does not inherit font-family/font-size; without font:inherit every "
        "tree label falls back to the UA default (~13.33px Arial)"
    )
    assert re.search(r"background:\s*none", body), "must reset the sunken background"
    assert re.search(r"padding:\s*0", body), "must reset the global padding"
    assert re.search(r"border:\s*1px\s+solid\s+transparent", body), (
        "a transparent rest border keeps :hover layout-neutral -- adding a border on "
        "hover to a border-less element shifts text and grows the row"
    )


def test_tree_rename_form_is_a_shrinkable_flex_item():
    css = _css()
    rule = re.search(r"\.tree__rename\s*\{[^}]*\}", css)
    assert rule, ".tree__rename must be styled"
    body = rule.group(0)
    assert re.search(r"min-width:\s*0", body), (
        ".tree__rename is now the flex item and would otherwise blow out the row"
    )
    assert re.search(r"margin:\s*0", body), (
        "a <form> is a block element with a UA default margin, inside a row with only "
        "padding: 3px 4px (cf. .tree__inline, which sets margin:0 for the same reason)"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_builder_styles.py -v
```

Expected: the two new tests FAIL; `test_tree_title_truncates_with_ellipsis` still passes against the old button rule.

- [ ] **Step 3: Replace the rule**

In `courses/static/courses/css/builder.css`, replace line 38:

```css
.tree__title { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: none; border: none; cursor: pointer; text-align: left; color: var(--text-primary); padding: 0; }
```

with:

```css
/* The title is an <input> (inline rename). Two hazards, both handled here:
   1. app.css:136 styles input[type=text] at specificity (0,1,1) -- the same as
      input.tree__title -- so this only wins because builder.css loads after app.css
      via {% block extra_css %}. Every inherited property is therefore reset explicitly.
   2. An <input> does not inherit font-family/font-size, hence font: inherit.
   Hover/focus are layout-neutral: a transparent rest border becomes coloured on hover
   (a border appearing from nothing would shift text and grow the row), and focus uses
   outline, which does not participate in layout. */
.tree__rename { flex: 1; min-width: 0; display: flex; margin: 0; }
input.tree__title { width: 100%; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  text-align: left; color: var(--text-primary); font: inherit; background: none;
  border: 1px solid transparent; border-radius: 0; padding: 0; cursor: text; }
input.tree__title:hover { border-color: var(--border-default); }
input.tree__title:focus { outline: 2px solid var(--primary); outline-offset: 1px; border-color: transparent; }
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_builder_styles.py -v
```

Expected: all PASS.

- [ ] **Step 5: Falsify**

Remove `font: inherit` — `test_tree_title_input_neutralises_the_global_form_control_rule` must go RED. Change `border: 1px solid transparent` to `border: 0` — the same test must go RED. Restore both.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/css/builder.css tests/test_builder_styles.py
git commit -m "style(builder): make the tree title input read as plain text

Neutralises app.css's global input[type=text] rule (equal specificity, won on
source order) and restores font: inherit, which an <input> does not get for
free. Hover/focus are layout-neutral so rows don't twitch under the pointer."
```

---

### Task 5: Selection moves from click to focusin

**Files:**
- Modify: `courses/static/courses/js/builder.js` (delete `refreshPanel` ~117-132 and its call site ~171-174; remove the `[data-select]` branch ~190-200; add the focusin machinery)
- Test: `tests/test_builder_js_invariants.py` (must stay green)

**Interfaces:**
- Consumes: `input.tree__title[data-panel-url]` from Task 3; `setPanel`, `clearMoving` (existing).
- Produces: module-level `loadPanel(url)`, and the `focusin` listener that Task 6's handlers sit alongside.

**Why:** the current click handler calls `e.preventDefault()` on `[data-select]`, which on a text input suppresses caret placement. The branch is therefore removed entirely rather than merely losing its `preventDefault` — leaving it would double-fetch the panel on every pointer selection (once from `click`, once from `focusin`) and defeat the debounce.

`refreshPanel` becomes unreachable: it is called only from the `inPanel` branch, and once the panel's rename form is gone the only remaining panel form with `data-op` is the Move picker (`data-op="reparent"`), which takes the `setPanel(neutralPanel)` branch.

- [ ] **Step 1: Delete `refreshPanel` and its call site**

Remove the whole block at `builder.js` lines ~117-132 (the 6-line comment starting "The detail panel holds token-bearing forms" through the end of `function refreshPanel(form) { … }`).

Then in the submit handler, replace:

```js
          if (inPanel) {
            if (form.getAttribute("data-op") === "reparent") setPanel(neutralPanel);
            else refreshPanel(form);
          }
```

with:

```js
          // Only the Move picker remains as a panel form with data-op; it resets the
          // panel to neutral. (The panel's rename form is gone, so refreshPanel -- which
          // existed solely to re-token it -- was deleted along with it.)
          if (inPanel) setPanel(neutralPanel);
```

- [ ] **Step 2: Remove the `[data-select]` click branch**

In the click listener (~line 190), delete this block entirely:

```js
    var sel = e.target.closest("[data-select]");
    if (sel) {
      e.preventDefault();
      clearMoving();
      fetch(sel.getAttribute("data-panel-url"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) { setPanel(html); })
        .catch(function () { setPanel('<div class="op-error" role="alert">Network error — please reload.</div>'); });
      return;
    }
```

leaving the listener with only the `[data-move]` branch.

- [ ] **Step 3: Add the focusin selection machinery**

Insert immediately before the `// --- WS2 drag-and-drop ---` comment:

```js
  // ---- Inline rename: selection ------------------------------------------------
  // Selection moved from click to focusin: preventDefault() on a click into a text
  // input suppresses caret placement, so the click branch was removed outright.
  var panelReq = 0;        // last-request-wins id, allocated when a fetch is ISSUED
  var panelTimer = null;   // pending keyboard-debounce timer
  var pointerFocus = false;

  root.addEventListener("pointerdown", function () { pointerFocus = true; });
  root.addEventListener("pointerup", function () { pointerFocus = false; });
  root.addEventListener("pointercancel", function () { pointerFocus = false; });

  function loadPanel(url) {
    var id = ++panelReq;
    fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.text(); })
      .then(function (html) { if (id === panelReq) setPanel(html); })
      .catch(function () {
        // The id check gates this branch too: an ungated slow FAILURE from an earlier
        // row would otherwise replace a later row's loaded panel with an error box.
        if (id === panelReq) {
          setPanel('<div class="op-error" role="alert">Network error — please reload.</div>');
        }
      });
  }

  root.addEventListener("focusin", function (e) {
    // Mark consumption and timer clearing run for EVERY focusin, whatever the target,
    // BEFORE the .tree__title test. Tab goes title -> ~6 cluster controls -> next
    // title, and those stops can span more than 150ms; if only titles cleared the
    // timer, row A's fetch would fire while the author was still inside A's cluster.
    var byPointer = pointerFocus;
    pointerFocus = false;
    if (panelTimer) { clearTimeout(panelTimer); panelTimer = null; }
    var t = e.target.closest(".tree__title");
    if (!t) return;
    var url = t.getAttribute("data-panel-url");
    if (!url) return;
    clearMoving();
    // A deliberate click must not gain 150ms of latency; only keyboard traversal is
    // debounced, so tabbing across ten rows issues one fetch rather than ten.
    if (byPointer) loadPanel(url);
    else panelTimer = setTimeout(function () { panelTimer = null; loadPanel(url); }, 150);
  });
```

- [ ] **Step 4: Verify the JS invariant test still passes**

```bash
uv run pytest tests/test_builder_js_invariants.py -v
```

Expected: PASS — exactly one `panel.innerHTML =` assignment, inside `setPanel`. `loadPanel` routes both branches through `setPanel`; if you inlined either write this goes RED.

- [ ] **Step 5: Confirm `data-select` and `refreshPanel` are gone**

```bash
grep -rn "data-select\|refreshPanel" courses/ templates/ tests/
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/builder.js
git commit -m "refactor(builder): select on focusin, drop refreshPanel

preventDefault() on a click into a text input kills caret placement, so the
[data-select] click branch is removed rather than softened. Pointer focus
fetches immediately; keyboard focus is debounced 150ms with last-request-wins
on both the success and failure branches. refreshPanel is unreachable once the
panel's rename form is gone."
```

---

### Task 6: The commit path

**Files:**
- Modify: `courses/static/courses/js/builder.js` (append to the inline-rename block from Task 5)

**Interfaces:**
- Consumes: `loadPanel`/`panelTimer` context from Task 5; the form markup from Task 3.
- Produces: `revert(input)` and `commitRename(input)`, used by Task 7's response branch.

**The ordering is load-bearing.** Commit order is: cancel default → dirty check → trim write-back → `reportValidity()` → set `dataset.submitting` → set `readOnly` → `requestSubmit()`.

- `requestSubmit()`, never `submit()` — `submit()` does not fire the `submit` event, so the interceptor never runs and the browser does a full-page POST.
- Enter's `preventDefault()` is **unconditional**, before any check: a text input in a form with a submit button performs native implicit submission, so cancelling only on the commit path would make Enter on an *unchanged* title post anyway.
- Trim is written **back into the input**, because the interceptor builds `new FormData(form)` which reads the live value — trimming into a local would leave the untrimmed string in the POST body.
- `readOnly` is set **after** `reportValidity()`: a readonly input is barred from constraint validation, so setting it earlier would silently skip `required`.

- [ ] **Step 1: Add the commit machinery**

Append to the inline-rename block:

```js
  // ---- Inline rename: commit ---------------------------------------------------
  function titleForm(input) { return input.closest("form.tree__rename"); }

  // Programmatic value assignment fires NO input event, so the tooltip must be synced
  // by hand here or it keeps showing abandoned text -- exactly on the truncated long
  // titles where the tooltip is the only way to read the name.
  function revert(input) {
    input.value = input.defaultValue;
    input.title = input.value;
  }

  function commitRename(input) {
    var form = titleForm(input);
    if (!form || form.dataset.submitting) return;
    var trimmed = input.value.trim();
    // Compare trimmed against trimmed: a legacy row whose stored title has stray
    // whitespace would otherwise post a rename on a bare focus-and-blur.
    if (trimmed === input.defaultValue.trim()) return;
    input.value = trimmed;           // FormData reads the LIVE value
    input.title = input.value;
    if (!form.reportValidity()) return;   // native bubble; no state set, so no wedge
    form.dataset.submitting = "1";
    input.readOnly = true;           // AFTER validity: readonly is barred from it
    form.requestSubmit();
  }

  root.addEventListener("keydown", function (e) {
    var input = e.target.closest("input.tree__title");
    if (!input) return;
    if (e.key === "Enter") {
      // Unconditional, before any check: a text input in a form with a submit button
      // implicitly submits on Enter, which would post even an unchanged title and
      // would double-post alongside requestSubmit().
      e.preventDefault();
      if (titleForm(input).dataset.submitting) return;
      commitRename(input);
    } else if (e.key === "Escape") {
      e.preventDefault();
      if (titleForm(input).dataset.submitting) return;
      // Revert WITHOUT blurring: dropping focus to <body> would force someone who
      // abandoned an edit 300 rows down to Tab from the top of the document again.
      revert(input);
    }
  });

  root.addEventListener("focusout", function (e) {
    var input = e.target.closest("input.tree__title");
    if (!input) return;
    var form = titleForm(input);
    if (!form) return;
    // 1. A commit is already in flight. Nothing is lost -- readOnly means the field
    //    cannot have changed since the POST.
    if (form.dataset.submitting) return;
    // 2. The WINDOW lost focus, not the field. Chromium fires focusout when the tab
    //    or window is deactivated; committing here would persist half-typed text.
    if (e.relatedTarget === null && !document.hasFocus()) return;
    // 3. The form was detached by another op's applyFragment; committing would post a
    //    token that swap already superseded (cf. the add flow's isConnected guard).
    if (!form.isConnected) return;
    // 4. Emptied field = cancel. This MUST precede the dirty check inside
    //    commitRename: an emptied field IS dirty, so we would otherwise post "" and
    //    surface a 422 on an ambiguous gesture. Enter deliberately does not share
    //    this branch -- it relies on required + reportValidity's native bubble.
    if (!input.value.trim()) { revert(input); return; }
    commitRename(input);
  });

  // Keep the tooltip honest while typing. Delegated like every other handler here,
  // because applyFragment replaces whole scopes on other ops.
  root.addEventListener("input", function (e) {
    var input = e.target.closest("input.tree__title");
    if (input) input.title = input.value;
  });
```

- [ ] **Step 2: Clear the in-flight state on every completion branch**

In the submit handler, both `delete form.dataset.submitting` sites must also clear `readOnly`. The flag lives on the *form* but `readOnly` lives on a child input that only rename forms have, so the lookup must be defensive. Replace each `delete form.dataset.submitting;` with:

```js
        delete form.dataset.submitting;
        var ti = form.querySelector("input.tree__title");
        if (ti) ti.readOnly = false;
```

Note `form.querySelector(...)?.readOnly = false` is a **syntax error** — optional chaining is illegal on an assignment target.

- [ ] **Step 3: Syntax-check**

```bash
node --check courses/static/courses/js/builder.js
```

Expected: no output (exit 0).

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/js/builder.js
git commit -m "feat(builder): commit inline renames on Enter and blur

Enter's preventDefault is unconditional (native implicit submission would
double-post); the trim is written back into the input because FormData reads
the live value; readOnly is set after reportValidity, since a readonly input
is barred from constraint validation. Four blur bail-outs: in-flight, window
blur, detached form, and empty-means-cancel."
```

---

### Task 7: Applying the narrow response in place

**Files:**
- Modify: `courses/static/courses/js/builder.js` (add a `data-op === "rename"` branch to the submit handler's 200 path)

**Interfaces:**
- Consumes: the `<data data-rename-for>` contract from Task 2; `revert`/`commitRename` context from Task 6.
- Produces: nothing consumed later.

**The governing invariant: every DOM carrier of this node's `updated` must be refreshed.** A rename bumps `node.updated`, and that value is rendered into more places than the rowhead. Miss one and the author's *next* action spuriously 409s. The complete inventory, all within `li.tree__row[data-node="<pk>"]`:

| Carrier | Consumer | Miss it and… |
|---|---|---|
| `> .tree__rowhead input[name=token]` ×N (rename, reorder, + duplicate on unit rows) | those forms' POSTs | the next reorder/duplicate 409s |
| the `<li>`'s own `data-updated` | `dragstart` reads it as `node_token` | dragging the renamed row 409s |
| `> ol.tree__scope[data-scope="<pk>"]`'s `data-updated` (non-unit rows) | `builder.js:279` reads it as `dropToken` → `parent_token` | dragging *into* the renamed chapter 409s |
| that child scope's add form `input[name=parent_token]` | `add_node`'s `_check_token(parent.updated, …)` | "rename a chapter, then add a lesson under it" 409s |

- [ ] **Step 1: Add the rename branch**

In the submit handler's `if (r.status === 200 || r.status === 409)` block, branch before `applyFragment`:

```js
        if (r.status === 200 || r.status === 409) {
          if (r.status === 200 && form.getAttribute("data-op") === "rename") {
            applyRename(form, text);
          } else {
            applyFragment(text);
          }
          if (r.status === 409) notice(msg("conflict", "This changed elsewhere — reloaded to the latest."));
          if (inPanel) setPanel(neutralPanel);
          clearMoving();
        } else if (r.status === 422) {
```

A rename's **409** deliberately still goes through `applyFragment`: there the tree genuinely diverged and `_conflict_scope` must be applied, or the stale row is never reloaded.

- [ ] **Step 2: Implement `applyRename`**

Add it beside `applyFragment`:

```js
  // A rename changes no structure, so its 200 is applied IN PLACE -- no scope swap,
  // so the focused input, its caret, and document scroll are all untouched.
  function applyRename(form, html) {
    // A foreign applyFragment can land between this POST and its response, replacing
    // the row. The swapped-in markup is already server-rendered, so there is nothing
    // to patch -- and patching would be harmful: that render can PREDATE this commit,
    // so writing our committed title into its defaultValue while leaving the displayed
    // old value alone would leave the row dirty against a stale value, from which the
    // next blur would post the old title back and silently undo the rename.
    if (!form.isConnected) return;
    var tmp = document.createElement("div");
    tmp.innerHTML = html.trim();
    var data = tmp.querySelector("[data-rename-for]");
    if (!data) return;                       // unexpected body: silent no-op
    var row = form.closest("li.tree__row");
    if (!row) return;
    var token = data.getAttribute("data-updated");
    var title = data.getAttribute("value");

    var input = form.querySelector("input.tree__title");
    if (input) {
      // Assign value ONLY when it differs: the HTML value setter jumps the caret to
      // the end and drops the selection even when assigning an identical string.
      // readOnly means the field cannot have been edited in flight, so a difference
      // can only be server-side normalisation.
      if (input.value !== title) input.value = title;
      input.defaultValue = title;            // makes the field clean again
      input.title = input.value;             // after the assignment, not before
    }

    // Every carrier of this node's `updated`, scoped so descendant rows are untouched.
    var head = row.querySelector(":scope > .tree__rowhead");
    if (head) {
      head.querySelectorAll("input[name=token]").forEach(function (el) {
        el.value = token;                    // rename + reorder + duplicate (units)
      });
    }
    row.setAttribute("data-updated", token); // dragstart reads this as node_token
    var scope = row.querySelector(':scope > ol.tree__scope[data-scope="' + row.getAttribute("data-node") + '"]');
    if (scope) {
      scope.setAttribute("data-updated", token);   // drop target's parent_token
      // Pk-anchored, NOT a descendant query: _add_affordance renders its add row LAST
      // in every scope, so a nested child row's own add form precedes it in document
      // order and a plain querySelector would return a GRANDCHILD's parent_token.
      var add = root.querySelector(
        'form.tree__add[data-add-scope="' + row.getAttribute("data-node") + '"] input[name=parent_token]'
      );
      if (add) add.value = token;
    }
  }
```

- [ ] **Step 3: Syntax-check**

```bash
node --check courses/static/courses/js/builder.js
```

Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/js/builder.js
git commit -m "feat(builder): apply the rename response in place

Patches the row rather than swapping a scope: title, tooltip, defaultValue,
and every DOM carrier of the node's updated token -- the rowhead's token
inputs, the li's data-updated, and (on container rows) the child scope's
data-updated plus its add form's parent_token. The last two are why renaming
a chapter no longer breaks the next drop or add under it."
```

---

### Task 8: End-to-end coverage

**Files:**
- Create: `tests/test_e2e_inline_rename.py`
- Modify: `tests/test_e2e_builder_tree_layout.py` (seven `.tree__title` locators; the truncation assertion; one docstring)

**Interfaces:**
- Consumes: everything above.

**Run e2e in the foreground only.** Backgrounding `-m e2e` has previously spawned runaway browsers.

- [ ] **Step 1: Migrate the existing locators**

`.tree__title` appears with `has_text=` at lines 93, 107, 183, 205, 283, 297, 330 of `tests/test_e2e_builder_tree_layout.py`. An `<input>` has no text content, so each becomes a value-attribute selector:

```python
page.locator('.tree__title[value="Unit 40"]')
```

This matches the **server-rendered attribute**, so it must be read before the user types into that field.

- [ ] **Step 2: Fix the truncation assertion at lines 93-96**

It asserts `scrollWidth > clientWidth` to prove truncation. An `<input>` renders text in an inner editing host where those may not report overflow as they do for a `<button>`. Take the measurement on the **unfocused** input and falsify it (give the row a short title, require RED).

If the engine reports `scrollWidth === clientWidth` for a text control, the comparison goes **hard RED**, not vacuously green — and the short-title falsification would then pass trivially while the real case stays broken, so do not read a RED here as "the assertion works". In that case switch to comparing the input's rendered box width against the measured width of its full text (a hidden span with the same computed font), and falsify *that*.

- [ ] **Step 3: Update the stale docstring**

`test_notice_bar_is_visible_and_opaque_while_panel_scrolled` explains that the 409 path "calls `refreshPanel()`". That function is deleted; restate the rationale in terms of the `_conflict_scope` swap. The test passes either way, so nothing else would surface it.

- [ ] **Step 4: Write the new e2e suite**

Create `tests/test_e2e_inline_rename.py`, following the fixtures and markers of the existing e2e modules. Drive the **real UI** — never `page.evaluate` shortcuts, which ship broken UX green. Cover:

**Core**
- Click a **unit** title, type, press Enter → the tree label updates *and* the DB value changes.
- Same for a **chapter**, proving the interaction is kind-agnostic.
- **Focus and caret survive an Enter commit:** place the caret **mid-string** before Enter, then assert the input is still focused *and* `selectionStart` is unchanged. Asserting focus alone would pass even if the response reassigned `value` (which jumps the caret to the end even for an identical string). This is the observable proof that no scope swap happened.
- **Blur commits:** type, then click outside the tree → saved.
- **Escape reverts and keeps focus.**
- **Tooltip tracks typing, then reverts:** type into a long title and — **before** Escape — assert `title` equals the *typed* value; then Escape and assert it equals the reverted value. Without the mid-typing assertion, omitting the `input` handler entirely still passes the Escape half. Two falsifications: delete the `input` handler (first assertion RED); drop `revert()`'s title sync (second RED).
- **Unchanged field does not post:** focus and blur without typing → **no POST to `manage_node_rename`** (a panel GET is expected and must not be counted), and no `updated` bump.
- **Enter on an unchanged title issues no POST**; **plain Enter posts exactly once**; **Enter-then-blur posts exactly once**.

**In-flight**
- **Read-only during the round trip:** with the response delayed via route interception, press Enter, then attempt to type, assert the value is unchanged, then let the response land and assert the field is editable again. **Use `page.keyboard.type()` after focusing — not `fill()` or the locator's `type()`/`pressSequentially()`.** Those run an *editable* actionability check, so against a `readOnly` input they hang and throw a timeout instead of typing-and-asserting-unchanged — and they *succeed* once the `readOnly` assignment is removed, inverting RED and GREEN. `page.keyboard.type()` performs no editability check and silently no-ops. Assert `readOnly` is `false` afterwards via `to_have_js_property` before re-typing.
- **Window blur does not commit:** type, blur the window (not the field) → no POST; field stays dirty. Playwright has no gesture that blurs the browser window: use a **second page in the same context plus `bring_to_front()`**, and confirm `document.hasFocus()` actually reports `False` under the run mode used — it differs between headed and headless Chromium. If it does not, skip with that reason rather than leaving the test falsely green.

**Token refresh — the reason Task 7 exists.** Every one of these must **wait for the rename POST's response** (`expect_response` on `manage_node_rename`) before firing the follow-up op. The token patch happens when the response lands, so firing "immediately" races the round trip — which the design explicitly accepts as a 409 — making the test flaky by construction and its failure indistinguishable from the bug it guards.
- Rename a **unit**, await the response, then click Duplicate on that row → succeeds, **no** conflict notice. Falsify by skipping the duplicate form's token refresh.
- Same for the reorder arrows (every row has them) and for a drag of the just-renamed row.
- **Rename a chapter, await, then drag a unit into it** → no conflict notice. Guards the child scope's `data-updated`.
- **Rename a chapter, await, then add a lesson under it** → succeeds, no conflict notice, typed child title not discarded. Guards the child scope's `parent_token`. **The fixture chapter must itself contain a nested section with its own add row**, so a naive descendant query (which would find the *grandchild's* `parent_token`) fails RED — and additionally assert the nested section's own add still works afterwards, which is what catches a mis-stamped token.
- **Rename the same row twice without reloading:** commit via Enter, wait, then type a different title and Enter again → both succeed, no conflict, DB holds the second title. This is the only test exercising the rename form's *own* refreshed token together with the `defaultValue` reset. Falsify by skipping that refresh.

**Errors**
- **422 does not wedge the row.** The row's guards make a 422 **unreachable by typing** — `required` plus the unconditional Enter-cancel block an empty title, `maxlength="200"` truncates over-length input including pasted text, and `ContentNode.clean()` validates nothing else about the title. So both 422 tests use **route interception**: fulfil the first `manage_node_rename` request with a 422 and an `_op_error.html` body, assert the notice appeared and that the typed text, focus and cleared `readOnly` all survived; then unroute so the corrected re-submit reaches the real server. Do **not** use `page.evaluate` to strip `maxlength`.

**Navigation / a11y**
- **Enter on an empty field does not wedge the row:** clear the field, press Enter (native bubble), then type a valid title and Enter → it commits. Additionally assert **zero** requests to `manage_node_rename` during the empty-Enter step: without that, the test passes even if `readOnly` is set *before* `reportValidity()`, which would skip validation entirely, POST the empty title and merely 422. Falsify by swapping the `readOnly`/`reportValidity()` order.
- **Debounce / ordering:** Tab from a row title through that row's cluster controls to the **next** row's title — the real tab order, ~6 stops per row — and assert exactly **one** panel GET, counted after focus rests. Written as "Tab N times between titles" it would not exercise the actual path. A pointer click issues its GET immediately. Falsify by scoping the timer clear to `.tree__title` focusins only.
- **Tab to a row, then click a different row within 150ms** → the panel ends up showing the clicked row.
- **Keyboard tab order:** tabbing from a row title reaches the next control, not a hidden "Rename".
- **Top-level rename preserves document scroll** in a long course.

- [ ] **Step 5: Run the e2e suite in the foreground**

```bash
uv run pytest tests/test_e2e_inline_rename.py tests/test_e2e_builder_tree_layout.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_inline_rename.py tests/test_e2e_builder_tree_layout.py
git commit -m "test(builder): e2e coverage for inline tree renaming

Drives the real gestures. The token-refresh cases await the rename response
before the follow-up op (firing immediately would race the round trip, which
the design accepts as a 409). The readonly case uses page.keyboard.type(),
since locator typing runs an editability check that inverts RED and GREEN."
```

---

### Task 9: i18n, page weight, and visual verification

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`

- [ ] **Step 1: Refresh the catalogs**

```bash
uv run python manage.py makemessages -l en -l pl
```

**No msgid is removed by this change.** `Title` and `Rename` both survive in the new `_tree_node.html` markup, so only their source-location comments change — deleting them would drop working Polish translations. If any msgid *does* fall out of use, delete it from both catalogs rather than leaving an obsolete `#~` entry, which the catalog tests reject. Watch for fuzzy flags and clear them.

- [ ] **Step 2: Run the i18n tests**

```bash
uv run pytest tests/test_i18n_ws4.py -v
```

Expected: PASS, with no `#~` entries in either catalog.

- [ ] **Step 3: Measure page weight**

The row gains a `<form>`, a `{% csrf_token %}`, two hidden inputs, a hidden submit and a second `{% url %}` reversal. Courses here reach ~800 units, so measure rather than assume: record the builder page's transferred size and DOM node count for the largest available fixture, before and after. (The CSRF token is kept rather than dropped in favour of the cookie-reading `csrf()` helper, because dropping it would break the no-JS path this design newly enables.) Record the delta for the PR body.

- [ ] **Step 4: Visual verification**

Playwright screenshots in **light and dark**: the tree at rest, on hover, and focused; plus the **selected non-unit detail panel**, now heading-only, which must not look broken or awkwardly padded. Self-critique before accepting.

- [ ] **Step 5: Screen-reader spot-check**

Covering the `button` → `textbox` role change: rows remain navigable, the "Title" name plus the announced value identifies each row, and the hidden Rename button is not reachable by Tab.

- [ ] **Step 6: Full verification**

```bash
uv run ruff check
uv run ruff format --check
uv run pytest
```

Expected: all green. Note pytest's verdict line does not survive the Bash pipe — check the exit code and grep for `FAILED`.

- [ ] **Step 7: Commit**

```bash
git add locale/
git commit -m "chore(i18n): refresh catalogs for the inline rename markup"
```

---

## Self-Review

**Spec coverage.** Backend normalization → Task 1. Narrow response → Task 2. Template/markup, panel change, partial deletion → Task 3. Styling (cascade, font, layout-neutral hover) → Task 4. JS selection/debounce/`refreshPanel` → Task 5. Commit path (Enter/blur/Escape/trim/validity/`readOnly`) → Task 6. In-place application and the four-item token inventory → Task 7. All e2e and existing-test migration → Task 8. i18n, page weight, screenshots, screen-reader → Task 9. The no-JS path is covered by a test in Task 2 and by the markup in Task 3.

**Placeholders.** None: every code step carries the actual code, every command its expected output, every test its falsification.

**Type/name consistency.** `_clean_title` (Task 1) is referenced only in Task 1. `_rename_result.html`'s `data-rename-for` / `data-updated` / `value` (Task 2) are exactly the attributes `applyRename` reads (Task 7). `revert`/`commitRename`/`titleForm` (Task 6) are used consistently. `form.tree__rename`, `input.tree__title`, `li.tree__row[data-node]`, `form.tree__add[data-add-scope]` match the markup in Task 3 and the existing templates.

**Deliberately accepted, not gaps** (do not "fix" these during implementation): the touch soft-keyboard cost; a foreign swap clobbering a half-typed title and its stale-display residual; a same-row op racing the round trip and 409-ing; the panel heading lagging until reselect; the AT role change; per-row markup growth; starting a rename discarding an open Move picker; `spellcheck` disabled; ancestor scope tokens untouched; Escape doing nothing mid-flight.
