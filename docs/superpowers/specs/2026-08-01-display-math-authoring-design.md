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
`div`/`p`, so `<br>` is the only shape a cell can present.

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
| mergeable (partner past a `<div>`/`<p>`/`<br>` boundary — phase 1 fixes these) | **6** |
| past a non-structural barrier (left alone) | **0** |
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
- if `root` **itself** matches an ignored selector the function returns immediately, doing nothing.
  This is not covered by "the walk does not descend into them": `math.js` already had to special-case
  a self-matching root (`scope.matches("[data-katex]")`), so it is a live shape here.

**Hook A — `window.renderMathInElement(root, options)`**: call `window.libliMathReflow(root, options)`,
then call through.

**Hook B — `window.katex.render(expr, element, options)`**: strip one balanced surrounding `\[…\]` or
`\(…\)` from `expr`, then call through. Covers the Math element and the `[data-math-live]` preview.

**Installation is once, unconditional, with no retry, and guarded by a marker.**
`text_colour.js:587-595` re-runs its installs on `DOMContentLoaded` when either global was missing.
`math_reflow.js` must **not** copy that: marker properties do not propagate through another module's
wrapper, so a retry would wrap an already-wrapped chain and reflow twice per call. A single install is
safe because the module loads after `katex.min.js` and `auto-render.min.js` in document order. It
still sets and checks a `__libliMathReflowWrapped` marker — as a **double-include guard** (a shared
partial, a future refactor), not as a retry enabler. If either global is absent the module installs
nothing and every path keeps today's behaviour.

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
paint would bypass both hooks with no error. Placing the module before `text_colour.js` also means
`text_colour.js` installs second and owns the outer function, keeping its retry logic correct.

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
$$ … $$            \( … \)            \[ … \]
\begin{equation} … \end{equation}     \begin{align} … \end{align}
\begin{alignat} … \end{alignat}       \begin{gather} … \end{gather}
\begin{CD} … \end{CD}
```

Two of those (`\(`, `\[`) overlap with the seven explicit callers; the extra **six** are the actual
asymmetry. On fill-table, switch-gate and switch-grid, split `$$…$$` and `\begin{align}` spans will
therefore reflow, and will not on the other seven surfaces. That is pre-existing asymmetry in what
those surfaces accept; the module inherits it rather than creating it, and deliberately does not
paper over it.

#### Scan semantics — reproduce `splitAtDelimiters`

The merged text node is handed straight to auto-render, which re-splits it. If the two disagree about
where a span begins or ends, the reflow merges one region and the renderer parses another. So:

- **Position order and precedence.** Walk positions left to right; at each position test the
  delimiters in the caller's array order, first match wins. Do not use longest-match or a
  reordered alternation.
- **Opening parity.** A candidate delimiter only *opens* a span when the run of backslashes
  immediately preceding its first character has even length. Without this,
  `\[\begin{align*} a&=b \\[2ex] c&=d \end{align*}\]` is misread: `\\[2ex]` contains the characters
  `\[`. Stated generally for every delimiter in the set — for a delimiter whose own first character
  is a backslash, that character is not counted as part of the preceding run; for `$$`, which starts
  with no backslash, the rule reduces to "not preceded by an odd number of backslashes".
- **Closing search takes the first literal occurrence, with no parity filter** — because that is
  exactly what auto-render's `splitAtDelimiters` does (it performs no escape handling at all).
  The asymmetry is deliberate: parity decides where a span *opens*, and auto-render's own semantics
  decide where it *ends*, so the reflow can never pair a span differently from the renderer.

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

**Ignored subtrees** are anything matching:

- auto-render's own default ignore list — `script, noscript, style, textarea, pre, code, option`
  (`pre` and `code` are in `ALLOWED_TAGS`, so this is reachable);
- **`[contenteditable]`** — `text_toolbar.js:196-197` mounts a `contenteditable` `.rte-surface` in
  `editor.html`, and `sync()` writes that surface's `innerHTML` back into the POSTed textarea. A DOM
  mutation inside the RTE is therefore a **data** mutation, and would break the render-only
  guarantee. Load-bearing, not hygiene. Its user-visible consequence is deliberate and must be
  documented for testers: **display math is not typeset live inside the editing surface** — the round
  trip is paste → save → view;
- **`.katex`** — after the first pass KaTeX's output holds the original TeX in a MathML
  `<annotation encoding="application/x-tex">`; re-entering would let phase 2 rewrite the string
  screen readers and copy-paste consumers receive. `math` and `annotation` are listed alongside it
  for defence in depth only — KaTeX nests them **inside** `.katex`, so `.katex` already subsumes
  both; they matter only if KaTeX's output mode ever changes.

The ignore list is **deliberately fixed** rather than derived from `options.ignoredTags` /
`ignoredClasses` (which auto-render does honour). No caller passes them today, and a fixed list is a
superset of what any caller would ignore — ignoring more than the renderer is always safe, whereas
ignoring less would let the reflow act on a subtree the renderer skips. The delimiter set is derived
precisely because the opposite holds there: scanning a *different* delimiter set than the renderer is
not safe in either direction.

**Mergeable vs barrier.** Within one element's child list, a child node is *mergeable* if it is

- a text node, or
- a `<br>` **carrying no attributes**, or
- a `<div>` or `<p>` **carrying no attributes** whose descendants are exclusively text nodes and
  attribute-free `<br>` elements.

Every other node is a **barrier**. The attribute condition is load-bearing: `ALIGN_CLASS_TAGS` puts
`ta-left`/`ta-center`/`ta-right` on `div`, `p`, `h2`–`h4`, `blockquote`, `li`, and `text_toolbar.js`
emits them. Merging a `<div class="ta-center">` into a bare text node would discard the centring.

#### Phase 1 — merge

For each element reached by the walk, over its snapshotted child list:

1. Partition the children into maximal **runs** of consecutive mergeable nodes. Barriers terminate a
   run. Each run is processed independently.
2. Build the run's linear text: a text node contributes its data; a `<br>` contributes `"\n"`; a
   mergeable `<div>`/`<p>` contributes `"\n"` + its text (its own `<br>`s becoming `"\n"`) + `"\n"`.
3. Find spans over that text using the scan semantics above.
4. A span **wholly inside one text-node segment** is skipped.
5. Any other span is rewritten. Let *covered* be the contiguous child nodes from the one holding the
   span's first character through the one holding its last. Those nodes — and only those; earlier and
   later siblings in the run are untouched — are replaced by up to three text nodes: the covered text
   preceding the span, the span itself, and the covered text following it, omitting empties.
   **The synthetic newlines from step 2 are dropped from the preceding and following fragments and
   retained only where they fall inside the span.** So
   `<div>a</div><div>\[x</div><div>y\]</div><div>b</div>` yields `a`, `\[x\ny\]`, `b` — not
   `"\na\n"` and a whitespace-only node that "omitting empties" would not remove.
6. Matches are processed left to right, re-deriving the run's segments after each rewrite.
   **This terminates**: after a rewrite the span lies in a single text node, so rule 4 skips it on
   re-derivation and the scan strictly advances past it.

> **Merge-phase invariant.** A math span that already lies entirely inside a single text node is
> never *merged*. That is the 23,520 spans measured to render correctly today, so phase 1 cannot
> change how any of them parses.
>
> **Qualification.** An intact span that happens to sit inside the *covered range* of a different,
> broken span — `<div>\(x\) prose \[a</div><div>b\]</div>` — is not merged, but its wrapper is folded
> away and it is relocated into a bare text node. It still renders; a unit case pins that. The
> invariant is about span *parsing*, not about surrounding markup being untouched.

**Inline spans merge too, and that collapses authored lines.** The derived set includes `\(…\)` on
every surface, and KaTeX renders those inline rather than as a block. So
`<div>Prose \(x</div><div>y\) more</div>` becomes one visual line. Accepted: the alternative — merging
only display-mode spans — would leave split inline math permanently broken, which is the same class
of silent failure this spec exists to remove. Covered by a unit case so it is a decision, not a
surprise.

#### Phase 1b — textual boundaries inside a span

Because `sanitize_cell` already flattened cell content at save (Problem 1b), the boundary markers in
a cell arrive as **literal characters** rather than as DOM nodes. So, inside a matched span only,
a literal `<br>`, `<br/>`, `<div>`, `</div>`, `<p>` or `</p>` character sequence — matched by tag
name, case-insensitively, attributes allowed — becomes `"\n"`.

This is the exact textual counterpart of phase 1's DOM merge and is what makes math in table cells
work at all. It is confined to the interior of a span that has already matched, so prose is never
touched; and `<br>` has no meaning in LaTeX, so nothing legitimate is being rewritten.

#### Phase 2 — delimiter promotion

**Runs only after phases 1 and 1b have completed for the entire subtree.** The ordering is not
cosmetic: promote-then-merge would leave a `\(\begin{align*}…\end{align*}\)` that the RTE split
across `<div>`s unpromoted, because it is not yet inside any single text node — and that split case
is precisely the reported symptom.

For every text node reached by the walk, a `\(…\)` span whose content — **after skipping leading
whitespace**, which a paste plausibly produces — begins with one of the ten display-only environments
has its delimiters rewritten to `\[…\]`. Specifically:

- the **opening parity rule applies** when locating the `\(`;
- the delimiters are **hardcoded `\(` → `\[`**, not derived; promotion is about the two libli
  delimiter forms, not about whatever exotic set a caller registered;
- promotion is a **no-op unless `\[` is in the effective set** for that caller. All ten callers have
  it today, so this is a stated precondition rather than a live branch, but it must not be left
  implicit;
- the environment set is enumerated literally —

```
align  align*  alignat  alignat*  gather  gather*  equation  equation*  CD  split
```

— rather than as `(align|alignat|gather|equation|CD|split)\*?`, which would also admit the
non-existent `CD*` and `split*`.

**The merge-phase invariant does not cover phase 2**: promotion by design rewrites spans that sit
inside a single text node. It carries its own regression coverage.

#### Newlines

The span's text carries a real `\n` at each former boundary. Two adjacent mergeable `<div>`s produce
a blank line, which in real LaTeX is a `\par` and an error inside `align*`; it is inert here only
because **KaTeX collapses** whitespace and has no paragraph handling. State it that way — an
implementer must not carry "LaTeX ignores it" anywhere else.

Losing the `<div>` wrapper for attribute-free prose adjacent to a *display* span is intended and was
verified visually: KaTeX renders display math as a block, so lead-in and trailing prose each keep
their own line anyway. For inline spans see the note under phase 1.

#### Idempotence, failure, cost

**Idempotence.** After one pass every rewritten span lives in a single text node, so a second pass
takes rule 4 and changes nothing; phase 1b finds no literal tag text left inside a span it already
converted; phase 2 is idempotent because a promoted span no longer uses `\(`.
`renderMathInElement` is called repeatedly on the same DOM (quiz feedback swaps, tab reveals,
`libli:reveal` re-measures), so this matters.

**Bounded failure.** An unclosed opening delimiter, or a span whose partner sits beyond a barrier,
matches nothing and is left as-is. The whole reflow is wrapped so a failure degrades to today's
behaviour rather than blocking typesetting.

**Cost.** O(nodes under `root`). `math.js:33` calls `renderMathInElement` once per matched element
across the nine selectors listed at `math.js:31`, and roots are per-element, so total added traversal
is bounded by one pass over the page's element subtrees — the same order as auto-render's own work.

#### Hook B, precisely

Two conditions, both required — the guard is part of the logic, not commentary beside it:

1. the expression matches `/^\s*\\\[([\s\S]*)\\\]\s*$/` or `/^\s*\\\(([\s\S]*)\\\)\s*$/`; **and**
2. the captured group contains none of `\[`, `\]`, `\(`, `\)` **counted with the parity rule**, so a
   legitimate `\\[2ex]` in the body does not veto stripping.

`[\s\S]*` is greedy, so condition 1 alone would match `\[a\] + \[b\]` with the group `a\] + \[b` and
strip exactly the case that must be left alone.

On a match, strip the wrapper. **`displayMode` is left exactly as the caller passed it, for both
wrapper forms.** Both real callers reach `katex.render` through `math.js:6`, which hardcodes
`displayMode: true`, so a Math element containing `\(x\)` renders as display — correct, since a Math
element is a display element by design and its inline-looking wrapper is an author's habit, not an
instruction. The hook **shallow-copies** `options` (creating one when `undefined`) and never mutates
the caller's object; `text_colour.js` wraps the same function and shares the argument list.

## Error handling

| Situation | Behaviour |
|---|---|
| Unclosed `\[` or `\(` in prose | No match; DOM untouched; renders as literal text, as today |
| Span crossing a barrier (`<td>`, `<li>`, `<strong>`, colour span, `<div class=…>`) | Not merged; unchanged |
| Span split across `<div>`s *inside* a barrier (`<td>`, `<li>`) | Merged — the walk descends into barriers |
| Table-cell span holding literal `<br>` text | Converted to `\n` by phase 1b; renders |
| Intact span inside another span's covered range | Relocated into a bare text node; still renders |
| Split **inline** `\(…\)` span | Merged; the two authored lines collapse to one (accepted) |
| `\\[2ex]` row spacing inside a display block | Parity rule: not an opening delimiter |
| `$$…$$` split span on fill-table / switch-gate / switch-grid | Reflowed — the caller's set registers it |
| `$$…$$` on the other seven surfaces | Not a delimiter there; untouched |
| `root` itself matches an ignored selector | Returns immediately, does nothing |
| `renderMathInElement` or `katex` absent | Hooks never install; today's behaviour |
| Module included twice | Marker guard; installs once |
| Reflow throws | Caught; the original `renderMathInElement` runs on the untouched DOM |
| `\[a\] + \[b\]` reaching `katex.render` | Condition 2 fails; not stripped |
| `\(x\)` in a Math element | Wrapper stripped; `displayMode` stays as passed (`true`) |
| `options` undefined at Hook B | Fresh object constructed; caller's argument never mutated |
| Display-only environment inside `\(…\)`, any leading whitespace | Promoted to `\[…\]` |
| `cases`, `matrix`, … inside `\(…\)` | Untouched; already works inline |
| Math typed inside the RTE surface | Deliberately not typeset live; renders after save |

## Testing

**Falsification is the acceptance criterion**: each test must be shown to go **red** when its guard
is removed.

**Baseline** — full non-e2e suite green at **4559 passed, 1 skipped**, measured at branch point
`0a9c2882`.

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
   green. This case must drive the real gesture; the stored shape a real multi-line paste produces is
   the unknown under test.
2. The same wrapped block in a **callout body** (fixture), and — separately — in a **table cell**
   stored in the shape `sanitize_cell` actually produces (literal `&lt;br&gt;` inside the span), to
   pin phase 1b.
3. A **Math element** whose `latex` carries the `\[…\]` wrapper renders instead of erroring; and one
   carrying `\(x\)` renders as display.
4. `\(\begin{align*}…\end{align*}\)` renders as display — **phase 2's own regression coverage**.
5. `\[a\] + \[b\]` in a Math element is left alone (Hook B condition 2).
6. A display block containing `\\[2ex]` reflows and strips correctly (parity rule).
7. **Regression**: single-line `\(x^2\)` and single-line `\[…\]` render identically before and after.
8. **Idempotence**: a re-rendering surface (quiz feedback swap or tab reveal) still shows one
   `.katex` node.

### `tests/test_math_reflow_unit.py` (e2e-marked; DOM table driven from a Playwright page)

Direct DOM-in/DOM-out cases against `window.libliMathReflow`:

- two spans in one run, siblings outside the covered range untouched (rule 5);
- synthetic-newline placement: `<div>a</div><div>\[x</div><div>y\]</div><div>b</div>` → exactly
  `a`, `\[x\ny\]`, `b`;
- a `<div>` with element content beyond `<br>` acts as a barrier;
- a `<div class="ta-center">` acts as a barrier and keeps its class;
- **a span split across two `<div>`s inside a `<td class="ta-center">` merges** — barrier descended;
- **nested split inside a mergeable `<div>` that the parent then folds** — pins post-order traversal;
- a bystander intact span inside another span's covered range still renders (invariant qualification);
- a split **inline** `\(…\)` span merges (accepted line collapse);
- phase 1b: a single text node containing `\[a<br>b\]` as literal text becomes `\[a\nb\]`;
- a `\(…align*…\)` span split across two `<div>`s comes out **both merged and promoted** — pins the
  phase ordering;
- phase 2 with leading whitespace: `\( \begin{align*}…\)` promotes;
- each ignored subtree: `pre`, `code`, `textarea`, `[contenteditable]`, `.katex`. The
  `[contenteditable]` case asserts byte-identical `innerHTML` **both** with the surface as `root` and
  with an ancestor as `root`;
- delimiter set derived from `options.delimiters`, plus a `$$` and a `\begin{align}` case under the
  hardcoded defaults;
- idempotence: a second call is a no-op.

### `tests/test_math_reflow_defaults.py` (pytest, static)

The module's hardcoded default-delimiter list matches what the vendored
`courses/static/courses/vendor/katex/contrib/auto-render.min.js` actually contains, so a KaTeX
upgrade reddens rather than silently diverging.

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
  `text_colour.js`'s retry; assert on the call form `addEventListener("DOMContentLoaded"` in
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
| Script shipped on math-free pages | Containment assertion inside `{% if has_math %}` |
| MCQ / choice-grid / switch-grid option surfaces unmeasured | Stated in the corpus section; they are `sanitize_cell`-shaped, so phase 1b governs them and behaves as it does for cells |
