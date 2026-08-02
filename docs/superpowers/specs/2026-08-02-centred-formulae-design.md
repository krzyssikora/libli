# Centred Formulae — Attribute-Homogeneous Merging for Aligned Blocks

**Status:** approved design, ready to plan.
**Predecessor:** `docs/superpowers/specs/2026-08-01-display-math-authoring-design.md` (shipped as PR #206). This slice closes the limitation that one named and deliberately pinned.

## Purpose

`math_reflow.js` rejoins math spans that the rich-text editor split across block boundaries, so
KaTeX's auto-render — which only matches inside a **single text node** — can typeset multi-line
display math. Its mergeability predicate rejects any `<div>`/`<p>` carrying an effective attribute.
A centred formula carries `class="ta-center"` on every line, so **a formula split across sibling
centred blocks never reflows**.

Scope that precisely: a formula inside a *single* centred block —
`<div class="ta-center">\[a<br>b\]</div>` — already merges today, because the attribute test applies
when classifying that div as a member of its *parent's* run, while the merge among the div's own
text/`<br>` children is unaffected. Only the multi-block shape is broken. Do not plan a fix for the
single-block case.

This slice makes sibling blocks mergeable when their alignment is identical, and preserves that
alignment on the merged result.

### Evidence base — read this before weighing the priority

The predecessor measured the live corpus: **23,520 intact spans, 6 broken**, and the
"attributed boundary" row was **0**. Every real break is a bare `</p><p>`. **No stored content
carries centred display math.** In the repo, `ta-*` appears alongside math delimiters only in test
fixtures — the two this slice inverts, plus `test_walk_descends_into_barriers`, which uses a
`<td class="ta-center">` and is a regression case rather than a subject of this change (see
Regression surface).

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

**The attribute vocabulary on a stored block is small, but not as small as it first appears.** In
`courses/sanitize.py`:

- `ALLOWED_ATTRIBUTES = {"a": {"href", "title", "rel"}}` — `div`/`p` are absent, so **`style` is
  unconditionally stripped** from a stored block.
- `ALIGN_CLASS_VALUES = {"ta-left", "ta-center", "ta-right"}` — exactly three; there is no
  `ta-justify`.
- `ALIGN_CLASS_TAGS = {"p", "div", "h2", "h3", "h4", "blockquote", "li"}`.
- A class value outside the allow-list is **emptied, not dropped**: nh3 emits `class=""` for a tag
  that is a key of `allowed_classes`. Measured: `<p class="evil">x</p>` → `<p class="">x</p>`;
  `<p class="ta-center evil">x</p>` → `<p class="ta-center">x</p>`.
- **Filtering is token-wise, so MULTIPLE align tokens survive together.** Measured against this
  repo's real nh3 config: `<p class="ta-center ta-left">x</p>` → `<p class="ta-center ta-left">x</p>`,
  both tokens kept, order preserved. Any subset of the three can appear.

So a stored `<div>`/`<p>` can present: no attributes, `class=""`, `style=""`, a single align token,
**or two or three align tokens together**. The multi-token case is nonsense that no editor gesture
produces, but it is reachable through hand-authored or pasted HTML, so the design must decide it
rather than assume it away.

**Colour never competes for the same attribute.** `courses/colour.py` sets
`TC_CLASS_TAGS = {"span", "b", "i", "em", "strong", "u", "a"}` — disjoint from `ALIGN_CLASS_TAGS` —
and the sanitiser strips `tc-*` from any block tag. `courses/recolour/colouriser.py:85-96` shows this
is a designed invariant, not an accident: when the importer meets a palette colour on a block tag it
wraps the children in a **new** `<span class="tc-…">` rather than classing the block. A
centred-and-coloured line is therefore
`<div class="ta-center">…<span class="tc-red">…</span>…</div>` — align tokens on the block, colour
on a child span, never competing.

**Whitespace between sibling blocks is real and common.** nh3 preserves inter-tag newlines, and the
imported corpus under `scripts/lal_import/out/` contains **505** `</div>\n<div` and **270**
`</p>\n<p` occurrences. `buildRun` already accounts for this — it ignores whitespace-only text nodes
(`if (/\S/.test(node.data))`, commented "so hand-written test markup with indentation behaves like
nh3 output"). Any rule this design states about text nodes **must** make the same distinction, or
the feature works on fixtures and fails on real content.

**The editor's representation is different, and out of reach.** `text_toolbar.js:46-74` converts
between the stored `ta-*` class and a native `style="text-align:…"` when loading into and saving out
of the contenteditable surface. In the RTE the alignment is therefore a **non-empty `style`**, which
this design classifies as not mergeable — and the surface is in `IGNORE_SELECTOR` regardless. Stored
content and editor content are two representations; only the stored one participates.

## Architecture

Two separate concepts, deliberately not fused into one "signature" string. The predecessor's review
showed that a single overloaded return value invites exactly the ambiguity that breaks the unsigned
path.

### 1. `alignToken(el)` — what alignment a block carries

Returns:

- `""` — the block carries no align class (no `class` attribute, or `class=""`).
- `"ta-left"` / `"ta-center"` / `"ta-right"` — exactly one recognised align token.
- `null` — **ineligible**: the class attribute holds two or more align tokens, or any token that is
  not one of the three. `null` means the block cannot merge at all.

Defined over a normalised **token set** parsed from the class attribute, never over the raw
attribute string, so `class=" ta-center "` and `class="ta-center"` agree.

### 2. `isMergeableBlock(node, extraSelector)` — unchanged in every respect but one

It keeps **all** of today's checks, in today's order:

1. `node.nodeType === 1`
2. `!isIgnored(node, extraSelector)` — the caller's `ignoredTags`/`ignoredClasses` must reach
   **classification**, not merely descent. The existing code comment states why: `walk` refusing to
   descend into an extra-ignored child does not stop `mergeChildren` from folding that child away.
3. `tagName` is `DIV` or `P`
4. every child is a text node or a bare `<br>`
5. **the attribute test, and only this changes:** today `noEffectiveAttributes(node)`; now the node
   passes if its only attributes are an empty `style` and a `class` for which
   `alignToken(node) !== null`.

`noEffectiveAttributes` is **retained unchanged** and still used by `isBareBr`. A `<br>` cannot carry
`ta-*` (`br` is not in `ALIGN_CLASS_TAGS`), so that path has no reason to change.

Worked table:

| element | `isMergeableBlock` | `alignToken` |
|---|---|---|
| `<div>` | true | `""` |
| `<div class="">` | true | `""` |
| `<div style="">` | true | `""` |
| `<div class="" style="">` | true | `""` |
| `<p class="ta-center">` | true | `"ta-center"` |
| `<div class="ta-right">` | true | `"ta-right"` |
| `<div class="ta-center ta-left">` | **false** | `null` |
| `<div data-x="1">` | false | — |
| `<div style="text-align:center">` | false | — |
| `<h3 class="ta-center">` | false (tag) | — |
| `<div class="ta-center">\[a<em>x</em></div>` | false (child shape) | — |

An empty `class`/`style` continues to count as no attribute — load-bearing, because nh3 emits
`class=""` on every line of a pasted formula, and treating it as attributed would make the whole
feature a no-op on the dominant paste path.

### 3. Compatibility — mergeability becomes relative

This is the design's one structural change, and the only one on a shared code path.

Today `mergeChildren` partitions children into runs by asking one independent question per child:
*is this mergeable?* Compatibility is now **pairwise**. Two mergeable blocks `a` and `b` are
compatible iff:

| `alignToken(a)` | `alignToken(b)` | tags | compatible? |
|---|---|---|---|
| `""` | `""` | any (`DIV`/`P` may mix) | **yes** |
| `""` | non-empty | any | no |
| non-empty | `""` | any | no |
| same non-empty token | same non-empty token | **same tag** | **yes** |
| same non-empty token | same non-empty token | different tag | no |
| different non-empty tokens | — | any | no |

Tag equality is required **only** when the token is non-empty. Mixed `DIV`/`P` membership in an
unsigned run stays permitted, because that is the path the six real `</p><p>` repairs travel and it
must come out byte-identical.

### 4. Run partition — how a run acquires its token, and the invariant that follows

Children are scanned left to right, as today. Define a run's **token** as the `alignToken` of its
**first block member**; a run whose token is non-empty is **signed**.

Membership rules, in order:

- A **whitespace-only text node** (no `/\S/`) is **transparent**: it may join any run, signed or not,
  and never establishes or breaks the token. This mirrors `buildRun`, which already ignores such
  nodes, and is what keeps the feature working on real nh3 output rather than only on
  whitespace-free fixtures.
- A **non-whitespace text node** or a **bare `<br>`** may join an *unsigned* run (today's behaviour)
  but **ends a signed run**.
- A **block** joins the run if it is compatible with the run's token (per the table above); otherwise
  it ends the run and starts a new one.
- If a run has not yet established a token (it so far holds only transparent whitespace and/or
  non-whitespace text/`<br>`) and a **signed** block arrives, that block **ends the current run and
  starts a new one**. It does not retroactively sign the run it arrived into.

**The invariant this produces, which the rewrite depends on:** in a signed run every member is
either a block carrying the run's token or a whitespace-only text node, and the run's *first* member
is always a block. Therefore `nodes[group.first]` in a signed run is always a block — never a text
node, never a `<br>`.

### 5. The rewrite — reuse, do not rebuild

When a replacement group belongs to a **signed** run, the merged content goes into the **first
covered block**, which is kept as the wrapper; the rest of the group is removed. Reusing the existing
element rather than constructing a new one avoids re-serialising the class and cannot normalise it.

The ordering is specified, not incidental, because it decides the failure mode (see Error handling):

1. **Insert** the replacement nodes into the wrapper (appended after its existing children).
2. **Remove** the wrapper's original children — they are fully represented in the replacement, since
   every character mapping to `group.first` lies inside `[startOffset, endOffset)`. Skipping this
   step duplicates the first line.
3. **Remove** the sibling blocks — the removal loop runs from `group.first + 1` to `group.last`, not
   from `group.first`, which would delete the wrapper along with the content just placed in it.

Members contributing **zero characters** to `run.text` — a whitespace-only text node, or an empty
line `<div class="ta-center"><br></div>` — appear in `nodes` and inside `[group.first, group.last]`
but never in `run.map`. They are removed by the index-based loop regardless, exactly as they are on
the unsigned path today.

When the run is unsigned, the rewrite is **unchanged**: content goes into the parent and every
covered block is removed.

### 6. Mixed alignment is a barrier — deliberate

When a span crosses blocks that are not compatible, **no merge happens** and the math stays
unrendered, exactly as today.

This is a decided trade-off, not an omission. Adopting the first block's token silently restyles the
author's other lines; dropping alignment discards an explicit author choice. Refusing to merge means
the reflow never guesses at intent. The accepted cost is that an author who centres only some lines
of a formula still gets non-rendering math with no explanation.

## Data flow

Worked examples. `⇒` is one `reflow()` pass. `␤` marks a real newline text node between siblings —
the shape real nh3 output has, and the one fixtures usually omit.

**Homogeneous — merges, alignment preserved:**

```
<div class="ta-center">\[a</div><div class="ta-center">b\]</div>
  ⇒ <div class="ta-center">\[a\nb\]</div>
```

**Homogeneous with real inter-tag whitespace — must also merge:**

```
<div class="ta-center">\[a</div>␤<div class="ta-center">b\]</div>
  ⇒ <div class="ta-center">\[a\nb\]</div>
```

**Empty centred line between the lines — the shape a real author produces first:**

```
<div class="ta-center">\[a</div><div class="ta-center"><br></div><div class="ta-center">b\]</div>
  ⇒ <div class="ta-center">\[a\nb\]</div>
```

**Mixed token, mixed tag, ineligible multi-token — barrier, unchanged:**

```
<div class="ta-center">\[a</div><div>b\]</div>                          ⇒ unchanged
<div class="ta-center">\[a</div><div class="ta-right">b\]</div>         ⇒ unchanged
<p class="ta-center">\[a</p><div class="ta-center">b\]</div>            ⇒ unchanged
<div class="ta-center ta-left">\[a</div><div class="ta-center ta-left">b\]</div>  ⇒ unchanged
```

**Signed block with an element child — barrier, unchanged:**

```
<div class="ta-center">\[a<em>x</em></div><div class="ta-center">b\]</div>  ⇒ unchanged
```

**Signed run interrupted by real text or a bare `<br>` — barrier, unchanged:**

```
<div class="ta-center">\[a</div>stray<div class="ta-center">b\]</div>   ⇒ unchanged
<div class="ta-center">\[a</div><br><div class="ta-center">b\]</div>    ⇒ unchanged
```

**Text leading or trailing a signed run — the run starts at the block, so the text is untouched:**

```
lead <div class="ta-center">\[a</div><div class="ta-center">b\]</div>
  ⇒ lead <div class="ta-center">\[a\nb\]</div>

<div class="ta-center">\[a</div><div class="ta-center">b\]</div> trail
  ⇒ <div class="ta-center">\[a\nb\]</div> trail
```

**Partial coverage — the uncovered block survives separately:**

```
<div class="ta-center">x</div><div class="ta-center">\[a</div><div class="ta-center">b\]</div>
  ⇒ <div class="ta-center">x</div><div class="ta-center">\[a\nb\]</div>
```

**Nested — the cascade stops one level earlier than on the unsigned path:**

```
unsigned (today):  <div><div>\[a</div><div>b\]</div></div>
                     ⇒ <div>\[a\nb\]</div>

signed  (this):    <div><div class="ta-center">\[a</div><div class="ta-center">b\]</div></div>
                     ⇒ <div><div class="ta-center">\[a\nb\]</div></div>
```

This asymmetry is intended and must be pinned by a test. On the unsigned path the merge deletes the
child blocks, which makes the parent newly mergeable and lets post-order folding continue within one
pass — what `test_nested_split_merges_after_post_order_folding` asserts. On the reuse path the
wrapper survives, so the parent retains an element child and the cascade stops. The wrapper *must*
survive to carry the alignment, so this is the price of the feature, not a defect.

**Unsigned — today's behaviour, unchanged:**

```
<p>\[a</p><p>b\]</p>   ⇒ \[a\nb\]        (content into the parent, both blocks removed)
```

### Idempotence

The naive argument — "after one pass the formula is a single block holding one text node, so rule 4
skips it" — is **insufficient**, and stating it that way is how the predecessor got idempotence wrong
twice. It holds only when the span covers the entire covered range. With trailing prose
(`…b\] tail</div>`), an authored `<br>` outside the span, or a synthetic trailing boundary pulled in
by `endOffset`, the wrapper ends up holding several nodes — `[text, br, text]` or `[text, text]`.

The argument that actually covers those shapes is **leaf identity**: rule 4 skips a span iff
`run.leaf[span.start] === run.leaf[span.end - 1]`, i.e. both ends live in the same Text node. After a
rewrite the merged span occupies exactly one Text node inside the wrapper, so on the next pass its
ends share a leaf and it is skipped — regardless of what else the wrapper holds.

That argument must be **measured, not trusted**. See the idempotence fixtures below.

## Error handling

Mostly unchanged — `IGNORE_SELECTOR`, the root guards and the per-element `try/catch` in `walk` are
untouched, so no reflow can reach a serialized contenteditable surface, and a throw still leaves the
traversal running and emits a `console.warn`. A `null` `alignToken` is a **classification** result,
not an error: it produces a barrier, the same outcome an unmergeable element produces today.

**One genuinely new failure window, and why the ordering in §5 is what it is.** Today `mergeChildren`
inserts replacement nodes and *then* removes the originals, so a throw between those loops leaves
both in the DOM — duplicated content, ugly but non-destructive. The reuse path adds a step that
removes the wrapper's original children. If that removal ran *before* the insertion, a throw in
between would lose the line outright, which is strictly worse than duplication. The specified order —
insert, then remove originals, then remove siblings — preserves the existing insert-before-remove
invariant so the worst case stays duplication.

`findEndOfMath` / `findSpans` **must not be touched**. A 4,044-input differential proof of
byte-equivalence against the vendored auto-render depends on them, and that proof is void if they
change.

## Testing

### Invert the two pinning tests, without losing their coverage

- `tests/test_e2e_math_reflow.py::test_centred_display_math_is_not_reflowed` becomes its positive
  twin: `.katex` count 1, `.katex-error` count 0, one surviving `ta-center` block, and no
  `</div><div` in the markup.
- In `tests/test_e2e_math_reflow_dom.py::test_barriers_are_not_merged_across`, the `ta-center` case
  moves out. Because deleting a barrier case **weakens** that test, the barrier cases below replace
  it.

### Barrier cases — each must come out byte-identical

1. `ta-center` + bare `<div>`
2. `ta-center` + `ta-right`
3. `<p class="ta-center">` + `<div class="ta-center">` — same token, different tag
4. a signed run interrupted by a **non-whitespace** parent-level text node
5. a signed run interrupted by a parent-level bare `<br>`
6. two `<div class="ta-center ta-left">` blocks — ineligible multi-token
7. a signed block holding an element child (`<em>`) — the child-shape check
8. two `ta-center` divs under `{ignoredTags: ['div']}`, from a `<section>` root — the extraSelector
   path. The root must be `<section>`, not `<div>`: the existing
   `test_caller_ignored_tags_are_unioned_in` records that a `<div>` root makes this pass for the
   wrong reason.

### Happy-path cases

- homogeneous merge producing exactly one wrapper — **exact-equality** assertion, not membership
- the same shape **with a real newline text node between the blocks** — the corpus shape; this is the
  case that fails if whitespace transparency is missed
- an empty centred line (`<div class="ta-center"><br></div>`) between two centred lines
- `ta-left` and `ta-right` as well as `ta-center`, so nothing is hardcoded to centre
- text leading a signed run, and text trailing it, each untouched
- partial coverage: a span covering only the last two of three centred divs, first block surviving
- the nested case, asserting the cascade stops with the wrapper intact
- phase-2 interaction: a centred `\(\begin{cases}…\)` split across lines comes out **merged and
  promoted**

### Idempotence fixtures — the signed analogues of all three existing ones

One fixture is a regression in rigour: the predecessor needed three discriminating shapes and its
fuzz found 14/500 divergent. Required, each asserting pass 1 == pass 2:

- a signed block holding an intra-block `<br>`-split span
- two spans with prose between the groups, inside signed blocks
- the signed analogue of the `map`-vs-`leaf` discriminating shape recorded in `math_reflow.js`'s
  rule-4 comment

### Falsification — a mutant per test, because the obvious one does not work

"Revert the change and watch it redden" is **unsatisfiable for the barrier cases**: with the change
reverted every `ta-*` block is already a barrier, so all eight stay green. Each test names the mutant
that must redden it, and the RED output of each is recorded:

| test group | mutant that must redden it |
|---|---|
| happy path, idempotence | revert the change (blocks with a token are barriers again) |
| barrier 1–3 | a run adopts the token/tag of its first block instead of requiring compatibility |
| barrier 4–5 | signed runs admit non-whitespace text nodes and `<br>`s |
| barrier 6 | `alignToken` returns the first token instead of `null` for multi-token |
| barrier 7 | drop the child-shape loop from `isMergeableBlock` |
| barrier 8 | `isMergeableBlock` stops receiving `extraSelector` |
| whitespace happy-path case | whitespace-only text nodes end a signed run |
| nested case | (documents behaviour; reverting changes it) |

### Idempotence beyond the fixtures

The predecessor's "500-document structured generator" was **ad-hoc and was never committed** — it
exists only as a claim in a code comment and a docstring. Do not plan around reusing it. Instead:

- **Committed:** a deterministic parametrized idempotence test over an enumerated cross-product of
  shapes — block tag (`div`/`p`) × token (`""`, `ta-center`, `ta-right`) × separator (none,
  whitespace text, `<br>`, non-whitespace text) × span placement (whole run, trailing prose,
  intra-block `<br>`) — asserting for each: pass 1 == pass 2, and `textContent` (whitespace-normalised)
  unchanged from the input. This is the artefact that survives.
- **One-shot, recorded in the PR body only:** a larger randomised run may be performed for
  confidence, but if so its generator, seed and shape count must be stated in the PR body so the
  claim is reproducible. An unreproducible "fuzzed at N documents" claim is worth nothing.

Define both terms: **divergence** = pass N+1 output HTML differs from pass N; **text loss** =
whitespace-normalised `textContent` of the root differs before vs after any pass.

### Regression surface

- The six real `</p><p>` repairs — unsigned runs, unchanged path.
- The `data-x="1"` barrier case: attributes outside the align vocabulary still block.
- `test_empty_class_attribute_still_merges` — `<div style="">` and `<div class="">` still merge.
- `tests/test_e2e_math_reflow_dom.py::test_walk_descends_into_barriers` merges inside a
  `<td class="ta-center">` — a `td` is not `DIV`/`P`, so the merge happens among its children and the
  cell's class is irrelevant. That must stay true.
- Headings, `<li>`, `<blockquote>` stay barriers. The sanitiser permits `ta-*` on them, but
  `isMergeableBlock` only ever accepted `DIV`/`P` and this does not widen that.

## Definition of done

- Full non-e2e suite: **4566 passed, 0 skipped**, measured by the controller on `master` at
  `671c57f0` with `-n 4`. The predecessor's plan predicted "4565 passed, 1 skipped" — the same total;
  `test_db_quiesce.py` carries a dynamic skip that runs as a pass depending on session state. Treat
  the **total** as the invariant, not the pass/skip split. Every test this slice adds is e2e, so the
  non-e2e total should not move.
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
- **General attribute-set homogeneity.** Considered and rejected: the only attributes that reach a
  stored block are an empty `style` and align tokens, so a general rule buys nothing today while
  having to answer harder questions (duplicate `id`s on rebuild, `data-*` semantics).
- **Changing the authoring surface** so per-line `ta-*` is never emitted. This would attack the cause,
  and with zero affected stored content the usual legacy-data objection does not apply — but
  alignment is a general text feature and this would change behaviour for all authored prose, not
  just math.
- **Performance.** The predecessor makes no performance claim and neither does this slice. A measured
  follow-up exists there (fold phases 1b and 2 into one walk; add a delimiter early-out).
- **The leading-edge glue case**, where a run's first block follows a non-mergeable inline element
  (`<span>hi</span><div>\[a</div><div>b\]</div>` → `hi\[a b\]`). Pre-existing, unrelated to
  alignment, and recorded as a follow-up in PR #206.
