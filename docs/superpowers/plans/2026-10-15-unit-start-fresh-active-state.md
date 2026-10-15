# Unit-page "Start fresh" active-state Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The unit page's "Start fresh" control keeps rendering where it renders today, but is INACTIVE (greyed, no `href`) until this viewer has stored practice state, and flips to ACTIVE live, without a reload, the first time a save stores something.

**Architecture:** The server render branches on the `element_state` dict `build_lesson_context` already computes. The four client-side write sites (`state.js` `saveFlag`, `reveal.js` `save`, `markdone.js`, `question.js`) dispatch one `document` event, `libli:state-saved`, after a successful save that stored something. `question.js` learns this from a new `check_answer` response header. A new `reset_control.js` listener activates the control in place. Source-level drift guards pin the event name, the header name, the dispatch placement and the writer set.

**Tech Stack:** Django templates + views, vanilla JS (IIFE, `"use strict"`, `var`), token CSS in `core/static/core/css/app.css`, pytest + pytest-django, BeautifulSoup (`bs4`, already a dependency), Playwright sync API for e2e (`-m e2e`).

**Spec:** `docs/superpowers/specs/2026-10-15-unit-start-fresh-active-state-design.md`. Read it before starting any task. Its owner-decisions table (D1'–D7) is VERBATIM and must not be reversed.

## Global Constraints

- Presence unchanged (D1'): the control renders iff `has_stateful_elements`. Do not touch that computation (`courses/views.py:519-522`).
- Active iff `element_state` (the context dict) is non-empty (D2); zero new queries.
- Inactive markup (D3): the same `<a>` with the same classes; no `href`; `role="link"`, `aria-disabled="true"`, `title` = "Nothing to clear yet", `data-reset-control`, `data-reset-href`. No `tabindex` (deliberately unfocusable).
- Active markup = today's link **byte-for-byte unchanged**, with NO `data-reset-*` attributes.
- Polish msgstr for "Nothing to clear yet": **`Nie ma nic do wyczyszczenia`** (owner-confirmed; no trailing period).
- Event name: `libli:state-saved`, dispatched on `document`, as `new CustomEvent("libli:state-saved")`.
- Header name: `X-Libli-State-Saved`, value `"1"`, as Python constant `STATE_SAVED_HEADER` in `courses/views.py`.
- No live reverse transition (D6). Outline untouched. Unit page only.
- Run tools via `uv run` (bare `pytest`/`ruff`/`python` are not on PATH). **Never pass `-q`** to pytest (`addopts` already has it; doubling it hides the summary). Start the test DB first: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. One pytest run at a time. e2e needs `-m e2e`.
- Before each commit: `uv run ruff check .` AND `uv run ruff format --check .` (separate CI gates).
- Django `{# #}` comments are single-line only; multi-line comments use `{% comment %}…{% endcomment %}`.
- Never use `git checkout -- <file>` to revert a mutant; revert by hand-editing, then confirm with `git diff`.
- Falsify: each new test must be seen RED against the named mutant, then GREEN. Read the actual `git diff` of every mutant before running.

## Review Focus

1. **A non-enrolled previewer (teacher) with no stored state** sees the inactive control, and their own saves activate it. Previewers persist and read their own state (`views.py:536-543`). Covered by Task 2 Step 1 (`test_previewer_without_state_sees_inactive_control`).
2. **A no-JS mark-done POST redirects back to the unit page**, where the server render must show ACTIVE. Covered by Task 2 Step 1 (`test_active_after_no_js_markdone_post`).
3. **The no-JS `check_answer` full-page branch** re-renders `lesson_unit.html` via `full_lesson_render_context`, which must still show the right state after a non-empty answer. Covered by Task 2 Step 1 (`test_no_js_check_answer_rerender_shows_active_control`), header half by Task 1 (`test_no_js_branch_sets_no_header`).
4. **A unit with BOTH a capability element and an orphaned blob** for a deleted element renders ACTIVE (reset really clears it). Covered by Task 2 Step 1 (`test_orphaned_blob_on_capability_unit_is_active`).
5. **The quiz-results page loads `question.js`** with no reset control. The dispatch and listener must be inert there, not throw. Covered by Task 3: the listener is null-safe by construction (`querySelectorAll`), and `reset_control.js` is not loaded on `quiz_results.html` (asserted in Task 3 Step 1, `test_reset_control_script_only_on_lesson_page`).

---

### Task 1: `check_answer` reports a stored answer via a response header

**Files:**
- Modify: `courses/views.py` (`_wants_fragment` at ~`:102`; `check_answer` at `:1120-1188`)
- Test: `courses/tests/test_state_saved_header.py` (create)

**Interfaces:**
- Produces: `courses.views.STATE_SAVED_HEADER == "X-Libli-State-Saved"`. Every `check_answer` **fragment** response carries `STATE_SAVED_HEADER: "1"` iff the question is `RESTORABLE_IN_LESSON` and the answer was non-empty (i.e. `save_element_state` stored a blob). The no-JS full-page response never carries it.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_state_saved_header.py`:

```python
"""check_answer tells question.js whether it STORED practice state (spec §4).

The header is the only signal question.js gets: the response body is HTML. It must be
set on BOTH fragment return points -- the INLINE_LESSON_FEEDBACK full-element render
(choice, short text, ...) and the _question_feedback.html render (extended response).
"""

import pytest
from django.urls import reverse

from courses import views
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db

H = views.STATE_SAVED_HEADER


def _enrolled(client):
    student = make_verified_user()
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    return student, course, unit


def _check_url(unit, element_pk):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk, "element_pk": element_pk},
    )


def _choice(unit):
    q = ChoiceQuestionElement.objects.create(stem="Pick", multiple=False)
    right = Choice.objects.create(question=q, text="A", is_correct=True, order=0)
    Choice.objects.create(question=q, text="B", is_correct=False, order=1)
    row = Element.objects.create(unit=unit, content_object=q)
    return row, right


def test_header_constant_is_the_agreed_name():
    assert H == "X-Libli-State-Saved"


def test_inline_type_nonempty_answer_sets_header(client):
    _s, _c, unit = _enrolled(client)
    row, right = _choice(unit)
    assert ChoiceQuestionElement.INLINE_LESSON_FEEDBACK is True  # anti-vacuity
    r = client.post(
        _check_url(unit, row.pk), {"choice": [right.pk]}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert r.status_code == 200
    assert r.headers.get(H) == "1"


def test_non_inline_restorable_type_nonempty_answer_sets_header(client):
    _s, _c, unit = _enrolled(client)
    q = ExtendedResponseQuestionElement.objects.create(stem="Explain")
    row = Element.objects.create(unit=unit, content_object=q)
    # anti-vacuity: this is the _question_feedback.html return point
    assert not ExtendedResponseQuestionElement.INLINE_LESSON_FEEDBACK
    assert ExtendedResponseQuestionElement.RESTORABLE_IN_LESSON
    r = client.post(
        _check_url(unit, row.pk), {"answer": "some words"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert r.status_code == 200
    assert r.headers.get(H) == "1"


def test_empty_answer_sets_no_header(client):
    _s, _c, unit = _enrolled(client)
    row, _right = _choice(unit)
    r = client.post(_check_url(unit, row.pk), {}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 200
    assert H not in r.headers


def test_non_restorable_question_sets_no_header(client, monkeypatch):
    _s, _c, unit = _enrolled(client)
    q = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = Element.objects.create(unit=unit, content_object=q)
    monkeypatch.setattr(ShortTextQuestionElement, "RESTORABLE_IN_LESSON", False)
    r = client.post(
        _check_url(unit, row.pk), {"answer": "paris"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert r.status_code == 200
    assert H not in r.headers


def test_no_js_branch_sets_no_header(client):
    # The no-JS full-page branch never carries the header (no client reads it). The
    # render half of Review Focus 3 lives in test_reset_controls.py (Task 2).
    _s, _c, unit = _enrolled(client)
    row, right = _choice(unit)
    r = client.post(_check_url(unit, row.pk), {"choice": [right.pk]})
    assert r.status_code == 200
    assert H not in r.headers
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest courses/tests/test_state_saved_header.py -v`
Expected: every test errors or fails with `AttributeError: module 'courses.views' has no attribute 'STATE_SAVED_HEADER'`.

- [ ] **Step 3: Implement**

In `courses/views.py`, directly above `def _wants_fragment(request):`, add:

```python
# Set on a check_answer FRAGMENT response iff it stored practice state, so question.js
# (whose body is HTML, not a JSON echo) can announce `libli:state-saved` and activate
# the unit page's "Start fresh" control. tests/test_state_saved_event_guard.py checks
# question.js reads exactly this name.
STATE_SAVED_HEADER = "X-Libli-State-Saved"
```

In `check_answer`, replace the `RESTORABLE_IN_LESSON` block and the `_wants_fragment` block (`views.py:1136-1170`) with:

```python
    stored_answer = False
    if getattr(question, "RESTORABLE_IN_LESSON", False):
        # Practice-state (slice 3): persist the answer only — never the verdict; it
        # is re-marked on restore. Empty answer clears any prior stored answer.
        if answer_is_empty(answer):
            save_element_state(request.user, node, element.pk, None)
        else:
            save_element_state(
                request.user, node, element.pk, {"answer": answer_to_json(answer)}
            )
            stored_answer = True

    if _wants_fragment(request):
        if question.INLINE_LESSON_FEEDBACK:
            # Choice / fill-blank: return the full re-rendered element so the inline
            # feedback lands on the options / blanks (question.js swaps the form
            # body). render() sets reveal_template=None for lesson mode -> no bottom
            # reveal list.
            response = HttpResponse(
                question.render(
                    element=element,
                    mode="lesson",
                    selected_ids=selected_ids(answer),
                    submitted_values=(
                        None if isinstance(answer, (set, frozenset)) else answer
                    ),
                    mark_result=result,
                    feedback_for_pk=element.pk,
                )
            )
        else:
            response = render(
                request,
                "courses/elements/_question_feedback.html",
                question.feedback_context(result),
            )
        # BOTH fragment return points, from ONE flag (spec §4).
        if stored_answer:
            response[STATE_SAVED_HEADER] = "1"
        return response
```

Leave the no-JS branch below it unchanged.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest courses/tests/test_state_saved_header.py courses/tests/test_question_restore.py -v`
Expected: all PASS.

- [ ] **Step 5: Falsify**

Apply each mutant by hand, confirm with `git diff courses/views.py`, run the file, see RED, then revert by hand:
1. Move `if stored_answer: response[...] = "1"` inside the `if question.INLINE_LESSON_FEEDBACK:` branch only → `test_non_inline_restorable_type_nonempty_answer_sets_header` RED.
2. Set `stored_answer = True` also in the `answer_is_empty` branch → `test_empty_answer_sets_no_header` RED.
3. Set the header on the no-JS `render(...)` too → `test_no_js_branch_sets_no_header` RED.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check courses/views.py courses/tests/test_state_saved_header.py
uv run ruff format --check courses/views.py courses/tests/test_state_saved_header.py
git add courses/views.py courses/tests/test_state_saved_header.py
git commit -m "feat(check_answer): X-Libli-State-Saved header when an answer is stored"
```

---

### Task 2: Server render — inactive vs active control, i18n, decision records

**Files:**
- Modify: `templates/courses/_lesson_article.html:31-36`
- Modify: `courses/views.py:509-519` (comment only)
- Modify: `courses/tests/test_reset_controls.py` (new tests; docstrings of existing presence tests and of `test_an_orphaned_blob_does_not_bring_the_reset_link_back`)
- Modify: `docs/superpowers/specs/2026-07-25-start-fresh-only-on-stateful-units-design.md` (under its D1, ~`:38`)
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po`, and both `.mo` files

**Interfaces:**
- Consumes: the `element_state` and `has_stateful_elements` context keys (existing).
- Produces (DOM contract for Tasks 3–4): the inactive control is
  `a.lesson-unit__reset[data-reset-control][aria-disabled="true"][role="link"][title][data-reset-href]` with no `href`. The active control is today's `<a class="btn btn--ghost btn--small lesson-unit__reset" href="…">` with no `data-reset-*`, `role`, `aria-disabled` or `title`.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_reset_controls.py`. Add the imports at the top, in sorted position: `from bs4 import BeautifulSoup`, `from courses.models import Choice`, `from courses.models import ChoiceQuestionElement`.

```python
def _control(body):
    """The ONE unit-head reset control, parsed -- never a substring check: the reset
    URL also appears in data-reset-href, so `url in body` passes in BOTH states."""
    soup = BeautifulSoup(body, "html.parser")
    found = soup.select(".lesson-unit__head .lesson-unit__reset")
    assert len(found) == 1, f"expected exactly one control, found {len(found)}"
    return found[0]


def _lesson(client, course, unit):
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    return r.content.decode()


def _expected_href(course, unit):
    return (
        _reset_url(course, unit)
        + "?next="
        + reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    )


def test_capability_unit_without_state_renders_inactive_control(client):
    course, unit = make_course_with_unit()
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    _login(client, course)
    a = _control(_lesson(client, course, unit))
    assert not a.has_attr("href")
    assert a["aria-disabled"] == "true"
    assert a["role"] == "link"
    assert a["title"] == "Nothing to clear yet"
    assert a.has_attr("data-reset-control")
    assert a["data-reset-href"] == _expected_href(course, unit)
    assert not a.has_attr("tabindex")
    assert a.get_text(strip=True) == "Start fresh"


def test_capability_unit_with_state_renders_todays_active_link(client):
    course, unit = make_course_with_unit()
    md = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, md)
    item = MarkDoneItem.objects.create(element=md, content="a")
    student = _login(client, course)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"items": [item.pk]}}
    )
    a = _control(_lesson(client, course, unit))
    assert a["href"] == _expected_href(course, unit)
    for attr in ("aria-disabled", "role", "title", "data-reset-control", "data-reset-href"):
        assert not a.has_attr(attr), attr
    assert a["class"] == ["btn", "btn--ghost", "btn--small", "lesson-unit__reset"]


def test_orphaned_blob_on_capability_unit_is_active(client):
    # Review Focus 4: a blob for a DELETED element on a unit that still has a
    # capability element is real stored state -- the reset clears it -- so ACTIVE.
    course, unit = make_course_with_unit()
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    student = _login(client, course)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={"999999": {"items": [1]}}
    )
    a = _control(_lesson(client, course, unit))
    assert a["href"] == _expected_href(course, unit)


def test_previewer_without_state_sees_inactive_control(client):
    # Review Focus 1: a non-enrolled viewer who can access the course (the owner).
    course, unit = make_course_with_unit()
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    client.force_login(course.owner)
    a = _control(_lesson(client, course, unit))
    assert a["aria-disabled"] == "true"
    assert not a.has_attr("href")


def test_active_after_no_js_markdone_post(client):
    # Review Focus 2: the no-JS form posts, redirects to the unit page, and the
    # server render must now be ACTIVE.
    course, unit = make_course_with_unit()
    md = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, md)
    item = MarkDoneItem.objects.create(element=md, content="a")
    _login(client, course)
    r = client.post(
        reverse("courses:element_state_save", args=[course.slug, unit.pk]),
        {"element": row.pk, "item": [item.pk]},
        follow=True,
    )
    assert r.status_code == 200
    a = _control(r.content.decode())
    assert a["href"] == _expected_href(course, unit)


def test_no_js_check_answer_rerender_shows_active_control(client):
    # Review Focus 3, render half (header half lives in test_state_saved_header.py).
    course, unit = make_course_with_unit()
    q = ChoiceQuestionElement.objects.create(stem="Pick", multiple=False)
    right = Choice.objects.create(question=q, text="A", is_correct=True, order=0)
    row = Element.objects.create(unit=unit, content_object=q)
    _login(client, course)
    r = client.post(
        reverse("courses:check_answer", args=[course.slug, unit.pk, row.pk]),
        {"choice": [right.pk]},
    )
    assert r.status_code == 200
    a = _control(r.content.decode())
    assert a["href"] == _expected_href(course, unit)


def test_inactive_title_is_translated_in_polish(client):
    from django.utils import translation

    with translation.override("pl"):
        assert translation.gettext("Nothing to clear yet") == "Nie ma nic do wyczyszczenia"
```

Before relying on `course.owner` (Review Focus 1), check that `make_course_with_unit` (`tests/factories.py`) gives the course an owner who can access it. If it doesn't, build the previewer the way `courses/tests/test_reset_controls.py` or another test in the repo already makes a non-enrolled staff viewer. Grep `force_login(` in `courses/tests/` for an existing teacher/owner helper and reuse it. Also check whether the no-JS markdone POST shape matches what `element_state_save`'s form branch expects (`views.py:1030-1080`: field names `element` and `item`). Adjust to the real field names if they differ.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest courses/tests/test_reset_controls.py -v`
Expected: the inactive / previewer / Polish tests FAIL (the control has an `href`, and there is no translation). The active-state tests may already pass, since today's template is always active. That is expected; they are pinned against the Step 5 mutant "render inactive unconditionally".

- [ ] **Step 3: Implement the template**

Replace `templates/courses/_lesson_article.html:31-36` (the `{% if has_stateful_elements %}` block) with:

```django
    {% if has_stateful_elements %}
      {% comment %}Presence keys on CAPABILITY (spec D1'); enabled-ness on THIS viewer's
         stored state (D2). The inactive branch keeps the same element and classes so the
         head row never shifts; reset_control.js flips it live on `libli:state-saved`.
         The active branch is today's link, unchanged (D3).{% endcomment %}
      {% if element_state %}
      <a class="btn btn--ghost btn--small lesson-unit__reset"
         href="{% url 'courses:progress_reset' slug=course.slug node_pk=unit.pk %}?next={% url 'courses:lesson_unit' slug=course.slug node_pk=unit.pk %}">
        {% trans "Start fresh" %}
      </a>
      {% else %}
      <a class="btn btn--ghost btn--small lesson-unit__reset" role="link" aria-disabled="true"
         title="{% trans 'Nothing to clear yet' %}" data-reset-control
         data-reset-href="{% url 'courses:progress_reset' slug=course.slug node_pk=unit.pk %}?next={% url 'courses:lesson_unit' slug=course.slug node_pk=unit.pk %}">
        {% trans "Start fresh" %}
      </a>
      {% endif %}
    {% endif %}
```

- [ ] **Step 4: Update the views comment**

In `courses/views.py`, the comment above `has_stateful_elements` (`:509-518`): keep it, and append these lines after its first sentence (`… (spec D1).`):

```python
    # That rule now governs PRESENCE only: the template ALSO reads `element_state`
    # (below) to render the control inactive until this viewer has stored something
    # (spec 2026-10-15-unit-start-fresh-active-state, D2).
```

- [ ] **Step 5: Update existing tests' docstrings / comments**

In `courses/tests/test_reset_controls.py`:
- In `test_lesson_page_links_to_the_reset_interstitial`, `test_lesson_page_shows_the_reset_link_for_an_element_nested_in_a_tab`, `test_lesson_page_shows_the_reset_link_on_a_question_only_unit` and `test_views_calls_the_state_helper…`, add as the first comment line: `# PRESENCE only (spec 2026-10-15 D1'): with no stored state the URL appears in data-reset-href of the INACTIVE control. Active-ness is pinned by the _control() tests below.`
- In `test_an_orphaned_blob_does_not_bring_the_reset_link_back`, edit its docstring: replace the sentence beginning "The union rule…" through "…rather than an accident." with: `Presence is still capability-only under the 2026-10-15 revision (D1'); enabled-ness now reads stored state (D2), but only INSIDE the capability gate, so an orphaned blob on a non-capability unit still renders no control. This test pins that.` Leave the assertions unchanged.

- [ ] **Step 6: Supersede the July D1 record**

In `docs/superpowers/specs/2026-07-25-start-fresh-only-on-stateful-units-design.md`, directly after the `**D1 — Gate on capability, not on stored state.**` paragraph (its first paragraph, ending "…stored blob for this unit*."), insert:

```markdown
> **Superseded in part (2026-10-15).** See
> `docs/superpowers/specs/2026-10-15-unit-start-fresh-active-state-design.md`. PRESENCE still keys
> on capability, as below. ENABLED-NESS now keys on this viewer's stored state: the control renders
> inactive (greyed, no `href`) until something is stored, and is activated live by a
> `libli:state-saved` event, which removes the flicker objection argued below.
```

- [ ] **Step 7: Catalog**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

Then in `locale/pl/LC_MESSAGES/django.po`, find `msgid "Nothing to clear yet"`. It will very likely arrive `#, fuzzy`, pre-filled from `Nothing to clear here.` as `"Nie ma tu nic do wyczyszczenia."`. **Overwrite unconditionally:** set `msgstr "Nie ma nic do wyczyszczenia"`, delete the `#, fuzzy` line, AND delete the `#| msgid "Nothing to clear here."` provenance line. Grep the whole diff of both `.po` files for other new `#, fuzzy` entries this run picked up, and for each one, report it and fix it the same way rather than leaving it. Then:

```bash
uv run python manage.py compilemessages -l pl -l en
git diff --stat locale/
```

- [ ] **Step 8: Run to verify they pass**

Run: `uv run pytest courses/tests/test_reset_controls.py courses/tests/test_state_saved_header.py courses/tests/test_progress_reset.py -v`
Expected: all PASS.

- [ ] **Step 9: Falsify** (hand-applied, `git diff` read, RED seen, hand-reverted)
1. Template: replace `{% if element_state %}` with `{% if True %}` ("render active unconditionally") → `test_capability_unit_without_state_renders_inactive_control` RED.
2. Template: replace `{% if element_state %}` with `{% if False %}` ("render inactive unconditionally") → `test_capability_unit_with_state_renders_todays_active_link` RED.
3. Template: change the outer gate to `{% if has_stateful_elements and element_state %}` and delete the `{% else %}` branch → `test_capability_unit_without_state_renders_inactive_control` RED (zero controls found).

- [ ] **Step 10: Lint + commit**

```bash
uv run ruff check courses/ && uv run ruff format --check courses/
git add templates/courses/_lesson_article.html courses/views.py courses/tests/test_reset_controls.py docs/superpowers/specs/2026-07-25-start-fresh-only-on-stateful-units-design.md locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo
git commit -m "feat(lesson): Start fresh renders inactive until this viewer has saved work"
```

---

### Task 3: Writers announce `libli:state-saved`; listener activates the control; drift guard

**Files:**
- Create: `courses/static/courses/js/reset_control.js`
- Modify: `courses/static/courses/js/state.js:20-31` (`saveFlag`)
- Modify: `courses/static/courses/js/reveal.js:27-38` (`save`)
- Modify: `courses/static/courses/js/markdone.js` (success `.then`, ~`:67-78`)
- Modify: `courses/static/courses/js/question.js:53` (first `.then`)
- Modify: `templates/courses/lesson_unit.html` (`extra_js` block)
- Test: `tests/test_state_saved_event_guard.py` (create)

**Interfaces:**
- Consumes: `STATE_SAVED_HEADER` (Task 1); the inactive-control DOM contract (Task 2).
- Produces: `document` dispatches `new CustomEvent("libli:state-saved")` after a successful save that stored something; `reset_control.js` activates every `[data-reset-control][aria-disabled="true"]`.

- [ ] **Step 1: Write the failing guard**

Create `tests/test_state_saved_event_guard.py`:

```python
"""Drift guard (spec D5): every client-side practice-state writer announces a STORED
save with `libli:state-saved`, and only after the response says something is stored.

PLACEMENT, not presence: a bare `"libli:state-saved" in src` passes on a dispatch in a
dead branch or above the fetch. Each writer's dispatch is matched together with its
guard, and must come after that file's fetch(.

BLIND SPOTS, stated honestly: a widget posting to element_state_save through a
differently named attribute, a template-injected URL, or a new server route writing
state from a different endpoint is not caught. The dispatch's placement INSIDE the
correct callback is approximated by "after fetch( + adjacent to its guard". The
question.js mutant "dispatch at the end of the second .then" is caught ONLY by the
inline-choice e2e in tests/test_e2e_start_fresh_activation.py. A tripwire, not a proof.
"""

import re
from pathlib import Path

from courses.views import STATE_SAVED_HEADER

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "courses" / "static" / "courses" / "js"
EVENT = "libli:state-saved"
DISPATCH = re.escape(f'document.dispatchEvent(new CustomEvent("{EVENT}"))')


def _strip_js_comments(source):
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?m)//.*$", "", source)


def _src(name):
    src = _strip_js_comments((JS / name).read_text(encoding="utf-8"))
    assert len(src) > 200, f"comment stripping ate {name}"
    return src


# The guarded dispatch, per write site: the guard must sit IMMEDIATELY before the
# dispatch, so deleting the guard (unconditional dispatch) fails the match.
GUARDED = {
    "state.js": r"if \(data && data\.state && Object\.keys\(data\.state\)\.length\) \{\s*"
    + DISPATCH,
    "reveal.js": r"if \(data && data\.state && Object\.keys\(data\.state\)\.length\) \{\s*"
    + DISPATCH,
    "markdone.js": r"if \(Object\.keys\(blob\)\.length\) \{\s*" + DISPATCH,
    "question.js": r"if \(r\.ok && r\.headers\.get\("
    + re.escape(f'"{STATE_SAVED_HEADER}"')
    + r"\)\) \{\s*"
    + DISPATCH,
}

STATE_URL_SHAPES = re.compile(
    r'dataset\.stateUrl|getAttribute\("data-state-url"\)|getAttribute\("data-markdone-url"\)'
)


def test_each_writer_dispatches_exactly_once_behind_its_guard_after_fetch():
    for name, pattern in GUARDED.items():
        src = _src(name)
        assert src.count(f'new CustomEvent("{EVENT}"') == 1, name
        m = re.search(pattern, src)
        assert m, f"{name}: guarded dispatch not found (guard removed or renamed?)"
        fetch_at = src.find("fetch(")
        assert fetch_at != -1, name
        assert m.start() > fetch_at, f"{name}: dispatch sits above fetch(("


def test_question_js_dispatches_before_returning_the_text():
    src = _src("question.js")
    m = re.search(GUARDED["question.js"], src)
    assert m
    assert m.start() < src.find("return r.text()"), "dispatch must be in the FIRST .then"


def test_writer_set_is_exactly_the_known_files():
    found = {
        p.name
        for p in JS.glob("*.js")
        if STATE_URL_SHAPES.search(_strip_js_comments(p.read_text(encoding="utf-8")))
    }
    assert found == {"state.js", "reveal.js", "markdone.js"}, found
    # question.js writes through check_answer's form.action, so no URL shape names it:
    # it is listed explicitly, and its dispatch is pinned in GUARDED above.
    assert "question.js" in GUARDED


def test_listener_listens_for_the_same_name_and_restores_the_contract():
    src = _src("reset_control.js")
    assert f'addEventListener("{EVENT}"' in src
    assert '[data-reset-control][aria-disabled="true"]' in src
    assert 'getAttribute("data-reset-href")' in src
    for attr in ("aria-disabled", "role", "title"):
        assert f'removeAttribute("{attr}")' in src, attr


def test_reset_control_script_only_on_lesson_page_and_before_the_writers():
    lesson = (ROOT / "templates/courses/lesson_unit.html").read_text(encoding="utf-8")
    tag = "{% static 'courses/js/reset_control.js' %}"
    at = lesson.find(tag)
    assert at != -1
    # gated on the same condition as the control itself
    line_start = lesson.rfind("\n", 0, at)
    assert "{% if has_stateful_elements %}" in lesson[line_start:at]
    # deferred scripts run in document order: listener first
    for writer in ("question.js", "state.js", "reveal.js", "markdone.js"):
        assert at < lesson.find(f"courses/js/{writer}"), writer
    results = (ROOT / "templates/courses/quiz_results.html").read_text(encoding="utf-8")
    assert "reset_control.js" not in results
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_state_saved_event_guard.py -v`
Expected: FAIL. There is no dispatch yet, `reset_control.js` does not exist, and the tag is missing. `test_writer_set_is_exactly_the_known_files` should already PASS; if it doesn't, stop and re-check the writer inventory against spec §4.

- [ ] **Step 3: Implement the writers**

`state.js` — in `saveFlag`, replace the `fetch(...)...` statement with:

```js
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ element: eid, state: stateObj }),
        keepalive: true,
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          // The echo is what is STORED (REJECT echoes the stored blob too), so a
          // non-empty echo means there is now something "Start fresh" can clear.
          if (data && data.state && Object.keys(data.state).length) {
            document.dispatchEvent(new CustomEvent("libli:state-saved"));
          }
        })
        .catch(function () {});
```

Also update the `saveFlag` trailing comment from `// fire-and-forget, keepalive, swallow errors` to `// keepalive, swallow errors; announces a stored save`.

`reveal.js` — in `save(btn)`, replace the `fetch(...)...catch(...)` statement with:

```js
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ element: eid, state: { open: true } }),
      keepalive: true, // survives unload
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        // Monotone: the DOM is never adopted from the echo. It is read only to
        // announce a stored save to the "Start fresh" control.
        if (data && data.state && Object.keys(data.state).length) {
          document.dispatchEvent(new CustomEvent("libli:state-saved"));
        }
      })
      .catch(function () {});
```

`markdone.js` — in the success `.then(function (data) {…})`, directly after `paint(root, last);`, add:

```js
            if (Object.keys(blob).length) {
              document.dispatchEvent(new CustomEvent("libli:state-saved"));
            }
```

(This sits after the `if (mine !== seq) return;` sequence guard, so only the newest echo announces.)

`question.js` — replace `.then(function (r) { return r.text(); })` with:

```js
        .then(function (r) {
          // FIRST .then, where `r` is in scope: the second .then returns early on the
          // inline branch, so a dispatch there would skip choice / fill-blank. Only the
          // dispatch is guarded; the text is always returned, exactly as before.
          if (r.ok && r.headers.get("X-Libli-State-Saved")) {
            document.dispatchEvent(new CustomEvent("libli:state-saved"));
          }
          return r.text();
        })
```

- [ ] **Step 4: Implement the listener**

Create `courses/static/courses/js/reset_control.js`:

```js
(function () {
  "use strict";

  // The unit page's "Start fresh" control renders INACTIVE (no href, aria-disabled)
  // until this viewer has stored practice state. The four state writers announce a
  // STORED save with `libli:state-saved`; this flips the control live. One-way by
  // design (spec 2026-10-15 D6): a save that empties state never re-disables it.
  // The data-reset-* hooks stay on purpose: they make this idempotent.
  document.addEventListener("libli:state-saved", function () {
    document
      .querySelectorAll('[data-reset-control][aria-disabled="true"]')
      .forEach(function (a) {
        a.setAttribute("href", a.getAttribute("data-reset-href"));
        a.removeAttribute("aria-disabled");
        a.removeAttribute("role");
        a.removeAttribute("title");
      });
  });
})();
```

In `templates/courses/lesson_unit.html`'s `{% block extra_js %}`, directly after the `progress.js` line, add:

```django
  {% if has_stateful_elements %}<script src="{% static 'courses/js/reset_control.js' %}" defer></script>{% endif %}
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_state_saved_event_guard.py tests/test_element_state_write_routes.py courses/tests/test_reset_controls.py -v`
Expected: all PASS.

Then check whether a static-manifest or script-inventory test enumerates JS files (`grep -rln "unit_done.js" tests/`) and run those too. A new JS file may need registering there; do it if a test says so.

- [ ] **Step 6: Falsify** (hand-applied, `git diff` read, RED seen, hand-reverted)
1. `state.js`: move the dispatch line above `fetch(` → `test_each_writer_dispatches_exactly_once_behind_its_guard_after_fetch` RED.
2. `markdone.js`: delete the `if (Object.keys(blob).length) {` guard and keep the dispatch → same test RED.
3. `reveal.js`: change the event to `"libli:state-save"` → same test RED.
4. `question.js`: change the header literal to `"X-Libli-State-Save"` → same test RED.
5. `reset_control.js`: delete `a.removeAttribute("title");` → `test_listener_listens_for_the_same_name_and_restores_the_contract` RED.
6. `lesson_unit.html`: move the `reset_control.js` line to the end of the block → `test_reset_control_script_only_on_lesson_page_and_before_the_writers` RED.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check tests/test_state_saved_event_guard.py && uv run ruff format --check tests/test_state_saved_event_guard.py
git add courses/static/courses/js/reset_control.js courses/static/courses/js/state.js courses/static/courses/js/reveal.js courses/static/courses/js/markdone.js courses/static/courses/js/question.js templates/courses/lesson_unit.html tests/test_state_saved_event_guard.py
git commit -m "feat(lesson): state writers announce stored saves; Start fresh activates live"
```

---

### Task 4: Inactive styling + end-to-end activation tests + screenshots

**Files:**
- Modify: `core/static/core/css/app.css` (the "Practice-state reset controls" block, ~`:762-775`)
- Create: `tests/test_e2e_start_fresh_activation.py`
- Modify: `tests/test_e2e_unit_head_layout.py` (one new test)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing e2e tests**

Create `tests/test_e2e_start_fresh_activation.py`:

```python
"""e2e: the unit page's "Start fresh" control is INACTIVE until a save stores
something, then activates live (spec 2026-10-15). Drives real UI; syncs on responses
and DOM signals, never sleeps."""

import os
import re

import pytest
from django.urls import reverse
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

CONTROL = ".lesson-unit__head .lesson-unit__reset"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _unit(username):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    EnrollmentFactory(student=student, course=course)
    return student, unit


def _url(live_server, unit):
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _expected_href(unit):
    return (
        reverse("courses:progress_reset", args=[unit.course.slug, unit.pk])
        + "?next="
        + reverse("courses:lesson_unit", args=[unit.course.slug, unit.pk])
    )


def _is_state_save(r):
    return "/state/" in r.url and r.request.method == "POST"


def _assert_inactive(page):
    c = page.locator(CONTROL)
    expect(c).to_have_attribute("aria-disabled", "true")
    expect(c).not_to_have_attribute("href", re.compile(".*"))


def _wait_active(page):
    page.wait_for_selector(f"{CONTROL}[href]")


def test_reveal_gate_activates_live_with_full_contract(page, live_server):
    from courses.models import RevealGateElement
    from courses.models import TextElement

    _s, unit = _unit("sf_reveal")
    add_element(unit, TextElement.objects.create(body="<p>before</p>"))
    add_element(unit, RevealGateElement.objects.create(label="Show more"))
    add_element(unit, TextElement.objects.create(body="<p>after</p>"))
    _login(page, live_server, "sf_reveal")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)
    inactive_opacity = page.locator(CONTROL).evaluate(
        "el => getComputedStyle(el).opacity"
    )

    page.get_by_role("button", name="Show more").click()
    _wait_active(page)

    c = page.locator(CONTROL)
    for attr in ("aria-disabled", "role", "title"):
        assert c.get_attribute(attr) is None, attr
    assert c.get_attribute("href") == _expected_href(unit)
    active_opacity = c.evaluate("el => getComputedStyle(el).opacity")
    assert active_opacity == "1"
    assert inactive_opacity != active_opacity  # anti-vacuity: the styling exists

    c.click()
    page.wait_for_url(re.compile(r"/reset/"))
    expect(page.get_by_text("Nothing to clear here.")).to_have_count(0)


def test_fill_gate_answered_correctly_activates(page, live_server):
    from courses.fillblank import parse
    from courses.models import FillGateElement
    from courses.models import TextElement

    _s, unit = _unit("sf_fillgate")
    token_stem, blanks = parse("Capital of France? {{Paris}}")
    add_element(unit, FillGateElement.objects.create(stem=token_stem, answers=blanks))
    add_element(unit, TextElement.objects.create(body="<p>reward</p>"))
    _login(page, live_server, "sf_fillgate")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)

    blank = page.locator('[data-fillgate] input[name="blank"]').first
    blank.fill("Paris")
    with page.expect_response(_is_state_save) as resp:
        page.get_by_role("button", name="Confirm").click()
    assert resp.value.ok
    _wait_active(page)


def _choice_unit(username):
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    _s, unit = _unit(username)
    q = ChoiceQuestionElement.objects.create(stem="Pick one", multiple=False)
    Choice.objects.create(question=q, text="Alpha", is_correct=True, order=0)
    Choice.objects.create(question=q, text="Beta", is_correct=False, order=1)
    add_element(unit, q)
    return unit


def _arm_swap_probe(page):
    """Test setup, not a gesture: a child the inline swap (form.innerHTML = …) will
    destroy, so its detachment proves the SECOND .then ran -- after the first-.then
    dispatch line."""
    page.locator("[data-question] form").evaluate(
        "f => { const i = document.createElement('i'); "
        "i.setAttribute('data-e2e-probe', ''); f.appendChild(i); }"
    )


def test_inline_choice_nonempty_answer_activates(page, live_server):
    # ONLY guard for the mutant "question.js dispatch moved to the end of the second
    # .then" (the inline branch returns early there). Do not trim.
    unit = _choice_unit("sf_choice")
    _login(page, live_server, "sf_choice")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)
    page.get_by_label("Alpha").check()
    page.get_by_role("button", name="Check").click()
    _wait_active(page)


def test_inline_choice_empty_answer_stays_inactive(page, live_server):
    unit = _choice_unit("sf_choice_empty")
    _login(page, live_server, "sf_choice_empty")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)
    _arm_swap_probe(page)
    page.get_by_role("button", name="Check").click()
    page.wait_for_selector("[data-e2e-probe]", state="detached")
    _assert_inactive(page)


def test_markdone_stays_active_after_untick_then_inactive_after_reload(page, live_server):
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem

    _s, unit = _unit("sf_markdone")
    md = MarkDoneElement.objects.create(prompt="Prep")
    MarkDoneItem.objects.create(element=md, content="one")
    add_element(unit, md)
    _login(page, live_server, "sf_markdone")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)

    box = page.locator(".markdone__item input[type='checkbox']").first
    with page.expect_response(_is_state_save) as r1:
        box.check()
    assert r1.value.ok
    _wait_active(page)

    with page.expect_response(_is_state_save) as r2:
        box.uncheck()
    assert r2.value.ok
    assert r2.value.json()["state"] == {}  # the final save stored nothing
    expect(page.locator(CONTROL)).to_have_attribute("href", _expected_href(unit))  # D6

    page.reload()
    _assert_inactive(page)


def test_pressed_inactive_control_paints_no_fill(page, live_server):
    from courses.models import MarkDoneElement

    _s, unit = _unit("sf_pressed")
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    _login(page, live_server, "sf_pressed")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)
    box = page.locator(CONTROL).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    hover_bg = page.locator(CONTROL).evaluate("el => getComputedStyle(el).backgroundColor")
    page.mouse.down()
    pressed_bg = page.locator(CONTROL).evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    page.mouse.up()
    assert hover_bg == "rgba(0, 0, 0, 0)", hover_bg
    assert pressed_bg == "rgba(0, 0, 0, 0)", pressed_bg
```

Before running, check these against the real code and fix the test (never the product) where they differ:
- The reset interstitial's URL path: use the path `reverse("courses:progress_reset", …)` produces in place of the `/reset/` regex.
- That the choice input's accessible name is its text (`get_by_label("Alpha")`). If not, locate it by `input[name="choice"]` inside the label containing "Alpha".
- That an empty Check submits. If `question.js` or the browser blocks an empty submit, the empty-answer test must still prove a server round trip: wrap the click in `page.expect_response(lambda r: "/check/" in r.url)` and keep the probe wait.
- That the button label is "Check" (`templates/courses/elements/choicequestion.html:18`).

Append to `tests/test_e2e_unit_head_layout.py` (reuse its `_seed`, `_login`, `MEASURE` helpers and its existing url-building pattern; read the file's first 40 lines for the exact helper names):

```python
@pytest.mark.django_db(transaction=True)
def test_live_activation_does_not_move_the_control(page, live_server):
    """Same page, both states: measure INACTIVE, trigger a real save, wait for href,
    measure ACTIVE. A second page load could hide a live-only shift."""
    course, unit = _seed("headlive", "head-layout-live")
    # ... log in and open the unit exactly as the existing tests in this module do ...
    page.wait_for_selector(".lesson-unit__reset[aria-disabled='true']")
    before = page.locator(".lesson-unit__reset").bounding_box()
    with page.expect_response(lambda r: "/state/" in r.url and r.request.method == "POST"):
        page.locator(".markdone__item input[type='checkbox']").first.check()
    page.wait_for_selector(".lesson-unit__reset[href]")
    after = page.locator(".lesson-unit__reset").bounding_box()
    assert before == after
```

`_seed` creates a `MarkDoneElement` with **no items**, so this test needs one checkbox. In the new test only, add a `MarkDoneItem` for that element after `_seed` returns (look it up via `unit.elements`). Do not change `_seed` itself; other tests depend on its traffic-free shape. Replace the `# ...` line with the module's real login/goto calls.

- [ ] **Step 2: Run to verify they fail**

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
uv run pytest tests/test_e2e_start_fresh_activation.py tests/test_e2e_unit_head_layout.py -m e2e -n 2 -v
```

Expected: `test_reveal_gate_activates_live_with_full_contract` FAILS on `inactive_opacity != active_opacity` (there is no styling yet). `test_pressed_inactive_control_paints_no_fill` FAILS (the `.btn--ghost:hover` / `.btn:active` fill). The others PASS, since Tasks 2–3 are in.

- [ ] **Step 3: Implement the styling**

In `core/static/core/css/app.css`, directly after the `.outline-node__reset:hover { color: var(--danger); }` line (end of the "Practice-state reset controls" rules), add:

```css
/* Unit page: rendered INACTIVE until this viewer has stored practice state (an <a>
   with aria-disabled and no href). NOT pointer-events:none -- that would suppress the
   title tooltip. So the two fills that would repaint it as live must be neutralised
   here: .btn--ghost:hover's, and .btn:active's primary fill, which .btn--ghost never
   overrides and which native :disabled blocks only on real buttons. Specificity
   (0,3,0) beats .btn:active (0,2,0). */
.lesson-unit__reset[aria-disabled="true"] { opacity: .45; cursor: default; }
.lesson-unit__reset[aria-disabled="true"]:hover,
.lesson-unit__reset[aria-disabled="true"]:active { background: transparent; }
```

- [ ] **Step 4: Run to verify they pass, plus every CSS source test**

```bash
uv run pytest tests/test_e2e_start_fresh_activation.py tests/test_e2e_unit_head_layout.py tests/test_e2e_practice_state.py -m e2e -n 2 -v
uv run pytest $(ls tests/test_*css*.py) -n 4
```

Expected: all PASS. CSS marker tests partition on block text; if one fails, the new rule hijacked its marker, so fix the marker the way that test's own comments describe, not by moving the rule.

- [ ] **Step 5: Falsify** (hand-applied, `git diff` read, RED seen, hand-reverted)
1. `app.css`: delete the `:active` selector line from the override → `test_pressed_inactive_control_paints_no_fill` RED.
2. `reset_control.js`: delete `a.removeAttribute("aria-disabled");` → `test_reveal_gate_activates_live_with_full_contract` RED (the attribute is still present).
3. `question.js`: move the guarded dispatch from the first `.then` to the end of the second `.then` (after its inline early `return`) → `test_inline_choice_nonempty_answer_activates` RED (times out on `[href]`).
4. `courses/views.py`: set `stored_answer = True` in the `answer_is_empty` branch too → `test_inline_choice_empty_answer_stays_inactive` RED.
5. `app.css`: add `padding: 0;` to `.lesson-unit__reset[aria-disabled="true"]` → `test_live_activation_does_not_move_the_control` RED.

- [ ] **Step 6: Screenshots (light + dark)**

Write a throwaway capture script in the session scratchpad (NOT under `tests/`; `capture_*` scripts there overwrite tracked screenshots). Have it log in, open a capability unit, and screenshot `.lesson-unit__head` in four states: inactive light, inactive dark, active light, active dark. Set dark mode with `page.emulate_media(color_scheme="dark")` and/or the `data-theme="dark"` attribute the app uses. Check the screenshots yourself. In dark mode, judge separately that the inactive control reads as clearly disabled while its text stays legible. Report the paths; do not commit them.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check tests/ && uv run ruff format --check tests/
git add core/static/core/css/app.css tests/test_e2e_start_fresh_activation.py tests/test_e2e_unit_head_layout.py
git commit -m "feat(lesson): inactive Start fresh styling + live-activation e2e"
```

---

## Branch gate (after Task 4, before the PR)

Run the unit suite in chunks (the full suite in one go is OOM-killed). Grep each run's summary line; don't rely on the exit code.

```bash
uv run pytest courses -n 4
uv run pytest tests -n 4
uv run pytest tests -m e2e -n 2 -k "reset or practice or start_fresh or head_layout or fillgate or markdone or question or reveal"
uv run ruff check . && uv run ruff format --check .
```
