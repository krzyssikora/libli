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
  so the field is empty when validity is checked; `required` then fails and the browser shows its
  native "fill in this field" bubble. Nothing is posted **and no in-flight state is set** (see JS
  step 4 — this is what stops the row wedging).
- **Server-rejected title** (over `max_length`, or anything reaching the no-JS path) → see the error
  table; the JS path retains typed text, focus, and the row's token, so a corrected re-submit
  succeeds.
- **Resting appearance:** the field looks like plain text — no border, no background — so the tree
  does not become a wall of input boxes. A subtle border appears on hover and a real focus ring on
  focus, both **layout-neutral** (see Styling). Ellipsis truncation is preserved.

**Touch devices — accepted cost.** Because selecting a node now focuses a text input, tapping a row
on a tablet or phone raises the on-screen keyboard even when the author only meant to inspect the
node's panel. A `readonly`-until-second-tap scheme would avoid this, and is **deliberately rejected**:
it reintroduces the two-gesture "edit mode" this design exists to remove, and the builder is a
desktop-first authoring surface (its two-pane layout already collapses to a stacked fallback below
720px). The cost is accepted and recorded here as a decision, not an omission.

## Architecture / components

The change is essentially a **relocation of the existing rename form**. It needs one small backend
addition (title normalization, below); everything else reuses the existing plumbing unchanged.

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

### The one backend change — normalize the title for *all* writers

`ContentNode.title` is `models.CharField(max_length=200)` (`models.py:196`) and `ContentNode.clean()`
(`models.py:235`) validates only parent/kind/unit_type. `full_clean()` rejects `""`, but `"   "` is
**not** in Django's `EMPTY_VALUES`, so a whitespace-only title currently validates and persists.
Client-side trimming cannot fix this, because the no-JS path posts whatever was typed.

Add a small shared helper in `courses/builder.py` that strips an incoming title, and call it from
**both** `rename_node` (only when `title is not _UNSET`, so the type-only toggle is unaffected) **and**
`add_node` (`builder.py:146-156`, which currently assigns `title` unstripped). A whitespace-only title
then becomes `""` and `full_clean()` rejects it on every path.

Normalizing on the add path too is deliberate: the inline-add flow (`builder.js:343-347`) only *tests*
`t.value.trim()` while submitting the raw value, so `"  Foo  "` currently enters the DB at creation
time. Fixing only `rename_node` would leave the tree seeding exactly the "stored title with stray
whitespace" rows that the trimmed-vs-trimmed dirty check (JS step 6) exists to tolerate.

The normalization deliberately lives in these service functions rather than `ContentNode.clean()`:
`full_clean()` runs `clean_fields()` (which enforces `blank`) *before* `clean()`, so stripping inside
`clean()` would let `"   "` pass the blank check and then persist as `""`.

**Out of scope:** course import/transfer paths, which write titles from an external payload. They are
unchanged, and a note in the helper's docstring records that they bypass it.

### Scope of the returned fragment

`node_rename` returns `_render_scope(request, course, _scope_ref(node.parent_id))`. Note that
`_scope_ref(None)` returns `"top"` (`views_manage.py:223`), so renaming a **top-level** node
re-renders the *entire* tree pane, not just a subtree. Two consequences the JS must respect:

- **Focus.** The input element is destroyed by the swap. Focus restoration must therefore re-query
  the DOM by `data-node` *after* `applyFragment` returns — never hold a reference to the old element.
- **Other rows' uncommitted typing** in the replaced scope is discarded. Accepted; identical to how
  every other builder op behaves today.

**Scroll position is *not* at risk and needs no restoration code**, provided focus restoration uses
`preventScroll` (JS step 9). `.builder__panel` is the sticky, `overflow: hidden auto` scroll container
(`builder.css:15-16`); the tree itself sits in normal document flow. Replacing `[data-scope="top"]`
with a subtree of identical height — which a rename guarantees, since the row count and structure are
unchanged — leaves document scroll untouched. An e2e assertion guards this invariant; no
`scrollTop` save/restore should be written.

### Template change — `templates/courses/manage/_tree_node.html`

Line 12–13's title `<button>` becomes a small form wrapping a text input:

```html
<form class="tree__rename" method="post"
      action="{% url 'courses:manage_node_rename' slug=node.course.slug %}" data-op="rename">
  {% csrf_token %}
  <input type="hidden" name="node" value="{{ node.pk }}">
  <input type="hidden" name="token" value="{{ node.updated.isoformat }}">
  <input class="tree__title" type="text" name="title" value="{{ node.title }}"
         title="{{ node.title }}" aria-label="{% trans 'Title' %}"
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
  of costing a 422 round trip. `required` is what makes Enter-on-empty fail validity rather than post
  a blank title.
- **`autocomplete="off"`** stops browser autofill dropdowns over tree rows. **`spellcheck="false"`**
  stops red squiggles across every row at rest; the tradeoff — no spellcheck while actively editing a
  prose title either — is **accepted** rather than fixed with focus-time toggling, which would add a
  handler for marginal benefit.
- **The accessible name is a plain, kind-independent `Title`.** A text input's *value* is announced
  alongside its name, so the value already distinguishes rows, and the row's badge conveys the kind.
  Interpolating the kind (`"Title of {{ kind }}"`) was considered and rejected: Polish needs the
  genitive ("Tytuł rozdziału"), while `get_kind_display` supplies a nominative label, so the `pl`
  catalog could not produce a correct string by translating the frame alone. Interpolating the
  *title* was likewise rejected — it would go stale the moment the author types. Note `aria-label`
  overrides `title` for the accessible name; `title` is retained purely as the hover tooltip for
  truncated labels.
- **The submit button is `.visually-hidden` *and* `tabindex="-1"`.** The utility at
  `core/static/core/css/app.css:1167` uses the `clip` pattern, which keeps the element **focusable** —
  without `tabindex="-1"` every row would gain a second Tab stop, a serious keyboard regression in a
  long course. It exists only to guarantee a submit path for the no-JS case; Enter already submits, so
  removing it from the tab order costs nothing.

**Per-row markup cost — considered and measured.** Each row gains a `<form>`, a `{% csrf_token %}`
hidden input, two hidden inputs, a hidden submit button and a second `{% url %}` reversal. In this
repo courses reach ~800 units (the matematyka import loads 793), and the long-course navigation work
exists because tree size already matters, so this is not a free change: the CSRF token alone is ~64
bytes of value per row. The token is kept rather than dropped in favour of the cookie-reading `csrf()`
helper, because dropping it would break the no-JS path this design newly enables. Verification
therefore **measures** the builder page's transferred size and DOM node count for the largest
available fixture before and after, and records the delta in the PR (see Verification).

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

#### The in-flight gate

A single module-level `renameInFlight` object (or `null`) is the whole concurrency story. It replaces
any per-row attribute or timer-based deferral, and it exists because a rename commit and any other
tree op both carry the same row's token and both return a full server-rendered scope snapshot — so
letting them overlap yields either a guaranteed 409 or an out-of-order `applyFragment` that
re-instates the pre-op tree (a deleted row reappearing, a reorder visually undone).

While `renameInFlight` is set:

- the delegated submit handler ignores forms whose `data-op` is **not** `rename` (the rename's own
  submit must still be processed — it lives inside the same row, so a naive "ignore this row"
  rule would suppress the very request it is meant to send);
- `[data-move]` and `[data-select]` clicks, and clicks on the row's `<a>` controls (Delete, Export),
  are `preventDefault`ed and dropped;
- `dragstart` is ignored. Without this, grabbing the grip focuses it, which blurs the title and
  commits the rename, while the drop handler still posts the `node_token` it read from `data-updated`
  at `dragstart` time (`builder.js:223-224`) — a token the rename has just invalidated, i.e. a
  guaranteed 409 with the drag silently discarded.

**Consequence, accepted and specified:** interacting with any tree control while a title is dirty
commits the rename and **drops that control's action**. The alternative cannot work for the reasons
above. The tree re-renders with the new title and the author repeats the gesture.

`renameInFlight` is cleared in **every** completion branch — 200, 409, 422 and the `.catch` — mirroring
where `delete form.dataset.submitting` already happens (`builder.js:181`, `:185`). Clearing it only on
the fragment swap would leave the gate stuck after a 422 or a network error, permanently disabling
that row's controls and blocking the corrected re-submit the error table promises.

#### Handlers

1. **Selection moves from `click` to `focusin`.** The existing handler at line 190 calls
   `e.preventDefault()` on `[data-select]`; on a text input that suppresses caret placement, so the
   click handler must no longer claim `[data-select]`. Two guards come with the move:
   - **Pointer focus fetches immediately; keyboard focus is debounced.** A `pointerdown` on a row
     marks the next `focusin` as pointer-initiated, and pointer-initiated selection issues its panel
     fetch with no delay — the click-to-select gesture must not gain 150ms of latency, and a click
     followed quickly by a click into the panel must not cancel the fetch and leave the panel blank.
     Keyboard-initiated focus (no pointer mark) uses a **trailing 150ms** debounce, so tabbing across
     ten rows issues one fetch rather than ten.
   - **Last-request-wins.** Each fetch carries a monotonically increasing request id; a response whose
     id is not the latest is discarded, so out-of-order responses cannot leave the panel showing a row
     the author has already moved past.
   - **A suppression flag around programmatic refocus** (step 9), so restoring focus does not
     re-trigger a redundant panel fetch and reset the panel's scroll.
2. **Commit via `form.requestSubmit()` — never `form.submit()`.** `form.submit()` does not fire the
   `submit` event, so `builder.js:135`'s interceptor would never run and the browser would perform a
   full-page POST, silently losing the entire fragment-swap design. This mirrors `commitOrCancel` at
   `builder.js:347`.
3. **`Enter` is cancelled unconditionally.** The `keydown` handler calls `e.preventDefault()` for
   `Enter` on any `.tree__title` **before** any dirty / validity / in-flight check. A text input in a
   form with a submit button performs *native implicit submission*, so cancelling only on the commit
   path would mean: Enter on an unchanged title still posts (violating "unchanged never posts"), and
   Enter during an in-flight commit posts again with a consumed token — the exact 409 the gate exists
   to prevent. The add flow cancels the same way at `builder.js:370`.
4. **Validity is checked *before* any state is set.** The commit path calls `form.reportValidity()`
   (which surfaces the native bubble) and returns immediately if it is false, **without** setting
   `renameInFlight` or `dataset.submitting`. A failed `requestSubmit()` fires no `submit` event, so
   nothing would ever clear those flags — the row would be permanently unable to commit and would have
   all its controls suppressed. Order is therefore: cancel default → dirty check → trim write-back →
   validity → set flags → `requestSubmit()`.
5. **Trim by writing back to the input, not to a local variable.** The interceptor builds
   `new FormData(form)` (`builder.js:142`), which reads the input's **live** value — so trimming into
   a local would leave the untrimmed string in the POST body. Assign `input.value = input.value.trim()`
   before the validity check. (The server-side normalization is the real guarantee; this keeps the
   field and the request consistent with what is persisted.)
6. **Dirty check compares trimmed against trimmed:**
   `input.value.trim() !== input.defaultValue.trim()`. Comparing a trimmed value against a raw
   `defaultValue` would make any legacy row whose stored title has stray whitespace post a rename on a
   bare focus-and-blur, violating the "unchanged field never posts" rule.
7. **In-flight guard, reusing `form.dataset.submitting`.** After Enter the input keeps focus and its
   `defaultValue` still holds the old title until the swap lands, so a following click-away would see
   a dirty field and try to post a second time. Both the `focusout` and `keydown` handlers bail while
   it is set; the existing submit handler clears it on completion.
8. **Blur commits synchronously.** On `focusout` of a dirty `.tree__title` the commit is dispatched
   immediately, with no timer. This is safe because the handler only dispatches a `fetch`; unlike the
   add flow's `closeAdd`, it removes nothing from the DOM synchronously, so an in-progress click still
   lands (and is then dropped by the gate). A timer-based deferral was rejected: it would make the
   outcome depend on whether another op's round-trip beat the timer — a race with no deterministic
   winner and a guaranteed-flaky e2e.
9. **Focus restoration.** The swap destroys the input, so restoration always re-queries after
   `applyFragment`, using the selector `li.tree__row[data-node="<pk>"] > .tree__rowhead .tree__title`
   — the child combinator matters because a container row's `li[data-node]` also contains its
   descendant rows. All programmatic focus uses **`focus({ preventScroll: true })`**; without it the
   browser scrolls the freshly-created element into view, which is precisely the document-scroll jump
   the scroll invariant above asserts cannot happen.
   - **200, Enter commit** → refocus the renamed row's own input, caret at the end.
   - **200, blur commit whose `focusout` `relatedTarget` was another `.tree__title`** → refocus *that*
     row's input instead. Without this, the natural "rename row A, click row B to rename it next"
     gesture silently drops focus to `<body>` when A's response replaces the shared parent scope (or
     the whole tree, for top-level nodes). Record the target row's `data-node` at commit time.
   - **200, blur to anywhere else** → no restoration; focus has legitimately left the tree.
   - **409** → the scope is swapped and the typed title is discarded (the server's value wins).
     Restoration follows the same rule as 200, so focus lands in the renamed row's input showing the
     authoritative title, alongside the conflict notice — rather than dropping to `<body>`.
   - **422 and network error** → no swap occurs, so the input still exists: focus and typed text are
     left exactly as they are, and only `renameInFlight` / `dataset.submitting` are cleared. This is
     what makes the "corrected re-submit" promise real.
10. **Escape reverts.** `input.value = input.defaultValue`, then blur; the blur handler then sees a
    clean field and does not post.
11. **Keep the `title` tooltip in sync.** An `input` handler mirrors `input.value` into the element's
    `title` attribute, so the tooltip never disagrees with the visible text while editing or after a
    rejected rename. (`aria-label` is a static string, so it needs no syncing.)
12. **No panel refresh — and `refreshPanel` is deleted.** The submit handler's panel refresh is gated
    by `var inPanel = panel.contains(form)` (`builder.js:141`, gating the call at `:171`). A tree-row
    rename form is not in the panel, so no refresh would run. More than that: once the panel's rename
    form is gone, the *only* remaining panel form carrying `data-op` is the Move picker
    (`data-op="reparent"`), which takes the `setPanel(neutralPanel)` branch — so `refreshPanel()`
    becomes unreachable. Delete it, its `else` branch, and the now-obsolete comment at
    `builder.js:117-122`, rather than leaving dead code behind.
    The panel *heading* keeps the old title until the node is reselected; an accepted cosmetic lag,
    recorded so it is not mistaken for a bug.
13. **Accepted side effects.**
    - `clearMoving()` now runs on keyboard focus rather than only on a deliberate click, so
      Tab-traversing the tree while a Move picker is open clears the `.moving` highlight.
    - An open inline-add row schedules `commitOrCancel` 120ms after its own blur
      (`builder.js:373-379`). Clicking a title while an add row is open therefore lets that add commit
      land and swap the scope, discarding an in-progress title edit. This is the same accepted class
      as "uncommitted typing clobbered by an unrelated op" below; it is not worth cross-wiring the two
      flows to avoid.

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
`if (panel.querySelector("form[data-op]"))`. A non-unit node's detail panel now contains no form at
all, so a drag no longer resets it — intended and harmless. (The Move picker still carries
`data-op="reparent"`, so it still matches and is still cleared on drop.)

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
  background: none; border-radius: 0; padding: 0; cursor: text;` — neutralising the global
  form-control rule.
- **Hover and focus must be layout-neutral.** The row has only `padding: 3px 4px` (`builder.css:33`),
  so introducing a 1px border on hover to an element that has none at rest would shift the text and
  grow the row, making every row twitch as the pointer travels down a long tree. Instead the input
  carries `border: 1px solid transparent` at rest and only its *colour* changes on `:hover`; the
  focus ring uses `outline` / `box-shadow`, which do not participate in layout.
- `.tree__rename` (the form) becomes the flex item: `flex: 1; min-width: 0; display: flex;
  margin: 0;`. The `margin: 0` is required — a `<form>` is a block element that UA stylesheets give a
  default margin, inside a row with almost no slack. The sibling `.tree__inline` (`builder.css:44`)
  sets `margin: 0` for exactly this reason.
- Visual verification: Playwright screenshots in light **and** dark mode before shipping.

## Data flow

Successful rename (JS path):

1. Author clicks a row title → `pointerdown` marks the focus as pointer-initiated → `focusin` issues
   an immediate, last-request-wins `fetch(data-panel-url)` → `setPanel`.
2. Author types, then presses Enter (default cancelled unconditionally) or clicks away → dirty check
   passes → `input.value` trimmed in place → `form.reportValidity()` passes → `renameInFlight` and
   `form.dataset.submitting` are set → `requestSubmit()` → the submit handler posts `node`, `token`,
   `title`, CSRF to `courses:manage_node_rename`.
3. `node_rename` → `builder_svc.rename_node` (normalizes the title) → `_check_token` →
   `full_clean()` → `save(update_fields=["updated", "title"])`.
4. Response 200 with the parent-scope fragment (the whole tree pane when the node is top-level) →
   `applyFragment` swaps it → the row renders the new title with a **fresh token**; `renameInFlight`
   and `dataset.submitting` are cleared.
5. Focus is restored with `preventScroll` under the suppression flag — to the renamed row (Enter) or
   to the row whose title was clicked (blur), per JS step 9.

## Error handling

| Situation | Behaviour |
|---|---|
| Enter on an empty or whitespace-only field | Trimmed write-back makes it empty; `reportValidity()` fails → native bubble. Nothing posted, **no flags set**. |
| Blur on an empty / whitespace-only field | Treated as cancel: revert to the stored title, nothing posted. |
| Whitespace-only title reaching the server (no-JS, or editor settings form) | `rename_node` normalizes it to `""`; `full_clean()` rejects it. |
| Leading/trailing whitespace | Trimmed client-side into the field before posting, and stripped server-side on both the rename and add paths, so `"Unit 1 "` never persists. |
| Over-length or invalid title, **JS path** | 422 + `_op_error.html` → existing `notice()`. No swap: typed text, focus and token all survive, so a corrected re-submit succeeds. Flags are cleared. |
| Over-length or invalid title, **no-JS path** | `node_rename` routes to `_builder_with_notice(..., status=422)` (`views_manage.py:331-340`) — a full builder page with an inline notice. The tree re-renders from the DB, so **typed text is not retained**. This is the path over-length input actually reaches, since `maxlength` is client-side only. |
| Stale token (node changed elsewhere) | `ConflictError` → 409 → `_conflict_scope` fragment + "This changed elsewhere — reloaded to the latest." The typed title is discarded (server value wins) and focus is restored per JS step 9. |
| Enter immediately followed by click-away | `dataset.submitting` guard suppresses the second commit — exactly one POST. |
| Enter on an unchanged title | Default cancelled before the dirty check, so native implicit submission cannot fire — no POST. |
| Any tree control (Duplicate, Move, Delete, Export, drag) used while a title is dirty | The rename commits; the gate drops that control's action. No 409 is possible. |
| Blur caused by clicking another row's title | The rename commits and focus is restored to that other row's input after the swap. |
| Blur caused by a navigation away from the builder | The in-flight commit may be aborted by the navigation and the edit lost — same as every other in-flight builder fetch. |
| Node deleted elsewhere | `ConflictError` → 409 path; the row disappears from the swapped scope. |
| Network failure | Existing `catch` → "Network error — please try again."; flags cleared, no swap, typed text kept. |
| Uncommitted typing clobbered by an unrelated op | A drag/reorder/add-commit that re-renders the same scope discards uncommitted text. **Accepted**, identical to the panel form's behaviour today. |
| No JavaScript | Enter submits natively; `node_rename` redirects back to the builder. |

## Testing

Every test below is **falsified before being accepted**: break the thing it guards and require RED
first (a passing test that never fails proves nothing).

**Backend tests**

- The shared normalization helper strips titles on **both** paths: `rename_node("  Fractions  ")`
  persists `"Fractions"`, `add_node("  Foo  ")` persists `"Foo"`, and a whitespace-only title raises
  `ValidationError` rather than persisting. Cover the no-JS POST path too, since that is where an
  unstripped title would otherwise reach the DB.
- A title-only rename of a **unit** succeeds and leaves `unit_type`, `obligatory` and `html_seed_js`
  untouched — `rename_node`'s `_UNSET` handling is load-bearing, so guard it rather than assume it.
  Include the type-only toggle, to prove normalization did not disturb the `_UNSET` branch.

**Django template/view tests**

- A tree row for each of part / chapter / section / **unit** renders an editable title form
  (`data-op="rename"`, hidden `node` + `token`, `input[name=title]` with the current value,
  `required`, `maxlength="200"`). The unit case is the regression this change exists to prevent.
- The input carries `aria-label="Title"` and a `title` tooltip equal to the node title.
- **No-JS path:** POST the tree-row form shape *without* `X-Requested-With`; assert 302 to the builder
  and the persisted title. Also assert the rendered row is a real `<form method="post" action=…>`.
- **409 path from a tree row:** POST with a stale token; assert 409 and the `_conflict_scope`
  fragment. The token's *source* changes in this design (from a panel form to a tree row refreshed
  only by the `[data-scope]` swap), so it must be guarded directly.
- `_node_panel.html` no longer renders a rename form, and `_rename_form.html` no longer exists.
- `tests/test_tree_badge.py:23` matches `<button class="tree__title"[^>]*\btitle="([^"]*)"`. Retarget
  it to `<input class="tree__title"[^>]*\btitle="([^"]*)"`, still asserting the tooltip carries the
  node title.

**CSS tests** (`tests/test_builder_styles.py`)

- The existing ellipsis / `min-width: 0` / `nowrap` assertions (lines 34-41) must keep passing against
  the `input.tree__title` rule.
- New: `.tree__rename` carries `min-width: 0` and `margin: 0`.
- New: the input rule carries `font: inherit`, resets `background` / `padding`, and declares a
  `transparent` rest border (the layout-neutral hover guard), at a selector specific enough to beat
  `input[type=text]` from `app.css`.

**JS invariant test** (`tests/test_builder_js_invariants.py`)

- Must stay green: exactly one `panel.innerHTML =` assignment, inside `setPanel`.

**End-to-end (real browser, real gestures)**

Drive the actual UI — never `page.evaluate` shortcuts, which ship broken UX green.

- Click a **unit** title, type, press Enter → the tree label updates *and* the DB value changes.
- Same for a **chapter**, proving the interaction is kind-agnostic.
- **Blur commits:** type, then click outside the tree → saved.
- **Escape reverts:** type, press Escape → field shows the original, nothing posted.
- **Unchanged field does not post:** focus and blur without typing → **no POST to
  `manage_node_rename`** (a panel GET is expected and must not be counted), and no `updated` bump.
- **Enter on an unchanged title issues no POST** — guards the unconditional `preventDefault`.
- **Plain Enter posts exactly once**, and **Enter-then-blur posts exactly once**.
- **Enter on an empty field does not wedge the row:** clear the field, press Enter (native bubble),
  then type a valid title and press Enter → it commits. Guards the validity-before-flags ordering.
- **422 does not wedge the row:** force a rejected rename, then correct it and re-submit successfully
  without reloading. Guards clearing the gate outside the swap path.
- **Trailing whitespace:** type `"Fractions "` and commit through the real JS path → `"Fractions"`
  persists. Guards the write-back-before-`requestSubmit()` requirement, which a local-variable trim
  would silently fail.
- **Same-row control while dirty:** type, then click Duplicate → the rename persisted, **no duplicate
  was created**, and no conflict notice appeared. Guards the gate.
- **Cross-row op while dirty:** type in row A, then click Delete on row B → deterministic outcome per
  the gate (B's action dropped), with no resurrected rows after the swap.
- **Rename A, then click B's title:** A persists and focus lands in B's input after the swap.
- **Debounce / ordering:** tabbing across N rows issues exactly one panel GET; programmatic refocus
  after a commit issues none; a pointer click issues its GET immediately (no 150ms delay).
- **Keyboard tab order:** tabbing from a row title reaches the next control, not a hidden "Rename"
  button.
- **Top-level rename preserves document scroll** in a long course — guards both the whole-tree-swap
  invariant and the `preventScroll` requirement.
- `tests/test_e2e_builder_tree_layout.py` locates `.tree__title` with `has_text=` in seven places
  (lines 93, 107, 183, 205, 283, 297, 330) — an `<input>` has no text content, so all seven must move
  to value-based locators. **Line 93-96 needs more than a locator change:** it asserts
  `scrollWidth > clientWidth` to prove truncation, and an `<input>` renders its text in an inner
  editing host where those properties do not report overflow the way they do for a `<button>`. Replace
  the measurement with one valid for an input and falsify it first, or it may go vacuously green.
  Also confirm which panel-state assertions need explicit waits now that selection is fetch-driven.

**Verification before shipping**

- Full test suite green via `uv run pytest` (bare `pytest` / `ruff` / `python` are not on PATH).
- `uv run ruff check` and `uv run ruff format --check`.
- **i18n catalog tests**, since this change adds `{% trans %}` strings in a new location and deletes
  `_rename_form.html`: run `makemessages`, update both `en` and `pl` `.po` files, and **delete**
  removed msgids rather than leaving them as obsolete `#~` entries.
- **Page-weight measurement:** builder page transferred size and DOM node count for the largest
  available course fixture, before and after, with the delta recorded in the PR.
- Light and dark Playwright screenshots of: the tree at rest, on hover, and focused; and the
  **selected non-unit detail panel**, which is now heading-only and must not look broken or
  awkwardly padded.
- Because this worktree runs concurrently with others, it needs its **own `DATABASE_URL`** to avoid
  colliding on the shared Postgres `test_libli` database.
