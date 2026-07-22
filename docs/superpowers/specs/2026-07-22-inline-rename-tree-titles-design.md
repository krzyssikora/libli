# Inline rename of node titles in the course builder tree

## Purpose

In the course builder, every node kind except **unit** can be renamed without leaving the page: you
click a node in the tree and the detail panel offers a `Title` field plus a `Rename` button
(`templates/courses/manage/_node_panel.html:4` → `_rename_form.html`). The unit panel
(`_unit_panel.html`) deliberately omits that form — commit `acc8dab` moved unit settings (title,
type, obligatory, seed JS) onto the editor page — so renaming a unit means opening the editor,
changing the title, and coming back. For a course with many units that is a lot of round trips for a
one-word change.

This design makes the **title of every tree row directly editable in place**, for parts, chapters,
sections and units alike, and removes the panel rename form so there is exactly one way to rename a
node.

Two goals, in priority order:

1. **A unit's title is editable from the builder tree**, without opening the editor.
2. **One consistent rename interaction for every node kind** — no per-kind special cases, no
   separate "enter edit mode" affordance.

Non-goals: renaming the course itself (that stays on the course-metadata page), any change to unit
*type*/*obligatory*/*seed JS* (they stay on the editor page), and any change to element editing.

## Interaction design

- **Click a row title** → the node is selected (the detail panel loads, exactly as today) *and* the
  caret lands in the title text, ready to edit. There is no separate pencil or "edit" affordance.
- **Enter**, or **clicking away (blur)** → saves, but only if the text actually changed. An unchanged
  field never posts.
- **Escape** → restores the stored title and blurs, discarding the edit.
- **Invalid title** (e.g. blank) → the server's existing 422 path fires the existing error notice; the
  typed text stays in the field so the author can correct it, and the row's optimistic-lock token is
  unchanged so re-submitting works.
- **Resting appearance:** the field looks like plain text — no border, no background — so the tree
  does not become a wall of input boxes. A subtle border appears on hover and a real focus ring on
  focus. Truncation with an ellipsis is preserved, as today.

## Architecture / components

The change is deliberately a **relocation of the existing rename form**, not a new mechanism. No
backend change is required.

### What already works and is reused unchanged

- `courses/builder.py:163` `rename_node(course, node_pk, title, token, unit_type=_UNSET, …)` already
  performs a **title-only** rename of any node kind: `unit_type`, `obligatory` and `html_seed_js` are
  only touched when they are not `_UNSET`, so a POST carrying just `node`/`token`/`title` renames a
  unit without disturbing its type or settings.
- `courses/views_manage.py:290` `node_rename` already handles that POST shape: `has_settings` and
  `type_only` are absent, `ctx` is not `editor`, so it takes the plain-rename branch and returns
  `_render_scope(request, course, _scope_ref(node.parent_id))` — the parent scope fragment, which is
  exactly the tree subtree containing the renamed row. The label therefore updates in the tree with no
  extra work.
- `courses/static/courses/js/builder.js:135` intercepts **any** builder form carrying `data-op`,
  POSTs it via `fetch` with the CSRF token, and swaps the returned fragment via `applyFragment`,
  handling 200 / 409 (conflict notice) / 422 (error notice) uniformly.
- The optimistic-lock token (`node.updated.isoformat`) and its `ConflictError` → 409 → "reloaded to
  the latest" path are unchanged.

### Template change — `templates/courses/manage/_tree_node.html`

Line 12–13's title `<button>` becomes a small form wrapping a text input:

```html
<form class="tree__rename" method="post"
      action="{% url 'courses:manage_node_rename' slug=node.course.slug %}" data-op="rename">
  {% csrf_token %}
  <input type="hidden" name="node" value="{{ node.pk }}">
  <input type="hidden" name="token" value="{{ node.updated.isoformat }}">
  <input class="tree__title" type="text" name="title" value="{{ node.title }}"
         title="{{ node.title }}"
         aria-label="{% trans 'Title' %}"
         data-select="{{ node.pk }}"
         data-panel-url="{% url 'courses:manage_node_panel' slug=node.course.slug pk=node.pk %}">
  <button class="visually-hidden" type="submit">{% trans "Rename" %}</button>
</form>
```

Three structural points:

- **The form wraps only the title**, staying a *sibling* of the per-row `duplicate` form already
  present in `.tree__cluster` (`_tree_node.html:20-25`). Nested forms are invalid HTML; wrapping the
  whole `.tree__rowhead` would produce them.
- **`data-select` / `data-panel-url` move onto the input**, so selection keeps working from the same
  element the user clicks.
- **The submit button is `.visually-hidden`** (the class exists at `core/static/core/css/app.css:1167`).
  It is never seen by sighted mouse users but gives assistive tech an explicit control and guarantees
  a working submit path.

### No-JS behaviour

Today the detail panel is JS-only: the title is a `type="button"` with a `data-panel-url` that only
`builder.js` acts on, so **without JS there is currently no way to rename any node from the builder.**
After this change the tree row is a real `<form method="post">`: pressing Enter (or activating the
hidden submit) posts normally, `node_rename` falls through `_wants_fragment` to
`redirect("courses:manage_builder")`, and the builder re-renders with the new title. This is a strict
improvement, not a regression.

Blur-to-save and Escape-to-revert are JS enhancements; without JS, Enter is the commit gesture.

### JavaScript change — `courses/static/courses/js/builder.js`

1. **Selection moves from `click` to `focus`.** The existing handler at line 190 does
   `e.preventDefault()` on `[data-select]`; on a text input that suppresses caret placement. Selection
   is therefore driven by a `focus` (capturing, since `focus` does not bubble — or `focusin`, which
   does) listener on `[data-select]`, and the click handler no longer claims `[data-select]`. The
   panel-fetch body itself (`fetch(data-panel-url)` → `setPanel`) is unchanged, as is `clearMoving()`.
2. **Commit on blur or Enter, when dirty.** A `blur`/`focusout` handler on `.tree__title` submits its
   form when `input.value !== input.defaultValue`; a `keydown` handler submits on `Enter` (preventing
   the native submit so the existing `data-op` fetch path handles it).
3. **Escape reverts.** `keydown` on `Escape` sets `input.value = input.defaultValue` and blurs; the
   blur handler then sees a clean field and does not post.
4. **Focus restoration after an Enter commit.** The server returns the parent scope fragment, so
   `applyFragment` replaces the input element. After a successful swap the handler re-focuses the
   input for that `data-node`, so the author can keep typing/tabbing. A blur commit needs no
   restoration — focus has already legitimately moved on.
5. **Panel refresh.** `refreshPanel` (line 123) keys off `panel.contains(form)`; a tree-row rename form
   is *not* in the panel, so no panel refresh runs. That is correct: the tree swap already re-renders
   the row with a fresh token, and the panel's own content (heading, and for units the element list)
   is unaffected by a title change. The panel heading will show a stale title until reselected — an
   accepted cosmetic lag, called out here so it is not mistaken for a bug.

### Panel change — `templates/courses/manage/_node_panel.html`

The `_rename_form.html` include is removed, leaving a heading-only panel for non-unit nodes. The panel
is kept (rather than suppressing panel loading for non-units) because it preserves the selection
feedback and costs nothing.

`_unit_panel.html` is **not** changed: it stays valuable (type/obligatory summary, element list,
`+ Add element`, `Open editor →`).

`_rename_form.html` itself is **kept**, because `templates/courses/manage/editor/_unit_settings.html`
still posts a rename with `ctx=editor` for unit settings on the editor page. Only the `_node_panel`
include of it goes away. (Implementation note: confirm whether `_unit_settings.html` includes
`_rename_form.html` or carries its own markup; if nothing else includes `_rename_form.html`, delete
it.)

### Styling — `courses/static/courses/css/builder.css`

`.tree__title` (line 38) currently styles a button: `flex: 1; min-width: 0; white-space: nowrap;
overflow: hidden; text-overflow: ellipsis; background: none; border: none; cursor: pointer;
text-align: left; color: var(--text-primary); padding: 0;`.

- Those properties are retained on the input (the ellipsis/nowrap/min-width trio is asserted by
  `tests/test_builder_styles.py:34-41` and must keep passing), with `cursor: text` replacing
  `cursor: pointer`.
- The flex item is now the **`.tree__rename` form**, not the input, so the form takes
  `flex: 1; min-width: 0; display: flex` and the input keeps `min-width: 0` to shrink below its
  content width.
- Hover and focus states: a subtle border on `:hover`, the standard focus ring on `:focus`, so the
  field reads as plain text at rest but is discoverably editable.
- Visual verification: Playwright screenshots in light **and** dark mode before shipping.

## Data flow

Successful rename (JS path):

1. Author focuses a row title → `focusin` on `[data-select]` → `fetch(data-panel-url)` → panel swaps.
2. Author types, presses Enter (or clicks away) → dirty check passes → `builder.js` submit handler
   posts `node`, `token`, `title`, CSRF to `courses:manage_node_rename`.
3. `node_rename` → `builder_svc.rename_node` → `_check_token` → `full_clean()` →
   `save(update_fields=["updated", "title"])`.
4. Response 200 with the parent-scope fragment → `applyFragment` swaps that subtree → the row now
   renders the new title and a **fresh token**.
5. If the commit came from Enter, focus is restored to the same row's input.

## Error handling

| Situation | Behaviour |
|---|---|
| Blank / invalid title | `full_clean()` raises `ValidationError` → 422 + `_op_error.html` → existing `notice()`. Typed text is retained; the token is unchanged, so a corrected re-submit succeeds. |
| Stale token (node changed elsewhere) | `ConflictError` → 409 → `_conflict_scope` fragment + "This changed elsewhere — reloaded to the latest." Existing path, unchanged. |
| Node deleted elsewhere | `ConflictError` → same 409 path; the row disappears from the swapped scope. |
| Network failure | Existing `catch` → "Network error — please try again." |
| Uncommitted typing clobbered by an unrelated op | A drag/reorder that re-renders the same scope discards uncommitted text. **Accepted**, and identical to how the panel form behaves today. |
| No JavaScript | Enter submits natively; `node_rename` redirects back to the builder. |

## Testing

Every test below is **falsified before being accepted**: break the thing it guards and require RED
first (a passing test that never fails proves nothing).

**Django template/view tests**

- A tree row for each of part / chapter / section / **unit** renders an editable title form
  (`data-op="rename"`, hidden `node` + `token`, `input[name=title]` carrying the current title). The
  unit case is the regression this whole change exists to prevent.
- Posting a title-only rename for a **unit** succeeds and leaves `unit_type`, `obligatory` and
  `html_seed_js` untouched. (`rename_node`'s `_UNSET` handling is the load-bearing behaviour; guard
  it explicitly rather than assuming.)
- `_node_panel.html` no longer renders a rename form.
- `tests/test_tree_badge.py:23` matches `<button class="tree__title"[^>]*\btitle="([^"]*)"` — it must
  be retargeted to the input while still asserting the tooltip.

**CSS test**

- `tests/test_builder_styles.py:34-41` (ellipsis / `min-width: 0` / `nowrap` on `.tree__title`) must
  keep passing against the input rule; extend it to assert the `.tree__rename` form also carries
  `min-width: 0`, since the form is now the flex item that can otherwise blow out the row.

**End-to-end (real browser, real gestures)**

Drive the actual UI — never `page.evaluate` shortcuts, which ship broken UX green.

- Click a **unit** title, type a new name, press Enter → the tree label updates *and* the DB value
  changes.
- Same for a **chapter**, proving the interaction is kind-agnostic.
- **Blur commits:** type, then click elsewhere → saved.
- **Escape reverts:** type, press Escape → field shows the original, nothing posted.
- **Unchanged field does not post:** focus and blur without typing → no request, no `updated` bump.
- `tests/test_e2e_builder_tree_layout.py` locates `.tree__title` with `has_text=` in seven places
  (lines 93, 107, 183, 205, 283, 297, 330). An `<input>` has no text content, so every one of those
  must move to a value-based locator.

**Verification before shipping**

- Full test suite green via `uv run pytest` (bare `pytest`/`ruff`/`python` are not on PATH).
- `uv run ruff check` and `uv run ruff format --check`.
- Light and dark Playwright screenshots of the builder tree at rest, on hover, and focused.
- Because this worktree runs concurrently with others, it needs its **own `DATABASE_URL`** to avoid
  colliding on the shared Postgres `test_libli` database.
