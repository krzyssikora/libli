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
- Any change to carousel mode. Its caption is a block-level `<h3>` that wraps and already displays
  the full stored label; nothing in the carousel CSS or the `tabs.js` carousel branch is touched.
- Truncating or otherwise restyling the builder tree `<summary>`.
- Warning the author that a *paste* was truncated at the server. `maxlength` already truncates the
  paste client-side, so the counter (below) reflects the post-truncation value and the server path
  is unreachable from the editor UI.

## Architecture / components

Two independent changes. They share no code and can be verified separately.

### Change 1 — editor: per-row character counter

Give the author a visible signal as the cap approaches, and an unmistakable one at the cap.

**Markup** (`templates/courses/manage/editor/_edit_tabs.html`). Each `.tabs-editor__row` gains a
span immediately after `[data-tab-label-input]` and before `.tabs-editor__ctl`:

```html
<span class="tabs-editor__count" data-tab-count aria-live="polite"></span>
```

It is rendered **empty** by the server. The counter is a purely client-side affordance; a
server-rendered value would be wrong the instant the author types, and an empty span keeps the
no-JS editor unchanged.

Attribute naming is constrained by existing tests that count raw substrings:
`test_tabs_editor_partial.py:42` asserts `html.count("data-tab-row") == 2`. `data-tab-count` does
not contain that substring, nor `data-tab-label`. **Do not** name it `data-tab-label-count`.

**Behaviour** (`courses/static/courses/js/tabs_editor.js`).

- `max` is read from `input.maxLength` — the value the server already wrote as
  `maxlength="{{ tb.label_max }}"`. No new `data-*` plumbing, and it cannot drift from
  `LABEL_MAX`. If `maxLength` is absent or `-1`, the counter stays inert (no text, no class).
- `threshold = Math.ceil(max * 0.8)` — 64 at the current cap. Derived, never hardcoded. The
  fraction is a JS constant; the *limit* remains single-sourced in the model.
- Below `threshold`: the span's text is `""` and it carries no state class. A permanent `0/80` on
  up to `MAX_TABS` (10) rows is noise that trains an author to stop reading it.
- At or above `threshold`: text becomes `n/max` (locale-neutral digits and a slash), and the span
  takes `.is-near`.
- At `max` exactly: `.is-at-cap` replaces `.is-near`, and a visually-hidden localized phrase
  ("Limit reached") is appended inside the span.

**Announcement.** `aria-live="polite"` sits on the span **itself**, not on a container, and
deliberately not `aria-describedby` on the input: this partial is injected by editor fragment swap
and its own template comment records that it avoids `for=`/id references because ids collide across
swapped fragments. A span that is empty until it matters only announces when it has something to
say, so the live region is quiet for the whole normal authoring path. Because the sr-only phrase
lives *inside* the live region, the at-cap announcement reads "80/80, limit reached" while the
visible text stays compact.

**Wiring.** `tabs_editor.js` already delegates `input` on the `[data-tab-list]` container
(`rows.addEventListener("input", …)`), so the counter needs **no per-row listener** and therefore
survives reorder and clone for free — the existing delegated handler gains a `refreshCount(li)`
call alongside its `serialize()`.

Three paths need an *explicit* refresh, because a delegated `input` listener only fires on typing:

1. **Init** (`wire()`): refresh every existing row. A saved label may already be at 80, and the
   counter must be correct before the author touches anything.
2. **Add tab**: `addBtn`'s handler does `proto.cloneNode(true)`. The clone copies the counter span
   **including its text and state class**, so cloning a row that sits at the cap yields a brand-new
   empty input showing a stale `80/80 Limit reached`. The handler already clears `input.value`; it
   must clear the cloned counter in the same place.
3. **Reorder / remove**: no refresh needed — `insertBefore` moves the whole `<li>` and the counter
   travels with it; `remove()` takes it away.

**Idempotence.** `wire()` is guarded by `editor.dataset.tabsEditorReady`, and the editor fragment
swap replaces the node entirely, so the re-init after a swap wires a fresh node with fresh state.
No change to that contract.

**Styling** (`courses/static/courses/css/editor.css`, beside the existing `.tabs-editor__*` rules).
`.tabs-editor__count` is `flex: 0 0 auto`, small, tabular-figures, `var(--text-secondary)`;
`.is-near` and `.is-at-cap` shift colour, with at-cap the stronger signal. The row is already a
flex container with `.tabs-editor__label { flex: 1 1 auto; min-width: 0 }`, so an
`flex: 0 0 auto` sibling shortens the input rather than overflowing the row.

Colour alone must not be the only at-cap signal (`--text-tertiary` already fails AA at body size in
this codebase, and colour-only state is inaccessible regardless) — the sr-only phrase plus the
weight/format change carry it.

### Change 2 — student tabs strip: cap the tab width

**CSS** (`courses/static/courses/css/courses.css`, on the existing `.el--tabs .tabs__tab` rule).
Add `max-width`, `overflow: hidden`, `text-overflow: ellipsis`. The rule is already
`white-space: nowrap` and `flex: 0 0 auto`, which is what makes ellipsis work at all.

Proposed cap: `max-width: min(18rem, 55vw)`. The `18rem` bound stops an 80-character monster on a
desktop; the `55vw` bound keeps a second tab and the edge fade visible on a ~360px phone. Both are
*maxima* — a tab narrower than the cap is unaffected, and anything still overflowing the strip is
handled by the scroller, fade and chevrons that already exist.

The selector stays the existing descendant form `.el--tabs .tabs__tab`. Unlike the carousel rules,
this one does **not** need an explicit child chain: it is purely cosmetic and applying it to a
nested tabs element's strip is correct, not harmful. (The child-chain rule exists because carousel
rules *position and hide* things, so leaking into a nested instance blanks it.)

`overflow: hidden` does not clip the focus ring: `.tabs__tab:focus-visible` uses
`outline-offset: -2px`, so the outline is drawn inset.

**Tooltip.** The full label goes into the button's `title`.

The source of that string is the one genuinely delicate part. It **must not** be
`label.textContent`. `math.js` runs before `tabs.js` in document order, so by the time the strip is
built a label carrying inline LaTeX is already a `<span class="katex">` subtree whose `textContent`
is the MathML annotation *and* the visual HTML rendering concatenated — mangled output like
`x2x^2x2`. The existing code comment at `tabs.js:129-136` documents exactly this, which is why the
strip *clones child nodes* rather than copying text.

So the plain label is carried from the server instead. `templates/courses/elements/tabselement.html`
emits it on the existing `<h3 class="tabs__panel-label">`:

```html
<h3 class="tabs__panel-label" data-tab-label data-label-text="{{ tab.label }}" id="…">
```

and `tabs.js` copies it across immediately after the child-node clone loop:

```js
var full = label.getAttribute("data-label-text");
if (full) btn.title = full;
```

`data-label-text` does not contain the substring `data-tab-label`, so
`test_tabs_partial.py:35` and `:224` (`html.count("data-tab-label") == 2`) still hold. The value is
escaped by Django's autoescaping in an attribute context, as `{{ tab.label }}` already is in its
text position.

The `title` is set **unconditionally**, not only when the tab actually overflows. Measuring
overflow means a layout read after append plus re-measurement on resize; the cost and the added
failure surface are not worth avoiding a redundant tooltip on a short tab.

## Data flow

Nothing is persisted or transferred by either change.

**Editor:** author types → delegated `input` handler on `[data-tab-list]` → `serialize()` writes
the authoritative hidden `input[name="data"]` (unchanged) **and** `refreshCount(row)` updates the
span. The counter never participates in serialization, never has a `name`, and is invisible to the
form. On save the server path is byte-for-byte what it is today.

**Student:** `tab.label` (already normalized and truncated at write time by
`normalize_labels_and_ids`) → rendered into the `<h3>` text *and* its new `data-label-text`
attribute → `tabs.js` clones the child nodes into the button and copies the attribute into `title`.
The stored value is the single source for both.

## Error handling

- **`maxLength` unavailable** (attribute removed, or `-1`): the counter renders nothing and adds no
  class. Degrades to today's behaviour rather than showing `n/-1`.
- **Counter span missing** from a row (markup drift, or an old cached fragment): `refreshCount`
  returns early. `serialize()` and the hidden field are untouched, so authoring still works — the
  counter is an affordance, never a dependency.
- **`data-label-text` missing or empty** on the `<h3>` (nested/legacy markup): `tabs.js` sets no
  `title`. The tab still renders and still elides; only the tooltip is absent.
- **No JS:** the editor shows an empty span (no visual change) and the student page shows the
  server's stacked fallback with full headings, exactly as today.
- **Print:** unchanged. The strip is `display: none !important` under `@media print` and the panel
  headings are revealed, so neither the cap nor the tooltip is reachable on paper.

## Accepted edge (deliberately not solved)

`text-overflow: ellipsis` cannot elide *inside* a KaTeX subtree — it is a sequence of inline-block
boxes, not a text run. A math-only label that overflows the cap is therefore hard-clipped with no
ellipsis glyph. The `title` tooltip is the fallback. Solving this properly would mean measuring and
rebuilding the math, which is far out of proportion to the case.

## Testing

Every test must be **falsified**, not merely run: for each one, name the mutation to the
implementation that it is supposed to catch, apply it, and confirm the test goes RED. A test that
passes against the broken build proves nothing. Falsify at the cheapest layer that can see the
defect, and scope each run narrowly (`-k`) — whole-suite sweeps belong to the branch gate.

**`tests/test_tabs_editor_partial.py`** — the counter span renders once per row, is empty, carries
`aria-live="polite"`, and sits between the input and the controls. Existing
`html.count("data-tab-row") == 2` still holds.
*Mutants:* drop the span; drop `aria-live`; name it `data-tab-label-count` (must break the row
count).

**`tests/test_tabs_partial.py`** — `data-label-text` is present on every `<h3>` and carries the full
label; `html.count("data-tab-label") == 2` and `html.count("data-tab-panel") == 2` are unchanged; a
label containing `<`, `&` or a quote is escaped in the attribute.
*Mutants:* drop the attribute; rename it to `data-tab-label-text` (must break the count assertion);
mark the attribute value `|safe` (must break the escaping assertion).

**`tests/test_tabs_css.py`** — `.tabs__tab` declares `max-width`, `overflow: hidden` and
`text-overflow: ellipsis`; the existing `white-space: nowrap` survives. No carousel selector is
touched.
*Mutants:* remove `text-overflow`; remove `overflow: hidden`; move the cap onto a carousel selector.

**`tests/test_e2e_tabs.py`** (`-m e2e`, and it must drive the real UI, not synthesise DOM) —
- type to `threshold - 1` → counter empty; type one more → `n/80` visible with `.is-near`
- type to 80 → `.is-at-cap` and the sr-only phrase present in the live region
- "Add tab" cloned from an at-cap row → the new row's counter is empty
- reorder a row that is at the cap → its counter is still correct afterwards
- a long label in the strip → `title` equals the full stored label and `clientWidth` ≤ the cap
- a label containing inline LaTeX → `title` is the plain source, **not** the KaTeX-flattened text
  (this is the assertion that would catch a regression to `label.textContent`)

*Sync on conditions, never sleeps.* Note the known init-time transition window in this element: a
`wait_for_selector` can resolve mid-transition, so negative visibility assertions need a settled
condition, not a bare selector wait.

**i18n.** The sr-only "Limit reached" phrase is the only new user-facing string. It is JS-set, so it
rides on a `data-msg-*` attribute read through the existing `label(root, key, fallback)` helper in
`tabs_editor.js` — the established pattern for JS-built strings in this file. It needs a `pl`
catalog entry; `makemessages` may fuzzy-pre-fill a **wrong** translation from a similar msgid, so
clearing a bad fuzzy means deleting both the `#, fuzzy` marker and the pre-filled `msgstr`.

**Branch gate.** Both lint steps, not one: `uv run ruff check .` **and**
`uv run ruff format --check .`. PR #219 passed the first and failed CI on the second, because a
"wrap to 88 columns" instruction makes implementers wrap defensively and `format --check` rejects
unnecessary wrapping. Any lint nit a task report *mentions but does not fix* must be tracked to
closure, not read and scrolled past — that is the exact way #219's failure reached CI.

`uv run` is mandatory (ruff/pytest/python are not on PATH), and e2e needs `-m e2e` or the selection
silently empties and exits 5. Only one pytest invocation may run at a time across all worktrees —
concurrent runs collide on the test database.
