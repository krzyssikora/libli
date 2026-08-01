# Display-math authoring: multi-line `\[…\]`, and `<` inside math

## Purpose

Authoring a display-math block in libli fails in two independent, silent ways. Both were reproduced
against this repo's vendored KaTeX 0.16.11 and this repo's own sanitiser before this spec was
written; every claim below is a measurement, not a recollection, and the corpus numbers come from a
read-only scan of the live local `libli` database.

The reported symptom — a paste like

```latex
\begin{align*}
a^n\cdot a^k&=a^{n+k}\\
a^n: a^k&=a^{n-k}\\
\left(a^n\right)^k&=a^{nk}
\end{align*}
```

"is not accepted within `\(\)` or `\[\]`, i.e. it does not render".

### What is actually wrong

**Problem 1 — the RTE splits the span, and auto-render only matches inside a single text node.**

`renderMathInElement` scans **text nodes**. It never joins text across element boundaries. A
contenteditable turns each ENTER into a `<div>` (Chrome/Safari) or a `<br>` (Firefox) — see the
comment already in `courses/sanitize.py` on why `div` is in `ALLOWED_TAGS`. So the opening `\[` and
the closing `\]` land in different text nodes and the whole span is skipped, with no error and no
visible trace.

Measured in real Chromium against the vendored `katex.min.js` + `contrib/auto-render.min.js`:

| Input | `.katex` nodes |
|---|---|
| `\[\begin{align*}…\end{align*}\]` in **one** text node | **1** — renders correctly |
| the same span split across `<div>` lines | **0** — silently nothing |
| the same span split by `<br>` | **0** — silently nothing |
| the same span **rejoined into one text node**, newline at each boundary, prose before and after | **1**, three aligned rows, prose intact |

So `\[…\]` already supports `align*`. The delimiters are fine; the DOM shape is not.

**Problem 2 — `\(…\)` cannot host an alignment environment.** Measured against `katex.renderToString`
for 23 environments, exactly ten are display-only and raise
`{…} can be used only in display mode` when `displayMode: false`:

```
align  align*  alignat  alignat*  gather  gather*  equation  equation*  CD  split
```

Everything else (`aligned`, `alignedat`, `gathered`, `cases`, `matrix`, `pmatrix`, `bmatrix`,
`array`, `smallmatrix`, `darray`, `dcases`, `rcases`) works in both modes. So an author who reaches
for `\(` with an alignment environment gets a red KaTeX error, correctly but unhelpfully.

**Problem 3 — the Math element rejects the delimiters.** `mathelement.html` is
`<div class="el el--math" data-katex>{{ el.latex }}</div>` and `math.js` `renderOne` passes
`el.textContent` straight to `katex.render(…, {displayMode: true})`. `\[` and `\]` are auto-render
*delimiters*, not KaTeX control sequences, so `\[\begin{align*}…\end{align*}\]` in a Math element
fails with `Undefined control sequence: \[` — while the identical text **without** the wrapper
renders today. The author cannot tell which surface wants delimiters and which forbids them.

**Problem 4 — `<` inside math is destroyed at save, in text/callout/spoiler bodies.** `sanitize_cell`
protects balanced LaTeX spans from the HTML tokenizer before running nh3; `sanitize_html` does not.
Measured on this worktree (exact `repr()` output):

```
in    '\\[a<b\\]'
html  '\\[a'                                              tail destroyed
cell  '\\[a&lt;b\\]'                                      correct

in    '\\[\\begin{align*} a&=b\\\\ c<d \\end{align*}\\]'
html  '\\[\\begin{align*} a&amp;=b\\\\ c'                 tail destroyed
cell  '\\[\\begin{align*} a&amp;=b\\\\ c&lt;d \\end{align*}\\]'
```

nh3 reads `<b\]` as a `<b>` tag with garbage attributes, drops it, and takes everything after it. In
a maths course (`x<5`, `a<b`, `\left<`) this is on the main path. It is **destructive at save time**:
the tail is gone from the database, and no render-time fix can bring it back.

Note that Problems 1–3 are `<`-free — Problem 4 is a separate defect that this spec closes in the
same slice because it belongs to the same authoring story.

### What the existing corpus actually looks like

A read-only scan of every `sanitize_html`-shaped rich-text field in the live local `libli` database
(the `courses/richtext.py` registry — 16 models / 27 fields), classifying each opening delimiter by
where its partner sits:

| | count |
|---|---|
| rich-text values scanned | 17,594 |
| values containing any LaTeX | 7,693 |
| **spans intact** (no tag between the delimiters — renders today) | **17,821** |
| **spans mergeable** (partner past a `<div>`/`<p>`/`<br>` boundary — A1 fixes these) | **6** |
| **spans past a non-structural barrier** (A1 leaves alone) | **0** |
| unclosed spans | 1 |
| values ending inside an unterminated `\[` (Problem-4 damage shape) | **0** |

**This measurement corrects the obvious assumption, and it changes how the work is justified.** The
imported *matematyka* content is essentially all intact: the LAL importer wrote math into single text
nodes, so the split-span defect is an **authoring-time** defect, not an import-time one. A1 repairs
six spans retroactively. Its real value is that multi-line display math becomes *authorable at all*
— which is the user's current blocker — not that it rescues a broken corpus.

Equally, the scan finds **no** existing Problem-4 damage. A2 is therefore **purely preventive**, and
its risk budget should be spent on not perturbing the 17,821 spans that already work, rather than on
rescuing content that does not exist.

### Deliverables

Two parts, one PR, separable commits.

- **A1 — render-time reflow.** A new client module rejoins split math spans and normalises delimiters
  before KaTeX runs. It writes no stored data.
- **A2 — save-time math protection.** `sanitize_html` gains math-span protection, so `<` inside math
  stops being destroyed. Preventive; nothing existing is repaired.

### Non-goals

- **No `$$…$$` support** and **no bare `\begin{align*}` without delimiters.** Both were measured to
  render when the environment is *explicitly registered* as a delimiter pair (the measurement did not
  rely on auto-render's defaults, which register `align` but not `align*`). Both were declined: the
  accepted prose syntaxes remain exactly `\(…\)` and `\[…\]`.
- **No repair of already-damaged content.** The scan finds none; if any exists it stays damaged. No
  management command, no backfill.
- **No data migration and no re-save of any element** as part of this work.
- **No change to which elements may nest in which** — that is slice B.
- **No new authoring UI.** No RTE "insert display math" button, no MathLive changes.
- **No server-side math rendering.** KaTeX stays client-side.

## Architecture

### A1 — `courses/static/courses/js/math_reflow.js`

One new module installing two **pre-hooks** on the two globals every math path already funnels
through. This is the established technique in this repo, not an invention: `text_colour.js:537-565`
already wraps the identical pair as *post*-hooks and documents why the hook works
("math.js resolves that global at CALL time"). Ours run before the original, theirs after.

Why hooks rather than editing call sites: `renderMathInElement` is called from **10 modules** —
`math.js`, `question.js`, `quiz.js`, `filltable.js`, `switchgate.js`, `switchgrid.js`,
`choicegrid.js`, `dnd.js`, `editor.js`, `math_input.js`. One hook covers every one of them, plus any
added later, plus JS-injected content (quiz feedback, fill-table, switch-grid) that no server-side
filter can ever see.

**Public entry point.** The reflow is exported as `window.libliMathReflow(root)` — not merely an
internal of the wrapper. This is a testability requirement, not a convenience: the algorithm below is
the most intricate part of the change and needs DOM-in/DOM-out coverage that six end-to-end scenarios
cannot localise.

**Hook A — `window.renderMathInElement(root, options)`**: call `window.libliMathReflow(root, options)`,
then call through.

**Hook B — `window.katex.render(expr, element, options)`**: strip one balanced surrounding `\[…\]` or
`\(…\)` from `expr`; if the stripped wrapper was `\[…\]`, render with `displayMode: true`. Then call
through. This is Problem 3, and it also covers the Math editor's `[data-math-live]` preview.

**Installation is once, unconditional, with no retry.** `text_colour.js:588-596` re-runs its installs
on `DOMContentLoaded` when either global was missing. `math_reflow.js` must **not** copy that: marker
properties do not propagate through another module's wrapper, so a retry would wrap an
already-wrapped chain and reflow twice per call. A single install is safe because the module loads
after `katex.min.js` and `auto-render.min.js` in document order (below), so both globals exist. If
either global is absent the module installs nothing and every path keeps today's behaviour.

#### Load order

`math_reflow.js` is added to the **five** templates that load `contrib/auto-render.min.js`:

| template | loads `math.js` |
|---|---|
| `templates/courses/lesson_unit.html` | yes |
| `templates/courses/quiz_unit.html` | yes |
| `templates/courses/manage/editor/editor.html` | yes |
| `templates/courses/quiz_results.html` | no |
| `templates/courses/manage/review_submission.html` | no |

Placed **immediately after `auto-render.min.js` and before `text_colour.js`**, `defer` like its
neighbours. Deferred scripts execute in document order. Because `text_colour.js` installs second, it
owns the outer function and its retry logic remains correct.

#### Delimiter set

The scan set is **derived from `options.delimiters`** when the caller supplied one, falling back to
auto-render's own defaults when it did not. Hardcoding `\(`/`\[` would silently skip the three
callers that pass no delimiters at all (`filltable.js:73,86`, `switchgate.js:93`,
`switchgrid.js:102,111`), which run on auto-render's defaults — a per-surface inconsistency invisible
from any one page.

#### Delimiter recognition and backslash parity

An opening delimiter is only an opening delimiter when it is preceded by an **even** number of
backslashes. Without this, the row-spacing idiom inside the very construct this spec exists to fix —
`\[\begin{align*} a&=b \\[2ex] c&=d \end{align*}\]` — is misread: `\\[2ex]` contains the two
characters `\[`, so a naive scan opens a second span there. The same parity rule applies to `\\(`.
This rule governs both the reflow scan and Hook B's guard.

#### The reflow rule

**Ignored subtrees.** The walk descends into nothing matching:

- auto-render's own default ignore list — `script, noscript, style, textarea, pre, code, option`
  (`pre` and `code` are in `ALLOWED_TAGS`, so this is reachable);
- **`[contenteditable]`** — `text_toolbar.js:196-197` mounts a `contenteditable` `.rte-surface` in
  `editor.html`, and `sync()` writes that surface's `innerHTML` back into the POSTed textarea. A DOM
  mutation inside the RTE is therefore a **data** mutation, and would break A1's render-only
  guarantee. This exclusion is load-bearing, not hygiene;
- **`.katex`, `math`, `annotation`** — after the first pass KaTeX's own output holds the original TeX
  in a MathML `<annotation encoding="application/x-tex">`. Re-entering it would let step 7 rewrite
  the string screen readers and copy-paste consumers receive, and it is wasted traversal over the
  largest subtrees on the page.

**Mergeable vs barrier.** Within one element's child list, a child node is *mergeable* if it is

- a text node, or
- a `<br>` **carrying no attributes**, or
- a `<div>` or `<p>` **carrying no attributes** whose descendants are exclusively text nodes and
  attribute-free `<br>` elements.

Every other node is a **barrier**. The attribute condition is load-bearing: `ALIGN_CLASS_TAGS` puts
`ta-left`/`ta-center`/`ta-right` on `div`, `p`, `h2`–`h4`, `blockquote`, `li`, and `text_toolbar.js`
emits them. Merging a `<div class="ta-center">` into a bare text node would silently discard the
author's centring. Barriers therefore include `<td>`, `<th>`, `<li>`, `<h2>`–`<h4>`, `<a>`,
`<strong>`, `<em>`, `<u>`, `<blockquote>`, every `tc-*` colour `<span>`, and any `<div>`/`<p>` that
carries an attribute or holds element content beyond a bare `<br>`.

**Algorithm (the merge phase)**, for each element reached by the walk, over its own child list:

1. Partition the children into maximal **runs** of consecutive mergeable nodes. Barriers terminate a
   run and are never crossed. Each run is processed independently.
2. Build the run's linear text: a text node contributes its data; a `<br>` contributes `"\n"`; a
   mergeable `<div>`/`<p>` contributes `"\n"` + its text (its own `<br>`s becoming `"\n"`) + `"\n"`.
3. Find spans over that text using the derived delimiter set and the parity rule above.
4. A span **wholly inside one text-node segment** is skipped.
5. Any other span is rewritten. Let *covered* be the contiguous child nodes from the one holding the
   span's first character through the one holding its last. Those nodes — and only those; earlier and
   later siblings in the run are untouched — are replaced by up to three text nodes: the covered text
   preceding the span, the span itself, and the covered text following it, omitting empties.
6. Matches are processed left to right, re-deriving the run's segments after each rewrite. Runs are
   small; simplicity beats a single-pass rebuild here.

> **Merge-phase invariant.** A math span that already lies entirely inside a single text node is
> never merged. That is exactly the 17,821 spans measured to render correctly today, so the merge
> phase cannot regress them — the code path is not merely equivalent, it is not entered.

**Step 7 — delimiter promotion, a separate phase that deliberately does touch existing content.**
For every text node **reached by the walk** (i.e. after the ignore filter), a `\(…\)` span whose
content matches one of the ten display-only environments has its delimiters rewritten to `\[…\]`.
The environment set is enumerated literally —

```
align  align*  alignat  alignat*  gather  gather*  equation  equation*  CD  split
```

— rather than expressed as `(align|alignat|gather|equation|CD|split)\*?`, which would also admit the
non-existent `CD*` and `split*`.

The merge-phase invariant does **not** cover step 7: promotion by design rewrites spans that sit
inside a single text node. It therefore carries its own regression coverage (see Testing), and the
"cannot regress" argument above must not be extended to it.

**Newlines.** The span's text carries a real `\n` at each former boundary. Two adjacent mergeable
`<div>`s produce a blank line, which in real LaTeX is a `\par` and an error inside `align*`; it is
inert here only because **KaTeX collapses** whitespace and has no paragraph handling. State it that
way — an implementer must not carry "LaTeX ignores it" anywhere else.

Losing the `<div>` wrapper for attribute-free prose adjacent to the span is intended and was verified
visually: KaTeX renders display math as a block, so lead-in and trailing prose each keep their own
line anyway.

**Idempotence.** After one pass every rewritten span lives in a single text node, so a second pass
takes rule 4 and changes nothing; step 7 is idempotent because a promoted span no longer uses `\(`.
This matters because `renderMathInElement` is called repeatedly on the same DOM (quiz feedback swaps,
tab reveals, `libli:reveal` re-measures).

**Bounded failure.** An unclosed opening delimiter, or a span whose partner sits beyond a barrier,
matches nothing and is left exactly as-is. The whole reflow is wrapped so a failure degrades to
today's behaviour rather than blocking typesetting.

#### Hook B, precisely

Two conditions, both required — the guard is part of the logic, not prose commentary alongside it:

1. the expression matches `/^\s*\\\[([\s\S]*)\\\]\s*$/` or `/^\s*\\\(([\s\S]*)\\\)\s*$/`; **and**
2. the captured group contains none of `\[`, `\]`, `\(`, `\)` **counted with the parity rule**, so
   that a legitimate `\\[2ex]` inside the body does not veto stripping.

`[\s\S]*` is greedy, so condition 1 alone would match `\[a\] + \[b\]` with the group `a\] + \[b` and
strip exactly the case that must be left alone. Condition 2 is what prevents it.

On a match: strip the wrapper, and if it was `\[…\]` render with `displayMode: true`. The hook
**constructs a shallow copy** of `options` (creating one when `options` is `undefined`) and never
mutates the caller's object — `text_colour.js` wraps the same function and shares the argument list.

### A2 — math protection in `sanitize_html`

`sanitize_cell` protects math by stashing each balanced span behind an alphanumeric nonce
placeholder, running nh3, then restoring each span through `_canon_math` (unescape once, escape once
— so the editor path, where `<` already arrives as `&lt;`, and the import path, where it arrives
literal, converge on one single-escaped value that is inert to the parser but decodes correctly for
KaTeX).

**A naive port of that code to `sanitize_html` is wrong, and this is the crux of A2.** `_MATH_SPAN`
is `\\\(.*?\\\)|\\\[.*?\\\]` with `DOTALL`. A cell never contains block tags (`CELL_TAGS` has no
`div`), but a text body routinely does. Measured:

```
in    '<div>\\[\\begin{align*}</div><div>a&=b\\\\</div><div>\\end{align*}\\]</div>'
cell  '\\[\\begin{align*}&lt;/div&gt;&lt;div&gt;a&amp;=b\\\\&lt;/div&gt;&lt;div&gt;\\end{align*}\\]'
```

The intervening tags were swallowed **into** the math and escaped to literal text.

#### The rule: protect narrowly, abandon on anything unfamiliar

A span is protected **only if** everything between its delimiters is text plus *recognised structural
tags*. If any other tag falls inside it, the span is **left entirely unprotected** — today's exact
behaviour. This single rule closes three separate failure modes at once:

- markup destruction: measured, `sanitize_html('<ul><li>\[a</li><li>b\]</li></ul>')` returns its
  input **byte-identically** today. Escaping the `</li><li>` between the delimiters would turn a
  working list into visible literal text. The same applies to `<strong>`, `<em>`, `<a>`, `<h3>`,
  `<blockquote>` and the `tc-*` colour spans the recolour backfill wrote into 191 fields;
- unbounded span extent: a stray `\[` (a typo, a literal, an abandoned edit) would otherwise pair
  with a `\]` many paragraphs later and drag everything between into "math";
- unknown future markup: anything not on the recognised list fails safe.

**Recognised structural tags** are matched by **tag name, case-insensitively, with any attributes
allowed**: `<div …>`, `</div>`, `<p …>`, `</p>`, `<br …>` / `<br … />`. Literal-string matching would
miss `<div class="ta-center">`, which the RTE emits routinely and which — measured — passes through
`sanitize_html` byte-identically today; treating it as unrecognised would destroy the alignment
markup at save.

Within a protected span, each **non-tag run** between recognised tags is stashed separately and
restored through `_canon_math`; the recognised tags stay in the stream for nh3 to see, so the block
structure survives and the A1 reflow can still do its job at render.

**Segment-level contract for `_canon_math`.** `_canon_math` is idempotent on a whole span; applying
it per fragment needs its own statement: an empty or whitespace-only segment is not stashed, and
`escape(unescape(segment))` concatenated over segments must equal the same operation over the joined
text. The entity-boundary cases (`…&`, `…&am` at a fragment edge) are where this can fail and are
covered by a test vector.

**Placeholder completeness.** Splitting one span into N placeholders multiplies the ways nh3 can drop
or relocate one; a lost placeholder means math silently missing from the saved value, and a surviving
unrestored one means a literal `litmathspan<hex>x3xend` shown to students. After substitution the
function **asserts every stashed index was restored**; on failure it falls back to returning the
unprotected result (today's behaviour) rather than writing a corrupted value.

#### Signature, and the recolour pin

`sanitize_html(value, *, allowed_classes=None, protect_math=True)`.

`courses/recolour/replay.py` must pin `protect_math=False` on **both** sides of the replay, not just
the legacy one:

- `_LEGACY[SHAPE_HTML]` (`replay.py:41`) reconstructs the lookup **keys** the loader stored;
- `_CURRENT[SHAPE_HTML]` (`replay.py:57`) is the live `sanitize_html`, and `value_for()`
  (`replay.py:~84`) routes through `current_replay` to compute the **value that gets written**.

Changing either changes the backfill's output for every math-bearing field. That backfill has already
been applied byte-exactly to the local mat-pp database and **the PROD cutover is still pending**, so
a PROD run after A2 would otherwise write values the local run never produced, and
`recolour_imported_content.py`'s "already present in the database" idempotence probe would recompute
different values and misreport the applied local DB. Freezing both sides is the correct call: the
backfill's job is to reproduce one specific historical transformation, not to track sanitiser
evolution.

#### Blast radius

A2 changes behaviour on **three** kinds of path, not one.

**Save paths** — `models.py` TextElement / SpoilerElement / CalloutElement bodies (393, 412, 467),
`success_message` (779), question `stem` and `explanation` (1604-1605); `element_forms.py` fill-blank
and gate stems (257, 310, 411, 508, 814, 854), which compose as
`sanitize_html -> strip_sentinel -> parse`; `transfer/importer.py:768`.

**Render path — and this makes A2 retroactive, contrary to the intuitive framing.**
`templatetags/courses_extras.py:117` re-runs `sanitize_html` at render, and `textelement.html`,
`calloutelement.html` and `spoilerelement.html` all use `{{ el.body|sanitize }}`. So A2 changes what
**every stored body displays** the moment it deploys, with no save involved. The corpus scan bounds
the exposure — 0 barrier-crossing spans, 6 mergeable, 1 unclosed — and the abandon-on-unfamiliar-tag
rule keeps the rest untouched, but the render delta must be tested directly, not assumed away.

**Re-save paths** — `courses/richtext.py:~216 rewrite_instance` sets fields and its caller saves with
`update_fields=changed`, which still runs the model's `save()` and therefore `sanitize_html`. This
matters because the mat-pp internal-content-links PROD cutover is still pending: running
`migrate_course_content.py` after A2 would rewrite every touched body's math spans as a side effect
of a *link* migration, against fidelity guards calibrated on the old output. **Ordering requirement:
either the links cutover runs before A2 merges, or its fidelity guards are re-baselined against
A2's output.** This must be settled before the plan is written, not discovered during it.

**Idempotence is mandatory**, because `sanitize_html` runs at save *and* again at render.

## Error handling

| Situation | Behaviour |
|---|---|
| Unclosed `\[` or `\(` in prose | No match; DOM untouched; renders as literal text, as today |
| Math span crossing a barrier (`<td>`, `<li>`, `<strong>`, colour span, `<div class=…>`) | Not merged; unchanged |
| `\\[2ex]` row spacing inside a display block | Parity rule: not an opening delimiter; span reflows and Hook B still strips |
| `renderMathInElement` absent | Hooks never install; every path is today's behaviour |
| Reflow throws | Caught; the original `renderMathInElement` still runs on the untouched DOM |
| `\[a\] + \[b\]` reaching `katex.render` | Condition 2 fails; not stripped; today's behaviour |
| `options` undefined at Hook B | A fresh object is constructed; caller's argument never mutated |
| Display-only environment inside `\(…\)` | Promoted to `\[…\]`; renders as display |
| Non-display-only environment inside `\(…\)` (`cases`, `matrix`, …) | Untouched; already works inline |
| Math span containing a non-structural tag, A2 | Left entirely unprotected — today's behaviour |
| Stashed placeholder lost inside nh3 | Assertion fires; the unprotected result is returned |
| `<` inside math, table cell | Already correct via `sanitize_cell`; unchanged |
| `<` inside math, text/callout/spoiler body | Fixed by A2 going forward |
| Recolour backfill re-run | Unaffected — `replay.py` pins `protect_math=False` on both sides |

## Testing

Per this repo's convention, **falsification is the acceptance criterion**: each test must be shown to
go **red** when its guard is removed.

**Baseline** — the full non-e2e suite is green on this worktree at **4559 passed, 1 skipped**,
measured at branch point `0a9c2882` before any change.

### `tests/test_e2e_math_reflow.py` (e2e-marked, real Chromium)

1. **Golden path through the real UI.** Paste the three-line `align*` block into the RTE of a text
   element, save, open the lesson, assert exactly one `.katex` node with three aligned rows and no
   `.katex-error`. This one must drive the real gesture — the stored shape a real multi-line paste
   produces is precisely the unknown under test.
2. The same block in a **callout body** and in a **table cell**, from fixtures.
3. A **Math element** whose `latex` carries the `\[…\]` wrapper renders instead of erroring.
4. `\(\begin{align*}…\end{align*}\)` renders as display — **step 7's own regression coverage**, which
   the merge-phase invariant does not provide.
5. `\[a\] + \[b\]` in a Math element is left alone (Hook B condition 2).
6. A display block containing `\\[2ex]` reflows and strips correctly (parity rule).
7. **Regression**: single-line `\(x^2\)` and single-line `\[…\]` render identically before and after.
8. **Idempotence**: a re-rendering surface (quiz feedback swap or tab reveal) still shows one
   `.katex` node.

### `tests/test_math_reflow_unit.py` (e2e-marked; DOM table driven from a Playwright page)

Direct DOM-in/DOM-out cases against `window.libliMathReflow`, because the algorithm cannot be
localised through end-to-end scenarios:

- two spans in one run, and siblings outside the covered range left untouched (rule 5);
- a `<div>` with element content beyond `<br>` acts as a barrier;
- a `<div class="ta-center">` acts as a barrier and keeps its class;
- each ignored subtree: `pre`, `code`, `textarea`, `[contenteditable]`, `.katex`/`annotation`;
- a span crossing `<td>` / `<li>` is not merged;
- delimiter set derived from `options.delimiters`, including the no-delimiters caller shape;
- idempotence: second call is a no-op.

### `tests/test_sanitize_math_protection.py` (pytest)

A vector table through `sanitize_html`, each asserted **twice** to pin idempotence:

- `\[a<b\]` — tail preserved;
- the `align*` block containing `c<d`;
- a span split across `<div>`s — structural tags survive as tags, non-tag runs escaped;
- `<div class="ta-center">` inside a split span — recognised, attributes preserved;
- `<ul><li>\[a</li><li>b\]</li></ul>` — **byte-identical** before and after (abandon rule);
- a span containing `<strong>` — byte-identical (abandon rule);
- a stray unmatched `\[` with a `\]` several paragraphs later — byte-identical;
- an entity-boundary segment (`…&`, `…&am` at a fragment edge);
- content with no math at all — byte-identical;
- a fill-blank stem with a sentinel token adjacent to a math span, asserted through
  `sanitize_html -> strip_sentinel -> parse`;
- a forced placeholder-loss case reaching the assertion and the unprotected fallback.

### `tests/test_math_render_path.py` (pytest)

The render delta A2 introduces: pre-change stored bytes pushed through the `sanitize` **filter** and
asserted, so the retroactive render change is pinned rather than assumed.

### `tests/test_recolour_replay.py` (extend existing)

`legacy_replay` **and** `current_replay` / `value_for` output byte-identical to pre-change for a
math-bearing value. This is the test that protects the pending mat-pp PROD cutover.

### `tests/test_math_reflow_wiring.py` (pytest, static)

`math_reflow.js` is referenced in all five templates, and in each it precedes `text_colour.js`; the
module installs its wrappers exactly once and registers no `DOMContentLoaded` retry.

## Risks

| Risk | Mitigation |
|---|---|
| Merge phase disturbs the 17,821 spans that render today | Rule 4 makes them an unentered path; pinned by e2e 7 |
| Step 7 rewrites existing single-node content | Acknowledged as deliberate; own coverage at e2e 4 |
| A2 changes what existing bodies render | Bounded by the corpus scan; pinned by `test_math_render_path.py` |
| A2 destroys markup inside a span | Abandon-on-unfamiliar-tag rule; byte-identity vectors |
| A2 moves the recolour backfill's written values | `protect_math=False` on both replay sides; byte-identity guard on `value_for` |
| A2 collides with the pending links PROD cutover | Explicit ordering requirement, settled before planning |
| Reflow mutates the RTE surface and is persisted | `[contenteditable]` is an ignored subtree; asserted directly |
| Double-wrapping with `text_colour.js` | Single unconditional install, no retry; asserted by the wiring guard |
