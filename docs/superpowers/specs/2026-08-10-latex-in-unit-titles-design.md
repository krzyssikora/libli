# LaTeX in unit titles

## Purpose

A `ContentNode.title` containing `\(...\)` or `\[...\]` is displayed verbatim everywhere
it appears. Authors see raw backslashes and delimiters instead of typeset maths, in the
unit heading, the previous/next navigation buttons, the contents tree, the breadcrumbs,
and every management surface that lists units.

Two independent causes:

1. **The renderer never looks there.** `courses/static/courses/js/math.js:31` runs KaTeX
   auto-render over a hard-coded selector list (`.el--text, .el--table, .el--gallery,
   .el--tabs, .fillgate, .stepper, .markdone, .guessnumber, .spoiler__toggle,
   .callout__heading`). No title selector is in it.

2. **KaTeX is usually not loaded at all.** The vendor assets are gated on `has_math`
   (`templates/courses/lesson_unit.html:37,71-77`), and `has_math` is computed purely from
   the unit's *elements* and *questions* (`courses/views.py:406`, `:1318`, `:1588`;
   `courses/views_review.py:101`). A unit whose only maths is in its title ships no KaTeX,
   so fixing cause 1 alone would leave it unrendered. Five of the pages that display unit
   titles — course outline, course results, analytics matrix, analytics breakdown, review
   queue — load no KaTeX under any condition today.

A third defect surfaced while scoping the above, and is in scope because the shared
partial introduced below fixes it as a side effect:

3. **`math.js` is missing from two pages that do load KaTeX.**
   `templates/courses/quiz_results.html:63-66` and
   `templates/courses/manage/review_submission.html:135-138` load `katex.min.js`,
   `auto-render.min.js`, `math_reflow.js` and `text_colour.js` but **not** `math.js`.
   `renderInlineText` therefore never runs on those two pages; they typeset only what
   `question.js`/`quiz.js` reach. This is pre-existing and independent of titles.

**Decisions taken during design.** Maths in titles is a first-class authoring capability,
not a one-off repair of imported content, so every read-only display surface is in scope.
Asset loading extends the existing server-side `has_math` gate rather than introducing a
client-side sniffer or dropping the gate. Maths inside compact chrome is normalised by CSS
so it cannot alter row height. Plain-text contexts strip the delimiters.

**Non-goals.** No authoring affordance is added: the title inputs stay plain `<input
type="text">` and authors type the delimiters by hand, exactly as they already do for table
cells and tab labels. A live preview beneath the title field, or a MathLive field, may
follow as separate work. No change to the delimiter set, to `has_math_delimiters`, or to
how element bodies are typeset. No server-side KaTeX rendering. Titles are not sanitised
or validated for balanced delimiters — an unclosed `\(` renders as raw text, which is
KaTeX auto-render's existing behaviour everywhere else in the app.

## Architecture

### 1. `data-math-title` marks display sites

Adding a class name per surface to `renderInlineText`'s list would be brittle, and would
put the include/exclude decision in a place where it cannot be reviewed against the
surrounding markup. Instead every **read-only display** of a node title gains a
`data-math-title` attribute, and `renderInlineText` gains exactly one new entry:
`[data-math-title]`.

The twenty-three display sites, across fourteen templates:

| Surface | File | Lines |
| --- | --- | --- |
| Lesson unit heading | `templates/courses/_lesson_article.html` | 7 |
| Quiz unit heading | `templates/courses/_quiz_article.html` | 5 |
| Previous / next nav | `templates/courses/_unit_footer.html` | 14, 48 |
| Contents tree + mobile drawer | `templates/courses/_unit_tree_node.html` | 15, 25, 60 |
| Breadcrumbs | `templates/courses/_unit_crumbs.html` | 36 |
| Course outline | `templates/courses/_outline_node.html` | 7, 21 |
| Quiz results heading | `templates/courses/quiz_results.html` | 12 |
| Course results rows | `templates/courses/course_results.html` | 21 |
| Analytics matrix | `templates/courses/manage/analytics_matrix.html` | 115, 116, 126 |
| Analytics breakdown | `templates/courses/manage/_breakdown_node.html` | 6, 24, 30 |
| Review queue | `templates/courses/manage/review_queue.html` | 15, 30 |
| Review submission heading | `templates/courses/manage/review_submission.html` | 58 |
| Editor heading | `templates/courses/manage/editor/editor.html` | 80 |
| Editor preview heading | `templates/courses/manage/editor/_preview.html` | 6 |

Review queue lines 15 and 30 interpolate the student name and the title into one `<span>`.
The attribute must go on a `<span>` wrapping the title alone, not on the shared parent —
otherwise a student whose display name happens to contain `\(` would be typeset too.

Five sites are **deliberately excluded**, because the raw text is load-bearing rather than
displayed:

| Excluded site | File | Line | Why |
| --- | --- | --- | --- |
| Builder inline rename input | `templates/courses/manage/_tree_node.html` | 49 | `<input value=>` — the edit buffer; typesetting would corrupt what is saved |
| Editor settings title input | `templates/courses/manage/editor/_unit_settings.html` | 12 | same |
| Link picker payload | `templates/courses/manage/editor/_link_picker_node.html` | 14 | `data-title=` read by JS |
| Rename result payload | `templates/courses/manage/_rename_result.html` | 7 | `<data value=>` read by JS |
| Every `title=` tooltip | various | — | plain-text attribute; see §4 |

Exclusion by *absence of an attribute the neighbours carry* is legible in review. Exclusion
by *absence from a selector list in another file* is not. That is the whole reason for the
attribute.

### 2. Shared asset partials, and a widened `has_math`

The four KaTeX `<script>` tags are copy-pasted across five templates and have already
drifted apart (defect 3). Extract two partials and switch every call site to them:

- `templates/courses/_katex_css.html` — the `katex.min.css` `<link>`.
- `templates/courses/_katex_js.html` — `katex.min.js`, `contrib/auto-render.min.js`,
  `math_reflow.js`, `text_colour.js`, `math.js`, in that order.

Script order is load-bearing and must be preserved exactly: `math_reflow.js` installs
pre-hooks on `window.renderMathInElement` and `katex.render`, and its header comment
records that it runs a single install attempt with no deferred retry precisely because it
is loaded after both vendor files in document order. `text_colour.js` post-hooks the same
two globals. `math.js` runs the initial document pass and must be last.

Adopting the partial gives `quiz_results.html` and `review_submission.html` `math.js` for
the first time. That is the intended fix for defect 3, and it is a behaviour change on
those two pages beyond titles: `renderInlineText` will begin typesetting any `.el--text`,
`.el--table` and other listed containers they render. This is the behaviour every other
KaTeX page already has, and it must be called out in the PR rather than slipped in.

Call sites to convert: `lesson_unit.html:37,71-77`, `quiz_unit.html:10,28-32`,
`quiz_results.html:7,63-66`, `manage/review_submission.html:6,135-138`,
`manage/editor/editor.html:183-186`.

The editor additionally loads `mathlive.min.js` and its bootstrap
(`manage/editor/editor.html:169-176`); that stays where it is and is not part of the shared
partial, because no other page has a MathLive authoring surface.

**The gate.** One helper, in `courses/views.py` beside the existing `_element_has_math`
family:

```python
def _titles_have_math(nodes):
    """True iff any node's title carries a maths delimiter."""
    return any(has_math_delimiters(n.title) for n in nodes)
```

and, because two pages render a whole outline tree rather than a flat list, a companion
that walks it:

```python
def _tree_titles_have_math(tree):
    """Recursive: build_outline nodes nest under 'children'."""
    return any(
        has_math_delimiters(item["node"].title)
        or _tree_titles_have_math(item.get("children") or [])
        for item in tree
    )
```

Per page, `has_math` becomes the existing value OR the title scan:

| Page | View | Scan over |
| --- | --- | --- |
| Lesson unit | `full_lesson_render_context` (`views.py:529`) | `unit_nav.tree` (whole tree), `unit_nav.ancestors`, `unit` |
| Quiz unit | `views.py:1385` | same |
| Quiz results | `views.py:1609` region | `unit` |
| Course outline | `course_outline` (`views.py:576`) | the `outline` tree |
| Course results | `course_results` (`views.py:610`) | `summary` rows' units |
| Analytics matrix | `analytics_matrix` (`views_analytics.py:74`) | the `matrix` column/cell titles |
| Analytics breakdown | `analytics_student` (`views_analytics.py:224`) | the `breakdown` tree |
| Review queue | `review_queue` (`views_review.py:110`) | `awaiting` + `in_progress` submissions' units |
| Review submission | `_review_context` (`views_review.py:95`) | `submission.unit` |
| Editor | `_editor_page` (`views_manage.py:1886`) | `unit` |

The analytics matrix is the one row whose title-bearing key is not yet pinned:
`analytics_matrix.html:115,116,126` reads `cell.title`, built by `build_results_matrix` /
`build_progress_matrix`. The plan must read those builders and name the exact structure
rather than scanning a guessed key — a wrong key here yields a scan that silently always
returns `False`, which every positive test would still pass if the page happened to carry
element maths.

Course outline, course results, analytics matrix, analytics breakdown and review queue have
no `has_math` in context today; they gain the flag, the `{% if has_math %}` guards and both
partial includes.

**The trap.** On a unit page the contents tree is `unit_nav.tree`, which
`build_unit_nav` sets to the entire course outline (`courses/rollups.py:921`), and
`_unit_tree_node.html` renders all of it into the DOM whether collapsed or not. Scanning
only `unit`, `unit_nav.prev` and `unit_nav.next` therefore leaves a maths title three
sections away rendering raw on a maths-free lesson — and it fails silently, since the page
looks correct for the unit under test. This is the same shape as the "COLLECT + MUST
RECURSE" note on `_tabs_has_math` (`courses/views.py:229`). The scan must be over the full
tree, and §5 requires a test that would fail if it were not.

**Consequence, accepted.** Because the tree is course-wide, a single maths title anywhere
in a course loads KaTeX on every unit page in that course. This is correct — those titles
really are in the DOM — but it makes the gate coarse in practice. The alternative, scanning
only the subtree actually expanded, is wrong: the collapsed nodes are present in the markup,
not fetched on demand.

**Query cost: none.** Every page already has its node list materialised in context.
`pending_reviews_for` (`courses/review.py:244`) does `.select_related("student", "unit")`
and returns a `list`, so the review queue scan touches no database. Verified, not assumed —
this was flagged as a possible N+1 during design and cleared.

### 3. CSS normalisation for compact chrome

KaTeX sets `.katex { font-size: 1.21em }` and builds vertical `.vlist` struts that can
exceed a tight `line-height`. Three surfaces are single-line and clipped, so an unclamped
formula would change row height and shift the baseline:
`.unit-foot__navtitle` (`nowrap` + `overflow:hidden` + `text-overflow:ellipsis`,
`courses/static/courses/css/courses.css:778`), `.unit-tree__grouptitle`
(`overflow:hidden`, `:702`) and `.unit-tree__label`.

Starting point, to be measured before the PR rather than accepted as written:

```css
[data-math-title] .katex { font-size: inherit; }

.unit-foot__navtitle .katex,
.unit-tree__label .katex,
.unit-tree__grouptitle .katex,
.unit-crumbs__label .katex { line-height: 1; vertical-align: baseline; }
```

`font-size: inherit` is global to titles so a formula matches its surrounding text at every
size; the `line-height`/`vertical-align` clamp applies only to the compact chrome, leaving
headings and the outline free to render at natural height.

**Accepted degradation.** A long title containing maths hard-clips instead of showing an
ellipsis. `text-overflow` applies to inline text, not to KaTeX's inline-block box, so this
cannot be fixed by CSS in the truncated surfaces. It is the reason §4 keeps the tooltip
useful rather than removing it.

### 4. Plain-text contexts strip the delimiters

`title=` attributes and `<title>` cannot contain markup, so they can never typeset. Leaving
`\(x^2\)` in a tooltip beside a rendered heading reads as a bug. A new filter in
`courses/templatetags/courses_extras.py`:

```python
@register.filter
def strip_math_delimiters(value):
    """Remove the four maths delimiter sequences for plain-text contexts."""
```

It removes the exact two-character sequences `\(`, `\)`, `\[`, `\]` and changes nothing
else — `\(x^2\)` becomes `x^2`. A title with no delimiters passes through byte-identical.
No attempt is made to render `\frac{1}{2}` as anything friendlier; the filter is a
readability improvement, not a LaTeX-to-text converter.

Applied at: the `title=` tooltips in `_unit_tree_node.html:15,25`, `_unit_crumbs.html:34`
and `manage/_tree_node.html:50`; and `{% block head_title %}` in `lesson_unit.html:3`,
`quiz_unit.html:3` and `quiz_results.html:3`.

Not applied to `manage/_move_picker.html` or the link picker `data-title=`, which are
payloads rather than display.

**Course titles are out of scope.** `_unit_crumbs.html:20`, `outline.html:3` and
`course_results.html:3` render `course.title`, a different field on a different model. This
change touches node titles only; if course titles should typeset too, that is separate
work.

## Data flow

A title is authored as plain text in a `<input name="title">` and stored unchanged on
`ContentNode.title`. Nothing sanitises or transforms it — the delimiters survive to render
time verbatim. From there it forks into three paths.

**Path A — the typeset display.** The view scans the node titles it is about to render
(`_titles_have_math` / `_tree_titles_have_math`) and ORs the result into `has_math`. The
template's `{% if has_math %}` then emits the two shared partials, so `katex.min.css` plus
the five scripts reach the page. Django autoescapes the title into the `data-math-title`
element; `\`, `(` and `)` are untouched by autoescaping, and a `<` becomes `&lt;`, which
the parser turns back into a `<` text node — so `\(a<b\)` arrives at KaTeX intact. This
matters because it is the *opposite* of the stored-HTML path, where nh3 destroys `\(a<b\)`
outright; a title is a `CharField` and never passes through nh3. On `DOMContentLoaded`,
`math.js`'s `renderInlineText` selects `[data-math-title]` and hands each element to
`window.renderMathInElement`, which `math_reflow.js` has pre-hooked. Reflow is a no-op here
(a title is a single text node with no `<div>`/`<br>` splits), so auto-render matches the
delimiters and replaces them with KaTeX markup in place.

**Path B — the plain-text contexts.** The same title string goes through
`|strip_math_delimiters` into `title=` attributes and `{% block head_title %}`. This path
never reaches KaTeX; it terminates as attribute text.

**Path C — the edit buffers.** `<input value=>`, `data-title=` and `<data value=>` receive
the title with no filter and no marker attribute, so the round-trip through the rename and
settings forms is byte-identical to what was stored. Path C must stay disjoint from A and
B: applying either would corrupt what the author saves.

## Error handling

**Unbalanced or malformed delimiters.** A title of `\(x^2` (no closer) is left as literal
text by auto-render, which only rewrites a delimiter pair it can close. A title whose
contents are not valid TeX renders via KaTeX's `throwOnError: false`, producing a
`.katex-error` span with the raw source visible. Both are the app's existing behaviour for
element prose; titles inherit it rather than introducing a new policy. No validation is
added at the authoring end — a title is never rejected for bad TeX.

**KaTeX absent.** If the gate is wrong and a page with a maths title ships no KaTeX,
`renderInlineText` returns early: it guards on `typeof window.renderMathInElement !==
"function"` (`math.js:30`), and `renderMath` guards on `typeof katex === "undefined"`
(`:13`). The failure mode is therefore the *current* behaviour — raw delimiters on screen —
not a JavaScript error. This is a silent degradation, which is exactly why §Testing
requires the negative-direction assertion and the tree-trap test rather than trusting the
scan by inspection.

**Per-element isolation.** `renderInlineText` already wraps each element's render in
`try/catch` and swallows the error, so one malformed title cannot stop the remaining titles
on the page from typesetting.

**Filter input.** `strip_math_delimiters` must tolerate a non-string (`None`, a lazy
translation proxy, an integer from a template expression) by coercing to `str` — a template
filter that raises takes down the whole page render, and `title=` sits on surfaces well
outside this feature's blast radius.

**Scan robustness.** `_tree_titles_have_math` recurses over `build_outline`'s structure. It
must tolerate a missing or `None` `children` key rather than assume the key is present; the
tree is built by several call sites with differing `drafts`/`with_data` arguments, and a
`KeyError` inside a view's context construction is a 500 on a student-facing page.

## Testing

Every test below is falsified before it is trusted: it must be observed RED against a
mutant chosen from the *failure mode*, not from the assertion. Test runs stay scoped to the
affected files; the whole-repo sweep is a branch gate, not a step. The test-database
container must be running before any pytest invocation.

**Filter (unit).** `\(x^2\)` → `x^2`; `\[a\]` → `a`; a title with no delimiters is returned
byte-identical; a title containing only a lone `\(` still has it removed.

**Gate, per page (view tests).** For each of the ten pages: with a title carrying maths and
**nothing else on the page carrying maths**, the response contains the KaTeX `<script>`;
with no maths anywhere, it does not. Both directions are required — the negative is what
catches a flag that is accidentally always true. This mirrors the existing
`test_review_views.py::test_review_loads_katex_when_stem_has_math`.

**The tree trap (view test).** A course whose maths title sits on a node several levels
away from the unit being viewed, with the viewed unit and its immediate neighbours all
maths-free, must still load KaTeX on that unit's page. This is the assertion that fails if
the scan is narrowed to `unit`/`prev`/`next`; without it the narrowing is invisible.

**Marker coverage (template test).** Assert that rendering each of the fourteen templates
emits `data-math-title` on its title element(s), and that the five excluded sites do **not**
carry it. A regex over raw source is not acceptable here — per this repo's own experience
regexes match docstrings and comments; assert over rendered output.

**End-to-end.** Drive a real lesson page in a browser where the *only* maths in the entire
course is in the **next** unit's title, and assert a `.katex` element exists inside
`.unit-foot__navtitle`. Driving the real page is required: this defect is precisely one
that a template-level assertion cannot see, because the template is correct and the asset
gate is what fails.

**Visual verification.** Screenshots in light and dark, judged separately, of: the
previous/next buttons with a maths title, the contents tree with a maths title at two
nesting depths, and the breadcrumbs. The §3 clamp values are confirmed or corrected from
these measurements before the PR opens — they are a hypothesis in this document, not a
result.

## Risks

- **Coarse gate.** One maths title loads 275 KB of JavaScript and 23 KB of CSS on every
  unit page of that course. Accepted above; noted here so it is not rediscovered as a
  surprise.
- **Behaviour change on two pages.** Giving `quiz_results.html` and
  `review_submission.html` `math.js` typesets container elements there that were previously
  left raw. Intended, but it is a visible change beyond the stated feature.
- **Clamp values unmeasured.** §3's CSS is a starting hypothesis. If measurement shows the
  struts still overflow, the fix is more CSS in the same rule, not a change of approach.
