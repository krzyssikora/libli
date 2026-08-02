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

So a stored `<div>`/`<p>` can present: no attributes, `class=""`, a single align token, **or two or
three align tokens together**. The multi-token case is nonsense that no editor gesture produces, but
it is reachable through hand-authored or pasted HTML, so the design must decide it rather than assume
it away.

`style=""` is **not** in that list: the attribute is removed entirely, not emptied — measured,
`sanitize_html('<div style="">x</div>')` → `<div>x</div>`. It is a DOM-level shape only, reachable
from hand-written test markup, and it stays in the §2 eligibility table because
`test_empty_class_attribute_still_merges` asserts on it.

**Colour never competes for the same attribute.** `courses/colour.py` sets
`TC_CLASS_TAGS = {"span", "b", "i", "em", "strong", "u", "a"}` — disjoint from `ALIGN_CLASS_TAGS` —
and the sanitiser strips `tc-*` from any block tag. `courses/recolour/colouriser.py:85-96` shows this
is a designed invariant, not an accident: when the importer meets a palette colour on a block tag it
wraps the children in a **new** `<span class="tc-…">` rather than classing the block. A
centred-and-coloured line is therefore
`<div class="ta-center">…<span class="tc-red">…</span>…</div>` — align tokens on the block, colour
on a child span, never competing.

**Whitespace between sibling blocks is real and common.** nh3 preserves inter-tag newlines. Counting
over the **JSON-decoded string values** in `scripts/lal_import/out/**.json` (835 files — a raw grep
of the files finds nothing, because the markup is JSON-escaped), the imported corpus contains **505**
`</div>\n<div` and **270** `</p>\n<p` occurrences. `buildRun` already accounts for this — it ignores
whitespace-only text nodes (`if (/\S/.test(node.data))`, commented "so hand-written test markup with
indentation behaves like nh3 output"). Any rule this design states about text nodes **must** make the
same distinction, or the feature works on fixtures and fails on real content.

**The editor's representation is different, and out of reach.** `text_toolbar.js:46-74` converts
between the stored `ta-*` class and a native `style="text-align:…"` when loading into and saving out
of the contenteditable surface. In the RTE the alignment is therefore a **non-empty `style`**, which
this design classifies as not mergeable — and the surface is in `IGNORE_SELECTOR` regardless. Stored
content and editor content are two representations; only the stored one participates.

## Architecture

Two separate concepts, deliberately not fused into one "signature" string. An earlier draft used a
single overloaded return value and it produced exactly the ambiguity that breaks the unsigned path.

### 1. `alignToken(el)` — what alignment a block carries

Returns:

- `""` — the block carries no align class (no `class` attribute, or a class whose parsed token set is
  empty).
- `"ta-left"` / `"ta-center"` / `"ta-right"` — exactly one recognised align token.
- `null` — **ineligible**: the token set holds two or more align tokens, or any token that is not one
  of the three. `null` means the block cannot merge at all.

Defined over a normalised **token set** parsed from the class attribute, never over the raw attribute
string, so `class=" ta-center "` and `class="ta-center"` agree.

**One deliberate, negligible widening.** Because the token set is parsed, `class=" "` (whitespace
only) yields an empty set and therefore `""` — mergeable. Today `noEffectiveAttributes` compares
`attr.value === ""` exactly, so `<div class=" ">` is a barrier. Special-casing it back would be
arbitrary; a whitespace-only class has no rendering effect, so it is allowed and pinned by a test.
`noEffectiveAttributes` itself stays byte-exact for `isBareBr`.

### 2. `isMergeableBlock(node, extraSelector)` — unchanged in every respect but one

It keeps **all** of today's checks. Both predicates are pure, so the order below is immaterial; for
reference, in `math_reflow.js:153-165` the attribute test precedes the child-shape loop:

1. `node.nodeType === 1`
2. `!isIgnored(node, extraSelector)`
3. `tagName` is `DIV` or `P`
4. **the attribute test, and only this changes:** today `noEffectiveAttributes(node)`; now the node
   passes if its only attributes are an empty `style` and a `class` for which
   `alignToken(node) !== null`.
5. every child is a text node or a bare `<br>`

**A note on check 2, because three successive drafts of the mutant table got it wrong.**
`isIgnored` is checked **twice** on the live path for a `DIV`/`P`, both before and after this slice,
and the two checks are **mutually redundant** — so no single-deletion mutant can ever redden an
ignore test.

- *Today:* `isMergeableBlock`'s only caller is `isMergeable` (`math_reflow.js:170`), which returns
  `false` on `isIgnored(node, extraSelector)` at line 169 before delegating.
- *After this slice:* §4's classifier replaces that call site, but the classifier's own first test is
  the same `isIgnored → BARRIER` guard, and check 2 below is retained. So the pair persists; only its
  members change.

A mutant that means to exercise the ignore path must therefore remove **both** checks (see the
falsification table). Dropping either one alone leaves the other short-circuiting the case, which is
how three separate drafts of that row shipped vacuous.

Worked table:

| element | `isMergeableBlock` | `alignToken` |
|---|---|---|
| `<div>` | true | `""` |
| `<div class="">` | true | `""` |
| `<div class=" ">` | true | `""` (deliberate widening, see §1) |
| `<div style="">` | true | `""` |
| `<div class="" style="">` | true | `""` |
| `<p class="ta-center">` | true | `"ta-center"` |
| `<div class="ta-center" style="">` | true | `"ta-center"` |
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

### 4. Run partition — the classifier, the signature, and the invariant

**The classifier.** The partition loop today calls one predicate,
`isMergeable(children[i], extraSelector)` (`math_reflow.js:293`), which returns `true` for *any* text
node (line 168, before the `isIgnored` check) and folds `isBareBr` and `isMergeableBlock` into a
single boolean. That is too coarse for these rules, which need five outcomes. Introduce a classifier
used by the partition loop that returns one of:

The classifier's **first test, for element nodes, is `isIgnored(node, extraSelector) → BARRIER`.**
That is not decoration: today the ignore check lives in `isMergeable` (line 169) and runs *before*
`isBareBr`, so an ignored `<br>` is a barrier. A classifier that tested `isBareBr` alone would newly
admit a `<br>` under `{ignoredTags:['br']}` into a run — making
`<div>\[a</div><br><div>b\]</div>` merge where it does not today. With the guard, the classifier's
behaviour is identical to `isMergeable`'s.

| kind | test |
|---|---|
| `WS_TEXT` | text node, no `/\S/` |
| `TEXT` | text node with `/\S/` |
| `BR` | element, not ignored, `isBareBr(node)` |
| `BLOCK` | element, not ignored, `isMergeableBlock(node, extraSelector)`, carrying `alignToken(node)` and `tagName` |
| `BARRIER` | anything else |

The classifier **replaces `isMergeable`'s only call site.** `isMergeable` is referenced exactly twice
in `courses/static/courses/js/` — its definition (line 167) and the partition loop (line 293) — so
once the loop calls the classifier the function is dead. Delete it rather than leaving a dead
predicate that a future reader will assume is authoritative. `alignToken` is called only from the
classifier and from `isMergeableBlock`'s attribute check.

**The run signature** is the ordered pair `(alignToken, tagName)` taken from the run's **first
`BLOCK` member**. A run whose token is non-empty is **signed**. A signed run therefore has a tag as
well as a token, which is what makes §3's tag column evaluable.

**Membership rules**, applied left to right. They are labelled **M1–M5** because this document also
cites the predecessor's own numbered rules — "rule 4" (the leaf-based span skip) and "rule 5" (the
rewrite path) — which are different things with colliding numbers.

M1. A `BLOCK` arriving into a run whose signature is **not yet established** always joins, and
   establishes the run's signature. (M5 is the one exception: a *signed* block arriving into a
   run that already holds `TEXT`/`BR` members breaks it instead.) This clause matters — a literal
   "not compatible with a signature that does not exist ⇒ break the run" reading would break the
   ordinary `prose <div>\[a</div><div>b\]</div>` shape.
M2. A `BLOCK` arriving into a run whose signature **is** established joins iff it is compatible with
   that signature: when the run's token is `""`, the block's token must be `""` (tag irrelevant, so
   `DIV`/`P` may mix); when the run's token is non-empty, the block's `(alignToken, tagName)` must
   equal the run's pair. Otherwise it ends the run and starts a new one, carrying its own signature.
M3. `TEXT` and `BR` may join a run whose signature is not yet established, or an **unsigned** run
   (today's behaviour). They **end a signed run and become the first member of a new, unestablished
   run** — they are not excluded from every run. The distinction is not cosmetic: excluding them
   would regress a shape that merges on master today, e.g.
   `<div class="ta-center">x</div>\[a<div>b\]</div>`, where the run is
   `[TEXT("\[a"), <div>]`. None of the barrier cases discriminates the two readings, so this has its
   own fixture.
M4. `WS_TEXT` is **transparent**: it never establishes a signature and never ends a run whose
   signature is already established — signed or not. This mirrors `buildRun`, which already ignores
   such nodes, and is what keeps the feature working on real nh3 output rather than only on
   whitespace-free fixtures.
M5. Before a signature is established, a run may have accumulated `TEXT` and `BR` members. If a
   **signed** `BLOCK` then arrives, it **ends that run and starts a new one**; it does not
   retroactively sign the run it arrived into. This is what M3 defers to.

   `WS_TEXT` is deliberately **not** in that list, so a run holding only transparent whitespace stays
   unestablished and an arriving signed block simply joins it (M1). A leading newline text node
   before the first centred block — the corpus shape, and the shape of every indented hand-written
   fixture — therefore does not break the run. Both readings produce identical DOM output, since
   `WS_TEXT` contributes no characters; this one is chosen because it keeps the common case on the
   ordinary path rather than the exception path.

**The invariant the rewrite depends on, and its actual derivation.** In a signed run every member is
either a `BLOCK` matching the run's signature or a `WS_TEXT`. It is tempting to argue "the first
member is a block, therefore `nodes[group.first]` is a block" — that is a **non-sequitur**:
`group.first` is `run.map[span.start]`, not index 0 of the run (the partial-coverage example below
has `group.first == 1`). The correct derivation goes through the map: `buildRun` skips whitespace-only
text nodes (`math_reflow.js:226`), so **no zero-character member ever appears in `run.map`**; in a
signed run the only non-`BLOCK` members are `WS_TEXT`, which contribute zero characters; therefore
every `run.map` value in a signed run — including `group.first` and `group.last` — indexes a block.
The same argument is why §5's zero-character-member paragraph holds.

### 5. The rewrite — reuse, do not rebuild

When a replacement group belongs to a **signed** run, the merged content goes into the **first
covered block**, which is kept as the wrapper; the rest of the group is removed. Reusing the existing
element rather than constructing a new one avoids re-serialising the class and cannot normalise it.

`group.first` and `group.last` index the **run-local `nodes` array**, not `element.childNodes` — the
distinction `test_content_before_the_run_is_not_destroyed` exists to guard, and which cost real
author content when it was got wrong (see the comment at `math_reflow.js:369-375`). The new loop
below uses the same run-local indices.

The ordering is specified, not incidental, because it decides the failure mode (see Error handling):

0. **Snapshot** `wrapper.childNodes` into an array *before* step 1. After the insert, the replacement
   nodes are themselves children of the wrapper, so "the original children" is only recoverable from
   a snapshot. An implementation that reads step 2 as `while (wrapper.firstChild) wrapper.removeChild(…)`
   empties the wrapper and loses the merged line — exactly the destructive outcome this ordering
   exists to prevent.
1. **Insert** the replacement nodes into the wrapper, appended after its existing children.
2. **Remove all** of the snapshotted original children — unconditionally, not "those represented in
   the replacement". Most are represented, since every character mapping to `group.first` lies inside
   `[startOffset, endOffset)`; but a child contributing **zero** characters is not represented at all
   — a leading or collapsed `<br>` inside the wrapper, where `pushBlockText`'s `text.length && …`
   guard (`math_reflow.js:214`) suppresses the newline. Such a child is dropped, which is exactly
   what the unsigned path does today when it deletes the whole block. An implementer who adds a
   "only remove represented children" guard here ships duplicated content.
3. **Remove** the sibling blocks — from `nodes[group.first + 1]` through `nodes[group.last]`, never
   from `group.first`, which would delete the wrapper along with the content just placed in it.
   **Only the start index changes**: the existing loop's `nodes[i] && nodes[i].parentNode === element`
   guard (`math_reflow.js:380-384`) is retained. Dropping it turns any unexpected detachment into a
   thrown `NotFoundError`, and Error handling below depends on the throw window staying narrow.

Members contributing zero characters — a `WS_TEXT`, or an empty line
`<div class="ta-center"><br></div>` — appear in `nodes` and inside `[group.first, group.last]` but
never in `run.map`. Step 3's index-based loop removes them regardless, exactly as the unsigned path
does today.

When the run is unsigned, the rewrite is **unchanged**: content goes into the parent and every
covered block is removed.

### 6. Mixed alignment is a barrier — deliberate

When a span crosses blocks that are not compatible, **no merge happens** and the math stays
unrendered, exactly as today.

This is a decided trade-off, not an omission. Adopting the first block's signature silently restyles
the author's other lines; dropping alignment discards an explicit author choice. Refusing to merge
means the reflow never guesses at intent. The accepted cost is that an author who centres only some
lines of a formula still gets non-rendering math with no explanation.

## Data flow

Worked examples. `⇒` is one `reflow()` pass. `␤` marks a real newline text node between siblings —
the shape real nh3 output has, and the one fixtures usually omit.

**Homogeneous — merges, alignment preserved:**

```
<div class="ta-center">\[a</div><div class="ta-center">b\]</div>
  ⇒ <div class="ta-center">\[a\nb\]</div>
```

**Homogeneous `<p>` — the tag is preserved, not normalised to `<div>`:**

```
<p class="ta-center">\[a</p><p class="ta-center">b\]</p>
  ⇒ <p class="ta-center">\[a\nb\]</p>
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

**Two spans in one signed run — the boundary newline moves INSIDE the first wrapper:**

```
<div class="ta-center">\[a</div><div class="ta-center">b\]</div><div class="ta-center">\[c</div><div class="ta-center">d\]</div>
  ⇒ <div class="ta-center">\[a\nb\]\n</div><div class="ta-center">\[c\nd\]</div>
```

Note the trailing `\n` inside the first wrapper. Group 1's `endOffset` extends past the span to
include the synthetic boundary newline mapping to child 1, so on the reuse path that newline lands
inside the wrapper rather than remaining a bare text node between the groups (where the unsigned path
leaves it, pinned by `test_two_spans_in_one_run`). **It is deliberately not trimmed**: the unsigned
path keeps that newline on purpose — dropping it is what glued author prose together in the
predecessor's "tailhead" defect — and adding a signed-only trim would be a special case with the same
failure mode. Any exact-equality assertion over a two-span signed fixture must expect it.

**Nested — one nesting level is preserved that the unsigned path removes:**

```
unsigned (today):  <div><div>\[a</div><div>b\]</div></div>
                     ⇒ <div>\[a\nb\]</div>

signed  (this):    <div><div class="ta-center">\[a</div><div class="ta-center">b\]</div></div>
                     ⇒ <div><div class="ta-center">\[a\nb\]</div></div>
```

The asymmetry is intended and must be pinned by a test. It is **not** that post-order folding
"continues" on the unsigned path — it does not; after the inner merge, rule 4 skips the span at the
outer level because both ends share one leaf, which is why the unsigned output still has one `<div>`.
The real difference is that the unsigned rewrite deletes every covered block and hoists content into
the parent, so one nesting level disappears; the reuse path keeps one block, so the level count is
preserved. The observable consequence is that the parent retains an element child, so a
grandparent-level span crossing the outer block can still merge on the unsigned path but not on the
signed one. The wrapper *must* survive to carry the alignment, so this is the price of the feature.

**Unsigned — today's behaviour, unchanged:**

```
<p>\[a</p><p>b\]</p>            ⇒ \[a\nb\]   (content into the parent, both blocks removed)
<p>\[a</p><div>b\]</div>        ⇒ \[a\nb\]   (MIXED TAG — unsigned runs ignore the tag)
```

The mixed-tag case is not a curiosity: `courses.css:24-25` records that Chromium's contenteditable
emits `<div>` for Enter while the first block may be a `<p>`, so `<p>…</p><div>…</div>` is ordinary
RTE output. It is also the only shape that exercises §3's "tag equality is required **only** when the
token is non-empty" rule — the `</p><p>` repairs that motivate the rule are same-tag and therefore
prove nothing about it.

### Idempotence

The naive argument — "after one pass the formula is a single block holding one text node, so rule 4
skips it" — is **insufficient**, and stating it that way is how the predecessor got idempotence wrong
twice. It holds only when the span covers the entire covered range. With trailing prose
(`…b\] tail</div>`), an authored `<br>` outside the span, or the trailing synthetic newline shown in
the two-span example above, the wrapper ends up holding several nodes — `[text, br, text]` or
`[text, text]`.

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

`findEndOfMath` / `findSpans` **must not be touched**. They are a pinned port of auto-render's
`splitAtDelimiters`/`findEndOfMath`, and this slice has no reason to go near them. (PR #206's body
records a differential run of 4,044 inputs against the vendored file; that harness was ad-hoc and is
not committed, so treat the rule as standing on the port's purpose, not on the figure.)

## Testing

### Invert the two pinning tests, without losing their coverage

- `tests/test_e2e_math_reflow.py::test_centred_display_math_is_not_reflowed` becomes its positive
  twin: `.katex` count 1, `.katex-error` count 0, one surviving `ta-center` block, and no
  `</div><div` in the markup. **Rename the function** (e.g. `test_centred_display_math_is_reflowed`)
  and rewrite its docstring, which currently opens "KNOWN LIMITATION, pinned deliberately" and would
  otherwise describe the opposite of what it asserts. Its section header
  `# ---- Step 3: the named-limitation case ----` becomes stale too.
- In `tests/test_e2e_math_reflow_dom.py::test_barriers_are_not_merged_across`, the `ta-center` case
  moves out. Because deleting a barrier case **weakens** that test, the barrier cases below replace
  it.
- **Two stale case counts, in two different files** — both move when this slice lands, and neither
  is where a careless reading would look. `tests/test_e2e_math_reflow.py`'s **module docstring**
  says "already proves the module's DOM mechanics in isolation (65 cases)";
  `tests/test_e2e_math_reflow_dom.py` has no count in its module docstring, but line 27, inside the
  `_allow_sync_orm_under_playwright` fixture docstring, says "63 cases".
  **Both are already wrong on master** — `pytest --collect-only` on the DOM file reports **66** — and
  they disagree with each other despite describing the same quantity. So do not adjust them by this
  slice's delta: run `--collect-only` and set both to the measured number, which must end up equal.
- **A stale reference to a function this slice deletes:** `tests/test_e2e_math_reflow_dom.py:410`,
  in `test_caller_ignored_tags_are_unioned_in`'s docstring, says "the divs merge unless extraSelector
  is threaded into `isMergeable`". §4 deletes `isMergeable`, and this is the very test barrier 8 is
  modelled on. Retarget the sentence at the classifier and `isMergeableBlock`.

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
- **two `<p class="ta-center">` blocks** merging into a single surviving `<p class="ta-center">`,
  exact-equality. Tag equality is load-bearing in §3 and the only other `<p>` case is a barrier, so
  without this an implementation that restricted the reuse path to `DIV` would pass everything else.
- **`<p>\[a</p><div>b\]</div> ⇒ \[a\nb\]`** — unsigned, mixed tag, exact-equality. This is the only
  case that exercises "tag equality only when the token is non-empty", and it is ordinary Chromium
  RTE output (`courses.css:24-25`). Without it, an implementation that applies tag equality
  unconditionally — the simpler reading of "the signature is a pair" — passes every other happy-path,
  barrier, idempotence and regression case while silently regressing a shipped shape.
- the **homogeneous signed** shape with a real newline text node between the blocks
  (`<div class="ta-center">\[a</div>␤<div class="ta-center">b\]</div>`) — the corpus shape, and the
  case that fails if whitespace transparency is missed. It must be anchored to the *signed* shape,
  not the mixed-tag one above it: in an unsigned run every text node is already mergeable on master,
  so an unsigned whitespace fixture passes today and under every mutant, proving nothing.
- a signed run **followed by** a non-whitespace text node that begins a new merging run
  (`<div class="ta-center">x</div>\[a<div>b\]</div> ⇒ <div class="ta-center">x</div>\[a\nb\]`) —
  pins that `TEXT` ending a signed run starts a new one rather than being excluded (M3)
- a signed run **preceded** by a newline text node, merging normally (M5's `WS_TEXT` carve-out).
  **This one is a regression guard, not a discriminating fixture, and that is deliberate** — M5
  itself records that all readings of a leading `WS_TEXT` produce identical DOM, so no mutant can
  redden it. It is listed in the table below as such, so the "a mutant per test" contract is not
  silently broken.
- an empty centred line (`<div class="ta-center"><br></div>`) between two centred lines
- `ta-left` and `ta-right` as well as `ta-center`, so nothing is hardcoded to centre
- `<div class=" ">` merging — the deliberate widening in §1
- text leading a signed run, and text trailing it, each untouched
- partial coverage: a span covering only the last two of three centred divs, first block surviving
- two spans in one signed run, exact-equality **including the trailing `\n` inside the first wrapper**
- the nested case, asserting one nesting level is preserved
- phase-2 interaction: a centred `\(\begin{align*}…\)` split across two `ta-center` blocks comes out
  **merged and promoted**. Use `align*`, not `cases`: `DISPLAY_ONLY_ENVS` (`math_reflow.js:427-431`)
  is ten exact literals and `cases` is deliberately not among them, so a `\(\begin{cases}…\)` span
  merges but never promotes and the assertion would fail.

### Idempotence fixtures — the signed analogues of all three existing ones

One fixture would be a regression in rigour: the predecessor needed three discriminating shapes.
Required, each asserting pass 1 == pass 2 **and** a positive precondition that pass 1 actually merged
(assert the wrapper count, or that `</div><div` is absent) — without that precondition a no-op
satisfies the test trivially:

- **`<div class="ta-center">\(x<br>y\) prose \[a</div><div class="ta-center">b\]</div>`** — given as
  literal markup, not as "a signed block holding an intra-block `<br>`-split span", because the
  trailing `prose \[a` **and** the second signed block are what make the `textFragment` leaf guard
  fire: the guard only executes from an enclosing merge's covered-but-unspanned range. Reduced to
  `<div class="ta-center">\(x<br>y\)</div>`, both `textFragment` calls are empty, the outer span is a
  leaf skip, and the fixture stays green under its own mutant while still satisfying the "pass 1
  actually merged" precondition.
- two spans with prose between the groups, inside signed blocks
- the signed analogue of the `map`-vs-`leaf` discriminating shape recorded in `math_reflow.js`'s
  rule-4 comment. **Verify it still discriminates rather than assuming it does:** the recorded shape
  was measured against the *unsigned* rewrite, which hoists into the parent, whereas the reuse path
  leaves a different node layout going into pass 2. If the signed analogue does not go RED under the
  map-based rule-4 mutant, search for a shape that does and use that instead — keeping an
  unfalsifiable fixture here would be a third vacuous entry in the table below.

### Falsification — a mutant per test, because the obvious one is vacuous twice over

"Revert the change and watch it redden" is **unsatisfiable for the barrier cases** (with the change
reverted every `ta-*` block is already a barrier, so all eight stay green) **and for the idempotence
cases** (reverting leaves every signed *cross-block* merge suppressed, so pass 1 is either a no-op or
is already idempotent on its own — either way pass 1 == pass 2 holds trivially. Note it is not always
a no-op: an intra-block `\(x<br>y\)` span still merges during the block's own `mergeChildren` visit,
which is unaffected by that block's attributes). Each test names the mutant that must redden it, and
the RED output of each is recorded:

| test group | mutant that must redden it |
|---|---|
| happy path (**signed** cases only) | revert the change (blocks with a token are barriers again) |
| mixed-tag unsigned case | require tag equality even when the token is `""`. Listed separately because it passes on master, so "revert the change" cannot redden it. |
| M3 case (`TEXT` after a signed run) | a `TEXT`/`BR` that ends a signed run is excluded from every run instead of starting a new one |
| `<div class=" ">` case | `alignToken` compares the raw class attribute string instead of a parsed token set, restoring `class=" "` as a barrier |
| leading-`WS_TEXT` case | **none — regression guard only.** M5 records that every reading of a leading `WS_TEXT` yields identical DOM, so no mutant exists. Listed explicitly rather than omitted, so its absence is a decision. |
| barrier 1–3 | a run adopts the signature of its first block instead of requiring compatibility |
| barrier 4–5 | signed runs admit `TEXT` and `BR` members |
| barrier 6 | `alignToken` returns the first token instead of `null` for multi-token |
| barrier 7 | drop the child-shape loop from `isMergeableBlock` |
| barrier 8 | delete (or drop `extraSelector` from) **both** the classifier's `isIgnored → BARRIER` guard **and** `isMergeableBlock`'s own `isIgnored` check. Removing either alone is vacuous — the other short-circuits the case and the block stays a barrier, which is how three drafts of this row shipped unfalsifiable (§2). Verify RED before recording it. |
| idempotence, signed analogues of fixtures 1–2 | remove the `!run.leaf[i]` guard from `textFragment`, so an already-merged `\n` is re-split into `text` / `<br>` / `text` |
| idempotence, map-vs-leaf analogue | revert rule 4 to the `map`-based comparison (`if (first !== last)`). This mutant reddens **only** this fixture: `test_reflow_is_idempotent`'s existing docstring records as measured that the other two "do NOT pin rule 4 itself", and the signed analogues inherit that. |
| whitespace happy-path case | whitespace-only text nodes end a signed run |
| two-span case | trim the trailing synthetic newline from the wrapper |
| nested case | (documents behaviour; reverting changes it) |

**§5's ordering has no black-box mutant, and that is not an oversight.** Every replacement node is
freshly created (`textFragment`'s `createTextNode`/`createElement`, and the `doc.createTextNode` of
the sliced run text), so none aliases a wrapper child; "append then remove originals" and "remove
originals then append" leave the wrapper holding identical children. The ordering only changes what
survives a throw landing *between* the two loops, so it is a fault-tolerance requirement verified by
inspection. If it is to be tested at all, it needs fault injection — stub the removal loop to throw
and assert the line survives duplicated rather than vanishing — and that is optional.

### Idempotence beyond the fixtures

The predecessor's "500-document structured generator" was **ad-hoc and was never committed** — it
exists only as a claim in a code comment and a docstring. Do not plan around reusing it. Instead:

- **Committed:** a deterministic parametrized idempotence test over an enumerated cross-product of
  shapes — block tag (`div`/`p`) × token (`""`, `ta-center`, `ta-right`) × separator (none,
  whitespace text, `<br>`, non-whitespace text) × span placement (whole run, trailing prose,
  intra-block `<br>`) — asserting for each: pass 1 == pass 2, `textContent` **with all whitespace
  removed** (see the definition below — *not* "normalised", which would redden every merging shape)
  unchanged from the input, **and**, for the shapes expected to merge, that pass 1 changed the
  markup.

  **The three placement templates, written out so the predicate below has a fixed domain** — `T` is
  the block tag, `C` the class attribute (absent for token `""`), `SEP` the separator:

  ```
  whole run:        <T C>\[a</T>SEP<T C>b\]</T>
  trailing prose:   <T C>\[a</T>SEP<T C>b\] tail</T>
  intra-block <br>: <T C>\[a<br>b\]</T>SEP<T C>c</T>
  ``` The last clause is what stops the whole enumeration passing vacuously under a mutant that
  suppresses merging.

  **The merge-expected predicate is stated here as data, not derived from the implementation's
  output** — deriving it from what the code does would make the anti-vacuity clause circular, which
  is precisely what it exists to prevent. A shape is expected to merge iff:

  > `placement == intra-block <br>` (merges regardless of separator, since the span never crosses
  > the block boundary) **OR** `token == ""` **OR** `separator ∈ {none, whitespace}`.

  Equivalently: only a *signed* run with a `<br>` or non-whitespace-text separator is expected not to
  merge. If an implementation disagrees with this table, the table is the spec and the implementation
  is wrong until argued otherwise.
- **One-shot, recorded in the PR body only:** a larger randomised run may be performed for
  confidence, but if so its generator, seed and shape count must be stated in the PR body so the
  claim is reproducible. An unreproducible "fuzzed at N documents" claim is worth nothing.

Define both terms precisely, because the obvious reading of the second is wrong:

- **divergence** = pass N+1 output HTML differs from pass N.
- **text loss** = the root's `textContent` with **all whitespace removed** (`"".join(s.split())`)
  differs before vs after any pass.

"All whitespace removed" is deliberate and is **not** the usual "collapse runs to a single space".
A merge legitimately *introduces* characters that were never in `textContent` — `buildRun`'s
synthetic boundary newlines. `<div class="ta-center">\[a</div><div class="ta-center">b\]</div>` has
`textContent == "\[ab\]"` before and `"\[a\nb\]"` after; under collapse-to-single-space those are
`"\[ab\]"` vs `"\[a b\]"`, so the assertion would redden on **every merging shape in the
cross-product** against a perfectly correct implementation. Stripping whitespace entirely is what
makes the check mean "no authored character was lost".

The cost is that this check is blind to the "tailhead" glue class — two words joined without a
separator. That is accepted: glue has its own dedicated exact-equality tests, inherited from the
predecessor.

### Regression surface

- The six real `</p><p>` repairs — unsigned runs, unchanged path.
- **Unsigned mixed-tag runs** (`<p>…</p><div>…</div>`) must still merge. Ordinary Chromium RTE
  output, and the only shape that distinguishes "tag equality when signed" from "tag equality
  always".
- The `data-x="1"` barrier case: attributes outside the align vocabulary still block.
- `test_empty_class_attribute_still_merges` — `<div style="">` and `<div class="">` still merge.
- `tests/test_e2e_math_reflow_dom.py::test_walk_descends_into_barriers` merges inside a
  `<td class="ta-center">` — a `td` is not `DIV`/`P`, so the merge happens among its children and the
  cell's class is irrelevant. That must stay true.
- `test_two_spans_in_one_run` — the unsigned two-span shape keeps its boundary newline *between* the
  groups; only the signed path relocates it.
- `test_content_before_the_run_is_not_destroyed` — run-local indexing.
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
