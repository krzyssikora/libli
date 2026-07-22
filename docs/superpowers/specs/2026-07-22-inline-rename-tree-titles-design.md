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

## The central design decision: a rename does not re-render the tree

Every other builder op (add, reorder, reparent, duplicate, delete) changes the tree's *structure*, so
`node_rename` today does what they all do — responds with a re-rendered parent scope, which
`applyFragment` swaps into the DOM.

**A rename changes no structure.** It changes one label and one optimistic-lock token. Responding
with a scope swap would destroy the very `<input>` the author is typing in, and an earlier draft of
this design spent most of its complexity budget compensating for that: a global in-flight gate,
focus restoration by DOM re-query, suppression of drags / add-chips / the Move picker, ordering rules
between `notice()` and `setPanel()`, and bail-outs for detached forms. Review rounds kept finding
correctness bugs in that machinery, all of them downstream of the swap.

So the tree-row rename gets a **narrow response**: the new title and the new token for that one row.
The JS updates the row in place. Nothing is destroyed, so there is nothing to restore, nothing to
suppress, and no ordering hazard. This is the decision the rest of the spec follows from — everything
below is small because of it.

## Interaction design

- **Click a row title** → the node is selected (the detail panel loads, as today) *and* the caret
  lands in the title text. There is no separate pencil or "edit" affordance.
- **Enter**, or **clicking away (blur)** → saves, but only if the trimmed text actually changed. An
  unchanged field never posts. The field keeps focus and caret on an Enter save; a blur save leaves
  focus wherever the author sent it.
- **Escape** → restores the stored title **without blurring**, so a keyboard user 300 rows down keeps
  their position. The field is then clean, so a later blur posts nothing.
- **Blur on an empty or whitespace-only field** → treated as *cancel*: the field reverts to the
  stored title and nothing is posted. (Blur is an ambiguous gesture; silently 422-ing on it would be
  hostile.)
- **Enter on an empty *or whitespace-only* field** → the handler writes the trimmed value back first,
  so the field is empty when validity is checked; `required` then fails and the browser shows its
  native "fill in this field" bubble. Nothing is posted and no in-flight state is set.
- **Resting appearance:** the field looks like plain text — no border, no background — so the tree
  does not become a wall of input boxes. A subtle border appears on hover and a real focus ring on
  focus, both **layout-neutral** (see Styling).
- **Truncation, stated per state:** an over-long title on an *unfocused* input still truncates with an
  ellipsis, exactly as the button did. On a *focused* input it does not — `text-overflow: ellipsis`
  does not apply to a focused text field, which scrolls its content horizontally instead. That is
  correct for something being edited, and is recorded so the difference is not read as a regression.

**Touch devices — accepted cost.** Because selecting a node now focuses a text input, tapping a row
on a tablet or phone raises the on-screen keyboard even when the author only meant to inspect the
node's panel. A `readonly`-until-second-tap scheme would avoid this, and is **deliberately rejected**:
it reintroduces the two-gesture "edit mode" this design exists to remove, and the builder is a
desktop-first authoring surface (its two-pane layout already collapses to a stacked fallback below
720px).

## Architecture / components

### What is reused unchanged

- `courses/builder.py:163` `rename_node(course, node_pk, title, token, unit_type=_UNSET, …)` already
  performs a **title-only** rename of any node kind: `unit_type`, `obligatory` and `html_seed_js` are
  only touched when they are not `_UNSET`, so a POST carrying just `node`/`token`/`title` renames a
  unit without disturbing its type or settings.
- `courses/static/courses/js/builder.js:135` intercepts any builder form carrying `data-op`, POSTs it
  via `fetch` with the CSRF token, and handles 409 (conflict notice) / 422 (error notice) uniformly.
- The optimistic-lock token (`node.updated.isoformat`) and its `ConflictError` → 409 path.

### Backend change 1 — normalize the title for all writers

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
time — seeding exactly the stray-whitespace rows the trimmed-vs-trimmed dirty check has to tolerate.

The normalization lives in these service functions rather than `ContentNode.clean()` because
`full_clean()` runs `clean_fields()` (which enforces `blank`) *before* `clean()`, so stripping inside
`clean()` would let `"   "` pass the blank check and then persist as `""`.

**Out of scope:** course import/transfer, which builds `ContentNode` directly rather than through
these services. Unchanged, with a note in the helper's docstring recording that it is bypassed there.

### Backend change 2 — the narrow rename response

`node_rename` (`courses/views_manage.py:290`) currently ends its success path with
`_render_scope(request, course, _scope_ref(node.parent_id))`. Its three success branches are: the
editor redirect (`ctx=editor`), the unit-panel re-render (`is_settings` on a unit), and the plain
rename. Once the panel's rename form is deleted, **the plain-rename fragment branch has exactly one
caller: a tree row.** So that branch changes to return a small fragment instead of a scope:

```html
{# templates/courses/manage/_rename_result.html #}
<data data-rename-for="{{ node.pk }}"
      data-updated="{{ node.updated.isoformat }}"
      value="{{ node.title }}"></data>
```

An HTML fragment rather than JSON keeps the endpoint's content type uniform and rides the existing
`r.text()` flow — the JS reads attributes off the parsed element. The non-fragment (no-JS) branch
still redirects to the builder, and the 409 / 422 branches are untouched.

`data-rename-for` also acts as the guard that a rename's 200 response is never mistaken for a scope
fragment. Note this applies to the **200 branch only**: a rename's 409 still returns a
`_conflict_scope` fragment and still goes through `applyFragment`, because there the tree genuinely
diverged and must be reloaded.

### What the narrow response makes unnecessary

Recorded explicitly, because an implementer reading an older draft or a similar op might reintroduce
them: **no in-flight gate, no suppression of other controls, no focus restoration, no `preventScroll`,
no `refocusPk` bookkeeping, and no `setPanel()`-versus-`notice()` ordering rule.** The input is never
removed from the DOM on the success path, so focus, caret, scroll position and every sibling control
simply keep working.

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
         data-panel-url="{% url 'courses:manage_node_panel' slug=node.course.slug pk=node.pk %}">
  <button class="visually-hidden" type="submit" tabindex="-1">{% trans "Rename" %}</button>
</form>
```

Points that are load-bearing rather than incidental:

- **The form wraps only the title**, sitting inside `.tree__rowhead` as a sibling of `.tree__cluster`,
  so it never nests the duplicate (`_tree_node.html:20-25`) or reorder (`_move_buttons.html`) forms
  that live *within* that cluster. Nested forms are invalid HTML.
- **`data-panel-url` moves onto the input; `data-select` is dropped entirely.** The focusin selection
  hook is `.tree__title` (matching every other handler here), and `data-select` had exactly two
  readers in the repo — `builder.js:191`'s click branch and `refreshPanel` at `:125` — both of which
  this design removes, leaving it with none. Dropping it also saves a few bytes on every one of ~800
  rows, which the page-weight note below cares about. `data-node` remains on the ancestor
  `<li class="tree__row">` (`_tree_node.html:2`) and is the anchor for step 9's row lookup.
- **`maxlength="200"`** mirrors the model field. `required` is what makes Enter-on-empty fail validity
  rather than post a blank title.
- **`autocomplete="off"`** stops browser autofill dropdowns over tree rows. **`spellcheck="false"`**
  stops red squiggles across every row at rest; the tradeoff — no spellcheck while actively editing
  either — is accepted rather than fixed with focus-time toggling.
- **The accessible name is a plain, kind-independent `Title`.** A text input's *value* is announced
  alongside its name, so the value already distinguishes rows, and the row's badge conveys the kind.
  Interpolating the kind was rejected because Polish needs the genitive ("Tytuł rozdziału") while
  `get_kind_display` supplies a nominative label; interpolating the title was rejected because it
  would go stale the moment the author types. `aria-label` overrides `title` for the accessible name;
  `title` is retained purely as the hover tooltip for truncated labels.
- **The AT role change is accepted.** Every row's title goes from `button` to `textbox`, so a screen
  reader user browsing an 800-row tree meets edit fields rather than buttons. That is inherent to the
  feature; Verification includes a screen-reader spot-check.
- **The submit button is `.visually-hidden` *and* `tabindex="-1"`.** The utility at
  `core/static/core/css/app.css:1167` uses the `clip` pattern, which keeps the element focusable —
  without `tabindex="-1"` every row would gain a second Tab stop, a serious keyboard regression in a
  long course. It exists only to guarantee a submit path for the no-JS case.

**Per-row markup cost — considered and measured.** Each row gains a `<form>`, a `{% csrf_token %}`
hidden input, two hidden inputs, a hidden submit button and a second `{% url %}` reversal. Courses
here reach ~800 units (the matematyka import loads 793), so this is not free: the CSRF token alone is
~64 bytes of value per row. The token is kept rather than dropped in favour of the cookie-reading
`csrf()` helper, because dropping it would break the no-JS path this design newly enables.
Verification **measures** the builder page's transferred size and DOM node count for the largest
available fixture, before and after.

### No-JS behaviour

Today the detail panel is JS-only: the title is a `type="button"` with a `data-panel-url` that only
`builder.js` acts on, so **without JS there is currently no way to rename any node from the builder.**
After this change the tree row is a real `<form method="post">`: pressing Enter posts normally,
`node_rename` falls through `_wants_fragment` to `redirect("courses:manage_builder")`, and the builder
re-renders with the new title. This is a strict improvement, covered by a test rather than asserted.

Blur-to-save and Escape-to-revert are JS enhancements; without JS, Enter is the commit gesture.

### JavaScript change — `courses/static/courses/js/builder.js`

All handlers are **delegated on `root`** using bubbling event types (`focusin` / `focusout` /
`keydown` / `input`) with `e.target.closest(".tree__title")`, exactly like the existing inline-add flow
at `builder.js:367-379`. This is mandatory, not stylistic: `applyFragment` replaces whole scope `<ol>`s
on *other* ops, so a listener bound directly to an input would die at the first such swap.

**All panel writes must route through `setPanel()`.** `tests/test_builder_js_invariants.py` asserts
exactly one `panel.innerHTML =` assignment, inside `setPanel` (which resets `scrollTop`). The focusin
rewrite touches both the success and `.catch` branches of the panel fetch; inlining either turns that
test red.

1. **Selection moves from `click` to `focusin`, hooked on `.tree__title`.** The existing handler at
   line 190 calls `e.preventDefault()` on `[data-select]`; on a text input that suppresses caret
   placement. The `[data-select]` branch is therefore **removed outright** from the `click` listener
   (leaving it with the `[data-move]` branch only), and its `clearMoving()` responsibility moves to
   `focusin`. The new handler reads `data-panel-url` off the focused `.tree__title`. Merely
   dropping the `preventDefault()` and leaving the branch in place would double-fetch the panel on
   every pointer selection — once from `click`, once from `focusin` — defeating the debounce and
   last-request-wins design below. Two guards come with the move:
   - **Pointer focus fetches immediately; keyboard focus is debounced.** A `pointerdown` on a row
     marks the next `focusin` as pointer-initiated, and pointer-initiated selection fetches with no
     delay — the click-to-select gesture must not gain latency. Keyboard focus (no mark) uses a
     **trailing 150ms** debounce, so tabbing across ten rows issues one fetch rather than ten. The
     mark is **consumed by the very next `focusin` whatever its target**, and also cleared on
     `pointerup` / `pointercancel`; without a defined lifecycle a `pointerdown` that never yields a
     `focusin` (badge, grip, right-click, aborted drag) would misclassify the next keyboard focus.
     **The `focusin` listener consumes the pointer mark and clears any pending debounce timer
     *before* it tests whether the target is a `.tree__title`** — so a focusin on **any** element
     cancels a pending fetch, including the grip, the reorder arrows, Move…, Duplicate, Export,
     Delete and anything in the panel. This scope is load-bearing, not incidental: Tab never goes
     title → title, it goes title → ~6 cluster controls → next title, and those intervening tab stops
     can easily span more than 150ms. If only title focusins cleared the timer, row A's fetch would
     fire while the author was still tabbing through A's own cluster, and "tabbing across ten rows
     issues one fetch" would be false.
     The request id is allocated **when the fetch is issued**, not when it is scheduled. Without the
     clear, tabbing to row A and then clicking row B within 150ms would let A's timer fire *after* B's
     immediate fetch, taking a higher id and winning last-request-wins — leaving the panel showing A
     while B is focused and selected.
   - **Last-request-wins, on both branches.** Each fetch carries a monotonically increasing request
     id; a response whose id is not the latest is discarded. The id check gates the **`.catch` branch
     too**, not just the success branch — that branch calls `setPanel('…Network error — please
     reload.…')`, so an ungated slow *failure* from an earlier row would otherwise blow away a later
     row's successfully loaded panel with an error box.
2. **Commit via `form.requestSubmit()` — never `form.submit()`.** `form.submit()` does not fire the
   `submit` event, so `builder.js:135`'s interceptor would never run and the browser would perform a
   full-page POST. Mirrors `commitOrCancel` at `builder.js:347`.
3. **`Enter` is cancelled unconditionally.** The `keydown` handler calls `e.preventDefault()` for
   `Enter` on any `.tree__title` **before** any dirty / validity / in-flight check. A text input in a
   form with a submit button performs native implicit submission, so cancelling only on the commit
   path would mean Enter on an unchanged title still posts, and Enter during an in-flight commit posts
   again with a consumed token. The add flow cancels the same way at `builder.js:370`.
4. **Validity is checked *before* any state is set.** The commit path calls `form.reportValidity()`
   and returns immediately if false, **without** setting `dataset.submitting`. A failed
   `requestSubmit()` fires no `submit` event, so nothing would ever clear that flag and the row could
   never commit again. Order: cancel default → dirty check → trim write-back → validity → set flag →
   **set `readOnly`** → `requestSubmit()`. (`readOnly` must come after validity — see step 7a.)
5. **Trim by writing back to the input.** The interceptor builds `new FormData(form)`
   (`builder.js:142`), which reads the input's **live** value, so trimming into a local would leave
   the untrimmed string in the POST body. Assign `input.value = input.value.trim()` before the
   validity check.
6. **Dirty check compares trimmed against trimmed:**
   `input.value.trim() !== input.defaultValue.trim()`. Comparing against a raw `defaultValue` would
   make a legacy row with stray whitespace post on a bare focus-and-blur.
7. **`form.dataset.submitting` guards Enter-then-blur.** After Enter the input keeps focus and its
   `defaultValue` still holds the old title until the response lands, so a following click-away would
   see a dirty field and post again. Both `focusout` and `keydown` bail while the flag is set; the
   submit handler clears it in every completion branch (`builder.js:181`, `:185`). The `keydown` bail
   covers **both `Enter` and `Escape`**: mid-flight, Escape's `revert()` would write the *pre-response*
   `defaultValue` — the old title — into the field, and the arriving response would then set
   `defaultValue` to the newly committed title, leaving the field displaying the old title and reading
   dirty, so the next blur would silently post the old title back and undo the rename. Escape during a
   round trip therefore does nothing; the round trip is a few tens of milliseconds.

7a. **The input is `readOnly` while a commit is in flight.** Set `input.readOnly = true` immediately
   after `dataset.submitting`, and clear it in **every** completion branch alongside that flag
   (200 / 409 / 422 / `.catch`).

   The flag lives on the *form* but this property lives on a child input that only rename forms have,
   so the shared clear sites (`builder.js:181`, `:185`) must look it up defensively — either scoped to
   the `data-op === "rename"` branch, or as a guarded pair:
   `var t = form.querySelector("input.tree__title"); if (t) t.readOnly = false;`. Note the tempting
   one-liner `form.querySelector(...)?.readOnly = false` is a **syntax error** — optional chaining is
   illegal on an assignment target.

   This is what makes the response handler simple and total: the author physically cannot type,
   delete, or empty the field between the POST and its response, so the field the response lands on is
   byte-for-byte what was posted. Without it, every mid-flight edit becomes a recovery problem — text
   typed after Enter and then blurred away, a field emptied mid-flight and left blank forever, a
   second Enter swallowed with no feedback. With it, none of those states is reachable.

   Ordering matters: `readOnly` is set **after** `reportValidity()` (step 4), because a `readonly`
   input is barred from constraint validation and `required` would stop firing. Readonly fields are
   still submitted, so the POST body is unaffected, and the field remains focusable with a visible
   caret — for the few tens of milliseconds involved the author sees no difference beyond keystrokes
   not registering.
8. **Blur commits synchronously, with four bail-outs first.** The `focusout` ordering is:
   1. **Bail if a commit is already in flight** — `form.dataset.submitting`. Nothing is lost by this:
      step 7a's `readOnly` means the field cannot have changed since the POST, so there is never newer
      text for this blur to save.
   2. **Bail if the window itself lost focus** — `relatedTarget === null && !document.hasFocus()`.
      Chromium fires `focusout` when the browser window or tab loses focus, so without this,
      alt-tabbing mid-edit persists half-typed text. Leave the field dirty for a later real blur.
   3. **Bail if the form is detached** — `!form.isConnected`. A `focusout` can be delivered for an
      input whose scope `<ol>` was just replaced by *another* op's `applyFragment`; committing from a
      detached form would post a superseded token. The add flow guards this at `builder.js:378`.
   4. **Bail if the trimmed value is empty** — `revert(input)` and return without posting. This must
      precede the dirty check: an emptied field *is* dirty (`"".trim() !== "Old"`), so relying on
      step 4's ordering alone would post an empty title and surface a 422. The **Enter** path
      deliberately does not share this branch; it relies on `required` + `reportValidity()`.
   5. Otherwise commit immediately, with no timer.
9. **Applying the narrow response (the `data-op === "rename"` branch of the submit handler).** This
   branch replaces `applyFragment` **on 200 only** — 409 and 422 keep the existing handling untouched
   (`builder.js:164-165` calls `applyFragment` for 200 *and* 409, and the 409 `_conflict_scope`
   fragment must still be applied or the stale row is never reloaded).

   **Parsing, and which elements the branch operates on.** Parse the body with the throwaway-`div` +
   `innerHTML` pattern the 422 branch already uses (`builder.js:177-178`), then read
   `[data-rename-for]`. **A 200 body with no such element is a silent no-op** that still clears
   `dataset.submitting` **and `readOnly`** — mirroring the missing-row rule below, so an unexpected
   response can never
   throw inside the `.then` and be converted by the outer `.catch` into a spurious "Network error"
   notice.

   **Locating the row — and when to do nothing at all.** First: **if `!form.isConnected`, this is a
   silent no-op** that still clears `dataset.submitting` and `readOnly`. A foreign `applyFragment` can
   land between the POST and its response, replacing the whole row; the markup it swapped in is
   already server-rendered, so patching is unnecessary — and actively harmful. A swapped-in render can
   *predate* this rename's DB commit, so its input would hold the **old** title; writing our committed
   title into its `defaultValue` while leaving the displayed old `value` alone would leave the row
   reading **dirty against a stale value** — from which the next blur would post the old title back and
   silently undo the rename. Skipping avoids that. It does **not** make the stale display go away: the
   row may keep showing the pre-rename title until a reload, and the next op on it will 409-and-reload
   off its predating token. That residual is the accepted outcome, recorded in the error table.

   Otherwise the form is still in the document, which is itself the proof that no swap replaced it, so
   every write targets the submitted form's own row: `row = form.closest("li.tree__row")` and the
   input that steps 3–8 already refer to. There is no fresh-lookup-by-pk step and no possibility of
   patching a different node's elements.

   The `isConnected` guard also keeps the attribute writes from throwing inside the `.then`, where the
   outer `.catch` (`builder.js:183`) would turn a *successful* rename into a spurious "Network error —
   please try again." notice.

   **The governing invariant: every DOM carrier of this node's `updated` must be refreshed.** A rename
   bumps `node.updated`, and that value is rendered into more places than the rowhead. Missing any one
   of them produces a spurious 409 on the author's *next* action — the exact class of bug the scope
   swap used to hide. The complete inventory, all within `li.tree__row[data-node="<pk>"]` (descendant
   rows are never touched):

   - **`> .tree__rowhead` — every `input[name=token]`:** the rename form's, the reorder form's
     (`_move_buttons.html`), and the duplicate form's on unit rows.
   - **the `<li>`'s own `data-updated` attribute**, which `dragstart` reads as `node_token`
     (`builder.js:223-224`).
   - **`> ol.tree__scope[data-scope="<pk>"]`'s `data-updated`** — present on non-unit rows only.
     `_tree_node.html:31` includes `_scope.html` with `scope_updated=node.updated.isoformat`
     (`_scope.html:2`), and `builder.js:279` reads exactly that attribute as `dropToken`, posting it
     as `parent_token` for `reparent_node` to check. Skip it and the next drag **into** the renamed
     chapter 409s.
   - **that same child scope's `input[name=parent_token]`** in its add affordance. `_scope.html:8`
     passes `scope_updated` into `_add_affordance.html:11`, and `add_node` enforces it via
     `_check_token(parent.updated, parent_token)` (`builder.py:145`). Skip it and the very common
     "rename a chapter, then add a lesson under it" flow 409s and discards the typed child title.

     **Use the pk-anchored selector
     `root.querySelector('form.tree__add[data-add-scope="<pk>"] input[name=parent_token]')`**
     (`data-add-scope` is already rendered at `_add_affordance.html:8`). A plain descendant query on
     the child scope is **wrong**: `_add_affordance.html` renders its `<li class="tree__add-row">`
     **last** in every scope, so any nested non-unit child row's own add form precedes it in document
     order and `childScope.querySelector('input[name=parent_token]')` would return a *grandchild's*
     token — stamping this node's timestamp onto an unrelated node's add form (wedging that node's
     adds until reload) while leaving the intended one stale.

   **Values, and why `value` is conditional.** In this order:

   1. Assign `input.value` **only when it differs from the committed title** — i.e. only when the
      server normalised something the client had not. Skipping the equal case is what preserves the
      caret: the HTML `value` setter jumps the caret to the end and drops the selection *even when
      assigning an identical string*. (Thanks to step 7a's `readOnly`, the field cannot have been
      edited during the round trip, so "differs" can only mean server-side normalisation.)
   2. Set `defaultValue` to the committed title. This is what makes the field clean again, so a
      subsequent blur does not re-post.
   3. Set `input.title = input.value` — **after** step 1, not before, so the tooltip reflects what is
      actually displayed. This matches the ordering `revert()` uses, and matters on exactly the
      truncated long titles where the tooltip is the only way to read the name.

   **There is no recommit, because nothing can change during the round trip.** See step 7a: the input
   is `readOnly` from the moment a commit is dispatched until its response lands, so when the response
   arrives the field necessarily still holds exactly what was posted. That removes an entire class of
   in-flight edit-recovery problems rather than solving them.

   Two earlier drafts tried to *recover* mid-flight edits instead — first a `dataset.recommit` flag,
   then a condition derived from DOM state (dirty ∧ unfocused ∧ `document.hasFocus()`). Both are
   recorded here as rejected, because each looked reasonable and each generated a fresh crop of
   correctness bugs: a flag that had to be cleared on five paths and could be set by a window-blur
   bail; a derived condition that silently reposted the *stale* title after a foreign swap, stranded a
   blanked field permanently, and swallowed an Enter-during-flight with no recovery. Preventing the
   edit is smaller and provably correct; recovering it is neither.

   **Ancestor scopes are deliberately not touched:** `rename_node` saves only the node
   (`save(update_fields=…)`) and, unlike `add_node`, never calls `course.save()`, so no *ancestor*
   token changes. This is distinct from the node's *own* child scope above, which the rename does
   invalidate.
10. **Escape reverts without blurring** — `revert(input)`, focus retained. Blurring on cancel would
    drop focus to `<body>`, forcing someone who abandoned an edit deep in a long tree to Tab from the
    top of the document again.
11. **`revert(input)` is a shared helper** used by Escape and by the empty-blur cancel: it sets
    `input.value = input.defaultValue` **and** `input.title = input.value`. Both are needed because
    assigning `value` from script fires **no** `input` event, so the delegated tooltip-sync handler
    (step 12) would not run and the tooltip would keep showing abandoned text — precisely where the
    tooltip matters most, on a truncated long title.
12. **Tooltip sync**, delegated on `root` for the bubbling `input` event, mirrors `input.value` into
    the `title` attribute while the author types. (`aria-label` is static and needs no syncing.)
13. **`refreshPanel` is deleted.** It is reached only from the `inPanel` branch at
    `builder.js:171-174`; once the panel's rename form is gone the only remaining panel form with
    `data-op` is the Move picker (`data-op="reparent"`), which takes the `setPanel(neutralPanel)`
    branch. Delete `refreshPanel`, the `else` branch, and the now-obsolete comment at
    `builder.js:117-122` rather than leaving dead code. The panel *heading* keeps the old title until
    the node is reselected — an accepted cosmetic lag.
14. **Accepted side effects.**
    - `clearMoving()` now runs on keyboard focus rather than only on a deliberate click, so
      Tab-traversing while a Move picker is open clears the `.moving` highlight.
    - Re-clicking an already-focused title does not refetch its panel (`focusin` does not re-fire).
      Harmless: no path clears the panel while a title retains focus, because a rename no longer
      touches the panel at all.
    - **Starting a rename discards an open Move picker.** Focusing a title fires `focusin` → panel
      fetch → `setPanel`, which replaces `panel.innerHTML` wholesale, and the picker lives in that
      panel. This is not new — clicking a title does the same today — and it means the picker's tokens
      can never be stale at rename time, because no picker survives to the commit. (An earlier draft
      tried to patch the picker's `node_token` on the rename response; that code would have been
      unreachable.)
    - A same-row op fired during the rename's round trip (clicking Duplicate the instant after
      blurring a dirty title) can still post the pre-rename token and 409. The window is one network
      round trip, the 409 path is non-destructive and self-correcting, and this is the same race any
      two concurrent builder ops have always had. Accepted rather than gated.
    - **A *foreign* op's `applyFragment` can still destroy a half-typed title.** "Nothing is
      destroyed" is a claim about the rename's **own** response only. Another op's response still
      swaps whole scope `<ol>`s, and the most reachable case needs no blur at all: with an inline-add
      row open and non-empty, clicking a tree title blurs the add input, and 120ms later
      `commitOrCancel` (`builder.js:373-379`) posts `node_add`, whose response replaces the scope —
      deleting the input the author started typing into a tenth of a second earlier. A landing
      reorder, drag or duplicate does the same. No bail-out covers this because no `focusout` for the
      title occurs. **Accepted**, and the same class as "uncommitted typing clobbered by an unrelated
      op": re-seeding a swapped scope with a focused dirty input would reintroduce exactly the
      restoration machinery this redesign removed, for a rarer case.

### Panel change — `templates/courses/manage/_node_panel.html`

The `_rename_form.html` include is removed, leaving a heading-only panel for non-unit nodes. The panel
is kept (rather than suppressing panel loading for non-units) because it preserves selection feedback.

`_unit_panel.html` is **not** changed: it stays valuable (type/obligatory summary, element list,
`+ Add element`, `Open editor →`).

**`templates/courses/manage/_rename_form.html` is deleted.** `_node_panel.html:4` is its only consumer
anywhere in the repo — `editor/_unit_settings.html` carries its own form markup — so it becomes dead
code.

**No msgid is removed by this deletion.** The `Title` and `Rename` strings both survive in the new
`_tree_node.html` markup, so `makemessages` keeps them and only their source-location comments change.
Deleting them from the catalogs would drop working Polish translations. The general rule still
applies: if any msgid *does* fall out of use, delete it from both `locale/en` and `locale/pl` rather
than leaving an obsolete `#~` entry, which the repo's catalog tests reject.

**Accepted knock-on:** the drop handler at `builder.js:304` clears the panel only
`if (panel.querySelector("form[data-op]"))`. A non-unit panel now contains no form at all, so a drag
no longer resets it — intended and harmless. (The Move picker still matches and is still cleared.)

### Styling — `courses/static/courses/css/builder.css`

`.tree__title` (line 38) currently styles a `<button>`. Two things must be handled explicitly:

- **Cascade.** `core/static/core/css/app.css:136` sets
  `input[type=text], … { width: 100%; padding: …; background: var(--surface-sunken); border: 1px solid var(--border-strong); border-radius: … }`.
  That selector is (0,1,1), so a bare `.tree__title` — (0,1,0) — loses outright and every row would
  render as a bordered, sunken-filled box. Qualifying to `input.tree__title` raises it to (0,1,1): a
  **tie**, not a win, resolved by source order — which resolves correctly because `base.html:46` loads
  `app.css` while `builder.html:4` injects `builder.css` in the later `{% block extra_css %}`. The
  mechanism is "equal specificity, later stylesheet wins", which is why the CSS test asserts the
  *declarations in the rule*, not a specificity relationship that does not exist.
- **Font.** An `<input>` does not inherit `font-family`/`font-size`; it falls back to the UA default
  (~13.33px Arial). `font: inherit` is **required**, or every tree label silently changes typeface.

Concretely:

- The selector must be written **literally as `input.tree__title { … }`** — single, ungrouped, class
  immediately before the brace. `tests/test_builder_styles.py` matches `\.tree__title\s*\{[^}]*…`,
  which survives this form but breaks on a grouped or descendant selector. Mechanical constraint, not
  a style preference.
- `input.tree__title` keeps `width: 100%; min-width: 0; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; text-align: left; color: var(--text-primary);` and adds `font: inherit;
  background: none; border-radius: 0; padding: 0; cursor: text;`.
- **Hover and focus must be layout-neutral.** The row has only `padding: 3px 4px` (`builder.css:33`),
  so adding a 1px border on hover to an element with none at rest would shift text and grow the row,
  making rows twitch as the pointer travels. The input carries `border: 1px solid transparent` at rest
  and only its *colour* changes on `:hover`; the focus ring uses `outline` / `box-shadow`, which do
  not participate in layout.
- `.tree__rename` (the form) becomes the flex item: `flex: 1; min-width: 0; display: flex;
  margin: 0;`. The `margin: 0` is required — a `<form>` is a block element that UA stylesheets give a
  default margin. The sibling `.tree__inline` (`builder.css:44`) sets it for exactly this reason.

## Data flow

1. Author clicks a row title → `pointerdown` marks pointer-initiated → `focusin` issues an immediate,
   last-request-wins `fetch(data-panel-url)` → `setPanel`.
2. Author types, then presses Enter (default cancelled unconditionally) or clicks away → dirty check
   passes → `input.value` trimmed in place → `reportValidity()` passes → `dataset.submitting` set →
   `readOnly` set → `requestSubmit()` → the submit handler posts `node`, `token`, `title`, CSRF.
3. `node_rename` → `rename_node` (normalizes the title) → `_check_token` → `full_clean()` →
   `save(update_fields=["updated", "title"])` → renders `_rename_result.html`.
4. The submit handler's rename branch parses `<data data-rename-for>` and updates the row **in place**,
   per step 9's inventory: input `defaultValue`/`title` (and `value` only when it differs from the
   committed title), every `input[name=token]` in the rowhead (rename + reorder, plus duplicate on
   unit rows), the row's `data-updated`, and — on non-unit rows — the child scope's `data-updated` and
   its add form's `parent_token`. `dataset.submitting` and `readOnly` are cleared.
   **No DOM is replaced**; focus, caret and scroll are untouched.

## Error handling

| Situation | Behaviour |
|---|---|
| Enter on an empty or whitespace-only field | Trimmed write-back makes it empty; `reportValidity()` fails → native bubble. Nothing posted, no flag set. |
| Blur on an empty / whitespace-only field | `revert(input)` — value and tooltip restored, nothing posted. |
| Whitespace-only title reaching the server (no-JS, or editor settings form) | Normalized to `""`; `full_clean()` rejects it. |
| Leading/trailing whitespace | Trimmed client-side into the field before posting, and stripped server-side on both the rename and add paths. |
| Over-length or invalid title, **JS path** | 422 + `_op_error.html` → existing `notice()`. No DOM change: typed text, focus, caret and token all survive, so a corrected re-submit succeeds. Flag cleared. |
| Over-length or invalid title, **no-JS path** | `_builder_with_notice(..., status=422)` (`views_manage.py:331-340`) — a full builder page with an inline notice. The tree re-renders from the DB, so **typed text is not retained**. This is the path over-length input actually reaches, since `maxlength` is client-side only. |
| Stale token (node changed elsewhere) | `ConflictError` → 409 → `_conflict_scope` fragment + "This changed elsewhere — reloaded to the latest." This branch **does** swap a scope (the tree genuinely diverged), discarding the typed title; that is correct, and it is the only rename path that replaces DOM. |
| Node deleted elsewhere | Same 409 path; `_conflict_scope` falls back to the `"top"` scope (`views_manage.py:519-528`) and the row is simply absent. |
| Enter immediately followed by click-away | `dataset.submitting` suppresses the second commit — exactly one POST. |
| Any keystroke — typing, delete, a second Enter — while a commit is in flight | The input is `readOnly` for the round trip, so the edit never happens. No text to lose, no field left blank, no swallowed commit to recover. |
| Escape pressed while a commit is in flight | Nothing happens (the `keydown` bail covers Escape). Reverting mid-flight would leave the field stale-but-dirty and silently undo the rename on the next blur. |
| A foreign swap detaches the row while its rename is in flight | `!form.isConnected` → silent no-op; flags and `readOnly` still cleared. The swapped-in markup is already server-rendered, and patching it could write a committed title onto a render that predates the commit. **Accepted residual:** that row may keep displaying the pre-rename title until a reload, and its next op 409s-and-reloads off the predating token. |
| Enter on an unchanged title | Default cancelled before the dirty check, so native implicit submission cannot fire — no POST. |
| Window/tab loses focus mid-edit | No commit; the field stays dirty. |
| Another op replaced this row's scope before the blur was delivered | `!form.isConnected` bail; the edit is discarded rather than posting a superseded token. |
| Another op's response swaps the scope **while** a title is being typed (no blur involved — e.g. an open add row's 120ms `commitOrCancel` timer landing) | The input is destroyed and the typed text lost. Accepted; re-seeding would reintroduce the removed restoration machinery. |
| A same-row op fired during the rename round trip | May 409 and reload — accepted, non-destructive, and the same race any two builder ops have always had. |
| Network failure | Existing `catch` → "Network error — please try again."; `dataset.submitting` **and `readOnly`** cleared, no DOM change, typed text kept and editable again. |
| No JavaScript | Enter submits natively; `node_rename` redirects back to the builder. |

## Testing

Every test below is **falsified before being accepted**: break the thing it guards and require RED
first (a passing test that never fails proves nothing).

**Backend tests**

- The shared normalization helper strips titles on **both** paths: `rename_node("  Fractions  ")`
  persists `"Fractions"`, `add_node("  Foo  ")` persists `"Foo"`, and a whitespace-only title raises
  `ValidationError`. Cover the no-JS POST path too.
- **Strip happens before length validation:** a 200-character title wrapped in spaces persists intact,
  while a 201-character title still raises. Without this, an implementation that stripped *after*
  `full_clean()` would pass every other listed test. Note this is a **service/POST-level test only** —
  `maxlength="200"` counts the untrimmed string, so the case cannot be reached by typing into the tree
  input; it arises via the no-JS POST, the editor settings form, or a direct service call.
- A title-only rename of a **unit** succeeds and leaves `unit_type`, `obligatory` and `html_seed_js`
  untouched — `rename_node`'s `_UNSET` handling is load-bearing. Include the type-only toggle, to
  prove normalization did not disturb the `_UNSET` branch.
- **The fragment rename response is the narrow one:** a fragment POST returns
  `_rename_result.html` carrying `data-rename-for`, the new `data-updated` and the new title — **not**
  a `[data-scope]` tree fragment. This is the pivot of the whole design, so guard it directly.
- The editor (`ctx=editor`) branch still behaves as before. Note the `is_settings` **fragment** branch
  (`_render_unit_panel`, `views_manage.py:346`) is already unreachable in production: both
  `has_settings` posters (`editor/_unit_settings.html:10-11`) and the type toggle
  (`editor/editor.html:58`) also send `ctx=editor`, which is checked first (`views_manage.py:341-342`),
  and they are full-page POSTs so `_wants_fragment` is false anyway. Leave the branch untouched; any
  test of it is a synthetic guard on dead code, and the `ctx=editor` full-page path is the behaviour
  actually worth asserting.

**Django template/view tests**

- A tree row for each of part / chapter / section / **unit** renders an editable title form
  (`data-op="rename"`, hidden `node` + `token`, `input[name=title]` with the current value, `required`,
  `maxlength="200"`). The unit case is the regression this change exists to prevent.
- The input carries `aria-label="Title"` and a `title` tooltip equal to the node title.
- **No-JS path:** POST without `X-Requested-With`; assert 302 to the builder and the persisted title.
  Also assert the rendered row is a real `<form method="post" action=…>`.
- **409 from a tree row:** POST with a stale token; assert 409 and the `_conflict_scope` fragment.
- `_node_panel.html` no longer renders a rename form, and `_rename_form.html` no longer exists.
- `tests/test_tree_badge.py:23` matches `<button class="tree__title"[^>]*\btitle="([^"]*)"`. Retarget
  to `<input class="tree__title"[^>]*\btitle="([^"]*)"`, still asserting the tooltip.
- `tests/test_e2e_builder_tree_layout.py`'s `test_notice_bar_is_visible_and_opaque_while_panel_scrolled`
  carries a docstring explaining that the 409 path "calls `refreshPanel()`". Step 13 deletes
  `refreshPanel`, so restate that rationale in terms of the `_conflict_scope` swap. The test still
  passes either way, so nothing else would surface the stale comment.

**CSS tests** (`tests/test_builder_styles.py`)

- The existing ellipsis / `min-width: 0` / `nowrap` assertions (lines 34-41) keep passing against the
  `input.tree__title` rule.
- New: `.tree__rename` carries `min-width: 0` and `margin: 0`.
- New: the `input.tree__title` rule carries `font: inherit`, resets `background` / `padding`, and
  declares a `transparent` rest border. Assert the **declarations**, not specificity —
  `input.tree__title` merely ties `input[type=text]` and wins on source order.

**JS invariant test** (`tests/test_builder_js_invariants.py`) — must stay green: exactly one
`panel.innerHTML =` assignment, inside `setPanel`.

**End-to-end (real browser, real gestures)**

Drive the actual UI — never `page.evaluate` shortcuts, which ship broken UX green.

- Click a **unit** title, type, press Enter → the tree label updates *and* the DB value changes.
- Same for a **chapter**, proving the interaction is kind-agnostic.
- **Focus and caret survive an Enter commit** — place the caret **mid-string** before pressing Enter,
  then assert the input is still focused *and* `selectionStart` is unchanged afterwards. Asserting
  focus alone would pass even if the response reassigned `value` (which jumps the caret to the end
  even for an identical string), so the mid-string caret is the real guard on step 9's conditional
  assignment — and the observable proof that no scope swap happened, i.e. the core of this design.
- **The field is read-only during the round trip:** with the response delayed (Playwright route
  interception), press Enter, then attempt to type, assert the value is unchanged, then let the
  response land and assert the field is editable again.
  **Use `page.keyboard.type()` after focusing — not `fill()` or `pressSequentially()`/`type()` on the
  locator.** Those run an *editable* actionability check, so against a `readOnly` input they hang and
  throw a timeout instead of typing-and-asserting-unchanged — and they *succeed* once the `readOnly`
  assignment is removed, inverting the test's RED and GREEN relative to what it is meant to prove.
  `page.keyboard.type()` performs no editability check and silently no-ops on a readonly field.
  Assert `readOnly` is `false` afterwards via `to_have_js_property` before re-typing. Also assert
  `readOnly` is cleared on a **422** (via the route interception described in the 422 test below),
  not only on success, or a rejected rename would leave the row permanently uneditable.
- **Tab to a row, then click a different row within 150ms** → the panel ends up showing the clicked
  row, not the tabbed one. Guards clearing the pending debounce timer on every `focusin`.
- **Rename the same row twice without reloading:** commit via Enter, wait for the response, then type
  a different title and press Enter again → both succeed, no conflict notice, and the DB holds the
  second title. This is the only test exercising the rename form's *own* refreshed `token` together
  with the `defaultValue` reset; an implementation that refreshes the sibling forms' tokens but not
  its own passes every other listed e2e and fails here. Falsify by skipping the rename form's own
  `input[name=token]` refresh.
- **Blur commits:** type, then click outside the tree → saved.
- **Escape reverts and keeps focus:** the value reverts *and* the input still has focus.
- **Tooltip tracks typing, then reverts:** type into a long title and — **before** pressing Escape —
  assert the `title` attribute equals the *typed* value; then press Escape and assert it equals the
  reverted value. The mid-typing assertion is what guards step 12's live sync: without it, an
  implementer who omits the `input` handler entirely still passes the Escape half (the tooltip simply
  never drifts) and the live-tooltip behaviour ships missing. Two falsifications: delete the `input`
  handler (first assertion must go RED) and drop `revert()`'s title sync (second must go RED).
- **Unchanged field does not post:** focus and blur without typing → **no POST to
  `manage_node_rename`** (a panel GET is expected and must not be counted), and no `updated` bump.
- **Enter on an unchanged title issues no POST**; **plain Enter posts exactly once**;
  **Enter-then-blur posts exactly once**.
- **Enter on an empty field does not wedge the row:** clear the field, press Enter (native bubble),
  then type a valid title and press Enter → it commits. Additionally assert **zero** requests to
  `manage_node_rename` during the empty-Enter step. Without that request-count assertion the test
  passes even if `readOnly` is set *before* `reportValidity()` — which would skip validation entirely
  (a readonly input is barred from constraint validation), POST the empty title, and merely 422. That
  inversion is this test's falsification: swap the `readOnly` and `reportValidity()` order and require
  RED.
- **422 does not wedge the row:** the row's own guards make a 422 **unreachable by typing** —
  `required` plus the unconditional Enter-cancel block an empty title, `maxlength="200"` truncates
  over-length input including pasted text, and `ContentNode.clean()` validates nothing else about the
  title. So both 422 tests are driven by **Playwright route interception**: fulfil the first
  `manage_node_rename` request with a 422 and an `_op_error.html` body, assert the notice appeared,
  the typed text and focus survived, and `readOnly` was cleared; then unroute so the corrected
  re-submit reaches the real server and succeeds. Do **not** reach for `page.evaluate` to strip
  `maxlength` — that would bypass the real UI.
- **Trailing whitespace:** type `"Fractions "`, commit through the real JS path → `"Fractions"`
  persists. Guards write-back-before-`requestSubmit()`.
- **Sibling tokens are refreshed:** rename a **unit** row, **wait for the rename POST's response**
  (`expect_response` on `manage_node_rename`), then click Duplicate on that same row → it succeeds
  with **no** conflict notice. This is the test that proves step 9 updated the duplicate form's token,
  and it fails loudly if only the rename form's token was refreshed. Repeat for the reorder arrows
  (every row has them) and for a drag of the just-renamed row.

  **Every follow-up-op test below must wait for that response first.** The token patch happens when
  the response lands, so firing the second op "immediately" would race the round trip — which the
  spec explicitly accepts as a 409 (see "Accepted side effects"). A test written without the wait is
  flaky by construction, and its failure is indistinguishable from the bug it exists to catch.
- **Rename a chapter, await the response, then drag a unit into it** → no conflict notice. Guards the
  child scope's `data-updated` refresh.
- **Rename a chapter, await the response, then add a lesson under it** → succeeds, no conflict notice,
  typed child title not discarded. Guards the child scope's `parent_token` refresh. Together with the drag case above,
  these are the two tests that would have caught the original rowhead-only inventory.
  **The fixture chapter must itself contain a nested section with its own add row**, so that a naive
  descendant query (which would find the *grandchild's* `parent_token`) fails RED. Additionally assert
  the nested section's own add still works afterwards — that is what catches the mis-stamped token.
- **Window blur does not commit:** type, blur the window (not the field) → no POST; field stays dirty.
  Playwright has no user gesture that blurs the browser window, so use a **second page in the same
  context plus `bring_to_front()`**, and confirm `document.hasFocus()` actually reports `False` under
  the run mode used — it differs between headed and headless Chromium. If it does not, the test is not
  exercising bail-out 2 and must be skipped with that reason rather than left falsely green.
- **Debounce / ordering:** Tab from a row title through that row's cluster controls to the **next**
  row's title — the real tab order, ~6 stops per row — and assert exactly **one** panel GET, counted
  after focus comes to rest. Written as "Tab N times between titles" it would not exercise the actual
  path. A pointer click issues its GET immediately. Falsify by scoping the timer clear to
  `.tree__title` focusins only.
- **Keyboard tab order:** tabbing from a row title reaches the next control, not a hidden "Rename".
- `tests/test_e2e_builder_tree_layout.py` locates `.tree__title` with `has_text=` in seven places
  (lines 93, 107, 183, 205, 283, 297, 330). An `<input>` has no text content; use the value-attribute
  selector form `page.locator('.tree__title[value="Unit 40"]')`, noting it matches the
  **server-rendered attribute**, so it must be read before the user types into that field.
  **Line 93-96 needs more than a locator change:** it asserts `scrollWidth > clientWidth` to prove
  truncation, and an `<input>` renders text in an inner editing host where those properties may not
  report overflow the way they do for a `<button>`. Take the measurement on the **unfocused** input
  and falsify it (give the row a short title, require RED).
  If the engine reports `scrollWidth === clientWidth` for a text control, the comparison goes **hard
  RED**, not vacuously green — and the short-title falsification would then pass trivially while the
  real case stays broken, so do not read a RED here as "the assertion works". In that case switch to a
  measurement that does hold for an input: compare the input's rendered box width against the measured
  width of its full text (e.g. via a hidden span with the same computed font), or assert the CSS rule
  plus an unchanged `.tree__rowhead` width. Pick whichever reports correctly in Chromium and falsify
  *that* one.

**Verification before shipping**

- Full test suite green via `uv run pytest` (bare `pytest` / `ruff` / `python` are not on PATH).
- `uv run ruff check` and `uv run ruff format --check`.
- **i18n catalog tests**: run `makemessages`, update both `en` and `pl` `.po` files, and delete rather
  than obsolete any msgid that genuinely falls out of use.
- **Page-weight measurement:** builder page transferred size and DOM node count for the largest
  available course fixture, before and after, recorded in the PR.
- Light and dark Playwright screenshots of the tree at rest, on hover, and focused; plus the
  **selected non-unit detail panel**, now heading-only, which must not look broken or awkwardly padded.
- A **screen-reader spot-check** covering the `button` → `textbox` role change: rows remain navigable,
  the "Title" name plus announced value identifies each row, and the hidden Rename button is not
  reachable by Tab.
- Because this worktree runs concurrently with others, it needs its **own `DATABASE_URL`** to avoid
  colliding on the shared Postgres `test_libli` database.
