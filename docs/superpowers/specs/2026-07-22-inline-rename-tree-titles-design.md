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
- **Enter on an empty *or whitespace-only* field** → the handler writes the trimmed value back first,
  so the field is empty when `requestSubmit()` runs; `required` then fails constraint validation and
  the browser shows its native "fill in this field" bubble. Nothing is posted.
- **Server-rejected title** (over `max_length`, or anything reaching the no-JS path) → see the error
  table; the JS path retains typed text and the row's token, so a corrected re-submit succeeds.
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

The change is essentially a **relocation of the existing rename form**. It needs one small backend
addition (title stripping, below); everything else reuses the existing plumbing unchanged.

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

### The one backend change — strip the title in `rename_node`

`ContentNode.title` is `models.CharField(max_length=200)` (`models.py:196`) and `ContentNode.clean()`
(`models.py:235`) validates only parent/kind/unit_type. `full_clean()` rejects `""`, but `"   "` is
**not** in Django's `EMPTY_VALUES`, so a whitespace-only title currently validates and persists.
Client-side trimming cannot fix this, because the no-JS path posts whatever was typed.

`rename_node` therefore strips the incoming title before assigning it (only when `title is not
_UNSET`, so the type-only toggle is unaffected). A whitespace-only title then becomes `""` and
`full_clean()` rejects it on **every** path — JS, no-JS, and the editor settings form alike. This also
makes the client-side trim a UX nicety rather than the sole guarantee, which is the right division of
responsibility.

### Scope of the returned fragment

`node_rename` returns `_render_scope(request, course, _scope_ref(node.parent_id))`. Note that
`_scope_ref(None)` returns `"top"` (`views_manage.py:223`), so renaming a **top-level** node
re-renders the *entire* tree pane, not just a subtree. Two consequences the JS must respect:

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
         aria-label="{% blocktrans with kind=node.get_kind_display %}Title of {{ kind }}{% endblocktrans %}"
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
- **`maxlength="200"`** mirrors the model field, so over-length input is prevented client-side instead
  of costing a 422 round trip. `required` is what makes Enter-on-empty fail constraint validation
  rather than post a blank title.
- **`autocomplete="off"`** stops browser autofill dropdowns over tree rows. **`spellcheck="false"`**
  stops red squiggles across every row at rest; the tradeoff — no spellcheck while actively editing a
  prose title either — is **accepted** rather than fixed with focus-time toggling, which would add a
  handler for marginal benefit.
- **The accessible name is the node's *kind*, not its title** (e.g. "Title of Chapter"). A text
  input's *value* is announced alongside its name, so the value already distinguishes rows; embedding
  the server-rendered title in `aria-label` instead would go stale the moment the author types (and
  stay stale after a 422), which is exactly the drift the tooltip sync below exists to prevent. Note
  `aria-label` overrides `title` for the accessible name; `title` is retained purely as the hover
  tooltip for truncated labels.
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

**All panel writes must route through `setPanel()`.** `tests/test_builder_js_invariants.py` asserts
there is exactly **one** `panel.innerHTML =` assignment in the file and that it lives inside
`setPanel` (which resets `scrollTop`). The focusin rewrite touches both the success and `.catch`
branches of the panel fetch; inlining either write turns that test red.

1. **Selection moves from `click` to `focusin`.** The existing handler at line 190 calls
   `e.preventDefault()` on `[data-select]`; on a text input that suppresses caret placement, so the
   click handler must no longer claim `[data-select]`. Two guards come with the move:
   - **Trailing 150ms debounce plus last-request-wins.** Selection previously required a deliberate
     click; on `focusin` a keyboard user tabbing through the tree would fire one panel fetch per row
     and thrash the panel, with responses free to land out of order. The debounce is **trailing**: the
     timer restarts on each `focusin` and the fetch is issued only after focus settles for 150ms, so
     tabbing through ten rows issues one fetch, not ten. A `focusout` that leaves the tree entirely
     cancels the pending timer. Each fetch also carries a monotonically increasing request id, and a
     response whose id is not the latest is discarded.
   - **A suppression flag around programmatic refocus** (step 8), so restoring focus does not
     re-trigger a redundant panel fetch and reset the panel's scroll.
2. **Commit via `form.requestSubmit()` — never `form.submit()`.** `form.submit()` does not fire the
   `submit` event, so `builder.js:135`'s interceptor would never run and the browser would perform a
   full-page POST, silently losing the entire fragment-swap design. `requestSubmit()` also runs
   constraint validation, which is what makes `required` produce the native bubble on
   Enter-with-empty. This mirrors `commitOrCancel` at `builder.js:347`.
3. **The Enter branch must call `e.preventDefault()`.** A text input in a form with a submit button
   performs *native implicit submission* on Enter. Without cancelling the key's default action, the
   interceptor would fire once for the programmatic `requestSubmit()` and again for the implicit
   submit — two POSTs, the second with a consumed token, producing a spurious 409. The add flow does
   this at `builder.js:370`; it is required here for the same reason.
4. **Trim by writing back to the input, not to a local variable.** The interceptor builds
   `new FormData(form)` (`builder.js:142`), which reads the input's **live** value — so trimming into
   a local would leave the untrimmed string in the POST body. The handler must assign
   `input.value = input.value.trim()` *before* calling `requestSubmit()`. (The server-side strip is
   the real guarantee; this keeps the field and the request consistent with what is persisted.)
5. **Dirty check compares trimmed against trimmed:**
   `input.value.trim() !== input.defaultValue.trim()`. Comparing a trimmed value against a raw
   `defaultValue` would make any legacy row whose stored title has stray whitespace post a rename on a
   bare focus-and-blur, violating the "unchanged field never posts" rule.
6. **In-flight guard, reusing `form.dataset.submitting`.** After Enter the input keeps focus and its
   `defaultValue` still holds the old title until the swap lands, so a following click-away would see
   a dirty field and post a *second* time with a now-consumed token. The rename commit sets
   `form.dataset.submitting = "1"` before `requestSubmit()`; both the `focusout` and `keydown`
   handlers bail while it is set; the existing submit handler already clears it on completion
   (`builder.js:181`, `:185`).
7. **Blur commits synchronously, and the rename wins its row.** This is the deliberate resolution of
   the blur-versus-click race, and it replaces any timer-based deferral: a `setTimeout` would make the
   outcome depend on whether another op's `fetch` round-trip beat the timer — a race with no
   deterministic winner and a guaranteed-flaky e2e.
   - On `focusout` of a dirty `.tree__title`, the commit is dispatched **immediately** (no deferral).
     This is safe here because the handler only dispatches a `fetch`; unlike the add flow's
     `closeAdd`, it removes nothing from the DOM synchronously, so the in-progress click still lands.
   - The row is marked `data-rename-pending` for the duration. While that attribute is present, the
     delegated submit handler and the `[data-move]` / `[data-select]` click handlers **ignore events
     originating inside that row**, and clicks on its `<a>` controls (Delete, Export) are
     `preventDefault`ed. The attribute vanishes with the fragment swap.
   - **Consequence, accepted and specified:** clicking a same-row control (Duplicate, Delete, Move,
     Export) while the title is dirty commits the rename and **drops that control's action**. The
     alternative — letting both fire — cannot work, because both ops carry the same row token, so
     whichever lands second necessarily 409s. Dropping it deterministically is better than a coin
     flip. The row re-renders with the new title and the author can click the control again.
8. **Focus restoration after a commit.** The swap destroys the input, so restoration always re-queries
   by `data-node` after `applyFragment`, under the step-1 suppression flag:
   - **Enter commit** → refocus the renamed row's own input, caret at the end.
   - **Blur commit whose `focusout` `relatedTarget` was another `.tree__title`** → refocus *that*
     row's input instead. Without this, the natural "rename row A, click row B to rename it next"
     gesture silently drops focus to `<body>` when A's response replaces the shared parent scope (or
     the whole tree, for top-level nodes). Record the target row's `data-node` at commit time.
   - **Blur to anywhere else** → no restoration; focus has legitimately left the tree.
9. **Escape reverts.** `input.value = input.defaultValue`, then blur; the blur handler then sees a
   clean field and does not post.
10. **Keep the `title` tooltip in sync.** An `input` handler mirrors `input.value` into the element's
    `title` attribute, so the tooltip never disagrees with the visible text while editing or after a
    rejected rename. (`aria-label` is kind-based and static, so it needs no syncing — see the markup
    notes.)
11. **No panel refresh.** The submit handler's panel refresh is gated by
    `var inPanel = panel.contains(form)` (`builder.js:141`, gating the call at `:171`). A tree-row
    rename form is not in the panel, so no refresh runs — correct, since the tree swap already
    re-renders the row with a fresh token. The panel *heading* keeps the old title until the node is
    reselected; an accepted cosmetic lag, recorded so it is not mistaken for a bug.
12. **Accepted side effect:** `clearMoving()` now runs on keyboard focus rather than only on a
    deliberate click, so Tab-traversing the tree while a Move picker is open clears the `.moving`
    highlight. Harmless and not worth extra logic to avoid.

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

**Accepted knock-on:** the drop handler at `builder.js:304` clears the panel only
`if (panel.querySelector("form[data-op]"))`. With the panel's rename form gone, a non-unit node's
panel no longer matches, so a drag no longer resets it. That is intended and harmless — the panel now
holds no token-bearing form that could go stale.

### Styling — `courses/static/courses/css/builder.css`

`.tree__title` (line 38) currently styles a `<button>`. Moving to an `<input>` breaks two things that
must be handled explicitly:

- **Specificity.** `core/static/core/css/app.css:136` sets
  `input[type=text], … { width: 100%; padding: …; background: var(--surface-sunken); border: 1px solid var(--border-strong); border-radius: … }`.
  That selector is specificity (0,1,1); a bare `.tree__title` is (0,1,0), so the global rule wins
  regardless of file order and every row would render as a bordered, sunken-filled box — precisely the
  "wall of input boxes" this design forbids.
- **Font.** An `<input>` does not inherit `font-family`/`font-size` from its ancestors; it falls back
  to the UA default (~13.33px Arial). The current button picks its font up from button-targeting
  rules that do not apply to inputs. `font: inherit` is therefore **required**, or every tree label
  silently changes typeface and size.

Concretely:

- The selector must be written **literally as `input.tree__title { … }`** — single, ungrouped, with
  the class immediately before the brace. `tests/test_builder_styles.py` matches
  `\.tree__title\s*\{[^}]*…`, which survives this form but breaks on a grouped or descendant selector.
  This is a mechanical constraint, not a style preference.
- `input.tree__title` keeps `width: 100%; min-width: 0; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; text-align: left; color: var(--text-primary);` and adds `font: inherit;
  background: none; border: 0; border-radius: 0; padding: 0; cursor: text;` — the last five
  neutralising the global form-control rule.
- `.tree__rename` (the form) becomes the flex item: `flex: 1; min-width: 0; display: flex;
  margin: 0;`. The `margin: 0` is required — a `<form>` is a block element that UA stylesheets give a
  default margin, inside a row with only `padding: 3px 4px`. The sibling `.tree__inline`
  (`builder.css:44`) sets `margin: 0` for exactly this reason.
- Hover and focus states: a subtle border on `:hover`, the standard focus ring on `:focus`.
- Visual verification: Playwright screenshots in light **and** dark mode before shipping.

## Data flow

Successful rename (JS path):

1. Author clicks a row title → `focusin` on `[data-select]` → trailing-debounced, last-request-wins
   `fetch(data-panel-url)` → `setPanel`.
2. Author types, presses Enter (`preventDefault`) or clicks away → trimmed-dirty check passes →
   `input.value` is trimmed in place → `form.dataset.submitting = "1"`, row marked
   `data-rename-pending` → `requestSubmit()` → the submit handler posts `node`, `token`, `title`,
   CSRF to `courses:manage_node_rename`.
3. `node_rename` → `builder_svc.rename_node` (strips the title) → `_check_token` → `full_clean()` →
   `save(update_fields=["updated", "title"])`.
4. Response 200 with the parent-scope fragment (the whole tree pane when the node is top-level) →
   `applyFragment` swaps it → the row renders the new title with a **fresh token**;
   `dataset.submitting` and `data-rename-pending` are gone with the replaced DOM.
5. Focus is restored by `data-node` lookup under the suppression flag — to the renamed row (Enter) or
   to the row whose title was clicked (blur), per JS step 8.

## Error handling

| Situation | Behaviour |
|---|---|
| Enter on an empty or whitespace-only field | Trimmed write-back makes it empty; `required` + `requestSubmit()` → native constraint-validation bubble. Nothing posted. |
| Blur on an empty / whitespace-only field | Treated as cancel: revert to the stored title, nothing posted. |
| Whitespace-only title reaching the server (no-JS, or editor settings form) | `rename_node` strips it to `""`; `full_clean()` rejects it. |
| Leading/trailing whitespace | Trimmed client-side into the field before posting, and stripped server-side, so `"Unit 1 "` never persists on any path. |
| Over-length or invalid title, **JS path** | 422 + `_op_error.html` → existing `notice()`. Typed text retained; token unchanged, so a corrected re-submit succeeds. |
| Over-length or invalid title, **no-JS path** | `node_rename` routes to `_builder_with_notice(..., status=422)` (`views_manage.py:331-340`) — a full builder page with an inline notice. The tree re-renders from the DB, so **typed text is not retained**. This is the path over-length input actually reaches, since `maxlength` is client-side only. |
| Stale token (node changed elsewhere) | `ConflictError` → 409 → `_conflict_scope` fragment + "This changed elsewhere — reloaded to the latest." Existing path; the swapped row carries a fresh token. |
| Enter immediately followed by click-away | `dataset.submitting` guard suppresses the second commit — exactly one POST. |
| Blur caused by clicking this row's Duplicate or Move control | The rename commits; that control's op is suppressed via `data-rename-pending` (JS step 7). No 409 is possible. |
| Blur caused by clicking this row's Delete or Export link | Same suppression, applied by `preventDefault`ing the navigation — these are plain `<a href>`s (`_tree_node.html:18,27`) with no JS interception of their own. |
| Blur caused by clicking another row's title | The rename commits and focus is restored to that other row's input after the swap (JS step 8). |
| Blur caused by a navigation away from the builder | The in-flight commit may be aborted by the navigation and the edit lost — same as every other in-flight builder fetch. |
| Node deleted elsewhere | `ConflictError` → 409 path; the row disappears from the swapped scope. |
| Network failure | Existing `catch` → "Network error — please try again." |
| Uncommitted typing clobbered by an unrelated op | A drag/reorder that re-renders the same scope discards uncommitted text. **Accepted**, identical to the panel form's behaviour today. |
| No JavaScript | Enter submits natively; `node_rename` redirects back to the builder. |

## Testing

Every test below is **falsified before being accepted**: break the thing it guards and require RED
first (a passing test that never fails proves nothing).

**Backend tests**

- `rename_node` strips the title: `"  Fractions  "` persists as `"Fractions"`, and a whitespace-only
  title raises `ValidationError` rather than persisting. Cover the no-JS POST path too, since that is
  where an unstripped title would otherwise reach the DB.
- A title-only rename of a **unit** succeeds and leaves `unit_type`, `obligatory` and `html_seed_js`
  untouched — `rename_node`'s `_UNSET` handling is load-bearing, so guard it rather than assume it.
  Include the type-only toggle, to prove stripping did not disturb the `_UNSET` branch.

**Django template/view tests**

- A tree row for each of part / chapter / section / **unit** renders an editable title form
  (`data-op="rename"`, hidden `node` + `token`, `input[name=title]` with the current value,
  `required`, `maxlength="200"`). The unit case is the regression this change exists to prevent.
- The input carries a kind-based `aria-label` and a `title` tooltip equal to the node title.
- **No-JS path:** POST the tree-row form shape *without* `X-Requested-With`; assert 302 to the builder
  and the persisted title. Also assert the rendered row is a real `<form method="post" action=…>`.
- **409 path from a tree row:** POST with a stale token; assert 409 and the `_conflict_scope`
  fragment. The token's *source* changes in this design (from a panel form refreshed by
  `refreshPanel` to a tree row refreshed only by the `[data-scope]` swap), which is exactly the
  staleness class the comment at `builder.js:117-122` was written about, so it must be guarded.
- `_node_panel.html` no longer renders a rename form, and `_rename_form.html` no longer exists.
- `tests/test_tree_badge.py:23` matches `<button class="tree__title"[^>]*\btitle="([^"]*)"`. Retarget
  it to `<input class="tree__title"[^>]*\btitle="([^"]*)"`, still asserting the tooltip carries the
  node title.

**CSS tests** (`tests/test_builder_styles.py`)

- The existing ellipsis / `min-width: 0` / `nowrap` assertions (lines 34-41) must keep passing against
  the `input.tree__title` rule.
- New: `.tree__rename` carries `min-width: 0` and `margin: 0`.
- New: the input rule carries `font: inherit` and explicitly resets `background` / `border` /
  `padding`, at a selector specific enough to beat `input[type=text]` from `app.css`. This is the
  guard for the two failure modes named in Styling above.

**JS invariant test** (`tests/test_builder_js_invariants.py`)

- Must stay green: exactly one `panel.innerHTML =` assignment, inside `setPanel`.

**End-to-end (real browser, real gestures)**

Drive the actual UI — never `page.evaluate` shortcuts, which ship broken UX green.

- Click a **unit** title, type, press Enter → the tree label updates *and* the DB value changes.
- Same for a **chapter**, proving the interaction is kind-agnostic.
- **Blur commits:** type, then click outside the tree → saved.
- **Escape reverts:** type, press Escape → field shows the original, nothing posted.
- **Unchanged field does not post:** focus and blur without typing → **no POST to
  `manage_node_rename`** (a debounced panel GET is expected and must not be counted), and no
  `updated` bump.
- **Plain Enter posts exactly once** — guards the `preventDefault` requirement against native
  implicit submission.
- **Enter-then-blur posts exactly once** — guards the `dataset.submitting` flag.
- **Trailing whitespace:** type `"Fractions "` and commit through the real JS path → `"Fractions"`
  persists. Guards the write-back-before-`requestSubmit()` requirement, which a local-variable trim
  would silently fail.
- **Same-row control while dirty:** type, then click Duplicate → the rename persisted, **no duplicate
  was created**, and no conflict notice appeared. Guards the `data-rename-pending` suppression.
- **Rename A, then click B's title:** A persists and focus lands in B's input after the swap.
- **Keyboard tab order:** tabbing from a row title reaches the next control, not a hidden "Rename"
  button.
- **Top-level rename preserves document scroll** in a long course, guarding the whole-tree-swap
  invariant asserted in "Scope of the returned fragment".
- `tests/test_e2e_builder_tree_layout.py` locates `.tree__title` with `has_text=` in seven places
  (lines 93, 107, 183, 205, 283, 297, 330). An `<input>` has no text content, so every one of those
  must move to a value-based locator. Check whether the 150ms trailing debounce requires those
  panel-state assertions to gain explicit waits.

**Verification before shipping**

- Full test suite green via `uv run pytest` (bare `pytest` / `ruff` / `python` are not on PATH).
- `uv run ruff check` and `uv run ruff format --check`.
- **i18n catalog tests**, since this change adds `{% trans %}` / `{% blocktrans %}` strings in a new
  location and deletes `_rename_form.html`: run `makemessages`, update both `en` and `pl` `.po`
  files, and **delete** removed msgids rather than leaving them as obsolete `#~` entries.
- Light and dark Playwright screenshots of the builder tree at rest, on hover, and focused.
- Because this worktree runs concurrently with others, it needs its **own `DATABASE_URL`** to avoid
  colliding on the shared Postgres `test_libli` database.
