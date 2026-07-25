# Unit editor link

## Purpose

A Course Admin walking their own course the way a student sees it — the path from the **Groups**
menu into `courses:lesson_unit` / `courses:quiz_unit`, adding notes and tags as they read — has no
way to act on what they notice. Spotting a typo or a broken element means leaving the walkthrough,
going to Studio, re-finding the unit in the builder tree, and opening its editor by hand. By the time
they are back, their place in the course is gone.

This adds a single affordance to the student-facing unit pages: an **Edit unit** link, pointing at
that unit's editor, shown only to a user who can actually author the course. The walkthrough stays
where it is; the fix happens in a second tab.

The link is deliberately *not* conditioned on how the reader arrived. Detecting "came in from the
Groups menu" would mean sniffing `HTTP_REFERER`, which is unreliable, absent on many navigations,
and would make the link vanish on a plain reload. It renders for anyone who can edit, on every unit
page. The Groups walkthrough is simply where it will be noticed most.

## Scope

The motivating journey is fully covered by the three templates below, and that is checkable rather
than assumed: every Groups surface (`templates/grouping/my_groups.html`, `group_list.html`,
`group_detail.html`, `collection_detail.html`) links into a course through
`courses:course_outline`, whose tree rows link to `courses:lesson_unit`, which redirects to
`courses:quiz_unit` for a quiz unit, which in turn redirects to `courses:quiz_results` once
submitted. There is no fourth unit-reading view to miss.

**In scope** — the three unit consumption templates:

- `templates/courses/lesson_unit.html`
- `templates/courses/quiz_unit.html`
- `templates/courses/quiz_results.html`

**Explicitly out of scope** — the course outline rows (`templates/courses/_outline_node.html`), the
in-page contents tree and its mobile drawer (`templates/courses/_unit_tree_node.html`), and any
change to the editor page itself. These were considered and declined: one affordance, in one place,
is the whole feature.

Also deliberately out of scope: `tags/templates/tags/panel_page.html`, the standalone page
`tags/views.py::_add_error` renders on the no-JS tag-validation-error path. A manager who submits an
invalid tag name with JS off lands there without the strip. That is a transient error surface the
reader immediately navigates back out of, and giving it the strip would mean giving it a full unit
context it does not build — an accepted, stated gap rather than an oversight.

**In-app help** (`core.help`, the bilingual permission-gated manuals) is an accepted **follow-up**,
not part of this change. The feature adds an affordance squarely inside the Course Admin walkthrough
those manuals describe, so a sentence in the relevant topic is warranted — but it is documentation
work with its own bilingual review, and bundling it would widen this change's blast radius for no
functional gain. No committed help screenshot needs regenerating either way:
`tests/capture_help_screenshots.py` clips the `content-consume` and `interactive` shots to
`article.lesson`, which sits *below* the strip and therefore excludes it.

## Architecture / components

Three pieces, each mirroring a pattern the repo already uses.

### 1. `courses/rendering.py` — new module, one function

```python
def unit_edit_context(user, unit):
    """Context for the unit-page editor link: `can_edit_unit` plus the resolved URL."""
```

Returns `{"can_edit_unit": bool, "unit_editor_url": str | None}`.

**Precondition.** Callers pass an **authenticated** user and a **UNIT** `ContentNode`. Both hold at
every call site, so the helper does not defend against either. Note that "every call site" is **six
views, not three** — because the merge happens inside two *shared builders*, the helper runs from
every view that reaches them:

| View | Reaches the helper via |
|---|---|
| `courses.views.lesson_unit` | `full_lesson_render_context` |
| `courses.views.check_answer` | `full_lesson_render_context` — **no-JS branch only** |
| `notes.views.note_add` | `full_lesson_render_context` |
| `courses.views.quiz_unit` | `build_quiz_context` |
| `courses.views.quiz_answer` (via `_quiz_render_feedback`) | `build_quiz_context` — **no-JS branch only** |
| `courses.views.quiz_results` | local context |

All six carry `@login_required` and resolve their node with `get_node_or_404(..., require_unit=True)`,
so the precondition genuinely holds — but the enumeration is spelled out because "the three views" is
the wrong set to re-audit against if the builders ever gain a seventh caller.

The two "no-JS branch only" annotations matter for the same reason: both views return their fragment
early (`courses/views.py:822` and `:1157`) before reaching the builder, so on the JS path they never
execute `unit_edit_context` at all. The precondition is unaffected — it holds wherever the helper is
reached — but a future re-audit should not expect the helper to run on every request to those two. Behaviour
on other inputs is unspecified: an anonymous user happens to return `False` safely, via
`can_manage_course`'s `owner_id is not None` guard, but that is an accident of the current
implementation and not a contract; a chapter node would produce a reversible URL that 404s.

`can_edit_unit` is `can_manage_course(user, unit.course)` from `courses/access.py` — course owner,
**or** a holder of the `courses.change_course` model permission (the Platform Admin group). That is
the *exact* predicate `courses.views_manage.editor` enforces before serving the editor, so the link
can never appear where following it would 403. Reusing the predicate rather than restating it is the
point: a future change to authoring access moves both together.

Worth stating precisely, because the role names invite a wrong assumption: the **Course Admin** role
group holds `grouping.change_group`, *not* `courses.change_course` (see `institution/roles.py` and
`tests/factories.make_ca`). A CA therefore gets this link through **course ownership**, which is also
how they come to see the course under Groups at all (`grouping/scoping.py` scopes a CA's groups by
`group.course.owner_id == user.id`).

A PA satisfies the helper on **every** course via the model permission — but that is a statement
about `unit_edit_context`, not about page reachability. Whether a non-owner PA can open the unit page
at all is decided earlier, by `can_access_course`, which grants a non-owner/non-enrolled user access
only through `is_staff`. In production a PA *is* `is_staff` (derived from the role by
`accounts/services.py`), so the two agree. In tests they do not: `tests/factories._make_role` attaches
the permission group **without** setting `is_staff`, so `make_pa(client)` yields a user who passes
`can_manage_course` and fails `can_access_course`. Any *page-level* PA test must therefore set
`is_staff` or enroll the actor; the unit-level matrix row below needs neither.

`unit_editor_url` is `reverse("courses:manage_editor", kwargs={"slug": unit.course.slug, "pk": unit.pk})`
when permitted, and `None` otherwise — never a URL the template must guard against emitting.

That `reverse(...)` line is byte-identical to `courses/views_manage.py::_editor_path` (`:1106`), and
the duplication is deliberate rather than overlooked. `_editor_path` is a private helper of the manage
layer; importing it into `courses/views.py` would make the consumption path depend on the authoring
module for two lines of URL construction. Duplicating them keeps the dependency arrow pointing one
way, and `reverse()` fails loudly on both sides if the route ever changes.

The module is new but the shape is not: `tags/rendering.py` and `notes/rendering.py` are the same
thing — a thin, request-free context builder that a view merges into its context and a test can call
directly. `courses/access.py` is deliberately left alone; it answers permission questions, and URL
construction is not one.

### 2. Three merge points (`courses/views.py`)

Three edits, but they are **not** the three views — each is the *shared context builder* behind one
or more render sites, chosen so no render path is left out:

- **`full_lesson_render_context()`** (`courses/views.py:431`) — covers three lesson render paths: the
  `lesson_unit` GET (`:587`), the `check_answer` POST re-render (`:828`), and the no-JS notes
  validation re-render (`notes/views.py:194`, status 422). It already merges `unit_tags_context(...)`
  and `lesson_notes_context(...)`; `unit_edit_context(user, node)` joins them.
- **`build_quiz_context()`** (`courses/views.py:995`) — the merge goes **inside this function**, next
  to its existing `unit_tags_context` merge (`:1114`), *not* into the `quiz_unit` view. This is
  load-bearing: `courses/quiz_unit.html` is rendered from **two** sites — the `quiz_unit` view
  (`:1135`) and `_quiz_render_feedback`'s no-JS full re-render (`:1170`) — and both build their
  context here. Merging in the view instead would leave the second site without `can_edit_unit`,
  and the link would vanish from it.

  To be accurate about how reachable that second site is, rather than overstating it: `quiz_answer`
  raises `PermissionDenied` unless `is_enrolled(request.user, course)`, and `build_quiz_context` sets
  `read_only` when there is no submission — so a manager who is *not* enrolled in their own course
  gets a read-only quiz and can never trigger the no-JS re-render at all. The path is live only for a
  manager who is also enrolled. The merge point is still chosen for `build_quiz_context` — it
  single-sources both sites for free — but the justification is insurance against divergence, not a
  bug that exists today. Because the path is genuinely reachable (an enrolled owner is an ordinary
  case), it gets an assertion of its own rather than being left to the argument above.
- **`quiz_results`** (`courses/views.py:1284`) — a single render site with a locally-built context;
  merge next to its existing `unit_tags_context` merge.

Merging the whole dict (rather than setting `ctx["can_edit_unit"]` by hand at each site) keeps the
three sites from drifting if the helper ever returns a third key.

**Update both builders' docstrings.** `full_lesson_render_context` and `build_quiz_context` each open
with a docstring that enumerates exactly what they assemble; adding an authoring-permission key
without touching them leaves two descriptions that are now incomplete. Extend both to mention the
edit-link context — it is part of the change, not follow-up tidying.

**The merge layer is deliberately asymmetric, and that asymmetry has a consequence worth stating.**
Lessons merge one layer *above* `build_lesson_context` (in `full_lesson_render_context`), while
quizzes merge *inside* `build_quiz_context` — for the single-sourcing reason given above. The result
is that `build_quiz_context` becomes a builder that performs a permission check and a `reverse()`,
while its lesson counterpart `build_lesson_context` stays pure.

That matters because `build_quiz_context` has **direct unit-test callers** that bypass the views
entirely — `courses/tests/test_callout_has_math.py:58`, `tests/test_slideshow_context.py:29`,
`tests/test_tabs_invariant.py:99`, `tests/test_tags_consumption.py:84` — so all four now execute
`can_manage_course` on whatever user they pass. None of them should break, but state the reason
precisely, because the tempting shorthand ("the course has no owner") is false for one of them:
**none of the four passes an actor who owns the course, and none holds `courses.change_course`**, so
both branches of the predicate return `False` and the `reverse()` branch is never taken. Note in
particular that `test_callout_has_math.py` *does* give its course an owner —
`pa = make_pa(client, "pa"); course = CourseFactory(owner=pa)` — while the user it passes to
`build_quiz_context` is `student_user`, an unrelated plain verified user. The conclusion survives; the
"owner is None" premise does not. They must be **run and confirmed green** rather than assumed,
and a future reader must not "tidy" the merge out of `build_quiz_context` or mirror it into
`build_lesson_context` without re-reading the two-render-sites argument above.

`from courses.rendering import unit_edit_context` goes at **module top level** in `courses/views.py`.
The neighbouring `unit_tags_context` / `lesson_notes_context` merges use function-local imports, one
of which — `lesson_notes_context` at `courses/views.py:436` — carries a `# lazy: avoid import cycle`
comment (the three `unit_tags_context` imports at `:437`, `:1112` and `:1321` are function-local but
uncommented). Copying that style here would be cargo-culting:
`courses/rendering.py` imports only `courses.access` and `django.urls`, both of which
`courses/views.py` already imports at module level, so there is no cycle to avoid and a lazy import
with a cycle comment would assert something false.

The "one builder covers N render sites" property is exactly the kind of claim that decays silently
under refactoring, so the non-GET paths get their own assertions rather than being trusted (see
Testing).

### 3. `templates/courses/_unit_strip.html` — new partial

```html
{% load i18n %}
<div class="unit-strip">
  {% include "tags/_unit_tag_panel.html" %}
  {% if can_edit_unit %}
    <a class="btn btn--ghost btn--small unit-strip__edit"
       href="{{ unit_editor_url }}" target="_blank" rel="noopener">
      <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3z"/><path d="M14.5 5.5l4 4"/>
      </svg>
      {% trans "Edit unit" %}<span class="visually-hidden">&nbsp;{% trans "(opens in a new tab)" %}</span>
    </a>
  {% endif %}
</div>
```

Each of the three templates changes exactly one line: the existing
`{% include "tags/_unit_tag_panel.html" %}` at the top of `{% block content %}` becomes
`{% include "courses/_unit_strip.html" %}`. The include sits at the identical position in all three
today, which is what makes one wrapper cover them all.

**Why a wrapper, and not the link inside the tag panel.** `tags/views.py::_panel_response` re-renders
`tags/_unit_tag_panel.html` **on its own** as a fetch fragment, and `tags/static/tags/js/tags.js` does
`panel.replaceWith(fresh)` (~line 86) with `fresh = tmp.querySelector(".unit-tags")`. A link placed
inside the panel would be silently destroyed the first time the user added a tag — i.e. during the
exact workflow this feature exists for, and only with JS on, so it would pass every server-side test.
As a **sibling** of `.unit-tags` inside `.unit-strip`, the link is outside the replaced subtree and
survives. This is a load-bearing structural constraint, not a styling preference; a dedicated test
guards it (see Testing).

The link itself:

- `href="{{ unit_editor_url }}"`, `target="_blank"`, `rel="noopener"`.
- A monochrome `currentColor` line-SVG pencil with the shared `.icon` class — the repo's icon
  convention is line SVGs, never emoji, so the `✎` from the mockup ships as an inline `<path>`.
  It must be **inline**, not a `<use href="#…">` sprite reference: the repo's sprite
  (`templates/courses/manage/_icon_sprite.html`) is included only on manage pages, so a sprite
  reference would render blank on these consumption templates. `.icon` is defined globally in
  `core/static/core/css/app.css` and supplies fill/stroke, so the SVG carries only `viewBox`,
  `aria-hidden` and `focusable`.
- Visible label `{% trans "Edit unit" %}`, plus a visually-hidden "(opens in a new tab)" so the
  new-tab jump is announced rather than surprising. **The code block above is the normative markup** —
  note the `&nbsp;` *inside* the span, before the parenthetical. It is a non-breaking space on
  purpose, and an ordinary space would not do: `.visually-hidden` sets `position: absolute`, which
  blockifies the span, and leading collapsible whitespace
  at the start of a block box is stripped — so a plain space there is simply discarded and the markup
  is not doing what it appears to. `&nbsp;` is not collapsible and survives.

  Be honest about how much this buys: browsers generally insert a separator when concatenating an
  accessible name across element boundaries, so "Edit unit" and "(opens" would very likely be
  announced apart regardless. The `&nbsp;` makes the separation explicit rather than dependent on
  accname implementation details; it is cheap insurance, **not** a load-bearing invariant, and no
  automated test guards it. Confirm the announced name with a real screen reader during the same
  manual pass that checks the screenshots, not by asserting on markup bytes.

  `.visually-hidden` needs no per-page CSS, but note it is defined **three times** in the repo —
  `core/static/core/css/app.css:1167`, `tags/static/tags/css/tags.css:6`, and
  `notes/static/notes/css/notes.css:4`. On these three pages `tags.css` loads last, so *its* copy is
  the one that applies; it adds `padding: 0; margin: -1px; border: 0` on top of the same
  `position: absolute`. The argument above depends only on `position: absolute`, which all three
  share, so the conclusion is unaffected — but cite the right rule, since a reader checking only
  `app.css` would be checking a copy that loses the cascade here.

### Styling

In `courses/static/courses/css/courses.css` — all three templates already load it, so no new `<link>`
anywhere:

```css
/* The strip owns the block rhythm; .unit-tags' own .5rem margin is zeroed inside it
   so both flex items align on the row's top edge and the spacing survives wrapping. */
.unit-strip { display: flex; flex-wrap: wrap; gap: .5rem; align-items: flex-start;
              margin-block: .5rem; }
.unit-strip .unit-tags { flex: 1 1 auto; min-width: 0; margin-block: 0; }
```

**Why the strip takes over the margin.** `align-items: flex-start` aligns each item's **margin box**
to the row's cross-start. `.unit-tags` carries `margin: .5rem 0` from `tags.css` while a bare `.btn`
carries none, so leaving that margin in place would drop the anchor's top edge ~8px above the panel's
border-box top — visibly misaligned. Zeroing it *inside the strip* and moving the `.5rem` up to
`.unit-strip` fixes three things at once and introduces no duplicated literal:

1. Both items now have zero block margin, so their border boxes align exactly — no compensating
   margin on the anchor, and therefore no hardcoded `.5rem` in `courses.css` silently coupled to the
   value in `tags.css`.
2. The `.5rem` above and below the strip is preserved in **every** state. This matters most in the
   wrapped narrow layout, where the button is the last flex line and `.btn` has no block-end margin:
   with the margin left on `.unit-tags`, the strip's bottom edge would be the button's bottom edge and
   the following `.unit-shell` would start with **0px** of separation — a real regression against
   today's `.5rem`, in exactly the state the narrow screenshots scrutinise.
3. The link-absent (student) case keeps today's vertical rhythm exactly: the panel's `.5rem` block
   margin is simply relocated to its wrapper. (Horizontally the student case is unchanged too,
   provided `min-width: 0` is present — see "What the student actually sees.")

`.unit-strip__edit` therefore carries **no screen styling at all**. It exists primarily as a stable
selector hook for the view tests and the e2e, and is documented as such so it does not read as an
undefined class.

Its one and only rule is a print hide:

```css
@media print { .unit-strip__edit { display: none; } }
```

**Print is worth a decision rather than an omission.** The repo tunes print output deliberately —
`core/static/core/css/app.css:971` and `courses/static/courses/css/courses.css:1238` both carry
`@media print` blocks written for lesson printing — and neither hides `.btn` or the tag strip. Without
this rule a manager who prints a lesson during the very walkthrough this feature serves gets an
"Edit unit" button on paper, which is pure noise: it is an affordance for a second browser tab, and
paper has none. Hiding it costs one line.

This does not weaken anything that leaned on "no styling": the CI guard below asserts on
`.unit-strip` and `.unit-strip .unit-tags` (margins and `min-width`), not on `.unit-strip__edit`, and
the e2e/selector-hook justification is unaffected — a print-only rule changes no screen layout. State
the property as "no *screen* styling, one print rule" so the two are not read as contradicting.

**Horizontal placement is intentional.** `flex: 1 1 auto` on the panel makes it take the remaining
width, which pins the button to the **far right end of the row** — adjacent to the row's edge, not to
the "Tags (n)" summary text. That is the approved mockup, and it is also what keeps the link-absent
(student) case the same width as today: a lone `flex: 1 1 auto` item fills the row exactly as the
block-level panel does now. The acceptance criterion for the **unwrapped** row is therefore that the
button **shares the tag panel's top edge**, not that it sits beside the summary.

**On the wrapped line the button sits flush left, and that is the intended behaviour.** Once the row
breaks, the panel is alone on line 1 (still `flex: 1 1 auto`, still full width) and the button is
alone on line 2, where — with no `justify-content` and no auto margin — it starts at the row's
inline-start edge, directly under the panel's left edge. This is a deliberate acceptance, not an
omission: right-pinning it in the wrapped state would require `margin-inline-start: auto` on the
anchor, which would contradict the "`.unit-strip__edit` carries no styling at all" property above and
buy nothing — a lone button on its own line reads naturally at the start of the line, following the
panel above it in reading order.

State it as its own criterion because the top-edge criterion above is **meaningless once the two
items are on different lines**, which is exactly the state the ~400px owner shot captures. The
wrapped-layout acceptance criterion is: the button sits on its own line, flush with the content
column's left edge, with the `.5rem` block gap below it intact (see the margin discussion above).

`min-width: 0` is not boilerplate — but be exact about what it is for, because it is easy to describe
backwards. **It does not add a behaviour; it prevents this change from regressing one.**

On master `.unit-tags` is a plain block-level child of `<main class="app-main">`
(`templates/base.html:146`; `lesson_unit.html`'s `{% block content %}` includes the panel directly),
and `.app-main` declares no `display` (`core/static/core/css/app.css:34`) — so the panel is **not** a
flex item today and has **no** automatic minimum at all. Its width is simply the containing block's
width, and an over-wide `<fieldset class="unit-tags__picker">` spills outside the panel's chrome.

Wrapping the panel in `.unit-strip` makes it a flex item for the first time, and *that* is what
introduces the floor: a flex item's automatic minimum is its min-content size, and the UA
stylesheet's `min-inline-size: min-content` on `<fieldset>` inflates that min-content to the widest
label row. Without `min-width: 0`, the panel's used width would be floored there — its border,
background and rounded corners inflating with the fieldset, which is **not** how the page renders
today. `min-width: 0` defeats that new floor and restores master's behaviour exactly.

So the three states are:

| | panel's border box | fieldset |
|---|---|---|
| master | container width (no floor — not a flex item) | spills outside the chrome |
| this change, **without** `min-width: 0` | floored at min-content — **regression** | contained, chrome inflated |
| this change, **with** `min-width: 0` | container width — same as master | spills outside the chrome |

Be precise about what that does and does not change, because the intuitive story is wrong. It is
**not** about wrapping: flex line-breaking is decided from each item's outer *hypothetical* main size,
and with `flex-wrap: wrap` the button moves to a second line whenever the panel's content plus the
button exceeds the container — identically with or without this declaration. What the declaration
buys is that once the panel is alone on a shrunk line, its **own border box** can shrink to that
line's width instead of staying floored at min-content. Without it, the panel's border, background
and rounded corners extend past the content column.

That is the observable: at ~400px with the panel open, **the panel's right border edge lines up with
the content column's right edge** — as it does on master — rather than running past it. The acceptance
criterion is stated in those terms, because it is the only thing that actually distinguishes the
declaration's presence from its absence.

**What it does not buy, stated plainly so the acceptance criteria stay honest.** `min-width: 0`
defeats the automatic minimum of the *flex item* it is set on (`.unit-tags`). It does nothing about
the UA `min-inline-size: min-content` on the `<fieldset class="unit-tags__picker">` further down, and
that fieldset's min-content contribution still propagates up through ordinary min-content sizing into
`.unit-tags`. So a sufficiently wide unbreakable token in a tag label can still push the fieldset past
the `<details>` box — which has no `overflow` clipping — and scroll the page sideways, *with this fix
fully in place*.

Be exact about **which** boxes have an automatic-minimum floor here, because the plausible-sounding
version of this story is wrong and the repo has been bitten by confidently-stated false mechanisms
before. `min-width: auto` resolves to a content-based minimum **only for flex and grid items**. The
relevant nesting is:

```
<details class="unit-tags">              ← flex ITEM of .unit-strip   → automatic minimum applies
  <div class="unit-tags__panel">         ← plain block (padding + border-top only, no display:flex)
    <form class="unit-tags__add">        ← block-level child of a BLOCK → NOT a flex item
      <fieldset class="unit-tags__picker">  ← flex item of .unit-tags__add → floor is the UA
                                             min-inline-size: min-content, plus width: 100%
```

`.unit-tags__add` is `display: flex` — but that makes it a flex *container*, not a flex *item*. Its
parent `.unit-tags__panel` is a plain block, so `.unit-tags__add` has **no** automatic-minimum floor
and `min-width: 0` on it would be a no-op. The floor that actually survives is the fieldset's.

That overflow is **pre-existing and out of scope**: `.unit-tags` is full-container-width today, so the
same label overflows the same way on master. Cutting the chain properly would mean adding
`min-inline-size: 0` to `.unit-tags__picker` — one line, and one line only, since that fieldset is the
sole box in the chain with a floor to defeat — a fix to the tags panel's internals that changes
rendering for every reader, including those who never see this link. That is a separate concern from "add an edit link" and is deliberately not bundled
here.

**What the student actually sees: nothing new — and that is the whole point.** `min-width: 0` is
scoped to `.unit-strip .unit-tags`, and the strip wraps the panel for **every** reader, link or no
link, so a student's panel becomes a flex item too. That is exactly why the declaration is not
optional for them: without it, the student — who never sees the link and gets no benefit from this
feature at all — would be the one who inherits the new min-content floor.

With it, the student rendering matches master in **every** state, including the long-token one (see
the three-state table above: master and this-change-with-`min-width: 0` are the same row twice). There
is no accepted student-visible trade-off here, because there is no student-visible change to accept.

This is worth stating flatly because the tempting framing — "we clamp the panel, so the fieldset now
spills out" — describes something master already does, and would send a reviewer looking for a
regression that isn't there, or asking this change to fix pre-existing overflow that is out of scope.
The student narrow screenshot row therefore exists as a **parity guard**, not as a sign-off on a
degradation.

The acceptance criterion is therefore about the **panel's border box**, not the page: its right edge
sits within the content column at ~400px with the panel open, and the page shows no horizontal
overflow **beyond what the same page shows with the feature's rendering undone** (compare against the
feature-off baseline described in the screenshot section — produced by reverting the three includes
and the two CSS rules in place, *not* by checking out master; do not assert an absolute).

That fieldset is itself conditional — `{% if addable_tags %}` — so it renders only when the actor
owns at least one tag *not already on this unit*. Any test or screenshot meant to exercise this
hazard must therefore be set up with `addable_tags` non-empty. The "long label" must be a **single
unbroken token** with no spaces, at the model's full `TAG_NAME_MAX_LEN = 50` cap:
`.unit-tags__picker label` is `inline-flex` around plain text, so its min-content size is the longest
*unbreakable* token, not the label's length — a 50-character label of ordinary words simply wraps and
contributes nothing, leaving the shot identical with `min-width: 0` deleted.

**The margin here is thin, so do not trust a character count — validate the shot by A/B.** The
label renders at `font-size: .8rem` (12.8px, `tags/css/tags.css:175`). At a 400px viewport the content
column is ~368px, and after `.unit-tags`' border and `.unit-tags__panel`'s `.65rem` inline padding
roughly **~345px** reaches the fieldset. A 50-character lowercase token at 12.8px lands around
325–350px including the checkbox and gap — i.e. *right at the boundary* — and a 40-character one is
nowhere near it. Since 50 is a hard model cap there is no headroom to fix a too-short token by
lengthening it. Two consequences:

1. Use **wide glyphs** to buy margin — uppercase letters, `W`s, digits — not 50 narrow lowercase
   characters, and consider dropping the shot's viewport to ~360px.
2. **Validate the fixture, don't assume it:** take the shot once with `min-width: 0` deleted from
   `courses.css` and confirm the two images actually differ. If they are identical the fixture failed
   to reproduce the hazard and the shot is proving nothing — which is precisely the failure this
   paragraph exists to prevent.

Because that declaration is load-bearing but otherwise guarded only by a human looking at a
screenshot, it also gets a cheap automated guard — see Testing.

To state the margin ownership once, unambiguously: `.unit-tags` keeps its `margin: .5rem 0` from
`tags/css/tags.css` **everywhere except inside `.unit-strip`**, where it is zeroed and the strip owns
the block rhythm instead (for the three reasons enumerated above). That is a deliberate override, not
an inheritance — so if the `.5rem` in `tags.css` ever changes, the matching value on `.unit-strip`
must be changed with it.

**The override wins on specificity, not source order — keep the two-class selector.** All three
templates link `courses.css` *before* `tags.css` (`lesson_unit.html:33` and `:35`), so `tags.css`'s
`.unit-tags { margin: .5rem 0 }` comes later in the cascade and would win a source-order tie. The
override survives only because `.unit-strip .unit-tags` is (0,2,0) against (0,1,0). Anyone
"simplifying" that selector to a bare `.unit-tags` inside `courses.css` — or hoisting the rule into a
stylesheet that loads earlier still — silently reintroduces both the ~8px top-edge misalignment and
the 0px wrapped-layout gap this section spends three paragraphs justifying. The CI guard below
catches the deletion; it does not catch a specificity-losing rewrite, so the reason is recorded here.

The link is a plain `.btn.btn--ghost.btn--small`, matching the existing "Start fresh" / "My notes"
affordances. `flex-wrap: wrap` lets the row break to two lines on narrow viewports with no media
query. Note that with the panel **closed** the summary is only ~10 characters, so at 400px there is
ample room and the row correctly does *not* wrap — the wrap behaviour is only observable with the
panel open, which is what the narrow-screen screenshot must therefore capture.

Because `.unit-tags` is a `<details>`, it grows downward when opened. `align-items: flex-start` keeps
the link pinned to the top of the row instead of stretching or re-centering as the panel expands.

## Data flow

```
GET /courses/<slug>/u/<pk>/
  → courses.views.lesson_unit
      → can_access_course(user, course)            (gate: 403 if not)
      → full_lesson_render_context(node, user, …)
          → unit_edit_context(user, node)
              → can_manage_course(user, node.course)   → can_edit_unit
              → reverse("courses:manage_editor", …)    → unit_editor_url (or None)
  → lesson_unit.html → _unit_strip.html
      → {% if can_edit_unit %} <a target="_blank" href="{{ unit_editor_url }}"> {% endif %}

click → GET /manage/courses/<slug>/build/unit/<pk>/edit/   (new tab)
      → courses.views_manage.editor
          → can_manage_course(user, unit.course)     ← same predicate; cannot disagree
```

The quiz paths are identical with `quiz_unit` / `quiz_results` in place of `lesson_unit`.

Two access checks apply in sequence and answer different questions: `can_access_course` decides
whether the reader may see the unit page at all, `can_manage_course` decides whether the edit link
appears on it. A group teacher passes the first and fails the second — they read the unit, they do
not get the link.

## Error handling

There is no new failure mode to handle, which is the design's main defence:

- **No new view, no new URL, no POST, no form, no JS.** The feature is a conditional anchor.
- **Permission is fail-closed, but by the editor view — not by the rendered value.** `unit_editor_url`
  is `None` whenever `can_edit_unit` is false, and the template's `{% if %}` means it is never
  rendered. Note what a guard-less template would actually emit, since it is easy to get wrong:
  Django renders a `None` context value as the literal string `"None"` (the empty-string substitution
  of `string_if_invalid` applies only to *missing* variables), so the markup would carry
  `href="None"` — a dead relative URL that 404s, not an empty attribute. The real guarantee is the
  next bullet, not this one.
- **Defence in depth is already there.** The editor view re-checks `can_manage_course` itself and
  raises `PermissionDenied`; a hand-typed URL is refused regardless of what any page rendered. This
  is what makes the feature safe even against a template mistake.
- **The URL cannot silently rot.** `reverse()` raises `NoReverseMatch` if the route name or kwargs
  ever change. It runs at **view time**, not render time, and only on the branch where
  `can_edit_unit` is true — so a route rename fails loudly only because the positive matrix row
  drives a manager through the helper. That row is what keeps this guarantee alive.
- **No migration.** `uv run python manage.py makemigrations --check` must stay clean.

The one realistic regression this design *can* cause is layout: `.unit-strip` wraps an element
(`.unit-tags`) that three pages already position. That is covered by screenshot verification in both
light and dark mode rather than by runtime error handling.

## Testing

Every new test must be **falsified** before it is accepted: delete or invert the thing it guards and
confirm it goes RED. A green test that was never seen to fail proves nothing. Use
`tests/factories.py` role helpers (`make_pa` / `make_ca` / `make_teacher` / `make_student`) and
`tests.factories.TEST_PASSWORD` — never a password literal, which GitGuardian flags.

**Where the tests live.** A new `tests/test_unit_edit_link.py` owns the helper matrix, the three
page-rendering groups and **all three** non-GET path assertions — one per row of the table in "The
non-GET render paths" below, which is the authoritative count. The
**containment test** — so named because the fragment-level formulation is rejected further down as
unfalsifiable; it asserts on the **full page render** despite living beside the tags tests — belongs
in the existing `tests/test_tags_consumption.py`, beside the tags
consumption tests whose behaviour it constrains, because that is where someone editing the panel will
look. The e2e extends `tests/test_e2e_tags.py`, whose existing add-a-tag flow already uses the exact
wait idiom this spec prescribes
(`expect(page.locator(".unit-tags__chips .tag-chip", has_text=…)).to_be_visible()` after the fetch
swap) — copy that flow rather than writing a new one.

**A trap that makes naive negative tests worthless.** `tests/factories._make_role` attaches the role
permission group but does **not** set `is_staff` (production derives it in `accounts/services.py`; the
factory does not). `can_access_course` grants a non-owner, non-enrolled user access only via
`is_staff` or non-archived `group.teachers` membership. So a bare `make_student(client)` or
`make_teacher(client)` gets **403 from the unit page before any template renders**. A test asserting
"the response does not contain the editor href" against that actor passes for the wrong reason and
keeps passing even if the `{% if can_edit_unit %}` guard is deleted outright. Every negative
page-level actor in this feature must therefore be given genuine read access — enrolled via
`EnrollmentFactory`, or added to a non-archived `GroupFactory` group's `teachers` — and every
page-level test must assert the **expected** status **before** asserting on the body.

"Expected" is 200 everywhere in this feature *except* the no-JS note-validation re-render, which
`notes/views.py:194` returns with **status 422** by design. Taking the 200 rule literally there would
fail the test on its own precondition, so that one row asserts `422`. The rule's purpose is to prove
the page actually rendered rather than short-circuiting into a 403 or a redirect — a 422 that carries
the re-rendered lesson body satisfies that purpose exactly as a 200 does.

**Unit — `unit_edit_context` (the permission matrix).** The negative rows are the point of the
feature, so they are tested at least as carefully as the positive ones.

Although this test issues no request, it still takes the `client` fixture: every role helper routes
through `_make_role(client, …)` → `make_login(client, username)`, which needs a client and logs it in
as a side effect. Writing it as a pure helper-level test without `client` raises `TypeError` on the
first row. Pass an explicit, distinct `username` per row so building several roles in one test cannot
collide on `create_user`.

| Actor | `can_edit_unit` |
|---|---|
| Course owner **holding no `courses.change_course`** | `True` |
| Platform Admin (holds `courses.change_course`), non-owner | `True` |
| **Course Admin (`make_ca`), non-owner, enrolled** | **`False`** |
| **Course Admin (`make_ca`) who owns the course** | **`True`** |
| Group teacher with `can_access_course` on the course, non-owner | `False` |
| Enrolled student | `False` |

**The owner row's actor is constrained for the same reason the `make_ca` rows exist.** It must hold
**no** `courses.change_course` — build it as `make_student(client, "owner")` (or a bare verified
user) plus `CourseFactory(owner=that_user)`. Built instead with `make_pa(client, "owner")`, the row
would be satisfied by the *permission* branch of `can_manage_course` and would never exercise the
`owner_id == user.id` branch at all: deleting the ownership check outright would leave it green, and
the row would silently duplicate the PA row below it. Ownership is the only route by which a Course
Admin reaches this link, so the row that proves ownership works must not be reachable any other way.

The two `make_ca` rows are the most valuable in the table, and are easy to omit precisely because the
role's *name* suggests they are redundant. They pin the asymmetry this design rests on — a Course
Admin holds `grouping.change_group`, not `courses.change_course`, so the link reaches them through
**ownership alone**. Without these rows, adding `courses.change_course` to the CA role group, or
"helpfully" broadening the predicate to `user.is_staff`, would silently widen who can edit while every
other test stayed green.

The teacher row must be built so the actor genuinely passes `can_access_course` (a `GroupFactory`
group on the course, actor in `group.teachers`, `archived=False`) — otherwise it degrades into a
duplicate of the student row and stops guarding anything. A positive row also asserts
`unit_editor_url` equals the reversed `courses:manage_editor` URL, and a negative row asserts it is
`None`.

**View rendering — all three pages.** For each of `lesson_unit`, `quiz_unit` and `quiz_results`: the
owner's response (200) contains the editor href, and an **enrolled** non-managing viewer's response
(also 200 — see the trap above) contains **neither** the editor href **nor** the string
`unit-strip__edit`.

Asserting both is not belt-and-braces; each catches a different mutation, and neither catches the
other's:

- Inverting the predicate in `unit_edit_context` is caught by the **href** assertion.
- Deleting the `{% if can_edit_unit %}` guard from the template is caught **only** by the
  `unit-strip__edit` assertion. It is *not* caught by the href one: for a non-manager
  `unit_editor_url` is `None`, so the unguarded anchor renders `href="None"`, which does not contain
  the reversed `manage_editor` URL — the href assertion sails through the very regression it looks
  like it is guarding.

So when falsifying these tests, the mutation to try for the href assertion is **inverting the
predicate**, and for the class assertion it is **deleting the template guard**. Running only the
latter against only the former would produce a green result with no stated interpretation. `quiz_unit` redirects to `quiz_results` once a submission is
SUBMITTED, so the quiz-unit case must have no submission for the actor.

The quiz-results case needs more care than "a submitted submission" suggests: `quiz_results` filters
by `student=request.user` and **redirects back to `quiz_unit`** when that user has none. So *each*
actor needs their **own** SUBMITTED row — including the owner, who being non-enrolled would never
accumulate one naturally. Spell the fixture out explicitly, because the factory's defaults build
something useless here: `QuizSubmissionFactory` defaults `student` to a fresh `UserFactory` and
`unit` to `make_quiz_unit()`, which mints a brand-new quiz unit **in a brand-new course**. Every row
must therefore pass all three kwargs —
`QuizSubmissionFactory(student=<actor>, unit=<the quiz node under test>, status=QuizSubmission.Status.SUBMITTED)`
(the status field defaults to `IN_PROGRESS`). Without it the test silently follows a 302 to
`quiz_unit`, which for the owner still contains the href and so passes while asserting against the
wrong page. Each quiz-results test must therefore assert it actually landed on `quiz_results` before asserting on
the body. These are **two mutually exclusive setups, not one recipe** — `redirect_chain` exists only
on a response fetched with `follow=True`, so pairing it with a non-following GET raises
`AttributeError`:

- **prescribed:** `resp = client.get(url)` (no follow) → `assert resp.status_code == 200`; or
- `resp = client.get(url, follow=True)` → `assert resp.redirect_chain == []`.

Use the first unless there is a reason not to; a 302 then fails the status assertion directly.

At least one positive assertion checks the **whole anchor**, not just the URL: `target="_blank"` and
`rel="noopener"` must both be present. The new-tab behaviour is the feature's entire ergonomic
premise — "the walkthrough stays where it is" — so dropping `target="_blank"` would ship green while
silently destroying the reader's place in the course.

**The non-GET render paths.** The claim that one context builder covers N render sites is exactly the
kind of thing that decays silently under refactoring, so each secondary site gets its own assertion —
the response still carries the editor href for the owner:

| Path | Copy the setup from |
|---|---|
| no-JS `check_answer` POST re-render | `tests/test_courses_views.py::test_check_answer_nojs_rerender_includes_unit_nav` (same shape: asserting the shared context survived) |
| no-JS note-validation-error re-render (422) | `tests/test_notes_views.py::test_create_note_invalid_no_js_422_repopulates_rejected_text` |
| no-JS `quiz_answer` re-render (`_quiz_render_feedback`) | **no precedent exists — build it from the recipe below** |

Naming an existing test per row matters: each needs non-trivial fixtures (a `QuestionElement` plus an
acceptable answer body; an **over-length** note body — `"z" * (NOTE_MAX_LEN + 1)` — posted with a real
`element` pk, which is what fails `NoteForm` and triggers the no-JS 422 lesson re-render; an enrolled
manager with a live submission) that are already assembled in those tests. The notes row is worth
describing precisely because a *blank* body is a different validation branch and need not produce the
same 422 re-render shape.

**The `quiz_answer` row has no precedent to copy, and that is a verified absence rather than an
oversight.** Every server-side POST to `quiz_answer` in the suite sends `HTTP_X_REQUESTED_WITH="fetch"`
(`tests/test_quiz_answer.py`, `test_questions_2diii_quiz.py`, `test_questions_2d_results.py`,
`test_questions_2d_quiz_noleak.py`, `test_choice_nudge_paths.py`, `test_quiz_finish.py`,
`test_questions_2diii_results.py`), so every one of them takes the fragment branch and returns at
`courses/views.py:1157` — *before* `_quiz_render_feedback` ever reaches `build_quiz_context` at
`:1161`. The only no-JS quiz flow in the repo is the browser e2e
`tests/test_e2e_quiz.py::test_quiz_no_js_full_flow`, which is not a copyable fixture. So this row —
the one needing the heaviest setup — is also the one with nothing to copy, and the spec must supply
the recipe instead:

- an **enrolled** course owner (`quiz_answer` raises `PermissionDenied` for non-enrolled users, and
  the owner needs the link, so both properties are required of the same actor);
- a quiz unit with a question `Element` (e.g. `ShortTextQuestionElement`);
- then, directly, the POST — **no preparatory GET is required**. `quiz_answer` opens with
  `QuizSubmission.objects.select_for_update().get_or_create(student=request.user, unit=node)`
  (`courses/views.py:1191`), so it creates the `IN_PROGRESS` submission itself; a GET first is
  optional realism, not a precondition, and describing it as one would send an implementer looking
  for a fixture that does not exist.

The POST URL must be written out literally, because the quiz route is **not** the lesson route with
the verb swapped:

```python
client.post(
    f"/courses/{course.slug}/u/{quiz.pk}/quiz/q/{el.pk}/answer/",
    {"answer": "..."},
)   # no HTTP_X_REQUESTED_WITH
```

Note the `quiz/` segment (`courses/urls.py:75`), which the lesson `check/` route (`:40`) does not
carry — the nearest precedent, `test_check_answer_nojs_rerender_includes_unit_nav`, posts to
`/courses/{slug}/u/{pk}/q/{el}/check/`, so pattern-matching off it produces a 404.

**The header's absence is the entire point of the row** and is the single easiest thing to lose when
adapting one of the header-ful tests above: include it and the assertion tests the fragment branch,
which never touches the builder, and the row silently stops guarding anything.

**Falsifying these three needs its own mutation — the page-render mutations do not work here.** The
two mutations named above (invert the predicate, delete the template guard) both redden the plain GET
tests as well, so seeing RED after either one proves nothing about the property these three rows
actually guard: that the merge lives in the **shared builder** and not in the individual view. The
falsification must therefore be *relocation*, and the green half of the result is as load-bearing as
the red half:

| Mutation | Must go RED | Must stay GREEN |
|---|---|---|
| Move the `unit_edit_context` merge out of `full_lesson_render_context` and into the `lesson_unit` view | `check_answer` row, notes-422 row | `lesson_unit` GET |
| Move the merge out of `build_quiz_context` and into the `quiz_unit` view | `quiz_answer` row | `quiz_unit` GET |

If the GET test also goes red, the mutation was applied wrongly (the merge was deleted rather than
relocated) and the falsification does not count. `quiz_results` builds its context locally and has no
shared-builder property to guard, which is why it has no row here.

**Every copy needs the same adaptation:** the course must end up with `owner=<the acting user>`.
`CourseFactory` declares no `owner`, so it defaults to `None`, and all three precedent tests build a
plain `CourseFactory()` and merely *enroll* the actor. Copied verbatim, `can_manage_course` returns
`False` (its `owner_id is not None` guard fails and the actor holds no `courses.change_course`), the
prescribed positive assertion fails, and the implementer has no stated cause. Keep the enrollment the
copied fixture already carries — `check_answer` and the notes path do not require it, but
`quiz_answer` does. The 422 row matters most in practice — that is
a page a manager hits precisely while annotating during the walkthrough this feature serves.

**It is not literally a one-line edit in two of the three copies, because of fixture ordering.**
`CourseFactory(owner=user)` needs the user to exist first, and in two precedents it does not:

- `test_check_answer_nojs_rerender_includes_unit_nav` builds `course = CourseFactory()` first and
  only creates the actor ~25 lines later with `make_login(client, "njs")`.
- `test_create_note_invalid_no_js_422_repopulates_rejected_text` builds the course first by
  necessity — its actor comes from `_enrolled_user(course)`, which takes the course as an argument.

For those two, either hoist the actor's creation above `CourseFactory(owner=…)`, or leave the order
alone and assign afterwards (`course.owner = user; course.save()`). Only the e2e copy — where the
user genuinely precedes the course — is a true one-liner. Flagging this matters because an
implementer who tries the drop-in edit hits a `NameError` or a not-yet-existent user and has no
stated cause.

**The `min-width: 0` guard.** A pre-ship screenshot is not re-run by CI, so the load-bearing
declaration gets a cheap static assertion in `tests/test_consumption_css.py`, following the existing
precedent there (`test_uploaded_video_is_constrained_to_its_container` regex-extracts a rule block
from `courses.css` and asserts on its declarations): assert the `.unit-strip .unit-tags` block exists
and contains `min-width: 0`, with a comment naming the `<fieldset>` hazard so a future deleter sees
why it is there.

**The containment contract** — the server-side guard that the link is a *sibling* of the panel, not
a child of it. This must be asserted **on the full unit page**, not on the tag fragment, and the
reason is worth pinning down because the obvious formulation is unfalsifiable:

`tags/views.py::_panel_response` builds its context from `unit_tags_context(...)` plus
`course` / `unit` / `tag_error` / `tag_draft` — it never carries `can_edit_unit` or
`unit_editor_url`. So if someone moved the anchor into `tags/_unit_tag_panel.html`, the *fragment*
would render `{% if can_edit_unit %}` against a missing variable, emit nothing, and a
"fragment does not contain the href" assertion would stay GREEN through the very regression it
exists to catch. (An unguarded anchor is no better: `{{ unit_editor_url }}` on a missing key renders
`""` via `string_if_invalid`.) By this project's own rule — a test that cannot be made to fail is not
a test — the fragment formulation must be rejected.

The falsifiable form is a **structural containment assertion on the page**, as the course owner
(an actor for whom the link is genuinely present, so the negative is anchored to a proven positive):

1. GET the lesson unit as the owner (plain URL, no `?panel=tags`); assert 200 and that the editor
   href **is** present.
2. Extract the panel's markup with the regex `<details class="unit-tags"[^>]*>.*?</details>` under
   `re.DOTALL`, and **assert the match succeeded** before going further.
3. Assert the editor href does **not** occur inside the matched text.
4. Assert the href **does** occur inside the strip: extract `<div class="unit-strip"[^>]*>.*?</div>`
   under the same `re.DOTALL`, assert *that* match succeeded too, and assert the href is inside it.

Step 4 is not redundant with step 1. Steps 1–3 alone pin only the *negative* half of the sibling
relationship — "not inside the panel" — which stays satisfied if someone moves the anchor out of
`.unit-strip` altogether (below `.unit-shell`, or as a sibling of the strip rather than a child).
That would leave the page containing the href, the panel not containing it, all three steps green,
and the entire flex row the Styling section is built around destroyed. Step 4 pins the positive half,
so the test asserts *both* sides of "sibling of the panel, child of the strip".

(A caveat on step 4's regex, so it is not written naively: `.unit-strip`'s content includes the
panel's own `</div>` tags, so a non-greedy `.*?</div>` stops at the **first** closing tag, not the
strip's. Use index bounds instead — but get their **order** right, because the obvious phrasing is
backwards. In the normative `_unit_strip.html` the anchor is a *following* sibling of
`<details class="unit-tags">`, so the href's index is strictly **greater** than the end of
`</details>`. The assertion is therefore: the href's index falls **after** the end of the panel's
`</details>` and **before** the start of the strip's next top-level sibling in `{% block content %}`
— `<div class="unit-shell"` on the lesson and quiz pages (`_unit_shell.html:2`), and
`<article class="quiz-results` on the results page. Note that results-page literal carefully:
`quiz_results.html:11` renders `<article class="quiz-results result" …>`, so a bound written as
`<article class="result` never matches and `find()` returns `-1`. Prefer a class-order-tolerant regex
(`<article class="[^"]*\bresult\b`) if the assertion is ever extended beyond the lesson page, which
the per-page enumeration here invites. An assertion written the other way round (href *before* `</details>`) fails against correct
markup, and an implementer "fixing" it would reorder the link ahead of the panel, changing both the
approved layout and the reading order. Whichever form is used, keep the match assertion from step 2: a
`find()` returning `-1` must fail loudly, never slice garbage.)

The regex — rather than a literal `<details class="unit-tags">` — is required, not stylistic. The
partial emits `<details class="unit-tags" {% if tags_panel_open %}open{% endif %}>`, so the rendered
markup is always `<details class="unit-tags" >` (note the trailing space) or
`<details class="unit-tags" open>`; the naive literal never matches. Worse, an implementer using
`str.find()` without checking for `-1` would slice a garbage region and step 3 would pass vacuously
in **both** the healthy and the regressed state — which is why step 2's match assertion is mandatory.

The test needs its **own** fixture — an actor built with `make_login(client, …)` (or
`make_verified_user`), plus `CourseFactory(owner=user)` and `ContentNodeFactory`. The actor's
**verified email is a hard requirement, not a detail**: allauth's `AccountMiddleware` enforces
mandatory verification and redirects an unverified session to verify-email before any template
renders, which is exactly why `tests/factories.make_login` uses `make_verified_user` and says so in
its docstring. With a bare `UserFactory()` + `force_login`, step 1's "assert 200 and the href is
present" fails as a redirect, and the test gets misread as broken rather than as guarding something —
the same failure this paragraph warns about, reached by a different route.

It must also not reuse `tests/test_tags_consumption.py`'s `_enrolled(user, …)` helper, which builds a plain
`CourseFactory()` — so the course has **no owner** (`owner=None`) — and merely enrolls the actor. With that helper the actor is not a manager,
step 1 fails, and the whole test is misread as broken rather than as guarding something.

Because the page render *does* carry `can_edit_unit`, moving the anchor into the panel partial makes
step 3 fail immediately — a one-step falsification, which is how this test must be verified before
acceptance.

**e2e (`e2e` marker) — the `replaceWith` trap.** As the owner, on a lesson unit with JS on: assert
the Edit link is present, add a tag through the real form — a real click on the real submit, never
`page.evaluate`, since a test that bypasses the gesture ships broken UX green — then assert the Edit
link is **still** in the DOM.

The wait between those two steps needs a deterministic anchor, and `tags.js` provides none: it swaps
the panel from an un-awaited `fetch(...).then(...)` and leaves behind no marker attribute, status
node, or URL change. So the wait is expressed as a **content** condition on the swapped-in panel —
`expect(page.locator(".unit-tags__chips .tag-chip", has_text=<tag name>)).to_be_visible()`, the same
idiom already used at `tests/test_e2e_tags.py:68` — and only once that passes is the Edit link
asserted. The ordering is load-bearing: asserting the link first would pass even if the swap went on
to destroy it, i.e. green while broken. A bare timeout is not acceptable here.

Both Edit-link assertions use the `.unit-strip__edit` hook — `expect(page.locator(".unit-strip__edit"))
.to_be_visible()` — which is the whole reason that class exists (it carries no styling; see Styling).
Naming it here rather than leaving the locator to the implementer keeps the hook's stated
justification and its actual use in agreement.

Copying that existing flow requires **one change**: it builds `CourseFactory(...)` plus an
`Enrollment`, so its actor is not the course owner and would see no Edit link at all. The copy must
set `owner=user` on the course. No enrollment is needed for the tag-add step — `tags.views.tag_add`
gates on `can_access_course`, which an owner passes.

Run e2e focused and in the **foreground** — a backgrounded `-m e2e` run has previously spawned
runaway browsers.

**Visual verification.** Playwright screenshots checked before shipping, covering **both** rendering
states, because `.unit-strip` now wraps `.unit-tags` for *every* reader — the single-child (student,
no link) case is the far more common one and the one that would regress for the whole user base:

**Every row pins the tag panel's open/closed state**, because the panel is a `<details>` whose flex
base size is its max-content size: the same viewport with the panel open and several tags can wrap the
row exactly like the narrow shots, producing a completely different layout. Leaving the state
unstated would make it undefined which layout the "pinned far right" criterion is judged against.

**How to open it:** load the page with `?panel=tags`. That is the server-side switch the views already
read (`courses/views.py:591` for `lesson_unit`, `:1134` for `quiz_unit`, `:1325` for `quiz_results`),
it renders `<details class="unit-tags" open>` directly, and the existing e2e already uses it.
Closed-panel shots are taken by loading the same URL without the parameter. Do **not** open the panel
by clicking the `<summary>` in Playwright — that adds a disclosure animation to race against for no
benefit, when the state is reachable declaratively.

| Page | Viewport | Actor | Tag panel | light | dark |
|---|---|---|---|---|---|
| `lesson_unit` | desktop | owner (link present) | closed | ✓ | ✓ |
| `lesson_unit` | desktop | enrolled student (link absent) | closed | ✓ | ✓ |
| `lesson_unit` | desktop | owner (link present) | **open** | ✓ | ✓ |
| `lesson_unit` | ~400px | owner, **populated panel** (see below) | **open** | ✓ | ✓ |
| `lesson_unit` | ~400px | enrolled student, **long-token tag** | **open** | ✓ | ✓ |
| `quiz_results` | desktop | owner (link present), **needs a SUBMITTED submission** | closed | ✓ | ✓ |

Which criterion applies to which row:

- **Closed-panel desktop rows** are where "the button is pinned to the far right end of the row,
  sharing the panel's top edge" is judged. The summary is short, the row cannot wrap, and this is the
  approved mockup's state.
- **The open-panel desktop row** exists because opening the panel can push the row into the wrapped
  layout at full width too — not only at 400px. Judge it by whichever criterion its actual layout
  lands in (unwrapped → top-edge; wrapped → flush-left-on-its-own-line).
- **The ~400px owner row** is the wrapped layout, judged by the wrapped-line criterion above,
  including the `.5rem` gap below the strip. It needs the **same populated fixture** as the student
  row below it — several chips and/or a non-empty `addable_tags`. With an empty panel the open
  panel's max-content is barely the text input plus the Add button, comfortably under the ~368px
  column even with the button beside it, so the row would simply not wrap and the shot could not show
  the layout it exists to show. Treat it as a fixture failure, not a pass: **if this shot is not
  wrapped, the fixture is wrong.**
- **The ~400px student row** is a **parity guard**, not a sign-off on a degradation (see "What the
  student actually sees"). It needs a tag label with a 50-character unbroken token so the fieldset's
  min-content actually exceeds the column. Its criterion is two-part, and both halves are required:
  1. the shot is **equivalent to the feature-off baseline** — same panel border box, same sideways
     scroll; and
  2. the prescribed A/B — the same shot with `min-width: 0` deleted from `courses.css` — **differs**.

  Part 2 is what proves the fixture reproduced the hazard at all; part 1 is what proves the
  declaration does its job. A run where both shots are identical means the fixture failed, not that
  the declaration is unnecessary.

  **How to produce the "feature-off baseline" — do not check out master.** The shot depends on a
  fixture (an actor with several owned tags, one a 50-character unbroken token, loaded with
  `?panel=tags`) that exists only on this branch; checking out master discards the fixture code and
  there is nothing left to shoot. Undo the feature's *rendering* instead, in place: revert the three
  `{% include "courses/_unit_strip.html" %}` lines to `{% include "tags/_unit_tag_panel.html" %}` and
  remove the two `.unit-strip*` rules from `courses.css`, take the shot, then restore. That yields
  master's rendering with this branch's fixture — the only combination that makes the comparison
  meaningful. The same procedure produces the baseline for the general "no horizontal overflow beyond
  the master baseline" criterion, which otherwise has no runnable definition either.
- **The `quiz_results` row needs the same submission fixture the `quiz_results` *tests* need**, and it
  fails silently without it. That view (`courses/views.py:1289`) filters `QuizSubmission` by
  `student=request.user, status=SUBMITTED` and **redirects to `quiz_unit`** when the actor has none —
  and the owner, being non-enrolled, never accumulates one naturally. The shot would then capture
  `quiz_unit`, which renders the same strip and looks entirely plausible, while the one property this
  row exists to check (the 736px `.result` under a 920px strip) goes unverified. Build it with
  `QuizSubmissionFactory(student=<owner>, unit=<the quiz node>, status=QuizSubmission.Status.SUBMITTED)`
  and **confirm the captured URL is the results path**, not a redirect target. The spec already spells
  this trap out for the tests; the screenshot is just as exposed to it.

**`quiz_unit` is deliberately not screenshotted.** It is one of the three edited templates, so its
absence is a decision rather than an oversight: its strip heads `.unit-shell` at the same clamped
920px as `lesson_unit`'s, so every layout property the shots examine is already covered by the
`lesson_unit` rows. `quiz_results` earns a row of its own only because `.result` is narrower and
produces the overhang discussed next.

Naming the page matters, and `quiz_results` is not redundant with the lesson rows. `.app-main` is
`max-width: 960px` with `var(--space-5)` (20px) inline padding; `box-sizing: border-box` is global,
so the content box is 960 − 2×20 = **920px**. On
`lesson_unit`/`quiz_unit` the strip heads `.unit-shell`, whose `max-width: 72rem` is always clamped by
that, so the two are the same width. On `quiz_results` it heads `.result`, which is
`max-width: 46rem; margin-inline: auto` — **736px** — so the strip, and with it the right-pinned
button, overhangs the article it heads by about **90px per side**.

**This overhang is pre-recorded as accepted, not as a pass/fail gate**, because it is certain rather
than hypothetical and it is not new: the tag panel already spans the full 920px above that same 736px
article on master today. The button simply sits at the panel's right edge, where the panel's own
border already is. The screenshot row exists to confirm that reads as deliberate rather than broken —
if a human judges otherwise, that is a follow-up styling decision, not a blocker for this change. No
`.quiz-results-page` hook is invented for it: no such class exists, `quiz_results.html` overrides
neither `body_class` nor `main_class`, and the strip is a preceding *sibling* of the article, so
constraining it would require a fourth template edit and would break the "each template changes
exactly one line" property for no proven gain.

General acceptance criteria: the button shares the tag panel's top edge and does not overlap it; the
panel's right border edge sits within the content column at ~400px with the panel open; there is
`.5rem` of separation below the strip in the **wrapped** narrow layout, exactly as today; no
horizontal overflow **beyond the master baseline** for the same page; and the student view is
visually equivalent to today's vertical rhythm.

**The margin relocation gets the same CI guard as `min-width: 0`.** The argument for guarding one
applies verbatim to the other: `margin-block: .5rem` on `.unit-strip` and `margin-block: 0` on
`.unit-strip .unit-tags` are jointly load-bearing — deleting them reintroduces both the ~8px top-edge
misalignment and the 0px gap before `.unit-shell` in the wrapped layout — and a screenshot a human
looks at once does not stop that from silently returning later. Extend the same
`tests/test_consumption_css.py` assertion to cover both extracted rule blocks, with a comment naming
the wrapped-layout gap. The narrow shots are taken with the panel open
deliberately — closed, the summary is short enough that the row will not wrap and the shot would prove
nothing.

The narrow-viewport fixture must also give the actor **several owned tags not yet on the unit**, at
least one with a long label, so `addable_tags` is non-empty and the `<fieldset class="unit-tags__picker">`
actually renders. Without it the shot contains no fieldset, exhibits no min-content blowout, and would
look identical with `min-width: 0` deleted.

**i18n.** Two new msgids — `Edit unit` and `(opens in a new tab)` — regenerated into both catalogs via
`uv run python manage.py makemessages -l pl -l en --no-obsolete`. The two catalogs are **not**
symmetric, and `tests/test_i18n_po_health.py` enforces the asymmetry: every PL entry needs a non-empty
`msgstr` (`test_pl_has_no_untranslated_msgid`), while EN `msgstr`s are intentionally left blank.
So the EN entries stay empty by design, and PL gets real translations, following the catalog's
existing house terms (`Unit` → `Jednostka`, `Edit` → `Edytuj`):

- `Edit unit` → `Edytuj jednostkę`
- `(opens in a new tab)` → `(otwiera się w nowej karcie)`

**A per-feature i18n test, following the repo's own precedent.** Catalog health
(`test_i18n_po_health.py`) proves only that the PL `msgstr` is non-empty — not that the template
actually routes the label through `{% trans %}`, nor that the Polish string reaches the rendered page.
Add both halves to `tests/test_unit_edit_link.py`:

1. **Catalog level.** The common repo pattern — 13 of the 17 `tests/test_i18n_*.py` files are exactly
   this, e.g. `tests/test_i18n_stepper.py`: for each of the two new msgids,
   `with translation.override("pl"): assert translation.gettext(msgid) != msgid`.
2. **Render level** — the half catalog health cannot cover, and the *rarer* pattern: only four
   `test_i18n_*` files issue a request at all (`test_i18n_catalog.py`, `test_i18n_error_pages.py`,
   `test_i18n_quiz.py`, `test_i18n_results.py`). GET the lesson unit as the owner in Polish and assert
   `Edytuj jednostkę` appears in the response body. This is what fails if the template ships the label
   as a bare literal instead of `{% trans %}`.

**Activating Polish takes more than `translation.override` — this is the part that will silently
fail.** `config/settings/base.py:48` installs `core.middleware.SessionLocaleMiddleware`, which
**re-activates a language per request** from the session's `_language` key / `Accept-Language`,
discarding whatever the test process activated ambiently. `LANGUAGE_CODE = "en"`, and the root
`conftest.py` autouse fixture re-activates it before every test. So a bare
`with translation.override("pl"): client.get(...)` renders **English**, the assertion is red from the
start, and the prescribed falsification proves nothing because it was already failing.

Copy `tests/test_i18n_quiz.py::test_quiz_finish_label_translated_pl` — the closest precedent (a
logged-in unit-page GET asserting a PL string). It sets all three:

```python
session = client.session
session["_language"] = "pl"
session.save()
with translation.override("pl"):
    resp = client.get(url, HTTP_ACCEPT_LANGUAGE="pl")
```

The `conftest.py` autouse fixture resets the active language afterwards, so nothing leaks into
neighbouring tests.

Falsify the render half by removing the `{% trans %}` wrapper (the body then carries the English
literal and the assertion goes RED) — but only **after** confirming it is green with the activation
above. Do not falsify it by emptying the catalog, which would redden the catalog half too and prove
nothing about the template.

**`compilemessages` is required, not optional.** `locale/en/LC_MESSAGES/django.mo` and
`locale/pl/LC_MESSAGES/django.mo` are both **tracked in git**, and Django reads `.mo` at runtime — so
`makemessages` plus hand-written Polish `msgstr`s would ship a stale binary catalog and the Polish
strings above would simply never render. `uv run python manage.py compilemessages` is the mandatory
third step (`docs/development/conventions.md:50`), and the regenerated `.mo` files are **part of the
commit**.

Two standing hazards:
`makemessages` can pre-fill a new msgid with a **fuzzy** translation lifted from an unrelated string,
so each new entry's Polish text must be read and corrected, and clearing a fuzzy means deleting
**both** the `#, fuzzy` line and the `#| msgid` line above it. The project forbids obsolete `#~`
entries; `tests/test_i18n_po_health.py` guards the catalogs and must stay green.

**Suite-level.** `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`,
`uv run python manage.py compilemessages`, and `uv run python manage.py makemigrations --check` all
clean. Note that bash `pytest` / `ruff` /
`python` are not on PATH in this environment — every invocation goes through `uv run`.
