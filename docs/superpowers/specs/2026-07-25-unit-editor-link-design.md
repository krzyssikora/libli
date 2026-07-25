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
  context here. Merging in the view instead would silently drop the link the moment a manager
  answered a quiz question with JS off.
- **`quiz_results`** (`courses/views.py:1284`) — a single render site with a locally-built context;
  merge next to its existing `unit_tags_context` merge.

Merging the whole dict (rather than setting `ctx["can_edit_unit"]` by hand at each site) keeps the
three sites from drifting if the helper ever returns a third key.

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
- Visible label `{% trans "Edit unit" %}`, plus
  `<span class="visually-hidden">{% trans "(opens in a new tab)" %}</span>` so the new-tab jump is
  announced rather than surprising. `.visually-hidden` is defined globally in
  `core/static/core/css/app.css` and needs no per-page CSS.

### Styling

In `courses/static/courses/css/courses.css` — all three templates already load it, so no new `<link>`
anywhere:

```css
.unit-strip { display: flex; flex-wrap: wrap; gap: .5rem; align-items: flex-start; }
.unit-strip .unit-tags { flex: 1 1 auto; min-width: 0; }
```

`min-width: 0` is not boilerplate — it is the fix for a hazard this repo has already been bitten by.
A flex item's automatic minimum size is its min-content size, and `tags/_unit_tag_panel.html` renders
a `<fieldset class="unit-tags__picker">` inside the panel. The UA stylesheet's
`min-inline-size: min-content` on `<fieldset>` inflates that min-content size to the widest label row,
so with the panel **open** on a narrow viewport the strip would overflow horizontally instead of
wrapping. `min-width: 0` lets the item shrink and the row wrap as intended.

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
look. The e2e goes in the existing e2e tags module if one exists, otherwise
`tests/test_e2e_unit_edit_link.py`.

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
| Group teacher with `can_access_course` on the course, non-owner | `False` |
| Enrolled student | `False` |

The teacher row must be built so the actor genuinely passes `can_access_course` (a `GroupFactory`
group on the course, actor in `group.teachers`, `archived=False`) — otherwise it degrades into a
duplicate of the student row and stops guarding anything. A positive row also asserts
`unit_editor_url` equals the reversed `courses:manage_editor` URL, and a negative row asserts it is
`None`.

**View rendering — all three pages.** For each of `lesson_unit`, `quiz_unit` and `quiz_results`: the
owner's response (200) contains the editor href, and an **enrolled** non-managing viewer's response
(also 200 — see the trap above) does not. `quiz_unit` redirects to `quiz_results` once a submission is
SUBMITTED, so the quiz-results case needs a submitted `QuizSubmission` (`QuizSubmissionFactory`) for
whichever actor is being tested, and the quiz-unit case must have none.

At least one positive assertion checks the **whole anchor**, not just the URL: `target="_blank"` and
`rel="noopener"` must both be present. The new-tab behaviour is the feature's entire ergonomic
premise — "the walkthrough stays where it is" — so dropping `target="_blank"` would ship green while
silently destroying the reader's place in the course.

**The two non-GET lesson render paths.** The claim that `full_lesson_render_context` covers three
paths is true today and nothing pins it, so one assertion each: a no-JS `check_answer` POST response
and a no-JS note-validation-error re-render (status 422, `notes/views.py:194`) each still carry the
editor href for the owner. The 422 one matters most in practice — it is a page a manager hits
precisely while annotating during the walkthrough this feature serves.

**The fragment contract.** `tags/views.py::tag_add` returns `_panel_response`'s panel-only fragment
**only** when `_wants_fragment(request)` is true, i.e. when the request carries
`X-Requested-With: fetch`; a plain no-JS POST instead returns a 302 redirect with an empty body.
The test must therefore POST to `tags:tag_add` **with `HTTP_X_REQUESTED_WITH="fetch"`**, assert a 200,
and assert the body contains `unit-tags` but **not** the editor href. Posting without that header
would make the assertion trivially true regardless of where the link lives — unfalsifiable, and
useless as the guard it is meant to be. Falsify it explicitly: temporarily move the link inside
`tags/_unit_tag_panel.html` and confirm this test goes RED.

**e2e (`e2e` marker) — the `replaceWith` trap.** As the owner, on a lesson unit with JS on: assert
the Edit link is present, add a tag through the real form — a real click on the real submit, never
`page.evaluate`, since a test that bypasses the gesture ships broken UX green — then assert the Edit
link is **still** in the DOM.

The wait between those two steps needs a deterministic anchor, and `tags.js` provides none: it swaps
the panel from an un-awaited `fetch(...).then(...)` and leaves behind no marker attribute, status
node, or URL change. So the wait is expressed as a **content** condition on the swapped-in panel —
`expect(page.locator(".unit-tags__chips")).to_contain_text(<tag name>)` — and only once that passes is
the Edit link asserted. The ordering is load-bearing: asserting the link first would pass even if the
swap went on to destroy it, i.e. green while broken. A bare timeout is not acceptable here.

Run e2e focused and in the **foreground** — a backgrounded `-m e2e` run has previously spawned
runaway browsers.

**Visual verification.** Playwright screenshots checked before shipping, covering **both** rendering
states, because `.unit-strip` now wraps `.unit-tags` for *every* reader — the single-child (student,
no link) case is the far more common one and the one that would regress for the whole user base:

| | light | dark |
|---|---|---|
| desktop, owner (link present) | ✓ | ✓ |
| desktop, enrolled student (link absent) | ✓ | ✓ |
| ~400px, owner, **tag panel open** | ✓ | ✓ |
| ~400px, enrolled student | ✓ | ✓ |

Acceptance criteria: the link aligns with the tag summary and does not overlap it; at ~400px with the
panel open the page has **no horizontal overflow** (the `min-width: 0` fix working); and the student
view is visually equivalent to today's vertical rhythm. The narrow shots are taken with the panel open
deliberately — closed, the summary is short enough that the row will not wrap and the shot would prove
nothing.

**i18n.** Two new msgids — `Edit unit` and `(opens in a new tab)` — added to both the EN and PL
catalogs via `uv run python manage.py makemessages -l pl -l en --no-obsolete`. Two standing hazards:
`makemessages` can pre-fill a new msgid with a **fuzzy** translation lifted from an unrelated string,
so each new entry's Polish text must be read and corrected, and clearing a fuzzy means deleting
**both** the `#, fuzzy` line and the `#| msgid` line above it. The project forbids obsolete `#~`
entries; `tests/test_i18n_po_health.py` guards the catalogs and must stay green.

**Suite-level.** `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, and
`uv run python manage.py makemigrations --check` all clean. Note that bash `pytest` / `ruff` /
`python` are not on PATH in this environment — every invocation goes through `uv run`.
