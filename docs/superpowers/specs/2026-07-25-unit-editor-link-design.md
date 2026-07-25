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

## Architecture / components

Three pieces, each mirroring a pattern the repo already uses.

### 1. `courses/rendering.py` — new module, one function

```python
def unit_edit_context(user, unit):
    """Context for the unit-page editor link: `can_edit_unit` plus the resolved URL."""
```

Returns `{"can_edit_unit": bool, "unit_editor_url": str | None}`.

`can_edit_unit` is `can_manage_course(user, unit.course)` from `courses/access.py` — course owner,
**or** a holder of the `courses.change_course` model permission (the Platform Admin group). That is
the *exact* predicate `courses.views_manage.editor` enforces before serving the editor, so the link
can never appear where following it would 403. Reusing the predicate rather than restating it is the
point: a future change to authoring access moves both together.

Worth stating precisely, because the role names invite a wrong assumption: the **Course Admin** role
group holds `grouping.change_group`, *not* `courses.change_course` (see `institution/roles.py` and
`tests/factories.make_ca`). A CA therefore gets this link through **course ownership**, which is also
how they come to see the course under Groups at all (`grouping/scoping.py` scopes a CA's groups by
`group.course.owner_id == user.id`). PAs get it everywhere via the model permission.

`unit_editor_url` is `reverse("courses:manage_editor", kwargs={"slug": unit.course.slug, "pk": unit.pk})`
when permitted, and `None` otherwise — never a URL the template must guard against emitting.

The module is new but the shape is not: `tags/rendering.py` and `notes/rendering.py` are the same
thing — a thin, request-free context builder that a view merges into its context and a test can call
directly. `courses/access.py` is deliberately left alone; it answers permission questions, and URL
construction is not one.

### 2. Three view call sites (`courses/views.py`)

- `full_lesson_render_context()` — one edit covers three render paths: the `lesson_unit` GET, the
  `check_answer` POST re-render, and the no-JS notes re-render. This function already merges
  `unit_tags_context(...)` and `lesson_notes_context(...)`; `unit_edit_context(user, node)` joins them.
- `quiz_unit` — merges into the context built by `build_quiz_context`.
- `quiz_results` — merges into its locally-built context, next to the existing `unit_tags_context`
  merge.

Merging the whole dict (rather than setting `ctx["can_edit_unit"]` by hand at each site) keeps the
three sites from drifting if the helper ever returns a third key.

### 3. `templates/courses/_unit_strip.html` — new partial

```html
<div class="unit-strip">
  {% include "tags/_unit_tag_panel.html" %}
  {% if can_edit_unit %}<a class="btn btn--ghost btn--small unit-strip__edit" …>{% endif %}
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
  convention is line SVGs, never emoji, so the `✎` from the mockup ships as a path.
- Visible label `{% trans "Edit unit" %}`, plus
  `<span class="visually-hidden">{% trans "(opens in a new tab)" %}</span>` so the new-tab jump is
  announced rather than surprising. `.visually-hidden` is defined globally in
  `core/static/core/css/app.css` and needs no per-page CSS.

### Styling

In `courses/static/courses/css/courses.css` — all three templates already load it, so no new `<link>`
anywhere:

```css
.unit-strip { display: flex; flex-wrap: wrap; gap: .5rem; align-items: flex-start; }
.unit-strip .unit-tags { flex: 1 1 auto; margin-block: .5rem; }
```

`.unit-tags` currently carries its own `margin: .5rem 0` from `tags/css/tags.css`; as a flex item that
margin is preserved deliberately so the strip keeps the vertical rhythm the pages have today. The
link is a plain `.btn.btn--ghost.btn--small`, matching the existing "Start fresh" / "My notes"
affordances. Below roughly 480px the row wraps to two lines rather than crushing the tag summary;
`flex-wrap: wrap` on the container is what delivers that, with no media query needed.

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
- **Permission is fail-closed by construction.** `unit_editor_url` is `None` whenever
  `can_edit_unit` is false, and the template's `{% if %}` means the `None` is never rendered. Even a
  template edited to drop the guard could only emit an empty `href`, never a working link for an
  unauthorized user.
- **Defence in depth is already there.** The editor view re-checks `can_manage_course` itself and
  raises `PermissionDenied`; a hand-typed URL is refused regardless of what any page rendered.
- **The URL cannot silently rot.** `reverse()` raises `NoReverseMatch` at render time if the route
  name or kwargs ever change, so a rename fails loudly in tests rather than shipping a dead link.
- **No migration.** `uv run python manage.py makemigrations --check` must stay clean.

The one realistic regression this design *can* cause is layout: `.unit-strip` wraps an element
(`.unit-tags`) that three pages already position. That is covered by screenshot verification in both
light and dark mode rather than by runtime error handling.

## Testing

Every new test must be **falsified** before it is accepted: delete or invert the thing it guards and
confirm it goes RED. A green test that was never seen to fail proves nothing. Use
`tests/factories.py` role helpers (`make_pa` / `make_ca` / `make_teacher` / `make_student`) and
`tests.factories.TEST_PASSWORD` — never a password literal, which GitGuardian flags.

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

**View rendering — all three pages.** For each of `lesson_unit`, `quiz_unit` and `quiz_results`:
the owner's response contains the editor href, and a non-managing viewer's response does not.
`quiz_unit` redirects to `quiz_results` once a submission is SUBMITTED, so the quiz-results case
needs a submitted `QuizSubmission` for the actor being tested (`QuizSubmissionFactory`), and the
quiz-unit case needs none.

**The fragment contract.** A no-JS tag-add POST to `tags:tag_add` returns
`_panel_response`'s panel-only fragment; assert the edit link is **not** in that response. This is
what keeps the wrapper honest — if someone later moves the link inside the panel, the fragment starts
carrying it and this test fires.

**e2e (`e2e` marker) — the `replaceWith` trap.** As the owner, on a lesson unit with JS on: assert
the Edit link is present, add a tag through the real form (a real click on the real submit, not
`page.evaluate` — a test that bypasses the gesture ships broken UX green), wait for the panel to swap,
then assert the Edit link is **still** in the DOM. This is the only test that can catch the failure
mode the wrapper exists to prevent. Run e2e focused and in the **foreground** — a backgrounded `-m e2e`
run has previously spawned runaway browsers.

**Visual verification.** Playwright screenshots of a lesson unit page in **both** light and dark
mode, at desktop width and at ~400px, checked before shipping: the link aligns with the tag summary,
does not overlap it, and wraps rather than crushes on narrow screens.

**i18n.** Two new msgids — `Edit unit` and `(opens in a new tab)` — added to both the EN and PL
catalogs via `uv run python manage.py makemessages -l pl -l en --no-obsolete`. Two standing hazards:
`makemessages` can pre-fill a new msgid with a **fuzzy** translation lifted from an unrelated string,
so each new entry's Polish text must be read and corrected, and clearing a fuzzy means deleting
**both** the `#, fuzzy` line and the `#| msgid` line above it. The project forbids obsolete `#~`
entries; `tests/test_i18n_po_health.py` guards the catalogs and must stay green.

**Suite-level.** `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, and
`uv run python manage.py makemigrations --check` all clean. Note that bash `pytest` / `ruff` /
`python` are not on PATH in this environment — every invocation goes through `uv run`.
