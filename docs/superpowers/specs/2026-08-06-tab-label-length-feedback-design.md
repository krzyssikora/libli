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

This design fixes the feedback gap and caps the tab width. It does **not** change the limit.

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

**Consequence:** no model, migration, transfer or `FORMAT_VERSION` impact. `LABEL_MAX` and its four
live references stay exactly as they are — the constant (`courses/models.py:1399`), the read in
`normalize_labels_and_ids` (`models.py:1478`), `tabs_bounds` (`courses/templatetags/
courses_manage_extras.py:195`), and the transfer validator `check_str` (`courses/transfer/
payloads.py:747`).

## Non-goals

- Changing `LABEL_MAX`, `sanitize_label`, or any persistence/transfer behaviour.
- Any change to carousel **rendering**. The carousel caption is a block-level `<h3>` that wraps and
  already displays the full stored label; no carousel CSS rule and no branch of `tabs.js`'s carousel
  path is touched. (The new `data-label-text` attribute *is* emitted in carousel mode — see
  "Attribute is emitted in both modes" below — but nothing reads it there.)
- Truncating or otherwise restyling the builder tree `<summary>`.
- Warning the author that a *paste* was truncated at the server. `maxlength` already truncates the
  paste client-side, so the counter reflects the post-truncation value and the server path is
  unreachable from the editor UI.

## Architecture / components

Two independent changes. They share no code and can be verified separately.

### Change 1 — editor: per-row character counter

Give the author a visible signal as the cap approaches, and an unmistakable one at the cap.

#### Markup (`templates/courses/manage/editor/_edit_tabs.html`)

Two edits.

**(a)** The `[data-tabs-editor]` root div gains a third `data-msg-*` attribute beside the existing
`data-msg-remove` / `data-msg-confirm` (`_edit_tabs.html:17-18`):

```html
data-msg-cap="{% trans 'Limit reached' %}"
```

This is not optional plumbing. `label(root, key, fallback)` (`tabs_editor.js:13-15`) reads
`root.getAttribute("data-msg-" + key)`; without this attribute the helper silently returns its
English fallback forever, which is exactly the failure the i18n section exists to prevent. The key
is `cap`, read as `label(editor, "cap", "Limit reached")`.

**(b)** Each `.tabs-editor__row` gains a counter immediately after `[data-tab-label-input]` and
before `.tabs-editor__ctl`:

```html
<span class="tabs-editor__count" data-tab-count hidden>
  <span data-tab-num></span>
  <span class="sr-only" data-tab-cap aria-live="polite"></span>
</span>
```

Rendered **empty and `hidden`** by the server. The counter is a purely client-side affordance; a
server-rendered value would be wrong the instant the author types, and `hidden` keeps the no-JS
editor byte-identical in effect.

**Attribute naming is constrained by existing raw-substring assertions.**
`test_tabs_editor_partial.py:42` asserts `html.count("data-tab-row") == 2`. None of
`data-tab-count`, `data-tab-num`, `data-tab-cap` contains that substring, nor `data-tab-label`.
**Do not** name any of them `data-tab-label-count` or `data-tab-row-count`.

**Class naming has a live consequence.** `test_tabs_editor_partial.py:153`
(`test_editor_css_styles_every_tabs_editor_class`) scans the partial for every `tabs-editor__*`
class and requires `editor.css` to style each one. `.tabs-editor__count` is therefore *required* to
have a rule. The two inner spans deliberately carry **no** `tabs-editor__*` class — they are
addressed by data-attribute and by the global `.sr-only` — so they add no obligation.

#### The visually-hidden phrase

Use `.sr-only`, defined in `core/static/core/css/reset.css:25`:

```css
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
           overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
```

Chosen over `.visually-hidden` (`core/static/core/css/app.css:1212`), which omits the
`padding`/`margin`/`border` reset. It is loaded on the editor page: `editor.html` extends
`base.html`, which links `reset.css`, `tokens.css` and `app.css` (`base.html:44-46`) *before* the
`extra_css` block that adds `courses.css` and `editor.css`.

It must stay **clip-based, never `display: none` or `visibility: hidden`** — the phrase has to
remain in the accessibility and text trees so `aria-live` announces it and Playwright can read its
text.

#### Behaviour (`courses/static/courses/js/tabs_editor.js`)

- `n = input.value.length` — UTF-16 code units. This deliberately matches what `maxlength` counts
  (so an astral emoji counts 2), not `sanitize_label`'s code-point slice. See "Counter vs stored
  length" below.
- `max` is read from `input.maxLength` — the value the server already wrote as
  `maxlength="{{ tb.label_max }}"`. No new `data-*` plumbing, and it cannot drift from `LABEL_MAX`.
  If `maxLength` is absent or `-1`, the counter stays inert: `hidden` set, no text, no class.
- `threshold = Math.ceil(max * 0.8)` — 64 at the current cap. Derived, never hardcoded. The
  fraction is a JS constant; the *limit* remains single-sourced in the model.

`refreshCount(li)` **rebuilds the counter's entire state from `n` on every call.** It is a pure
function of the current value — never an incremental mutation. This is load-bearing: an
append-on-each-`input` implementation would repeat "Limit reached" once per keystroke at the cap
(and `input` does keep firing there in some browsers), and would leave the at-cap state stranded
when the author deletes back below it. One code path, three exhaustive branches:

| `n` | outer span | `[data-tab-num]` text | state class | `[data-tab-cap]` text |
|---|---|---|---|---|
| `n < threshold` | `hidden` | `""` | none | `""` |
| `threshold <= n < max` | shown | `n/max` | `.is-near` | `""` |
| `n >= max` | shown | `n/max` | `.is-at-cap` | localized "Limit reached" |

The at-cap branch tests `n >= max`, not `n == max`. Over-length values should be unreachable
(`editor_rows` normalizes both the bound and unbound source), but `>=` costs nothing and degrades
sanely if that ever stops holding, where `==` would silently show `.is-near` on `85/80`.

Below the threshold the outer span is `hidden`, which also keeps the row's flex `gap` out of the
layout — see "Layout" below. A permanent `0/80` on up to `MAX_TABS` (10) rows is noise that trains
an author to stop reading it.

#### Announcement policy

`aria-live="polite"` sits on the **inner `.sr-only` span only** — not on the outer counter.

This is the deliberate resolution of a real conflict. If the live region wrapped the digits, every
keystroke from 64 to 80 would mutate it, and a screen-reader user typing a long label would hear up
to seventeen consecutive "65/80", "66/80" … announcements interleaved with their own keystroke
echo. Putting the digits *outside* the live subtree and the phrase *inside* it means exactly one
announcement fires, on the transition into the cap, which is the only moment the author needs told.

`aria-describedby` on the input is deliberately **not** used: this partial is injected by editor
fragment swap and its own template comment records that it avoids `for=`/id references because ids
collide across swapped fragments.

#### Wiring

`tabs_editor.js` already delegates `input` on the `[data-tab-list]` container
(`rows.addEventListener("input", …)`, `tabs_editor.js:75-78`), so the counter needs **no per-row
listener** and therefore survives reorder and clone for free. That handler has only `e.target` in
scope — there is no `li` — so the call is:

```js
refreshCount(e.target.closest("[data-tab-row]"));
```

alongside the existing `serialize()`.

Three paths need an *explicit* refresh, because a delegated `input` listener only fires on typing:

1. **Init** (`wire()`): loop over `rowEls()` and refresh each. A saved label may already be at 80,
   and the counter must be correct before the author touches anything. This is the one path a
   delegated listener structurally cannot cover.
2. **Add tab**: the handler does `proto.cloneNode(true)`, which copies the counter span **including
   its text, its state class and its `hidden` state**, so cloning an at-cap row yields a brand-new
   empty input showing a stale `80/80 Limit reached`. Immediately after the existing
   `input.value = ""`, call `refreshCount(li)` — reusing the one state function resets text, class,
   phrase and `hidden` together, where an ad-hoc "clear the counter" would be three things to
   remember.
3. **Reorder / remove**: no refresh needed — `insertBefore` moves the whole `<li>` and the counter
   travels with it; `remove()` takes it away.

`refreshCount` returns early if the row, its input, or its counter span is missing, so markup drift
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
.el-editor--tabs .tabs-editor__count            { … }
.el-editor--tabs .tabs-editor__count[hidden]    { display: none; }
.el-editor--tabs .tabs-editor__count.is-near    { … }
.el-editor--tabs .tabs-editor__count.is-at-cap  { … }
```

`.tabs-editor__count[hidden] { display: none }` is **required, not cosmetic.**
`.tabs-editor__row` is `display: flex; gap: var(--space-2)` (`editor.css:931-936`), so a third flex
item that merely has empty text still contributes a second `gap` — every row would permanently lose
that much input width, for every author, in every state below the threshold, and with JS disabled.
The explicit `display: none` is also necessary because `[hidden]` is overridden by `display: flex`
in this codebase (the same trap `.tabs-editor__setting[hidden]` already handles two rules above).

The counter is `flex: 0 0 auto` with `font-variant-numeric: tabular-nums` so the digits do not
jitter as they change. The row's input is `flex: 1 1 auto; min-width: 0`, so a fixed-size sibling
shortens the input rather than overflowing the row.

**Tokens.** `.is-near` uses `--text-secondary`; `.is-at-cap` uses `--danger` (or the nearest
existing warning token — name it, do not invent one). **Do not** use `--text-tertiary`: it is
recorded in this codebase as failing AA at body size.

**Colour is not the only at-cap signal.** `.is-at-cap` also changes `font-weight`, and the sr-only
phrase carries the state to assistive tech. A colour-only state would be inaccessible to a
colour-blind author regardless of which token is chosen.

### Change 2 — student tabs strip: cap the tab width

#### CSS (`courses/static/courses/css/courses.css`)

Extend the existing `.el--tabs .tabs__tab` rule (`courses.css:1505-1510`) with `max-width`,
`overflow: hidden`, `text-overflow: ellipsis`. The rule is already `white-space: nowrap` and
`flex: 0 0 auto`, which is what makes ellipsis possible at all.

Cap: `max-width: min(18rem, 55vw)`.

**Be honest about what that guarantees.** The `55vw` bound is measured against the **viewport**, not
the strip's container. On a ~360px phone it resolves to ~198px and keeps a second tab and the edge
fade visible. In a narrow *container* on a wide viewport — the editor's preview pane, a tabs element
nested in a two-column layout, a tabs element inside a slide — `min()` resolves to the `18rem`
bound instead, the tab may fill its container, and no second tab is visible. That case falls back to
the scroller, fade and chevrons that already exist. The cap's job is to stop one pathological tab
from monopolising the strip; it is not a promise about any particular container width. A
container-relative bound (`cqi` with `container-type` on `.tabs__bar`) was considered and rejected
as disproportionate machinery for a cosmetic maximum.

The selector stays the existing descendant form `.el--tabs .tabs__tab`. Unlike the carousel rules,
this one does **not** need an explicit child chain: it is purely cosmetic, and applying it to a
nested tabs element's strip is correct rather than harmful. (The child-chain rule exists because
carousel rules *position and hide* things, so leaking into a nested instance blanks it.)

`overflow: hidden` does not clip the focus ring: `.tabs__tab:focus-visible` uses
`outline-offset: -2px`, so the outline is drawn inset.

#### Ellipsis on a `<button>` must be measured, not assumed

`white-space: nowrap` + `overflow: hidden` are necessary but not sufficient on a `<button>`:
Blink and WebKit wrap button content in an anonymous content box that has historically swallowed
`text-overflow`. Nothing in this spec establishes that it works here, and no *width* assertion can
tell an ellipsis glyph from a hard mid-character chop.

**Requirement:** before Change 2 is considered done, verify by screenshot (light and dark, judged
separately) that a long-label strip renders an actual ellipsis. **Named fallback if it does not:**
wrap the cloned label nodes in an inner `<span>` inside the button and move
`overflow`/`text-overflow` onto that span. The e2e must include a check that distinguishes ellipsis
from a hard clip (e.g. `scrollWidth > clientWidth` on the element carrying the ellipsis, together
with the screenshot).

#### Tooltip

The full label goes into the button's `title`.

The source of that string is the delicate part. It **must not** be `label.textContent`. `math.js`
runs before `tabs.js` in document order, so by the time the strip is built a label carrying inline
LaTeX is already a `<span class="katex">` subtree whose `textContent` is the MathML annotation *and*
the visual HTML rendering concatenated — mangled output like `x2x^2x2`. The existing code comment at
`tabs.js:129-139` documents exactly this, which is why the strip *clones child nodes* rather than
copying text.

So the plain label is carried from the server instead.
`templates/courses/elements/tabselement.html` emits it on the existing `<h3 class="tabs__panel-label">`:

```html
<h3 class="tabs__panel-label" data-tab-label data-label-text="{{ tab.label }}" id="…">
```

and `tabs.js` copies it across immediately after the child-node clone loop:

```js
var full = label.getAttribute("data-label-text");
if (full) btn.title = full;
```

`data-label-text` does not contain the substring `data-tab-label`, so `test_tabs_partial.py:35` and
`:224` (`html.count("data-tab-label") == 2`) still hold. The value is escaped by Django's
autoescaping in an attribute context, as `{{ tab.label }}` already is in its text position.

The `title` is set **unconditionally**, not only when the tab actually overflows. Measuring overflow
means a layout read after append plus re-measurement on resize; the cost and added failure surface
are not worth avoiding a redundant tooltip on a short tab.

**For a math label the tooltip is the raw LaTeX source** — `\(x^{2}\)`, not rendered maths, and not
anything a student can act on. This is accepted, and it is the honest reason the "accepted edge"
below is a genuine limitation rather than a mitigated one.

#### Attribute is emitted in both modes

`tabselement.html` emits one layout for both display modes, so `data-label-text` lands on the
carousel's `<h3>` as well, where nothing reads it. This is required, not incidental:
`test_tabs_partial.py:199` (`test_markup_is_identical_between_modes_apart_from_the_two_attributes`)
asserts the two modes' markup differs only by the two known attributes, so emitting the new
attribute in one mode only would break it.

## Data flow

Nothing is persisted or transferred by either change.

**Editor:** author types → delegated `input` handler on `[data-tab-list]` → `serialize()` writes the
authoritative hidden `input[name="data"]` (unchanged) **and** `refreshCount(row)` rebuilds the
counter. The counter never participates in serialization, never has a `name`, and is invisible to
the form. On save the server path is byte-for-byte what it is today.

**Student:** `tab.label` (already normalized and truncated at write time by
`normalize_labels_and_ids`) → rendered into the `<h3>` text *and* its new `data-label-text`
attribute → `tabs.js` clones the child nodes into the button and copies the attribute into `title`.
The stored value is the single source for both.

**Counter vs stored length.** The counter mirrors what `maxlength` counts — the raw input value in
UTF-16 code units. `sanitize_label` (`courses/sanitize.py:188`) stores
`_WS.sub(" ", html.unescape(value)).strip()[:max_length]`, so a label typed with entity text or runs
of spaces persists *shorter* than the counter showed: the author can see `80/80 Limit reached` for a
label that lands at 70. This divergence is pre-existing (it is exactly what `maxlength` has always
done) and is accepted; reproducing the server's normalization in JS would be a second source of
truth for a cosmetic readout.

## Error handling

- **`maxLength` unavailable** (attribute removed, or `-1`): the counter stays `hidden` with no text
  and no class. Degrades to today's behaviour rather than showing `n/-1`.
- **Counter span or input missing** from a row (markup drift, or an old cached fragment):
  `refreshCount` returns early. `serialize()` and the hidden field are untouched — the counter is an
  affordance, never a dependency.
- **`data-msg-cap` missing:** `label()` returns the English fallback. Degraded, not broken.
- **`data-label-text` missing or empty** on the `<h3>` (nested/legacy markup): `tabs.js` sets no
  `title`. The tab still renders and still elides; only the tooltip is absent.
- **No JS:** the editor shows a `hidden` span (no layout or visual change at all) and the student
  page shows the server's stacked fallback with full headings, exactly as today.
- **Print:** unchanged. The strip is `display: none !important` under `@media print` and the panel
  headings are revealed, so neither the cap nor the tooltip is reachable on paper.

## Accepted edges (deliberately not solved)

**1. A clipped label is unreadable on touch.** Today a phone user can swipe the horizontally
scrolling strip (`.tabs__scroller` is `overflow-x: auto`) and read an entire 80-character label.
After Change 2 the text is clipped *inside* the button, so scrolling no longer reveals it, and
`title` tooltips do not exist on touch devices — the chevrons are `aria-hidden` decoration, not an
alternative. This is a real reader-facing trade-off, not a cosmetic one, and it is accepted for
three reasons: the clipping is visual only, so the DOM text is intact and assistive tech still reads
the complete label; the cap is chosen to sit well past any reasonable tab label; and Change 1 exists
precisely to steer authors away from labels long enough to hit it. **This trade-off must be called
out explicitly in the PR body** so it is a decision on the record rather than a silent regression.

**2. Ellipsis cannot elide inside maths.** `text-overflow: ellipsis` operates on a text run, and a
KaTeX subtree is a sequence of inline-block boxes. A math-only label that overflows the cap is
hard-clipped with no ellipsis glyph, and its `title` is raw LaTeX (above). Solving this properly
would mean measuring and rebuilding the rendered maths — far out of proportion to the case.

## Testing

Every test must be **falsified**, not merely run: for each one, name the mutation to the
implementation it is supposed to catch, apply it, and confirm the test goes RED. A test that passes
against the broken build proves nothing. Falsify at the cheapest layer that can see the defect, and
scope each run narrowly (`-k`) — whole-suite sweeps belong to the branch gate.

**`tests/test_tabs_editor_partial.py`**
- `data-msg-cap` is present on the `[data-tabs-editor]` root and its value is a translated string.
  *Mutant:* drop the attribute.
- The counter renders once per row, `hidden`, between the input and the controls, with a
  `[data-tab-num]` child and an `.sr-only` `[data-tab-cap]` child carrying `aria-live="polite"`.
  *Mutants:* drop the span; drop `aria-live`; drop `hidden`; move `aria-live` to the outer span
  (must fail — that is the announcement-storm regression).
- `html.count("data-tab-row") == 2` still holds. *Mutant:* rename the counter to
  `data-tab-row-count`.
- `editor.css` styles `.el-editor--tabs .tabs-editor__count`, its `[hidden]`, `.is-near` and
  `.is-at-cap`, and the at-cap rule carries at least one **non-colour** declaration.
  *Mutants:* delete the `[hidden]` rule; delete the state rules; reduce `.is-at-cap` to colour only.
  (`test_editor_css_styles_every_tabs_editor_class` already forces a rule to exist for
  `.tabs-editor__count` itself; these assertions cover what it cannot see.)

**`tests/test_tabs_partial.py`**
- `data-label-text` is present on every `<h3>` and carries the full label.
- `html.count("data-tab-label") == 2` and `html.count("data-tab-panel") == 2` unchanged.
- A label containing `<`, `&` or a quote is escaped in the attribute.
- `test_markup_is_identical_between_modes_apart_from_the_two_attributes` still passes.
  *Mutants:* drop the attribute; rename it `data-tab-label-text` (must break the count); mark the
  value `|safe` (must break the escaping assertion); emit it only when `display == "tabs"` (must
  break the both-modes test).

**`tests/test_tabs_css.py`** — assert on the *physical rule*, not on file-wide presence, or the
mutant below passes. Locate the line whose selector subject is `.tabs__tab`, parse its
declarations, and require `max-width`, `overflow: hidden`, `text-overflow: ellipsis` and the
surviving `white-space: nowrap` **on that line**. Separately assert that no line whose selector
contains `[data-display="carousel"]` or `.tabs--carousel` gained a `max-width`.
*Mutants:* remove `text-overflow`; remove `overflow: hidden`; move the cap declaration onto a
carousel selector (must fail both assertions).

**`tests/test_e2e_tabs.py`** (`-m e2e`; must drive the real UI, never synthesise DOM)
- type to `threshold - 1` → counter still `hidden`; one more character → visible, `n/80`,
  `.is-near`
- type to 80 → `.is-at-cap`, and `[data-tab-cap]` has the localized phrase
- **descend**: 80 → 79 → 63 → the phrase clears, `.is-at-cap` gives way to `.is-near`, then the
  span returns to `hidden`. *Mutant:* make `refreshCount` append rather than rebuild.
- **init**: open the editor on an element whose *stored* label is already 80 characters and assert
  the at-cap state at first paint, before any keystroke. *Mutant:* delete the init refresh loop.
- "Add tab" cloned from an at-cap row → the new row's counter is `hidden` and empty.
  *Mutant:* remove the `refreshCount(li)` call from the add handler.
- reorder a row that is at the cap → its counter is still correct afterwards
- a long label in the strip → `title` equals the full stored label, `clientWidth` ≤ the cap, and the
  ellipsis check above distinguishes elision from a hard clip
- a label containing inline LaTeX → `title` is the plain LaTeX source, **not** the KaTeX-flattened
  text. *Mutant:* revert to `label.textContent` — this is the assertion that catches it.

*Sync on conditions, never sleeps.* Note the known init-time transition window in this element: a
`wait_for_selector` can resolve mid-transition, so negative visibility assertions need a settled
condition, not a bare selector wait.

**i18n.** "Limit reached" is the only new user-facing string. The full sequence is required, not
just the `.po` edit: `makemessages` → **clear any fuzzy pre-fill** (delete both the `#, fuzzy`
marker and the wrong `msgstr` it guessed from a similar msgid) → add the Polish translation →
`compilemessages` → **commit the binary `.mo`**. A `.po`-only change ships English to Polish users
with every test green. Add an assertion that the phrase resolves to its Polish form under
`translation.override("pl")` — `test_tabs_partial.py:421` exists for exactly this class of
regression and is the model to follow.

**Branch gate.** Both lint steps, not one: `uv run ruff check .` **and**
`uv run ruff format --check .`. PR #219 passed the first and failed CI on the second, because a
"wrap to 88 columns" instruction makes implementers wrap defensively and `format --check` rejects
unnecessary wrapping. Any lint nit a task report *mentions but does not fix* must be tracked to
closure, not read and scrolled past — that is the exact way #219's failure reached CI.

`uv run` is mandatory (ruff/pytest/python are not on PATH), and e2e needs `-m e2e` or the selection
silently empties and exits 5. Only one pytest invocation may run at a time across all worktrees —
concurrent runs collide on the test database.
