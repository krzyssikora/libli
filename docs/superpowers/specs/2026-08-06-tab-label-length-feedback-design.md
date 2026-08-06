# Tab label length feedback + tab strip width cap

## Purpose

A content author writes a tab label longer than `TabsElement.LABEL_MAX` (80). Two mechanisms
enforce that limit and **both are silent**:

- `maxlength="{{ tb.label_max }}"` on the editor input (`_edit_tabs.html`) — typing simply stops.
  No counter, no message, no visual change. A paste is truncated the same way.
- `sanitize_label(value, TabsElement.LABEL_MAX)` (`courses/sanitize.py:188`) — `[:max_length]` on
  save, also silent.

The author's label ends mid-word, and because the cut happened to the *stored data*, it shows
identically in the editor preview and on the student page. Carousel mode surfaced this: there the
label renders as a visible centred caption rather than a strip handle, so a truncated one is
obvious in a way it never was before.

A second, related problem is visible at the *permitted* length: an 80-character label in tabs mode
produces a ~600px `white-space: nowrap` tab that fills the strip on a narrow viewport and pushes
every sibling tab out of sight.

This design fixes the feedback gap and caps the tab width. It does **not** change the limit, and it
never hides label text from any reader.

## Settled decisions

These were decided during brainstorming and are **not** open questions for review.

**`TabsElement.LABEL_MAX` stays at 80.** Raising it was considered and rejected. The label is not
only a caption — it is also:

- the slide's accessible name (`aria-labelledby` on the `<section>`, set by `tabs.js`),
- the `<summary>` of the per-tab group in the builder tree (`_element_row.html:83`),
- the tab handle in the strip whenever `display` is flipped back to `tabs`.

Short is a feature in all three. Long prose belongs in a text element *inside* the slide, which
carousel mode already supports — slides hold arbitrary child elements.

**No per-mode limit.** A limit that depends on `display` was rejected as actively dangerous.
`display` is a runtime toggle and `normalize_labels_and_ids` runs on **every** save, so switching a
carousel to tabs mode would permanently truncate a long caption: silent destructive data loss
triggered by a settings change.

**A too-wide tab wraps; it is never clipped.** Capping the width with
`overflow: hidden` + `text-overflow: ellipsis` was specified, reviewed, and then **rejected on the
user's explicit instruction**: a clipped label is unreadable on touch, where `title` tooltips do not
exist, and today a phone reader can swipe the strip and read the whole label. Nothing about this
feature may make label text unreadable on any device. The cap therefore constrains *width* only, and
the label wraps to as many lines as it needs.

This decision deleted the ellipsis, the `title` tooltip, the `data-label-text` attribute and the
`tabs.js` edit that the earlier draft required — along with their KaTeX hazards. **Change 2 is now a
CSS-only change.**

**Consequence:** no model, migration, transfer or `FORMAT_VERSION` impact. `LABEL_MAX` and its four
live references stay exactly as they are — the constant (`courses/models.py:1399`), the read in
`normalize_labels_and_ids` (`models.py:1478`), `tabs_bounds` (`courses/templatetags/
courses_manage_extras.py:195`), and the transfer validator `check_str` (`courses/transfer/
payloads.py:747`).

## Non-goals

- Changing `LABEL_MAX`, `sanitize_label`, or any persistence/transfer behaviour.
- Any change to `courses/static/courses/js/tabs.js`, `templates/courses/elements/tabselement.html`,
  or any carousel CSS rule.
- Truncating or otherwise restyling the builder tree `<summary>`.
- Any change to the reorder (up/down) handler in `tabs_editor.js` beyond clearing the shared live
  region — in particular it gains no `refreshCount` call.
- Warning the author that a *paste* was truncated at the server. `maxlength` already truncates the
  paste client-side, so the counter reflects the post-truncation value and the server path is
  unreachable from the editor UI.

## Architecture / components

Two independent changes. They share no code, touch no common file, and can be verified separately.

### Change 1 — editor: per-row character counter

Give the author a visible signal as the cap approaches, and an unmistakable one at the cap.

#### Markup (`templates/courses/manage/editor/_edit_tabs.html`)

Three edits.

**(a)** The `[data-tabs-editor]` root div gains a third `data-msg-*` attribute beside the existing
`data-msg-remove` / `data-msg-confirm` (`_edit_tabs.html:17-18`):

```html
data-msg-cap="{% trans 'Tab {n} label limit reached — {max} characters' %}"
```

This is not optional plumbing. `label(root, key, fallback)` (`tabs_editor.js:13-15`) reads
`root.getAttribute("data-msg-" + key)`; without this attribute the helper silently returns its
English fallback forever, which is exactly the failure the i18n section exists to prevent. The key
is `cap`.

Both placeholders are filled at runtime. This reuses the *shape* `tabs.js` uses for
`t("slidePos", "Slide {n} of {total}")` — a `data-msg-*` attribute carrying `{…}` tokens — but
**not its substitution code**: `tabs.js:275-276` chains `.replace("{n}", …).replace("{total}", …)`,
the single-occurrence form this design rejects. Do not copy it.

**Substitution must be global** — `.split("{max}").join(max)` or a `/g` regex, **not**
`String.replace` with a string pattern, which replaces only the first occurrence: a translation may
legitimately repeat a token, and a residual literal `{max}` in an announcement is a visible defect.

`{n}` is the row's **1-based position** (`rowEls().indexOf(li) + 1`), matching the number the
author already sees in the row's CSS-counter badge. It is not decoration — see "Why the phrase
names the row" below.

**(b)** Each `.tabs-editor__row` gains a digits span immediately after `[data-tab-label-input]` and
before `.tabs-editor__ctl`:

```html
<span class="tabs-editor__count" data-tab-num aria-hidden="true" hidden></span>
```

Rendered **empty and `hidden`** by the server. The counter is a purely client-side affordance; a
server-rendered value would be wrong the instant the author types, and `hidden` keeps the no-JS
editor unchanged in both appearance and layout.

`aria-hidden="true"` is deliberate: a bare "64/80" with no label is noise to a screen reader, and
the announcement channel is the live region below, which says what it means.

**(c)** One live region **per editor**, not per row, placed immediately after the closing `</ol>` of
`[data-tab-list]`:

```html
<span class="tabs-editor__status" data-tab-cap role="status" aria-live="polite"></span>
```

Per-editor rather than per-row for three reasons, all load-bearing:

1. **It is always present in the accessibility tree.** A live region that is inserted (or revealed
   from `display: none`) *already containing* its text is generally not announced — assistive tech
   announces mutations to a region that was already rendered. A per-row region hidden below the
   threshold would therefore drop its one announcement on exactly the case that matters most: a
   single `input` event jumping from empty to 80, which is what a paste, a select-all-replace, an
   undo or a text drag-and-drop produces.
2. **It costs no layout.** The clip rule below is `position: absolute`, so the region is out of flow
   and cannot contribute a flex gap to the row — see "Layout" below.
3. **One is sufficient.** Only one input has focus at a time.

The region is written from the `input`, **add**, **remove** and **reorder** paths — never from
init. It is a transition signal for something the author just did; re-announcing on editor open
would be noise.

**Attribute naming is constrained by existing raw-substring assertions.**
`test_tabs_editor_partial.py:42` asserts `html.count("data-tab-row") == 2`. Neither `data-tab-num`
nor `data-tab-cap` contains that substring, nor `data-tab-label`. **Do not** name either
`data-tab-label-count` or `data-tab-row-count`.

**Class naming has a live consequence.** `test_tabs_editor_partial.py:153`
(`test_editor_css_styles_every_tabs_editor_class`) scans the partial for every `tabs-editor__*`
class and requires `editor.css` to style each one. Both `.tabs-editor__count` and
`.tabs-editor__status` are therefore *required* to have rules — which is a feature, not a tax: it is
what keeps the clip rule below from being deleted as unused.

#### The visually-hidden mechanism: a locally-owned clip rule

`.tabs-editor__status` gets its own clip rule in `editor.css`, mirroring the two the codebase
already has for exactly this job — `.el--gallery .gallery__status` (`courses.css:1477`) and
`.el--tabs .tabs__status` (`courses.css:1601`):

```css
.el-editor--tabs .tabs-editor__status {
  position: absolute; width: 1px; height: 1px;
  padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
```

**The global `.sr-only` utility (`core/static/core/css/reset.css:25`) is deliberately NOT used**,
even though `base.html:44-46` does load `reset.css` on the editor page. A grep of the worktree finds
**zero** users of that class — no template, no project JavaScript (the only hits are a comment in
`slideshow.js` and the vendored MathLive bundle's unrelated `.ML__sr-only`) — and no test asserts it
exists. It is effectively dead CSS and a plausible cleanup casualty. If it were deleted, or changed
to `display: none`, the failure would be either a stray visible phrase sitting in every tabs editor,
or a silently dead announcement channel.

A locally-owned rule avoids that dependency, follows the established convention, and is
automatically protected: `test_editor_css_styles_every_tabs_editor_class` already requires a rule to
exist for any `tabs-editor__*` class found in the partial.

It must stay **clip-based, never `display: none` or `visibility: hidden`** — the region has to
remain in the accessibility and text trees so `aria-live` announces it and Playwright can read its
text.

#### Behaviour (`courses/static/courses/js/tabs_editor.js`)

`refreshCount(li, announce)` is defined **inside `wire()`**, in the same closure as `serialize` and
`refreshControlState` — it needs `editor` in scope for `label(editor, "cap", …)`.

**Its declaration goes after `function refreshControlState`'s body and before the first
`addEventListener` registration.** That position is chosen so the declaration lies outside all three
test slices defined below: a `function refreshCount(` declaration sitting *inside* the add-handler
slice would supply a `refreshCount(` occurrence after that handler's `serialize()` and satisfy the
ordering assertion vacuously. Declaring it between `serialize` and `refreshControlState` instead
would work for the slices but would push its body into the range
`test_serialize_reads_both_select_elements` already slices — so this position avoids both.

- `n = input.value.length` — UTF-16 code units. This deliberately matches what `maxlength` counts
  (so an astral emoji counts 2), not `sanitize_label`'s code-point slice. See "Counter vs stored
  length" below.
- `max` is read from `input.maxLength` — the value the server already wrote as
  `maxlength="{{ tb.label_max }}"`. No new `data-*` plumbing, and it cannot drift from `LABEL_MAX`.
  If `maxLength` is absent or `-1`, the counter stays inert: `hidden` set, no text, no class, and
  the live region is left untouched.
- `threshold = Math.ceil(max * 0.8)` — 64 at the current cap. Derived, never hardcoded. The
  fraction is a JS constant; the *limit* remains single-sourced in the model. **Note:** `80 * 0.8`
  is exactly `64.0` in IEEE-754, so `Math.ceil` and `Math.floor` are indistinguishable at the
  current cap; `ceil` is chosen for when `LABEL_MAX` is a value where `max * 0.8` is fractional.

`refreshCount` **rebuilds the counter's entire state from `n` on every call.** It is a pure function
of the current value — never an incremental mutation. This is what keeps the at-cap state from being
stranded when the author deletes back below the cap.

**Rebuilding is not, on its own, enough to prevent repeat announcements.** `input` keeps firing at
the cap in some browsers, and re-assigning the same string to `textContent` replaces the text node —
a mutation many screen readers announce again. The live-region write is therefore **guarded on
change**: compute the intended string and write it only if it differs from the region's current
`textContent`. This applies to clearing too — do not write `""` over an already-empty region.

One code path, three exhaustive branches:

| `n` | digits span | digits text | state class | live region (only when `announce`, and only on change) |
|---|---|---|---|---|
| `n < threshold` | `hidden` | `""` | none | `""` |
| `threshold <= n < max` | shown | `n/max` | `.is-near` | `""` |
| `n >= max` | shown | `n/max` | `.is-at-cap` | phrase with `{n}` and `{max}` filled |

The at-cap branch tests `n >= max`, not `n == max`. Over-length values should be unreachable
(`editor_rows` normalizes both the bound and unbound source), but `>=` costs nothing and degrades
sanely if that ever stops holding, where `==` would silently show `.is-near` on `85/80`.

Below the threshold the digits span is `hidden`, which keeps the row's flex `gap` out of the layout.
A permanent `0/80` on up to `MAX_TABS` (10) rows is noise that trains an author to stop reading it.

#### Why the phrase names the row

The change-guard and the shared region interact badly unless the phrase distinguishes rows, and the
failure is silent.

Row 1 reaches the cap, so the region holds the phrase. The author moves to row 2 and pastes 80
characters in a single `input` event. If the phrase were row-agnostic the intended string would be
**byte-identical** to what the region already holds, the change-guard would suppress the write, and
**no announcement would fire** — defeating the exact paste-to-cap case that motivated the
per-editor region in the first place.

Interpolating the row's 1-based position makes each row's phrase distinct, so a genuinely new
at-cap event always mutates the region while a repeat event on the *same* row is still correctly
suppressed. It also produces a better message: it names which tab, matching the badge the author
already sees.

The add and remove paths clear the region for the same reason — both move the author's attention
away from the row that produced the phrase, and a stale phrase is both readable by a browsing
screen-reader user and (per the above) capable of suppressing a later announcement.

#### Announcement policy

The digits are `aria-hidden` and carry the **sighted** signal; the live region carries the
**assistive-tech** signal, and only at the cap.

That asymmetry is deliberate and its cost is stated plainly: a screen-reader author gets **no
near-threshold warning** — no running count as they approach 64. Announcing every keystroke from 64
to 80 would mean up to seventeen consecutive "65/80", "66/80" … announcements interleaved with the
author's own keystroke echo, which is worse than silence. The at-cap phrase is therefore
self-contained — it names the tab, the fact, and the number — because it is the only thing that
channel ever says.

`aria-describedby` on the input is deliberately **not** used: this partial is injected by editor
fragment swap and its own template comment records that it avoids `for=`/id references because ids
collide across swapped fragments.

#### Wiring

`tabs_editor.js` already delegates `input` on the `[data-tab-list]` container
(`rows.addEventListener("input", …)`, `tabs_editor.js:75-78`), so the counter needs **no per-row
listener** and therefore survives reorder and clone for free. That handler has only `e.target` in
scope — there is no `li` — so the call is:

```js
refreshCount(e.target.closest("[data-tab-row]"), true);
```

**Invariant: `refreshCount` must be the LAST statement at each of its THREE call sites.** The
counter is an affordance, never a dependency, and that is only true if a throw inside it cannot
abort the authoritative work:

1. **`wire()` init loop** — placed after the existing tail
   `refreshControlState(); syncLabelPosRow(); if (hidden.value === "") serialize();`
   (`tabs_editor.js:125-136`). This ordering is not cosmetic: on the **add** path `hidden.value`
   starts `""`, so a throw from an init `refreshCount` placed above that tail would skip the init
   `serialize()` and submit an **empty** `input[name="data"]`.
2. **Delegated `input` handler** — after `serialize()`.
3. **Add handler** — after `rows.appendChild(li)`, `refreshControlState()` and `serialize()`.

Per-path detail:

1. **Init** (`wire()`): loop over `rowEls()` and call `refreshCount(li, false)` for each. A saved
   label may already be at 80, and the digits must be correct before the author touches anything.
   This is the one path a delegated listener structurally cannot cover. `announce = false` — opening
   an editor is not an event to announce.
2. **Add tab**: the handler does `proto.cloneNode(true)`, which copies the digits span **including
   its text, its state class and its `hidden` state**, so cloning an at-cap row yields a brand-new
   empty input showing a stale `80/80`. **Clear the shared region first** (subject to the
   change-guard), **then** call `refreshCount(li, false)` as the handler's genuinely last statement
   — reusing the one state function resets text, class and `hidden` together. The order matters
   only so the code and the invariant above read consistently.
3. **Reorder**: `insertBefore` moves the whole `<li>` and the counter travels with it, so no
   `refreshCount` call is needed or permitted here. But the branches **must clear the shared
   region**, as their last statement, for a reason stronger than the add/remove case: reorder
   *renumbers every row*, so a phrase naming "Tab 2" now describes a different tab. Worse, it
   re-opens the suppression hole: row 2 reaches the cap (region holds "Tab 2 …"), the author clicks
   Move up, then fills the row now sitting at position 2 to 80 — the intended string is
   byte-identical to what the region still holds, the change-guard suppresses the write, and
   nothing is announced. Clearing on reorder closes it. A bare clear, not `refreshCount`, keeps the
   ordering-invariant test's exemption for this handler intact.
4. **Remove**: clear the region as the **last statement** of the remove branch, subject to the same
   change-guard.

`refreshCount` returns early if the row, its input, or its digits span is missing, so markup drift
degrades to today's behaviour rather than throwing.

**File-order constraint.** `test_tabs_editor_partial.py:240`
(`test_serialize_reads_both_select_elements`) slices the JS as
`js[js.index("function serialize") : js.index("function refreshControlState")]`. Inserting
`refreshCount` between those two is harmless, but `function serialize` must keep preceding
`function refreshControlState` in file order or that slice inverts and the test fails for a reason
unrelated to this change.

**Idempotence.** `wire()` is guarded by `editor.dataset.tabsEditorReady`, and the editor fragment
swap replaces the node entirely, so the re-init after a swap wires a fresh node with fresh state.
No change to that contract.

#### Layout and styling (`courses/static/courses/css/editor.css`)

All selectors carry the `.el-editor--tabs` prefix every neighbouring rule in that block uses
(`editor.css:924-962`); a bare `.tabs-editor__count`, and especially bare `.is-near` / `.is-at-cap`,
would be globally scoped and inconsistent:

```
.el-editor--tabs .tabs-editor__count            { display: inline-flex; font-size: .82rem; … }
.el-editor--tabs .tabs-editor__count[hidden]    { display: none; }
.el-editor--tabs .tabs-editor__count.is-near    { … }
.el-editor--tabs .tabs-editor__count.is-at-cap  { … }
.el-editor--tabs .tabs-editor__status           { …clip rule above… }
```

The base rule declares `display: inline-flex`, which makes the paired
`.tabs-editor__count[hidden] { display: none }` **genuinely load-bearing** rather than a safety net:
`[hidden]` is a UA-stylesheet `display: none` and loses to any author `display` declaration, which
is the same trap `.tabs-editor__setting[hidden]` already handles two rules above. Without the paired
rule the span would occupy layout while empty, and `.tabs-editor__row` is
`display: flex; gap: var(--space-2)` (`editor.css:931-936`) — so every row would permanently lose a
gap's width of input space, for every author, in every state below the threshold, and with JS
disabled.

`font-size: .82rem` matches the sibling `.tabs-editor__setting label` rule (`editor.css:926`) and is
stated explicitly because the token caution below is recorded *at body size* — leaving the size
open would mean judging contrast against a different WCAG threshold than intended.

The counter is `flex: 0 0 auto` with `font-variant-numeric: tabular-nums` so the digits do not
jitter, and a `min-width` of `5ch` so its appearance does not shift the row. To be precise about
what that does and does not do: `ch` makes the floor scale with the **font size**, but `5` is sized
for the current two-digit cap (`2 + 1 + 2`) and would need revisiting if `LABEL_MAX` ever gained a
digit. It does not track the digit count. (`ch` is the advance of `0`, so the `/` makes `5ch`
slightly approximate even at two digits — harmless, since it is only a floor.)

**The input's floor, and an honest account of what it does.** `.tabs-editor__row` already reserves
`padding-left: calc(1.4rem + var(--space-4))` for the CSS-counter badge and carries a three-button
`.tabs-editor__ctl` group. Adding a fourth fixed item plus a second gap shrinks
`.tabs-editor__label` in the narrow editor pane at exactly the moment the author is typing a long
label. `.tabs-editor__label` is `flex: 1 1 auto; min-width: 0`, which permits it to shrink
arbitrarily. Raise it to `min-width: min(8rem, 100%)`.

**Do not claim this prevents overflow — it does not.** A percentage `min-width` on a flex item
resolves against the flex container's *full* inline size, not the space remaining after the badge,
counter and buttons. Summing those fixed items (≈38px badge reservation, 8px right padding, ≈92px of
icon buttons and gaps, two 8px row gaps, and the counter's own floor) the row needs roughly 330px of
inner width to honour a 128px floor — so for every row between 128px and ~330px wide, `min(8rem,
100%)` still evaluates to 128px and the flex line can overflow. The `100%` arm only engages below
128px, a width no realistic pane reaches.

**And it makes intrinsic-size inflation slightly worse, not better.** `.el-editor--tabs` is a grid
*container* (`editor.css:919`, `display: grid`), not a grid item — its parent `.editor-form`
(`editor.css:111`) is a plain block. The grid items are `.tabs-editor__setting`, the
`<ol class="tabs-editor__rows">` and the add button. Raising `.tabs-editor__label` from
`min-width: 0` to a 128px floor can only *increase* the `<ol>`'s min-content contribution, hence
that grid item's automatic minimum size. All `min(8rem, 100%)` buys over a bare `8rem` is less of
that increase. (The #220 fix was a different shape — `.el-editor > .scroll-x { min-width: 0 }`
(`editor.css:780`), an item *of* `.el-editor` opting out of intrinsic-width protection — so it is
not an analogy for this rule.)

**The real gate is measurement, not the declaration** — and when it was run, **the 8rem floor
failed it.**

Measured at the deepest legal nesting (depth 3) in a split-view pane at 1280×900: the row is 286px
wide, the input pinned at exactly 128px, the counter took 44px, and the row's `scrollWidth` came to
326px against a `clientWidth` of 286 — **40px of overflow, with the remove button rendering ~39px
outside the editor card**, over the nesting rails. A row with no counter showing (7-char label) fit
exactly. Identical in light and dark.

The shipped floor is therefore **`min-width: 4rem`**. With the floor removed entirely the input
still receives ~80px at that depth, so 64px fits with headroom while still preventing the field
collapsing to nothing. Re-measure if the row ever gains another fixed item.

**Tokens.** `.is-near` uses `--text-secondary`; `.is-at-cap` uses `--danger` — a hard stop, not a
caution. Both are defined for light and dark (`tokens.css:57`, `:98`). **Do not** use
`--text-tertiary`: it is recorded in this codebase as failing AA at body size.

**Colour is not the only at-cap signal.** `.is-at-cap` also changes `font-weight`, and the live
region carries the state to assistive tech. A colour-only state would be inaccessible to a
colour-blind author regardless of which token is chosen.

### Change 2 — student tabs strip: cap the width, wrap the label

Two rule edits in `courses/static/courses/css/courses.css`.

**(a)** The existing `.el--tabs .tabs__tab` block (`courses.css:1505-1510`):

- **remove** `white-space: nowrap`
- **add** `max-width: min(18rem, 55vw)`
- **add** `overflow-wrap: break-word`
- **add** `text-align: center` (see "Text alignment" below)

**(b)** A new rule immediately after it:

```css
.el--tabs .tabs__tab .katex { white-space: nowrap; }
```

No `overflow: hidden`, no `text-overflow`, no tooltip, no JS. A label that exceeds the cap wraps to
as many lines as it needs and stays completely readable on every device.

`overflow-wrap: break-word` is required, not decorative: an author can type 80 characters with no
spaces, and without it that single token would overflow the cap rather than wrap.

**Rule (b) is required because removing `nowrap` newly permits mid-formula breaks.** KaTeX emits
*multiple* `.katex .base` spans per formula, splitting at top-level binary operators and relations
so a formula *can* line-break between them; each base is `white-space: nowrap` internally
(`vendor/katex/katex.min.css`), but nothing prevents a break between bases. `white-space: nowrap` on
`.tabs__tab` has been suppressing that, so removing it would let `\(a + b = c\)` in a tab handle
wrap mid-formula. Restoring `nowrap` on the `.katex` subtree keeps a formula atomic; the cost is
that a formula wider than the cap overflows it, which is the accepted edge below.

**Measured capacity.** `18rem` = 288px (no `html { font-size }` override exists, so `1rem` = 16px);
global `box-sizing: border-box` (`reset.css:2`) and `padding: var(--space-3) var(--space-4)` = 16px
each side (`tokens.css:75`) leave 256px of text — roughly 34 characters per line at the tab's
`font-weight: 600`. An 80-character label therefore wraps to about three lines.

**This is why the cap and the counter threshold need not agree.** Wrapping begins around 34
characters while the counter stays silent until 64, and that mismatch is harmless *because wrapping
loses nothing*: labels between ~35 and ~63 characters simply occupy two lines, fully legible, with
no authoring signal needed. Under the rejected ellipsis design the same mismatch would have meant a
silently clipped label with no warning — which is precisely why that design was rejected.

**Text alignment and leading.** `.tabs__tab` is a `<button>`, which centres its text by default, so
a wrapped label renders as centred ragged lines. **Keep the centring and declare it explicitly**
(`text-align: center`) so it reads as a decision rather than an accident and nobody "fixes" it
later; a left-aligned multi-line tab beside centred single-line siblings looks worse than uniform
centring. `line-height` stays inherited (1.5 from `body` in `reset.css`) — no tuning.

**What the cap does and does not promise.** The `55vw` bound is measured against the **viewport**,
not the strip's container. On a ~360px phone it resolves to ~198px and keeps a second tab and the
edge fade visible. In a narrow *container* on a wide viewport — the editor's preview pane, a tabs
element nested in a two-column layout or inside a slide — `min()` resolves to the `18rem` bound
instead and the tab may fill its container, falling back to the scroller, fade and chevrons that
already exist. The cap's job is to stop one pathological tab monopolising the strip; it is not a
promise about any particular container width. A container-relative bound (`cqi` with
`container-type` on `.tabs__bar`) was considered and rejected as disproportionate machinery for a
cosmetic maximum.

**Row height — and why two tabs in one strip cannot be compared.** `.tabs__strip` is `display: flex`
with no `align-items` (`courses.css:1503`), so it defaults to `stretch`: when one tab wraps to three
lines, **every tab in that strip becomes equally tall** and the 2px active-tab underline stays on
one baseline. This is the desired result. It also means a test comparing a wrapped tab's height to a
short tab's height *in the same strip* is measuring two equal numbers — see the e2e section.

**Selector scope.** Both rules stay in the existing descendant form `.el--tabs .tabs__tab …`. Unlike
the carousel rules, they do **not** need an explicit child chain: they are purely cosmetic, and
applying them to a nested tabs element's strip is correct rather than harmful. (The child-chain rule
exists because carousel rules *position and hide* things, so leaking into a nested instance blanks
it.) `tabs.js` builds `.tabs__tab` only in the tabs branch, so carousel mode never sees either rule.

No existing test pins `white-space: nowrap` on `.tabs__tab` — verified. (`test_tabs_partial.py:150`
mentions `nowrap` but is about the `@media print` reset for `.tabs__panel-label`, a different rule.)

## Data flow

Nothing is persisted or transferred by either change. Change 2 renders no new data — it restyles
markup that already exists.

**Editor:** author types → delegated `input` handler on `[data-tab-list]` → `serialize()` writes the
authoritative hidden `input[name="data"]` (unchanged) → **then** `refreshCount(row, true)` rebuilds
the digits and, at the cap and only if the string changed, writes the shared live region. The
counter never participates in serialization, never has a `name`, and is invisible to the form. On
save the server path is byte-for-byte what it is today.

**Counter vs stored length.** The counter mirrors what `maxlength` counts — the raw input value in
UTF-16 code units. `sanitize_label` (`courses/sanitize.py:188`) stores
`_WS.sub(" ", html.unescape(value)).strip()[:max_length]`, so a label typed with entity text or runs
of spaces persists *shorter* than the counter showed: the author can see `80/80` for a label that
lands at 70. This divergence is pre-existing (it is exactly what `maxlength` has always done) and is
accepted; reproducing the server's normalization in JS would be a second source of truth for a
cosmetic readout.

## Error handling

- **`maxLength` unavailable** (attribute removed, or `-1`): the digits stay `hidden` with no text
  and no class, and the live region is not written. Degrades to today's behaviour rather than
  showing `n/-1`.
- **Digits span or input missing** from a row (markup drift, or an old cached fragment):
  `refreshCount` returns early. `serialize()` and the hidden field are untouched.
- **Live region missing** (older cached partial): `refreshCount` skips the announcement and still
  updates the digits.
- **`data-msg-cap` missing:** `label()` returns the English fallback, with both placeholders still
  interpolated. Degraded, not broken. The fallback literal is
  `label(editor, "cap", "Tab {n} label limit reached — {max} characters")` and **must stay
  byte-for-byte identical to the `{% trans %}` msgid** — including the em dash and both tokens — or
  the degraded path renders a different string from the normal one.
- **A throw inside `refreshCount`:** cannot affect saving, because it is the last statement at all
  three call sites.
- **No JS:** the editor shows a `hidden` span and an empty clipped region (no layout or visual
  change at all) and the student page shows the server's stacked fallback with full headings,
  exactly as today.
- **Print:** unchanged. `.tabs__bar` is `display: none !important` under `@media print` and the
  panel headings are revealed, so the cap is not reachable on paper.

## Accepted edge (deliberately not solved)

**A single formula wider than the cap overflows it.** With rule (b) keeping a KaTeX subtree atomic,
a label consisting of one very wide rendered formula will paint past the `max-width` box and may
overlap the neighbouring tab. This is accepted deliberately: the alternatives are `overflow: hidden`
(the clipping this design exists to avoid) or letting formulas break mid-expression (worse to read
than a slight overlap). Layout overlap in a pathological case is preferable to hidden or mangled
content in a common one. Screenshot case 2 exists to record how bad it actually looks.

## Testing

Every test must be **falsified**, not merely run: for each one, name the mutation to the
implementation it is supposed to catch, apply it, and confirm the test goes RED. A test that passes
against the broken build proves nothing. **A named mutant that cannot go RED is a defect in the test
plan, not a step to skip** — if applying a mutant leaves the suite green, fix the assertion rather
than the code. Falsify at the cheapest layer that can see the defect, and scope each run narrowly
(`-k`) — whole-suite sweeps belong to the branch gate.

**`tests/test_tabs_editor_partial.py`**
- `data-msg-cap` is present on the `[data-tabs-editor]` root and its value contains both the `{n}`
  and `{max}` placeholders. *Mutant:* drop the attribute.
- Rendering the partial under `translation.override("pl")` puts the Polish msgstr in `data-msg-cap`.
  *Mutant:* leave the `.po` entry untranslated or fuzzy. (`test_tabs_partial.py:421` is the model
  for this assertion, but the string lives in `_edit_tabs.html`, so the test belongs here.)
- The digits span renders once per row, `hidden`, `aria-hidden="true"`, between the input and the
  controls. *Mutants:* drop the span; drop `hidden`; drop `aria-hidden`.
- Exactly one `[data-tab-cap]` region renders per editor, **outside** `[data-tab-list]`, with
  `aria-live="polite"` and class `tabs-editor__status`.

  Assert `html.count("data-tab-cap") == 1`, then prove the placement by slicing the list itself:
  ```python
  start = html.index("data-tab-list")
  assert "data-tab-cap" not in html[start : html.index("</ol>", start)]
  ```
  **Do not** use `html.index("data-tab-cap") > html.rindex("</ol>")`. That form is only sound
  against the partial-only render. This module has two idioms — `_render_form()`
  (`test_tabs_editor_partial.py:32`, renders `_edit_tabs.html` alone, exactly one `</ol>`) and
  `_served_tabs_form(client)` (`:178`, the full `element_add` response).

  In the served render the tabs editor is emitted as the **last `<li>` inside**
  `_editor_scope.html`'s top-level `<ol class="element-list">` — the list opens at `:41` and the
  `open_form_pk == "new"` branch appends the open form at `:53`, so the list's `</ol>` at `:54`
  always follows `data-tab-cap`. `rindex("</ol>")` therefore lands *after* it and the assertion goes
  RED against a **correct** implementation. (Note it is *not* the nested per-tab lists that cause
  this: `_served_tabs_form` builds its unit with `make_course_with_unit`, which creates a unit with
  no elements, so `rows` is empty, `_element_row.html` is never included, and the served HTML
  contains zero `element-list--nested` blocks. Do not go looking for them and conclude this warning
  is stale.) The forward-slice form above is robust under either render.
  *Mutants:* drop it (count fails); move it inside a row (the slice check fails — the count alone
  would not catch this).
- `editor.css` defines `.el-editor--tabs .tabs-editor__status` as a **clip-based** rule —
  `position: absolute` and a `clip`, and specifically *not* `display: none`.
  *Mutant:* replace the rule body with `display: none` (must go RED — that is the silently-dead
  announcement channel).
- `html.count("data-tab-row") == 2` still holds. *Mutant:* rename the digits span
  `data-tab-row-count`.
- `editor.css` styles `.el-editor--tabs .tabs-editor__count`, its `[hidden]`, `.is-near` and
  `.is-at-cap`; the base rule declares a `font-size`; and the at-cap rule carries at least one
  **non-colour** declaration. *Mutants:* delete the `[hidden]` rule; delete the state rules; reduce
  `.is-at-cap` to colour only.
- `.tabs-editor__label` declares a **non-zero** `min-width`. The assertion must **extract the
  declared value and compare it** — e.g. `m = re.search(r"min-width:\s*([^;}]+)", block)` then
  `assert m.group(1).strip() not in ("0", "0px")`.

  Two forms that look adequate and are not: a naive `"min-width" in block` stays green because
  `min-width: 0` is also a `min-width` declaration; and the negative lookahead
  `re.search(r"min-width:\s*(?!0\b)", block)` **also** stays green — `\s*` backtracks to zero
  characters, so the lookahead is evaluated at the space rather than at the `0` and trivially
  succeeds. It matches `min-width: 0;` and is completely inert. (This was verified by running it,
  after the lookahead form survived six rounds of spec review unexecuted.)
  *Mutant:* revert it to `min-width: 0`.
- **Ordering invariant.** The three call sites are anonymous callbacks and `wire()`'s tail, not
  named functions, so the `function serialize` / `function refreshControlState` idiom cannot be
  reused and a whole-file "last `refreshCount(` after last `serialize(`" check would **not** go RED
  against the mutant below (the input handler precedes both later sites in file order, so the
  file-level last indices never move). Use literal slice anchors:
  - input handler: `js[js.index('rows.addEventListener("input"') : js.index('rows.addEventListener("click"')]`
  - add handler: from `js.index('addBtn.addEventListener("click"')` to `js.index(TAIL)`
  - init: from `js.index(TAIL)` to `js.index("function initTabsEditor")`

  where `TAIL` is the literal `if (hidden.value === "")`. **Every anchor must be unique, and the
  test must assert that** (`js.count(anchor) == 1`) before slicing. This is not pedantry: the
  `wire()` tail is quoted above as
  `refreshControlState(); syncLabelPosRow(); if (hidden.value === "") serialize();`, and of those
  three statements `refreshControlState();` occurs **3 times** in the file and `syncLabelPosRow();`
  **2 times** — both appear *before* `addBtn.addEventListener`, so choosing either would invert the
  add slice into a `ValueError` or an empty string on which the index comparison passes vacuously.
  Only `if (hidden.value === "")` is unique (verified: 1 occurrence). This is the same
  slice-inversion trap the spec flags for `test_serialize_reads_both_select_elements`.

  Within each slice assert the last `refreshCount(` index exceeds the last `serialize(` index, and
  that the matched occurrence is a **call, not the `function refreshCount(` declaration** — the
  declaration's mandated position (above all listeners) already keeps it out of every slice, and
  this check keeps the assertion honest if that ever moves. The **click handler is exempt** — it
  contains no `refreshCount` call, only the region clears.
  *Mutant:* move `refreshCount` above `serialize()` inside the `input` handler slice.
  Note the recorded trap that raw-source regexes of this kind also match **comments and
  docstrings** — strip or account for them, or the assertion can pass on a comment.
- The reorder branches contain no `refreshCount` call, still use `insertBefore`, and **do** contain
  the region clear. *Mutants:* add a `refreshCount` call to the up/down branch; delete the clear.
- The cap-phrase interpolation in `tabs_editor.js` uses `.split("{n}")`/`.split("{max}")` (or a `/g`
  regex) and contains no `.replace("{n}"` or `.replace("{max}"` string-pattern form. This static
  check is the **only** thing enforcing the global-substitution rule: both the English msgid and the
  Polish msgstr contain each token exactly once, so a single-occurrence `.replace` chain produces an
  identical string and the e2e's "no residual `{`" assertion is green against it.
  *Mutant:* swap the split/join for `.replace("{max}", max)`.

**`tests/test_tabs_css.py`** — assert on the *declaration block*, not on a line and not on file-wide
presence. The existing rule spans `courses.css:1505-1510`, so a line-based parser finds nothing, and
"the line whose selector mentions `.tabs__tab`" also matches the `:hover`, `[aria-selected]` and
`:focus-visible` rules that follow. Locate the block whose selector is exactly
`.el--tabs .tabs__tab` (no pseudo-class, attribute or descendant qualifier), slice from its `{` to
the matching `}`, and assert **within that slice**: `max-width` present, `overflow-wrap` present,
`text-align` present, and `white-space: nowrap` **absent**. Separately assert that
`.el--tabs .tabs__tab .katex` exists and declares `white-space: nowrap`, and that no block whose
selector contains `[data-display="carousel"]` or `.tabs--carousel` gained a `max-width` (verified
safe today: no carousel rule currently declares one).
*Mutants:* restore `white-space: nowrap` on the tab; delete `max-width`; delete `overflow-wrap`;
delete the `.katex` rule; move the cap onto a carousel selector.

**`tests/test_e2e_tabs.py`** (`-m e2e`; must drive the real UI, never synthesise DOM)

Input method matters and is **specified for every case**: `fill()` sets the value and fires **one**
`input` event; `press_sequentially()` fires one per character and costs real wall-clock. Use
`fill()` to reach a starting length cheaply, then single-character gestures to cross a boundary.
Whether `fill()` is itself subject to `maxlength` depends on the injection path, so **every case
must `fill()` with a string of exactly the intended length — never longer — and assert
`input.value.length` before asserting on the counter.** Use plain single-width characters with no
leading, trailing or repeated whitespace and no `&`-entities, so the value survives `sanitize_label`
unchanged wherever a case round-trips through the server.

- **threshold boundary:** `fill()` to `threshold - 1` → digits still `hidden`; one
  `press_sequentially("x")` → visible, `n/80`, `.is-near`.
  *Mutants:* `n < threshold` → `n <= threshold`; the `0.8` fraction → `0.75`. (**Not**
  `Math.ceil` → `Math.floor`: `80 * 0.8` is exactly `64.0`, so that mutation is a no-op at the
  current cap and can never go RED.)
- **at cap:** `fill()` to 79, then `press_sequentially("x")` → `.is-at-cap`, and `[data-tab-cap]`
  holds the phrase with the row number and `80` interpolated, and contains no residual `{`.
  *Mutant:* delete the `.is-at-cap` branch.
- **jump to cap:** a single `fill()` carrying the value from any length below `max - 1` straight to
  80 → the live region receives the phrase. The discriminating property is **one `input` event
  spanning the gap**, not the starting value, so no emptying step is needed: a default row already
  holds `"Tab 1"` (5 characters — `default_data()`, `models.py:1455-1462`) and qualifies as-is.
  *Mutant:* **announce only when the previous length was exactly `max - 1`.** Name it that
  precisely: the loose phrasing "conditional on the previous state" invites an edge-triggered guard
  like `if (!wasAtCap && n >= max)`, which still announces on a jump from empty and so cannot go
  RED here. The `max - 1` form passes the incremental "at cap" case above and fails this one, which
  is exactly what this case uniquely pins.
- **second row to cap:** row 1 `fill()`ed to 80 (region holds its phrase), then row 2 `fill()`ed
  straight to 80 → the region carries **row 2's** phrase. *Mutant:* make the phrase row-agnostic
  and keep the plain `textContent` change-guard — the write is then suppressed and nothing is
  announced.
- **descend:** from 80, `press("Backspace")` once → digits read `79/80`, `.is-near` is present
  **and `.is-at-cap` is absent**, and the phrase has cleared; then `fill()` to 63 → digits return to
  `hidden`. The single `Backspace` matters: a `fill("")`-then-`fill()` implementation produces a
  different event sequence and would not exercise the at-cap → is-near transition this case exists
  to pin.

  The `.is-at-cap`-absent assertion is the load-bearing one. Without it, an add-only class
  implementation (`if (n >= max) cls.add("is-at-cap")` with no removal on the way down) passes every
  other assertion here — at 79 the row still shows `.is-near`, and at 63 the span is `hidden` — while
  rendering bold `--danger` "79/80" to the author. *Mutants:* drop the
  `classList.remove("is-at-cap")` / use add-only class handling (the narrow one this case must
  catch); make `refreshCount` append rather than rebuild (the broad one).
- **init:** open the editor on an element whose *stored* label is already 80 characters (seeded per
  the character constraints above), assert `input.value.length == 80`, then assert the at-cap digits
  at first paint before any keystroke **and** that the live region is empty.
  *Mutants:* delete the init refresh loop; pass `announce = true` at init.
- **add tab:** fill the **last** row (`[data-tab-row]:last-of-type`) to 80, then "Add tab" → the new
  row's digits are `hidden`, empty, and carry no `.is-at-cap`; **and** the live region is empty.
  Filling the last row is mandatory, not incidental: the add handler clones
  `existing[existing.length - 1]` (`tabs_editor.js:112`), so filling row 1 of 2 would make the clone
  source the untouched row 2 — already `hidden` and empty — and the first mutant below would stay
  GREEN. *Mutants:* remove the `refreshCount` call from the add handler; remove the region clear
  from the add handler.
- **remove:** this case has **two** preconditions, and missing either makes it go RED against a
  correct implementation while the named mutant is also RED — so it would discriminate nothing.

  1. **Row count.** Seed the element with three tabs (`_seed_tabs_element`, `test_e2e_tabs.py:101`)
     or click "Add tab" before removing, and assert the Remove button is enabled before clicking.
     `MIN_TABS = 2` (`models.py:1397`) and the button is gated twice — `b.disabled = n <= minTabs`
     (`tabs_editor.js:58`) and an early `return` in the click handler (`:84`) — so on the default
     two-row editor the click is a no-op. Every other e2e case here runs fine on the two-row
     default; this one alone must not.
  2. **The confirm dialog.** `tabs_editor.js:85` is
     `if (!window.confirm(label(editor, "confirm", "Delete this tab?"))) return;`. **Playwright
     auto-dismisses dialogs when no `dialog` listener is attached**, and a dismissed `confirm`
     returns `false`, so `li.remove()` never runs and the region keeps its stale phrase. Register
     `page.once("dialog", lambda d: d.accept())` before clicking `[data-tab-remove]`. This is the
     first case in `test_e2e_tabs.py` to need it — the file has no dialog handling at all today —
     and the repo already records the trap verbatim in `tests/test_e2e_spanning_merge.py:8-15`
     ("the test then fails on a later assertion with no hint why").

  Then: `fill()` a row to 80, remove that row, **assert the `[data-tab-row]` count actually dropped
  3 → 2** (so a silently-dismissed confirm fails with a diagnostic rather than masquerading as a
  missing clear), and finally assert the live region is empty.
  *Mutant:* delete the clear from the remove branch.
- **reorder:** `fill()` row 2 to 80; click Move up; **assert `[data-tab-cap]` is empty at this
  point**; then `fill()` the row now at position 2 to 80 → the region carries the phrase again.
  The mid-sequence assertion is the one that discriminates, and it is easy to omit: at the *end* of
  the sequence both builds read identically. Correct build — cleared on reorder, then rewritten.
  Mutant build — never cleared, so the change-guard suppresses the rewrite and the region still
  holds the same phrase. Only the state *between* the gestures differs.
  *Mutant:* delete the clear from the reorder branches (must go RED on the mid-sequence assertion).
- **strip wrapping:** pin the viewport to a width where the `18rem` arm of `min(18rem, 55vw)`
  unambiguously wins — `set_viewport_size({"width": 1280, …})` gives `min(288px, 704px)` = **288px**.
  Assert the 80-character tab's `clientWidth` is 288px within a small tolerance (not merely `<=` the
  cap: on a wide viewport `<= 55vw` is vacuously true and would stay green against a deleted
  `max-width`). `clientWidth` equals the border-box width here only because `.tabs__tab` sets
  `border: 0` on the horizontal edges. Choosing the `18rem` arm also sidesteps Chromium measuring
  `vw` against the viewport *including* the classic scrollbar.

  To prove it **wrapped**, assert on the *content* height, not raw `clientHeight`. `clientHeight` is
  the padding box, so with `padding: 12px` top and bottom and an inherited `line-height` of 24px a
  **single-line** tab already measures `24 + 24 = 48px` — exactly `2 × line-height`, which is why a
  naive "at least twice the line-height" check passes against an unwrapped tab. Assert instead
  `clientHeight >= 2 * lineHeight + 24` (72px), which a single-line tab fails at 48px and the
  ~3-line 80-character tab clears at ~96px. **Do not compare it to a short tab in the same strip** —
  `.tabs__strip` stretches every tab to equal height, so those two numbers are equal by design and
  such a test would fail against a *correct* implementation.
  *Mutant:* delete the `max-width` declaration — confirm it goes RED on the **height** assertion
  specifically, not only on the width one.

*Sync on conditions, never sleeps.* Note the known init-time transition window in this element: a
`wait_for_selector` can resolve mid-transition, so negative visibility assertions need a settled
condition, not a bare selector wait.

**Screenshot verification** (light and dark, judged separately — dark is not a recolour of light).
Three cases, because none is provable from the DOM:

1. A strip containing an 80-character label: confirm it wraps, that every tab in the strip is equal
   height, and that the active-tab underline sits on one baseline.
2. A tab whose label carries a **multi-base** formula wider than the cap — e.g.
   `\(a + b = c + d + e + f\)`, which KaTeX splits into several `.base` spans. A single-base fixture
   such as `\(\frac{a}{b}\)` is structurally incapable of showing this, because the behaviour under
   test is whether rule (b) keeps the formula atomic. Confirm it does not break mid-expression, that
   the line box contains its vertical extent without clipping, and record how far it overflows the
   cap and how the overlap with the neighbouring tab looks — this is the accepted edge.
3. A tabs editor at the **deepest legal nesting level in the narrowest realistic editor pane**, with
   a row at the cap: confirm the counter appearing does not push the row into overflow. This is the
   real gate on the `min-width` floor, whose declaration alone does **not** guarantee it.

**i18n.** The at-cap phrase is the only new user-facing string. The repo has **two** catalogs,
`locale/en` and `locale/pl`, and `makemessages`/`compilemessages` touch both — so the branch must
carry both regenerated `.mo` files or it ships inconsistent. (`en` is a source catalog with empty
msgstrs, so a fuzzy pre-fill there is harmless, but the file still moves.)

The full sequence is required, not just the `.po` edit: `makemessages` → **clear any fuzzy
pre-fill in `pl`** (delete both the `#, fuzzy` marker and the wrong `msgstr` it guessed from a
similar msgid) → add the Polish translation → `compilemessages` → **commit both binary `.mo`
files**. A `.po`-only change ships English to Polish users with every test green. Both `{n}` and
`{max}` must survive translation — flag them to the translator as literal tokens, not prose.

**Branch gate.** Both lint steps, not one: `uv run ruff check .` **and**
`uv run ruff format --check .`. PR #219 passed the first and failed CI on the second, because a
"wrap to 88 columns" instruction makes implementers wrap defensively and `format --check` rejects
unnecessary wrapping. Any lint nit a task report *mentions but does not fix* must be tracked to
closure, not read and scrolled past — that is the exact way #219's failure reached CI.

`uv run` is mandatory (ruff/pytest/python are not on PATH), and e2e needs `-m e2e` or the selection
silently empties and exits 5. Only one pytest invocation may run at a time across all worktrees —
concurrent runs collide on the test database.
