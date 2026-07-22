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
sections and units alike, and removes the panel rename form.

Two goals, in priority order:

1. **A unit's title is editable from the builder tree**, without opening the editor.
2. **One rename surface in the builder**, identical for every node kind — no per-kind special cases,
   no separate "enter edit mode" affordance.

Goal 2 is deliberately scoped to *the builder*. The editor page's unit-settings form
(`templates/courses/manage/editor/_unit_settings.html:6`) contains its own `Title` field alongside
type / obligatory / seed JS, and **keeps it**: it is one field of a coherent settings form, and
removing just that field to chase a global "exactly one rename surface" would leave a settings form
that edits everything about a unit except its name. A unit therefore still has two rename surfaces
overall (tree row, editor settings). That is accepted and stated here so it is not mistaken for an
oversight.

Non-goals: renaming the course itself (that stays on the course-metadata page), any change to unit
*type* / *obligatory* / *seed JS*, and any change to element editing.

## Interaction design

- **Click a row title** → the node is selected (the detail panel loads, as today) *and* the caret
  lands in the title text. There is no separate pencil or "edit" affordance.
- **Enter**, or **clicking away (blur)** → saves, but only if the trimmed text actually changed. An
  unchanged field never posts.
- **Escape** → restores the stored title and blurs, discarding the edit.
- **Blur on an empty or whitespace-only field** → treated as *cancel*: the field reverts to the
  stored title and nothing is posted. (Blur is an ambiguous gesture; silently 422-ing on it would be
  hostile.)
- **Enter on an empty field** → the input's `required` attribute makes `requestSubmit()` fail
  constraint validation, so the browser shows its native "fill in this field" bubble and nothing is
  posted.
- **Server-rejected title** (over `max_length`, or anything reaching the no-JS path) → the existing
  422 path fires the existing error notice; typed text is retained and the row's optimistic-lock
  token is unchanged, so a corrected re-submit succeeds.
- **Resting appearance:** the field looks like plain text — no border, no background — so the tree
  does not become a wall of input boxes. A subtle border appears on hover and a real focus ring on
  focus. Ellipsis truncation is preserved.

**Touch devices — accepted cost.** Because selecting a node now focuses a text input, tapping a row
on a tablet or phone raises the on-screen keyboard even when the author only meant to inspect the
node's panel. A `readonly`-until-second-tap scheme would avoid this, and is **deliberately rejected**:
it reintroduces the two-gesture "edit mode" this design exists to remove, and the builder is a
desktop-first authoring surface (its two-pane layout already collapses to a stacked fallback below
720px). The cost is accepted and recorded here as a decision, not an omission.

## Architecture / components

The change is deliberately a **relocation of the existing rename form**, not a new mechanism. No
backend change is required.

### What already works and is reused unchanged

- `courses/builder.py:163` `rename_node(course, node_pk, title, token, unit_type=_UNSET, …)` already
  performs a **title-only** rename of any node kind: `unit_type`, `obligatory` and `html_seed_js` are
  only touched when they are not `_UNSET`, so a POST carrying just `node`/`token`/`title` renames a
  unit without disturbing its type or settings.
- `courses/views_manage.py:290` `node_rename` already handles that POST shape: `has_settings` and
  `type_only` are absent and `ctx` is not `editor`, so it takes the plain-rename branch.
- `courses/static/courses/js/builder.js:135` intercepts **any** builder form carrying `data-op`,
  POSTs it via `fetch` with the CSRF token, and swaps the returned fragment via `applyFragment`,
  handling 200 / 409 (conflict notice) / 422 (error notice) uniformly.
- The optimistic-lock token (`node.updated.isoformat`) and its `ConflictError` → 409 → "reloaded to
  the latest." path are unchanged.

### Scope of the returned fragment

`node_rename` returns `_render_scope(request, course, _scope_ref(node.parent_id))`. Note that
`_scope_ref(None)` returns `"top"` (`views_manage.py:223`), so renaming a **top-level** node
re-renders the *entire* tree pane, not just a subtree. Two consequences, both of which the JS must
respect:

- **Focus.** The input element is destroyed by the swap. Focus restoration must therefore re-query
  the DOM by `data-node` *after* `applyFragment` returns — never hold a reference to the old element.
- **Other rows' uncommitted typing** in the replaced scope is discarded. Accepted; identical to how
  every other builder op behaves today.

**Scroll position is *not* at risk and needs no restoration code.** `.builder__panel` is the sticky,
`overflow: hidden auto` scroll container (`builder.css:15-16`); the tree itself sits in normal
document flow. Replacing `[data-scope="top"]` with a subtree of identical height — which a rename
guarantees, since the row count and structure are unchanged — leaves document scroll untouched. An
e2e assertion guards this invariant cheaply (see Testing); no `scrollTop` save/restore should be
written.

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
         aria-label="{% blocktrans with kind=node.get_kind_display title=node.title %}Title of {{ kind }} {{ title }}{% endblocktrans %}"
         required maxlength="200" autocomplete="off" spellcheck="false"
         data-select="{{ node.pk }}"
         data-panel-url="{% url 'courses:manage_node_panel' slug=node.course.slug pk=node.pk %}">
  <button class="visually-hidden" type="submit" tabindex="-1">{% trans "Rename" %}</button>
</form>
```

Points that are load-bearing rather than incidental:

- **The form wraps only the title**, staying a *sibling* of the per-row `duplicate` form already
  present in `.tree__cluster` (`_tree_node.html:20-25`). Nested forms are invalid HTML; wrapping the
  whole `.tree__rowhead` would produce them.
- **`data-select` / `data-panel-url` move onto the input**, so selection works from the element the
  user actually clicks.
- **`maxlength="200"`** mirrors `ContentNode.title = models.CharField(max_length=200)`, so
  over-length input is prevented client-side instead of costing a 422 round trip. `required` is what
  makes Enter-on-empty fail constraint validation rather than post a blank title.
- **`autocomplete="off" spellcheck="false"`** — without them every tree row attracts browser autofill
  dropdowns and red squiggles.
- **The accessible name is row-specific.** A bare `aria-label="Title"` would make a screen reader
  announce "Title, edit text" identically for every row, which is worse than the `<button>` it
  replaces (that at least announced its own text). Note `aria-label` overrides the `title` attribute
  for the accessible name; `title` is retained purely as the hover tooltip for truncated labels.
- **The submit button is `.visually-hidden` *and* `tabindex="-1"`.** The utility at
  `core/static/core/css/app.css:1167` uses the `clip` pattern, which keeps the element **focusable** —
  without `tabindex="-1"` every row would gain a second Tab stop, a serious keyboard regression in a
  long course. It exists only to guarantee a submit path for the no-JS case; Enter already submits, so
  removing it from the tab order costs nothing.

### No-JS behaviour

Today the detail panel is JS-only: the title is a `type="button"` with a `data-panel-url` that only
`builder.js` acts on, so **without JS there is currently no way to rename any node from the builder.**
After this change the tree row is a real `<form method="post">`: pressing Enter posts normally,
`node_rename` falls through `_wants_fragment` to `redirect("courses:manage_builder")`, and the builder
re-renders with the new title. This is a strict improvement, and it is covered by a test rather than
merely asserted (see Testing).

Blur-to-save and Escape-to-revert are JS enhancements; without JS, Enter is the commit gesture.

### JavaScript change — `courses/static/courses/js/builder.js`

All handlers are **delegated on `root`** using bubbling event types (`focusin` / `focusout` /
`keydown`) with `e.target.closest(".tree__title")`, exactly like the existing inline-add flow at
`builder.js:367-379`. This is mandatory, not stylistic: `applyFragment` replaces whole scope `<ol>`s
on every op, so a listener bound directly to an input would die at the first swap and inline renaming
would silently stop working for the swapped rows.

1. **Selection moves from `click` to `focusin`.** The existing handler at line 190 calls
   `e.preventDefault()` on `[data-select]`; on a text input that suppresses caret placement, so the
   click handler must no longer claim `[data-select]`. The panel-fetch body (`fetch(data-panel-url)`
   → `setPanel`) and `clearMoving()` are otherwise unchanged. Two guards come with the move:
   - **Debounce (~150ms) plus last-request-wins.** Selection previously required a deliberate click;
     on `focusin` a keyboard user tabbing through the tree would fire one panel fetch per row and
     thrash the panel, with responses free to land out of order. Each fetch takes a monotonically
     increasing request id and a response whose id is not the latest is discarded. 150ms is
     imperceptible for a click.
   - **A suppression flag around programmatic refocus** (step 5), so restoring focus does not
     re-trigger a redundant panel fetch and reset the panel's scroll.
2. **Commit via `form.requestSubmit()` — never `form.submit()`.** `form.submit()` does not fire the
   `submit` event, so `builder.js:135`'s interceptor would never run and the browser would perform a
   full-page POST, silently losing the entire fragment-swap design. `requestSubmit()` also runs
   constraint validation, which is what makes `required` produce the native bubble on Enter-with-empty.
   This mirrors `commitOrCancel` at `builder.js:347`.
3. **In-flight guard, reusing `form.dataset.submitting`.** After Enter the input keeps focus and its
   `defaultValue` still holds the old title until the swap lands, so a following click-away would see
   a dirty field and post a *second* time with a now-consumed token — producing a bogus "This changed
   elsewhere" notice on a completely natural gesture. The rename commit sets
   `form.dataset.submitting = "1"` before `requestSubmit()`; both the `focusout` and `keydown`
   handlers bail while it is set; the existing submit handler already clears it on completion
   (`builder.js:181`, `:185`).
4. **Blur commit uses the add-flow's deferral pattern.** `focusout` schedules the commit via
   `setTimeout(…, 120)` and only proceeds `if (form.isConnected && !form.contains(document.activeElement))`
   — copied from `builder.js:374-379`. This is what resolves the blur-vs-click race: the click that
   caused the blur (another row's title, this row's Duplicate button, a Move/Delete/Export link) gets
   to run first, and a commit is skipped entirely if the swap already removed the form. A link
   navigation is allowed to abort an in-flight commit — the rename is lost, matching how every other
   in-flight builder fetch behaves on navigation.
5. **Commit rules.** Compare and submit `input.value.trim()`, matching the add flow's
   `t.value.trim()` at `builder.js:342`. `ContentNode.full_clean()` does not strip `CharField`s, so
   without this a trailing space would persist a title that renders identically but matches no
   fixture or test locator. Post only when the trimmed value differs from `defaultValue`; on blur,
   an empty trimmed value reverts instead of posting.
6. **Escape reverts.** `input.value = input.defaultValue`, then blur; the deferred blur handler then
   sees a clean field and does not post.
7. **Focus restoration after an Enter commit.** After a successful swap, re-query
   `[data-node="<pk>"] .tree__title` and focus it with the caret **at the end** of the text, under the
   step-1 suppression flag. A blur commit needs no restoration — focus has legitimately moved on.
8. **Keep the `title` tooltip in sync.** An `input` handler mirrors `input.value` into the element's
   `title` attribute, so the tooltip never disagrees with the visible text while editing or after a
   rejected rename.
9. **No panel refresh.** The submit handler's panel refresh is gated by
   `var inPanel = panel.contains(form)` (`builder.js:141`, gating the call at `:171`). A tree-row
   rename form is not in the panel, so no refresh runs — correct, since the tree swap already
   re-renders the row with a fresh token. The panel *heading* keeps the old title until the node is
   reselected; an accepted cosmetic lag, recorded so it is not mistaken for a bug.

### Panel change — `templates/courses/manage/_node_panel.html`

The `_rename_form.html` include is removed, leaving a heading-only panel for non-unit nodes. The panel
is kept (rather than suppressing panel loading for non-units) because it preserves the selection
feedback and costs nothing.

`_unit_panel.html` is **not** changed: it stays valuable (type/obligatory summary, element list,
`+ Add element`, `Open editor →`).

**`templates/courses/manage/_rename_form.html` is deleted.** `_node_panel.html:4` is its only
consumer anywhere in the repo — `editor/_unit_settings.html` carries its own form markup rather than
including it — so it becomes dead code. Its `Title` and `Rename` msgids must be **removed** from both
`locale/en` and `locale/pl` `.po` catalogs, not left as obsolete `#~` entries, which the repo's
catalog tests reject.

### Styling — `courses/static/courses/css/builder.css`

`.tree__title` (line 38) currently styles a `<button>`. Moving to an `<input>` breaks two things that
must be handled explicitly:

- **Specificity.** `core/static/core/css/app.css:136` sets
  `input[type=text], … { width: 100%; padding: …; background: var(--surface-sunken); border: 1px solid var(--border-strong); border-radius: … }`.
  That selector is specificity (0,1,1); a bare `.tree__title` is (0,1,0), so the global rule wins
  regardless of file order and every row would render as a bordered, sunken-filled box — precisely the
  "wall of input boxes" this design forbids. The rule must therefore be written at higher specificity
  (`input.tree__title`) and must explicitly neutralise `background`, `border`, `border-radius` and
  `padding` from that global rule.
- **Font.** An `<input>` does not inherit `font-family`/`font-size` from its ancestors; it falls back
  to the UA default (~13.33px Arial). The current button picks its font up from button-targeting rules
  that do not apply to inputs. `font: inherit` is therefore **required**, or every tree label silently
  changes typeface and size.

Concretely:

- `.tree__rename` (the form) becomes the flex item: `flex: 1; min-width: 0; display: flex;`.
- `input.tree__title` keeps `width: 100%; min-width: 0; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; text-align: left; color: var(--text-primary);` and adds `font: inherit;
  background: none; border: 0; border-radius: 0; padding: 0; cursor: text;`.
- Hover and focus states: a subtle border on `:hover`, the standard focus ring on `:focus`.
- Visual verification: Playwright screenshots in light **and** dark mode before shipping.

## Data flow

Successful rename (JS path):

1. Author clicks a row title → `focusin` on `[data-select]` → debounced, last-request-wins
   `fetch(data-panel-url)` → panel swaps.
2. Author types, presses Enter (or clicks away and the 120ms deferral elapses) → trimmed-dirty check
   passes → `form.dataset.submitting = "1"` → `requestSubmit()` → `builder.js`'s submit handler posts
   `node`, `token`, `title`, CSRF to `courses:manage_node_rename`.
3. `node_rename` → `builder_svc.rename_node` → `_check_token` → `full_clean()` →
   `save(update_fields=["updated", "title"])`.
4. Response 200 with the parent-scope fragment (the whole tree pane when the node is top-level) →
   `applyFragment` swaps it → the row renders the new title with a **fresh token**;
   `dataset.submitting` is cleared.
5. If the commit came from Enter, focus is restored by `data-node` lookup, caret at end, with the
   selection fetch suppressed.

## Error handling

| Situation | Behaviour |
|---|---|
| Enter on an empty field | `required` + `requestSubmit()` → native constraint-validation bubble. Nothing posted. |
| Blur on an empty / whitespace-only field | Treated as cancel: revert to the stored title, nothing posted. |
| Trailing/leading whitespace | Trimmed before the dirty check and before posting, so `"Unit 1 "` never persists. |
| Over-length or otherwise invalid title | `full_clean()` → `ValidationError` → 422 + `_op_error.html` → existing `notice()`. Typed text retained; token unchanged, so a corrected re-submit succeeds. |
| Stale token (node changed elsewhere) | `ConflictError` → 409 → `_conflict_scope` fragment + "This changed elsewhere — reloaded to the latest." Existing path; the swapped row carries a fresh token. |
| Enter immediately followed by click-away | `dataset.submitting` guard suppresses the second commit — exactly one POST. |
| Blur caused by clicking this row's Duplicate/Delete/Move control | The 120ms deferral lets that click run first; `isConnected` / `activeElement` checks skip a commit whose form is already gone. |
| Blur caused by a link navigation | The in-flight commit may be aborted by the navigation and the edit lost — same as every other in-flight builder fetch. |
| Node deleted elsewhere | `ConflictError` → 409 path; the row disappears from the swapped scope. |
| Network failure | Existing `catch` → "Network error — please try again." |
| Uncommitted typing clobbered by an unrelated op | A drag/reorder that re-renders the same scope discards uncommitted text. **Accepted**, identical to the panel form's behaviour today. |
| No JavaScript | Enter submits natively; `node_rename` redirects back to the builder. |

## Testing

Every test below is **falsified before being accepted**: break the thing it guards and require RED
first (a passing test that never fails proves nothing).

**Django template/view tests**

- A tree row for each of part / chapter / section / **unit** renders an editable title form
  (`data-op="rename"`, hidden `node` + `token`, `input[name=title]` with the current value,
  `required`, `maxlength="200"`). The unit case is the regression this change exists to prevent.
- The input's accessible name is **row-specific** (contains the node's own title), not a bare "Title".
- Posting a title-only rename for a **unit** succeeds and leaves `unit_type`, `obligatory` and
  `html_seed_js` untouched — `rename_node`'s `_UNSET` handling is load-bearing, so guard it rather
  than assume it.
- **No-JS path:** POST the tree-row form shape *without* `X-Requested-With`; assert 302 to the builder
  and the persisted title. Also assert the rendered row is a real `<form method="post" action=…>`.
- **409 path from a tree row:** POST with a stale token; assert 409 and the `_conflict_scope`
  fragment. The token's *source* changes in this design (from a panel form refreshed by
  `refreshPanel` to a tree row refreshed only by the `[data-scope]` swap), which is exactly the
  staleness class the comment at `builder.js:117-122` was written about, so it must be guarded.
- **Whitespace-only title** is rejected (or reverted, per the interaction rules) rather than persisted.
- `_node_panel.html` no longer renders a rename form, and `_rename_form.html` no longer exists.
- `tests/test_tree_badge.py:23` matches `<button class="tree__title"[^>]*\btitle="([^"]*)"`. Retarget
  it to `<input class="tree__title"[^>]*\btitle="([^"]*)"`, still asserting the tooltip carries the
  node title.

**CSS tests** (`tests/test_builder_styles.py`)

- The existing ellipsis / `min-width: 0` / `nowrap` assertions (lines 34-41) must keep passing against
  the input rule.
- New: `.tree__rename` carries `min-width: 0` — it is now the flex item that would otherwise blow out
  the row.
- New: the input rule carries `font: inherit` and explicitly resets `background` / `border` /
  `padding`, at a selector specific enough to beat `input[type=text]` from `app.css`. This is the
  guard for the two failure modes named in Styling above.

**End-to-end (real browser, real gestures)**

Drive the actual UI — never `page.evaluate` shortcuts, which ship broken UX green.

- Click a **unit** title, type, press Enter → the tree label updates *and* the DB value changes.
- Same for a **chapter**, proving the interaction is kind-agnostic.
- **Blur commits:** type, then click elsewhere → saved.
- **Escape reverts:** type, press Escape → field shows the original, nothing posted.
- **Unchanged field does not post:** focus and blur without typing → no request, no `updated` bump.
- **Enter-then-blur posts exactly once** — the `dataset.submitting` guard; assert a single request and
  no conflict notice.
- **Commit by clicking another control on the same row** (Duplicate): assert the rename persisted
  *and* the duplicate succeeded without a spurious conflict notice — the C6 race, end to end.
- **Keyboard tab order:** tabbing from a row title reaches the next control, not a hidden "Rename"
  button.
- **Top-level rename preserves document scroll** in a long course, guarding the whole-tree-swap
  invariant asserted in "Scope of the returned fragment".
- `tests/test_e2e_builder_tree_layout.py` locates `.tree__title` with `has_text=` in seven places
  (lines 93, 107, 183, 205, 283, 297, 330). An `<input>` has no text content, so every one of those
  must move to a value-based locator.

**Verification before shipping**

- Full test suite green via `uv run pytest` (bare `pytest` / `ruff` / `python` are not on PATH).
- `uv run ruff check` and `uv run ruff format --check`.
- **i18n catalog tests**, since this change adds `{% trans %}` / `{% blocktrans %}` strings in a new
  location and deletes `_rename_form.html`: run `makemessages`, update both `en` and `pl` `.po`
  files, and **delete** removed msgids rather than leaving them as obsolete `#~` entries.
- Light and dark Playwright screenshots of the builder tree at rest, on hover, and focused.
- Because this worktree runs concurrently with others, it needs its **own `DATABASE_URL`** to avoid
  colliding on the shared Postgres `test_libli` database.
