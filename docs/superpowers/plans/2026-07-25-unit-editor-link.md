# Unit Editor Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Edit unit" link to the three student-facing unit pages, visible only to a user who can actually author the course, opening that unit's editor in a new tab.

**Architecture:** One new request-free context helper (`courses/rendering.py::unit_edit_context`) merged into the two shared context builders plus `quiz_results`' local context; one new template partial (`courses/_unit_strip.html`) that wraps the existing tag panel and adds the link as its *sibling*; two CSS rules. No new view, no new URL, no JS, no migration.

**Tech Stack:** Django 5.2, `uv run` for every tool invocation, pytest + pytest-django, Playwright for e2e, Django i18n (`.po` + tracked `.mo`).

**Spec:** `docs/superpowers/specs/2026-07-25-unit-editor-link-design.md` — read it before starting. It records *why* several non-obvious choices are load-bearing; this plan records *what to type*.

## Global Constraints

- **Every tool invocation goes through `uv run`.** Bare `pytest` / `ruff` / `python` are **not on PATH** in this environment.
- **Work in the worktree** `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/unit-editor-link` on branch `pipeline/unit-editor-link`. Verify with `git branch --show-current` immediately before every commit — a parallel session has previously switched branches underfoot.
- **Never hardcode a password literal.** Use `tests.factories.TEST_PASSWORD`. GitGuardian blocks literals.
- **Every new test must be falsified before acceptance:** break the thing it guards, watch it go RED, restore. A green test never seen to fail proves nothing. Each task below names its specific mutation.
- **No migration is expected.** `uv run python manage.py makemigrations --check` must stay clean.
- **Two new msgids only:** `Edit unit` and `(opens in a new tab)`. PL translations `Edytuj jednostkę` / `(otwiera się w nowej karcie)`. EN `msgstr`s stay **empty by design**; PL must be non-empty (`tests/test_i18n_po_health.py` enforces the asymmetry). Obsolete `#~` entries are forbidden.
- **`.mo` files are tracked in git.** `compilemessages` is mandatory and its output is part of the commit.
- **Icons are inline monochrome `currentColor` line SVGs** with the shared `.icon` class — never emoji, and never a `<use href="#…">` sprite reference (the sprite is included only on manage pages and would render blank here).

---

### Task 1: `unit_edit_context` helper + permission matrix

**Files:**
- Create: `courses/rendering.py`
- Test: `tests/test_unit_edit_link.py`

**Interfaces:**
- Consumes: `courses.access.can_manage_course(user, course) -> bool` (existing).
- Produces: `unit_edit_context(user, unit) -> dict` with exactly two keys — `can_edit_unit: bool` and `unit_editor_url: str | None`. Tasks 2 and 3 rely on both key names verbatim.

**Precondition (do not add defensive code for it):** callers pass an authenticated user and a UNIT `ContentNode`. All six call sites are `@login_required` and resolve their node with `get_node_or_404(..., require_unit=True)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_unit_edit_link.py`.

**Two repo lint rules govern every snippet in this plan** — `pyproject.toml` sets
`[tool.ruff.lint] select = ["E", "F", "I", "UP", "B", "S"]` with
`[tool.ruff.lint.isort] force-single-line = true`:

- **One name per `from … import` line.** A parenthesized multi-name import raises `I001`. Every
  existing test module follows this.
- **88-character lines** (ruff's default `line-length`, and `E` is selected). This is why the fixture
  below is factored into a `_lesson_unit()` helper rather than repeated inline — the inline form is
  90 characters and would fail `ruff check` *and* `ruff format --check` in eleven places.

```python
import pytest
from django.urls import reverse

from courses.rendering import unit_edit_context
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import make_ca
from tests.factories import make_pa
from tests.factories import make_student
from tests.factories import make_teacher


def _lesson_unit(course):
    """A top-level lesson unit. Factored out to keep every call under 88 chars."""
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


@pytest.mark.django_db
def test_owner_without_change_course_perm_gets_the_link(client):
    """Ownership ALONE must grant the link. The actor deliberately holds no
    courses.change_course: built with make_pa this row would pass via the
    permission branch and never exercise `owner_id == user.id`, so deleting the
    ownership check outright would leave it green."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)

    ctx = unit_edit_context(owner, unit)

    assert ctx["can_edit_unit"] is True
    assert ctx["unit_editor_url"] == reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )


@pytest.mark.django_db
def test_platform_admin_non_owner_gets_the_link(client):
    """A PA holds courses.change_course, so the permission branch grants it on
    every course — including one they do not own."""
    pa = make_pa(client, "pa")
    course = CourseFactory()  # owner is None
    unit = _lesson_unit(course)

    ctx = unit_edit_context(pa, unit)

    assert ctx["can_edit_unit"] is True


@pytest.mark.django_db
def test_course_admin_non_owner_does_not_get_the_link(client):
    """THE row this design rests on. The Course Admin role group holds
    grouping.change_group, NOT courses.change_course — so a CA who does not own
    the course gets nothing. Adding courses.change_course to the CA role, or
    broadening the predicate to is_staff, must break here."""
    ca = make_ca(client, "ca")
    course = CourseFactory()
    unit = _lesson_unit(course)
    EnrollmentFactory(student=ca, course=course)

    ctx = unit_edit_context(ca, unit)

    assert ctx["can_edit_unit"] is False
    assert ctx["unit_editor_url"] is None


@pytest.mark.django_db
def test_course_admin_who_owns_the_course_gets_the_link(client):
    """The other half of the pair: a CA reaches this link through OWNERSHIP
    alone, which is also how they come to see the course under Groups at all."""
    ca = make_ca(client, "ca2")
    course = CourseFactory(owner=ca)
    unit = _lesson_unit(course)

    ctx = unit_edit_context(ca, unit)

    assert ctx["can_edit_unit"] is True


@pytest.mark.django_db
def test_group_teacher_with_read_access_does_not_get_the_link(client):
    """Built so the actor genuinely passes can_access_course (non-archived group
    on THIS course, actor in group.teachers). Without that this row degrades into
    a duplicate of the student row and stops guarding anything."""
    teacher = make_teacher(client, "teach")
    course = CourseFactory()
    unit = _lesson_unit(course)
    group = GroupFactory(course=course, archived=False)
    group.teachers.add(teacher)

    ctx = unit_edit_context(teacher, unit)

    assert ctx["can_edit_unit"] is False
    assert ctx["unit_editor_url"] is None


@pytest.mark.django_db
def test_enrolled_student_does_not_get_the_link(client):
    student = make_student(client, "stu")
    course = CourseFactory()
    unit = _lesson_unit(course)
    EnrollmentFactory(student=student, course=course)

    ctx = unit_edit_context(student, unit)

    assert ctx["can_edit_unit"] is False
    assert ctx["unit_editor_url"] is None
```

Note: these tests issue no request but still take `client` — every role helper routes through `_make_role(client, …)` → `make_login(client, username)`, which needs a client. Each row uses a **distinct username** so building several roles cannot collide on `create_user`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_unit_edit_link.py -v`
Expected: a pytest **collection ERROR** (exit code 2, an `ERRORS` section, zero tests collected) —
`ModuleNotFoundError: No module named 'courses.rendering'`. Note this is an error, not a `FAILED`
line: a missing module aborts collection before any test runs.

- [ ] **Step 3: Write the implementation**

Create `courses/rendering.py`:

```python
"""Request-free context builders for the course consumption pages.

Mirrors tags/rendering.py and notes/rendering.py: a thin function a view merges
into its context and a test can call directly, with no request object involved.
"""

from django.urls import reverse

from courses.access import can_manage_course


def unit_edit_context(user, unit):
    """Context for the unit-page editor link: `can_edit_unit` plus the resolved URL.

    Callers pass an authenticated user and a UNIT ContentNode; every call site is
    @login_required and resolves its node with require_unit=True, so this does not
    defend against either. Behaviour on other inputs is unspecified.

    `can_edit_unit` is exactly the predicate courses.views_manage.editor enforces
    before serving the editor, so the link can never appear where following it
    would 403.
    """
    can_edit = can_manage_course(user, unit.course)
    return {
        "can_edit_unit": can_edit,
        "unit_editor_url": (
            reverse(
                "courses:manage_editor",
                kwargs={"slug": unit.course.slug, "pk": unit.pk},
            )
            if can_edit
            else None
        ),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_unit_edit_link.py -v`
Expected: 6 passed

- [ ] **Step 5: Falsify — invert the predicate**

Temporarily change `can_edit = can_manage_course(user, unit.course)` to `can_edit = not can_manage_course(user, unit.course)`.

Run: `uv run pytest tests/test_unit_edit_link.py -v`
Expected: **all 6 FAIL**. If any row still passes, that row is not guarding what it claims — fix it before continuing.

Restore the line.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check courses/rendering.py tests/test_unit_edit_link.py
uv run ruff format --check courses/rendering.py tests/test_unit_edit_link.py
git branch --show-current   # must be pipeline/unit-editor-link
git add courses/rendering.py tests/test_unit_edit_link.py
git commit -m "feat(courses): unit_edit_context helper for the unit-page editor link"
```

---

### Task 2: The strip partial, CSS, merge points, and page rendering

**Files:**
- Create: `templates/courses/_unit_strip.html`
- Modify: `courses/static/courses/css/courses.css` (append two rules + one print rule)
- Modify: `courses/views.py` — `full_lesson_render_context` (~:431), `build_quiz_context` (~:995), `quiz_results` (~:1284), plus a module-level import
- Modify: `templates/courses/lesson_unit.html:53`, `templates/courses/quiz_unit.html:10`, `templates/courses/quiz_results.html:10`
- Test: `tests/test_unit_edit_link.py` (append)

**Interfaces:**
- Consumes: `unit_edit_context(user, unit)` from Task 1.
- Produces: the CSS class `.unit-strip__edit` (a selector hook relied on by Tasks 4, 6 and 7) and the rendered anchor carrying `target="_blank"` and `rel="noopener"`.

**Why the merge goes in `build_quiz_context` and not the `quiz_unit` view:** `quiz_unit.html` is rendered from **two** sites — the `quiz_unit` view (`:1135`) and `_quiz_render_feedback`'s no-JS re-render (`:1170`) — and both build their context in `build_quiz_context`. Merging in the view would leave the second site without `can_edit_unit`. Task 3 asserts this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_unit_edit_link.py` (add `QuizSubmission`, `QuizSubmissionFactory`, `make_quiz_unit` to the imports):

```python
def _editor_href(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


@pytest.mark.django_db
def test_lesson_unit_shows_the_link_to_the_owner(client):
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)

    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/")

    assert resp.status_code == 200
    body = resp.content.decode()
    assert _editor_href(course, unit) in body
    # The whole anchor, not just the URL: the new-tab behaviour IS the feature's
    # ergonomic premise ("the walkthrough stays where it is"), so losing
    # target="_blank" would ship green while destroying the reader's place.
    assert 'target="_blank"' in body
    assert 'rel="noopener"' in body


@pytest.mark.django_db
def test_lesson_unit_hides_the_link_from_an_enrolled_student(client):
    """The actor MUST be enrolled. A bare make_student gets 403 before any
    template renders, and the assertion would then pass for the wrong reason —
    staying green even if the {% if can_edit_unit %} guard were deleted."""
    student = make_student(client, "stu")
    course = CourseFactory()
    unit = _lesson_unit(course)
    EnrollmentFactory(student=student, course=course)

    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/")

    assert resp.status_code == 200
    body = resp.content.decode()
    assert _editor_href(course, unit) not in body
    # Both assertions are required and neither catches the other's mutation:
    # inverting the predicate is caught by the href; deleting the template guard
    # is caught ONLY here, because an unguarded anchor renders href="None",
    # which does not contain the reversed manage_editor URL.
    assert "unit-strip__edit" not in body


@pytest.mark.django_db
def test_quiz_unit_shows_the_link_to_the_owner(client):
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = make_quiz_unit(course=course)

    # No submission for this actor: quiz_unit redirects to quiz_results once one
    # is SUBMITTED.
    resp = client.get(f"/courses/{course.slug}/u/{quiz.pk}/quiz/")

    assert resp.status_code == 200
    assert _editor_href(course, quiz) in resp.content.decode()


@pytest.mark.django_db
def test_quiz_unit_hides_the_link_from_an_enrolled_student(client):
    student = make_student(client, "stu")
    course = CourseFactory()
    quiz = make_quiz_unit(course=course)
    EnrollmentFactory(student=student, course=course)

    resp = client.get(f"/courses/{course.slug}/u/{quiz.pk}/quiz/")

    assert resp.status_code == 200
    body = resp.content.decode()
    assert _editor_href(course, quiz) not in body
    assert "unit-strip__edit" not in body


@pytest.mark.django_db
def test_quiz_results_shows_the_link_to_the_owner(client):
    """quiz_results filters submissions by student=request.user and REDIRECTS to
    quiz_unit when there is none — and the owner, being non-enrolled, never
    accumulates one naturally. All three kwargs are required: the factory
    defaults `unit` to a brand-new quiz unit in a brand-new course, and `status`
    to IN_PROGRESS."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = make_quiz_unit(course=course)
    QuizSubmissionFactory(
        student=owner, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )

    resp = client.get(f"/courses/{course.slug}/u/{quiz.pk}/quiz/results/")

    # Assert we landed on quiz_results, not on a 302 to quiz_unit (which also
    # renders the strip and would pass the body assertion against the wrong page).
    assert resp.status_code == 200
    assert _editor_href(course, quiz) in resp.content.decode()


@pytest.mark.django_db
def test_quiz_results_hides_the_link_from_an_enrolled_student(client):
    student = make_student(client, "stu")
    course = CourseFactory()
    quiz = make_quiz_unit(course=course)
    EnrollmentFactory(student=student, course=course)
    QuizSubmissionFactory(
        student=student, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )

    resp = client.get(f"/courses/{course.slug}/u/{quiz.pk}/quiz/results/")

    assert resp.status_code == 200
    body = resp.content.decode()
    assert _editor_href(course, quiz) not in body
    assert "unit-strip__edit" not in body
```

The file's import block becomes exactly this (one name per line — `force-single-line`; the three new
entries are `QuizSubmission`, `QuizSubmissionFactory`, `make_quiz_unit`, each slotted in isort order):

```python
import pytest
from django.urls import reverse

from courses.models import QuizSubmission
from courses.rendering import unit_edit_context
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import make_ca
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.factories import make_teacher
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_unit_edit_link.py -v -k "shows_the_link or hides_the_link"`
Expected: the three `shows_the_link` tests FAIL (href absent). The three `hides_the_link` tests will *pass* vacuously at this point — that is expected and is why Step 6 falsifies them explicitly.

- [ ] **Step 3: Create the partial**

Create `templates/courses/_unit_strip.html`:

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

This markup is **normative**. Two details are deliberate: the link is a **sibling** of `.unit-tags`, not a child (`tags.js` does `panel.replaceWith(fresh)` on the `.unit-tags` subtree when a tag is added — a link inside it would be silently destroyed, with JS on only, passing every server-side test); and the separator is `&nbsp;`, not a space, because `.visually-hidden` is `position: absolute`, which blockifies the span and strips leading collapsible whitespace.

- [ ] **Step 4: Point the three templates at the partial**

In each file, replace the single line `{% include "tags/_unit_tag_panel.html" %}` with `{% include "courses/_unit_strip.html" %}`:

- `templates/courses/lesson_unit.html:53`
- `templates/courses/quiz_unit.html:10`
- `templates/courses/quiz_results.html:10`

Exactly one line changes per file. Do **not** touch `tags/templates/tags/panel_page.html` — it is explicitly out of scope.

- [ ] **Step 5: Wire the three merge points**

In `courses/views.py`, add at **module top level** (not function-local — `courses/rendering.py` imports only `courses.access` and `django.urls`, both already imported at module level here, so there is no cycle and a `# lazy: avoid import cycle` comment would assert something false).

Placement is not free: the file has a strictly single-line-sorted first-party block, and anywhere else
raises `I001` on Step 10's `ruff check`. `rendering` sorts between `quiz` and `rollups`, so insert it
**immediately after `from courses.quiz import selected_ids` (line 74) and immediately before
`from courses.rollups import build_course_results` (line 75)**:

```python
from courses.quiz import selected_ids
from courses.rendering import unit_edit_context
from courses.rollups import build_course_results
```

(The middle line is the new one; the other two are existing context showing where it goes.)

In `full_lesson_render_context` (~:431), after the existing `ctx.update(unit_tags_context(...))`:

```python
    ctx.update(unit_edit_context(user, node))
```

and extend its docstring. Do **not** do this as an in-place substitution: the target line
(`courses/views.py:433`) is already 84 characters, and inserting the phrase makes it **105**, which
fails E501 on Step 10's `ruff check` (ruff's default `line-length` is 88 and `E` is selected).
Formatters do not rewrap docstring prose, so `ruff format` will not rescue it. Type this rewrapped
block instead, replacing the existing four-line docstring in full:

```python
    """Full context for rendering courses/lesson_unit.html: lesson context +
    unit nav + feedback defaults + the author's notes + tag panel + the
    edit-unit link. Single-sourced so every render site (lesson_unit GET,
    check_answer re-render, notes no-JS re-render) stays consistent."""
```

In `build_quiz_context` (~:995), after the existing `ctx.update(unit_tags_context(user, node, panel_open=False))`:

```python
    ctx.update(unit_edit_context(user, node))
```

and extend its docstring. As with `full_lesson_render_context` above, replace the **whole** docstring
rather than substituting a sentence — its second sentence begins mid-way through line 1, so a
sentence-level substitution leaves that line's ending undefined:

```python
    """Element/render context for a QUIZ unit. Parallels build_lesson_context
    but threads per-question quiz state (responses, locked, attempts_left),
    plus the edit-unit link context."""
```

In `quiz_results` (~:1284), after the existing `ctx.update(unit_tags_context(...))` block:

```python
    ctx.update(unit_edit_context(request.user, node))
```

Merge the **whole dict** at each site rather than setting `ctx["can_edit_unit"]` by hand, so the three sites cannot drift if the helper gains a third key.

- [ ] **Step 6: Add the CSS**

Append to `courses/static/courses/css/courses.css`:

```css
/* Unit strip: the tag panel and the Edit-unit link on one row.
   The strip owns the block rhythm; .unit-tags' own .5rem margin (from tags.css)
   is zeroed inside it so both flex items align on the row's top edge, so no
   hardcoded .5rem is duplicated onto the anchor, and so the .5rem below the
   strip survives the wrapped narrow layout (where .btn has no block-end margin
   and .unit-shell would otherwise start with 0px of separation).
   NOTE: this override wins on SPECIFICITY, not source order — courses.css loads
   BEFORE tags.css, so a bare `.unit-tags` selector here would lose. Keep both
   classes.
   Both .5rem literals are deliberate rather than var(--space-N): they track the
   value in tags.css's `.unit-tags { margin: .5rem 0 }`, which this rule relocates
   and must stay numerically equal to. If that value changes, change these too. */
.unit-strip { display: flex; flex-wrap: wrap; gap: .5rem; align-items: flex-start;
              margin-block: .5rem; }
/* min-width: 0 is load-bearing. Wrapping the panel in a flex container makes it a
   flex item for the first time — on master it is a plain block child of .app-main
   with no automatic minimum. Without this, the UA's `min-inline-size: min-content`
   on <fieldset class="unit-tags__picker"> would floor the panel's border box at
   min-content, inflating its chrome. This RESTORES master's rendering; it does not
   add a behaviour. See the spec's three-state table. */
.unit-strip .unit-tags { flex: 1 1 auto; min-width: 0; margin-block: 0; }

/* An affordance for a second browser tab is noise on paper. */
@media print { .unit-strip__edit { display: none; } }
```

`.unit-strip__edit` carries **no screen styling** — it exists as a stable selector hook for the tests and the e2e, plus this one print rule.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_unit_edit_link.py -v`
Expected: all 12 passed

- [ ] **Step 8: Falsify both mutations**

Each assertion catches a different regression; run both, separately.

*Mutation A — invert the predicate* (`courses/rendering.py`: `can_edit = not can_manage_course(...)`):
Run: `uv run pytest tests/test_unit_edit_link.py -v`
Expected: the three `shows_the_link` tests FAIL **and** the three `hides_the_link` tests FAIL (href now present for the student). Restore.

*Mutation B — delete the template guard* (in `_unit_strip.html`, remove the `{% if can_edit_unit %}` / `{% endif %}` lines, keeping the anchor):
Run: `uv run pytest tests/test_unit_edit_link.py -v -k hides_the_link`
Expected: the three `hides_the_link` tests FAIL on the `unit-strip__edit` assertion — **and not on the href one**, because `unit_editor_url` is `None` so the anchor renders `href="None"`. If they fail on the href assertion instead, re-read the test. Restore.

- [ ] **Step 9: Confirm the four direct `build_quiz_context` callers still pass**

The merge makes `build_quiz_context` perform a permission check, and four unit tests call it directly, bypassing the views. None passes an actor who owns the course or holds `courses.change_course`, so both predicate branches return `False` and `reverse()` is never reached — but confirm rather than assume:

Run: `uv run pytest courses/tests/test_callout_has_math.py tests/test_slideshow_context.py tests/test_tabs_invariant.py tests/test_tags_consumption.py -v`
Expected: all pass

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check courses/ tests/test_unit_edit_link.py
uv run ruff format --check courses/ tests/test_unit_edit_link.py
git branch --show-current
git add templates/courses/_unit_strip.html templates/courses/lesson_unit.html \
        templates/courses/quiz_unit.html templates/courses/quiz_results.html \
        courses/views.py courses/static/courses/css/courses.css \
        tests/test_unit_edit_link.py
git commit -m "feat(courses): Edit unit link on the three unit consumption pages"
```

---

### Task 3: The three non-GET render paths

**Files:**
- Test: `tests/test_unit_edit_link.py` (append)

**Interfaces:**
- Consumes: everything from Task 2.
- Produces: nothing new — these assertions exist solely to pin the "one shared builder covers N render sites" property, which decays silently under refactoring.

Each row copies its fixture from a named precedent. **Every copy needs the course to end up with `owner=<the acting user>`** — all three precedents build a plain `CourseFactory()` (so `owner` is `None`) and merely *enroll* the actor, and copied verbatim the positive assertion fails with no stated cause.

| Path | Copy the setup from | Expected status |
|---|---|---|
| no-JS `check_answer` POST re-render | `tests/test_courses_views.py::test_check_answer_nojs_rerender_includes_unit_nav` | 200 |
| no-JS note-validation re-render | `tests/test_notes_views.py::test_create_note_invalid_no_js_422_repopulates_rejected_text` | **422** |
| no-JS `quiz_answer` re-render | **no precedent exists** — build from the recipe below | 200 |

**Fixture-ordering warning:** `CourseFactory(owner=user)` needs the user to exist first, and in two precedents it does not — `test_check_answer_nojs…` creates the actor ~25 lines after the course, and the notes precedent's actor comes from `_enrolled_user(course)`, which takes the course as an argument. For those two, either hoist the actor's creation above `CourseFactory(owner=…)` or assign afterwards (`course.owner = user; course.save()`).

- [ ] **Step 1: Write the pinning tests**

These are *pinning* tests: they pass as soon as they are written, because Task 2 already wired the
builders. Their red half comes from the relocation mutations in Step 3 — that is what makes them
tests rather than decoration.

Append to `tests/test_unit_edit_link.py`:

```python
@pytest.mark.django_db
def test_check_answer_nojs_rerender_carries_the_link(client):
    """full_lesson_render_context covers the check_answer POST re-render, not just
    the lesson_unit GET. Fixture shape copied from
    tests/test_courses_views.py::test_check_answer_nojs_rerender_includes_unit_nav,
    with owner= added."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)
    q = ShortTextQuestionElement.objects.create(
        stem="2+2?", accepted="4", marking_mode="A", max_marks=1
    )
    el = add_element(unit, q)
    EnrollmentFactory(student=owner, course=course)

    # No X-Requested-With header -> full-page no-JS re-render.
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/q/{el.pk}/check/", {"answer": "5"}
    )

    assert resp.status_code == 200
    assert _editor_href(course, unit) in resp.content.decode()


@pytest.mark.django_db
def test_notes_invalid_nojs_422_rerender_carries_the_link(client):
    """The notes no-JS validation re-render returns 422 BY DESIGN — assert that,
    not 200. This is the path a manager hits while annotating during the very
    walkthrough this feature serves. Fixture shape from test_notes_views.py's
    test_create_note_invalid_no_js_422_repopulates_rejected_text."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)
    el = ElementFactory(unit=unit)
    EnrollmentFactory(student=owner, course=course)

    # Over-cap body (NOT a blank one — that is a different validation branch).
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/notes/add/",
        {"element": el.pk, "body": "z" * (NOTE_MAX_LEN + 1)},
    )

    assert resp.status_code == 422
    assert _editor_href(course, unit) in resp.content.decode()


@pytest.mark.django_db
def test_quiz_answer_nojs_rerender_carries_the_link(client):
    """build_quiz_context covers _quiz_render_feedback's no-JS full re-render, not
    just the quiz_unit GET. No precedent exists to copy: every server-side
    quiz-answer test in the suite sends HTTP_X_REQUESTED_WITH="fetch" and returns
    at the fragment branch before reaching the builder.

    The actor must be an ENROLLED owner — quiz_answer raises PermissionDenied for
    non-enrolled users, and the owner needs the link."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = make_quiz_unit(course=course)
    EnrollmentFactory(student=owner, course=course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Rome", marking_mode="A", max_marks=1
    )
    el = add_element(quiz, q)

    # No preparatory GET needed: quiz_answer get_or_creates the submission itself.
    # Note the `quiz/` URL segment — the lesson `check/` route does NOT carry it,
    # so pattern-matching off the check_answer test above produces a 404.
    # THE ABSENCE OF HTTP_X_REQUESTED_WITH IS THE ENTIRE POINT OF THIS TEST.
    resp = client.post(
        f"/courses/{course.slug}/u/{quiz.pk}/quiz/q/{el.pk}/answer/",
        {"answer": "Paris"},
    )

    assert resp.status_code == 200
    assert _editor_href(course, quiz) in resp.content.decode()
```

The file's import block becomes exactly this — shown in full, as in Task 2, so no isort placement has
to be inferred (`notes.models` sorts after `courses.*` and before `tests.*`; the four new entries are
`ShortTextQuestionElement`, `NOTE_MAX_LEN`, `ElementFactory`, `add_element`):

```python
import pytest
from django.urls import reverse

from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.rendering import unit_edit_context
from notes.models import NOTE_MAX_LEN
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import ElementFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import add_element
from tests.factories import make_ca
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.factories import make_teacher
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `uv run pytest tests/test_unit_edit_link.py -v -k "nojs or 422"`
Expected: 3 passed. (They should pass immediately — Task 2 already wired the builders. These tests exist to *keep* that true.)

If the `quiz_answer` one returns 302 or 403, the actor is not enrolled or the URL is wrong — re-check the `quiz/` segment.

- [ ] **Step 3: Falsify by RELOCATION, not deletion**

The Task-2 mutations do not work here: both also redden the plain GET tests, so seeing RED proves nothing about *where* the merge lives. The mutation must be relocation, and the **green half is as load-bearing as the red half**.

**The relocated line must be rewritten, not moved verbatim.** The builders have a local `user`; the
destination views do not — `lesson_unit` (`courses/views.py:580`) and `quiz_unit` (`:1119`) have only
`request.user` and `node`. Pasting `unit_edit_context(user, node)` into either raises `NameError`,
which makes the GET test *error* rather than stay green — and you would then read that as "the merge
was deleted rather than relocated" and chase a mistake that isn't there.

*Mutation A:* delete `ctx.update(unit_edit_context(user, node))` from `full_lesson_render_context`,
and in `lesson_unit` insert this immediately after the `ctx = full_lesson_render_context(...)` call:

```python
    ctx.update(unit_edit_context(request.user, node))
```

Run: `uv run pytest tests/test_unit_edit_link.py -v`
Expected: `test_check_answer_nojs_rerender_carries_the_link` and `test_notes_invalid_nojs_422_rerender_carries_the_link` **FAIL**, while `test_lesson_unit_shows_the_link_to_the_owner` **still PASSES**. If the GET test errors instead, check you made the `user` → `request.user` change. Restore.

*Mutation B:* delete `ctx.update(unit_edit_context(user, node))` from `build_quiz_context`, and in
`quiz_unit` insert the same line immediately after `ctx = build_quiz_context(node, request.user)`:

```python
    ctx.update(unit_edit_context(request.user, node))
```

Run: `uv run pytest tests/test_unit_edit_link.py -v`
Expected: `test_quiz_answer_nojs_rerender_carries_the_link` **FAILS**, `test_quiz_unit_shows_the_link_to_the_owner` **still PASSES**. Restore.

(`quiz_results` builds its context locally and has no shared-builder property to guard, which is why it has no row here.)

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff check tests/test_unit_edit_link.py
uv run ruff format --check tests/test_unit_edit_link.py
git branch --show-current
git add tests/test_unit_edit_link.py
git commit -m "test(courses): pin the edit link to the shared builders, not the views"
```

---

### Task 4: The containment contract

**Files:**
- Test: `tests/test_tags_consumption.py` (append)

**Interfaces:**
- Consumes: the rendered `.unit-strip` / `.unit-tags` structure from Task 2.
- Produces: nothing.

**Why this must assert on the full page, not the tag fragment.** `tags/views.py::_panel_response` builds its context from `unit_tags_context(...)` plus `course` / `unit` / `tag_error` / `tag_draft` — it never carries `can_edit_unit`. So if someone moved the anchor into `tags/_unit_tag_panel.html`, the *fragment* would render `{% if can_edit_unit %}` against a missing variable, emit nothing, and a "fragment does not contain the href" assertion would stay **green through the very regression it exists to catch**. By this project's own rule — a test that cannot be made to fail is not a test — the fragment formulation is rejected.

- [ ] **Step 1: Write the pinning test**

A pinning test — green on arrival, with its red half supplied by Step 3's mutation.

Append to `tests/test_tags_consumption.py`. Note there is **no `@pytest.mark.django_db` decorator**:
that module already sets `pytestmark = pytest.mark.django_db` at line 11, and every other test in the
file relies on it.

```python
def test_edit_link_is_a_sibling_of_the_tag_panel_not_a_child(client):
    """The Edit link must sit OUTSIDE <details class="unit-tags">.

    tags.js does panel.replaceWith(fresh) on the .unit-tags subtree when a tag is
    added, so a link inside the panel would be silently destroyed the first time
    the user tags a unit — with JS on only, passing every other server-side test.

    Do NOT reuse this module's _enrolled() helper: it builds a plain
    CourseFactory() with no owner, so the actor would not be a manager, step 1
    would fail, and the test would read as broken rather than as guarding
    something.
    """
    import re

    from tests.factories import make_login

    # `reverse`, `ContentNodeFactory` and `CourseFactory` are already imported at
    # the top of this module; `make_login` is not (it imports make_verified_user).

    # make_login (not a bare UserFactory + force_login): allauth's
    # AccountMiddleware enforces mandatory email verification and redirects an
    # unverified session to verify-email BEFORE any template renders.
    user = make_login(client, "containment")
    course = CourseFactory(owner=user)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    href = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})

    # 1. Plain URL, no ?panel=tags. Anchor the negative to a proven positive.
    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert href in body, "editor link absent — the rest of this test is vacuous"

    # 2. Regex, not a literal: the partial emits
    #    <details class="unit-tags" {% if tags_panel_open %}open{% endif %}>,
    #    so the rendered markup is always `class="unit-tags" >` (trailing space)
    #    or `class="unit-tags" open>`. A naive literal never matches, and a
    #    str.find() without a -1 check would slice garbage and pass vacuously in
    #    BOTH the healthy and the regressed state.
    panel = re.search(r'<details class="unit-tags"[^>]*>.*?</details>', body, re.DOTALL)
    assert panel, "could not locate the tag panel in the rendered page"

    # 3. Negative half: the link is not inside the panel.
    assert href not in panel.group(0)

    # 4. Positive half. Without this, moving the anchor out of .unit-strip
    #    entirely (below .unit-shell, or as a sibling of the strip) leaves steps
    #    1-3 green while destroying the flex row.
    #    Order matters and the obvious phrasing is backwards: the anchor FOLLOWS
    #    </details>, so the href's index is GREATER than the panel's end.
    strip_start = body.index('<div class="unit-strip"')
    shell_start = body.index('<div class="unit-shell"')
    assert strip_start < panel.end() <= body.index(href) < shell_start
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/test_tags_consumption.py::test_edit_link_is_a_sibling_of_the_tag_panel_not_a_child -v`
Expected: PASS

- [ ] **Step 3: Falsify — move the anchor into the panel**

Temporarily move the whole `{% if can_edit_unit %}…{% endif %}` block from `templates/courses/_unit_strip.html` into `tags/templates/tags/_unit_tag_panel.html`, inside the `<details>`.

Run: `uv run pytest tests/test_tags_consumption.py::test_edit_link_is_a_sibling_of_the_tag_panel_not_a_child -v`
Expected: **FAIL at step 3** (the href is now inside the panel). This is a one-step falsification — the page render carries `can_edit_unit`, so the anchor really does render there. Restore.

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff check tests/test_tags_consumption.py
uv run ruff format --check tests/test_tags_consumption.py
git branch --show-current
git add tests/test_tags_consumption.py
git commit -m "test(tags): guard the edit link as a sibling of the tag panel"
```

---

### Task 5: CSS regression guard

**Files:**
- Test: `tests/test_consumption_css.py` (append)

**Interfaces:**
- Consumes: the CSS rules added in Task 2.
- Produces: nothing.

A pre-ship screenshot is not re-run by CI, so the two load-bearing declarations get a cheap static assertion. This follows the existing precedent in this file (`test_uploaded_video_is_constrained_to_its_container` regex-extracts a rule block from `courses.css` and asserts on its declarations).

Note what this guard does **not** catch: a specificity-losing rewrite (changing `.unit-strip .unit-tags` to a bare `.unit-tags`) keeps the declarations present while silently losing the cascade to `tags.css`. That reason is recorded in the CSS comment from Task 2.

- [ ] **Step 1: Write the pinning test**

Another pinning test — green on arrival; Step 3's deletion is its red half.

Append to `tests/test_consumption_css.py`:

```python
def test_unit_strip_rules_are_present_and_load_bearing():
    """.unit-strip and .unit-strip .unit-tags carry three jointly load-bearing
    declarations. A screenshot a human looks at once does not stop them silently
    returning later.

    - min-width: 0 — wrapping the panel in a flex container makes it a flex item
      for the first time (on master it is a plain block child of .app-main).
      Without this, the UA's `min-inline-size: min-content` on
      <fieldset class="unit-tags__picker"> floors the panel's border box at
      min-content and inflates its chrome. This RESTORES master's rendering.
    - margin-block on both — deleting them reintroduces the ~8px top-edge
      misalignment AND the 0px gap before .unit-shell in the wrapped layout.
    """
    import re

    css = CSS.read_text(encoding="utf-8")

    strip = re.search(r"\.unit-strip\s*\{([^}]*)\}", css)
    assert strip, ".unit-strip rule missing"
    assert "margin-block" in strip.group(1), (
        f"the strip must own the block rhythm: {strip.group(1)!r}"
    )

    inner = re.search(r"\.unit-strip\s+\.unit-tags\s*\{([^}]*)\}", css)
    assert inner, (
        ".unit-strip .unit-tags rule missing — note the TWO-class selector is "
        "required: courses.css loads before tags.css, so a bare .unit-tags here "
        "would lose the cascade to tags.css's margin: .5rem 0"
    )
    block = inner.group(1)
    assert "min-width: 0" in block, f"min-width: 0 missing (fieldset hazard): {block!r}"
    assert "margin-block: 0" in block, f"margin-block: 0 missing: {block!r}"
    # flex: 1 1 auto is what makes the panel absorb the remaining width, which is
    # what pins the button to the row's FAR RIGHT edge — the single criterion the
    # desktop screenshots exist to judge. Delete it and the panel shrink-wraps its
    # summary, the button lands beside "Tags (n)", and nothing else in CI notices.
    assert "flex: 1 1 auto" in block, f"flex: 1 1 auto missing (right-pin): {block!r}"
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/test_consumption_css.py -v`
Expected: all pass

- [ ] **Step 3: Falsify**

Delete `min-width: 0;` from the `.unit-strip .unit-tags` rule in `courses.css`.
Run: `uv run pytest tests/test_consumption_css.py::test_unit_strip_rules_are_present_and_load_bearing -v`
Expected: FAIL. Restore.

Repeat once per guarded declaration — `margin-block: 0`, `flex: 1 1 auto`, and `margin-block` on
`.unit-strip` — confirming FAIL each time and restoring after each. Four deletions, four REDs: a
guard you never saw fail is not a guard.

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff check tests/test_consumption_css.py
uv run ruff format --check tests/test_consumption_css.py
git branch --show-current
git add tests/test_consumption_css.py
git commit -m "test(css): guard the unit-strip layout declarations"
```

---

### Task 6: i18n — catalogs, translations, and tests

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`
- Modify (generated, tracked): `locale/en/LC_MESSAGES/django.mo`, `locale/pl/LC_MESSAGES/django.mo`
- Test: `tests/test_unit_edit_link.py` (append)

**Interfaces:**
- Consumes: the two `{% trans %}` msgids from Task 2's partial.
- Produces: nothing.

- [ ] **Step 1: Regenerate the catalogs**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

- [ ] **Step 1b: Check the catalogs for collateral churn BEFORE editing them**

```bash
git diff --stat locale/
git diff -U0 locale/ | grep -E '^[+-](msgid|msgstr|#, fuzzy)' | sort | uniq -c
```

These are ~6,300-line catalogs and `makemessages` runs repo-wide: it rewrites every entry's `#:`
location comment, and it can re-flag pre-existing entries as **fuzzy** or, under `--no-obsolete`,
drop entries it considers dead — none of it caused by this change.

**The only `msgid`/`msgstr` content changes may be the two new entries.** Location-comment churn is
expected and fine. Anything else — a newly fuzzy pre-existing entry, a dropped msgid — is collateral:
**revert it, or split it into its own commit. Never ship it silently inside this feature's i18n
commit.** If `test_i18n_po_health.py` goes red on an entry this feature never touched, that is what
happened; do not "fix" it here.

- [ ] **Step 2: Fill in the Polish translations and clear any fuzzy flags**

In `locale/pl/LC_MESSAGES/django.po`:

```po
msgid "Edit unit"
msgstr "Edytuj jednostkę"

msgid "(opens in a new tab)"
msgstr "(otwiera się w nowej karcie)"
```

Follow the catalog's existing house terms (`Unit` → `Jednostka`, `Edit` → `Edytuj`).

**Two standing hazards:**
- `makemessages` can pre-fill a new msgid with a **fuzzy** translation lifted from an unrelated string. Read each new entry and correct it — do not assume a pre-filled `msgstr` is right.
- Clearing a fuzzy means deleting **both** the `#, fuzzy` line **and** the `#| msgid` line above it.

Leave the **EN** `msgstr`s **empty** — that asymmetry is intentional and `tests/test_i18n_po_health.py` enforces it (PL entries must be non-empty; EN are deliberately blank). Do not introduce any `#~` obsolete entries.

- [ ] **Step 3: Compile the catalogs**

```bash
uv run python manage.py compilemessages
```

This is **mandatory, not optional** (`docs/development/conventions.md:50`): both `.mo` files are tracked in git and Django reads `.mo` at runtime, so hand-written `msgstr`s without this step ship a stale binary catalog and the Polish strings simply never render.

- [ ] **Step 4: Write the tests**

Append to `tests/test_unit_edit_link.py` (add `from django.utils import translation` to the imports):

```python
@pytest.mark.parametrize("msgid", ["Edit unit", "(opens in a new tab)"])
def test_pl_translation_present(msgid):
    """Catalog half — the common repo pattern (13 of the 17 tests/test_i18n_*.py
    files are exactly this; cf. tests/test_i18n_stepper.py)."""
    with translation.override("pl"):
        assert translation.gettext(msgid) != msgid


@pytest.mark.django_db
def test_edit_link_label_renders_in_polish(client):
    """Render half — the rarer pattern (only 4 test_i18n_* files issue a request).
    Catalog health cannot prove the template routes the label through {% trans %}
    or that the Polish string reaches the page.

    translation.override ALONE renders English: SessionLocaleMiddleware
    re-activates a language per request from the session key / Accept-Language,
    discarding whatever the test process activated, and conftest.py pins en before
    every test. All three activations below are required — copied from
    tests/test_i18n_quiz.py::test_quiz_finish_label_translated_pl.
    """
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)

    session = client.session
    session["_language"] = "pl"
    session.save()
    with translation.override("pl"):
        resp = client.get(
            f"/courses/{course.slug}/u/{unit.pk}/", HTTP_ACCEPT_LANGUAGE="pl"
        )

    assert resp.status_code == 200
    assert "Edytuj jednostkę" in resp.content.decode()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_unit_edit_link.py tests/test_i18n_po_health.py -v`
Expected: all pass

If `test_edit_link_label_renders_in_polish` fails with the English label present, the activation is incomplete — check all three of the session key, the `save()`, and the `HTTP_ACCEPT_LANGUAGE` header.

- [ ] **Step 6: Falsify the render half**

Only after it is green: in `_unit_strip.html`, replace `{% trans "Edit unit" %}` with the bare literal `Edit unit`.

Run: `uv run pytest tests/test_unit_edit_link.py::test_edit_link_label_renders_in_polish -v`
Expected: FAIL. Restore.

Do **not** falsify by emptying the catalog — that reddens the catalog half too and proves nothing about the template.

- [ ] **Step 7: Commit**

```bash
uv run ruff check tests/test_unit_edit_link.py
uv run ruff format --check tests/test_unit_edit_link.py
git branch --show-current
git add locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo \
        locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo \
        tests/test_unit_edit_link.py
git commit -m "i18n(courses): translate the Edit unit link into Polish"
```

---

### Task 7: e2e — the `replaceWith` trap

**Files:**
- Test: `tests/test_e2e_tags.py` (append)

**Interfaces:**
- Consumes: the `.unit-strip__edit` hook from Task 2.
- Produces: nothing.

This is the only test that can catch the regression the whole wrapper exists to prevent: `tags.js` replaces the `.unit-tags` subtree after a tag is added, with JS on only. A server-side test cannot see it.

**`-m e2e` is MANDATORY on every command in this task.** `pyproject.toml` sets
`addopts = "-q -m 'not e2e'"`, and that marker filter applies **even when a test is selected by node
id**. Without `-m e2e` both the verification run and the falsification run report *"1 deselected, no
tests ran"* with exit code 5 — which is not a pass. The only test guarding the `replaceWith`
regression would ship unrun, and Task 8's bare `uv run pytest` excludes it too, so nothing else
covers the gap.

**Treat "no tests ran" as a failure of the step**, never as a green result. Confirm the run actually
collected the test before believing either outcome.

**Run e2e focused and in the FOREGROUND.** A backgrounded `-m e2e` run has previously spawned runaway browsers in this repo.

- [ ] **Step 1: Write the test**

Append to `tests/test_e2e_tags.py`. This mirrors the ADD block of the existing
`test_tag_filter_untag_delete_via_ui` in the same file, with **one change**: that test builds a plain
`CourseFactory(title="Bio")` plus an `Enrollment`, so its actor is not the course owner and would see
no Edit link at all. The copy sets `owner=user`. No enrollment is needed — `tags.views.tag_add` gates
on `can_access_course`, which an owner passes.

The module already sets `pytestmark = pytest.mark.e2e`, defines the `_login(page, live_server,
username)` helper, and imports `expect`, `make_verified_user` and `TEST_PASSWORD`.

```python
@pytest.mark.django_db(transaction=True)
def test_edit_link_survives_adding_a_tag(page, live_server):
    """The Edit link must survive tags.js's panel.replaceWith() swap.

    This is the ONLY test that can catch it: the swap happens with JS on only, so
    every server-side test passes while the link silently vanishes the first time
    the user tags a unit — during the exact workflow this feature exists for.
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username="editor", email="editor@test.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="Owned", owner=user)
    part = ContentNodeFactory(course=course, kind="part", unit_type=None)
    unit = ContentNodeFactory(
        course=course, parent=part, unit_type="lesson", title="Photosynthesis"
    )

    _login(page, live_server, "editor")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/?panel=tags")

    # 1. The link is there to begin with — anchors the later assertion to a
    #    proven positive.
    expect(page.locator(".unit-strip__edit")).to_be_visible()

    # 2. Add a tag through the REAL form: a real fill and a real click on the real
    #    submit. Never page.evaluate — an e2e that bypasses the gesture ships
    #    broken UX green.
    page.locator(".unit-tags__add input[name='name']").fill("walkthrough")
    page.get_by_role("button", name="Add").click()

    # 3. Wait on a CONTENT condition on the swapped-in panel. tags.js swaps from
    #    an un-awaited fetch().then() and leaves behind no marker attribute,
    #    status node or URL change, so there is no deterministic anchor to wait
    #    on. Same idiom as the ADD block above. A bare timeout is NOT acceptable.
    expect(
        page.locator(".unit-tags__chips .tag-chip", has_text="walkthrough")
    ).to_be_visible()

    # 4. ONLY NOW assert the link survived. The ordering is load-bearing:
    #    asserting it before the swap completes would pass even if the swap went
    #    on to destroy it — green while broken.
    expect(page.locator(".unit-strip__edit")).to_be_visible()
```

- [ ] **Step 2: Run it in the foreground**

Run: `uv run pytest -m e2e tests/test_e2e_tags.py::test_edit_link_survives_adding_a_tag -v`
Expected: **1 passed**. If the output says "1 deselected" or "no tests ran", the `-m e2e` flag is
missing — the step has not been performed.

- [ ] **Step 3: Falsify — put the link inside the replaced subtree**

Temporarily move the `{% if can_edit_unit %}…{% endif %}` block into `tags/templates/tags/_unit_tag_panel.html`, inside the `<details>`.

Run: `uv run pytest -m e2e tests/test_e2e_tags.py::test_edit_link_survives_adding_a_tag -v`
Expected: **step 1 passes, step 4 FAILS** — the link renders initially and is destroyed by the swap. That asymmetry is the whole point; if step 1 also fails, the mutation broke the initial render instead and the falsification does not count. Restore.

- [ ] **Step 4: Commit**

```bash
uv run ruff check tests/test_e2e_tags.py
uv run ruff format --check tests/test_e2e_tags.py
git branch --show-current
git add tests/test_e2e_tags.py
git commit -m "test(e2e): the Edit link survives the tag panel's replaceWith swap"
```

---

### Task 8: Visual verification and full-suite green

**Files:**
- Create (temporary, **not committed**): `tests/test_e2e_unit_strip_shots.py`
- Modify: none, unless Step 3 reveals a defect

**Interfaces:** consumes the finished feature.

This is the only verification for the one regression this design can actually cause: `.unit-strip` now wraps an element that three pages already position.

- [ ] **Step 0: Write the capture harness**

The shots need a logged-in Playwright `page`, and the repo's only login path is `_login()` inside
`tests/test_e2e_tags.py` — an `e2e`-marked module. So the harness is itself an `e2e` test, run with
`-m e2e` in the **foreground**, and deleted at the end of the task.

Create `tests/test_e2e_unit_strip_shots.py`, modelled on `tests/test_e2e_tags.py`. Copy from it
verbatim: the `_allow_sync_orm_under_playwright` fixture, the `_login` helper, and
`pytestmark = pytest.mark.e2e`. Every shot test **also** needs
`@pytest.mark.django_db(transaction=True)`, exactly as `test_tag_filter_untag_delete_via_ui` carries
it — `live_server` runs in a separate thread and must see the fixture rows, so without it every test
errors on "Database access not allowed" before a single pixel is captured.

The file's imports, in full:

```python
import os
import tempfile
from pathlib import Path

import pytest

from courses.models import QuizSubmission
from tags import services
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import TagFactory
from tests.factories import make_quiz_unit
from tests.factories import make_verified_user
```

(`TEST_PASSWORD` sorts **first** within the group: ruff's default `order-by-type` puts CONSTANTS
before Classes before functions. Every one of the ~60 repo modules importing it has it first.)

This covers every name Step 1's six rows actually call — `services.tag_unit`, `TagFactory`,
`QuizSubmissionFactory` / `QuizSubmission.Status`, `CourseFactory`, `ContentNodeFactory`,
`make_quiz_unit` and `EnrollmentFactory`. (`expect` is **not** needed: this harness only captures
images, it asserts nothing.)

**`SHOT_DIR` lives outside the repository.** Do not write the images into the worktree and do not add
a git ignore: this is a *linked* worktree, so `.git` is a **file**, not a directory —
`.git/info/exclude` is an unwritable path here, and git actually reads
`$(git rev-parse --git-common-dir)/info/exclude`, which is the **main checkout's** git dir, shared
with every other worktree and any parallel session. Writing images outside the repo sidesteps all of
that and removes the accidental-commit risk entirely.

```python
SHOT_DIR = Path(tempfile.gettempdir()) / "unit-strip-shots"
VARIANT = os.environ.get("SHOT_VARIANT", "feature")


def _shoot(page, name, variant=None):
    """Capture the current viewport in both themes.

    `variant` distinguishes the same row captured under different source states —
    "feature" (as built), "nomin" (min-width: 0 deleted), "baseline" (feature
    rendering reverted). Step 2's A/B comparisons need all three to coexist; a
    filename derived from `name` alone would overwrite the very image being
    compared against. It defaults to the SHOT_VARIANT env var so an entire
    re-run can be labelled without editing the file.

    data-theme is baked server-side and core/context_processors.py resolves the
    default `auto` preference to "light", so page.emulate_media(color_scheme=...)
    does NOTHING here — it would silently produce two identical light images.
    """
    variant = variant or VARIANT
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    for theme in ("light", "dark"):
        page.evaluate(f"document.documentElement.setAttribute('data-theme', '{theme}')")
        path = SHOT_DIR / f"{name}_{variant}_{theme}.png"
        page.screenshot(path=str(path), full_page=True)
```

**Write THREE test functions** — `test_shots_owner(page, live_server)`,
`test_shots_student(page, live_server)` and `test_shots_ab_narrow_student(page, live_server)`. Two of
them exist because of the actor split, the third because of the A/B isolation described below; do not
collapse them. The actor split is not cosmetic: `_login()` navigates to the login page
and fills the form, but never logs out, and allauth redirects an already-authenticated visitor away
from `/accounts/login/`, so a second `_login()` on the same `page` hangs on a locator that never
resolves. pytest-playwright's `page` fixture is function-scoped, so a separate function per actor
gives each a fresh browser context. Row assignment:

- `test_shots_owner` → matrix rows 1, 3, 4, 6 (the four owner rows)
- `test_shots_student` → matrix row 2 only (desktop enrolled student)
- `test_shots_ab_narrow_student` → matrix row 5 only (~400px enrolled student)

**Row 5 gets a function to itself, and that isolation is load-bearing.** It is the only row Step 2
re-captures under a modified source tree. If it shared a function with any other row, re-running that
function would also re-capture its siblings — under the *modified* tree, at their default
`variant="feature"` filenames, silently overwriting the Step 1 images. `_shoot` never clears
`SHOT_DIR`, so the parity run in particular would refile feature-off renderings as `_feature_`, and
Step 3 would then judge baseline images believing they showed the feature.

Viewports: **desktop** `page.set_viewport_size({"width": 1280, "height": 900})`; **narrow**
`page.set_viewport_size({"width": 400, "height": 900})`.

Keep the harness `ruff format`-clean anyway, so that a stray `ruff check` on it before Step 4 does not
send you debugging scaffolding you are about to delete. The `page.evaluate(...)` line above is already
in its collapsed form for that reason (split across lines it joins to exactly 88 characters, and
`ruff format` would collapse it).

- [ ] **Step 1: Capture the screenshot matrix**

Six states × light and dark = **12 shots**.

Each row's **shot name** is the literal string passed to `_shoot`, and Step 2's filenames are built
from it — use these exact keys:

| Page | Viewport | Actor | Tag panel | Shot name |
|---|---|---|---|---|
| `lesson_unit` | desktop | owner (link present) | closed | `desktop_owner_closed` |
| `lesson_unit` | desktop | enrolled student (link absent) | closed | `desktop_student_closed` |
| `lesson_unit` | desktop | owner (link present) | **open** | `desktop_owner_open` |
| `lesson_unit` | ~400px | owner, **populated panel** | **open** | `narrow_owner` |
| `lesson_unit` | ~400px | enrolled student, **long-token tag** | **open** | `narrow_student` |
| `quiz_results` | desktop | owner, **needs a SUBMITTED submission** | closed | `results_owner` |

**Open the panel** by loading with `?panel=tags` — the server-side switch the views already read. Do **not** click the `<summary>` in Playwright; that adds a disclosure animation to race against.

Each row is one `_shoot(page, "<row-name>")` call from Step 0, which handles both themes.

Run: `uv run pytest -m e2e tests/test_e2e_unit_strip_shots.py -v` — in the **foreground**, and note
that `-m e2e` is mandatory here for the same reason as in Task 7.

**If a light and dark pair are identical, the capture failed** — that is a harness bug, not a theme that happens to match.

**Fixtures that are easy to get wrong:**
- The `quiz_results` row needs `QuizSubmissionFactory(student=<owner>, unit=<the quiz node>, status=QuizSubmission.Status.SUBMITTED)`, or the view redirects to `quiz_unit`, which renders the same strip and looks entirely plausible while leaving the row's actual purpose unverified. **Confirm the captured URL is the results path.**
- Both ~400px rows need a **populated** panel. With an empty panel the row will not wrap and the shot cannot show the layout it exists to show. **If the ~400px owner shot is not wrapped, the fixture is wrong.**
- **The ~400px owner row's fixture, explicitly** — it needs *both* kinds of tag, and they are built
  differently, which is exactly the trap described in the next bullet:
  ```python
  from tags import services

  # Chips (attached) — these are what widen the OPEN panel enough to force the wrap.
  for name in ("revision", "photosynthesis", "needs-diagram", "chapter-two"):
      services.tag_unit(owner, unit, name)
  # One UNATTACHED tag so {% if addable_tags %} is true and the <fieldset> renders.
  TagFactory(author=owner, name="not-yet-applied")
  ```
  The attached chips produce the wrap; the unattached tag produces the fieldset. Confirm
  `services.tag_unit`'s signature before use — if it differs, the equivalent is a `Tag` plus a
  `UnitTag` join row (`UnitTagFactory(tag=…, unit=…)`).
- The long-token tag must be created **unattached** — every service in `tags/services.py` attaches the tag to the unit, which removes it from `addable_tags`:
  ```python
  TagFactory(author=actor, name="WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW")  # 50 chars
  ```
  The model field is **`author`**, not `owner`. Use **wide glyphs** (uppercase/`W`/digits) at the full 50-character `TAG_NAME_MAX_LEN` cap — at `.8rem` a 50-char lowercase token is right at the ~345px boundary and a 40-char one provably shows nothing.

- [ ] **Step 2: Run the two A/B validations**

Both validations re-capture the **~400px student row** under a modified source tree. Two rules make
that safe, and both matter:

1. **Run only `test_shots_ab_narrow_student`** — never the whole file, and never a function holding
   other rows. Anything else re-captures its siblings under the modified tree and overwrites their
   Step 1 images.
2. **Label the run** via `SHOT_VARIANT`, so the new images land beside the originals instead of on
   top of them.

*Fixture validation:* delete `min-width: 0` from `courses.css`, then:

```bash
SHOT_VARIANT=nomin uv run pytest -m e2e   tests/test_e2e_unit_strip_shots.py::test_shots_ab_narrow_student -v
```

Restore the declaration afterwards. Compare:

```
narrow_student_feature_light.png   vs   narrow_student_nomin_light.png
```

They **must differ**. If they are identical the fixture failed to reproduce the hazard and the shot
proves nothing — that is a fixture bug to fix, not evidence the declaration is unnecessary.

*Parity validation:* produce the **feature-off baseline** — **do not check out master**, which
discards the fixture code the shot depends on. Undo the feature's *rendering* in place: revert the
three `{% include "courses/_unit_strip.html" %}` lines to `{% include "tags/_unit_tag_panel.html" %}`
and remove the two `.unit-strip*` rules from `courses.css`. Then:

```bash
SHOT_VARIANT=baseline uv run pytest -m e2e   tests/test_e2e_unit_strip_shots.py::test_shots_ab_narrow_student -v
```

Restore everything afterwards. Compare:

```
narrow_student_feature_light.png   vs   narrow_student_baseline_light.png
```

These must be **equivalent**. Repeat both comparisons for the `_dark` pair.

**Before moving to Step 3, confirm the `_feature_` images are still the Step 1 ones** — i.e. captured
under the unmodified tree. If a stray whole-file re-run happened at any point, delete `SHOT_DIR` and
re-capture Step 1 from scratch; judging a baseline image as though it were the feature is exactly the
vacuous pass this task exists to prevent.

- [ ] **Step 3: Self-critique the shots against the acceptance criteria**

- **Unwrapped rows:** the button is pinned to the far right end of the row and **shares the tag panel's top edge**, without overlapping it.
- **Wrapped (~400px) rows:** the button sits on its own line, flush with the content column's left edge, with the `.5rem` gap below the strip intact. (The top-edge criterion is meaningless here — the items are on different lines.)
- **Panel border box** at ~400px with the panel open: its right edge sits within the content column.
- **No horizontal overflow beyond the feature-off baseline** for the same page. Do not assert an absolute.
- **Student view** is visually equivalent to today's vertical rhythm.
- **Screen-reader name.** The `&nbsp;` + `.visually-hidden` "(opens in a new tab)" construction is
  this feature's only accessibility affordance and is deliberately guarded by **no automated test** —
  the spec routes its verification entirely into this manual pass, so it is unverified by anything if
  skipped here. Confirm the announced accessible name of `.unit-strip__edit` with a real screen
  reader (or, at minimum, the browser devtools accessibility inspector) and **record the observed
  name** in the task's completion notes, to be carried into the PR body (see Step 6). Expected: the label and the parenthetical are announced as separate words, not
  run together as "unit(opens".
- **`quiz_results` overhang is pre-recorded as ACCEPTED, not a pass/fail gate.** The strip spans 920px above a 736px `.result` article — ~90px per side. This is not new: the tag panel already does exactly this on master. Confirm it reads as deliberate rather than broken; if a human judges otherwise that is a follow-up styling decision, **not a blocker for this change**.

- [ ] **Step 4: Delete the capture harness — BEFORE the lint gate**

```bash
rm tests/test_e2e_unit_strip_shots.py
rm -rf "${TMPDIR:-/tmp}/unit-strip-shots"   # SHOT_DIR, outside the repo
git status --short                          # must show no stray harness file
```

The harness is scaffolding for the manual pass, not a deliverable — it asserts nothing and would only
rot in CI (where it is excluded by `addopts` anyway).

**This must happen before Step 5's lint gate.** `uv run ruff check` and `ruff format --check` take no
path argument there, so they cover the whole tree including this throwaway file — and you would be
debugging a lint failure in scaffolding you are about to delete.

- [ ] **Step 5: Full suite, lint, and migration check**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run python manage.py compilemessages
uv run python manage.py makemigrations --check
```

Expected: all clean, **no new migration**.

Note: `pytest` verdict lines do not survive a Bash pipe in this environment — rely on the exit code, or grep for `FAILED`.

**"All clean" above does NOT include e2e — run it separately.** `addopts = "-q -m 'not e2e'"` means
the bare `uv run pytest` covers **zero** e2e tests, and this change inserts a new visible element at
the top of `{% block content %}` on all three consumption pages *for course owners* — while many
existing e2e fixtures build `CourseFactory(..., owner=<the actor>)` and then assert on geometry
(`bounding_box()`, `scrollTop`) of those same pages. `tests/test_e2e_unit_nav.py` does both. Reporting
"all clean" without running these would miss exactly the regression this feature is most likely to
cause, and CI runs e2e as a separate job.

Run the full e2e suite in the **foreground**:

```bash
uv run pytest -m e2e
```

If a full run is impractical, the minimum is every module that consumes a unit page with an
owner-actor or geometric assertions:

```bash
uv run pytest -m e2e tests/test_e2e_tags.py tests/test_e2e_unit_nav.py   tests/test_e2e_unit_head_layout.py tests/test_e2e_scroll_affordance.py   tests/test_e2e_practice_state.py tests/test_e2e_markdone.py -v
```

Never background an `-m e2e` run — it has previously spawned runaway browsers in this repo.

If an **unrelated pre-existing flaky** test fails, prove it is not caused by this diff (re-run it on the base commit) and fix it in its **own** PR rather than bundling it here.

- [ ] **Step 6: Commit any screenshot-driven fixes**

Only if Step 3 revealed a real defect:

```bash
git branch --show-current
git add <the specific files>
git commit -m "fix(css): <what the screenshot revealed>"
```

If the shots were clean, there is nothing to commit — say so plainly rather than inventing a commit.
