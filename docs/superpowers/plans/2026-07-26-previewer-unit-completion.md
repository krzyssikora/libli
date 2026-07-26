# Previewer Unit Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an explicit "Mark as done" click persist for any viewer who can access the course, instead of silently no-op'ing for non-enrolled previewers.

**Architecture:** Two behavioural edits in `courses/views.py` — drop the `is_enrolled` gate in `complete` (leaving `can_access_course` as the sole guard) and wrap the write in `transaction.atomic()` + `select_for_update()`; and assign `progress = state_row` in `build_lesson_context`'s non-enrolled branch so the saved state re-renders. Scroll-based auto-completion (`seen`) deliberately stays enrolled-only. The bulk of this change is tests, not code.

**Tech Stack:** Django, pytest + pytest-django, factory_boy (`tests/factories.py`), BeautifulSoup for HTML assertions, PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-07-26-previewer-unit-completion-design.md` — read it before starting. It carries the reasoning behind every decision here.

## Global Constraints

- **No migration, no model change, no new URL, no JS change, no new translatable strings, and no template markup change.** The only template edit is a `{% comment %}` body.
- **Every command goes through `uv run`.** Bare `ruff`, `pytest` and `python` are not on PATH: `uv run pytest`, `uv run ruff check`, `uv run python manage.py check`.
- **Test DB isolation:** this work happens in a git worktree. Concurrent pytest runs across worktrees collide on the shared Postgres `test_libli`, and `-n auto` widens that window. Use a worktree-unique `DATABASE_URL` and **never run two pytest invocations at once**. A collision produces failures unrelated to this diff.
- **Prose in `courses/views.py` must not match the write-route tripwire.** `tests/test_element_state_write_routes.py` regexes raw source text — comments *and* docstrings, no stripping — and asserts exactly 3 hits in `courses/views.py`. No comment or docstring this diff adds may match:
  `\.update\(\s*element_state=|element_state\.pop\(|element_state\[[^\]]*\]\s*=|\.element_state\s*=(?!=)`
  Refer to the field in prose ("the practice-state blob") instead. The template comment is exempt — the guard walks first-party `.py` roots only.
- **Every new/inverted/extended test must be falsification-proven:** remove the guard it exists for, confirm RED, restore. A passing test proves nothing until it has been made to fail.
- **All new tests land in `tests/test_courses_progress.py`**, each decorated with `@pytest.mark.django_db` individually (that module has no module-level `pytestmark`).
- **Use `tests.factories` helpers and `TEST_PASSWORD`.** Never a hardcoded password.
- **Scope HTML assertions to a subtree with BeautifulSoup** (precedent: `tests/test_unit_nav_render.py`). Never a body-wide substring — `data-done-label="{% trans 'Completed' %}"` renders unconditionally at `_lesson_article.html:13`, so `assert "Completed" in body` is vacuous.
- **`UnitProgressFactory` declares `student` and `unit` as `SubFactory`s.** Always pass both explicitly, or the factory mints a row for an unrelated user on an unrelated node and negative assertions pass silently.
- **`element_state` seeds use STRING keys.** It is a `JSONField`: an int-keyed seed round-trips as `{"1": …}` and a comparison against the in-memory literal false-REDs against correct code.
- **Django multi-line template comments use `{% comment %}`**, never `{# #}`.

---

### Task 1: The write — lift the gate, lock the row

Inverts the shipped no-op guarantee and makes `complete` write for any accessing viewer. This is spec Testing §1(a) plus Architecture §1 and the §2b `element_state_save` comment correction.

**Files:**
- Modify: `tests/test_courses_progress.py:121-135` (invert `test_previewer_complete_redirects_without_write`)
- Modify: `courses/views.py:671-685` (`complete`)
- Modify: `courses/views.py:784-788` (the `element_state_save` comment)

**Interfaces:**
- Produces: `complete` writes a `UnitProgress` row for any `can_access_course` viewer; every later task's POST to `courses:complete` relies on this.

- [ ] **Step 1: Rewrite the existing test in place (do not add a second test beside it)**

Replace the whole of `test_previewer_complete_redirects_without_write` (currently `tests/test_courses_progress.py:121-135`) with:

```python
@pytest.mark.django_db
def test_previewer_complete_persists_and_redirects(client):
    from courses.models import UnitProgress

    staff = make_login(client, "staff2")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="pcx")  # staff not enrolled -> previewer
    unit, ids = _make_unit_with_elements(course, 1)

    r = client.post(
        reverse("courses:complete", kwargs={"slug": "pcx", "node_pk": unit.pk})
    )

    # The redirect assertion is KEPT from the old test (the inversion replaces the
    # WRITE assertion, not the response-shape one) and tightened: complete() ends in
    # redirect(), so a 200 would now mean something went wrong.
    assert r.status_code == 302
    assert r["Location"] == reverse(
        "courses:lesson_unit", kwargs={"slug": "pcx", "node_pk": unit.pk}
    )
    row = UnitProgress.objects.get(student=staff, unit=unit)
    assert row.completed is True
    assert row.completed_at is not None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_courses_progress.py::test_previewer_complete_persists_and_redirects -v`
Expected: FAIL — `UnitProgress.DoesNotExist`, because `complete` still writes nothing for a previewer.

- [ ] **Step 3: Lift the gate and lock the row**

Replace `courses/views.py:671-685` (the body of `complete`, from the `def` line through the `return`) with:

```python
@require_POST
@login_required
def complete(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    # can_access_course is DELIBERATELY the sole guard on this write: the row is the
    # viewer's OWN record, not course analytics, so any viewer who can open the lesson
    # may mark it done -- the same reversal PR #136 applied to markdone_save. Do not
    # "restore" an enrollment check here; tests 5(a)-(d) pin both directions.
    if not can_access_course(request.user, course):
        raise PermissionDenied
    with transaction.atomic():
        # Re-read under the lock instead of keeping get_or_create's instance. FOR
        # UPDATE serialises concurrent writers, but it CANNOT protect a writer whose
        # READ happened before the lock -- that writer carries a stale row across the
        # block and writes it back afterwards. (It is NOT the case that a lock "only
        # excludes writers that also take it": on PostgreSQL a plain UPDATE does block
        # on an existing FOR UPDATE. The rule is about ORDERING, not exclusion.) That
        # is why save_element_state locks before it reads, and why seen -- which does
        # not -- can still lose an update. Collapsing this back to
        # `progress, _ = get_or_create(...)` is byte-identical in every sequential
        # test, so this comment is the only thing protecting the re-fetch.
        UnitProgress.objects.get_or_create(student=request.user, unit=node)
        progress = UnitProgress.objects.select_for_update().get(
            student=request.user, unit=node
        )
        if not progress.completed:
            progress.completed = True
            progress.save()  # completed_at stamped in save()
    return redirect("courses:lesson_unit", slug=slug, node_pk=node_pk)
```

`transaction` is already imported (`courses/views.py:8`). Do not add an import.

- [ ] **Step 4: Run the test and watch it pass**

Run: `uv run pytest tests/test_courses_progress.py::test_previewer_complete_persists_and_redirects -v`
Expected: PASS.

- [ ] **Step 5: Prove the test is falsifiable**

Temporarily re-wrap the write in `if is_enrolled(request.user, course):` (indent the `with transaction.atomic():` block one level under it). Run the same command.
Expected: FAIL (`UnitProgress.DoesNotExist`). **Then restore the code from Step 3** and re-run to confirm PASS.

- [ ] **Step 6: Correct the `element_state_save` comment**

Replace `courses/views.py:784-788` (the comment block beginning `# Practice state is personal self-tracking`) with:

```python
    # Practice state is personal self-tracking (ungraded, absent from analytics), so
    # ANY viewer who can access the lesson persists their own -- not just enrolled
    # students. This deliberately diverges from seen/quiz, which ignore previewers so
    # authors don't pollute their own SCROLL-tracking and quiz analytics. Note that is
    # those two specifically, NOT progress writes in general: an explicit "Mark as
    # done" click now persists for previewers too (see complete()). The
    # can_access_course gate above is the only guard the write needs.
```

The enumeration (`seen`/quiz) was already correct and is unchanged — only the parenthetical rationale, which this change falsifies, is rewritten.

- [ ] **Step 7: Check the tripwire and lint, then commit**

Run: `uv run pytest tests/test_element_state_write_routes.py -v`
Expected: PASS (3 hits in `courses/views.py`). If it fails, the new prose matched the regex — reword it; it is a prose problem, not a code one.

Run: `uv run ruff check courses/views.py tests/test_courses_progress.py` and `uv run ruff format --check courses/views.py tests/test_courses_progress.py`
Expected: clean.

```bash
git add courses/views.py tests/test_courses_progress.py
git commit -m "feat(courses): persist an explicit Mark-as-done for any accessing viewer"
```

---

### Task 2: The write over a pre-existing row

Spec Testing §1(b) and §1(c). No production change — this is regression cover for the shape the change most plausibly breaks: `complete` running over a row that already exists.

**Files:**
- Modify: `tests/test_courses_progress.py` (two new tests, plus one import)

**Interfaces:**
- Consumes: Task 1's gate-lifted `complete`.

- [ ] **Step 1: Add the `UnitProgressFactory` import**

At the top of `tests/test_courses_progress.py`, beside the existing factory imports:

```python
from tests.factories import UnitProgressFactory
```

- [ ] **Step 2: Write test 1(b) — the previewer's checklist row**

Append to `tests/test_courses_progress.py`:

```python
@pytest.mark.django_db
def test_previewer_complete_over_checklist_row_preserves_practice_state(client):
    from courses.models import UnitProgress

    staff = make_login(client, "staff1b")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="pcb")
    unit, ids = _make_unit_with_elements(course, 1)
    # STRING keys: element_state is a JSONField, so an int-keyed seed round-trips as
    # {"<pk>": ...} and comparing to the in-memory literal would fail against CORRECT
    # code. This is production shape -- save_element_state stores str(element_pk).
    seeded = {str(ids[0]): {"checked": True}}
    # Both student= and unit= are mandatory: they are SubFactory fields, and omitting
    # them mints a row for an unrelated user on an unrelated node.
    UnitProgressFactory(student=staff, unit=unit, completed=False, element_state=seeded)

    client.post(reverse("courses:complete", kwargs={"slug": "pcb", "node_pk": unit.pk}))

    row = UnitProgress.objects.get(student=staff, unit=unit)
    assert row.completed is True
    assert row.completed_at is not None
    assert row.element_state == seeded
```

- [ ] **Step 3: Write test 1(c) — the enrolled twin**

Append:

```python
@pytest.mark.django_db
def test_enrolled_complete_over_existing_row_preserves_state_and_seen_ids(client):
    from courses.models import UnitProgress

    student = make_login(client, "enr1c")
    course = CourseFactory(slug="pcc")
    EnrollmentFactory(student=student, course=course)
    unit, ids = _make_unit_with_elements(course, 1)
    seeded_state = {str(ids[0]): {"checked": True}}
    # seen_element_ids is the column the lost-update argument actually centres on:
    # `seen` is the unhardened full-row writer, and only an ENROLLED row realistically
    # carries a non-empty seen-set (a previewer never reaches seen's write).
    UnitProgressFactory(
        student=student,
        unit=unit,
        completed=False,
        element_state=seeded_state,
        seen_element_ids=[ids[0]],
    )

    client.post(reverse("courses:complete", kwargs={"slug": "pcc", "node_pk": unit.pk}))

    row = UnitProgress.objects.get(student=student, unit=unit)
    assert row.completed is True
    assert row.element_state == seeded_state
    assert row.seen_element_ids == [ids[0]]
```

- [ ] **Step 4: Run both and confirm they pass**

Run: `uv run pytest tests/test_courses_progress.py -k "checklist_row_preserves or existing_row_preserves" -v`
Expected: 2 passed.

- [ ] **Step 5: Falsify the `completed` half of 1(b) only**

Temporarily re-wrap the write in `complete` in `if is_enrolled(request.user, course):`. Run the same command.
Expected: `test_previewer_complete_over_checklist_row_preserves_practice_state` FAILS; the enrolled 1(c) still passes. **Restore the code** and re-run.

The blob assertions in 1(b)/1(c) are **exempt from falsification, in writing**: sequentially, `get_or_create` re-reads the row, so both blobs survive even a lock-less implementation and no mutation reddens them. They are asserted as cheap regression cover, and are not claimed as guards.

- [ ] **Step 6: Commit**

```bash
git add tests/test_courses_progress.py
git commit -m "test(courses): cover complete() over a pre-existing progress row"
```

---

### Task 3: The read — make the saved state re-render

Spec Architecture §2 and Testing §2. This is the load-bearing half: without it the write lands but the pill still reads "Mark as done", making the change invisible.

**Files:**
- Modify: `tests/test_courses_progress.py` (one new test)
- Modify: `courses/views.py:395-399` (the `elif user.is_authenticated` branch)
- Modify: `courses/views.py:273-275` (`build_lesson_context`'s docstring)
- Modify: `templates/courses/_lesson_article.html:8-11` (the `{% comment %}` body)

**Interfaces:**
- Produces: `progress` is non-`None` for a non-enrolled viewer holding a row. Tasks 4, 5 and 8 all depend on this.

- [ ] **Step 1: Write the failing read test**

Append to `tests/test_courses_progress.py`:

```python
@pytest.mark.django_db
def test_previewer_sees_completed_pill_after_marking(client):
    from bs4 import BeautifulSoup

    from courses.models import UnitProgress

    staff = make_login(client, "staff3")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="prd")
    unit, ids = _make_unit_with_elements(course, 1)
    client.post(reverse("courses:complete", kwargs={"slug": "prd", "node_pk": unit.pk}))
    assert UnitProgress.objects.filter(student=staff, unit=unit, completed=True).exists()

    # A SEPARATE GET -- deliberately not follow=True on the POST, or "test 1 stays
    # green while this goes RED" in the falsification below would mean nothing.
    r = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "prd", "node_pk": unit.pk})
    )

    assert r.status_code == 200
    # Scope to the [data-unit-done] subtree: is-complete is safe as a body substring
    # only by accident today, and "Completed" is always present via data-done-label.
    pill = BeautifulSoup(r.content, "html.parser").select_one("[data-unit-done]")
    assert pill is not None
    assert "is-complete" in pill.get("class", [])
    assert pill.select_one("button.unit-done__pill--btn") is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_courses_progress.py::test_previewer_sees_completed_pill_after_marking -v`
Expected: FAIL — `is-complete` is absent and the submit button is present, because `progress` is still `None` for a previewer.

- [ ] **Step 3: Assign `progress` in the non-enrolled branch**

Replace `courses/views.py:395-399` (the `elif user.is_authenticated:` branch and its comment) with:

```python
    elif user.is_authenticated:
        # Non-enrolled but can view (author/teacher): read an EXISTING row for their
        # practice state AND the completion pill -- an explicit "Mark as done" click
        # persists for them too (see complete()), and without this assignment the
        # write would land but never re-render. Still .filter().first(), never
        # get_or_create: a passive GET must not mint a row for a previewer.
        state_row = UnitProgress.objects.filter(student=user, unit=node).first()
        progress = state_row
```

`progress` is already initialised to `None` at `courses/views.py:385`, so a viewer with no row still renders the button.

- [ ] **Step 4: Run the test and watch it pass**

Run: `uv run pytest tests/test_courses_progress.py::test_previewer_sees_completed_pill_after_marking -v`
Expected: PASS.

- [ ] **Step 5: Prove it is falsifiable, and that test 1 does not cover it**

Temporarily delete the `progress = state_row` line. Run:
`uv run pytest tests/test_courses_progress.py -k "sees_completed_pill or persists_and_redirects" -v`
Expected: the pill test FAILS, `test_previewer_complete_persists_and_redirects` still PASSES — proving the read edit is separately guarded. **Restore the line** and re-run.

- [ ] **Step 6: Fix the `build_lesson_context` docstring (both false clauses)**

Replace `courses/views.py:273-275` (the docstring) with:

```python
    """Shared element/has_*/progress context for a LESSON unit. Reached through
    full_lesson_render_context, which serves every render site (see its docstring --
    do not re-enumerate them here, or the list drifts in two places).
    Enrolled: UnitProgress.get_or_create + seen-count, as a normal view. Non-enrolled
    but authorised: a read-only .filter().first() lookup that feeds practice state and
    the completion pill without creating a row on a GET."""
```

Both clauses were wrong: "both … the two" (there are three render sites) and "the same `UnitProgress.get_or_create`" (true only on the enrolled path).

- [ ] **Step 7: Fix the template comment**

Replace `templates/courses/_lesson_article.html:8-11` (the `{% comment %}` block) with:

```html
    {% comment %}Completion is auto-tracked FOR ENROLLED STUDENTS ONLY: progress.js
       auto-completes the unit once every element has been seen (Phase-1a). For a
       non-enrolled viewer who can access the course, seen-tracking is never recorded,
       so this pill is not a fallback — it is their ONLY route to completion, and an
       explicit click persists for them (see courses/views.py::complete). For enrolled
       students it remains the no-JS fallback + manual override and the live status
       indicator — progress.js flips it to "✓ Completed" the moment auto-complete
       fires. The form keeps class="unit-progress" (e2e + no-JS POST).{% endcomment %}
```

Comment body only — no markup, no attributes, no strings change. Keep it a `{% comment %}` block: `{# #}` cannot span lines in Django.

- [ ] **Step 8: Verify nothing rendered changed, check the tripwire, commit**

Run: `uv run pytest tests/test_courses_progress.py tests/test_element_state_write_routes.py -v`
Expected: all pass.

Run: `uv run ruff check courses/views.py tests/test_courses_progress.py` and `uv run ruff format --check courses/views.py tests/test_courses_progress.py`
Expected: clean.

```bash
git add courses/views.py templates/courses/_lesson_article.html tests/test_courses_progress.py
git commit -m "feat(courses): render a previewer's own completion on the lesson page"
```

---

### Task 4: Pre-existing rows, both directions

Spec Testing §6. Two cases that must not be collapsed: a `completed=True` row surfaces with no POST at all (a visible day-one change for anyone previously enrolled), and a `completed=False` row still renders the button.

**Files:**
- Modify: `tests/test_courses_progress.py` (two new tests)

- [ ] **Step 1: Write 6(a) — a pre-existing `completed=True` row shows the pill on a plain GET**

```python
@pytest.mark.django_db
def test_previewer_pre_existing_completed_row_shows_pill_without_posting(client):
    from bs4 import BeautifulSoup

    staff = make_login(client, "staff6a")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="p6a")
    unit, ids = _make_unit_with_elements(course, 1)
    # The "was enrolled earlier" population: a row survives the enrollment going away.
    UnitProgressFactory(student=staff, unit=unit, completed=True)

    r = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "p6a", "node_pk": unit.pk})
    )

    assert r.status_code == 200
    pill = BeautifulSoup(r.content, "html.parser").select_one("[data-unit-done]")
    assert "is-complete" in pill.get("class", [])
    assert pill.select_one("button.unit-done__pill--btn") is None
```

Do **not** assert `"Completed" in r.content.decode()` — `_lesson_article.html:13` emits `data-done-label="{% trans 'Completed' %}"` unconditionally, so that substring is in every lesson response and the falsification below would stay green.

- [ ] **Step 2: Write 6(b) — a `completed=False` row still renders the button**

```python
@pytest.mark.django_db
def test_previewer_incomplete_row_still_renders_the_button(client):
    from bs4 import BeautifulSoup

    staff = make_login(client, "staff6b")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="p6b")
    unit, ids = _make_unit_with_elements(course, 1)
    # The most common previewer row in production once this ships: a checklist tick
    # creates exactly this shape. Both kwargs mandatory (SubFactory fields).
    UnitProgressFactory(
        student=staff,
        unit=unit,
        completed=False,
        element_state={str(ids[0]): {"checked": True}},
    )

    r = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "p6b", "node_pk": unit.pk})
    )

    assert r.status_code == 200
    pill = BeautifulSoup(r.content, "html.parser").select_one("[data-unit-done]")
    # Two DIFFERENT elements: the div's own class list, and a descendant button.
    assert "is-complete" not in pill.get("class", [])
    assert pill.select_one("button.unit-done__pill--btn") is not None
```

- [ ] **Step 3: Run both**

Run: `uv run pytest tests/test_courses_progress.py -k "pre_existing_completed_row or incomplete_row_still_renders" -v`
Expected: 2 passed.

- [ ] **Step 4: Falsify 6(a)**

Temporarily delete `progress = state_row` from `courses/views.py`. Run the same command.
Expected: 6(a) FAILS. **Restore** and re-run.

- [ ] **Step 5: Falsify 6(b) — and use the recipe that actually works**

6(b) guards the `progress`-vs-`progress.completed` distinction, not mere truthiness. Temporarily change `_lesson_article.html:12` and `:14` from `{% if progress.completed %}` to `{% if progress %}`. Run:
`uv run pytest tests/test_courses_progress.py::test_previewer_incomplete_row_still_renders_the_button -v`
Expected: FAIL. **Restore the template** and re-run.

Do **not** try "assign any truthy sentinel" as the recipe — the template branches on `.completed`, so a sentinel with a falsy/missing `.completed` leaves 6(b) green.

- [ ] **Step 6: Commit**

```bash
git add tests/test_courses_progress.py
git commit -m "test(courses): pin both directions of a pre-existing previewer row"
```

---

### Task 5: The second render surface — `check_answer`'s no-JS path

Spec Testing §7. The read assignment feeds three render surfaces; this drives the one that is not the plain GET.

**Files:**
- Modify: `tests/test_courses_progress.py` (one new test)

- [ ] **Step 1: Add the `add_element` import**

```python
from tests.factories import add_element
```

- [ ] **Step 2: Write the test**

```python
@pytest.mark.django_db
def test_previewer_completed_pill_survives_no_js_check_answer_rerender(client):
    from bs4 import BeautifulSoup

    from courses.models import Enrollment
    from courses.models import ShortTextQuestionElement

    staff = make_login(client, "staff7")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="p7")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    # Field names and URL shape copied from the repo's ONLY no-JS check_answer test
    # (courses/tests/test_reset_controls.py:156-177): ShortTextQuestionElement takes
    # stem/accepted, and add_element returns the JOIN ROW whose pk is the third URL
    # argument. Copy that recipe only -- never that file's _login helper, which calls
    # Enrollment.objects.create() before force_login and would silently make this an
    # ENROLLED-path test whose falsification recipe stays GREEN.
    q_row = add_element(
        unit, ShortTextQuestionElement.objects.create(stem="Q", accepted="x")
    )
    # Seeded directly, NOT via a complete() POST: this test's falsification targets the
    # READ assignment, and routing it through the write would couple it to an edit it
    # does not guard.
    UnitProgressFactory(student=staff, unit=unit, completed=True)
    # Access comes from the is_staff pin above, not from any fixture.
    assert not Enrollment.objects.filter(student=staff, course=course).exists()

    r = client.post(
        reverse("courses:check_answer", args=[course.slug, unit.pk, q_row.pk]),
        {"answer": "x"},  # NON-EMPTY: an empty answer takes the clear branch instead
    )  # NO HTTP_X_REQUESTED_WITH: the header would take the fragment branch instead

    assert r.status_code == 200
    pill = BeautifulSoup(r.content, "html.parser").select_one("[data-unit-done]")
    assert pill is not None
    assert "is-complete" in pill.get("class", [])
    assert pill.select_one("button.unit-done__pill--btn") is None
```

Note the incidental write: on a `RESTORABLE_IN_LESSON` question type, `check_answer` calls `save_element_state` on the **same** pre-seeded `UnitProgress` row — harmless here, but surprising if unexpected.

The header omission is load-bearing: `_wants_fragment` is `request.headers.get("X-Requested-With") == "fetch"`, and `question.js` always sets it, so the real JS UI returns a bare question fragment that never renders the pill. Adding the header "to mimic the real UI" would drive a branch this change does not touch.

- [ ] **Step 3: Run it**

Run: `uv run pytest tests/test_courses_progress.py::test_previewer_completed_pill_survives_no_js_check_answer_rerender -v`
Expected: PASS.

- [ ] **Step 4: Falsify**

Temporarily delete `progress = state_row`. Run the same command.
Expected: FAIL. **Restore** and re-run.

This also covers `notes/views.py:194`, which calls the same `full_lesson_render_context` with one extra kwarg touching only the notes panel — a third near-duplicate test would pin the caller list rather than any behaviour.

- [ ] **Step 5: Commit**

```bash
git add tests/test_courses_progress.py
git commit -m "test(courses): pin the completed pill on the no-JS check_answer re-render"
```

---

### Task 6: Every access route, positively and negatively

Spec Testing §5. `can_access_course` is now the sole guard on a write, so each route it admits must be driven end to end.

**Files:**
- Modify: `tests/test_courses_progress.py` (four new tests)

- [ ] **Step 1: Add the imports you will need**

```python
from tests.factories import GroupFactory
```

- [ ] **Step 2: Write 5(a) — the non-staff course owner (positive)**

```python
@pytest.mark.django_db
def test_non_staff_course_owner_can_complete(client):
    from courses.models import Enrollment
    from courses.models import UnitProgress

    owner = make_login(client, "owner5a")
    # owner= is MANDATORY: CourseFactory declares no owner and Course.owner is
    # null=True, so a bare CourseFactory() leaves route (a) non-existent.
    course = CourseFactory(slug="p5a", owner=owner)
    unit, ids = _make_unit_with_elements(course, 1)
    # Trap 1: accessible_courses returns Course.objects.all() at `if user.is_staff:`
    # BEFORE evaluating Q(owner=user), so a staff owner would pass via the wrong route.
    assert owner.is_staff is False
    # Trap 2: an enrolled owner writes on the BASE commit too, making this vacuous.
    assert not Enrollment.objects.filter(student=owner, course=course).exists()

    client.post(reverse("courses:complete", kwargs={"slug": "p5a", "node_pk": unit.pk}))

    assert UnitProgress.objects.get(student=owner, unit=unit).completed is True
```

- [ ] **Step 3: Write 5(d) — teacher of a non-archived group (positive)**

```python
@pytest.mark.django_db
def test_non_staff_teacher_of_live_group_can_complete(client):
    from courses.models import Enrollment
    from courses.models import UnitProgress

    teacher = make_login(client, "teach5d")
    course = CourseFactory(slug="p5d")
    unit, ids = _make_unit_with_elements(course, 1)
    # archived defaults to False on the model; GroupFactory declares no such field.
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    assert teacher.is_staff is False
    assert not Enrollment.objects.filter(student=teacher, course=course).exists()

    client.post(reverse("courses:complete", kwargs={"slug": "p5d", "node_pk": unit.pk}))

    assert UnitProgress.objects.get(student=teacher, unit=unit).completed is True
```

This route is tested because the branch exists in `accessible_courses` and now guards a write — **not** because it is the common production previewer. `role_is_staff` returns `True` for every role except Student, so a production Teacher short-circuits on `is_staff` and never reaches the group clause. The dominant previewer is the `is_staff` route, covered by Task 1.

- [ ] **Step 4: Write 5(b) — archived group (negative twin of 5(d))**

```python
@pytest.mark.django_db
def test_teacher_of_archived_group_is_denied(client):
    from courses.models import UnitProgress

    teacher = make_login(client, "teach5b")
    course = CourseFactory(slug="p5b")
    unit, ids = _make_unit_with_elements(course, 1)
    # archived=True is a PASSTHROUGH model kwarg, not a declared factory field.
    # Setting group.archived = True without a .save() would silently turn this into
    # route (d) and the test would pass while proving the opposite of its claim.
    group = GroupFactory(course=course, archived=True)
    group.teachers.add(teacher)
    # Kept because this test's whole claim is about the groups__archived=False pin,
    # which is only legible if the fixture shows the user reaching the group clause.
    assert teacher.is_staff is False

    r = client.post(
        reverse("courses:complete", kwargs={"slug": "p5b", "node_pk": unit.pk})
    )

    assert r.status_code == 403
    assert not UnitProgress.objects.filter(student=teacher, unit=unit).exists()
```

- [ ] **Step 5: Write 5(c) — no relationship at all (negative)**

```python
@pytest.mark.django_db
def test_unrelated_logged_in_user_is_denied(client):
    from courses.models import UnitProgress

    stranger = make_login(client, "stranger5c")
    course = CourseFactory(slug="p5c")
    unit, ids = _make_unit_with_elements(course, 1)

    r = client.post(
        reverse("courses:complete", kwargs={"slug": "p5c", "node_pk": unit.pk})
    )

    assert r.status_code == 403
    assert not UnitProgress.objects.filter(student=stranger, unit=unit).exists()
```

No `is_staff` pin needed here: the assertion is a 403, so a stray staff flag reddens it loudly rather than passing silently.

- [ ] **Step 6: Run all four**

Run: `uv run pytest tests/test_courses_progress.py -k "5a or 5b or 5c or 5d or owner_can_complete or live_group_can_complete or archived_group_is_denied or unrelated_logged_in" -v`
Expected: 4 passed.

- [ ] **Step 7: Two falsifications**

*Gate:* temporarily delete the `if not can_access_course(...): raise PermissionDenied` block in `complete`. Expected: 5(b) and 5(c) FAIL. Restore.

*Diff-local:* temporarily re-wrap the write in `if is_enrolled(request.user, course):`. Expected: 5(a) and 5(d) FAIL. Restore.

Re-run all four after restoring: 4 passed.

- [ ] **Step 8: Commit**

```bash
git add tests/test_courses_progress.py
git commit -m "test(courses): drive every can_access_course route into complete()"
```

---

### Task 7: The asymmetry guard — `seen` stays enrolled-only

Spec Testing §3 and the §2b `seen` comment. `seen` is behaviourally untouched; this task renames and extends its test, and corrects the comment that now misdescribes the asymmetry.

**Files:**
- Modify: `tests/test_courses_progress.py:101-118` (rename + extend `test_previewer_seen_no_write_synthetic`)
- Modify: `courses/views.py:652` (the `seen` comment)

- [ ] **Step 1: Rename and extend the existing test — sequence it, do not overwrite it**

Replace `tests/test_courses_progress.py:101-118` with:

```python
@pytest.mark.django_db
def test_previewer_seen_no_write_and_ignores_stored_completion(client):
    from courses.models import UnitProgress

    staff = make_login(client, "staff1")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="pp")  # staff not enrolled
    unit, ids = _make_unit_with_elements(course, 1)

    # (1) The pre-existing half, unchanged: no row exists, so no write and a synthetic
    # response.
    r = client.post(
        _seen_url("pp", unit.pk), data=json.dumps(ids), content_type="application/json"
    )
    assert r.status_code == 200
    assert r.json() == {
        "seen_element_ids": [],
        "completed": False,
        "completed_at": None,
    }
    assert not UnitProgress.objects.filter(student=staff, unit=unit).exists()

    # (2) NOW seed a completed row for THAT SAME viewer. student= and unit= are
    # mandatory here above all: every step-(3) assertion is negative, so a row minted
    # against an unrelated node leaves them all green -- and so does this extension's
    # own falsification recipe.
    row = UnitProgressFactory(student=staff, unit=unit, completed=True)
    stamped_at = UnitProgress.objects.get(pk=row.pk).completed_at

    # (3) seen STILL reports the synthetic response and STILL writes nothing.
    r2 = client.post(
        _seen_url("pp", unit.pk), data=json.dumps(ids), content_type="application/json"
    )
    assert r2.json() == {
        "seen_element_ids": [],
        "completed": False,
        "completed_at": None,
    }
    row.refresh_from_db()
    # Name the fields; do not compare whole objects (updated_at is auto_now).
    assert row.seen_element_ids == []  # the POSTed ids were not merged
    assert row.completed is True
    assert row.completed_at == stamped_at
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_courses_progress.py::test_previewer_seen_no_write_and_ignores_stored_completion -v`
Expected: PASS.

- [ ] **Step 3: Falsify step (1) — the pre-existing half**

Temporarily delete the `if not is_enrolled(request.user, course):` early return in `seen`. Run the same command.
Expected: FAIL. **Restore** and re-run.

This recipe removes code *outside* this diff on purpose: the test's job is to catch a future implementer "finishing the job" by lifting both gates.

- [ ] **Step 4: Falsify steps (2)–(3) — the extension's own recipe, made null-safe**

Temporarily replace `seen`'s early return with an echo of the stored row. **It must be null-safe**, or it reddens step (1) too and the recipe loses the property it was added for — at step (1) the viewer deliberately has no row, and `_progress_json` dereferences its argument unconditionally:

```python
    if not is_enrolled(request.user, course):
        row = UnitProgress.objects.filter(student=request.user, unit=node).first()
        return JsonResponse(
            _progress_json(row)
            if row
            else {"seen_element_ids": [], "completed": False, "completed_at": None}
        )
```

Run the same command.
Expected: FAIL at step (3), while step (1) still passes. **Restore** the original early return and re-run.

- [ ] **Step 5: Correct the `seen` comment**

Replace `courses/views.py:652` (`# untracked preview: no write, synthetic canonical response`) with:

```python
        # ASYMMETRY, deliberate: SCROLL-tracking is not recorded for a previewer, but
        # completion via the explicit button IS (see complete()). So "untracked" is
        # narrow -- their practice state and their completion both persist; only this
        # signal is dropped. The synthetic response therefore reports completed=False
        # even when a stored row says True: this endpoint's contract is "here is your
        # scroll-tracking", not "here is your progress row". Do not "fix" it to echo
        # the stored row -- that breaks
        # tests/test_courses_progress.py::test_previewer_seen_no_write_and_ignores_stored_completion
        # and quietly turns a write-free endpoint into a state reporter.
```

- [ ] **Step 6: Check the tripwire and commit**

Run: `uv run pytest tests/test_courses_progress.py tests/test_element_state_write_routes.py -v` and `uv run ruff check courses/views.py tests/test_courses_progress.py`
Expected: all pass, lint clean.

```bash
git add courses/views.py tests/test_courses_progress.py
git commit -m "test(courses): pin seen's enrolled-only asymmetry against a stored completion"
```

---

### Task 8: Downstream chrome actually lights up

Spec Testing §9 — the payoff that justifies fixing rather than hiding the button. Two different pages, two GETs, both issued **as the previewer**.

**Files:**
- Modify: `tests/test_courses_progress.py` (one new test)

- [ ] **Step 1: Write the test**

```python
@pytest.mark.django_db
def test_previewer_mark_lights_outline_badge_and_footer_counter(client):
    import re

    from bs4 import BeautifulSoup

    staff = make_login(client, "staff9")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="p9")
    # ContentNode.obligatory defaults to True, which the footer half REQUIRES:
    # course_progress.done sums required_done, set only when is_obligatory_lesson(node).
    unit, ids = _make_unit_with_elements(course, 1)

    # PROVENANCE: the row must come from the previewer's OWN POST. Seeding it with
    # UnitProgressFactory(completed=True) yields a green test whose diff-local
    # falsification below cannot redden.
    client.post(reverse("courses:complete", kwargs={"slug": "p9", "node_pk": unit.pk}))

    # (1) The course outline page -> the unit's own row carries the done marker.
    r_outline = client.get(reverse("courses:course_outline", kwargs={"slug": "p9"}))
    assert r_outline.status_code == 200
    body = r_outline.content.decode()
    # TEMPERED pattern: it cannot cross into a later <li data-unit="...">, which a
    # naive `data-unit="pk"[^>]*>` or `.*?` form would do, matching another unit's
    # marker. [\s\S] (not .) because the two tokens sit on different lines.
    assert re.search(
        rf'data-unit="{unit.pk}"(?:(?!data-unit=)[\s\S])*?outline-unit--done', body
    )

    # (2) The lesson unit page -> the footer's course-progress counter is non-zero.
    r_lesson = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "p9", "node_pk": unit.pk})
    )
    assert r_lesson.status_code == 200
    # Read it through the real view's context rather than parsing HTML:
    # full_lesson_render_context sets ctx["unit_nav"] = build_unit_nav(...).
    assert r_lesson.context["unit_nav"]["course_progress"]["done"] > 0
```

Do **not** call `build_unit_nav(...)` standalone instead of issuing the GET — it is a pure function, so that would skip the view-level wiring this test's whole claim is about.

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_courses_progress.py::test_previewer_mark_lights_outline_badge_and_footer_counter -v`
Expected: PASS. (`courses:course_outline` takes only `slug` — `courses/urls.py:15`.)

- [ ] **Step 3: Falsify (the one that matters)**

Temporarily re-wrap the write in `complete` in `if is_enrolled(request.user, course):`. Run the same command.
Expected: FAIL — proving the test is non-vacuous with respect to *this* change. **Restore** and re-run.

- [ ] **Step 4: Commit**

```bash
git add tests/test_courses_progress.py
git commit -m "test(courses): pin that a previewer's mark lights their own progress chrome"
```

---

### Task 9: Containment — an off-roster previewer stays invisible to teachers

Spec Testing §10. This is the claim the whole "fix rather than hide" decision rests on, and it has **two** distinct mechanisms that must both be driven.

**Files:**
- Modify: `tests/test_courses_progress.py` (one new test)

- [ ] **Step 1: Write the test**

```python
@pytest.mark.django_db
def test_off_roster_previewer_absent_from_matrix_and_drilldown(client):
    from django.test import Client

    from courses.rollups import build_progress_matrix
    from grouping.scoping import students_in_scope

    # Two DISTINCT users: the course owner is itself one of test 5's can_access
    # routes, so casting one user as both silently makes the session switch a no-op.
    previewer = make_login(client, "prev10")
    previewer.is_staff = True
    previewer.save()
    resolver_client = Client()
    resolver = make_login(resolver_client, "owner10")
    # PIN THE FIXTURE, not just the role: CourseFactory sets no owner, so a "resolver"
    # never assigned as one is neither PA nor owner, can_review_course returns False,
    # and the drill-down 404s UNCONDITIONALLY -- step 2 would pass for the wrong
    # reason and step 4 would fail against correct behaviour.
    course = CourseFactory(slug="p10", owner=resolver)
    unit, ids = _make_unit_with_elements(course, 1)  # obligatory lesson by default

    # A genuinely enrolled control student: without one the roster is empty, rows ==
    # [], and "the previewer is not a row" is true of an empty matrix rather than of
    # any scoping.
    control = make_verified_user(username="control10", email="c10@test.example.com")
    EnrollmentFactory(student=control, course=course)

    # (1) The previewer marks the unit done, via their OWN POST, while off-roster.
    client.post(reverse("courses:complete", kwargs={"slug": "p10", "node_pk": unit.pk}))

    # (2) Matrix: populated, but omits the previewer. Re-resolve students_in_scope
    # freshly for each use -- it returns a lazy queryset that caches on evaluation.
    matrix = build_progress_matrix(
        course, list(students_in_scope(resolver, course, "all"))
    )
    row_students = [row["student"] for row in matrix["rows"]]
    assert control in row_students
    assert previewer not in row_students
    # The control's percent must be NOT-NONE rather than non-zero: they hold no
    # completion, so _pct(0, total) gives a legitimate 0. None is what an empty
    # all_lesson_pks would produce, so None is the discriminator.
    control_row = next(r for r in matrix["rows"] if r["student"] == control)
    assert control_row["overall"]["percent"] is not None

    #     Drill-down: a different mechanism (view-level resolution, no roster filter).
    drill_url = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": "p10", "student_pk": previewer.pk},
    )
    assert resolver_client.get(drill_url).status_code == 404

    # (3) Enroll the previewer.
    EnrollmentFactory(student=previewer, course=course)

    # (4) The drill-down now resolves.
    assert resolver_client.get(drill_url).status_code == 200
```

- [ ] **Step 2: Add the `make_verified_user` import if absent**

```python
from tests.factories import make_verified_user
```

- [ ] **Step 3: Run it**

Run: `uv run pytest tests/test_courses_progress.py::test_off_roster_previewer_absent_from_matrix_and_drilldown -v`
Expected: PASS. (`courses:manage_analytics_student` takes `slug` + `student_pk` — `courses/urls.py:295-297`; `build_progress_matrix(course, students, expanded=frozenset())` returns rows shaped `{"student": …, "cells": […], "overall": …}` — `courses/rollups.py:566`.)

- [ ] **Step 4: Falsify**

Temporarily move the `EnrollmentFactory(student=previewer, course=course)` call to just before step (2). Run the same command.
Expected: **both** step-2 assertions go RED (the previewer becomes a matrix row, and the drill-down 200s), proving each discriminates. **Restore** the ordering and re-run.

Do **not** reach for "delete the `student__in=students` filter" as a falsification — that filter only narrows a lookup dict, so deleting it leaves the assertion green. The containment is the `students` **argument**.

The gradebook export is **exempt in writing**: it resolves its students through the identical `students_in_scope` call this test already drives, with no roster logic of its own in between.

- [ ] **Step 5: Commit**

```bash
git add tests/test_courses_progress.py
git commit -m "test(courses): pin both containment mechanisms against an off-roster previewer"
```

---

### Task 10: Double POST is idempotent and issues no second UPDATE

Spec Testing §11. The load-bearing assertion is the query one — it is the only one a guard deletion reddens.

**Files:**
- Modify: `tests/test_courses_progress.py` (one new test)

- [ ] **Step 1: Write the test**

```python
@pytest.mark.django_db
def test_double_complete_post_is_idempotent_and_issues_no_second_update(client):
    import re

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from courses.models import UnitProgress

    staff = make_login(client, "staff11")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="p11")
    unit, ids = _make_unit_with_elements(course, 1)
    url = reverse("courses:complete", kwargs={"slug": "p11", "node_pk": unit.pk})

    # Issued directly by the test client: after the first POST the pill replaces the
    # form, so a second POST is not reachable through the UI -- but a double submit,
    # a back-button or a retried request all produce it.
    client.post(url)
    first = UnitProgress.objects.get(student=staff, unit=unit)
    stamped_at = first.completed_at

    with CaptureQueriesContext(connection) as ctx:
        client.post(url)

    assert UnitProgress.objects.filter(student=staff, unit=unit).count() == 1
    row = UnitProgress.objects.get(student=staff, unit=unit)
    assert row.completed_at == stamped_at  # assert on the DB row: the 302 has no body
    # THE load-bearing assertion. Pin the match: Postgres captures
    # `UPDATE "courses_unitprogress" SET ...` with a QUOTED identifier, so a naive
    # `'UPDATE courses_unitprogress' in sql` never matches and passes vacuously.
    # Target UPDATE on this one table, never "no writes": the SELECTs and the
    # SAVEPOINT/RELEASE traffic (a pytest artefact of django_db's open transaction)
    # are expected and correct.
    assert not [
        q
        for q in ctx.captured_queries
        if re.search(r'update\s+"?courses_unitprogress"?', q["sql"], re.I)
    ]
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_courses_progress.py::test_double_complete_post_is_idempotent_and_issues_no_second_update -v`
Expected: PASS.

- [ ] **Step 3: Falsify**

Temporarily delete the `if not progress.completed:` guard in `complete` (always assign and save). Run the same command.
Expected: FAIL on the query assertion **and only that one** — which is precisely why it is the assertion that matters. **Restore** and re-run.

Do **not** substitute "an `element_state` key written between the two POSTs survives" as the assertion: `get_or_create` re-reads the row, so the in-memory instance already carries that key and a guardless `save()` writes it straight back — that assertion stays green with the guard deleted.

- [ ] **Step 4: Commit**

```bash
git add tests/test_courses_progress.py
git commit -m "test(courses): pin double-POST idempotence via the query trail"
```

---

### Task 11: Enrollment transition (documents a decision, guards no code)

Spec Testing §8. This pins an accepted boundary so a future change cannot silently reverse it.

**Files:**
- Modify: `tests/test_courses_progress.py` (one new test)

- [ ] **Step 1: Write the test**

```python
@pytest.mark.django_db
def test_previewer_completion_becomes_learner_progress_on_enrollment(client):
    """DOCUMENTS the 'Enrollment transition' decision (spec: Accepted side effects).

    This is not a safety guard -- it guards no code, and it is exempt from the
    falsification rule in writing, because the mutation would have to INVENT an
    enrollment hook that does not exist (Enrollment has no post_save receiver, and
    this test enrolls via EnrollmentFactory, not through add_students_to_group).
    A recipe with no insertion point is a wish, not a falsification.
    """
    from django.test import Client

    from courses.models import UnitProgress
    from courses.rollups import build_progress_matrix
    from grouping.scoping import students_in_scope

    previewer = make_login(client, "prev8")
    previewer.is_staff = True
    previewer.save()
    resolver_client = Client()
    resolver = make_login(resolver_client, "owner8")
    # The resolver must be the course OWNER or a PA: students_in_scope(..., "all")
    # falls through to reviewable_students, which derives from Enrollment only on
    # that branch -- for a group teacher it derives from GroupMembership, and
    # enrolling the previewer would add them to neither queryset.
    course = CourseFactory(slug="p8", owner=resolver)
    unit, ids = _make_unit_with_elements(course, 1)  # obligatory lesson

    control = make_verified_user(username="control8", email="c8@test.example.com")
    EnrollmentFactory(student=control, course=course)

    client.post(reverse("courses:complete", kwargs={"slug": "p8", "node_pk": unit.pk}))

    # BEFORE: absent from the roster and from the matrix; the control discriminates.
    before_roster = list(students_in_scope(resolver, course, "all"))
    assert previewer not in before_roster
    assert control in before_roster
    before_rows = build_progress_matrix(course, list(before_roster))["rows"]
    assert previewer not in [r["student"] for r in before_rows]
    assert control in [r["student"] for r in before_rows]

    EnrollmentFactory(student=previewer, course=course)

    # AFTER: re-resolve freshly. A queryset caches its rows on first evaluation, so
    # reusing before_roster here would read the stale cache and fail against CORRECT
    # behaviour.
    after_roster = list(students_in_scope(resolver, course, "all"))
    assert previewer in after_roster
    after_rows = build_progress_matrix(course, list(after_roster))["rows"]
    previewer_row = next(r for r in after_rows if r["student"] == previewer)
    # Non-zero is achievable here (unlike test 10) precisely because the previewer
    # DOES hold the completion.
    assert previewer_row["overall"]["percent"] > 0

    # The row survived the transition unchanged.
    assert UnitProgress.objects.get(student=previewer, unit=unit).completed is True
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_courses_progress.py::test_previewer_completion_becomes_learner_progress_on_enrollment -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_courses_progress.py
git commit -m "test(courses): document the enrollment-transition boundary"
```

---

### Task 12: Definition-of-done sweep

Everything the DoD requires that is not a single test: the pre-existing guards, the full suite, lint, migrations, the e2e trio, and the comment-edit gate.

**Files:**
- No new edits expected. Fix whatever the runs surface.

- [ ] **Step 1: Confirm the pre-existing no-spurious-row guard is still green**

Run: `uv run pytest courses/tests/test_markdone_render.py::test_passive_non_enrolled_viewer_gets_no_progress_row -v`
Expected: PASS.

This test already exists in a **different package** (`courses/tests/`, not the top-level `tests/`). Do not write a duplicate of it — it is listed so you don't. Running its recipe (change the non-enrolled read to `get_or_create` → RED) is optional.

- [ ] **Step 2: Confirm the enrolled path is unregressed**

Run: `uv run pytest tests/test_courses_progress.py::test_seen_merges_and_autocompletes tests/test_courses_progress.py::test_zero_element_unit_completes_only_via_fallback -v`
Expected: PASS.

These are pre-existing regression protection, **exempt from falsification in writing**: the diff does not change their behaviour, so there is no honest RED recipe.

- [ ] **Step 3: Full non-e2e suite**

Run: `uv run pytest -n auto`
Expected: green, no new failures against the base.

**One caveat:** `tests/test_html_element.py::test_lesson_html_render_query_count_invariant` is recorded as already failing **in isolation** on master. Since this change touches `build_lesson_context`, it is the test an implementer will wrongly blame. `progress = state_row` is a bare assignment of an already-fetched row and issues **zero** additional queries — so reproduce any failure there **on the base commit** before attributing it to this diff. Likewise, rule out a cross-worktree test-DB collision before blaming the diff.

- [ ] **Step 4: Lint and migrations**

Run: `uv run ruff check` and `uv run ruff format --check`
Expected: clean.

Run: `uv run python manage.py makemigrations --check` and `uv run python manage.py check`
Expected: clean (trivially — no model change).

- [ ] **Step 5: Existing e2e over the touched surface**

Run: `uv run pytest -m e2e tests/test_e2e_slideshow.py tests/test_e2e_unit_head_layout.py tests/test_e2e_unit_nav.py`

**The `-m e2e` marker is mandatory** — without it the entire e2e set is silently deselected and pytest exits 5, which reads like a pass.
Expected: green and unchanged. All three exercise the enrolled path, which this change does not alter.

No **new** e2e test is required: the change has no client-side component, and the full round trip is observable at the view/template layer by tasks 1, 3 and 5.

- [ ] **Step 6: Assemble the comment-edit gate for the PR description**

No automated gate covers the seven comment edits, and the atomic-block re-fetch they document is the one piece of code in this diff no test can protect. Collect all seven bodies verbatim into the PR description under a heading naming them as the unguarded half of the diff:

1. **New** — `complete`'s atomic block (Task 1). Verify it states the **ordering** rule: the row is re-fetched *under* the lock because `FOR UPDATE` serialises concurrent writers but cannot protect a writer whose read preceded the lock. It must **not** say a lock "only excludes writers that also take it" — that is false on PostgreSQL and would plant a confident falsehood where nothing tests.
2. **New** — `complete`'s access check (Task 1).
3. **Correction** — `element_state_save`, `courses/views.py` ≈:784-788 (Task 1).
4. **Correction** — `build_lesson_context`'s docstring, ≈:273-275 (Task 3).
5. **Correction** — the `elif user.is_authenticated` branch, ≈:396-398 (Task 3).
6. **Correction** — `seen`, ≈:652 (Task 7).
7. **Correction** — `templates/courses/_lesson_article.html:8-11` (Task 3).

- [ ] **Step 7: Record the falsification roster in the PR description**

Confirm each of these was driven RED and restored: **1(a), 1(b), 2, 3 (step 1), 3 (steps 2–3), 5(a)–(d), 6(a), 6(b), 7, 9, 10, 11**.

Exempt in writing, with reasons already stated: **8** (no insertion point for the mutation), **12** (pre-existing regression protection), **1(c)** entirely, and **1(b)'s blob assertions**. Test **4** is pre-existing and unchanged.

Include the spec-label → test-function mapping, since the roster is written in spec labels and the DoD is checked against them.

- [ ] **Step 8: Final commit if anything changed**

```bash
git add -A
git commit -m "chore(courses): DoD sweep for previewer unit completion"
```

If nothing changed, skip the commit — do not create an empty one.
