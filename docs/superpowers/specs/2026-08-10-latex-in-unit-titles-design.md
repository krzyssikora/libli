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
   the unit's *elements* and *questions* (`courses/views.py:406`, `:1318`, and `:1588,1598-1599`;
   `courses/views_review.py:101`). A unit whose only maths is in its title ships no KaTeX,
   so fixing cause 1 alone would leave it unrendered. Eight of the pages that display unit
   titles — course outline, course results, analytics matrix, analytics breakdown, review
   queue, course notes, the unit tags panel and the tags hub — load no KaTeX under any
   condition today.

A third defect surfaced while scoping the above, and is in scope because the shared
partial introduced below fixes it as a side effect:

3. **`math.js` is missing from two pages that do load KaTeX.**
   `templates/courses/quiz_results.html:63-66` and
   `templates/courses/manage/review_submission.html:135-138` load `katex.min.js`,
   `auto-render.min.js`, `math_reflow.js` and `text_colour.js` but **not** `math.js`.
   `renderInlineText` therefore never runs on those two pages; they typeset only what
   `question.js`/`quiz.js` reach. This is pre-existing and independent of titles.

**Decisions taken during design.** Maths in titles is a first-class authoring capability,
not a one-off repair of imported content. Asset loading extends the existing server-side
`has_math` gate rather than introducing a client-side sniffer or dropping the gate. Maths
inside compact chrome is normalised by CSS so it cannot alter row height. Plain-text
contexts strip the delimiters.

**Scope boundary: server-rendered display surfaces only.** Every site in §1 is markup the
server emits on page load, so the single document pass `math.js` already performs is
sufficient. Surfaces injected into the DOM by JavaScript *after* that pass are deferred —
see §5, which states exactly which they are and what they would additionally require. This
boundary is the reason the change needs no new client-side re-render plumbing.

**How the enumeration was produced.** The site list below is a sweep of **every** app
template directory (`templates/`, `notes/templates/`, `tags/templates/`,
`notifications/templates/`; `tests/templates/` holds fixtures, not user-facing surfaces,
and is excluded), not only `templates/courses/` — three student-facing node-title
displays live in `notes/` and `tags/` and would otherwise have been missed. Any template
directory added later must be swept before this list can be called complete.

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
surrounding markup. Instead every **read-only, server-rendered display** of a node title
gains a `data-math-title` attribute, and `renderInlineText` gains exactly one new entry:
`[data-math-title]`.

**Student and results surfaces:**

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
| Course notes headings | `notes/templates/notes/course_notes.html` | 16 |
| Unit tags panel heading | `tags/templates/tags/panel_page.html` | 5 |
| Tags hub unit list | `tags/templates/tags/_tag_section.html` | 25 |

**Teacher / management surfaces:**

| Surface | File | Lines |
| --- | --- | --- |
| Analytics matrix (leaf + group headers) | `templates/courses/manage/analytics_matrix.html` | 115, 116, 126 |
| Analytics breakdown | `templates/courses/manage/_breakdown_node.html` | 6, 24, 30 |
| Review queue | `templates/courses/manage/review_queue.html` | 15, 30 |
| Review submission heading | `templates/courses/manage/review_submission.html` | 58 |

**Editor surfaces** (the editor page is server-rendered and already loads KaTeX
unconditionally — see §2):

| Surface | File | Lines |
| --- | --- | --- |
| Editor heading | `templates/courses/manage/editor/editor.html` | 80 |
| Editor crumb (ancestor titles) | `templates/courses/manage/editor/editor.html` | 75 |
| Editor preview heading | `templates/courses/manage/editor/_preview.html` | 6 |

**Reading the "Lines" column.** It points at the **title interpolation**, and the attribute
goes on that title's nearest enclosing element — which for a multi-line opening tag is an
earlier line. In `analytics_matrix.html` the leaf `<a class="analytics__expand">` opens at
`:114`, the leaf `<span>` opens at the end of `:115`, and `<span class="analytics__group-title">`
opens at `:125`, even though the cited interpolations are at `:115,116,126`.

**The title-alone rule.** Where a template interpolates other content into the same
element, the marker goes on a `<span>` wrapping the title **alone**, never on the shared
parent — otherwise a student's display name or a translated word gets typeset too. This
applies to:

- `review_queue.html:15,30` — student name + title in one `<span>`.
- `review_submission.html:58` — `{% trans "Review" %}: <student> — {{ submission.unit.title }}`.
- `quiz_results.html:12` — `{{ unit.title }} — {% trans "results" %}`.
- `editor.html:75` — the loop emits a separator and each ancestor title; the marker wraps
  `{{ a.title }}` only, not `.editor-crumb__path`, which also holds `course.title`
  (out of scope per §4).
- `tags/panel_page.html:5` — `<h1>{{ unit.title }} — {% trans "Tags" %}</h1>`, structurally
  identical to `quiz_results.html:12`.

**The rule's limit.** It bites only when the sibling content **could itself contain
delimiters** — translated prose, a student name, another node's title. A static glyph does
not qualify: `analytics_matrix.html:114-115` renders `{{ cell.title }} ▸` inside the leaf
`<a>`, and the marker goes on that `<a>` with the `▸` inside its scope. Auto-render scans
the glyph, finds no delimiters, and leaves it alone. Stated because the two rules otherwise
give contradictory answers there.

`notes/course_notes.html:16` and `tags/_tag_section.html:25` were checked in the same pass
and hold the title **alone**, so the marker goes on the existing element there. They are
named here so the reader knows they were considered rather than skipped.

**Deliberately excluded — the raw text is load-bearing, not displayed:**

| Excluded site | File | Line | Why |
| --- | --- | --- | --- |
| Editor settings title input | `templates/courses/manage/editor/_unit_settings.html` | 12 | `<input value=>` — the edit buffer; typesetting would corrupt what is saved |
| Rename result payload | `templates/courses/manage/_rename_result.html` | 7 | `<data value=>` read by JS |
| Every `title=` tooltip | various | — | plain-text attribute; see §4 |

Exclusion by *absence of an attribute the neighbours carry* is legible in review. Exclusion
by *absence from a selector list in another file* is not. That is the whole reason for the
attribute.

### 2. Shared asset partials, and a widened `has_math`

**Current state of the duplicated block, precisely.** Three templates (`lesson_unit.html`,
`quiz_unit.html`, `manage/editor/editor.html`) carry **five** script tags — `katex.min.js`,
`auto-render.min.js`, `math_reflow.js`, `text_colour.js`, `math.js`. Two
(`quiz_results.html`, `manage/review_submission.html`) carry the **first four plus
`question.js`**, and are missing `math.js` (defect 3). Extract two partials and switch every
call site to them:

- `templates/courses/_katex_css.html` — the `katex.min.css` `<link>`.
- `templates/courses/_katex_js.html` — `katex.min.js`, `contrib/auto-render.min.js`,
  `math_reflow.js`, `text_colour.js`, `math.js`, in that order.

Both partials open with their own `{% load static %}` — template libraries are not
inherited from the including template, so omitting it is a `TemplateSyntaxError`. Because
the partials self-load, an *including* template does **not** need `{% load static %}` for
their sake.

**Every tag in `_katex_js.html` carries `defer`, and so does the retained `question.js`.**
All five tags at all five current call sites already do. This is a hard requirement, not a
style detail, and the spec states it because "preserve the order" alone does not imply it:
`editor.html:191-193` carries a comment recording that **source order only guarantees
execution order among `defer` scripts**, so a single non-deferred tag in the partial
silently reorders execution and makes §2's "`question.js` after the include" meaningless.
Worse, a non-deferred `math.js` runs *during* parsing, so `renderMath(document)` and
`renderInlineText(document)` see a partial DOM and typeset nothing below their own tag —
a failure that looks exactly like a missing marker.

Script order is load-bearing and must be preserved exactly: `math_reflow.js` installs
pre-hooks on `window.renderMathInElement` and `katex.render`, and its header comment
records that it runs a single install attempt with no deferred retry precisely because it
is loaded after both vendor files in document order. `text_colour.js` post-hooks the same
two globals. `math.js` runs the initial document pass and must be last within the partial.

**`question.js` is retained and stays outside the partial.** On `quiz_results.html:67` and
`review_submission.html:139` a `question.js` tag sits immediately after `text_colour.js`,
*inside* the same `{% if has_math %}`. It is not part of `_katex_js.html`. It must be
emitted **after** the include on both pages (matching the lesson page's math-then-question
order), and neither page's `{% if has_math %}` boundary moves.
`review_submission.html:130-134` carries an explicit comment recording that dropping
`question.js` regresses maths rendering and breaks
`test_review_views.py::test_review_loads_katex_when_stem_has_math`.

**The `{% if has_math %}` guard lives at each call site, never inside the partials.** The
partials emit tags unconditionally; every caller decides whether to include them. This is
what allows the next paragraph.

**The editor is unconditional and stays that way.** `manage/editor/editor.html:20` (CSS) and
`:182-186` (JS) have **no** `{% if has_math %}` wrapper — the editor ships KaTeX on every
unit because MathLive and the live preview need it regardless of the unit's content. Both
editor includes remain **unguarded**, no `has_math` is computed for the editor page, and the
editor does not appear in the gate table below.

**Call sites to convert.** Cited as the script-tag lines only; every existing
`{% if has_math %}` guard line stays exactly where it is:

| Template | CSS line | JS tag lines |
| --- | --- | --- |
| `lesson_unit.html` | 37 | 72-76 |
| `quiz_unit.html` | 10 | 28-32 |
| `quiz_results.html` | 7 | 63-66 (plus `math.js`, newly added by the partial) |
| `manage/review_submission.html` | 6 | 135-138 (plus `math.js`) |
| `manage/editor/editor.html` | 20 | 182-186 |

The editor's JS range begins at `182`, not `183`; replacing only `183-186` would strand a
`katex.min.js` tag above the include. The editor additionally loads `mathlive.min.js` and
its inline bootstrap (`manage/editor/editor.html:169-181`, `math_input.js` at `:181`); that
stays where it is and is not part of the shared partial, because no other page has a
MathLive authoring surface.

**The helpers.** Two public functions, placed so that every consumer imports *downward*.
Putting them in `courses/views.py` would force `views_analytics.py` and `views_review.py` —
neither of which imports `courses.views` today — to import a very large view module, and to
import a private name across module boundaries.

- `titles_have_math(titles)` in **`courses/htmlsandbox.py`**, beside `has_math_delimiters`.
  Takes an **iterable of strings** and returns `True` iff any carries a delimiter. A string
  iterable, not a node iterable, because the call sites hold four different shapes; each
  does its own extraction. It **must** be exactly
  `any(has_math_delimiters(t) for t in titles)` — delegating, never re-implementing the
  `"\\(" in t or "\\[" in t` test. An independent copy satisfies this spec today, forks the
  delimiter definition the moment `has_math_delimiters` changes, and no test here would go
  red. Delegating also inherits its `html or ""` guard for a `None` title for free.
- `tree_titles_have_math(tree)` in **`courses/rollups.py`**, which already owns the
  `build_outline` node-dict shape. Recurses over `item["node"].title` and
  `item["children"]`, and **must delegate its leaf test** to `titles_have_math` (or
  `has_math_delimiters`) rather than inlining a `"\(" in title` check. The fork argument
  above applies verbatim, and with more force: this is the helper written by hand against a
  tree walk, so it is the likeliest place for an inlined copy to appear — and nothing in
  §Testing would go red if it did.

Per page, `has_math` becomes the existing value OR the title scan.

Every function is cited by its `def` line. Expressions are written to be **paste-able at the
stated insertion point**, using the locals that actually exist there — five earlier drafts of
this table referred to names the views never bind.

**On the eight pages that have no `has_math` today, the context key must be spelled exactly
`has_math`** — that is the name §2's `{% if has_math %}` guard reads — and it goes into the
view's `render()` context dict. Every row below is a complete statement, not a bare boolean.

| Page | Function (`def` line) | Insertion point and complete statement |
| --- | --- | --- |
| Lesson unit | `full_lesson_render_context` (`views.py:529`) | after `ctx["unit_nav"] = …` (`:556`): `ctx["has_math"] = ctx["has_math"] or tree_titles_have_math(ctx["unit_nav"]["tree"]) or titles_have_math([node.title])` |
| Quiz unit | `quiz_unit` (`views.py:1365`) | after `ctx["unit_nav"] = …` (`:1385`): the same statement verbatim |
| Quiz unit (no-JS feedback) | `_quiz_render_feedback` (`views.py:1402`) | after `ctx["unit_nav"] = …` (`:1418`): the same statement again — see the note below |
| Quiz results | `quiz_results` (`views.py:1572`) | after the loop's last line (`:1601`), before `ctx = {` (`:1602`), at function-body indentation: `has_math = has_math or titles_have_math([node.title])` |
| Course outline | `course_outline` (`views.py:576`) | before `return render(...)`: `has_math = tree_titles_have_math(outline)`, then add `"has_math": has_math` to the context dict |
| Course results | `course_results` (`views.py:610`) | before `return render(...)`: `has_math = titles_have_math(r["unit"].title for r in summary["rows"])`, then add `"has_math": has_math` |
| Analytics matrix | `analytics_matrix` (`views_analytics.py:74`) | before `return render(...)`: `has_math = titles_have_math(c["title"] for row in matrix["header_rows"] for c in row)`, then add `"has_math": has_math` |
| Analytics breakdown | `analytics_student` (`views_analytics.py:224`) | before `return render(...)`: `has_math = tree_titles_have_math(breakdown["tree"])`, then add `"has_math": has_math` |
| Review queue | `review_queue` (`views_review.py:110`) | before `return render(...)`: `has_math = titles_have_math(s.unit.title for s in data["awaiting"] + data["in_progress"])`, then add `"has_math": has_math` |
| Review submission | `_review_context` (`views_review.py:93`) | the returned dict already carries `has_math`; OR into it: `... or titles_have_math([submission.unit.title])` |
| Course notes | `course_notes` (`notes/views.py:54`) | **bind a local first** — the view passes `services.course_notes(...)` inline into the dict, so `units` does not exist. `units = services.course_notes(request.user, course, drafts=drafts)`, then `has_math = titles_have_math(r["unit"].title for r in units)`, then pass both into the context |
| Unit tags panel | `_add_error` (`tags/views.py:61`, no-JS 422 path) | after `ctx.update(...)`, before `return render(...)` at `:69`: `ctx["has_math"] = titles_have_math([unit.title])` |
| Tags hub | `my_tags` (`tags/views.py:85`) **and** `tag_recolor` (`tags/views.py:120`) | **bind a local first at both sites** — `tags_by_tag` is passed inline into the dict at each. In `my_tags`, before `return render(` at `:86`; in `tag_recolor`, inside the `except ValidationError:` block before `return render(` at `:125`. Both: `tags_by_tag = services.units_by_tag(request.user)`, then `has_math = titles_have_math(u.title for _tag, grouped in tags_by_tag for units in grouped.values() for u in units)`, then pass both into the context |

**Both service functions return real lists, so the double iteration above is safe.**
`notes/services.py:98` builds and returns a `list` of `{"unit": ContentNode, "groups": …}`;
`tags/services.py:209` returns `[(Tag, {Course: [unit]})]`; and `build_course_results`
(`rollups.py:329`) builds `"rows"` with `rows.append` at `:422`, so `summary["rows"]` is a
list too. Scanning the local and then
passing it to the template iterates each twice. Were either a generator, the scan would
exhaust it and the page would render empty — a silent, severe failure that no test here
would catch, which is why the return types are pinned rather than assumed.

**`node`, not `unit`.** `full_lesson_render_context(node, …)`, `build_quiz_context(node, user)`
(`views.py:1218`) and the quiz-results view all bind the node as **`node`**; `unit` exists only
as a *context key*, never as a local. Likewise `has_math` and `unit_nav` on the two quiz paths
are reachable only as `ctx["has_math"]` / `ctx["unit_nav"]`, and `ctx["unit_nav"]` is assigned
on the very line cited — so the OR must come *after* that assignment, not before.

The editor is absent by design (see above).

**`tags_by_tag`'s shape, stated so it is not re-derived from the template.**
`services.units_by_tag` (`tags/services.py:209`) returns `[(Tag, {Course: [unit, ...]})]`.
The `{% for course, units in grouped.items %}` in `_tag_section.html:21` is the **inner**
loop, over one tag's `grouped` dict — translating it directly against `tags_by_tag` yields
`for course, units in tags_by_tag`, which unpacks `(tag, grouped)` into `(course, units)`
and then iterates a dict's keys, silently scanning `Course` objects instead of units. Use
the literal generator in the table above.

**The tags hub renders twice.** `tags/my_tags.html` is rendered by `my_tags` (`:88`) **and**
inside `tag_recolor`'s `ValidationError` branch (`:127`), which rebuilds the context inline.
Unlike the lesson and review pages — which both funnel through a shared helper
(`full_lesson_render_context`, `_review_context`) — there is no shared seam here, so the OR
must be applied at both sites or the hub context factored into one helper. Otherwise a
recolor validation error re-renders the hub with no `has_math` and shows raw delimiters.

**The quiz page renders twice.** `_quiz_render_feedback` (the no-JS answer path) calls
`build_quiz_context`, sets its own `ctx["unit_nav"]` at `views.py:1418` and re-renders
`quiz_unit.html` at `:1431`. Applying the OR only at `:1385` would leave that render on the
un-widened flag. It is masked today because `has_math = bool(questions) or …` and this path
is reachable only when the quiz has questions — but the code comment calls that
over-inclusiveness an "accepted tradeoff", i.e. something that could be tightened later, at
which point the omission would become live. Apply the OR at `:1418` as well.

**Two scan expressions that must be written against the real shape.** Both were wrong in an
earlier draft in ways that fail loudly or silently:

- `build_student_breakdown` (`rollups.py:452`) returns `{"student": student, "tree": tree}`
  — a **dict wrapper**, not a tree; `analytics_student.html:12` iterates `breakdown.tree`.
  Passing `breakdown` itself would iterate the dict's keys and raise
  `TypeError: string indices must be integers` — a 500 on the breakdown page.
- `review_queue` (`views_review.py:110`) binds only `data`; it unpacks
  `data["awaiting"]` / `data["in_progress"]` inline in the `render()` call (`:118-126`).
  There are no `awaiting` / `in_progress` locals, so referring to them is a `NameError`.

**Analytics matrix: scan `header_rows`, never `columns`.** The titles at
`analytics_matrix.html:115,116` (leaf) and `:126` (group) come from `matrix["header_rows"]`
— a list of lists of cell dicts, each with a `"title"` string, built in `frontier_columns`
(`courses/rollups.py:569,584,596`, assembled at `:615`), **not** in `build_results_matrix` /
`build_progress_matrix`. `matrix["columns"]` is `_public_columns(...)` (`:667`) and holds
**leaf columns only**, so a scan over it silently misses every expanded group cell — which
is exactly what line 126 renders. §Testing requires a fixture with the maths title on an
**expanded group** node, not only on a leaf.

**Why the lesson/quiz row scans two things — REDUNDANT TODAY, KEPT DELIBERATELY.**
`unit_nav["tree"]` is `build_outline(...)` and already contains the ancestors, the previous
and next units, **and** the current unit, so the `[node.title]` scan is provably redundant at
every present call site. It cannot be otherwise reached: `access.py:135-141` raises `Http404`
for an unpublished unit whose viewer cannot see drafts, and both `lesson_unit` (`views.py:717`)
and `quiz_unit` (`:1366`) resolve through `get_node_or_404(..., viewer=request.user, ...)`.
Since `drafts == "hide"` is exactly `not can_see_drafts`, the on-screen unit is always
`published`, so `unit_is_visible` (`rollups.py:77`) is `True` and it is never pruned.

Keep the second scan anyway, on the same footing as the `is_author` flag documented at
`views.py:544-553`: it is defence-in-depth for a future render site that reaches these
templates **without** the view-level `viewer=` gate, which would otherwise silently lose the
current unit's own title. Do not delete it as dead code without re-verifying that every
caller still carries that gate. There is deliberately **no test** for this branch — see
§Testing.

**Templates that need new blocks.** The gate table has thirteen rows across twelve distinct
templates (`quiz_unit.html` appears twice, one row per render site; the Tags-hub row covers two
render sites in a single row, so thirteen rows span fourteen render sites). Four templates
(`lesson_unit`, `quiz_unit`, `quiz_results`, `review_submission`) already have the guards
and need only the include swap, and the editor is excluded — leaving **eight** templates
that gain the flag, the `{% if has_math %}` guards and both partial includes. Seven of the
eight need at least one new block; only `notes/course_notes.html` has both today
(`base.html:49` and `:161` are the anchors):

| Template | What exists | What must be added |
| --- | --- | --- |
| `outline.html` | `extra_css` with `{{ block.super }}` | `extra_js` block |
| `course_results.html` | `extra_css` without `{{ block.super }}` | `extra_js` block |
| `manage/analytics_matrix.html` | `extra_js` only | `extra_css` block |
| `manage/analytics_student.html` | neither block | both blocks |
| `manage/review_queue.html` | neither block | both blocks |
| `notes/course_notes.html` | both blocks exist | includes only |
| `tags/my_tags.html` | `extra_css` only | `extra_js` block |
| `tags/panel_page.html` | neither block | both blocks |

None of these rows needs `{% load static %}` added: the partials self-load it, and a
template that only `{% include %}`s them never evaluates `{% static %}` itself.

Leave the `{{ block.super }}` asymmetry between `outline.html` and `course_results.html`
alone. It is pre-existing and **inert**: `base.html:49` is `{% block extra_css %}{% endblock %}`
— an empty block — and base's own stylesheets (`reset.css`, `tokens.css`, `app.css`) are at
`:44-46`, *outside* it. So `{{ block.super }}` expands to the empty string in both cases.
Preserve each file as-is purely to keep the diff minimal.

**The trap.** On a unit page the contents tree is `unit_nav["tree"]`, which
`build_unit_nav` sets to the entire course outline (`courses/rollups.py:921`), and
`_unit_tree_node.html` renders all of it into the DOM whether collapsed or not. Scanning
only `unit`, `unit_nav.prev` and `unit_nav.next` therefore leaves a maths title three
sections away rendering raw on a maths-free lesson — and it fails silently, since the page
looks correct for the unit under test. This is the same shape as the "COLLECT + MUST
RECURSE" note on `_tabs_has_math` (`courses/views.py:229`). The scan must be over the full
tree, and §Testing requires a test that would fail if it were not.

**Consequence, accepted.** Because the tree is course-wide, a single maths title anywhere
in a course loads KaTeX on every unit page in that course. This is correct — those titles
really are in the DOM — but it makes the gate coarse in practice. The alternative, scanning
only the subtree actually expanded, is wrong: the collapsed nodes are present in the markup,
not fetched on demand.

**Query cost: none.** Every page already has its node list materialised in context.
`pending_reviews_for` (`courses/review.py:236`) materialises its submissions with
`list(... .select_related("student", "unit"))` at `:242-246` and returns two plain lists
inside a dict (`:256`), so the review-queue scan touches no database and
`data["awaiting"] + data["in_progress"]` is a valid list concatenation.

### 3. CSS normalisation

KaTeX sets `.katex { font-size: 1.21em }` and builds vertical `.vlist` struts that can
exceed a tight `line-height`. Worse, `math.js`'s `INLINE_DELIMS` maps `\[` to
`display: true` (`math.js:23`), and the vendored stylesheet has
`.katex-display{display:block;margin:1em 0;text-align:center}` — so a **display-math title**
becomes a centred block with 1em vertical margins inside a nav button, a breadcrumb `<li>`
or a tree row. Since §Purpose commits to supporting `\[...\]` in titles, neutralising
`.katex-display` in compact chrome is required, not optional.

**Which stylesheet.** This matters: of the twelve distinct templates in §2's gate table, only five link `courses.css`. The other seven — `outline.html`, `analytics_matrix.html`,
`analytics_student.html`, `review_queue.html`, `notes/course_notes.html`,
`tags/my_tags.html` and `tags/panel_page.html` — extend `base.html` and link no
`courses.css` at all — their rules live in `app.css`, `notes.css` and `tags.css` (the
outline's own are `app.css:519` and `:495`). Putting the global
normalisation in `courses.css` would leave every one of those seven, all of which newly gain
KaTeX rendering under this change, at an unnormalised 1.21em.

**The overriding invariant.** `app.css` is at `base.html:46`; every `katex.min.css` link
lands in `{% block extra_css %}` at `:49` or later. **The vendor stylesheet therefore always
loads after ours on every page in this change.** At equal specificity KaTeX wins, so every
rule below must be *strictly more specific* than the vendor rule it overrides. This is the
check to re-apply whenever the measured clamp values are corrected — it is not a property
that survives casual editing.

- **`core/static/core/css/app.css`** (linked by `base.html:46` on every page) — the global
  rules. All live here only; a `courses.css` copy could never match anything these do not
  already match, and would drift:

  ```css
  [data-math-title] .katex {                                       /* (0,2,0) > (0,1,0) */
    font-size: inherit; font-weight: inherit; font-style: inherit;
  }
  [data-math-title] .katex-display {                               /* (0,2,0) > (0,1,0) */
    display: inline-block; margin: 0; text-align: inherit;
  }
  [data-math-title] .katex-display > .katex {                      /* (0,3,0) > (0,2,0) */
    display: inline-block; text-align: inherit;
  }
  ```

  **`white-space` is deliberately absent from the child override**, not merely omitted from
  the excerpt above. An earlier draft of this block listed `white-space: inherit` here, which
  directly contradicts this section's own prose two paragraphs below: the vendor's
  `white-space: nowrap` is "which we in fact want to keep for a formula". Task 10 followed the
  prose, not the code block, when it implemented this rule — `inherit` would hand a
  `white-space: normal` `<h1>` the exact mid-formula wrapping the vendor rule exists to
  prevent. This code block was corrected to match the shipped CSS and the prose during Task
  11's measurement pass; `tests/test_title_math_css.py::
  test_the_display_child_override_does_not_touch_white_space` pins it.

  **`font-weight` and `font-style` must be restored too, not just `font-size`.** The
  vendored rule is `.katex{font:normal 1.21em KaTeX_Main,…;line-height:1.2;…}` — a `font`
  **shorthand**, which resets every unset font longhand, `font-weight` among them. Restoring
  only `font-size` leaves a maths run rendering at `normal` weight inside a bold
  `lesson-unit__title`, `result__title` or `editor-head__title`, visibly lighter than the
  prose beside it. `line-height` is deliberately *not* inherited here; the compact-chrome
  clamps below own that.

  **Both rules must set `display`, and neither alone is sufficient.** The vendored
  stylesheet carries six `.katex-display` rules. Two matter here:
  `.katex-display{display:block;margin:1em 0;text-align:center}` **and**
  `.katex-display>.katex{display:block;text-align:center;white-space:nowrap}`.

  - The **wrapper** rule is the load-bearing one, and the child rule is **defensive**. Once
    the wrapper is `inline-block` it establishes its own formatting context, so a
    `display:block` `.katex` inside it does *not* break the surrounding line box. What the
    child rule still neutralises is `text-align:center` (a no-op inside a shrink-to-fit box)
    and `white-space:nowrap` (which we in fact want to keep for a formula). It is specified
    because it costs nothing, guards against a future vendor change, and the §Testing
    measurement is what actually decides — not because omitting it would break the line box.
    Note it is (0,2,0), identical to `[data-math-title] .katex`, so overriding it needs the
    child combinator to reach (0,3,0).
  - Neutralising only the **child** *is* wrong, and this is the half that matters: a
    `display:block` wrapper is still a block-level box. Inside `<h1>Rozwiąż \[x^2\] teraz</h1>`
    it splits the inline content into anonymous block boxes and renders on three lines; inside
    the inline `.unit-foot__navtitle` or `.unit-tree__label` it breaks the inline box and grows
    the row. `margin: 0` removes the 1em gaps but **not** the line break — an inline-block child
    cannot make a block parent join the surrounding line box.

  The **four** remaining vendor rules need no action.
  `.katex-display>.katex>.katex-html{display:block;position:relative}` is benign: a
  block-level child inside an inline-block `.katex` establishes that box's own formatting
  context and does not affect the outer line. The other three are unreachable — this app
  sets neither `fleqn` nor `leqno` and uses no `\tag`:
  `.katex-display>.katex>.katex-html>.tag{position:absolute;right:0}`,
  `.katex-display.leqno>.katex>.katex-html>.tag{left:0;right:auto}` and
  `.katex-display.fleqn>.katex{padding-left:2em;text-align:left}`. Should `fleqn` become
  reachable, note that its rule is (0,3,0) — the same specificity as the child override
  above — and its `text-align:left` would then collide with that override's
  `text-align:inherit`, with source order deciding.

- **`core/static/core/css/app.css`** — the analytics clamp, since those pages have no
  `courses.css`:

  ```css
  .analytics__matrix thead th .katex,
  .breakdown-unit__title .katex,
  .breakdown-node__title .katex { line-height: 1; vertical-align: baseline; }
  ```

- **`courses/static/courses/css/courses.css`** — the unit-chrome clamp:

  ```css
  .unit-foot__navtitle .katex,
  .unit-tree__label .katex,
  .unit-tree__grouptitle .katex,
  .unit-crumbs__label .katex { line-height: 1; vertical-align: baseline; }
  ```

- **`.outline-unit__title`: measured, and no rule was added.** A maths-titled outline row
  (`_outline_node.html:7`) measured 32.1px against a maths-free row's 24.0px for a title
  carrying a fraction, and 39.6px for a `\[...\]` display integral — real growth, but **not**
  caused by `line-height`, and a `line-height`/`vertical-align` clamp does not remove it. An
  A/B against a same-specificity override that restores the vendor's `line-height: 1.2`
  reproduces the identical 32.1px / 39.6px: the growth survives the clamp unchanged. This is
  provable from the numbers already in this section — `core/static/core/css/reset.css:6` sets
  `body { line-height: 1.5 }`, a 24px line box at 16px, which already *exceeds* the vendor's
  `1.2 × 16px = 19.2px`, so line-height was never the taller value on this surface to begin
  with. The growth is the fraction's own strut height (`.katex .base`'s vertical extent),
  which `line-height` cannot touch; `vertical-align: baseline` would also be inert here, since
  the vendored stylesheet sets `vertical-align` on no `.katex`/`.katex-display` selector and
  `baseline` is the initial value regardless. A plain inline title (even
  `\(\sum_{i=1}^{n} a_i b_i\)` with limits) measures 24.0px either way — identical to a
  maths-free row, clamp or no clamp.

  **Accepted, for the same reason the five-line clamp and the `.katex-display`
  neutralisation both keep a formula intact rather than deforming it:** a title containing a
  fraction or a display-mode formula legitimately occupies more vertical space than one line
  of prose, and no CSS property in this rule family can or should compress that without
  clipping the glyph. `.result-row__title` (49.2px vs 49.0px) and `.card-list__row` (57.0px
  vs 57.0px) were measured alongside it and came back within the same ~0.2px of noise a
  `line-height: 1` clamp would itself produce on a short inline title — the same standard
  applied consistently across all three surfaces, so none of the three gets a rule.

**The compact surfaces behave differently and must not be conflated.**

- **Three single-line clips (desktop)** — `.unit-foot__navtitle` (`courses.css:778`),
  `.unit-tree__label` (`:755`) and `.unit-crumbs__label` (`:848`) — are all
  `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`. A long maths title
  hard-clips rather than showing an ellipsis: `text-overflow` applies to inline text, not to
  KaTeX's inline-block box. Accepted; it is why §4 keeps the tooltips useful. Note this hits
  the contents-tree unit rows and the breadcrumb leaf, not just the nav buttons — the two
  most frequently seen surfaces of the three.
- **The mobile drawer is a fourth, different case.** `_unit_shell.html:40` renders a
  **second full copy** of the tree into the drawer, and `courses.css:943` overrides the
  label there: `.unit-drawer__list .unit-tree__label { white-space: normal; overflow:
  visible; text-overflow: clip; }`. So at ≤640px titles **wrap** rather than clip. The
  adjacent comment records that the title column is squeezed to roughly 98px, which raises
  the risk that a word wider than that column overflows and paints *under* the action
  buttons — which is exactly what an unbreakable KaTeX inline-block box could be. **Task 11
  measured this at 390×780, both themes, with the longest title in the fixture:** the wrap
  absorbs it and no `.katex` box intersected a sibling control's rect
  (`.unit-tree__count` / `.unit-tree__groupcheck` / `.unit-tree__check` /
  `.unit-tree__chevron` / `.unit-drawer__close`). CONFIRMED clean — no rule needed. The risk
  is real in principle (an unbreakable inline-block in a ~98px column) and should be
  re-checked if that column ever narrows further; it did not materialise on this measurement.
- **One five-line clamp** — `.unit-tree__grouptitle` (`courses.css:702-704`) is **not** a
  single-line clip. It is `display:-webkit-box; -webkit-line-clamp:5;
  -webkit-box-orient:vertical` with `overflow-wrap:break-word; hyphens:auto`. `-webkit-box`
  line counting and its ellipsis both behave differently with an inline-block `.katex`
  child. Intended behaviour: the surrounding prose keeps wrapping and clamping as today, and
  the formula stays intact on whichever line it lands on rather than being broken
  internally. A **measured** case, not an assumed one.
- **One fixed-height sticky header** — the analytics matrix, the most fragile of the six.
  `app.css:675` sets `.analytics{--ahead-h:2.4rem}`; `app.css:754-755` sets
  `.analytics__matrix thead th{position:sticky; height:var(--ahead-h); white-space:nowrap; …}`
  (there is no `.analytics__colhead{height:…}` rule), with an earlier
  `.analytics__matrix thead th{vertical-align:top}` at `:739` governing how an over-tall cell
  paints; and `analytics_matrix.html:112` positions each sticky header row at
  `top:calc(var(--ahead-h) * counter0)`. Two distinct failures follow: a title taller than
  `2.4rem` desynchronises every sticky header row beneath it — a layout break, not a cosmetic
  one — and because the cell is `nowrap`, a long maths title **widens the column** instead of
  wrapping.

**The remaining marked surfaces take the global rules only.** This list is exhaustive
against §1 and was MEASURED by Task 11: `_outline_node.html:7,21` (both the unit-row branch —
`.outline-unit__title` — and the group heading branch — `.outline-node__title`, a
`flex-wrap` heading row at 1.1–1.35rem, the same shape as the `.lesson-unit__title` `<h1>`
row 8 already confirms clean), `course_results.html:21`, `course_notes.html:16`,
`_tag_section.html:25`, `panel_page.html:5`, `review_queue.html:15,30`, `editor.html:75` and
`_preview.html:6` are neither compact chrome nor fixed-height headings: they wrap freely, so
no clamp is specified for them. Note this is a *claim to be checked*, not a free pass —
KaTeX's vertical extent survives the global rules, and `.result-row`, `.outline-unit` and
`.card-list__row` are flex rows that can still gain height from it. §Testing screenshots the
course-results, outline and review-queue rows so "needs no clamp" is a measurement rather
than an assumption. `.result-row__title` and `.card-list__row` measured within ~0.2px of
their maths-free rows. `.outline-unit__title` measured real growth for a fraction or display
title (see above) — but an A/B proved a `line-height`/`vertical-align` rule does not remove
that growth, so it stays in this list too: the growth is an accepted consequence of the
glyph's own height, not a gap this section's clamp pattern can close.

**Display math is forced inline everywhere, including the `<h1>`s.** The neutralisation is
keyed on bare `[data-math-title]`, so it also reshapes `_lesson_article.html:7`,
`_quiz_article.html:5`, `quiz_results.html:12`, `review_submission.html:58`,
`editor.html:80` and `tags/panel_page.html:5`, where nothing is clipped and a centred block would technically fit. That
is deliberate: a title is a single line of prose by definition, and an author who writes
`\[…\]` in one is reaching for emphasis, not for a standalone equation block. A centred,
1em-margined block inside an `<h1>` that also contains words would look like a rendering
bug. One rule, one behaviour, everywhere.

**The print override.** `courses.css:903-907` re-opens `.unit-crumbs__label` under
`@media print` to `overflow:visible; white-space:normal; overflow-wrap:anywhere`, and that
block's own comment records it exists because a screen-only rule once silently lost printed
text. `overflow-wrap: anywhere` cannot break a KaTeX inline-block, so a long maths crumb can
still overflow in print. Accepted for now — printing a breadcrumb is a marginal case and the
text is not *lost*, only over-wide — but stated so it is not rediscovered as a defect.

**Measured, 2026-08-10 (Task 11) — stated precisely, not oversold.** All fourteen
§Testing surfaces were rendered in a real Chromium browser, in both themes, WITH the CSS
above already in place, and judged by screenshot; two surfaces (row 6's analytics header and
row 9/10's flex rows) additionally got a numeric height/measurement pass. This is real
evidence that nothing regressed *with the rules present* — it is not, on its own, an A/B
proof that every rule is load-bearing. Row 6's `38.4px = --ahead-h: 38.4px` reading is weaker
in isolation than it looks: `.analytics__matrix thead th` carries `height: var(--ahead-h)`
directly, so the cell reads exactly `--ahead-h` whenever its content does not force it
taller — the measurement confirms nothing is currently forcing it taller, not that the
`.katex` clamp is what prevents it.

`.outline-unit__title` got the deeper A/B treatment after a first-pass claim about it proved
false (see above): the measured 32.1px/39.6px growth for fraction- and display-titled rows is
real, but reproduces identically with or without a `line-height`/`vertical-align` rule, so no
rule was added there — it is recorded as an accepted consequence of the glyph's own height,
the same category as the five-line clamp and the `.katex-display` neutralisation. **No CSS
value in this section changed as a result of Task 11's measurement pass**; the pass found one
false claim (corrected above) and otherwise found the shipped values doing what §3 already
documented. See `tests/capture_title_math_screenshots.py` for the fixture and
`.superpowers/shots/title-math-*-{light,dark}.png` for the screenshots this is based on.

### 4. Plain-text contexts strip the delimiters

`title=` attributes, `<title>`, and screen-reader-only text cannot contain markup, so they
can never typeset. Leaving `\(x^2\)` in a tooltip beside a rendered heading reads as a bug.
A new filter in `courses/templatetags/courses_extras.py`:

```python
@register.filter
def strip_math_delimiters(value):
    """Remove the four maths delimiter sequences for plain-text contexts."""
```

**Behaviour, pinned.** Coerce to `str` first (see §Error handling), then remove the exact
two-character sequences `\(`, `\)`, `\[`, `\]` by naive left-to-right replacement,
**regardless of pairing** — `\(x` yields `x`, and a stray `\)` is removed too. A literal
escaped backslash (`\\(`) is explicitly out of scope: it is treated as `\` followed by `\(`
and the trailing pair is removed. A title with no delimiters passes through with identical
*content*. No attempt is made to render `\frac{1}{2}` as anything friendlier; the filter is
a readability improvement, not a LaTeX-to-text converter.

**Every path must return a new plain `str`, never a `SafeString`** — including the
no-delimiter path. The tempting optimisation (return the input untouched when it holds no
delimiter) would satisfy "identical content" while passing a `SafeString` straight through,
and `SafeString.__str__` returns `self`, so even the `str()` coercion does not strip the
safe marker. `ContentNode.title` is a `CharField`, so this cannot bite today; it is pinned
because the filter sits on `title=` attributes, where silently losing autoescaping is an
injection seam, and because a future caller may pass marked-safe text.

**Applied at:**

| Site | File | Line |
| --- | --- | --- |
| Tree label tooltip | `_unit_tree_node.html` | 15, 25 |
| Breadcrumb tooltip | `_unit_crumbs.html` | 34 |
| Collapsed-crumb tooltip | `_unit_crumbs.html` | 27 |
| Collapsed-crumb SR-only name | `_unit_crumbs.html` | 29 |
| Part-progress chip tooltip | `_unit_footer.html` | 37 |
| Browser tab | `lesson_unit.html`, `quiz_unit.html`, `quiz_results.html` | 3 |
| Browser tab | `manage/editor/editor.html`, `manage/review_submission.html` | 3 |

`_unit_crumbs.html:27` and `:29` both render `{{ unit_nav.hidden_path }}` — the
`HIDDEN_PATH_SEP`-joined ancestor titles (`rollups.py:954`). Line 29 sits inside a
`.visually-hidden` span and is the collapsed crumb's **accessible name**: it is plain text
for a screen reader and must be stripped, never marked for typesetting. Without this, a
maths ancestor title is read aloud as "backslash paren x caret 2" on a page that is
otherwise fully typeset.

`_unit_footer.html:37` renders `title="{{ unit_nav.part_progress.title }}"` — the top-level
part's node title (`rollups.py:940`) — which would otherwise show raw delimiters in a
tooltip on an otherwise fully typeset footer.

**Required `{% load %}` additions.** `_unit_tree_node.html`, `_unit_crumbs.html` and
`_unit_footer.html` open with `{% load i18n %}` only; `editor.html:2` and
`review_submission.html:2` load `i18n static`. Each needs `courses_extras` added. A missing
`{% load %}` is a `TemplateSyntaxError` — a 500 on a student-facing page.

**Course titles are out of scope.** `_unit_crumbs.html:20`, `outline.html:3`,
`course_results.html:3` and `manage/editor/editor.html:75`'s leading `{{ course.title }}`
render `Course.title`, a different field on a different model. This change touches node
titles only; if course titles should typeset too, that is separate work.

### 5. Deferred: JavaScript-injected surfaces

Seven further title displays are **deferred because JavaScript injects them**; six share
one structural reason — **they are written into the DOM by JavaScript after `math.js` has
already made its single document pass**, so a `data-math-title` marker on them would have no
effect whatsoever — and the seventh (the media library) is mixed and carries its own reason
in the table. They are listed here so their absence is a decision, not an oversight.

| Deferred site | File | Injected by |
| --- | --- | --- |
| Builder node panel | `manage/_node_panel.html:3` | `builder.js:15-18` `setPanel()` — `panel.innerHTML = html` |
| Builder unit panel | `manage/_unit_panel.html:3` | same |
| Move picker heading | `manage/_move_picker.html:9` | same |
| Move picker destination rows | `manage/_move_picker.html:27` | same |
| Link picker display title | `manage/editor/_link_picker_node.html:26` | `link_dialog.js:238` — `mount.innerHTML = html` |
| Media library usage list | `manage/media/_asset_cell.html:23` | **Mixed, and excluded for two reasons.** It is server-rendered from `_asset_grid.html` *and* returned as a JS-swapped fragment (`views_media.py:60,89`), so the swapped path needs the same re-render hook as the rows above — but unlike them, a marker on the server-rendered path *would* take effect, so the blanket rule alone does not cover it. Independently, `u.unit_title` comes from `courses/media.py:51` as a **snapshot**, not a live `ContentNode.title`, so it is not the same data this change is about. |

Enabling these needs three things this change deliberately does not do: exporting
`renderInlineText` on `window` (today only `renderMath` is exported, as
`window.libliRenderMath`, and it matches `[data-katex]` only); a re-render call in
`builder.js`'s `setPanel` and in `link_dialog.js` after `mount.innerHTML`; and a gate on
`builder.html` (`:4` and `:56` already hold `extra_css`/`extra_js`, neither carrying KaTeX).
That is a distinct piece of client-side work with its own failure modes, and per this
repo's history a diff with no JS is exactly where such defects hide.


**These sites are excluded for reasons that would survive the above:**

| Excluded site | File | Why |
| --- | --- | --- |
| Move picker child rows | `manage/_move_picker.html:29,34` | `<li data-child-pk>` items are **payload, not display**. `builder.js:39` caches `kidsOl.innerHTML` and `:49` rebuilds each row as `escHtml(li.textContent)` — KaTeX markup here would be flattened into a garbage move-anchor label, this repo's known `.textContent`-flattens-KaTeX failure. Must stay unmarked even when the deferred work lands. |
| Flag/publish confirm headline | `manage/_flag_strip_headline.html` | The title is interpolated *inside* `{% blocktrans with title=node.title %}`. Marking it needs the title split out of the msgid, changing every msgid in the file (eleven blocks, six of them msgid/msgid_plural pairs) and invalidating their existing Polish translations — `makemessages` would then fuzzy-prefill wrong strings. Disproportionate for a transient confirm prompt. |
| Delete confirmation headline | `manage/node_confirm_delete.html:5` | Identical `{% blocktrans with title=node.title %}` shape, excluded for the identical reason. |
| Gradebook print/export | `manage/gradebook_print.html:56` | A print/PDF surface. KaTeX depends on webfonts that do not render reliably through print pipelines, so typesetting here needs its own font-embedding decision. |
| Move picker no-JS `<option>` | `manage/_move_picker.html:15` | `<option>` is in auto-render's own ignored-tags list and cannot hold markup at all, so this can never typeset under any future work. Structurally a plain-text context — it would take `\|strip_math_delimiters` if the builder were ever brought into scope. |
| Notification bodies | `notifications/templates/notifications/list.html:21,23`, `_bell_panel.html:25,27` | `{{ n.data.unit_title }}` inside `{% blocktrans %}` — the same msgid-splitting problem as the two confirm headlines. Also note `unit_title` is a **stored snapshot** taken when the notification was created, not a live `ContentNode.title`, so it can diverge from the node and is not strictly the same data. |
| Builder tree toggle aria-labels | `manage/_tree_toggle.html:6,7` | `node.title` inside `{% blocktrans count … asvar %}` expand/collapse accessible names. Plain-text attributes that can never typeset — they would take `\|strip_math_delimiters` if the builder were ever brought into scope, not a marker. |
| Builder rename tooltip | `manage/_tree_node.html:50` | `title="{{ node.title }}"` — likewise a plain-text attribute, listed separately from the row above it because "fragment swaps" is not the reason it is excluded. |
| Link picker payload | `manage/editor/_link_picker_node.html:14` | `data-title="{{ n.title }}"`, a JS-read payload of the same kind as `_rename_result.html:7`. Must stay unmarked and unfiltered when the deferred link-picker work lands. |
| Builder rename input | `manage/_tree_node.html:49` | `<input type="text" name="title" value="{{ node.title }}">` — a **Path C edit buffer**, the third in the app alongside `_unit_settings.html:12` and `_rename_result.html:7`. Must stay unmarked and unfiltered even when the deferred builder work lands; typesetting or stripping it would corrupt what the author saves. |

## Data flow

A title is authored as plain text in a `<input name="title">` and stored unchanged on
`ContentNode.title`. Nothing sanitises or transforms it — the delimiters survive to render
time verbatim. From there it forks into three paths.

**Path A — the typeset display.** The view scans the node titles it is about to render
(`titles_have_math` / `tree_titles_have_math`) and ORs the result into `has_math`. The
template's `{% if has_math %}` then emits the two shared partials, so `katex.min.css` plus
the five scripts reach the page. Django autoescapes the title into the `data-math-title`
element; `\`, `(` and `)` are untouched by autoescaping, and a `<` becomes `&lt;`, which
the parser turns back into a `<` text node — so `\(a<b\)` arrives at KaTeX intact. This
matters because it is the *opposite* of the stored-HTML path, where nh3 destroys `\(a<b\)`
outright; a title is a `CharField` and never passes through nh3. When the deferred
`math.js` executes — after parsing, but **before** `DOMContentLoaded` fires, since it is an
IIFE with no listener — `renderInlineText` selects `[data-math-title]` and hands each
element to `window.renderMathInElement`, which `math_reflow.js` has pre-hooked. Reflow is a
no-op here (a title is a single text node with no `<div>`/`<br>` splits), so auto-render
matches the delimiters and replaces them with KaTeX markup in place.

**Path B — the plain-text contexts.** The same title string goes through
`|strip_math_delimiters` into `title=` attributes, the `.visually-hidden` crumb name, and
`{% block head_title %}`. This path never reaches KaTeX; it terminates as attribute or
text-node content.

**Path C — the edit buffers.** `<input value=>` and `<data value=>` receive the title with
no filter and no marker attribute, so the round-trip through the rename and settings forms
is byte-identical to what was stored. Path C must stay disjoint from A and B: applying
either would corrupt what the author saves.

**DOM replacement.** Every §1 site is server-rendered and never replaced, with one
exception: `manage/editor/_preview.html:6` sits inside `[data-scope="preview"]`, which
`editor.js:88-101` `replaceWith`s on every editor mutation. It re-typesets because
`editor.js`'s `renderPreviewMath(scope)` runs `renderMathInElement` over the **whole**
preview pane — on initial load (`:539`) and after every swap (`:101`). That call is this
site's re-render path and must not be removed. A consequence worth stating plainly: the
preview heading **already typesets today**, before this change; its `data-math-title` marker
merely regularises it and is not a defect fix. One consequence to expect rather than
rediscover: on the editor's initial load that heading is visited **twice** — first by
`renderInlineText`'s `[data-math-title]` pass (`math.js` is `editor.html:186`), then by
`renderPreviewMath` over the whole pane (`editor.js:539`, loaded after it; both `defer`, so
source order is execution order). The second visit is a no-op: the first replaced the
delimiters with KaTeX markup whose `<annotation>` text carries none. Note this double visit
is **not new** — the preview pane's `.el--text` prose is already visited twice today for the
same reason. Every other DOM-replaced title site is listed
in §5 as deferred.

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

**Filter input.** `strip_math_delimiters` must tolerate a non-string (`None`, a
`gettext_lazy` proxy, an integer from a template expression) by coercing with `str()` — a
template filter that raises takes down the whole page render, and `title=` sits on surfaces
well outside this feature's blast radius. `None` therefore renders as the string `None`,
matching Django's own default rendering of `None` in a template; §Testing pins this.

**Scan robustness.** `tree_titles_have_math` recurses over `build_outline`'s structure using
`item.get("children") or []`. This is cheap defensiveness, not a response to a known
producer: `build_outline` unconditionally sets `"children": []` on every node dict
(`rollups.py:211`) and prunes by rebuilding the list (`:240-241`), never by deleting or
nulling the key. `titles_have_math` takes strings and so has no shape dependency at all.

## Testing

Every test below is falsified before it is trusted: it must be observed RED against a
mutant chosen from the *failure mode*, not from the assertion. Test runs stay scoped to the
affected files; the whole-repo sweep is a branch gate, not a step. The test-database
container must be running before any pytest invocation.

**Filter (unit).** `\(x^2\)` → `x^2`; `\[a\]` → `a`; a title with no delimiters is returned
byte-identical; an unmatched `\(x` → `x`; a stray `\)` is removed. Plus the non-string cases
§Error handling requires, which otherwise have no test and could be dropped without turning
anything red: `None` → `"None"`, a `gettext_lazy` proxy → its resolved text, an `int` → its
digits. Assert the return is a plain `str` and **not** `SafeString`, so autoescaping still
applies in a `title=` attribute.

**Filter application (rendered-output tests).** One assertion per **(file, line) site** —
eleven, not one per table row: for a unit whose title is `\(x^2\)`, the rendered output must
contain the stripped form in that attribute and must not contain `\(` anywhere inside a
`title=` or inside the `<title>` element. Per-row assertions are too coarse, because three
rows cover several sites each: `_unit_tree_node.html` `15` (unit label) and `25` (group
title) are independent interpolations, and the two "Browser tab" rows span five templates
(`lesson_unit`, `quiz_unit`, `quiz_results`, `editor`, `review_submission`). A per-row test
is satisfied by stripping at `:15` but not `:25`, or in `lesson_unit.html:3` but not
`quiz_results.html:3` — precisely the wiring gap this paragraph exists to close. Without it,
an implementation that defines the filter, registers it, and wires it into **no** site at all
passes the entire suite green — including the browser tab and the collapsed-crumb accessible
name, the two sites §4 argues hardest for. The unit tests above exercise the filter in
isolation and cannot see any of this.

**Defect 3 (view tests).** On `quiz_results.html` and `review_submission.html`, assert
`courses/js/math.js` appears in the response **and** appears *before* `courses/js/question.js`.
A gate test phrased as "contains the KaTeX `<script>`" is green on those two pages both
before and after the change — they already emit four KaTeX tags today — so without this the
one thing §Purpose defect 3 promises to fix is pinned by nothing, and the §2 ordering
constraint is unpinned too.

**Gate, per page (view tests).** For each page in the §2 gate table: with a title carrying
maths and **nothing else on the page carrying maths**, the response contains **both** the
KaTeX `<script>` **and** the `katex.min.css` `<link>`; with no maths anywhere, neither is
present. Mirrors the existing
`test_review_views.py::test_review_loads_katex_when_stem_has_math`.

**Assert the stylesheet, not only the script.** An implementation that adds
`{% include "courses/_katex_js.html" %}` to the eight new templates but forgets
`_katex_css.html` in the `extra_css` block passes a script-only suite entirely green, while
KaTeX renders with no stylesheet — overlapping glyphs and fallback fonts, i.e. visibly
broken rather than merely unstyled. Two blocks are being added per template and only one of
them is load-bearing for the test, so this is the same wiring gap the per-(file,line) rule
closes for the filter.

The two directions are **not** equally load-bearing everywhere, and the spec must not
pretend otherwise:

- On **all eight** pages that gain the flag — `course_outline`, `course_results`,
  `analytics_matrix`, `analytics_student`, `review_queue` and the three notes/tags pages —
  no `has_math` exists in the context today. `{% if has_math %}` on a
  missing variable is silently false, so the **negative assertion passes trivially** even if
  the view change is omitted entirely and only the template change lands. Only the positive
  assertion has force on those pages, and its falsification mutant must remove **the view's
  OR**, not the template's guard.
- On the pages that already compute `has_math`, both directions have force.

Two pages need further special handling, or the test cannot fail at all:

- **The editor is not in the gate table** (§2), because its assets are unconditional. It
  still needs its own assertion — that it emits both KaTeX tags for a unit with **no** maths
  anywhere — to pin the unconditional behaviour the shared partial must preserve.
- **The quiz-unit fixture must have zero questions.** `has_math = bool(questions) or ...`
  (`views.py:1318`), so any quiz with a single question already loads KaTeX and the positive
  assertion is vacuous. Only a question-free quiz exercises the title scan.

**The tree trap (view test).** A course whose maths title sits on a node several levels
away from the unit being viewed, with the viewed unit and its immediate neighbours all
maths-free, must still load KaTeX on that unit's page. This is the assertion that fails if
the scan is narrowed to `unit`/`prev`/`next`; without it the narrowing is invisible.

**The tags hub needs two gate assertions, not one.** Its gate-table row covers two render
sites, so "one test per row" is satisfiable by wiring only `my_tags` while `tag_recolor`'s
error branch still ships raw delimiters — and unlike the quiz-feedback case below, that
failure is **live today**, not masked by anything. Drive the second assertion through the
invalid-colour POST that reaches `tags/views.py:125`.

**The tags panel is unreachable by GET.** Its gate assertion needs the same invalid-tag
no-JS POST entry point described under Marker coverage below; a plain `client.get()` cannot
reach `panel_page.html`.

**No no-JS quiz-feedback gate test — and that is deliberate too.** The
`_quiz_render_feedback` row is reachable only by answering a question, so its fixture
necessarily has ≥1 question, so `has_math = bool(questions)` is already `True` and the
positive assertion would be vacuous. The OR is applied there anyway (§2) against a future
tightening of that flag; it is knowingly uncovered until then. Stated so a reader auditing
per-page coverage against the gate table does not read the gap as an omission.

**No pruned-unit test — and that is deliberate.** An earlier draft of this spec demanded a
test for "a draft unit pruned from the tree but still on screen". That state is
**unreachable**: `access.py:135-141` 404s the request before any render (see §2). The test
cannot be written through the client, so it is not required here. This paragraph exists so
its absence reads as a decision rather than an implementation gap — the `[node.title]` scan
is kept as defence-in-depth and is knowingly uncovered.

**The analytics group case (view test).** A maths title on an **expanded group** node, with
every leaf column maths-free, must load KaTeX on the matrix page. This fails if the scan
reads `matrix["columns"]` instead of `matrix["header_rows"]`.

**The breakdown shape (view test).** The analytics-breakdown page must return 200 with a
maths title present. A bare smoke test suffices: passing `breakdown` instead of
`breakdown["tree"]` raises `TypeError`, so this is the assertion that catches the wrapper
mistake rather than shipping a 500.

**Marker coverage (template test).** Assert that each display site emits `data-math-title`
and that each excluded site does not. A regex over raw source is not acceptable — per this
repo's own experience regexes match docstrings and comments; assert over rendered output.
The entry point is specified per template so this is not written N different ways:

- **Page templates** (`lesson_unit`, `quiz_unit`, `quiz_results`, `outline`,
  `course_results`, `analytics_matrix`, `analytics_student`, `review_queue`,
  `review_submission`, `editor`, `course_notes`, `my_tags`) — drive the owning **view**
  through the test client and assert on the response body.
- **`tags/panel_page.html` needs its own entry point.** `tags/views.py:69` reaches it only
  through `_add_error`, i.e. a **non-fragment POST that fails validation**, returning 422. A
  plain `client.get()` cannot reach it; the test must drive the invalid-tag no-JS POST.
- **Partials that cannot render bare** (`_outline_node` needs `item`, `course`,
  `note_counts` and the `get_item` filter; `_unit_tree_node` needs `current_pk` and
  recurses; `_breakdown_node` needs `course`; `_tag_section` needs `tag`, `grouped` and
  `palette`) — `render_to_string` with a named minimal context fixture, shared across the
  cases.
- **`_unit_tree_node.html:60`** — the childless-container branch — is unreachable through
  any view: the template's own comment (`:46-57`) records that `build_outline` prunes every
  zero-child container under both `"hide"` and `"keep"`, pinned by
  `tests/test_unit_nav_render.py::test_a_genuinely_empty_group_is_pruned_not_rendered`. Its
  marker is covered by the `render_to_string` fixture only.
- **The `_rename_result.html` exclusion** is a fragment endpoint, not a page template: cover
  it via the inline-rename POST, asserting the `<data value=>` payload is unmarked and
  unfiltered.

No builder-page assertion is required: §5 defers every builder surface, so no builder
template changes in this diff.

**Render cost (measured).** `renderInlineText` calls `window.renderMathInElement` **once per
matched element**, and a unit page holds the whole course outline *twice* — the rail plus
the drawer copy at `_unit_shell.html:40`. On this repo's own matematyka course (21 parts /
793 units) that is roughly 1,600 invocations, each entering `math_reflow.js`'s three
post-order walks, on every unit page in the course as soon as one title anywhere carries
maths. That figure counts **unit rows only**; `_unit_tree_node.html:25` marks every group
title too (parts, chapters, sections), in both copies, so the real matched-element count is
meaningfully higher. Each individual call is trivial (a title is a single text node), so the
expected result is "fine" — but that is a prediction, not a measurement, and the coarse gate
makes this the worst realistic case rather than a contrived one. Take the element count from
the fixture rather than deriving it, measure main-thread time for `renderInlineText`, and
record both; if the time exceeds ~50 ms, switch to a single `renderMathInElement` over a
common ancestor.

The single-root alternative was considered and is **not** the default: one call over
`document.body` would typeset every delimiter on the page, including element prose that
`renderInlineText`'s selector list deliberately scopes and the edit buffers §Data-flow Path C
must keep untouched. Per-element calls are what make the marker opt-in meaningful.

**Measured, 2026-08-10 (Task 11).** The small five-node fixture already exceeded this
section's own 5ms screening threshold (~30–53ms for 13 marked elements across several runs,
machine-dependent), so per the plan it was re-measured at the matematyka-scale fixture
predicted above (21 parts / 793 units, 1,643 marked elements measured — matching the ~1,600+
prediction). Across several runs this measured **~85–155ms** (observed readings included
86.2, 104.7, 105.0, 133.3, and 152.0ms), machine-dependent but consistently well past the
50ms threshold; `tests/test_e2e_title_math.py`'s own committed output (the number this
repo's test run actually prints) is the authoritative reading for any given run — see the
Task 11 report for the exact figure from the run it records. The
prediction that "each individual call is trivial" held for a single call; it did not account
for the aggregate cost across ~1,600 unconditional calls when only one title in the whole
course carries maths. `renderInlineText` (`courses/static/courses/js/math.js`) now
pre-filters: the first statement inside the `forEach` callback checks `el.textContent` for
`\(` / `\[` and returns immediately if neither is present, skipping the `renderMathInElement`
call entirely for the overwhelming majority of marked elements that carry no delimiters at
all. The single-root-over-a-common-ancestor alternative remains rejected for the reason
above; the pre-filter is the realisable fix. A fourth e2e
(`test_math_js_pre_filter_runs_end_to_end`) loads the page with `math.js` unmodified — no
route interception — so the pre-filter branch itself executes under test, since the two perf
tests above deliberately abort `math.js` and reimplement its loop without the pre-filter to
get a controlled raw-call timing.

**End-to-end.** Drive a real lesson page in a browser where the *only* maths in the entire
course is in the **next** unit's title, and assert a `.katex` element exists inside
`.unit-foot__navtitle`. Driving the real page is required: this defect is precisely one
that a template-level assertion cannot see, because the template is correct and the asset
gate is what fails.

**Visual verification.** Screenshots in light and dark, judged separately, of: the
previous/next buttons with an inline-maths title; the same with a **display-maths** (`\[…\]`)
title, which is the `.katex-display` case; a long maths title in a contents-tree unit row
and in the breadcrumb leaf, which are the other two single-line clips; a contents-tree
**group** title long enough to exercise the five-line clamp; an analytics matrix column
header with maths at two nesting depths, which is the `--ahead-h` sticky-offset and
`nowrap` column-widening case; at ≤640px the **mobile drawer** with a long maths title,
which wraps rather than clips and whose title column is squeezed to roughly 98px; a lesson
**`<h1>`** carrying `\(…\)` *and* `\[…\]` alongside words, which is both the forced-inline
decision and the `font-weight` restoration — the pass criterion being that the maths run
reads at the same weight as the adjacent words **without synthetic smearing**, since
`KaTeX_Main` has no true bold face and an inherited `bold` is browser-synthesised; if it
smears, drop `font-weight: inherit` and accept the weight mismatch as the lesser defect;
a **review-queue row** (`.card-list__row`), which is a flex row like the two below; and a
**course-results row and an outline row**,
which are the surfaces §3 claims need no clamp — screenshotted so that claim is measured
rather than assumed. **Done, 2026-08-10 (Task 11):** see §3's own closing note for the
per-surface results and the one false claim an A/B caught and corrected
(`.outline-unit__title`, which does NOT get a rule).

## Risks

- **Coarse gate.** One maths title loads 275 KB of JavaScript and 23 KB of CSS on every
  unit page of that course. Accepted above; noted here so it is not rediscovered as a
  surprise.
- **Behaviour change on two pages.** Giving `quiz_results.html` and
  `review_submission.html` `math.js` runs **both** of its passes there for the first time:
  `renderMath(document)` over `[data-katex]` (`math.js:43`) as well as
  `renderInlineText(document)` (`:44`). So any `MathElement` reachable on those pages
  (`elements/mathelement.html` emits `<div class="el el--math" data-katex>`) goes from raw
  LaTeX to a full `displayMode: true` render, and the listed inline containers begin
  typesetting too. Intended, but a larger visible change than the title feature itself.
- **A second newly-executing script on those two pages.** `question.js` sits *inside* their
  `{% if has_math %}` block (`quiz_results.html:59-68`, `review_submission.html:130-140`), so
  widening the flag for a maths **title** starts running it on responses where no question
  carries maths — a script that previously never executed there. Believed benign: both pages
  emit form-less `[data-question]` blocks, per the templates' own comments. Named here so the
  diff's reviewer is not surprised by it.
- **Clamp values measured (Task 11).** §3's CSS was a starting hypothesis; it has since been
  checked against a real render on all fourteen §Testing surfaces. The analytics sticky
  header — the surface this risk singled out as most likely to desync — measured its
  depth-2 leaf headers at exactly `--ahead-h` (38.4px = 38.4px), no desync. This risk
  predicted that struts overflowing would call for "more CSS in the same rules"; the one
  surface that did show real growth (`.outline-unit__title`, a fraction- or display-titled
  row) turned out NOT to be fixable that way — an A/B proved a `line-height`/
  `vertical-align` rule does not touch it, since the growth is the glyph's own strut height,
  not leading. No CSS changed as a result; see §3's closing note.
- **Partial coverage is visible to users.** After this change a maths title typesets on the
  student and analytics surfaces but still shows raw delimiters in the builder panels, the
  move picker, the link picker and the two confirm prompts (§5). A teacher who uses the
  builder will see the inconsistency. This is a deliberate boundary, not an unknown.
