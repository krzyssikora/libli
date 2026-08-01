# Display-math authoring: making multi-line `\[…\]` render

## Purpose

Pasting a multi-line display-math block into libli silently renders nothing. Everything below was
reproduced against this repo's vendored KaTeX 0.16.11 and measured on this worktree; the corpus
numbers come from read-only scans of the live local `libli` database.

The reported symptom — a paste like

```latex
\begin{align*}
a^n\cdot a^k&=a^{n+k}\\
a^n: a^k&=a^{n-k}\\
\left(a^n\right)^k&=a^{nk}
\end{align*}
```

"is not accepted within `\(\)` or `\[\]`, i.e. it does not render".

> **Scope note.** An earlier draft also carried a fix for `<` inside math being destroyed by
> `sanitize_html` at save time. Review established that it is a security-sensitive change to the
> repo's primary sanitiser (it reintroduces a quote-injection XSS if ported naively) with zero
> measured benefit on the current corpus. It is split into
> `2026-08-01-sanitize-math-protection-design.md`, sequenced after the mat-pp links PROD cutover.
> **This spec changes no save path and no stored data whatsoever.**

### What is actually wrong

**Problem 1 — the RTE splits the span, and auto-render only matches inside a single text node.**

`renderMathInElement` scans **text nodes**. It never joins text across element boundaries. In this
RTE each ENTER yields a `<div>` on **every** browser — `text_toolbar.js:200` runs
`document.execCommand("defaultParagraphSeparator", false, "div")` at surface mount precisely so
per-block alignment works cross-browser — while `<br>` arrives from Shift+Enter and from pasted
markup. (`courses/sanitize.py` keeps `div` in `ALLOWED_TAGS` for the same reason.) So the opening
`\[` and
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

**Problem 1b — in a table cell the same span is broken differently, before it ever reaches the DOM.**
Cells do not go through `sanitize_html`. `models.py:962` and `1134` route cell html through
`sanitize_cell`, whose `_MATH_SPAN` is `DOTALL` and therefore swallows the intervening markup **into**
the span, then reinstates it through `_canon_math` as escaped text. Measured:

```
in   \[\begin{align*}<br>a&=b\\<br>c&=d\end{align*}\]
out  \[\begin{align*}&lt;br&gt;a&amp;=b\\&lt;br&gt;c&amp;=d\end{align*}\]
```

The cell therefore stores a **single text node** whose LaTeX body contains the literal characters
`<br>`. Phase 1's rule 4 skips it — it *is* in one text node — and KaTeX renders `<br>` as glyphs.
A DOM merge cannot fix this; it needs the textual counterpart, phase 1b below. `CELL_TAGS` has no
`div`/`p`, so `<br>` is the only *line-boundary* shape a cell can present.

It is **not** the only markup that can arrive as literal text, though: `sanitize_cell` stashes the
whole span before `nh3.clean`, so any inline emphasis an author put inside cell math — `<strong>`,
`<em>`, a `tc-*` colour `<span>` — is reinstated as escaped text too and renders as glyphs. Phase 1b
does not address that, and it is named as an out-of-scope limitation rather than left implied. Only
the `<br>` shape was counted (0 occurrences); the other six `CELL_TAGS` were not.

**Problem 2 — `\(…\)` cannot host an alignment environment.** Measured against `katex.renderToString`
for 23 environments, exactly ten are display-only and raise
`{…} can be used only in display mode` when `displayMode: false`:

```
align  align*  alignat  alignat*  gather  gather*  equation  equation*  CD  split
```

Everything else (`aligned`, `alignedat`, `gathered`, `cases`, `matrix`, `pmatrix`, `bmatrix`,
`array`, `smallmatrix`, `darray`, `dcases`, `rcases`) works in both modes.

**Problem 3 — the Math element rejects the delimiters.** `mathelement.html` is
`<div class="el el--math" data-katex>{{ el.latex }}</div>` and `math.js` `renderOne` passes
`el.textContent` straight to `katex.render(…, {displayMode: true})`. `\[` and `\]` are auto-render
*delimiters*, not KaTeX control sequences, so `\[\begin{align*}…\end{align*}\]` in a Math element
fails with `Undefined control sequence: \[` — while the identical text **without** the wrapper
renders today.

### What the existing corpus actually looks like

Two read-only scans, because the two sanitiser families store different shapes.

**`sanitize_html`-shaped fields** — the `courses/richtext.py` registry, 16 models / 27 fields:

| values | |
|---|---|
| scanned | 17,594 |
| containing any LaTeX | 7,693 |

| spans | |
|---|---|
| intact (no tag between the delimiters — renders today) | **17,821** |
| mergeable **under the module's strict predicate** (attribute-free `<div>`/`<p>`/`<br>` boundary) | **6** |
| `div`/`p`/`br` boundary but **attributed** (barrier — not fixed) | **0** |
| past any other tag (barrier — not fixed) | **0** |
| unclosed | 1 |

**`sanitize_cell`-shaped fields** — table cells and gallery descriptions, which the registry
deliberately omits and which the hooks nonetheless traverse:

| | |
|---|---|
| table cells scanned | 7,190 |
| gallery descriptions scanned | 3 |
| values containing math | 5,519 |
| spans intact | **5,699** |
| spans with escaped markup inside the math (phase 1b's target) | **0** |

The mergeable count was re-measured under the module's exact predicate (boundary tags attribute-free,
`div`/`p` holding only text and bare `<br>`), not a looser tag-name taxonomy, so **6 is the real count,
not an upper bound**. All six are `</p><p>` boundaries, and they are real authored content: one
`CalloutElement` body holding the reported `align*` block, and five question stems
(`ChoiceQuestionElement` 218/226/227, `ShortNumericQuestionElement` 76/77) holding
`\begin{cases}\begin{align}`. They render as nothing today.

**Their delimiter forms are recorded here because phase 2's rule depends on them**: the callout span
is `\[`-wrapped (`\[\begin{align*}</p><p>…`), and **all five stems are `\(`-wrapped**
(`\(\begin{cases}</p><p>\begin{align}…`). See phase 2 for why that forces a "contains" test rather
than a "begins with" one.

**Phase 2's retroactive blast radius, from the same scan:**

| | spans |
|---|---|
| intact `\(…\)` spans phase 2 would promote | **0** |
| intact `\(…\)` spans opening with a both-modes environment name-prefixed by a display-only one (`aligned`, `gathered`, `alignedat`) | **0** |
| intact `\(…\)` spans containing but not opening with a display-only environment | **0** |

So phase 2 changes **nothing** in the existing corpus beyond the five stems it repairs.

**Total measured: 23,520 intact spans, 6 broken.** The imported *matematyka* content is essentially
all fine — the LAL importer wrote math into single text nodes — so this is an **authoring-time**
defect, not an import-time one. This spec repairs six spans retroactively. Its real value is that
multi-line display math becomes *authorable at all*, which is the current blocker.

Both scans cover only these two families. MCQ options (`models.py:738`), choice-grid options (`805`)
and switch-grid lines are `sanitize_cell`-shaped and **unmeasured**; the risk table reflects that.

### Non-goals

- **No new delimiters are registered.** The module reflows whatever set the calling code already
  registered — see "Delimiter set" for the consequence.
- **No bare `\begin{align*}` support on the seven explicit-delimiter surfaces.** Measured to render
  when explicitly registered as a delimiter pair; declined.
- **No save-path change and no stored-data change of any kind.**
- **No repair of already-damaged content**, no migration, no management command.
- **No change to which elements may nest in which** — a separate slice.
- **No new authoring UI.**
- **The HTML-element sandbox is out of scope.** `courses/htmlsandbox.py:98` inlines its own
  `renderMathInElement(document.body, …)` call into a `srcdoc` iframe whenever
  `has_math_delimiters(html)` is true, with KaTeX assets inlined under a `script-src 'unsafe-inline'`
  CSP. It is a separate document, unreachable from any of the five templates, and its content is
  author-written raw HTML rather than RTE output — so the split-span defect does not arise there in
  the same way. Named here so the five-template enumeration is not mistaken for exhaustive.
- **No interaction with the pending mat-pp links PROD cutover.** Nothing here runs at save.

## Architecture

### `courses/static/courses/js/math_reflow.js`

Two **pre-hooks** on the two globals every math path funnels through. Established technique, not an
invention: `text_colour.js:553-579` already wraps the identical pair as *post*-hooks and documents
why the hook works ("math.js resolves that global at CALL time"). Ours run before the original.

Why hooks rather than editing call sites: `renderMathInElement` is called from **10 modules** —
`math.js`, `question.js`, `quiz.js`, `filltable.js`, `switchgate.js`, `switchgrid.js`,
`choicegrid.js`, `dnd.js`, `editor.js`, `math_input.js`. One hook covers all of them, plus any added
later, plus JS-injected content no server-side filter could ever see.

**Public entry point and contract.** `window.libliMathReflow(root, options)`:

- `root` may be an `Element`, a `Document` or a `DocumentFragment` (auto-render accepts a document;
  the hooked callers all pass elements);
- `options` is optional; when absent, the default delimiter set applies;
- the return value is unspecified — treat it as `undefined`;
- **a falsy `root` is an immediate no-op.** Three callers (`filltable.js:73,86`, `switchgate.js:93`,
  `switchgrid.js:102,111`) pass their root with no truthiness guard, and Hook A calls
  `libliMathReflow` *before* calling through — so a falsy root reaches us before auto-render's own
  `if(!e) throw new Error("No element provided to render")` can fire. Returning immediately leaves
  that error unchanged;
- **the walk processes the root's own child list for all three root types.** "Does not throw" is not
  a sufficient contract for `Document`/`DocumentFragment`: an implementation that early-returns for
  any non-Element root satisfies it while doing nothing. auto-render's `renderElem` iterates
  `e.childNodes` directly, so a fragment's top-level children *are* processed and split, and the
  reflow must match. The fragment DOM case therefore asserts an actual merge across two top-level
  `<div>` children, not merely the absence of a throw;
- if `root` **itself** matches an ignored selector the function returns immediately, doing nothing.
  The check must be **guarded on the existence of `matches`** — `Document` and `DocumentFragment` have
  none and calling it throws — exactly as `math.js:18` already guards the same hazard with
  `if (scope.matches && scope.matches("[data-katex]"))`;
- **it also returns immediately if `root` is a *descendant* of an ignored node**, via
  `root.closest && root.closest(IGNORE_SELECTOR)`. Three shapes exist — root-is-ignored,
  root-is-an-ancestor, root-is-a-descendant — and an earlier draft handled only the first two. The
  third is unreachable today (`editor.js` passes only `[data-scope="preview"]` subtrees, while the
  RTE surface lives under `[data-scope="editor"]`), but that is an unstated invariant carrying the
  whole data-safety guarantee, and a future caller could break it silently;
- **the export is unconditional.** Only the two hooks are guarded on the KaTeX globals being present.
  If the export sat inside that guard, every unit case would fail on a harness page that does not also
  load `katex.min.js` and `auto-render.min.js`. The unit-test page needs to load only
  `math_reflow.js` itself.

**Hook A — `window.renderMathInElement(root, options)`**: call `window.libliMathReflow(root, options)`,
then call through.

**Hook B — `window.katex.render(expr, element, options)`**: strip one balanced surrounding `\[…\]` or
`\(…\)` from `expr`, then call through. Covers the Math element and the `[data-math-live]` preview
(`_edit_math.html`, routed via `text_toolbar.js:302-318` → `window.libliRenderMath` → `katex.render`).

Note that the math-insert dialog's `[data-math-preview]` is a **Hook A** surface, not Hook B —
`math_input.js:71-72` renders it through `renderMathInElement`. `math_input.js` is loaded at
`editor.html:135`, i.e. *before* `katex.min.js`; that is safe, and unaffected by the load-order
argument below, only because it resolves both globals lazily inside event handlers rather than at
evaluation time.

**Installation is once, unconditional, with no retry, and guarded by a marker.**
`text_colour.js:587-595` re-runs its installs on `DOMContentLoaded` when either global was missing.
`math_reflow.js` must **not** copy that: marker properties do not propagate through another module's
wrapper, so a retry would wrap an already-wrapped chain and reflow twice per call. A single install is
safe because the module loads after `katex.min.js` and `auto-render.min.js` in document order. It
still sets and checks a `__libliMathReflowWrapped` marker — as a **double-include guard** (a shared
partial, a future refactor), not as a retry enabler. **That marker lives on `window`, not on either
wrapped function**, and one flag covers both hooks. A function-attached marker would not survive the
mandated load order: `text_colour.js` wraps second and owns the outer function, so a second include
of `math_reflow.js` would find no marker on `window.renderMathInElement` and wrap again — exactly the
double-wrap the marker exists to prevent, and predicted by this spec's own reasoning that marker
properties do not propagate through another module's wrapper. If either global is absent the module
installs nothing and every path keeps today's behaviour.

#### Load order and the `has_math` gate

`math_reflow.js` is added to the **five** templates that load `contrib/auto-render.min.js`:

| template | what typesets there | loads `math.js` | KaTeX block gated |
|---|---|---|---|
| `lesson_unit.html` | `math.js` + element modules | yes | `{% if has_math %}` (L60) |
| `quiz_unit.html` | `math.js`, `quiz.js` | yes | `{% if has_math %}` (L16) |
| `quiz_results.html` | **`question.js`** (explicit `\(`/`\[`) | no | `{% if has_math %}` (L59) |
| `manage/review_submission.html` | **`question.js`** (explicit `\(`/`\[`) | no | `{% if has_math %}` (L130) |
| `manage/editor/editor.html` | `math.js`, `editor.js` | yes | **unconditional** |

The two `question.js` pages load no `math.js`; the module is genuinely active there, not installed
for uniformity.

**The tag goes inside the `{% if has_math %}` block** in the four gated templates, and unconditionally
in `editor.html`. Outside the conditional it would ship on every math-free lesson page — and an
index-based ordering test cannot see the difference, so the wiring test must assert containment
(see Testing).

Ordering, all four relations asserted rather than left to transitivity:
`katex.min.js` < `auto-render.min.js` < `math_reflow.js` < `text_colour.js`, plus
`math_reflow.js` < `math.js` wherever `math.js` loads. `math.js` runs `renderMath(document)` and
`renderInlineText(document)` at evaluation time, so if it ever preceded the module the entire first
paint would bypass both hooks with no error. Placing the module before `text_colour.js` is convention and determinism, not correctness:
`text_colour.js`'s retry fires only when a global was absent at its evaluation, which never happens on
these five templates, so either install order yields the same call sequence (reflow before the
original renderer, `mapColours` after it). The genuinely load-bearing relation is
`math_reflow.js` < `math.js`, argued above from `math.js`'s evaluation-time `renderMath(document)`.

#### Delimiter set

Derived from `options.delimiters` when the caller supplied one. Hardcoding `\(`/`\[` would silently
skip the three callers that pass none — `filltable.js:73,86`, `switchgate.js:93`,
`switchgrid.js:102,111`. The other seven pass exactly `\(`/`\[`.

**When the caller passed none, the module uses a hardcoded verbatim copy of auto-render's defaults.**
It cannot read them: the vendored `auto-render.min.js` keeps its default array as a minified internal
and exposes nothing on `window`. The copy is version-coupled third-party data, so a test asserts the
hardcoded list still matches what the vendored file contains — a KaTeX bump must redden, not silently
diverge. The eight default pairs are:

```
[{left:"$$",              right:"$$",              display:true },
 {left:"\\(",             right:"\\)",             display:false},
 {left:"\\begin{equation}",right:"\\end{equation}",display:true },
 {left:"\\begin{align}",  right:"\\end{align}",    display:true },
 {left:"\\begin{alignat}",right:"\\end{alignat}",  display:true },
 {left:"\\begin{gather}", right:"\\end{gather}",   display:true },
 {left:"\\begin{CD}",     right:"\\end{CD}",       display:true },
 {left:"\\[",             right:"\\]",             display:true }]
```

Transcribed verbatim from the vendored file, **in its order** — which matters, because "caller's array
order, first match wins" is load-bearing. `test_math_reflow_defaults.py` compares the **full triples
(`left`, `right`, `display`) in order**, not just the `left` strings.

Two of those (`\(`, `\[`) overlap with the seven explicit callers; the extra **six** are the actual
asymmetry. On fill-table, switch-gate and switch-grid, split `$$…$$` and `\begin{align}` spans will
therefore reflow, and will not on the other seven surfaces. That is pre-existing asymmetry in what
those surfaces accept; the module inherits it rather than creating it, and deliberately does not
paper over it.

One precondition worth stating: `courses/htmlsandbox.py:122` defines `has_math_delimiters` as
`("\(" in html) or ("\[" in html)`, and the four gated templates emit the whole KaTeX block only
when `has_math` is true. A page whose *only* math is `$$…$$` therefore loads no KaTeX at all and
nothing runs — auto-render included. The `$$` behaviour above applies only where a `\(` or `\[`
appears somewhere on the page too.

#### Scan semantics — a faithful port of `splitAtDelimiters`

The merged text is handed straight back to auto-render, which re-splits it. If the two disagree about
where a span begins or ends, the reflow merges one region and the renderer parses another. The only
safe design is therefore a **faithful port**, deviating nowhere. Deminified from the vendored
`auto-render.min.js`:

```js
// findEndOfMath(e = closing delim, t = text, n = start index)
let r = n, o = 0;        // r = cursor, o = brace depth
const i = e.length;      // closer length
for (; r < t.length; ) {
  const n = t[r];
  if (o <= 0 && t.slice(r, r + i) === e) return r;   // accept only at brace depth <= 0
  "\\" === n ? r++ : "{" === n ? o++ : "}" === n && o--;
  r++;
}
return -1;
```

- **Openings.** Walk left to right; at each position test the delimiters in the caller's array order,
  first match wins. **No escape handling** — auto-render does none on openings
  — auto-render builds its opener regex by regex-escaping each `left` string and alternating them,
  with no LaTeX escape handling anywhere, so neither may the reflow. (The literal is not reproduced
  here: two earlier attempts to transcribe its nested backslashes were wrong, and the specified port
  uses ordered `startsWith` rather than a regex, so the exact source text is not load-bearing.)
- **Closings.** Port `findEndOfMath` exactly: a backslash **skips the following character** (so an
  escaped `\]` is not accepted as a closer), and a closer is only accepted at **brace depth ≤ 0**.
- Do not use longest-match, a reordered alternation, or an `indexOf`-style first-literal search.
- **Scanning stops dead at the first opener that has no closer.** The vendored loop is
  `for(;r=e.search(a),-1!==r;){ … if(r=n(...), -1===r) break; … }` — on an unclosed opener auto-render
  breaks out of the whole loop and pushes the entire remainder as text. A reflow that skipped past it
  and kept scanning would merge a later span the renderer will never treat as math, folding away the
  author's wrappers for no rendering benefit. Nothing after an unclosed opener is a candidate.

**An earlier draft specified a backslash-parity rule on openings and an `indexOf` closing search.
Both were wrong and are deliberately removed.** The parity rule was a unilateral deviation: because
auto-render accepts openings the parity filter rejects, it produced concrete mis-pairings — for
`<div>\\[2ex] \[a</div><div>b\]</div>` the reflow would reject the `\[` inside
`\\[`, merge `\[a` + newline + `b\]`, and leave `\\[2ex] ` as an adjacent text node — whereupon
auto-render (see below) re-concatenates and opens at the `\[` inside `\\[2ex]`, rendering math the
author never wrote where
today the text stays inert. The `indexOf` closing search was wrong on its own terms: the deminified
source above shows auto-render *does* escape-skip and brace-track. Being a faithful port removes the
entire divergence class and needs no parity rule — the `\\[2ex]` idiom pairs correctly because the
scan opens at the span's real `\[` and never reconsiders the interior.

**auto-render concatenates sibling text nodes before splitting.** Also from the vendored source:

```js
if (3 === r.nodeType) {
  let o = r.textContent, i = r.nextSibling;
  for (; i && i.nodeType === Node.TEXT_NODE; ) o += i.textContent, i = i.nextSibling;
```

It joins the entire run of consecutive sibling text nodes and splits *that* string. Two consequences:

- **A text-node boundary confers no isolation.** Wherever rule 5 leaves adjacent text nodes they are
  re-joined before parsing, so no argument may rest on a fragment boundary separating two spans.
- **An intervening element does break the run** — the ordinary case after rule 5, since non-covered
  mergeable siblings survive as elements. The merged span then sits in its own text node between two
  elements and is scanned on its own.

What makes the result correct in both cases is only that the reflow scans the same concatenated-run
text, with the same semantics, as the renderer will.

#### The walk, and what stops it

Two distinct concepts whose interaction is the thing most likely to be got wrong:

- **Ignored subtrees stop the walk.** It does not descend into them at all.
- **Barriers do not stop the walk.** A barrier terminates the *run* it sits in — it is never merged
  across — but the walk still descends into it and processes its own child list. Required: a
  `<td class="ta-center">` is a barrier for its parent `<tr>`'s run, yet a span split across two
  `<div>`s *inside* that cell must still merge. Reading "barrier" as "do not enter" would silently
  skip every table cell, list item and aligned block.

**Traversal is post-order, over a snapshotted child list.** A mergeable `<div>`/`<p>` child is
simultaneously a node the parent's rule 5 may delete and an element the walk must descend into.
Post-order — process every descendant before the parent folds anything away — is the only order in
which the child is guaranteed to have been processed before it can be destroyed. Each element's child
list is copied into an array before any rewrite, because rule 5 mutates a live `childNodes` and a
live iteration would skip or revisit nodes.

**A parent classifies its children on their state *after* every descendant has been processed**, and
the snapshot is taken immediately before that parent's own rule-5 rewrites. This is observable: a
`<div>` containing two nested `<div>`s is a barrier by the predicate below, but once post-order
processing has folded those nested divs into a text node it becomes mergeable — so a two-level split
span merges only under this rule. **Only when the rewrite covered *all* of its element children**,
though: rule 5 folds covered nodes only, and non-covered mergeable siblings survive as elements, so an
outer `<div>` holding `[<div>\[a</div>, <div>b\]</div>, <div>c</div>]` still has a `<div>` child
afterwards and stays a barrier. The nested-split DOM case must state which of the two it exercises. The nested-split unit case must assert the resulting merge, not
merely that no node was skipped.

**Ignored subtrees** are anything matching:

- auto-render's own default ignore list — `script, noscript, style, textarea, pre, code, option`
  (`pre` and `code` are in `ALLOWED_TAGS`, so this is reachable);
- **`[contenteditable]:not([contenteditable="false"])`** — the bare attribute-presence selector
  would also match `contenteditable="false"` subtrees, which are not editable and carry no
  data-mutation risk. `text_toolbar.js:196-197` mounts a `contenteditable` `.rte-surface` in
  `editor.html`, and `sync()` writes that surface's `innerHTML` back into the POSTed textarea. A DOM
  mutation inside the RTE is therefore a **data** mutation, and would break the render-only
  guarantee. Load-bearing, not hygiene. Its user-visible consequence is deliberate and must be
  documented for testers: **display math is not typeset live inside the editing surface** — the round
  trip is paste → save → view.

  **A caller already passes an ancestor of a live RTE surface, so this skip is exercised on a real
  page — it is not prophylaxis.** `_edit_choicegridquestion.html:11` opens
  `<div … data-choicegrid-editor>` and nests `<textarea data-rte-source>` at line 15;
  `text_toolbar.js:299` (`initRte(document)`, at module evaluation) inserts a `contenteditable`
  `.rte-surface` as that textarea's sibling — i.e. *inside* `[data-choicegrid-editor]`; and
  `choicegrid.js:212` then calls `renderPreviewMath(editor)` with that very element, from a
  `DOMContentLoaded` handler that runs after the deferred `text_toolbar.js`. So the
  root-is-an-ancestor shape is **reachable today**. An earlier draft claimed "no caller does"; that
  was false, and the ancestor-root byte-identity DOM case must be built from the choicegrid shape
  rather than a synthetic one.

  **The guarantee is still one-sided and must not be over-read**: the ignore list constrains
  `libliMathReflow`, not auto-render, which honours only `ignoredTags`/`ignoredClasses`. On that same
  choicegrid path auto-render therefore already walks into `.rte-surface` and can inject `.katex`
  markup that `sync()` would persist. **That is a pre-existing defect, out of scope here** — this spec
  must not make it worse, and does not, but neither does it fix it. Recorded so the next person finds
  it rather than rediscovering it;
- **`.katex`** — after the first pass KaTeX's output holds the original TeX in a MathML
  `<annotation encoding="application/x-tex">`; re-entering would let phase 2 rewrite the string
  screen readers and copy-paste consumers receive. `math` and `annotation` are listed alongside it
  for defence in depth only — KaTeX nests them **inside** `.katex`, so `.katex` already subsumes
  both; they matter only if KaTeX's output mode ever changes;
- **`.katex-error`** — with `throwOnError: false` a failing `katex.render` emits
  `<span class="katex-error" title="…">raw TeX</span>`, which is **not** nested inside `.katex`. A
  later `renderMathInElement` over an ancestor (a Math element inside `.el--tabs`, which `math.js:31`
  matches) would otherwise descend into it and let phase 1b or phase 2 rewrite that raw TeX. This is
  a distinct selector, not covered by `.katex`.

The fixed list above is a **floor, not the whole set**: the caller's `options.ignoredTags` and
`options.ignoredClasses` (which auto-render honours) are **unioned into it**. No caller passes them
today, but "a fixed list is a superset" is a property of the current callers, not of a fixed list — a
future caller passing `ignoredTags: ["div"]` would have the reflow act on a subtree the renderer
skips, folding away the author's wrappers for no rendering benefit. That is a real DOM mutation, and
this spec applies the opposite standard elsewhere (the `closest()` guard exists precisely because a
future caller could break the invariant silently). Unioning is strictly safe and cheap: ignoring more
than the renderer never changes what renders.

The delimiter set is *derived* rather than unioned because the opposite holds there — scanning a
different delimiter set than the renderer is unsafe in both directions.

**Mergeable vs barrier.** Within one element's child list, a child node is *mergeable* if it is

- a text node, or
- a `<br>` **carrying no effective attributes**, or
- a `<div>` or `<p>` **carrying no effective attributes** whose descendants are exclusively text
  nodes and effectively attribute-free `<br>` elements.

**"No effective attributes" means: no attributes, or only an empty `class` and/or empty `style`.**
This is not pedantry — without it the feature is a no-op on the dominant authoring path. `div` and `p`
are keys in `ALLOWED_CLASSES` (via `ALIGN_CLASS_TAGS`), and nh3 emits an **empty** `class` attribute
for an allowed-classes-keyed tag whose class values are all rejected — the behaviour
`courses/sanitize.py:53-57` already documents. Measured on this worktree with the real allowlists:

```
'<div class="MsoNormal">a</div>'  ->  '<div class="">a</div>'
'<p class="x">a</p>'              ->  '<p class="">a</p>'
'<div style="color:red">a</div>'  ->  '<div>a</div>'
'<div class="ta-center">a</div>'  ->  '<div class="ta-center">a</div>'   (kept — a real class)
```

Pasting a multi-line formula from Word, Google Docs or a web page puts a class on every line block,
so after save **every line carries `class=""`**. Treating that as "attributed" would make every line
a barrier, nothing would merge, and the feature would silently do nothing for exactly the paste this
spec exists to fix. An empty `class` carries no styling, so folding it away loses nothing — whereas
`class="ta-center"` survives as a real class and correctly stays a barrier (the centring limitation
below).

The corpus's "attributed boundary: 0" row measures *existing* content and does **not** bound this;
the paste path is the authoring flow, not the archive.

Every other node is a **barrier**. The attribute condition is load-bearing: `ALIGN_CLASS_TAGS` puts
`ta-left`/`ta-center`/`ta-right` on `div`, `p`, `h2`–`h4`, `blockquote`, `li`, and `text_toolbar.js`
emits them. Merging a `<div class="ta-center">` into a bare text node would discard the centring.

**Named limitation, and it is a likely one.** Centring a formula is an ordinary gesture in maths
authoring. An author who pastes a multi-line `\[…\]` block and then presses the RTE's centre button
gets `class="ta-center"` on every line div; every line becomes a barrier, nothing merges, and the
reported symptom persists with no error — the same silent-failure class this spec exists to remove.
It appears in the Error-handling and Risks tables, and an e2e case pins the failure mode so it is a
known boundary rather than a surprise. Widening the predicate to *attribute-homogeneous* runs (merge
when every covered node carries an identical attribute set, preserving one wrapper) is the obvious
extension and is deliberately **out of scope here** — it changes the rewrite from "replace with text
nodes" to "replace with a reconstructed element", which deserves its own risk budget.

#### Phase 1 — merge

For each element reached by the walk, over its snapshotted child list:

1. Partition the children into maximal **runs** of consecutive mergeable nodes. Barriers terminate a
   run. Each run is processed independently.
2. Build the run's linear text by concatenating per-child contributions: a text node contributes its
   data; a `<br>` contributes `"\n"`; a mergeable `<div>`/`<p>` contributes its text (its own `<br>`s
   becoming `"\n"`). Then, **between every pair of adjacent mergeable children, emit one `"\n"` unless
   the boundary already carries one**, and **collapse any run of consecutive newlines to a single
   `"\n"`**.

   A leading-only rule (an earlier draft) is wrong: it marks a boundary only when the *next* node is a
   `div`/`p`, so `<div>\[\alpha</div>` followed by the text node `x\]` yields `\[\alphax\]` — the two
   tokens concatenate and KaTeX reports an undefined control sequence where the author wrote `\alpha`
   then `x`. The same loss reappears after a rule-5 rewrite, where a surviving `<div>` sits next to a
   freshly created text node.

   The collapse rule handles the other direction: `<div><br></div>` is Chrome's representation of an
   empty line and is mergeable (its only descendant is a bare `<br>`), so without collapsing it would
   contribute two or three consecutive newlines — a blank line, which in real LaTeX is a `\par` and an
   error inside `align*`. Collapsing makes that structural rather than relying on KaTeX's whitespace
   handling.

   **Two implementation constraints that are easy to get wrong.**

   *Provenance, not adjacency.* Emit a synthetic newline only where at least one side of the boundary
   is a mergeable `<div>`/`<p>`/`<br>`. auto-render concatenates consecutive sibling **text** nodes
   with no separator, so inserting one between two adjacent text-node children would make the reflow
   scan a string the renderer never sees — violating the port-fidelity rule the scan section rests on.

   *The collapse must preserve the offset→child map.* Rule 5 maps span offsets back to the child that
   contributed each character, and the collapse removes characters — one surviving newline can come
   from three children at once (boundary + `<br>` + boundary, for `<div><br></div>`). Building the
   string and then running `text.replace(/\n+/g, "\n")` discards the map and gives every later span a
   wrong covered range. So the collapse is applied **during** the build, with the map maintained, and
   a collapsed newline is attributed to its **first** contributing child. Whitespace-only mergeable
   text nodes contribute nothing to the run text, so hand-written test markup with indentation
   between blocks behaves the same as `nh3` output, which carries none.

   Net effect: exactly one `\n` per former boundary. `<div>a</div><div>\[x</div><div>y\]</div>` gives
   `"a\n\[x\ny\]"`, so the span text is `\[x\ny\]` — the shape the Purpose section's measurement
   exercised.
3. Find spans over that text using the scan semantics above.
4. **A span whose covered range is a single child node is skipped** — equivalently, only spans
   covering **two or more children** are ever rewritten.

   This must be stated in terms of *child nodes*, not text nodes. An earlier draft said "wholly inside
   one text-node segment", which is a different and much more destructive rule: a mergeable
   `<div>`/`<p>` child's contribution is not a *text-node* segment, so a span sitting entirely inside
   one attribute-free `<p>` would fail the test and be rewritten — unwrapping the paragraph. That is
   the ordinary shape of authored content: `textelement.html` is
   `<div class="el el--text">{{ el.body|sanitize }}</div>`, whose top-level children are the RTE's
   `<p>`/`<div>` blocks, and `math.js:31` hands `.el--text` straight to `renderMathInElement`. Under
   the old wording `<p>Rozważmy \(x\) …</p>` would lose its paragraph on **every render**, which would
   also falsify the merge-phase invariant, the "`</p><p>` boundaries are the only markup this change
   retroactively touches" claim, and the 6-broken/23,520-intact framing.
5. Any other span is rewritten. Let *covered* be the contiguous child nodes from the one holding the
   span's first character through the one holding its last. Those nodes — and only those; earlier and
   later siblings in the run are untouched — are replaced by three **fragments**: the covered text
   preceding the span, the span itself, and the covered text following it, omitting empties. Each
   fragment may be a *node sequence* rather than a single node (see the `<br>` rule below), so the
   replacement is not bounded to three nodes.
   **"Synthetic" means only the newlines step 2 manufactures from `<div>`/`<p>` wrapping — never the
   `"\n"` contributed by a real authored `<br>`.** Synthetic newlines are dropped from the preceding
   and following fragments and retained only where they fall inside the span.

   **Non-covered mergeable siblings are untouched and survive as elements.** In
   `<div>a</div><div>\[x</div><div>y\]</div><div>b</div>` the first and last divs hold no character of
   the span, so the result is `<div>a</div>`, one text node `\[x\ny\]`, `<div>b</div>` — three
   *children*, of which only the middle is a text node. An earlier draft said "three text nodes"; that
   was wrong, and no argument may rest on it.

   **A real `<br>` inside the covered range but outside the span must survive as an element.** The
   preceding and following fragments are therefore rebuilt as *node sequences* preserving
   attribute-free `<br>` elements, not flattened to a single text node — otherwise
   `<div>a<br>b \[x</div><div>y\]</div>` loses the author's line break either way: dropped as
   "synthetic", or kept as a `\n` character that HTML collapses to a space because the `<br>` element
   it came from was replaced. Inside the span a `\n` character is correct, because there the text is
   LaTeX, not HTML.
6. **All matches in a run are planned from a single derivation, then applied** — the run text and its
   offset→child map are built once, and every rewrite is computed against that one snapshot.

   **Covered ranges may overlap, so planned rewrites are coalesced before any mutation.** A child
   holding the end of one span and the start of the next belongs to *both* ranges — the rule-6 example
   below is exactly that shape. Applying such rewrites in either order destroys a node the other is
   planned against, so ordering alone cannot fix it. Instead: union the covered ranges of all planned
   spans into maximal **disjoint replacement groups**, and replace each group's children with one
   interleaved node sequence — covered text before span 1, span 1, covered text between spans 1 and 2,
   span 2, …, trailing covered text — under the same synthetic-newline-dropping and
   `<br>`-preservation rules rule 5 gives for the preceding and following fragments. Groups are
   disjoint by construction, so the mutations can then be applied right to left with earlier indices
   staying valid.

   Do **not** re-derive after each rewrite. Rule 5's output is adjacent text nodes, so a re-derivation
   sees boundaries that no element ever justified: for
   `[<div>\[a</div>, <div>b\] \(c</div>, "d\)"]` it is undefined whether the second span comes out
   `\(c\nd\)` or `\(cd\)`, because the `<div>`↔text boundary that justified the newline was erased by
   the first rewrite. Planning from one derivation removes the question, and removes the need to argue
   termination — there is no loop over a mutating DOM.

   That same example is also the overlap case: with run text `\[a\nb\] \(c\nd\)`, span 1 covers
   children {1,2} and span 2 covers {2,3}, so the two ranges share child 2 and coalesce into a single
   replacement group spanning {1,2,3}.

> **Merge-phase invariant.** A math span that already lies entirely inside a single text node is
> never *merged*. That is the 23,520 spans measured to render correctly today, so phase 1 cannot
> change how any of them parses.
>
> **Qualification.** An intact span that happens to sit inside the *covered range* of a different,
> broken span — `<div>\(x\) prose \[a</div><div>b\]</div>` — is not merged, but its wrapper is folded
> away and it is relocated into a bare text node. It still renders; a unit case pins that. The
> invariant is about span *parsing*, not about surrounding markup being untouched.
>
> **Phase 1b is carved out too**, exactly as phase 2 is: its whole target is a span lying inside a
> single text node, whose *contents* it rewrites. The corpus measured **0** such spans, so today's
> content is empirically safe — but that is an observation, not a design guarantee, and the
> `sanitize_cell`-shaped option surfaces (MCQ, choice-grid, switch-grid) are unmeasured.

**Inline spans merge too, and that collapses authored lines.** The derived set includes `\(…\)` on
every surface, and KaTeX renders those inline rather than as a block. So
`<div>Prose \(x</div><div>y\) more</div>` becomes one visual line. Accepted: the alternative — merging
only display-mode spans — would leave split inline math permanently broken, which is the same class
of silent failure this spec exists to remove. Covered by a unit case so it is a decision, not a
surprise.

#### Phase 1b — textual boundaries inside a span

Because `sanitize_cell` already flattened cell content at save (Problem 1b), the boundary markers in
a cell arrive as **literal characters** rather than as DOM nodes.

**Traversal — the part that decides whether phase 1b works at all.** It is a **separate full pass
over the same walk**, run after phase 1 completes for the entire subtree and before phase 2 — the
same shape as phase 2, pinned for the same reason. Text nodes that rule 5 *created* are therefore in
scope for it. It runs over every text node reached by the walk, locating spans with the same faithful `splitAtDelimiters` semantics as phase 1,
and it applies to **every span the scan finds, including — in fact especially — the ones rule 4
skipped**. The cell case *is* a rule-4 skip: the span already lies inside one text node. An
implementer who hangs phase 1b off the rule-5 rewrite path — the only place a span is otherwise both
matched and acted on — ships a phase 1b that never fires on any cell, and with every corpus count at
0 there is no test data to reveal it.

**Only `<br>` is rewritten**, matched by the equivalent of `courses/sanitize.py`'s existing `_BR` —
`(?i)<br\s*/?>`: case-insensitive, optional whitespace, optional slash. Enumerating just `<br>` and
`<br/>` would miss `<br />` and `<BR>`, and **that miss would be invisible** — the corpus count for
this shape is 0, and `sanitize_cell` stashes the span *before* `nh3.clean`
(`_MATH_SPAN.sub(_stash, value)` precedes the clean call), so what survives inside a span is
**un-normalised author/browser markup**, which is exactly where `<br />` and `<BR>` come from.
`<div>` and `<p>` are deliberately **not** in
the list: `CELL_TAGS` (`courses/sanitize.py:104`) is `{strong, b, em, i, u, br, span}`, so they can
never appear in flattened cell text, and including them would be unreachable code carrying a real
hazard — `\(a<p>b\)` is a plausible chain of inequalities that would be silently rewritten to
`\(a\nb\)` and render as "ab". Attributes are not tolerated either, for the same narrowing reason.

The residual hazard for `<br>` is much smaller: `a<br>b` as intended mathematics would have to mean
`a < b·r > b`, which no author writes.

This is the textual counterpart of phase 1's DOM merge, and it is what makes math in table cells work
at all.

#### Phase 2 — delimiter promotion

**Runs only after phases 1 and 1b have completed for the entire subtree.** The ordering is not
cosmetic: promote-then-merge would leave a `\(\begin{align*}…\end{align*}\)` that the RTE split
across `<div>`s unpromoted, because it is not yet inside any single text node — and that split case
is precisely the reported symptom.

**Traversal.** A second pass over the same walk, honouring the identical ignored-subtree list — it
must, or promotion would rewrite the TeX inside a `.katex` annotation or mutate the RTE surface. It
operates **per text node**, not per run: phase 1's rule-5 output is several adjacent text nodes, and
a promotion candidate never spans them (a span that spanned nodes would have been merged already).

For every text node reached by that pass, a `\(…\)` span whose content **contains** any of the ten
display-only environments has its delimiters rewritten to `\[…\]`. Specifically:

- **the test is "contains", not "begins with", and that distinction is load-bearing.** Five of the six
  repairable spans in the corpus are `\(`-wrapped and open with `\begin{cases}`, with `\begin{align}`
  *nested inside* — `\(\begin{cases}</p><p>\begin{align}…`. A begins-with test declines to promote
  them, phase 1 has already merged them into one text node, and KaTeX then meets `\begin{align}` in
  inline mode. Measured on the actual stored shape:

  | how the stem reaches KaTeX | result |
  |---|---|
  | inline (begins-with test declines) | **FAIL** — `{align} can be used only in display mode` |
  | display (contains test promotes) | **OK** — renders |

  So a begins-with test would convert five pieces of live content from *inert text* into a *visible
  red error* — a regression presented as a repair. The contains test renders them.

  The argument that promotion is always safe: a span containing a display-only environment cannot
  render inline at all, so its only two outcomes are display or `.katex-error`. Promotion is never
  worse and is usually right;

- **spans are located with the effective delimiter set's partition, not by a raw scan for `\(`.**
  Only a span the effective scan actually *opened with* `\(` may be promoted. On fill-table,
  switch-gate and switch-grid the effective set includes `$$` and the `\begin{…}` pairs, so a `\(…\)`
  sequence sitting **inside** a `$$…$$` span is not a span at all — a raw scan would rewrite its
  delimiters and corrupt the enclosing formula;
- once a candidate span is identified, the rewrite is **`\(` → `\[` and `\)` → `\]`**, hardcoded;
  promotion is about the two libli delimiter forms, not about whatever exotic set a caller registered;
- promotion is a **no-op unless `\[` is in the effective set** for that caller. All ten callers have
  it today, so this is a stated precondition rather than a live branch, but it must not be left
  implicit;
- the environments are matched as **ten exact literal strings, closing brace included** —

```
\begin{align}   \begin{align*}   \begin{alignat}   \begin{alignat*}   \begin{gather}
\begin{gather*} \begin{equation} \begin{equation*} \begin{CD}          \begin{split}
```

  Not ten *names* and not a prefix match. A prefix match on `\begin{align` also matches
  `\begin{aligned}`, and on `\begin{gather` also `\begin{gathered}` — environments Problem 2 lists as
  working in **both** modes. Promoting those would silently convert currently-correct inline math
  into display blocks. (Measured: **0** such spans exist today, so this is prophylaxis, not a repair —
  but it costs nothing and the failure would be invisible.) Enumerating literals also avoids the
  regex `(align|alignat|gather|equation|CD|split)\*?`, which admits the non-existent `CD*`/`split*`.

**The merge-phase invariant does not cover phase 2**: promotion by design rewrites spans that sit
inside a single text node. It carries its own regression coverage.

#### Newlines

The span's text carries exactly one real `\n` at each former boundary: rule 2 emits a newline at any
boundary that does not already carry one, then collapses consecutive newlines to a single one. The
collapse is what guarantees that two adjacent mergeable `<div>`s — or Chrome's empty-line
`<div><br></div>` between two blocks — yield one newline rather than a blank line. That matters: a
blank line in real LaTeX is a `\par` and an error inside `align*`. It would be inert here anyway,
because **KaTeX collapses** whitespace and has no paragraph handling, but making it structural avoids
relying on that. State it that way; an implementer must not carry "LaTeX ignores it" anywhere else.

Losing the `<div>` wrapper for attribute-free prose adjacent to a *display* span is intended, and was
verified visually for `<div>`: KaTeX renders display math as a block, so lead-in and trailing prose
each keep their own line anyway. For inline spans see the note under phase 1.

**`<p>` was not visually verified, and it is the case that actually matters.** All six repairable
spans in the corpus sit at `</p><p>` boundaries, so paragraphs — not divs — are the only markup this
change retroactively touches, and `<p>` carries real block margins in this codebase (`reset.css`'s
`* { margin: 0 }` and the `app.css form p` rule interact here). Verifying the `<p>` case visually,
light and dark, and recording what happens to surrounding paragraph spacing, is a **required step of
the implementation**, not an assumption this spec is entitled to make.

#### Idempotence, failure, cost

**Idempotence.** After one pass every rewritten span lives in a single text node, so a second pass
takes rule 4 and changes nothing; phase 1b finds no literal tag text left inside a span it already
converted; phase 2 is idempotent because a promoted span no longer uses `\(`.
`renderMathInElement` is called repeatedly on the same DOM (quiz feedback swaps, tab reveals,
`libli:reveal` re-measures), so this matters.

**Bounded failure, both hooks.** An unclosed opening delimiter, or a span whose partner sits beyond a
barrier, matches nothing and is left as-is. The whole reflow is wrapped so a failure degrades to
today's behaviour rather than blocking typesetting.

**Hook B needs the same containment**, and it is easy to overlook because the paragraph above is about
the reflow. Hook B runs the ported `findEndOfMath` over `expr`, and `expr` is not guaranteed to be a
string at every call site — `math.js:6` passes `el.textContent`, but this module's whole justification
for hooking is that new callers appear. An exception there propagates out of `katex.render`, where
`math.js` `renderOne`'s `catch` swallows it, leaving the Math element unrendered with no diagnostic.
So Hook B's strip logic is wrapped too, falling through to `original.apply(this, arguments)` with
`expr` untouched.

**Cost.** `math.js:33` calls `renderMathInElement` once per matched element
across the nine selectors listed at `math.js:31`. Those selectors nest — a `.el--tabs` holding
`.el--text` children matches both — so nested content is traversed once per matched ancestor level,
not once in total. The bound is **O(nodes × nesting depth of matched containers)**, which is small in
practice (depth 2-3) and is the same order as auto-render's own repeated work over the same roots.

#### Hook B, precisely

Reuse the ported `findEndOfMath` rather than inventing a second rule. The expression is stripped iff,
after skipping leading whitespace, it **opens** with `\[` or `\(` and `findEndOfMath` for the matching
closer, started just past the opener, lands on a closer whose end is the expression's last
non-whitespace character.

That single condition is exactly right where a regex is not. `/^\s*\\\[([\s\S]*)\\\]\s*$/` is greedy,
so it matches `\[a\] + \[b\]` with the group `a\] + \[b` and would strip the one case that must be
left alone; `findEndOfMath` stops at the first `\]` instead, which is not the end of the expression, so
the strip is correctly refused. And because the port skips the character after a backslash, a
legitimate `\\[2ex]` in the body neither opens nor closes anything, so it does not veto stripping —
without needing any parity rule of our own.

On a match, strip the wrapper. **`displayMode` is left exactly as the caller passed it, for both
wrapper forms.** Both real callers reach `katex.render` through `math.js:6`, which hardcodes
`displayMode: true`, so a Math element containing `\(x\)` renders as display — correct, since a Math
element is a display element by design and its inline-looking wrapper is an author's habit, not an
instruction. The hook writes nothing into `options` — it changes only `expr` — so it passes `options` through
untouched rather than copying it. (An earlier draft required a shallow copy; that was a leftover from
a version that forced `displayMode`, and copying an object nothing writes to is dead work.)
`text_colour.js` wraps the same function and shares the argument list, so leaving the caller's object
alone is also the least surprising behaviour.

## Error handling

| Situation | Behaviour |
|---|---|
| Unclosed `\[` or `\(` in prose | No match; DOM untouched; renders as literal text, as today |
| Span crossing a barrier (`<td>`, `<li>`, `<strong>`, colour span, `<div class=…>`) | Not merged; unchanged |
| Span split across `<div>`s *inside* a barrier (`<td>`, `<li>`) | Merged — the walk descends into barriers |
| Table-cell span holding literal `<br>` text | Converted to `\n` by phase 1b; renders |
| Intact span inside another span's covered range | Relocated into a bare text node; still renders |
| Split **inline** `\(…\)` span | Merged; the two authored lines collapse to one (accepted) |
| `\\[2ex]` row spacing inside a display block | Ported `findEndOfMath` skips the character after a backslash; it neither opens nor closes |
| `$$…$$` split span on fill-table / switch-gate / switch-grid | Reflowed — the caller's set registers it — **but only on a page that also contains a `\(` or `\[`** (see below) |
| `$$…$$` on the other seven surfaces | Not a delimiter there; untouched |
| `root` itself matches an ignored selector | Returns immediately, does nothing |
| `renderMathInElement` or `katex` absent | Hooks never install; today's behaviour |
| Module included twice | Marker guard; installs once |
| Reflow throws | Caught; typesetting never blocked. The DOM may be left **partially** rewritten — atomicity is per-element |
| `\[a\] + \[b\]` reaching `katex.render` | `findEndOfMath` stops at the first `\]`, which is not the expression's end; not stripped |
| `\(x\)` in a Math element | Wrapper stripped; `displayMode` stays as passed (`true`) |
| `options` undefined at Hook B | Passed through as-is; the hook writes nothing to it |
| Display-only environment anywhere inside `\(…\)` | Promoted to `\[…\]` |
| `cases`, `matrix`, … inside `\(…\)` | Untouched; already works inline |
| Math typed inside the RTE surface | Deliberately not typeset live; renders after save |

## Testing

**Falsification is the acceptance criterion**: each test must be shown to go **red** when its guard
is removed.

### Non-automated acceptance item

**Verify the `</p><p>` repair visually, light and dark, and record the paragraph-spacing outcome in
the PR.** This is the one manual step the spec requires (see `#### Newlines`): all six retroactively
repaired spans sit at `</p><p>` boundaries, `<p>` carries real block margins in this codebase, and no
automated case covers how the surrounding spacing looks once the wrappers are folded away. Screenshot
before and after.

**Baseline** — full non-e2e suite green at **4559 passed, 1 skipped**, measured at branch point
`0a9c2882`. That is a **floor, not the post-change target**: `test_math_reflow_defaults.py` and the
new assertions in `test_text_colour_script_order.py` are non-e2e and will raise the total. The
implementation must state the new expected count so "did the suite stay green?" has a target number;
only `test_e2e_math_reflow.py` and `test_e2e_math_reflow_dom.py` stay outside it (`-m e2e`).

### `tests/test_e2e_math_reflow.py` (e2e-marked, real Chromium)

1. **Golden path through the real UI.** Paste **this exact input** into the RTE of a text element:

   ```
   \[\begin{align*}
   a^n\cdot a^k&=a^{n+k}\\
   a^n: a^k&=a^{n-k}\\
   \left(a^n\right)^k&=a^{nk}
   \end{align*}\]
   ```

   then **save**, open the lesson, and assert exactly one `.katex` node with three aligned rows and
   no `.katex-error`. **The `\[…\]` wrapper is mandatory**: a text element's delimiter set is
   `math.js`'s `INLINE_DELIMS` (`\(`/`\[` only), and bare `\begin{align*}` there is an explicit
   non-goal — a test written from the unwrapped block in this spec's Purpose section could never go
   green.

   **The test must first assert the split actually happened**, or it can pass vacuously. The spec
   itself calls the stored shape "the unknown under test", which means the test may not assume it:
   `keyboard.type` with newlines presses Enter and yields `<div>` blocks, but a clipboard or
   `insertText` paste can land the whole block in a **single text node** — in which case the assertion
   is green on `master` with none of this work, and stays green if phase 1 later regresses. So before
   asserting the render, assert that the **saved HTML** for that element contains a `</div><div>` or
   `<br>` boundary *between* the `\[` and the `\]`. If the chosen gesture does not produce one, the
   test fails loudly rather than silently testing nothing.
2. The same wrapped block in a **callout body** (fixture), and — separately — in a **table cell**
   stored in the shape `sanitize_cell` actually produces (literal `&lt;br&gt;` inside the span), to
   pin phase 1b.
3. A **Math element** whose `latex` carries the `\[…\]` wrapper renders instead of erroring; and one
   carrying `\(x\)` renders as display.
4. `\(\begin{align*}…\end{align*}\)` renders as display — **phase 2's own regression coverage**.
5. `\[a\] + \[b\]` in a Math element is left alone — the ported closer search stops short of the
   expression's end, so the strip is refused.
6. A display block containing `\\[2ex]` reflows and strips correctly — pins the ported
   `findEndOfMath` (a backslash skips the next character), not a parity rule.
7. **Regression**: single-line `\(x^2\)` and single-line `\[…\]` render identically before and after.
8. **Idempotence**: a re-rendering surface (quiz feedback swap or tab reveal) still shows one
   `.katex` node.

### `tests/test_e2e_math_reflow_dom.py` (e2e-marked; DOM table driven from a Playwright page)

**Harness shape**: follow `tests/test_e2e_text_colour.py:46-47,143-145` — `page.set_content(...)` with
a bare document, then `page.add_script_tag(path=…)` for the vendored KaTeX and for `math_reflow.js`.
Do **not** reach for `live_server` plus staticfiles (`static()` no-ops under `DEBUG=False` in this
repo). This is also why "the export is unconditional" is a contract requirement rather than a nicety.

Named `test_e2e_…` so filename and marker agree: `pyproject.toml` sets `addopts = "-q -m 'not e2e'"`,
so this file is **excluded from the 4559-test baseline** and runs only under `-m e2e`. A reader
checking "did the DOM cases run?" against the baseline count would otherwise be misled.

Direct DOM-in/DOM-out cases against `window.libliMathReflow`:

- two spans in one run, siblings outside the covered range untouched (rule 5). Measured, the two
  spans come out **adjacent with no separator** — the boundary newline between them is synthetic and
  is dropped in the second replacement group. Harmless, since auto-render re-joins adjacent text
  nodes and parses both, but the assertion must expect the adjacent form;
- synthetic-newline placement: `<div>a</div><div>\[x</div><div>y\]</div><div>b</div>` → exactly three
  children: `<div>a</div>`, a text node holding `\[x` + newline + `y\]`, `<div>b</div>`. Stating it in
  node terms also pins "non-covered mergeable siblings survive as elements"; phrasing it as three
  bare values reads as three text nodes, the reading rule 5 exists to correct;
- a `<div>` with element content beyond `<br>` acts as a barrier;
- a `<div class="ta-center">` acts as a barrier and keeps its class;
- **a span split across two `<div>`s inside a `<td class="ta-center">` merges** — barrier descended.
  The `<td>` **must** be wrapped in `<table><tbody><tr>`: measured, a bare `<td>` outside a table is
  dropped by the HTML parser, leaving the two divs as direct children of the root, so the unwrapped
  case passes for entirely the wrong reason;
- **nested split inside a mergeable `<div>` that the parent then folds** — pins post-order traversal;
- a bystander intact span inside another span's covered range still renders (invariant qualification);
- a split **inline** `\(…\)` span merges (accepted line collapse);
- phase 1b: a single text node containing `\[a<br>b\]` as literal text becomes `\[a\nb\]` — reached
  via a **rule-4 skip**, not via a rule-5 rewrite;
- phase 1b leaves `\(a<p>b\)` alone (only `<br>` is rewritten);
- ported `findEndOfMath`: a span containing an escaped `\\]` closes at the real closer, and a `\]`
  inside braces (`\[\text{a\]b}\]`) is not accepted as the closer;
- a real `<br>` inside the covered range but outside the span survives as a `<br>` element;
- phase 2 does **not** promote a `\(…\)` sequence sitting inside a `$$…$$` span under the default
  delimiter set;
- a `\(…align*…\)` span split across two `<div>`s comes out **both merged and promoted** — pins the
  phase ordering;
- **Hook B leading whitespace**: `  \[x\]  ` (padded) is still stripped — Hook B skips leading
  whitespace before testing the opener, and that skip is a real, removable guard (phase 2's
  contains-test has none, so the old phase-2 whitespace case pinned nothing);
- each ignored subtree: `pre`, `code`, `textarea`, `[contenteditable]`, `.katex`, **and
  `.katex-error`** — the last carrying a payload that would otherwise be rewritten, e.g.
  `<span class="katex-error">\(a<br>b\)</span>` asserted byte-identical (phase 1b would convert that
  literal `<br>`, and a `\(…align*…\)` payload would be promoted by phase 2). The
  `[contenteditable]` case asserts byte-identical `innerHTML` **both** with the surface as `root` and
  with an ancestor as `root`, the latter built from the choicegrid shape;
- delimiter set derived from `options.delimiters`, plus a `$$` and a `\begin{align}` case under the
  hardcoded defaults;
- **C3**: the unclosed-opener break, which is observable **only with mixed delimiters** — measured,
  `<div>\[oops</div><div>\[a</div><div>b\]</div>` merely pairs the first `\[` with the only `\]`,
  which is correct and tests nothing. Use `<div>\(oops</div><div>$$a</div><div>b$$</div>`: the
  unclosed `\(` must suppress the complete `$$…$$` span that follows, DOM byte-identical;
- **C4**: `\(\begin{aligned}a&=1\\b&=2\end{aligned}\)` is **not** promoted (exact-literal match);
- **C5**: `\(\begin{cases}` + split `\begin{align}` + `\end{cases}\)` — built from the *actual stored
  shape* of `ChoiceQuestionElement` 218 — comes out merged **and** promoted, and renders with zero
  `.katex-error`;
- `libliMathReflow(document)` does not throw (the `matches` guard);
- `libliMathReflow(documentFragment)` **actually merges** a span split across two top-level `<div>`
  children, byte-checking the resulting child sequence. "Does not throw" is precisely the assertion
  the contract section rules out as vacuous — an implementation that early-returns for any
  non-Element root would satisfy it while doing nothing;
- `libliMathReflow` on a root **inside** an ignored subtree is a no-op (the `closest` guard);
- a forced internal throw (a poisoned `options.delimiters`) still lets the original renderer run;
- **a throw *mid-walk*, after at least one rewrite has been applied**, asserting the real
  post-condition — per-element atomicity, ignored subtrees untouched — which the poisoned-delimiters
  case cannot reach because it throws before any mutation. The try/catch is the only safety net for an
  implementation bug, and an
  untested `catch` is exactly what "falsification is the acceptance criterion" exists to prevent;
- **overlapping covered ranges**: `[<div>\[a</div>, <div>b\] \(c</div>, "d\)"]` — the two spans share
  child 2 — coalesces into one replacement group; assert the exact resulting child sequence;
- idempotence: a second call is a no-op.

### `tests/test_math_reflow_defaults.py` (pytest, static)

The module's hardcoded default-delimiter list matches what the vendored
`courses/static/courses/vendor/katex/contrib/auto-render.min.js` actually contains, so a KaTeX
upgrade reddens rather than silently diverging.

**The extraction contract must be stated, or the test passes vacuously** — the exact failure mode
`test_text_colour_script_order.py` already guards against. The minified file encodes booleans as
`!0`/`!1`, not `true`/`false`, and encodes each delimiter as JS source (`left:"\("` is the
two-character string `\(`). The test must parse `{left:…,right:…,display:…}` triples out of the
minified source, map `!0`→`True` and `!1`→`False`, unescape the JS string literals, compare the full
triples **in order** against the module's list, and **assert exactly eight triples were extracted**
before comparing anything.

The **module side needs the same treatment**, or the test needs a second unspecified JS parser:
`math_reflow.js` assigns its default list to a named property the test can read deterministically, and
the exactly-eight assertion is made on that side too.

### Wiring — extend `tests/test_text_colour_script_order.py`

That module already parses `{% static '…' %}` across the same five templates and already asserts
`auto-render.min.js` < `text_colour.js` < callers, with a deliberate anti-vacuity self-check. Extend
it rather than re-implementing the parser. It must additionally assert:

- `math_reflow.js` present in all five templates;
- the full order `katex.min.js` < `auto-render.min.js` < `math_reflow.js` < `text_colour.js`, and
  `math_reflow.js` < `math.js` in the three templates that load it;
- **the tag sits inside the same `{% if has_math %}` block as `auto-render.min.js`** in the four
  gated templates — an index-based check over `{% static %}` occurrences passes identically whether
  the tag is inside or outside, so containment needs its own assertion;
- the module registers no `DOMContentLoaded` retry. **That assertion must strip comments before
  matching**, since the module is required to carry a comment explaining why it does not copy
  `text_colour.js`'s retry. Match **quote-agnostically** (`addEventListener\(\s*["']DOMContentLoaded`),
  since a module written with single quotes would slip past a double-quoted literal and make the
  assertion vacuous; falsification must prove it reddens with **either** quote style, in
  comment-stripped source. (This repo has been bitten by exactly that:
  `test_element_state_write_routes.py` regexes raw source including comments.)
- the existing anti-vacuity self-check must cover the new assertions too — a parser returning `[]`
  makes every ordering assertion pass.

## Risks

| Risk | Mitigation |
|---|---|
| Phase 1 changes how any of the 23,520 intact spans parses | Rule 4 makes them an unentered path; e2e 7 |
| Surrounding markup of a bystander span folded away | Invariant qualified; own unit case |
| Phase 2 rewrites existing single-node content | Deliberate; own coverage at e2e 4 |
| Phase 1b rewrites something legitimate | Confined to the interior of a matched span; `<br>` is meaningless in LaTeX |
| Barrier read as "do not enter", skipping cells and list items | Stated explicitly; `<td class="ta-center">` unit case |
| Live `childNodes` mutation during the walk | Post-order + snapshotted child list; nested-split unit case |
| Reflow and auto-render pair a span differently | Scan semantics reproduce `splitAtDelimiters` exactly |
| Hardcoded defaults drift from a KaTeX upgrade | `test_math_reflow_defaults.py` |
| Reflow mutates the RTE surface and is persisted | `[contenteditable]` ignored; byte-identity both root shapes |
| Double-wrapping with `text_colour.js`, or a double include | No retry; `__libliMathReflowWrapped` marker |
| Author centres the formula, nothing merges, symptom persists silently | Named limitation; `ta-center` DOM case and e2e 9 pin the failure mode; attribute-homogeneous widening deferred to a follow-up |
| Script shipped on math-free pages | Containment assertion inside `{% if has_math %}` |
| MCQ / choice-grid / switch-grid option surfaces unmeasured | Stated in the corpus section; they are `sanitize_cell`-shaped, so phase 1b governs them and behaves as it does for cells |
