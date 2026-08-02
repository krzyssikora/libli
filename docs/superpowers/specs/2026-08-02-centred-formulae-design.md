# Centred Formulae — Attribute-Homogeneous Merging for Aligned Blocks

**Status:** approved design, ready to plan.
**Predecessor:** `docs/superpowers/specs/2026-08-01-display-math-authoring-design.md` (shipped as PR #206). This slice closes the limitation that one named and deliberately pinned.

## Purpose

`math_reflow.js` rejoins math spans that the rich-text editor split across block boundaries, so
KaTeX's auto-render — which only matches inside a **single text node** — can typeset multi-line
display math. Its mergeability predicate rejects any `<div>`/`<p>` carrying an effective attribute.
A centred formula carries `class="ta-center"` on every line, so **every line is a barrier and the
formula never reflows**.

This slice makes blocks mergeable when their alignment is identical, and preserves that alignment on
the merged result.

### Evidence base — read this before weighing the priority

The predecessor measured the live corpus: **23,520 intact spans, 6 broken**, and the
"attributed boundary" row was **0**. Every real break is a bare `</p><p>`. **Centred display math
does not occur in stored content**; the only occurrences repo-wide are the two pinning fixtures this
slice inverts.

So this is a **forward-looking authoring fix, not an archive repair**. That is a deliberate choice,
not an oversight: centring a formula is an ordinary authoring gesture that today silently produces
non-rendering math, and the paste path is the authoring flow rather than the archive. But the
justification differs from the predecessor's, where six real records were visibly broken, and any
cost/benefit argument in review should use this framing rather than assuming attested breakage.

### What "centred" does and does not buy

KaTeX centres display math itself — `katex.min.css` has
`.katex-display{display:block;margin:1em 0;text-align:center}`. So once a `\[…\]` block renders, it
is centred whether or not the author's `ta-center` survives.

Preserving the class therefore matters for the *other* content on those lines — surrounding prose,
and inline `\(…\)` spans, which get no `.katex-display` — not for the rendered display block. This
is why the design preserves alignment rather than discarding it, but also why discarding it would
not have been visibly catastrophic. Reviewers should not treat "the formula is still centred" as
evidence the wrapper logic works.

## Constraints established by measurement

These bound the design; each was verified against the code on `master` at `671c57f0`.

**The attribute vocabulary on a stored block is tiny.** In `courses/sanitize.py`:

- `ALLOWED_ATTRIBUTES = {"a": {"href", "title", "rel"}}` — `div`/`p` are absent, so **`style` is
  unconditionally stripped** from a stored block.
- `ALIGN_CLASS_VALUES = {"ta-left", "ta-center", "ta-right"}` — exactly three; there is no
  `ta-justify`.
- `ALIGN_CLASS_TAGS = {"p", "div", "h2", "h3", "h4", "blockquote", "li"}`.
- A class value outside the allow-list is **emptied, not dropped**: nh3 emits `class=""` for a tag
  that is a key of `allowed_classes`. Measured: `<p class="evil">x</p>` → `<p class="">x</p>`;
  `<p class="ta-center evil">x</p>` → `<p class="ta-center">x</p>`.

So the complete set of attribute states a stored `<div>`/`<p>` can present is:
**no attributes, `class=""`, or `class="ta-left|ta-center|ta-right"`.** Nothing else.

**Colour never competes for the same attribute.** `courses/colour.py` sets
`TC_CLASS_TAGS = {"span", "b", "i", "em", "strong", "u", "a"}` — disjoint from `ALIGN_CLASS_TAGS` —
and the sanitiser strips `tc-*` from any block tag. `courses/recolour/colouriser.py:85-96` shows this
is a designed invariant, not an accident: when the importer meets a palette colour on a block tag it
wraps the children in a **new** `<span class="tc-…">` rather than classing the block. A
centred-and-coloured line is therefore
`<div class="ta-center">…<span class="tc-red">…</span>…</div>` — one class token on the block, never
two.

**The editor's representation is different, and out of reach.** `text_toolbar.js:46-74` converts
between the stored `ta-*` class and a native `style="text-align:…"` when loading into and saving out
of the contenteditable surface. In the RTE the alignment is therefore a **non-empty `style`**, which
this design classifies as not mergeable — and the surface is in `IGNORE_SELECTOR` regardless. Stored
content and editor content are two representations; only the stored one participates.

## Architecture

### `blockSignature(el)` — the new predicate

Returns a string identifying what a block *is*, for compatibility purposes, or `null` if the element
is not a mergeable block at all:

| element | signature |
|---|---|
| `<div>` (no attributes) | `"DIV"` |
| `<div class="">` | `"DIV"` |
| `<p class="ta-center">` | `"P\|ta-center"` |
| `<div class="ta-right">` | `"DIV\|ta-right"` |
| `<div data-x="1">` | `null` |
| `<div style="text-align:center">` | `null` |
| `<h3 class="ta-center">` | `null` (tag not `DIV`/`P`) |

An empty `class`/`style` continues to count as no attribute — that behaviour is load-bearing, because
nh3 emits `class=""` on every line of a pasted formula, and treating it as attributed would make the
whole feature a no-op on the dominant paste path.

`noEffectiveAttributes` is **retained unchanged** for `isBareBr`. A `<br>` cannot carry `ta-*` (`br`
is not in `ALIGN_CLASS_TAGS`), so that path has no reason to change and should not be disturbed.

### Mergeability becomes relative — the run partition changes

This is the design's one structural change, and the only one on a shared code path.

Today `mergeChildren` partitions children into runs by asking a single independent question per
child: *is this mergeable?* Signatures make compatibility **pairwise**: two blocks can each be
mergeable yet incompatible with each other. The partition therefore gains a second condition — a run
breaks when a block's signature differs from the signature already established for that run.

**A signed run is blocks-only.** If a run's signature is non-empty (i.e. carries a `ta-*` token),
every member must be a block bearing it; a parent-level text node or bare `<br>` **ends the run**.
Without this, a stray text node between two centred divs would be absorbed into the rebuilt wrapper
and silently become centred — a change to content the author never aligned.

**An unsigned run behaves exactly as it does today.** Text nodes and bare `<br>`s join it freely, and
mixed `DIV`/`P` membership is still permitted, because that is the path the six real `</p><p>`
repairs travel and it must come out byte-identical.

### The rewrite — reuse, do not rebuild

When a replacement group's signature is non-empty, the merged content goes into the **first covered
block**, which is kept; the remaining blocks in the group are removed. Reusing the existing element
rather than constructing a new one avoids re-serialising the attribute and cannot accidentally
normalise it.

When the signature is empty, the rewrite is unchanged: content goes into the parent and every covered
block is removed.

### Mixed alignment is a barrier — deliberate

When a span crosses blocks whose signatures differ, **no merge happens** and the math stays
unrendered, exactly as today.

This is a decided trade-off, not an omission. The alternatives were considered and rejected:
adopting the first block's class silently restyles the author's other lines; dropping alignment
discards an explicit author choice. Refusing to merge means the reflow never guesses at intent. The
accepted cost is that an author who centres only some lines of a formula still gets non-rendering
math with no explanation.

## Data flow

Worked examples. `⇒` is one `reflow()` pass.

**Homogeneous — merges, alignment preserved:**

```
<div class="ta-center">\[a</div><div class="ta-center">b\]</div>
  ⇒ <div class="ta-center">\[a\nb\]</div>
```

**Mixed class — barrier, unchanged:**

```
<div class="ta-center">\[a</div><div>b\]</div>                    ⇒ unchanged
<div class="ta-center">\[a</div><div class="ta-right">b\]</div>   ⇒ unchanged
```

**Mixed tag, same class — barrier, unchanged:**

```
<p class="ta-center">\[a</p><div class="ta-center">b\]</div>      ⇒ unchanged
```

**Signed run interrupted — barrier, unchanged:**

```
<div class="ta-center">\[a</div>stray<div class="ta-center">b\]</div>   ⇒ unchanged
<div class="ta-center">\[a</div><br><div class="ta-center">b\]</div>   ⇒ unchanged
```

**Partial coverage — the uncovered block survives separately:**

```
<div class="ta-center">x</div><div class="ta-center">\[a</div><div class="ta-center">b\]</div>
  ⇒ <div class="ta-center">x</div><div class="ta-center">\[a\nb\]</div>
```

**Unsigned — today's behaviour, unchanged:**

```
<p>\[a</p><p>b\]</p>   ⇒ \[a\nb\]        (content into the parent, both blocks removed)
```

### Idempotence

After one pass a merged centred formula is a single `<div class="ta-center">` holding one text node.
On the next pass it forms a one-member run, the span lies wholly inside a single text node, and
**rule 4 skips it** — the same argument that makes the unsigned path idempotent.

This must be re-established by measurement, not by this paragraph. The module has been
non-idempotent twice, both times in code adjacent to this change, and both times the reasoning that
it "obviously" converged was wrong.

## Error handling

Unchanged. This slice adds no new failure mode and no new catch:

- The per-element `try/catch` in `walk` still contains a throw and lets the traversal continue, and
  still emits a `console.warn`.
- `IGNORE_SELECTOR` and the root guards are untouched, so no reflow can reach a serialized
  contenteditable surface.
- A `null` signature is a **classification** result, not an error — it produces a barrier, which is
  the same outcome an unmergeable element produces today.
- `findEndOfMath` / `findSpans` **must not be touched**. A 4,044-input differential proof of
  byte-equivalence against the vendored auto-render depends on them, and that proof is void if they
  change.

## Testing

### Invert the two pinning tests, without losing their coverage

- `tests/test_e2e_math_reflow.py::test_centred_display_math_is_not_reflowed` becomes its positive
  twin: `.katex` count 1, `.katex-error` count 0, one surviving `ta-center` block, and no
  `</div><div` in the markup.
- In `tests/test_e2e_math_reflow_dom.py::test_barriers_are_not_merged_across`, the `ta-center` case
  moves out. Because deleting a barrier case **weakens** that test, mixed-signature cases replace it.

### The mixed cases are the load-bearing new tests

The conservative rule is only real if something pins it. Each of these must come out byte-unchanged:

1. `ta-center` + bare `<div>`
2. `ta-center` + `ta-right`
3. `<p class="ta-center">` + `<div class="ta-center">` — same class, different tag
4. a signed run interrupted by a parent-level text node
5. a signed run interrupted by a parent-level bare `<br>`

These five are what would redden if the rule were later loosened to "take the first block's class".

### Happy-path cases

- homogeneous merge producing exactly one wrapper — **exact-equality** assertion, not membership
- `ta-left` and `ta-right` as well as `ta-center`, so nothing is hardcoded to centre
- partial coverage: a span covering only the last two of three centred divs, first block surviving
- phase-2 interaction: a centred `\(\begin{cases}…\)` split across lines must come out **merged and
  promoted**
- idempotence on a centred fixture: two passes, identical output

### Falsification is the acceptance bar, per test

Every new test must be demonstrated **RED** with the signature change reverted, and the RED output
recorded. The predecessor shipped a fix whose rule-4 half no committed test pinned — all 40 tests
stayed green with it reverted — and that surfaced only because a reviewer went looking. The same bar
applies here, and the mixed-signature tests are where it matters most.

### Idempotence is re-fuzzed, not re-argued

The predecessor's 500-document structured generator gains `ta-*` attributed blocks. Assertion is
unchanged: N passes, zero divergence, zero text loss.

### Regression surface

- The six real `</p><p>` repairs — unsigned runs, unchanged path.
- The `data-x="1"` barrier case: attributes outside the `ta-*` vocabulary still yield `null`.
- `tests/test_e2e_math_reflow_dom.py` already merges inside a `<td class="ta-center">` — the cell is
  not a mergeable *block*, the merge happens among its children, and the cell's class is irrelevant.
  That must stay true.
- Headings, `<li>`, `<blockquote>` stay barriers. The sanitiser permits `ta-*` on them, but
  `isMergeableBlock` only ever accepted `DIV`/`P` and this does not widen that.

## Definition of done

- Full non-e2e suite: expected to stay at **4566 passed** — every new test here is e2e.
- Full e2e suite. Two failures are known pre-existing parallel-load flakes
  (`test_e2e_builder_filter.py::test_collapse_everything_filter_clear_comes_back_EMPTY`,
  `test_e2e_inline_rename.py::test_tabbing_across_a_row_issues_one_panel_fetch`); each passes in
  isolation and neither is touched by this slice.
- `ruff check .` and `ruff format --check .` clean.
- **Light and dark before/after screenshots of a centred formula.** Three centred line divs currently
  receive `margin-top: var(--space-3)` between them from the adjacent-sibling rule at
  `courses/static/courses/css/courses.css:27-32`. Collapsing them to one block removes those gaps and
  substitutes KaTeX's own `.katex-display { margin: 1em 0 }`. That is the intended outcome — the same
  collapse the predecessor verified for `</p><p>` — but it is a real spacing change and is verified
  visually, not assumed.

## Out of scope

- **Widening `isMergeableBlock` beyond `DIV`/`P`.** Headings and list items can carry `ta-*` but are
  not formula lines.
- **General attribute-set homogeneity.** Considered and rejected: no attribute other than a `ta-*`
  class can reach a stored block, so a general rule buys nothing today while having to answer harder
  questions (duplicate `id`s on rebuild, `data-*` semantics).
- **Changing the authoring surface** so per-line `ta-*` is never emitted. This would attack the cause,
  and with zero affected stored content the usual legacy-data objection does not apply — but
  alignment is a general text feature and this would change behaviour for all authored prose, not
  just math.
- **Performance.** The predecessor makes no performance claim and neither does this slice. A measured
  follow-up exists there (fold phases 1b and 2 into one walk; add a delimiter early-out).
- **The leading-edge glue case**, where a run's first block follows a non-mergeable inline element
  (`<span>hi</span><div>\[a</div><div>b\]</div>` → `hi\[a b\]`). Pre-existing, unrelated to
  alignment, and recorded as a follow-up in PR #206.
