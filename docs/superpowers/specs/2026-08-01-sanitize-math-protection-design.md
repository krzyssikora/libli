# Math-span protection in `sanitize_html`: stop `<` destroying a body at save

**Status: deferred, not scheduled.** Split out of `2026-08-01-display-math-authoring-design.md` after
review established that it is a security-sensitive change to the repo's primary sanitiser with zero
measured benefit on the current corpus. **Sequenced after the mat-pp internal-content-links PROD
cutover** — see "Ordering". Do not begin implementation without re-reading "The XSS this must not
reintroduce".

## Purpose

`sanitize_cell` protects balanced LaTeX spans from the HTML tokenizer before running nh3;
`sanitize_html` does not. So a `<` inside math in a **text, callout or spoiler body** makes nh3 read
`<b\]` as a `<b>` tag with garbage attributes, drop it, and take everything after it. Measured on
this worktree (exact `repr()` output):

```
in    '\\[a<b\\]'
html  '\\[a'                                              tail destroyed
cell  '\\[a&lt;b\\]'                                      correct

in    '\\[\\begin{align*} a&=b\\\\ c<d \\end{align*}\\]'
html  '\\[\\begin{align*} a&amp;=b\\\\ c'                 tail destroyed
cell  '\\[\\begin{align*} a&amp;=b\\\\ c&lt;d \\end{align*}\\]'
```

In a maths course (`x<5`, `a<b`, `\left<`) this is on the main path, and it is **destructive at save
time**: the tail is gone from the database and no render-time fix can recover it. This is the gap
recorded as a deferred follow-up when the table element shipped.

### Why it is deferred rather than urgent

A read-only scan of every `sanitize_html`-shaped field in the live local `libli` database (the
`courses/richtext.py` registry — 16 models / 27 fields) found:

| | |
|---|---|
| rich-text values scanned | 17,594 values |
| values containing any LaTeX | 7,693 values |
| spans that render correctly today | 17,821 spans |
| **values ending inside an unterminated `\[` (this defect's damage shape)** | **0** |

So the fix is **purely preventive**. Its entire risk budget must go into not perturbing the 17,821
spans that already work — not into rescuing content, of which there is none.

## The XSS this must not reintroduce

**The naive port of `sanitize_cell`'s stash-and-restore into `sanitize_html` opens a
quote-injection XSS.** `_MATH_SPAN` matches anywhere in the raw string, **including inside an
attribute value**, and `_canon_math` is `html.escape(html.unescape(span), quote=False)` — `quote=False`
turns `&quot;` back into a literal `"`. `sanitize_cell` is immune only because it passes
`attributes={}`; `sanitize_html` allows `a[href|title|rel]`.

Measured on this worktree against a faithful port of the naive algorithm:

```
in     <a href="#" title="\[a&quot; onmouseover=&quot;alert(1)\]">x</a>
today  <a href="#" title="\[a&quot; onmouseover=&quot;alert(1)\]">x</a>    safe
naive  <a href="#" title="\[a" onmouseover="alert(1)\]">x</a>             executes
```

No "abandon on unfamiliar tag" rule helps: that span contains no tags at all.

**Requirement.** The scan must be **attribute-aware**: a candidate span whose delimiters fall inside a
tag's attribute region is never stashed. The repo already built exactly this, for exactly this class
of reason — `courses/richtext.py:79 _scan_anchors`, which consumes quoted attribute values until an
**unquoted** `>`, documented against the measured finding that *nh3 does not escape `>` inside
attribute values*. Reuse that technique; do not re-derive it.

## The other four hazards review established

### 1. Entity decoding diverges from nh3

`html.unescape` decodes every named entity; nh3 round-trips several unchanged. Measured:

```
in     '\\[x&nbsp;y\\]'
today  '\\[x&nbsp;y\\]'      (stored, and rendered)
naive  '\\[x\xa0y\\]'                                  DIVERGES
```

`&nbsp;` is pervasive in imported LAL HTML. Every math span containing one would change its stored
bytes on the next save **and its rendered bytes on the next page view** — the corpus scan classified
spans by delimiter position, not content, so it does **not** bound this.

**Requirement.** Narrow the normalisation used inside `sanitize_html` so it touches only `&`, `<` and
`>`, leaving every other entity byte-identical to nh3's output. Vectors: `&nbsp;`, `&mdash;`,
`&#8722;`.

### 2. The recolour backfill is pinned in the wrong place

`courses/recolour/dbscan.py:161` writes with `row.save(update_fields=[field])`, and
`TextElement`/`SpoilerElement`/`CalloutElement.save()` (`models.py:393, 412, 467`),
`GuessNumberElement.save()` (779) and `QuestionElement.save()` (1604-1605) all re-run the **live**
`sanitize_html`. So the bytes that land in the DB are `sanitize_html(current_replay(...))`, not
`current_replay(...)`. `dbscan.py:163-174` then reads back and raises `ReadBackError` on any
difference — so a divergence does not silently corrupt, it **hard-aborts the pending mat-pp PROD
cutover**.

**Requirement.** Pinning `replay.py` alone is insufficient and a replay-function comparison test
cannot detect this. State the requirement as
`sanitize_html(value_for(raw, shape)) == value_for(raw, shape)` for every math-bearing corpus value,
and guard it with a real `save()`-and-read-back round trip through `apply_matches` on a math-bearing
`TextElement`. Hazard 1 supplies a concrete input where the two differ.

### 3. `replay.py` has three `sanitize_html` references, not two

- `_LEGACY[SHAPE_HTML]` — `replay.py:41`, the partial that reconstructs the loader's keys;
- `_CURRENT[SHAPE_HTML]` — `replay.py:57`;
- **`_CURRENT[SHAPE_COMPOSED]` — `replay.py:60`**, `lambda v: sanitize_html(sanitize_stem_segments(v))`,
  which references the module-level function directly.

Pinning only 41 and 57 leaves fill-blank stems (the `SHAPE_COMPOSED` shape) replayed through the
*new* sanitiser while every other shape uses the old one. The legacy side is safe only by luck —
`_LEGACY[SHAPE_COMPOSED]` (line 53) routes through `_legacy_html`, which *is* the line-41 partial.

**Requirement.** All three sites pin `protect_math=False`, with a `SHAPE_COMPOSED` math-bearing
vector.

### 4. The per-segment idempotence equality cannot hold in general

An earlier draft asserted that `escape(unescape(segment))` concatenated over segments equals the same
operation over the joined text, and in the same paragraph admitted it "can fail". The contradiction
is real: for `\[a &<br>lt; b\]` the segments are `\[a &` and `lt; b\]`; per-segment gives
`\[a &amp;` + `lt; b\]`, joined gives `\[a &lt; b\]`.

**Requirement.** Pick one and state it as behaviour, not as an invariant plus a caveat. The
recommended resolution: **a segment ending in a bare `&` is left unstashed and passes to nh3
unprotected**, with near-miss vectors (`…&`, `…&am` at a fragment edge) asserting exactly that.

## Design sketch (to be completed when scheduled)

- **Signature** `sanitize_html(value, *, allowed_classes=None, protect_math=True)`.
- **Protect narrowly, abandon on anything unfamiliar.** A span is protected only if everything
  between its delimiters is text plus *recognised structural tags*; any other tag, and the span is
  left **entirely unprotected** — today's exact behaviour. Measured, `sanitize_html` returns
  `<ul><li>\[a</li><li>b\]</li></ul>` **byte-identically** today; escaping the `</li><li>` would turn
  a working list into literal text. The same rule bounds span extent, so a stray `\[` cannot drag
  paragraphs into "math".
- **Recognised structural tags** matched by tag name, **case-insensitively, attributes allowed**:
  `<div …>`, `</div>`, `<p …>`, `</p>`, `<br …>`/`<br … />`. Literal-string matching would miss
  `<div class="ta-center">`, which the RTE emits routinely and which passes through byte-identically
  today.
- **Backslash parity** — the same even-backslash rule the reflow spec defines must govern this scan
  too, or the server and the client will disagree about which region is math, which is the hardest
  class of bug to diagnose because each half is individually correct.
- **`pre`/`code` policy — undecided, must be decided.** The reflow spec excludes them (a `\[…\]` in a
  code sample is text an author is deliberately showing, not math). If this spec protects them, the
  two halves apply opposite policies to the identical construct. Decide and state; vector
  `<code>\[a<b\]</code>`.
- **Scan-resume position — undecided, must be decided.** After an abandoned span, `re.sub` semantics
  resume past its end, which skips every legitimate span between a stray `\[` and its far partner —
  reintroducing the defect via an unrelated typo. The corpus already holds one unclosed span.
  Vector: `\[a<strong>b\] … \[c<d\]`.
- **Placeholder completeness.** Assert every stashed index was restored; on failure return the
  unprotected result rather than writing a corrupted value or a literal `litmathspan…` to students.
- **Idempotence is mandatory** — `sanitize_html` runs at save *and* again at render via the
  `sanitize` filter.

## Blast radius

**Save paths** — `models.py` 393, 412, 467, 779, 1604-1605; `element_forms.py` 257, 310, 411, 508,
814, 854 (composing as `sanitize_html -> strip_sentinel -> parse`); `transfer/importer.py:768`.

**Render path** — `templatetags/courses_extras.py:117` re-runs `sanitize_html` at render, and
`textelement.html`, `calloutelement.html`, `spoilerelement.html` all use `{{ el.body|sanitize }}`. So
this change is **retroactive at render**: it alters what every stored body displays the moment it
deploys, with no save involved. That must be tested directly against pre-change stored bytes.

**Re-save paths** — `courses/richtext.py:~216 rewrite_instance` sets fields and its caller saves with
`update_fields=changed`, which runs the model `save()` and therefore `sanitize_html`.

## Ordering

**This spec must not land before the mat-pp internal-content-links PROD cutover.** Running
`migrate_course_content.py` after this change would rewrite every touched body's math spans as a side
effect of a *link* migration, against fidelity guards calibrated on the old output — and the recolour
read-back would abort on the divergence in hazard 2. Sequencing after the cutover removes the
collision entirely and is why this spec is deferred rather than merely deprioritised.

## Testing (outline)

- `tests/test_sanitize_math_protection.py` — vector table, each asserted **twice** for idempotence:
  the two XSS vectors (`title=` and `href=`) asserted **byte-identical to today**; `\[a<b\]`; the
  `align*` block with `c<d`; a span split across `<div>`s; `<div class="ta-center">` inside a split
  span; `<ul><li>\[a</li><li>b\]</li></ul>` byte-identical; a `<strong>` span byte-identical; a stray
  `\[` with a far partner; entity-boundary near-misses; `<code>\[a<b\]</code>`; a fill-blank sentinel
  adjacent to a math span; a forced placeholder-loss reaching the fallback.
- `tests/test_math_render_path.py` — pre-change stored bytes through the `sanitize` filter, including
  `&nbsp;`, `&mdash;`, `&#8722;`.
- `tests/test_recolour_replay.py` (extend) — all three `replay.py` sites pinned, `SHAPE_COMPOSED`
  covered, **plus a `save()`-and-read-back round trip through `apply_matches`**, not merely a
  replay-function comparison.
