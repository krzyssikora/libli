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
every call site (all three views are `@login_required` and resolve their node with
`get_node_or_404(..., require_unit=True)`), so the helper does not defend against either. Behaviour
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

`from courses.rendering import unit_edit_context` goes at **module top level** in `courses/views.py`.
The neighbouring `unit_tags_context` / `lesson_notes_context` merges use function-local imports
carrying a `# lazy: avoid import cycle` comment, and copying that style here would be cargo-culting:
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
      {% trans "Edit unit" %}<span class="visually-hidden"> {% trans "(opens in a new tab)" %}</span>
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
  new-tab jump is announced rather than surprising. **The code block above is the normative markup**
  — note the space *inside* the span, before the parenthetical, which keeps a screen reader from
  running "unit" and "(opens" together. `.visually-hidden` is defined globally in
  `core/static/core/css/app.css` and needs no per-page CSS.

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
3. The link-absent (student) case stays pixel-identical: the panel's `.5rem` block margin is simply
   relocated to its wrapper.

`.unit-strip__edit` therefore carries **no styling at all**. It exists solely as a stable selector
hook for the view tests and the e2e, and is documented as such so it does not read as an undefined
class.

**Horizontal placement is intentional.** `flex: 1 1 auto` on the panel makes it take the remaining
width, which pins the button to the **far right end of the row** — adjacent to the row's edge, not to
the "Tags (n)" summary text. That is the approved mockup, and it is also what keeps the link-absent
(student) case pixel-identical to today: a lone `flex: 1 1 auto` item fills the row exactly as the
block-level panel does now. The acceptance criterion is therefore that the button **shares the tag
panel's top edge**, not that it sits beside the summary.

`min-width: 0` is not boilerplate — it is the fix for a hazard this repo has already been bitten by.
A flex item's automatic minimum size is its min-content size, and `tags/_unit_tag_panel.html` renders
a `<fieldset class="unit-tags__picker">` inside the panel. The UA stylesheet's
`min-inline-size: min-content` on `<fieldset>` inflates that min-content size to the widest label row,
so without `min-width: 0` the panel's used width is floored at that inflated min-content size.

Be precise about what that does and does not change, because the intuitive story is wrong. It is
**not** about wrapping: flex line-breaking is decided from each item's outer *hypothetical* main size,
and with `flex-wrap: wrap` the button moves to a second line whenever the panel's content plus the
button exceeds the container — identically with or without this declaration. What the declaration
buys is that once the panel is alone on a shrunk line, its **own border box** can shrink to that
line's width instead of staying floored at min-content. Without it, the panel's border, background
and rounded corners extend past the content column.

That is the observable: at ~400px with the panel open, **the panel's right border edge lines up with
the content column's right edge** rather than running past it. The acceptance criterion is stated in
those terms, because it is the only thing that actually distinguishes the declaration's presence from
its absence.

**What it does not buy, stated plainly so the acceptance criteria stay honest.** `min-width: 0`
defeats the automatic minimum of the *flex item* (`.unit-tags`). It does nothing about the UA
`min-inline-size: min-content` on the `<fieldset>` itself, nor about `.unit-tags__add`'s own
`min-width: auto` floor (it is `display: flex` too). So a sufficiently wide unbreakable token in a tag
label can still push the fieldset past the `<details>` box — which has no `overflow` clipping — and
scroll the page sideways, *with this fix fully in place*.

That overflow is **pre-existing and out of scope**: `.unit-tags` is full-container-width today, so the
same label overflows the same way on master. This feature does not make it worse (when the row wraps,
the panel is full width again, exactly as now). Cutting the chain properly would mean adding
`min-inline-size: 0` to `.unit-tags__picker` and `min-width: 0` to `.unit-tags__add` — a one-line-each
fix to the tags panel's internals that changes rendering for every reader, including those who never
see this link. That is a separate concern from "add an edit link" and is deliberately not bundled
here.

The acceptance criterion is therefore about the **panel's border box**, not the page: its right edge
sits within the content column at ~400px with the panel open, and the page shows no horizontal
overflow **beyond what the same page shows on master without the feature** (compare against a
baseline shot; do not assert an absolute).

That fieldset is itself conditional — `{% if addable_tags %}` — so it renders only when the actor
owns at least one tag *not already on this unit*. Any test or screenshot meant to exercise this
hazard must therefore be set up with `addable_tags` non-empty. The "long label" must be a **single
unbroken token** (a ~40–50 character run with no spaces, within the model's `maxlength=50`):
`.unit-tags__picker label` is `inline-flex` around plain text, so its min-content size is the longest
*unbreakable* token, not the label's length — a 50-character label of ordinary words simply wraps and
contributes nothing, leaving the shot identical with `min-width: 0` deleted.

Because that declaration is load-bearing but otherwise guarded only by a human looking at a
screenshot, it also gets a cheap automated guard — see Testing.

The new rule deliberately does **not** restate a margin. `.unit-tags` keeps its own `margin: .5rem 0`
from `tags/css/tags.css`, untouched — flex items' margins do not collapse, so that margin still
produces exactly the vertical rhythm the three pages have today, and a later change in `tags.css`
carries through rather than being silently overridden here.

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
page-rendering groups and the two non-GET path assertions — the feature's own module. The
fragment-contract test belongs in the existing `tests/test_tags_consumption.py`, beside the tags
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
page-level test must `assert resp.status_code == 200` **before** asserting on the body.

**Unit — `unit_edit_context` (the permission matrix).** The negative rows are the point of the
feature, so they are tested at least as carefully as the positive ones:

| Actor | `can_edit_unit` |
|---|---|
| Course owner | `True` |
| Platform Admin (holds `courses.change_course`), non-owner | `True` |
| **Course Admin (`make_ca`), non-owner, enrolled** | **`False`** |
| **Course Admin (`make_ca`) who owns the course** | **`True`** |
| Group teacher with `can_access_course` on the course, non-owner | `False` |
| Enrolled student | `False` |

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
(also 200 — see the trap above) does not. `quiz_unit` redirects to `quiz_results` once a submission is
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
wrong page. Each quiz-results test must therefore assert it actually landed on `quiz_results`
(`follow=False` and a 200, or `resp.redirect_chain == []`) before asserting on the body.

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
| no-JS `quiz_answer` re-render (`_quiz_render_feedback`) | any no-JS quiz-answer case; the actor must be an **enrolled** owner, since `quiz_answer` refuses non-enrolled users |

Naming an existing test per row matters: each needs non-trivial fixtures (a `QuestionElement` plus an
acceptable answer body; a blank note POST that fails `NoteForm`; an enrolled manager with a live
submission) that are already assembled in those tests.

**Every copy needs the same one-line adaptation:** set `owner=<the acting user>` on the course.
`CourseFactory` declares no `owner`, so it defaults to `None`, and all three precedent tests build a
plain `CourseFactory()` and merely *enroll* the actor. Copied verbatim, `can_manage_course` returns
`False` (its `owner_id is not None` guard fails and the actor holds no `courses.change_course`), the
prescribed positive assertion fails, and the implementer has no stated cause. Keep the enrollment the
copied fixture already carries — `check_answer` and the notes path do not require it, but
`quiz_answer` does. The 422 row matters most in practice — that is
a page a manager hits precisely while annotating during the walkthrough this feature serves.

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

The regex — rather than a literal `<details class="unit-tags">` — is required, not stylistic. The
partial emits `<details class="unit-tags" {% if tags_panel_open %}open{% endif %}>`, so the rendered
markup is always `<details class="unit-tags" >` (note the trailing space) or
`<details class="unit-tags" open>`; the naive literal never matches. Worse, an implementer using
`str.find()` without checking for `-1` would slice a garbage region and step 3 would pass vacuously
in **both** the healthy and the regressed state — which is why step 2's match assertion is mandatory.

The test needs its **own** fixture — `CourseFactory(owner=user)` plus `ContentNodeFactory` — and must
not reuse `tests/test_tags_consumption.py`'s `_enrolled(user, …)` helper, which creates a course with
a factory-generated owner and merely enrolls the actor. With that helper the actor is not a manager,
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

Copying that existing flow requires **one change**: it builds `CourseFactory(...)` plus an
`Enrollment`, so its actor is not the course owner and would see no Edit link at all. The copy must
set `owner=user` on the course. No enrollment is needed for the tag-add step — `tags.views.tag_add`
gates on `can_access_course`, which an owner passes.

Run e2e focused and in the **foreground** — a backgrounded `-m e2e` run has previously spawned
runaway browsers.

**Visual verification.** Playwright screenshots checked before shipping, covering **both** rendering
states, because `.unit-strip` now wraps `.unit-tags` for *every* reader — the single-child (student,
no link) case is the far more common one and the one that would regress for the whole user base:

| Page | State | light | dark |
|---|---|---|---|
| `lesson_unit`, desktop | owner (link present) | ✓ | ✓ |
| `lesson_unit`, desktop | enrolled student (link absent) | ✓ | ✓ |
| `lesson_unit`, ~400px | owner, **tag panel open** | ✓ | ✓ |
| `lesson_unit`, ~400px | enrolled student | ✓ | ✓ |
| `quiz_results`, desktop | owner (link present) | ✓ | ✓ |

Naming the page matters, and `quiz_results` is not redundant with the lesson rows: the strip sits
above `.unit-shell` (`max-width: 72rem`, effectively the full `.app-main` column) on
`lesson_unit`/`quiz_unit`, but above `.result` (`max-width: 46rem; margin-inline: auto`) on
`quiz_results`. The strip keeps the full column width there, so the right-pinned button lands well
outside the narrower article it heads — a composition four lesson shots would never reveal. (The tag
panel already has this geometry today; the point is to confirm the button does not make it read as
broken.)

That row gets its own pass/fail criterion, since the general ones below are all satisfied no matter
how far outside the article the button sits: **the button's right edge must fall within the
article's right edge, or the mismatch must be explicitly judged acceptable and recorded in the PR.**
If it fails, the named remedy is to constrain the strip on that page only —
`.quiz-results-page .unit-strip { max-width: 46rem; margin-inline: auto; }` or equivalent — rather
than restyling the button.

General acceptance criteria: the button shares the tag panel's top edge and does not overlap it; the
panel's right border edge sits within the content column at ~400px with the panel open; there is
`.5rem` of separation below the strip in the **wrapped** narrow layout, exactly as today; no
horizontal overflow **beyond the master baseline** for the same page; and the student view is
visually equivalent to today's vertical rhythm. The narrow shots are taken with the panel open
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
