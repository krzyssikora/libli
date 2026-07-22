# Inline Rename of Tree Node Titles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every course-builder tree row's title directly editable in place — for parts, chapters, sections **and units** — replacing the detail panel's rename form.

**Architecture:** The title `<button>` in each tree row becomes a one-field `<form data-op="rename">` wrapping a text `<input>`, riding the existing `builder.js` fetch interceptor. Crucially, a tree-row rename does **not** re-render a tree scope: `node_rename` returns a tiny `_rename_result.html` fragment and the JS patches the row in place (title, tooltip, and every DOM carrier of the node's `updated` token). Nothing is destroyed, so there is no focus loss, no restoration, and no concurrency gate. The input is `readOnly` for the duration of the round trip, which makes mid-flight edits impossible rather than recoverable.

**Tech Stack:** Django 5.2 templates + views, vanilla ES5-style JS (no build step, no framework), plain CSS with design tokens, pytest + pytest-django, Playwright for e2e.

## Expected intermediate states — the tree is briefly broken on purpose

Tasks 3-7 change markup and JS in sequence, and the builder is **not** fully functional in between.
This is expected; do not "fix" it or assume you broke something. Manual smoke-testing mid-sequence
will mislead you.

| After task | What is temporarily broken | Restored by |
|---|---|---|
| 2 (narrow response) | The **panel's** rename form still exists and still posts as a fragment, but now receives the `<data>` body, which `applyFragment` silently no-ops — so a panel rename persists in the DB while the tree label goes stale until reload. | Task 3 (deletes that form) |
| 3 (markup) | Clicking a title no longer selects a node — the click handler still calls `preventDefault()` on `[data-select]`, which the input no longer carries, so no panel loads. Renaming **does** work: the form carries `data-op="rename"`, so native implicit submission on Enter is caught by the existing interceptor (`builder.js:135`) and POSTed via fetch — but the response is the Task 2 `<data>` body, which `applyFragment` no-ops, so the row's label and token go stale until reload. Separately, `refreshPanel` (deleted only in Task 5) still looks up `[data-select]`, finds nothing, and degrades to `setPanel("")`. | Tasks 5 and 7 |
| 5 (selection) | Selection works again. Commit behaviour is **unchanged** from Task 3 — Enter still commits via implicit submission and the row still goes stale. Blur-to-save, Escape and the trim/validity rules do not exist yet. | Tasks 6 and 7 |
| 6 (commit) | Enter/blur/Escape all behave per spec, but the response is still a no-op — `applyFragment` receives a `<data>` element with no `data-scope` and does nothing, so the row's label and token remain stale until reload. | Task 7 |
| 7 (apply) | Nothing. The feature is functional end-to-end; Task 8 proves it. | — |

## Global Constraints

- Read the spec before starting: `docs/superpowers/specs/2026-07-22-inline-rename-tree-titles-design.md`. It carries the reasoning behind every non-obvious rule here.
- **Tooling:** bare `pytest` / `ruff` / `python` are **not** on PATH. Always `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`.
- **This worktree runs concurrently with others.** Export a unique `DATABASE_URL` before running tests, or you will collide with another worktree on the Postgres `test_libli` database. Use the role from the main checkout's `.env` — `libli:libli`, **not** `postgres:postgres`, which
  fails password auth here:
  `export DATABASE_URL=postgres://libli:libli@localhost:5432/libli_rename`.
  The worktree has no `.env` of its own, so the exported variable is what takes effect.
- **Test files in this repo are CRLF.** Appending with a LF heredoc will make `ruff format --check`
  flag the whole file. Either write CRLF-aware, or run `uv run ruff format <file>` afterwards and
  confirm with `git diff --stat` that only your added lines changed.
- **Falsify every test before accepting it.** Break the thing the test guards and require RED. A passing test that never fails proves nothing. Where a step names a specific falsification, perform it.
- **JS style:** `builder.js` is a single IIFE using `var`, `function`, and `Array.prototype.slice.call`. Match it. No `let`/`const`/arrow functions/optional chaining — and note `form.querySelector(...)?.readOnly = false` is a *syntax error* regardless.
- **Django template comments** must be `{% comment %}…{% endcomment %}` for anything multi-line; `{# #}` is single-line only or it renders visibly.
- **i18n:** any module-level translatable string uses `gettext_lazy`. Do not leave obsolete `#~` entries in `.po` files — the catalog tests reject them.
- **`ContentNodeFactory` defaults `unit_type="lesson"` and creates via `objects.create()` (no
  `full_clean`).** Any **non-unit** node built with it must pass `unit_type=None`, or it persists in
  a state `ContentNode.clean()` rejects ("Only units may have a unit_type.", `models.py:246`) and the
  next `rename_node` returns **422** instead of 200 — silently turning several tests below into
  permanent failures and one into a vacuous pass. The repo documents this trap at
  `tests/test_e2e_transfer.py:128-133` and works around it at `tests/test_e2e_builder_ws2.py:54-56`.
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
    node = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Old"
    )
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
    node = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Old"
    )
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
    node = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Old"
    )
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
uv run pytest tests/test_manage_node_ops.py -k "test_rename_strips_surrounding_whitespace or test_rename_rejects_whitespace_only_title or test_add_strips_surrounding_whitespace or test_strip_happens_before_length_validation" -v
```

Expected: all four FAIL — `test_rename_strips_surrounding_whitespace` (title is `"  Fractions  "`), `test_rename_rejects_whitespace_only_title` (returns 200 and persists `"   "`; note this one is only a *meaningful* RED because the node is built with `unit_type=None` — a factory-default non-unit would 422 for an unrelated reason and the test would pass vacuously both before and after), `test_add_strips_surrounding_whitespace`, `test_strip_happens_before_length_validation`. The names are given in full rather than as a loose `-k "strip or ..."`, which would also select pre-existing green tests and muddy the expected-failure list. Step 1 adds a **fifth** test, `test_type_only_toggle_still_preserves_title` — it is an already-green guard on the `_UNSET` branch, deliberately excluded from this filter, and must pass both before and after.

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
    node = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Old"
    )
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
    node = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Old"
    )
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": node.pk, "token": _tok(node), "title": 'A "quoted" & <b>bold</b>'},
        **FETCH,
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    # Assert the EXACT escaped attribute. A loose `"&amp;" in body` disjunct would be
    # trivially true (Django always escapes the literal &), and would pass even if the
    # value attribute were emitted with raw double quotes -- which would break the
    # <data> tag outright.
    assert (
        'value="A &quot;quoted&quot; &amp; &lt;b&gt;bold&lt;/b&gt;"' in body
    )


@pytest.mark.django_db
def test_no_js_rename_still_redirects_to_the_builder(client):
    _, course = _setup(client)
    node = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Old"
    )
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

Falsification for the escaping test: render the title with `|safe` in `_rename_result.html` and require RED.

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
- Modify: `courses/static/courses/css/builder.css` (delete lines 99-100, the dead `.form--inline` panel rules)
- Modify: `tests/test_tree_badge.py` (line 23 regex)
- Modify: `tests/test_e2e_builder.py`, `tests/test_e2e_builder_authoring.py`, `tests/test_e2e_builder_reorder.py`, `tests/test_e2e_builder_ws2.py`, `tests/test_e2e_transfer.py` (15 text-engine matches — see Step 5b)
- Test: `tests/test_manage_builder.py`

**Interfaces:**
- Consumes: the `courses:manage_node_rename` URL (unchanged).
- Produces: the DOM contract Tasks 5-7 depend on — `form.tree__rename[data-op="rename"]` containing hidden `node` + `token` and `input.tree__title[data-panel-url]`, inside `li.tree__row[data-node][data-updated] > .tree__rowhead`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_manage_builder.py` (match the existing imports/fixtures in that file; it already logs in an owner and requests the builder page):

Add `import re` to the **existing import block at the top** of `tests/test_manage_builder.py`
as the **first line, followed by a blank line, above `import pytest`** -- `re` is stdlib and needs its own import group; putting it beside the third-party `import pytest` produces the very `I001` this is meant to avoid (ruff runs isort with `force-single-line`) — appending it with
the rest of this block would trip `ruff`'s `E402`/`I001` at Task 9, six tasks later, on a file you
have stopped thinking about. Append only the constant, helper and tests.

**Assertions must be scoped to the rename form.** Every tree row *already* emits a byte-identical
`<input type="hidden" name="node" value="…">` and `<input type="hidden" name="token" value="…">` from
`_move_buttons.html:5-6`, and `_add_affordance.html:15` already emits `required`. Asserting those
against the whole page would pass even if the rename form shipped with no hidden fields at all — a
vacuous test. So extract the form block first and assert inside it, attribute by attribute (which also
avoids coupling to attribute order).

```python
RENAME_FORM_RE = re.compile(
    r'<form class="tree__rename".*?</form>', re.DOTALL
)


def _rename_form(html):
    m = RENAME_FORM_RE.search(html)
    assert m, "no .tree__rename form found in the builder page"
    return m.group(0)


@pytest.mark.django_db
# unit_type MUST be None for non-units: ContentNodeFactory defaults it to "lesson"
# and creates via objects.create() (no full_clean), so a kind="part" row would persist
# with a unit_type and then 422 on rename -- ContentNode.clean() raises "Only units may
# have a unit_type." (models.py:246). The repo documents this trap at
# tests/test_e2e_transfer.py:128-133.
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
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    assert resp.status_code == 200
    form = _rename_form(resp.content.decode())
    assert 'data-op="rename"' in form
    assert f'name="node" value="{node.pk}"' in form
    assert f'name="token" value="{node.updated.isoformat()}"' in form
    assert 'class="tree__title"' in form
    assert 'name="title"' in form
    assert 'value="Fractions"' in form
    assert "required" in form
    assert 'maxlength="200"' in form
    assert 'autocomplete="off"' in form
    assert 'spellcheck="false"' in form
    # data-select had exactly two readers (the click branch and refreshPanel); both are
    # removed by this change, so it must not be carried on ~800 rows for nothing.
    assert "data-select" not in resp.content.decode()


@pytest.mark.django_db
def test_tree_title_has_a_static_accessible_name_and_a_title_tooltip(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Fractions"
    )
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    assert resp.status_code == 200
    form = _rename_form(resp.content.decode())
    assert 'aria-label="Title"' in form
    assert 'title="Fractions"' in form


@pytest.mark.django_db
def test_hidden_rename_submit_is_out_of_the_tab_order(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Fractions"
    )
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    assert resp.status_code == 200
    form = _rename_form(resp.content.decode())
    # .visually-hidden uses the clip pattern, which keeps the element FOCUSABLE --
    # without tabindex="-1" every row would gain a second tab stop. Asserted per
    # attribute so a harmless reorder doesn't fail a test that is about tab order.
    btn = re.search(r"<button[^>]*>", form)
    assert btn, "the rename form must contain a submit button"
    assert 'class="visually-hidden"' in btn.group(0)
    assert 'type="submit"' in btn.group(0)
    assert 'tabindex="-1"' in btn.group(0)


@pytest.mark.django_db
def test_node_panel_no_longer_offers_a_rename_form(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    node = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="P"
    )
    resp = client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "c1", "pk": node.pk}),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert 'data-op="rename"' not in resp.content.decode()


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

Expected: **8 failures** — `test_every_tree_row_title_is_an_editable_form` is parametrized ×4, plus the accessible-name, tab-order, panel and partial-deleted tests. Check the count, so a partial collection is detectable. Note `test_rename_form_partial_is_deleted` is RED for a different reason from the rest (the file still exists) and is not a `django_db` test.

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

Note `{% csrf_token %}` renders as an **empty string plus a warning** under
`render_to_string` without a request — which is how `tests/test_tree_badge.py::_render_unit` renders
this partial. That is pre-existing (the unit row's duplicate form already contains one), it does not
raise, and no assertion in this plan depends on it. Do not "fix" the warning.

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

Delete its **CSS** in the same commit, or the dead-code removal is only half done:
`builder.css:99-100` (`.builder__panel .form--inline { … }` and
`.builder__panel .form--inline > label { … }`) exist solely to style that panel form —
`form--inline` occurs nowhere else in `templates/` or `courses/`.

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

Rename the surrounding identifiers in the same edit, or the file is left describing markup that no
longer exists: the constant `TITLE_BTN_RE` → `TITLE_INPUT_RE`, the test
`test_title_button_has_hover_title` (~line 74) → `test_title_input_has_hover_title`, and its assertion
message `"title button title attr not found"` → `"title input title attr not found"`.

- [ ] **Step 5b: Migrate the `text=` waits in four other builder e2e modules**

This is the change most likely to ship broken, because nothing in the default test run would catch
it. Playwright's `text=` engine matches an `<input>` by its value **only** for `type=button` and
`type=submit` — a `type=text` input is never matched. So every
`page.wait_for_selector("text=<node title>")` that waits for a tree row silently stops matching the
moment this task lands, and those tests fail on a timeout that looks like a product bug. The same
applies to `get_by_text`, which is the *same* text engine — so search for **both** forms. There are
15, in five modules the plan does not otherwise touch:

| File | Lines | Form |
|---|---|---|
| `tests/test_e2e_builder.py` | 75, 83, 119, 187 | `wait_for_selector("text=…")` |
| `tests/test_e2e_builder_authoring.py` | 70, 85, 121, 132, 188, 198 | `wait_for_selector("text=…")` |
| `tests/test_e2e_builder_reorder.py` | 103 | `wait_for_selector("text=…")` |
| `tests/test_e2e_builder_ws2.py` | 66, 135, 245 | `wait_for_selector("text=…")` |
| `tests/test_e2e_transfer.py` | 177 | `part_scope.get_by_text("Root Chapter").count() == 1` → `part_scope.locator('.tree__title[value="Root Chapter"]').count() == 1` |

`test_e2e_transfer.py:177` is scoped to `[data-scope="{part.pk}"]`, i.e. a tree scope, so it *is* a
row title. Its line 92 `wait_for_selector(f"text={course.title}")` is on the **import preview** page,
not the tree — leave that one alone. Likewise `test_e2e_builder_tree_layout.py:188/233` scope
`get_by_text` to `.builder__panel`, which is panel copy, not a row title.

Rewrite each as a value-attribute wait against the tree title, e.g.

```python
page.wait_for_selector("text=Foundations")
# becomes
page.wait_for_selector('.tree__title[value="Foundations"]')
```

Check each one in context first: a few may be waiting for text that is **not** a tree row title (a
notice, a panel heading), in which case leave them alone. Only the tree-row waits change.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/test_manage_builder.py tests/test_tree_badge.py -v
uv run pytest -m e2e tests/test_e2e_builder.py tests/test_e2e_builder_authoring.py tests/test_e2e_builder_reorder.py tests/test_e2e_builder_ws2.py tests/test_e2e_transfer.py -v
```

The e2e run proves Step 5b's migration: without it those modules break **here**, and Task 6 would
later run two of them and mispredict PASS, sending you to debug the wrong change.

Expected: all PASS.

- [ ] **Step 7: Falsify**

Wrap the new form in `{% if node.kind != "unit" %}`. The `unit` parametrization of `test_every_tree_row_title_is_an_editable_form` must go RED — that is the exact regression this feature exists to prevent. Remove the guard.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/manage/_tree_node.html templates/courses/manage/_node_panel.html courses/static/courses/css/builder.css tests/test_manage_builder.py tests/test_tree_badge.py tests/test_e2e_builder.py tests/test_e2e_builder_authoring.py tests/test_e2e_builder_reorder.py tests/test_e2e_builder_ws2.py tests/test_e2e_transfer.py
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

**Leave `test_tree_title_truncates_with_ellipsis` unchanged** -- its `\.tree__title\s*\{` regex still matches inside `input.tree__title { ... }`, so there is nothing to edit there. Append only the two new tests to `tests/test_builder_styles.py`:

```python
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
        "defensive reset matching .tree__inline (builder.css:44) so the form never "
        "contributes vertical space in a row with only padding: 3px 4px"
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
- Modify: `courses/static/courses/js/builder.js` (delete `refreshPanel` -- comment 117-122, body 123-132 -- and its call site 171-174; remove the `[data-select]` branch 191-200; add the focusin machinery)
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

  // pointerdown is scoped to the tree; the RELEASE listeners are on document, because a
  // pointerup landing outside .builder (drag-select out of the pane, release over
  // browser chrome, an HTML5 drag started from .ica--grip) would otherwise latch
  // pointerFocus true -- and the next KEYBOARD Tab would then fetch immediately,
  // silently defeating the debounce.
  root.addEventListener("pointerdown", function () { pointerFocus = true; });
  document.addEventListener("pointerup", function () { pointerFocus = false; });
  document.addEventListener("pointercancel", function () { pointerFocus = false; });

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

  // Focus leaving the builder entirely fires no further focusin on root, so a pending
  // timer would still elapse and swap the panel for a row the author has left.
  root.addEventListener("focusout", function (e) {
    if (panelTimer && (!e.relatedTarget || !root.contains(e.relatedTarget))) {
      clearTimeout(panelTimer);
      panelTimer = null;
    }
  });
```

Also reset the latch in the existing `dragend` handler, since an HTML5 drag consumes the pointerup:

```js
  root.addEventListener("dragend", function () { clearDropMarks(); drag = null; pointerFocus = false; });
```

- [ ] **Step 4: Verify the JS invariant test still passes**

```bash
uv run pytest tests/test_builder_js_invariants.py -v
```

Expected: PASS — exactly one `panel.innerHTML =` assignment, inside `setPanel`. `loadPanel` routes both branches through `setPanel`; if you inlined either write this goes RED.

- [ ] **Step 5: Confirm `data-select` and `refreshPanel` are gone from the source**

```bash
grep -rn "data-select\|refreshPanel" courses/ templates/
```

Expected: **no output.** The grep deliberately excludes `tests/`, where two legitimate references
remain: the `assert "data-select" not in ...` guard added in Task 3, and the `refreshPanel` mentions
in `tests/test_e2e_builder_tree_layout.py` (both of which Task 8, Step 3 rewrites — check for **two**
occurrences there, not one).

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
    // Write the trim back -- FormData reads the LIVE value, so trimming into a local
    // would leave the untrimmed string in the POST body. GUARDED, because the HTML
    // value setter jumps the caret to the end and drops the selection even when
    // assigning an identical string; an unconditional write here would destroy the
    // mid-string caret before the POST is even issued, and Task 8 asserts it survives.
    if (input.value !== trimmed) input.value = trimmed;
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
    // 3. Another op's applyFragment is destroying, or has destroyed, this row; committing
    //    would post a token that swap already superseded. `swapping` carries this, NOT
    //    isConnected: Chromium delivers the focusout from inside replaceWith(), while the
    //    doomed subtree still reports isConnected true. isConnected stays for the async case.
    if (swapping || !form.isConnected) return;
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

Bail-out 3 needs a `swapping` flag that `applyFragment` owns — declare `var swapping = false;`
beside it and wrap the swap:

```js
    if (existing) {
      swapping = true;
      try { existing.replaceWith(incoming); } finally { swapping = false; }
    }
```

- [ ] **Step 2: Clear the in-flight state on every completion branch**

`builder.js` contains **three** `delete form.dataset.submitting` occurrences. Only the two inside the
submit handler are in scope: the `.then` tail (line 181) and the `.catch` (line 185). **Do not touch
the third**, inside `closeAdd()` (~line 328) for the inline-add flow — it has no `.tree__title` child,
so the lookup would be dead code there.

The flag lives on the *form* but `readOnly` lives on a child input that only rename forms have, so the
lookup must be defensive. In those two places only, replace `delete form.dataset.submitting;` with:

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

- [ ] **Step 4: Prove the shared-tail edit did not regress the other builder ops**

Step 2 edits the `.then`/`.catch` tails of the interceptor that **every** `data-op` form uses — add,
reorder, duplicate, reparent. A parse check proves nothing about them:

```bash
uv run pytest tests/test_manage_node_ops.py tests/test_builder_js_invariants.py -v
uv run pytest -m e2e tests/test_e2e_builder_ws2.py tests/test_e2e_builder_reorder.py -v
```

Expected: all PASS. Run the e2e set in the **foreground**.

- [ ] **Step 5: Falsify the ordering**

Move `input.readOnly = true` **above** `form.reportValidity()` in `commitRename`. A readonly input is
barred from constraint validation, so `required` stops firing: Task 7's smoke test still passes, but
the empty-Enter case would POST an empty title. Confirm you can observe that (an empty title reaching
the server), then restore the order. This is the one ordering in Task 6 with no other guard.

- [ ] **Step 6: Commit**

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

**This is the one path where the in-place invariant is deliberately broken, and it has a real cost:**
`_conflict_scope` (`views_manage.py:519`) re-renders the whole parent scope, so the `<li>` the author
is typing in is replaced — focus drops to `<body>` and the typed title is discarded, with only the
generic conflict notice as feedback. That is correct (the server's state won and the tree must be
reloaded to truth) and is **accepted**, but it is a genuine loss and is listed as such in the
Self-Review. Task 8 covers it.

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

- [ ] **Step 4: Smoke-test end to end, in a real browser**

`node --check` only proves the file parses, and `test_builder_js_invariants.py` only counts
`panel.innerHTML` assignments — so Tasks 5-7 have shipped three commits of behaviour change with no
executable proof. Pull one minimal e2e forward from Task 8 and get it green before committing;
everything after this point is elaboration on a path already known to work.

Create `tests/test_e2e_inline_rename.py` with the module skeleton given in Task 8, Step 4, plus this
single test:

```python
@pytest.mark.django_db(transaction=True)
def test_enter_commits_a_unit_rename(page, live_server):
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    title = page.locator('.tree__title[value="Unit 1"]')
    title.click()
    title.press("Control+a")
    page.keyboard.type("Renamed unit")
    with page.expect_response(
        lambda r: "rename" in r.url and r.request.method == "POST"
    ):
        title.press("Enter")
    expect(page.locator('.tree__title[value="Renamed unit"]')).to_have_count(1)
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Renamed unit"
```

Run it in the **foreground**, and note the `-m e2e` — `pyproject.toml:48` sets
`addopts = "-q -m 'not e2e'"`, so without it every test in this module is **deselected** and pytest
reports success having run nothing:

```bash
uv run pytest -m e2e tests/test_e2e_inline_rename.py -v
```

Expected: **1 passed** — check the collected count, not just the exit status, so "0 selected" cannot
be misread as green. If it fails, the bug is in Tasks 5-7, not in the test.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/builder.js tests/test_e2e_inline_rename.py
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
- Modify: `tests/test_e2e_builder_tree_layout.py` (seven `.tree__title` locators; the truncation assertion; two `refreshPanel` docstring mentions)

**Interfaces:**
- Consumes: everything above.

**Run e2e in the foreground only.** Backgrounding `-m e2e` has previously spawned runaway browsers.

- [ ] **Step 1: Migrate the existing locators**

`.tree__title` appears with `has_text=` at seven places in `tests/test_e2e_builder_tree_layout.py`. An
`<input>` has no text content, so each becomes a value-attribute selector — but **`has_text` is a
substring match and `[value="…"]` is exact**, so they are not interchangeable. Per line:

All seven call sites currently end in `.first`. Whether to keep it differs per line, so the full
replacement expression is given — dropping `.first` where more than one element matches raises a
Playwright strict-mode violation.

**Six of the seven sites end in `.first.click()`, not just `.first`** — line 93 is the only bare
assignment. The full replacement **including the trailing call** is given per line; dropping the
`.click()` would turn six clicks into no-op expression statements and the following
`wait_for_selector` waits would time out looking like product bugs.

| Line | Current | Full replacement | Why |
|---|---|---|---|
| 93 | `title = page.locator(".tree__title", has_text="deliberately very long").first` | `title = page.locator('.tree__title[value*="deliberately very long"]').first` | `LONG_TITLE` (line 17) is `"A deliberately very long unit title that must truncate " * 3`, so an **exact** selector matches nothing and the test dies on a timeout that looks like a product bug. **Keep `.first`** — `*=` is a substring match and may hit several rows. Assignment only, no `.click()`. |
| 107 | `page.locator(".tree__title", has_text="deliberately very long").first.click()` | `page.locator('.tree__title[value*="deliberately very long"]').first.click()` | Same selector reasoning; **keeps both `.first` and `.click()`**. |
| 183 | `page.locator(".tree__title", has_text="Unit 40").first.click()` | `page.locator('.tree__title[value="Unit 40"]').click()` | Exact and unique. **Drop `.first`, keep `.click()`.** |
| 205, 283, 330 | `page.locator(".tree__title", has_text="Unit 1").first.click()` | `page.locator('.tree__title[value="Unit 1"]').click()` | Exact is **stricter** than the original, which also matched `Unit 10`, `Unit 12`, … and leaned on `.first`. **Drop `.first`, keep `.click()`.** If a test then finds zero elements, check the seeded titles rather than reverting to `*=`. |
| 297 | `page.locator(".tree__title", has_text="Unit 2").first.click()` | `page.locator('.tree__title[value="Unit 2"]').click()` | Same as above. **Drop `.first`, keep `.click()`.** |
| 358-360 | `page.locator(".builder__tree form[data-op] button[type='submit']:not([disabled])").first.click()` | `page.locator(".builder__tree form[data-op=\"reorder\"] button[type='submit']:not([disabled])").first.click()` | **Not a `.tree__title` locator, but broken by this change all the same.** Every row now contains `form.tree__rename[data-op="rename"]` with a non-disabled submit, and that form precedes `.tree__cluster` in document order — so `.first` would select the rename form's `.visually-hidden` button. It is `position:absolute` and fully clipped, so Playwright sees a non-empty box but the hit-target check never resolves and `.click()` hangs for the full timeout. Narrowing to `data-op="reorder"` also keeps the surrounding comment's "first-row up arrow is disabled" rationale true. |

On the attribute vs. property distinction: typing mutates only the `value` **IDL property**, never the
content attribute, so these locators are stable while the author types. What *does* update the
attribute is `input.defaultValue = title` in `applyRename` (Task 7), which reflects to it. So an
attribute selector tracks the server-rendered title and must be re-derived **after a committed
rename**, not after typing.

- [ ] **Step 2: Fix the truncation assertion at lines 93-96**

It asserts `scrollWidth > clientWidth` to prove truncation. An `<input>` renders text in an inner editing host where those may not report overflow as they do for a `<button>`. Take the measurement on the **unfocused** input and falsify it (give the row a short title, require RED).

If the engine reports `scrollWidth === clientWidth` for a text control, the comparison goes **hard RED**, not vacuously green — and the short-title falsification would then pass trivially while the real case stays broken, so do not read a RED here as "the assertion works". In that case switch to comparing the input's rendered box width against the measured width of its full text (a hidden span with the same computed font), and falsify *that*.

- [ ] **Step 3: Update the stale docstring**

`test_notice_bar_is_visible_and_opaque_while_panel_scrolled` explains that the 409 path "calls `refreshPanel()`". That function is deleted; restate the rationale in terms of the `_conflict_scope` swap. There are **two** `refreshPanel` mentions in that file — fix both. The test passes either way, so nothing else would surface them.

- [ ] **Step 4: Write the new e2e suite**

`tests/test_e2e_inline_rename.py` was created in Task 7, Step 4 with the skeleton below and one test.
Fill in the rest here. Drive the **real UI** — never `page.evaluate` shortcuts, which ship broken UX
green.

**Module skeleton** (mirror the conventions in `tests/test_e2e_builder_ws2.py`; check that file for the
exact fixture names and marker in use and match them rather than inventing new ones):

This skeleton is copied from `tests/test_e2e_builder_ws2.py:1-41` rather than invented — the login is
allauth's (there is no `#id_username`), the actor needs verification **and** the `PLATFORM_ADMIN`
group (a bare `UserFactory` is not authorized for the manage surface, and its password is
`"password123"`, not `TEST_PASSWORD`), and the builder route is `/build/`, not `/builder/`.

```python
"""Playwright e2e for inline renaming of builder tree node titles.

Marked e2e (excluded from the default run; run with -m e2e).
"""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    u = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    u.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return u


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_course(username="owner"):
    """A course shaped for the token-refresh cases: a chapter that CONTAINS a nested
    section with its own add row, so a naive descendant query for parent_token finds
    the GRANDCHILD's and the test goes RED.

    Every non-unit node passes unit_type=None -- the factory defaults it to "lesson",
    which ContentNode.clean() rejects for non-units, so a chapter built without it
    422s on rename and the chapter-centric scenarios below fail looking like
    applyRename bugs. Keep this in mind if you add the optional n_units parameter.
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = _make_pa_user(username)
    course = CourseFactory(slug="c1", owner=owner)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Chapter 1"
    )
    section = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=chapter, title="Section 1"
    )
    unit1 = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=section, title="Unit 1"
    )
    unit2 = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=section, title="Unit 2"
    )
    return course, {
        "owner": owner, "chapter": chapter, "section": section,
        "unit1": unit1, "unit2": unit2,
    }


def _open_builder(page, live_server, course, username):
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")
    page.wait_for_selector(".tree__title")
```

**Every test in the module must be decorated `@pytest.mark.django_db(transaction=True)`** — including
the Task 7 smoke test. Without the marker the test errors on DB access; without `transaction=True` the
factory-seeded course is invisible to the live server and `refresh_from_db()` cannot observe the
server's write.

Never hard-code a password literal — use `tests.factories.TEST_PASSWORD`, or GitGuardian flags it.

**Four tests use Playwright APIs the rest of the plan never exercises, so they are written out in
full.** The remaining scenarios are ordinary click/type/assert and can be written by analogy with the
Task 7 smoke test. **Every scenario marked (F) must carry an explicit falsification** — break the
named thing, require RED, restore.

**Canonical URLs** (from `courses/urls.py:155-183`) — every glob and predicate below uses these, so
they cannot drift:

| Purpose | Path | Notes |
|---|---|---|
| Builder page | `/manage/courses/<slug>/build/` | **not** `/builder/` |
| Panel fragment | `/manage/courses/<slug>/build/node/<pk>/` | contains **no** literal `panel` — filtering requests on `"panel" in r.url` matches nothing |
| Rename POST | `/manage/courses/<slug>/build/node/rename/` | route glob `**/build/node/rename/` |

Panel-GET counting therefore uses this shared predicate (the trailing `$` excludes
`/node/<pk>/export/`, and `\d+` excludes `/node/rename/`):

```python
def _is_panel_get(r):
    return r.method == "GET" and re.search(r"/build/node/\d+/$", r.url) is not None
```

(`re` is imported at the top of the skeleton -- a module-level import placed after function
definitions would be `E402`.)

```python
@pytest.mark.django_db(transaction=True)
def test_sibling_tokens_are_refreshed_so_duplicate_still_works(page, live_server):
    # (F) falsify: skip the duplicate form's token refresh in applyRename.
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    title = page.locator('.tree__title[value="Unit 1"]')
    title.click()
    title.press("Control+a")
    page.keyboard.type("Renamed")
    # MUST await the response: the token patch happens when it lands, so firing the
    # follow-up op immediately would race the round trip (which the design accepts as
    # a 409) and the test would be flaky by construction.
    with page.expect_response(lambda r: "rename" in r.url and r.request.method == "POST"):
        title.press("Enter")
    # Anchor by pk and scope to the row's OWN head. `li.tree__row:has(...)` would match
    # the chapter and section ancestors too, and a bare descendant selector under those
    # also finds Unit 2's duplicate button -- two elements, so .click() raises a
    # strict-mode violation before the feature is exercised at all. (Same hazard as
    # tests/test_e2e_transfer.py:151-158.)
    row = page.locator(f'li.tree__row[data-node="{nodes["unit1"].pk}"]')
    row.locator(':scope > .tree__rowhead form[data-op="duplicate"] button[type="submit"]').click()
    expect(page.locator(".op-error")).to_have_count(0)
    expect(page.locator('.tree__title[value="Renamed"]')).to_have_count(2)


@pytest.mark.django_db(transaction=True)
def test_field_is_readonly_during_the_round_trip(page, live_server):
    # (F) falsify: remove `input.readOnly = true` from commitRename.
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")

    # Hold the response open so the in-flight window is observable.
    gate = {"release": None}
    def _handler(route):
        gate["release"] = route
    page.route("**/build/node/rename/", _handler)

    # Capture a HANDLE, not a value-attribute locator: applyRename sets defaultValue,
    # which reflects to the `value` ATTRIBUTE, so '[value="Unit 1"]' would resolve to
    # zero elements the moment the response lands.
    title = page.locator('.tree__title[value="Unit 1"]').element_handle()
    title.click()
    title.press("Control+a")
    page.keyboard.type("Renamed")
    with page.expect_request("**/build/node/rename/"):
        title.press("Enter")
    # readOnly is set BEFORE requestSubmit(), so waiting only on it can win the race
    # before the route handler has fired -- gate["release"] would still be None and the
    # test would die with AttributeError instead of a meaningful failure.
    page.wait_for_function("el => el.readOnly === true", arg=title)
    assert gate["release"] is not None
    # page.keyboard.type performs NO editability check and silently no-ops on a
    # readonly field. locator.fill()/type()/pressSequentially() run an *editable*
    # actionability check: they would hang and throw a timeout here, and would SUCCEED
    # once readOnly is removed -- inverting the test's RED and GREEN.
    page.keyboard.type("XYZ")
    assert title.input_value() == "Renamed"
    gate["release"].continue_()
    page.wait_for_function("el => el.readOnly === false", arg=title)
    assert title.input_value() == "Renamed"


@pytest.mark.django_db(transaction=True)
def test_422_does_not_wedge_the_row(page, live_server):
    # (F) falsify: stop clearing readOnly on the non-200 branch.
    # A 422 is UNREACHABLE by typing (required blocks empty, maxlength truncates
    # over-length, ContentNode.clean validates nothing else), so it is forced here.
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")

    state = {"n": 0}
    def _handler(route):
        state["n"] += 1
        if state["n"] == 1:
            route.fulfill(
                status=422,
                content_type="text/html; charset=utf-8",
                body='<div class="op-error" role="alert">Nope.</div>',
            )
        else:
            route.continue_()
    page.route("**/build/node/rename/", _handler)

    title = page.locator('.tree__title[value="Unit 1"]').element_handle()
    title.click()
    title.press("Control+a")
    page.keyboard.type("Rejected")
    title.press("Enter")
    expect(page.locator(".op-error")).to_be_visible()
    assert title.input_value() == "Rejected"        # typed text survives
    page.wait_for_function("el => el.readOnly === false", arg=title)   # not wedged
    assert page.evaluate("el => el === document.activeElement", title)
    # The counter (not page.unroute) is the mechanism: the second request falls through
    # to route.continue_() and reaches the real server. No unroute call is needed, and
    # the route stays registered for the rest of the test.
    title.press("Control+a")
    page.keyboard.type("Corrected")
    with page.expect_response(
        lambda r: "/build/node/rename/" in r.url and r.request.method == "POST"
    ):
        title.press("Enter")
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Corrected"


@pytest.mark.django_db(transaction=True)
def test_tabbing_across_a_row_issues_one_panel_fetch(page, live_server):
    # (F) falsify: scope the panelTimer clear to .tree__title focusins only.
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    gets = []
    page.on("request", lambda r: gets.append(r.url) if _is_panel_get(r) else None)

    # Start tabbing IMMEDIATELY -- do not settle, do not clear. Unit 1's debounced
    # fetch must still be PENDING when traversal begins: that pending timer is the
    # whole point. Draining it first (a 400ms wait + gets.clear()) makes the test
    # vacuous -- the falsified build would record the same single GET and pass, and so
    # would a build with no debounce at all. The only timing requirement is that the
    # first Tab lands within 150ms of this focus, which is not tight.
    page.locator('.tree__title[value="Unit 1"]').focus()

    # The REAL tab order is title -> cluster controls -> next row's title, and the
    # number of stops VARIES: _move_buttons renders the up arrow `disabled` on the
    # first sibling and the down arrow `disabled` on the last, and disabled buttons are
    # skipped. So tab until focus lands on a title again rather than hard-coding a
    # count -- a wrong count lands on a cluster control, whose focusin clears the timer,
    # and the test then asserts 0 == 1 for a reason unrelated to the debounce.
    for _ in range(15):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.classList.contains('tree__title')"):
            break
    else:
        raise AssertionError("never tabbed back onto a .tree__title")
    assert page.evaluate("document.activeElement.value") == "Unit 2"

    page.wait_for_timeout(400)          # let the 150ms debounce settle
    # Exactly one: Unit 2's. Unit 1's pending timer was cancelled by the first cluster
    # focusin. Falsified (clear scoped to .tree__title focusins), this records 2.
    assert len(gets) == 1, gets
```

Cover, in addition:

**Core**
- Click a **unit** title, type, press Enter → the tree label updates *and* the DB value changes.
- Same for a **chapter**, proving the interaction is kind-agnostic.
- **(F)** **Focus and caret survive an Enter commit.** The order is load-bearing: **type a change
  first**, *then* reposition the caret mid-string (`setSelectionRange` via `page.evaluate`, or arrow
  keys), record `selectionStart`, press Enter **inside**
  `page.expect_response(lambda r: "/build/node/rename/" in r.url and r.request.method == "POST")` so
  the assertions run after `applyRename` has executed, and only then assert the input is still
  focused and `selectionStart` is unchanged.
  Without the edit the field is clean, `commitRename` bails on
  `trimmed === input.defaultValue.trim()`, nothing posts, and focus/`selectionStart` are trivially
  unchanged in **every** build — including one that reassigns `value` unconditionally or swaps the
  whole scope. This is the only test pinning the two guarded value writes (Task 6's
  `if (input.value !== trimmed)` and Task 7's `if (input.value !== title)`), which the plan calls
  load-bearing in both places, so a vacuous version here ships both unprotected.
  Two falsifications: drop each guard in turn and require the `selectionStart` assertion to go RED.
  This is also the observable proof that no scope swap happened.
- **Blur commits:** type, then click outside the tree → saved.
- **Escape reverts and keeps focus.**
- **Tooltip tracks typing, then reverts:** extend `_seed_course` with a fifth node carrying a deliberately long title (copy the `LONG_TITLE` constant idea from `tests/test_e2e_builder_tree_layout.py:17`; keep it under the 200-char field limit), since the four seeded nodes are all short and nothing would truncate. Type into that long title and — **before** Escape — assert `title` equals the *typed* value; then Escape and assert it equals the reverted value. Without the mid-typing assertion, omitting the `input` handler entirely still passes the Escape half. Two falsifications: delete the `input` handler (first assertion RED); drop `revert()`'s title sync (second RED).
- **Unchanged field does not post:** focus and blur without typing → **no POST to `manage_node_rename`** (a panel GET is expected and must not be counted), and no `updated` bump.
- **Enter on an unchanged title issues no POST**; **plain Enter posts exactly once**; **Enter-then-blur posts exactly once**.

**In-flight**
- **Read-only during the round trip:** with the response delayed via route interception, press Enter, then attempt to type, assert the value is unchanged, then let the response land and assert the field is editable again. **Use `page.keyboard.type()` after focusing — not `fill()` or the locator's `type()`/`pressSequentially()`.** Those run an *editable* actionability check, so against a `readOnly` input they hang and throw a timeout instead of typing-and-asserting-unchanged — and they *succeed* once the `readOnly` assignment is removed, inverting RED and GREEN. `page.keyboard.type()` performs no editability check and silently no-ops. Assert `readOnly` is `false` afterwards via `to_have_js_property` before re-typing.
- **Window blur does not commit:** type, blur the window (not the field) → no POST; field stays dirty. Playwright has no gesture that blurs the browser window: use a **second page in the same context plus `bring_to_front()`**, and confirm `document.hasFocus()` actually reports `False` under the run mode used — it differs between headed and headless Chromium. If it does not, skip with that reason rather than leaving the test falsely green.

**Token refresh — the reason Task 7 exists.** Every one of these must **wait for the rename POST's response** (`expect_response` on `manage_node_rename`) before firing the follow-up op. The token patch happens when the response lands, so firing "immediately" races the round trip — which the design explicitly accepts as a 409 — making the test flaky by construction and its failure indistinguishable from the bug it guards.
- **(F)** Rename a **unit**, await the response, then click Duplicate on that row → succeeds, **no** conflict notice. Falsify by skipping the duplicate form's token refresh.
- **(F)** Same for the reorder arrows (every row has them). Use the same pk-anchored,
  `:scope > .tree__rowhead` locator as the duplicate test above — a bare descendant selector under a
  `:has()`-matched row picks up sibling rows' controls and raises a strict-mode violation.

**Drag scenarios need the repo's dispatchEvent helper, not `drag_to`.** Playwright's `drag_to` uses
pointer events internally and does **not** fire the `dragstart`/`dragover`/`drop` DOM events
`builder.js` listens for — it produces a silently-green "nothing happened" test. Reuse
`_simulate_drag` from `tests/test_e2e_builder_ws2.py:256` (synthetic `DragEvent` + `dataTransfer`),
and note the **`dragover` sweep is required**: `scope.dataset.dropToken` is only populated by the
`dragover` handler, so a `drop` without a preceding `dragover` posts no `parent_token` and the test
would not exercise the token refresh at all. `_simulate_drag` **already dispatches that `dragover`** at the destination's centre, which is sufficient -- use it **unmodified**; no multi-`clientY` sweep is needed for these two scenarios.
- **(F)** Drag of the just-renamed row (guards the `<li>`'s `data-updated`, read at `dragstart`).
- **(F)** **Rename a chapter, await, then drag a unit into it** → no conflict notice. Guards the child scope's `data-updated`.
- **Rename a chapter, await, then add a lesson under it** → succeeds, no conflict notice, typed child title not discarded. Guards the child scope's `parent_token`. **The fixture chapter must itself contain a nested section with its own add row**, so a naive descendant query (which would find the *grandchild's* `parent_token`) fails RED — and additionally assert the nested section's own add still works afterwards, which is what catches a mis-stamped token.
- **Rename the same row twice without reloading:** commit via Enter, wait, then type a different title and Enter again → both succeed, no conflict, DB holds the second title. This is the only test exercising the rename form's *own* refreshed token together with the `defaultValue` reset. Falsify by skipping that refresh.

**Errors**
- **(F)** **409 reloads the row and discards the edit.** Force the stale token **server-side via the
  ORM**, after the page has rendered — do not route-fulfil, since a hand-written body would not be the
  real `_conflict_scope` `[data-scope]` fragment the assertions depend on, and "post from a second
  client" would need its own session and CSRF handling:

  ```python
  node = nodes["unit1"]
  node.title = "Changed elsewhere"
  node.save(update_fields=["title", "updated"])   # bumps `updated`; page token is now stale
  ```

  Then type into the still-rendered row and press Enter. Assert: the conflict notice
  (`.op-error`) is visible; the row now shows `[value="Changed elsewhere"]` (the server's title, not
  the typed one); and focus has dropped — `page.evaluate("document.activeElement.tagName")` is
  `"BODY"`. This is the accepted cost of the one path that still swaps a scope; the test pins it
  rather than leaving it to be discovered. Falsify by routing the 409 through `applyRename` instead
  of `applyFragment` — the row would keep the stale title.
- **(F)** **An open add row's deferred commit clobbers a fresh rename edit:** type into an inline-add
  row, then click a tree title in the same scope and start typing. 120ms after the blur,
  `commitOrCancel` posts `node_add`, whose 200 is a `[data-scope]` fragment that `applyFragment`
  swaps — destroying the rename input mid-edit and dropping focus to `<body>`. The typed text is
  **accepted** as lost (same class as any foreign swap; cross-wiring the two flows to avoid it would
  reintroduce the coordination machinery this design removed). Assert on **requests** — zero POSTs to
  `manage_node_rename` — not on the row's title in the database: focus reaches `<body>` at swap time,
  i.e. inside the window between a POST being issued and it landing, so a database read there samples
  the gap and passes even when the commit goes through behind it. Then assert the invariants that
  make the loss merely a loss: the add child exists, exactly one row for the unit, the row still
  shows server truth, no `.op-error`, and the row is still editable afterwards. Falsify by dropping
  `swapping ||` from bail-out 3 — Chromium *does* dispatch a focusout for the doomed input, from
  inside `replaceWith()` with `isConnected` still true, so the half-typed title is POSTed.
- **422 does not wedge the row.** The row's guards make a 422 **unreachable by typing** — `required` plus the unconditional Enter-cancel block an empty title, `maxlength="200"` truncates over-length input including pasted text, and `ContentNode.clean()` validates nothing else about the title. So both 422 tests use **route interception**: fulfil the first `manage_node_rename` request with a 422 and an `_op_error.html` body, assert the notice appeared and that the typed text, focus and cleared `readOnly` all survived; the **request counter** in the written-out test above -- not `page.unroute` -- is what lets the corrected re-submit through: the second request falls to `route.continue_()` and reaches the real server, so no teardown is needed. Do **not** use `page.evaluate` to strip `maxlength`.

**Navigation / a11y**
- **Enter on an empty field does not wedge the row:** clear the field, press Enter (native bubble), then type a valid title and Enter → it commits. Additionally assert **zero** requests to `manage_node_rename` during the empty-Enter step: without that, the test passes even if `readOnly` is set *before* `reportValidity()`, which would skip validation entirely, POST the empty title and merely 422. Falsify by swapping the `readOnly`/`reportValidity()` order.
- **Debounce / ordering:** Tab from a row title through that row's cluster controls to the **next** row's title — the real tab order, ~6 stops per row — and assert exactly **one** panel GET, counted after focus rests. Written as "Tab N times between titles" it would not exercise the actual path. A pointer click issues its GET immediately. Falsify by scoping the timer clear to `.tree__title` focusins only.
- **Tab to a row, then immediately click a different row** → after both actions and a settle wait, the panel shows the **clicked** row. Assert the END STATE only: Playwright cannot guarantee the two actions complete inside the 150ms window, and on a loaded runner a timing-based assertion flakes both ways. The end state holds regardless of which fetch won, thanks to the `panelReq` last-request-wins guard -- which is the invariant actually worth pinning.
- **Keyboard tab order:** tabbing from a row title reaches the next control, not a hidden "Rename".
- **Top-level rename preserves document scroll** in a long course. `_seed_course` is too small to scroll, and the tall fixture lives in another module -- give `_seed_course` an optional `n_units` parameter and seed enough rows to overflow the viewport (the repo's convention is self-contained e2e modules, so extend the local helper rather than importing `_seed_tall_course`).

- [ ] **Step 5: Run the e2e suite in the foreground**

```bash
uv run pytest -m e2e tests/test_e2e_builder*.py tests/test_e2e_transfer.py tests/test_e2e_inline_rename.py -v
```

Run the **whole builder e2e set**, not just the two modules this task edits directly: Task 3 Step 5b touched
four further modules in Task 3 Step 5b, and `uv run pytest` in Task 9 deselects every e2e test
(`addopts` excludes the marker), so this command is the last check that the whole builder e2e set is
still green before the PR.

Expected: all PASS, with a collected count matching the number of tests written — **`-m e2e` is
mandatory** (`pyproject.toml:48` excludes the marker by default), and a run that collects 0 tests
exits successfully, so verify the count rather than the exit status.

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
- Modify: `docs/help/course-admin/builder.md`, `docs/help/course-admin/builder.pl.md`
- Regenerate: `core/static/core/img/help/builder-tree.en.png`, `core/static/core/img/help/builder-tree.pl.png`

- [ ] **Step 1: Refresh the catalogs**

```bash
uv run python manage.py makemessages -l en -l pl
```

**No msgid is removed by this change.** `Title` and `Rename` both survive in the new `_tree_node.html` markup, so only their source-location comments change — deleting them would drop working Polish translations. If any msgid *does* fall out of use, delete it from both catalogs rather than leaving an obsolete `#~` entry, which the catalog tests reject. Watch for fuzzy flags and clear them.

- [ ] **Step 2: Run the i18n tests**

```bash
uv run pytest tests/test_i18n_ws4.py tests/test_i18n_auth.py tests/test_i18n_notes.py tests/test_tags_i18n.py -v
```

Expected: PASS. Note `test_i18n_ws4.py` alone would give **false assurance** — it only checks that a
fixed list of WS4 msgids is translated and never reads the `.po` files. The obsolete-`#~` guards live
in `tests/test_i18n_auth.py:70`, `tests/test_i18n_notes.py:56` and `tests/test_tags_i18n.py:10`.

`compilemessages` is **not** required here: this change adds and removes no msgid — `Title` and
`Rename` already exist (`editor/_unit_settings.html:12`; translated at `locale/pl/…/django.po:556`
and `:4154`) — so only source-location comments change and the `.mo` files stay valid.

- [ ] **Step 3: Measure page weight against a budget**

The row gains a `<form>`, a `{% csrf_token %}`, two hidden inputs, a hidden submit and a second
`{% url %}` reversal — offset slightly by dropping `data-select`. Courses here reach ~800 units, so
measure rather than assume. (The CSRF token is kept rather than dropped in favour of the
cookie-reading `csrf()` helper, because dropping it would break the no-JS path this design newly
enables.)

Run these **in order**: seed → serve both → measure → tear down.

**1. Take the baseline safely.** Do **not** `git checkout master` in this worktree — a parallel session
has previously switched branches under an agent mid-task, and this worktree is explicitly flagged as
running concurrently with others. Create a throwaway checkout instead, on a Windows-safe path (this
host runs Windows; `/tmp` only resolves under Git Bash and lands in the MSYS root). It must be
**`--detach`ed**: `master` is already checked out in the main repo, and `git worktree add` refuses a
branch that is checked out elsewhere (`fatal: 'master' is already checked out at ...`).

```bash
BASE="$LOCALAPPDATA/Temp/claude/libli-perf-baseline"
git -C C:/Users/krzys/Documents/Python/own/libli worktree add --detach "$BASE" master
```

**2. Seed once, into a database of its own.** Do **not** reuse the `DATABASE_URL` from Global
Constraints — that one isolates the *pytest* database, and seeding 840 nodes into it (or leaving them
behind if teardown is skipped) would pollute the test runs. Export a separate one and use it for the
seed, both servers, and the teardown:

```bash
export PERF_DATABASE_URL=postgres://postgres:postgres@localhost:5432/libli_perf
```

Both measurements then read the same `perf` course from that same database.

```bash
DATABASE_URL=$PERF_DATABASE_URL uv run python manage.py shell -c "
from django.contrib.auth.models import Group
from institution.roles import PLATFORM_ADMIN, seed_roles
from tests.factories import CourseFactory, ContentNodeFactory, TEST_PASSWORD, make_verified_user
seed_roles()
o = make_verified_user(username='perfadmin', email='perfadmin@t.example.com', password=TEST_PASSWORD)
o.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
c = CourseFactory(slug='perf', owner=o)
for i in range(40):
    ch = ContentNodeFactory(course=c, kind='chapter', parent=None, title=f'Ch {i}')
    for j in range(20):
        ContentNodeFactory(course=c, kind='unit', unit_type='lesson', parent=ch, title=f'U {i}.{j}')
print(c.slug)
"
```

That is 800 units + 40 chapters, owned by **`perfadmin`** — one identity throughout, created here as
a verified platform admin (a bare `UserFactory` is not authorized for the manage surface). Its
password is `tests.factories.TEST_PASSWORD`; export it for the curl step. Use `manage.py shell`, not
a bare `python -c` — `tests/factories.py` imports `accounts.models`/`courses.models` at module level
and would raise `AppRegistryNotReady` before reaching the constant, leaving `PW` empty:

```bash
export PW=$(DATABASE_URL=$PERF_DATABASE_URL uv run python manage.py shell -c "from tests.factories import TEST_PASSWORD; print(TEST_PASSWORD)")
```

**3. Serve both checkouts against that database**, on distinct ports. `runserver` **blocks**, so each
goes in its own shell (or backgrounded); and a freshly-added worktree has no synced environment, so
prepare `$BASE` first:

```bash
# prepare the baseline checkout (own venv; copy whatever env file this repo uses)
(cd "$BASE" && cp C:/Users/krzys/Documents/Python/own/libli/.env . 2>/dev/null; uv sync)

# shell 1 -- this branch, from the pipeline worktree
DATABASE_URL=$PERF_DATABASE_URL uv run python manage.py runserver 8010

# shell 2 -- the baseline, from $BASE
cd "$BASE" && DATABASE_URL=$PERF_DATABASE_URL uv run python manage.py runserver 8011
```

**4. Measure.** `manage_builder` is `@login_required` and permission-gated, so an unauthenticated
`curl` measures a **login redirect**, not the tree. Log in through the form first and reuse the cookie
jar:

```bash
# Django's CsrfViewMiddleware requires csrfmiddlewaretoken in the POST BODY -- a cookie
# plus a Referer is not enough for a non-AJAX POST, and allauth's login view is not
# exempt. Omit it and the POST 403s, no session cookie is set, and the builder fetch
# below silently measures the @login_required REDIRECT -- on both ports, so the two
# numbers match and the 15% budget passes vacuously.
curl -s -c jar.txt -o login.html http://localhost:8010/accounts/login/
TOK=$(grep -o 'name="csrfmiddlewaretoken" value="[^"]*"' login.html | cut -d'"' -f4)
curl -s -b jar.txt -c jar.txt \
     -d "csrfmiddlewaretoken=$TOK" -d "login=perfadmin" -d "password=$PW" \
     -e http://localhost:8010/accounts/login/ http://localhost:8010/accounts/login/ > /dev/null

# Sanity-check BEFORE recording a number -- a login redirect also returns 200.
curl -s -b jar.txt http://localhost:8010/manage/courses/perf/build/ | grep -q 'data-scope="top"' \
  || { echo "not logged in -- measuring the wrong page"; exit 1; }

curl -s -b jar.txt --compressed -o /dev/null -w '%{size_download}\n' \
     http://localhost:8010/manage/courses/perf/build/
```

The builder path is `/manage/courses/perf/build/` — **not** `/builder/` (`courses/urls.py:158`); this
is the same canonical path Task 8 uses. Repeat against port 8011 for the baseline. Record **gzipped
transferred bytes** from those two numbers, and **DOM node count**
(`document.getElementsByTagName('*').length`) from DevTools on each.

**5. Tear down, after both measurements:**

```bash
git -C C:/Users/krzys/Documents/Python/own/libli worktree remove --force "$BASE"
DATABASE_URL=$PERF_DATABASE_URL uv run python manage.py shell -c "
from courses.models import Course; Course.objects.filter(slug='perf').delete()"
```

**Budget:** flag it in the PR body if gzipped transferred size grows by more than **15%**, or if the
per-row DOM node growth exceeds **6 nodes**. If either is exceeded, do not silently proceed — stop and
report, since the fallback (dropping `{% csrf_token %}` and reading the cookie instead) trades away
the no-JS path and is a decision for the author, not the implementer.

- [ ] **Step 4: Visual verification**

Playwright screenshots in **light and dark**: the tree at rest, on hover, and focused; plus the **selected non-unit detail panel**, now heading-only, which must not look broken or awkwardly padded. Self-critique before accepting.

- [ ] **Step 4b: Regenerate the committed help screenshots**

`core/static/core/img/help/builder-tree.en.png` and `builder-tree.pl.png` are **checked-in** images
produced by `tests/capture_help_screenshots.py` (the `"builder-tree"` entry, clipped to
`section.builder`) and shown on the `builder` help topic. This change alters exactly what they depict
— every row title becomes a text field with a hover border — so without regeneration the help page
ships a picture of the old button-based tree.

```bash
CAPTURE_ONLY=builder-tree uv run pytest tests/capture_help_screenshots.py::test_capture_help_screenshots -v
```

Two things make this non-obvious: the harness has no `test_` filename prefix, so a bare
`uv run pytest` does **not** collect it; and without `CAPTURE_ONLY` it regenerates all ~23 shots in
both locales, churning committed PNGs this change does not touch. The EN/PL loop is internal to the
test — no per-locale invocation is needed.

Then verify the topic still renders its illustration and commit the two regenerated PNGs:

```bash
uv run pytest tests/test_help.py -k every_topic_illustrated -v
```

- [ ] **Step 4c: Document the new capability in the builder help topic**

`docs/help/course-admin/builder.md` and its Polish twin `builder.pl.md` say nothing about renaming,
yet this change makes in-tree renaming a primary gesture and is the first time a **unit** can be
renamed without opening the editor. Add a short "Renaming" paragraph to both, kept in sync: click a
title, type, then Enter or click away to save; Escape reverts. Mention that it works for every level
of the tree.

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
git add locale/ docs/help/course-admin/builder.md docs/help/course-admin/builder.pl.md         core/static/core/img/help/builder-tree.en.png core/static/core/img/help/builder-tree.pl.png
git commit -m "docs(builder): document inline renaming; refresh catalogs and help shots

The builder-tree help screenshots depicted the old button-based titles, and
neither help topic mentioned renaming -- which is now a primary tree gesture
and the only way to rename a unit without opening the editor."
```

---

## Self-Review

**Spec coverage.** Backend normalization → Task 1. Narrow response → Task 2. Template/markup, panel change, partial deletion → Task 3. Styling (cascade, font, layout-neutral hover) → Task 4. JS selection/debounce/`refreshPanel` → Task 5. Commit path (Enter/blur/Escape/trim/validity/`readOnly`) → Task 6. In-place application and the four-item token inventory → Task 7. The four-module `text=` wait migration → Task 3 Step 5b (it must land with the markup that breaks those waits); `test_e2e_builder_tree_layout.py`'s locator migration and the new e2e suite → Task 8. i18n, page weight, screenshots, screen-reader → Task 9. The no-JS path is covered by a test in Task 2 and by the markup in Task 3.

**Placeholders.** Every code step in Tasks 1-7 and 9 carries actual code, every command its expected output, every test its falsification. Task 8 is the deliberate exception: it ships the module skeleton, the Task 7 smoke test, and full code for the four scenarios with genuine Playwright-API risk (token refresh, readonly-in-flight, route-intercepted 422, debounce request-counting); the remaining ~20 scenarios are specified as prose because they are ordinary click/type/assert written by analogy. Each carries either an `(F)` falsification marker or an explicit falsification sentence.

**Type/name consistency.** `_clean_title` (Task 1) is referenced only in Task 1. `_rename_result.html`'s `data-rename-for` / `data-updated` / `value` (Task 2) are exactly the attributes `applyRename` reads (Task 7). `revert`/`commitRename`/`titleForm` (Task 6) are used consistently. `form.tree__rename`, `input.tree__title`, `li.tree__row[data-node]`, `form.tree__add[data-add-scope]` match the markup in Task 3 and the existing templates.

**Deliberately accepted, not gaps** (do not "fix" these during implementation): the touch soft-keyboard cost; a foreign swap clobbering a half-typed title and its stale-display residual; a same-row op racing the round trip and 409-ing; the panel heading lagging until reselect; the AT role change; per-row markup growth; starting a rename discarding an open Move picker; `spellcheck` disabled; ancestor scope tokens untouched; Escape doing nothing mid-flight.

Two more, added after review because they are real losses that were previously implicit rather than
stated — both are pinned by tests in Task 8 so they cannot regress unnoticed:

- **A 409 discards the typed title and drops focus to `<body>`.** It is the one path that still swaps a
  scope, deliberately: the tree genuinely diverged and must be reloaded to server truth.
- **An open inline-add row's 120ms deferred commit destroys a rename input the author just focused.**
  Cross-wiring the two flows to prevent it would reintroduce exactly the coordination machinery the
  narrow-response design removed, for a rarer case.
