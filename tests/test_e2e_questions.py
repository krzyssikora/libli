"""Playwright e2e for Phase-2a choice questions.

Tests:
  1. Author a single-choice question via the editor UI (JS path), then answer it as
     a student — wrong choice → is-incorrect feedback; correct choice → is-correct.
  2. Inline-math renders via KaTeX: stem with \\(x^2\\) produces .katex nodes.
  3. Multiple-choice, no-JS path: full-page POST → verdict inline on the answered
     question; other questions show no correctness signal.

Marked e2e (excluded from the default run; run with -m e2e).
Follows the harness in test_e2e_html_element.py / test_e2e_editor.py verbatim.
"""

import os
import urllib.parse

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    """Log in via the allauth HTML form (works with JS enabled or disabled)."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_course_unit(username, slug, unit_title="Lesson"):
    """Create a course + lesson unit owned by *username*; return the unit."""
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    User = get_user_model()
    owner = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title=unit_title
    )
    return unit


def _enroll(user, course):
    from courses.models import Enrollment

    Enrollment.objects.get_or_create(student=user, course=course)


def _editor_url(live_server, unit):
    return (
        f"{live_server.url}/manage/courses/{unit.course.slug}"
        f"/build/unit/{unit.pk}/edit/"
    )


def _add_element(page, add_type):
    """Open the add-menu, click the type card, wait for the host form to mount."""
    page.locator("[data-add-toggle]").click()
    page.locator(f"[data-add-type='{add_type}']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")


def _seed_single_choice_question(unit, stem, choices, *, correct_index=0):
    """Create a ChoiceQuestionElement + choices via ORM; attach to *unit*.

    choices: list of str; correct_index: which one is correct (0-based).
    Returns the Element join-row.
    """
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from tests.factories import add_element

    q = ChoiceQuestionElement.objects.create(stem=stem, multiple=False)
    for i, text in enumerate(choices):
        Choice.objects.create(question=q, text=text, is_correct=(i == correct_index))
    return add_element(unit, q)


def _seed_multi_choice_question(unit, stem, choices, *, correct_indices):
    """Create a multiple-choice question via ORM; attach to *unit*."""
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from tests.factories import add_element

    q = ChoiceQuestionElement.objects.create(stem=stem, multiple=True)
    for i, text in enumerate(choices):
        Choice.objects.create(question=q, text=text, is_correct=(i in correct_indices))
    return add_element(unit, q)


def _get_csrf_token(ctx, live_server):
    """Extract the CSRF token cookie from the browser context.

    If not yet present (cookie not set), GET the login page to trigger the middleware
    to set it, then read it back.
    """
    cookies = ctx.cookies()
    token = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    if not token:
        # Force the cookie to be set by visiting any plain page.
        p = ctx.new_page()
        p.goto(f"{live_server.url}/accounts/login/")
        p.close()
        cookies = ctx.cookies()
        token = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    return token


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_author_and_answer_single_choice_js(browser, live_server):
    """Author a single-choice question via the editor UI (JS), assert it appears in
    the preview, then as an enrolled student answer it (JS fetch path): wrong choice →
    is-incorrect verdict + correct choice revealed; correct choice → is-correct.

    Uses two separate browser contexts: one PA context for authoring, one student
    context for answering — avoids cross-user logout complexity."""
    _make_pa_user("qe_author")
    unit = _seed_course_unit("qe_author", slug="qe-sc-js")

    # ── Authoring: PA context — open editor, add a single-choice question ─────
    pa_ctx = browser.new_context()
    pa_page = pa_ctx.new_page()
    _login(pa_page, live_server, "qe_author")
    pa_page.goto(_editor_url(live_server, unit))
    pa_page.wait_for_selector('[data-scope="editor"]')

    _add_element(pa_page, "choice-single")

    # The RTE (text_toolbar.js) hides the [data-rte-source] textarea and mounts a
    # contenteditable .rte-surface div.  The first surface in the edit slot is the
    # stem; type into it.
    stem_surface = pa_page.locator("[data-edit-slot] .rte-surface").first
    stem_surface.wait_for(state="visible")
    stem_surface.click()
    pa_page.keyboard.type("What is 1 + 1?")

    # Fill the two extra choice rows (extra=2 in the formset).
    # Row 0: wrong choice.
    pa_page.locator("[data-edit-slot] input[name='choices-0-text']").fill("One")
    # Row 1: correct choice — mark the radio for is_correct.
    pa_page.locator("[data-edit-slot] input[name='choices-1-text']").fill("Two")
    pa_page.locator("[data-edit-slot] input[name='choices-1-is_correct']").check()

    # Save (scoped to the edit slot to avoid the shell header's submit buttons).
    pa_page.locator("[data-edit-slot] button[type='submit']").click()

    # Assert the element appears in the preview.
    preview = pa_page.locator('[data-scope="preview"]')
    preview.locator("[data-question]").wait_for(timeout=8000)
    assert preview.locator("[data-question]").count() >= 1

    pa_ctx.close()

    # ── Student: separate browser context — enroll, open lesson, answer ────────
    student = make_verified_user(
        username="qe_student", email="qe_student@t.example.com"
    )
    _enroll(student, unit.course)

    stu_ctx = browser.new_context()
    stu_page = stu_ctx.new_page()
    _login(stu_page, live_server, "qe_student")

    lesson_url = f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/"
    stu_page.goto(lesson_url)
    stu_page.wait_for_selector("[data-question]")

    # The choices are ordered by (order, pk).  "One" was created first (wrong),
    # "Two" second (correct). Row 0 = "One", Row 1 = "Two".
    question_el = stu_page.locator("[data-question]").first
    choices_radios = question_el.locator("input[name='choice'][type='radio']")

    # Select the WRONG choice ("One") → Check.
    choices_radios.nth(0).check()
    # Click Check — scoped to the question to avoid any other submit buttons.
    question_el.locator("button[type='submit']").click()

    # Wait for JS to inject the feedback partial into [data-question-feedback].
    feedback_slot = question_el.locator("[data-question-feedback]")
    feedback_slot.locator(".question__verdict").wait_for(timeout=6000)

    # Assert incorrect verdict via CSS class (locale-independent, not translated text).
    assert feedback_slot.locator(".is-incorrect").count() >= 1, (
        "Expected .is-incorrect after submitting wrong choice"
    )
    # The correct choice must be revealed.
    assert feedback_slot.locator(".answer-correct").count() >= 1, (
        "Expected .answer-correct reveal after incorrect answer"
    )

    # Select the CORRECT choice ("Two") → Check again.
    choices_radios.nth(1).check()
    question_el.locator("button[type='submit']").click()

    feedback_slot.locator(".is-correct").wait_for(timeout=6000)
    assert feedback_slot.locator(".is-correct").count() >= 1, (
        "Expected .is-correct after submitting correct choice"
    )

    stu_ctx.close()


@pytest.mark.django_db(transaction=True)
def test_choice_editor_add_remove_and_radio_js(browser, live_server):
    """Authoring UX (JS) for the choice editor:
      - the editor heading names the type ("Single choice");
      - "Add option" appends a working formset row beyond the initial extra=2;
      - single-choice correct-markers are mutually exclusive (radios with distinct
        formset names are grouped by JS, not the browser);
      - "Remove" gives live feedback (row dims) before save;
      - a dynamically-added row persists on save.
    """
    from courses.models import ChoiceQuestionElement

    _make_pa_user("qe_editor")
    unit = _seed_course_unit("qe_editor", slug="qe-editor-js")

    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "qe_editor")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')

    _add_element(page, "choice-single")
    slot = page.locator("[data-edit-slot]")

    # Heading names the element type (CSS uppercases it, so compare case-insensitively).
    assert (
        slot.locator(".editor-form__type").inner_text().strip().lower()
        == "single choice"
    )

    # Starts with the formset's extra=2 blank rows.
    rows = slot.locator("[data-choice-row]")
    assert rows.count() == 2

    # Add option → a third row with the next formset index.
    slot.locator("[data-choice-add]").click()
    page.wait_for_function(
        "() => document.querySelectorAll("
        "'[data-edit-slot] [data-choice-row]').length === 3"
    )
    assert slot.locator("input[name='choices-2-text']").count() == 1
    assert slot.locator("input[name='choices-TOTAL_FORMS']").input_value() == "3"

    # Fill three options; mark row 0 correct, then row 1 correct.
    slot.locator("input[name='choices-0-text']").fill("Alpha")
    slot.locator("input[name='choices-1-text']").fill("Beta")
    slot.locator("input[name='choices-2-text']").fill("Gamma")
    r0 = slot.locator("input[name='choices-0-is_correct']")
    r1 = slot.locator("input[name='choices-1-is_correct']")
    r0.check()
    r1.check()
    # Radio exclusivity: marking row 1 cleared row 0.
    assert r1.is_checked()
    assert not r0.is_checked()

    # Remove row 2 → live dim feedback (row keeps its DELETE ticked).
    row2 = slot.locator("[data-choice-row]").nth(2)
    row2.locator("input[name='choices-2-DELETE']").check()
    page.wait_for_function(
        "() => document.querySelectorAll("
        "'[data-edit-slot] .choice-row--del').length === 1"
    )

    # Save → the question persists with the two kept choices (Gamma was removed).
    slot.locator("button[type='submit']").click()
    preview = page.locator('[data-scope="preview"]')
    preview.locator("[data-question]").wait_for(timeout=8000)

    q = ChoiceQuestionElement.objects.get()
    assert q.multiple is False
    texts = sorted(q.choices.values_list("text", flat=True))
    assert texts == ["Alpha", "Beta"]
    assert q.choices.get(is_correct=True).text == "Beta"

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_preview_try_it_grades_without_persisting(browser, live_server):
    """The editor's live preview is answerable ("try it"): answering a question there
    shows correct/incorrect feedback inline, posting to the manage-gated try endpoint —
    and persists nothing (no QuestionResponse rows)."""
    from courses.models import QuestionResponse

    _make_pa_user("qe_try")
    unit = _seed_course_unit("qe_try", slug="qe-try")
    _seed_single_choice_question(
        unit, stem="What is 1 + 1?", choices=["One", "Two"], correct_index=1
    )

    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "qe_try")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="preview"] [data-question]')

    preview_q = page.locator('[data-scope="preview"] [data-question]').first
    radios = preview_q.locator("input[name='choice']")
    feedback = preview_q.locator("[data-question-feedback]")

    # Wrong choice ("One") → incorrect verdict.
    radios.nth(0).check()
    preview_q.locator("button[type='submit']").click()
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert feedback.locator(".is-incorrect").count() >= 1

    # Correct choice ("Two") → correct verdict.
    radios.nth(1).check()
    preview_q.locator("button[type='submit']").click()
    feedback.locator(".is-correct").wait_for(timeout=6000)
    assert feedback.locator(".is-correct").count() >= 1

    # Try-it must never persist a response.
    assert QuestionResponse.objects.count() == 0

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_preview_quiz_gating_withholds_then_reveals(browser, live_server):
    """On a QUIZ unit, the try-it preview mirrors reveal-gating: a wrong answer with
    attempts left withholds the correct answer; the last wrong attempt reveals it and
    locks the inputs. Tracked in-browser, nothing persisted."""
    from django.contrib.auth import get_user_model

    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import QuestionResponse
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import add_element

    _make_pa_user("qe_qg")
    owner = get_user_model().objects.get(username="qe_qg")
    course = CourseFactory(slug="qe-qg", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Quiz"
    )
    q = ChoiceQuestionElement.objects.create(
        stem="Pick", multiple=False, max_attempts=2
    )
    Choice.objects.create(question=q, text="One", is_correct=False)
    Choice.objects.create(question=q, text="Two", is_correct=True)
    add_element(unit, q)

    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "qe_qg")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="preview"] [data-question]')

    pq = page.locator('[data-scope="preview"] [data-question]').first
    radios = pq.locator("input[name='choice']")
    fb = pq.locator("[data-question-feedback]")

    # Attempt 1 (wrong) → incorrect, correct answer WITHHELD.
    radios.nth(0).check()
    pq.locator("button[type='submit']").click()
    fb.locator(".is-incorrect").wait_for(timeout=6000)
    assert fb.locator(".answer-correct").count() == 0

    # Attempt 2 (wrong, last) → reveal + lock.
    radios.nth(0).check()
    pq.locator("button[type='submit']").click()
    fb.locator(".answer-correct").wait_for(timeout=6000)
    assert fb.locator(".answer-correct").count() >= 1
    assert radios.nth(0).is_disabled()  # inputs frozen after lock

    assert QuestionResponse.objects.count() == 0
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_question_inline_math_renders(page, live_server):
    """A single-choice question whose stem contains inline math \\(x^2\\) renders
    KaTeX (.katex nodes) in the student lesson view — proves question.js auto-render
    + KaTeX auto-render both fire on the [data-question] subtree."""
    _make_pa_user("qe_math")
    unit = _seed_course_unit("qe_math", slug="qe-math")

    # Seed question with math in stem and in a choice.
    _seed_single_choice_question(
        unit,
        stem=r"What is \(x^2\) when \(x = 3\)?",
        choices=[r"\(9\)", r"\(6\)"],
        correct_index=0,
    )

    student = make_verified_user(
        username="qe_mathstudent", email="qe_mathstudent@t.example.com"
    )
    _enroll(student, unit.course)

    _login(page, live_server, "qe_mathstudent")
    lesson_url = f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/"
    page.goto(lesson_url)
    page.wait_for_selector("[data-question]")

    # Wait for KaTeX to render (it runs on DOMContentLoaded + question.js pass).
    page.wait_for_function(
        "() => document.querySelectorAll('[data-question] .katex').length > 0",
        timeout=6000,
    )
    katex_count = page.locator("[data-question] .katex").count()
    assert katex_count > 0, (
        "Expected KaTeX-rendered .katex nodes inside [data-question], "
        f"got {katex_count}"
    )


@pytest.mark.django_db(transaction=True)
def test_answer_multiple_choice_no_js(browser, live_server):
    """With JS disabled, submitting a multiple-choice form causes a full-page reload.
    The answered question shows its verdict (.is-correct / .is-incorrect) inline AND
    other questions on the page show no correctness signal (.is-correct /
    .is-incorrect).

    Uses page.request.post() with the CSRF token from the cookie, mirroring the no-JS
    harness in test_no_js_fallback_save (test_e2e_editor.py). Choice PKs are read from
    the ORM so we don't need JS to inspect rendered inputs."""
    _make_pa_user("qe_nojs")
    unit = _seed_course_unit("qe_nojs", slug="qe-nojs")

    # Seed two questions so we can assert the OTHER one has no verdict.
    join1 = _seed_multi_choice_question(
        unit,
        stem="Pick the even numbers.",
        choices=["2", "3", "4"],
        correct_indices={0, 2},  # "2" and "4" are correct
    )
    _seed_single_choice_question(
        unit,
        stem="What is 2 + 2?",
        choices=["3", "4"],
        correct_index=1,  # "4"
    )

    student = make_verified_user(
        username="qe_nojsstudent", email="qe_nojsstudent@t.example.com"
    )
    _enroll(student, unit.course)

    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "qe_nojsstudent")

    lesson_url = f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/"
    # Navigate to the lesson page so the server sets the CSRF cookie on this context.
    page.goto(lesson_url)

    # Read the CSRF token from the cookie (the login + lesson GET have both set it).
    cookies = ctx.cookies()
    csrf_token = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    assert csrf_token, "CSRF cookie not set after navigating to lesson page"

    # Get the correct Choice PKs from the ORM so we can build the POST body without
    # requiring JS to inspect rendered inputs.

    q_obj = join1.content_object  # ChoiceQuestionElement
    all_choices = list(q_obj.choices.order_by("order", "pk"))
    # all_choices: [Choice("2", correct), Choice("3", wrong), Choice("4", correct)]
    correct_pks = [str(c.pk) for c in all_choices if c.is_correct]

    check_url = (
        f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/q/{join1.pk}/check/"
    )

    # Build a URL-encoded POST body with duplicate `choice` keys (one per correct PK),
    # mirroring the real browser form submit.
    body_parts = [("csrfmiddlewaretoken", csrf_token)]
    for pk in correct_pks:
        body_parts.append(("choice", pk))
    encoded_body = urllib.parse.urlencode(body_parts)

    # POST via page.request so the browser context's session cookie is included.
    resp = page.request.post(
        check_url,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": lesson_url,
        },
        data=encoded_body,
    )
    assert resp.ok, (
        f"check_answer POST failed with status {resp.status}; "
        "check CSRF cookie, login state, and enrollment"
    )

    # The no-JS check_answer view returns the full lesson HTML with inline feedback.
    # Load it into a fresh page to inspect the DOM.
    body_text = resp.text()
    result_page = ctx.new_page()
    result_page.set_content(body_text)

    questions_on_page = result_page.locator("[data-question]")
    assert questions_on_page.count() >= 2, (
        f"Expected at least 2 [data-question] elements in the response, "
        f"got {questions_on_page.count()}"
    )

    # The answered question (first — multi-choice) must show a verdict.
    answered_feedback = questions_on_page.first.locator("[data-question-feedback]")
    answered_verdict = answered_feedback.locator(".is-correct, .is-incorrect").count()
    assert answered_verdict >= 1, (
        f"Expected answered question to show .is-correct or .is-incorrect, "
        f"got {answered_verdict}"
    )

    # The unanswered question (second — single-choice) must show no verdict.
    unanswered_feedback = questions_on_page.nth(1).locator("[data-question-feedback]")
    unanswered_verdict = unanswered_feedback.locator(
        ".is-correct, .is-incorrect"
    ).count()
    assert unanswered_verdict == 0, (
        f"Expected unanswered question to show no verdict, got {unanswered_verdict}"
    )

    result_page.close()
    ctx.close()
