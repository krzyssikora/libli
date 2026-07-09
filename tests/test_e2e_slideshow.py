"""Playwright e2e for unit-level slideshow mode client pagination (Task 8),
mark-seen-on-reveal (Task 9), and quiz Finish gating + widget relayout (Task 10).

Tests:
  1. Prev/Next paginate a 3-slide lesson and update the counter; Next disables
     at the last slide.
  2. Arrow keys inside a text-input answer field do NOT change slides (the
     field owns the arrow key).
  3. Arrow keys inside a radio/select answer control do NOT change slides.
  4. Arrow keys DO paginate when focus is on the control bar / non-editable
     content (positive case for the same guard).
  5. A single-slide unit renders no control bar (degenerate no-op).
  6. A lesson whose first slide is taller than the viewport still completes
     once the student pages (without scrolling) to the last slide — the
     slideshow's own mark-seen-on-reveal (Task 9), not progress.js's
     IntersectionObserver, drives completion.
  7. A quiz's Finish form stays hidden until the last slide is active.
  8. A MathElement on slide 2 (after a break) renders at a real width once
     revealed — proves the Task 10 `resize` dispatch lets KaTeX/MathLive/
     GeoGebra widgets re-measure instead of staying collapsed at ~0.
  9. Builder authoring UI (Task 12): an author clicks Add -> Slide break in the
     unit editor and a divider row (not a content card) appears.

Marked e2e (excluded from the default run; run with -m e2e).
Mirrors the harness in tests/test_e2e_html_element.py.
"""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user
from tests.factories import seed_slideshow_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _unit_path(unit):
    from django.urls import reverse

    if unit.unit_type == "quiz":
        name = "courses:quiz_unit"
    else:
        name = "courses:lesson_unit"
    return reverse(name, kwargs={"slug": unit.course.slug, "node_pk": unit.pk})


def _seed_slideshow_lesson_3(username):
    """Enrolled lesson unit with 3 slides (t | brk | t | brk | t)."""
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = seed_slideshow_unit(course, "lesson", layout=["t", "brk", "t", "brk", "t"])
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_lesson_single(username):
    """Enrolled lesson unit with a single slide (no break -> no control bar)."""
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = seed_slideshow_unit(course, "lesson", layout=["t"])
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_quiz_text(username):
    """Enrolled quiz unit, 3 slides; slide 0 holds a short-text question."""
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = seed_slideshow_unit(course, "quiz", layout=["q", "brk", "t", "brk", "t"])
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_quiz_choice(username):
    """Enrolled quiz unit, 3 slides; slide 0 holds a single-choice (radio) question."""
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import SlideBreakElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")

    q = ChoiceQuestionElement.objects.create(stem="Pick one", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True)
    Choice.objects.create(question=q, text="B", is_correct=False)
    add_element(unit, q)
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, TextElement.objects.create(body="x"))
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, TextElement.objects.create(body="x"))

    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_quiz_3(username):
    """Enrolled quiz unit, 3 slides, one question per slide (q | brk | q | brk | q)."""
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = seed_slideshow_unit(course, "quiz", layout=["q", "brk", "q", "brk", "q"])
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_quiz_math(username):
    """Enrolled quiz unit, 2 slides; slide 1 (after a break) holds a MathElement."""
    from courses.models import MathElement
    from courses.models import ShortTextQuestionElement
    from courses.models import SlideBreakElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q?"))
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, MathElement.objects.create(latex="x^2"))

    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_builder_unit(username):
    """PA/author user + an empty lesson unit; return (author, builder editor URL
    path). Mirrors tests/test_e2e_builder.py's owner+CourseFactory+ContentNodeFactory
    seed pattern (ORM-seeded, no course-creation form round trip)."""
    from django.contrib.auth.models import Group
    from django.urls import reverse

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    seed_roles()
    author = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    author.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    course = CourseFactory(owner=author)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Unit One"
    )
    path = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    return author, path


def _seed_slideshow_lesson_tall(username):
    """Enrolled lesson unit with 3 slides; slide 0's TextElement is much taller than
    the viewport (many paragraphs), so a student who only pages Next (never scrolls)
    would leave it unseen under a scroll-driven observer. Used to prove Task 9's
    reveal-driven mark-seen (not progress.js's IntersectionObserver) drives
    completion."""
    from courses.models import SlideBreakElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    tall_body = "".join(
        f"<p>Paragraph {i} of a very long first slide.</p>" for i in range(200)
    )
    add_element(unit, TextElement.objects.create(body=tall_body))
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, TextElement.objects.create(body="x"))
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, TextElement.objects.create(body="x"))
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_lesson_short_first_tall_later(username):
    """3 slides: slide 0 short, slide 2 very tall. In a fixed-height deck the
    footer bar must sit at the same y on slide 0 and slide 2."""
    from courses.models import SlideBreakElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    add_element(unit, TextElement.objects.create(body="<p>short</p>"))
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, TextElement.objects.create(body="<p>middle</p>"))
    add_element(unit, SlideBreakElement.objects.create())
    tall = "".join(f"<p>Paragraph {i} of a tall last slide.</p>" for i in range(200))
    add_element(unit, TextElement.objects.create(body=tall))
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_lesson_many(username):
    """13-slide lesson (t brk t brk ... t) for the >DOTS_MAX counter fallback."""
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    layout = []
    for i in range(13):
        if i:
            layout.append("brk")
        layout.append("t")
    unit = seed_slideshow_unit(course, "lesson", layout=layout)
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_prev_next_paginate_and_counter(page, live_server):
    student, path = _seed_slideshow_lesson_3("s1")
    _login(page, live_server, "s1")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator(".slideshow-bar")).to_be_visible()
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 1 of 3")
    expect(page.locator(".slide.is-active")).to_have_count(1)
    page.get_by_role("button", name="Next").click()
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 2 of 3")
    page.get_by_role("button", name="Next").click()
    expect(page.get_by_role("button", name="Next")).to_be_disabled()


@pytest.mark.django_db(transaction=True)
def test_position_indicator_dots_and_status(page, live_server):
    # <=12 slides -> dots (one per slide, active tracks position); status live region
    # announces "Slide N of 3" and updates on navigation.
    student, path = _seed_slideshow_lesson_3("s_dots")
    _login(page, live_server, "s_dots")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator("[data-slideshow-dots] .slideshow-bar__dot")).to_have_count(3)
    expect(page.locator("[data-slideshow-counter]")).to_have_count(0)
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 1 of 3")
    dots = page.locator("[data-slideshow-dots] .slideshow-bar__dot")
    expect(dots.nth(0)).to_have_class(re.compile(r"is-active"))
    page.get_by_role("button", name="Next").click()
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 2 of 3")
    expect(dots.nth(1)).to_have_class(re.compile(r"is-active"))


@pytest.mark.django_db(transaction=True)
def test_position_indicator_counter_fallback_over_dots_max(page, live_server):
    # >12 slides -> text counter, no dots; status still announces "Slide 1 of 13".
    student, path = _seed_slideshow_lesson_many("s_many")
    _login(page, live_server, "s_many")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator("[data-slideshow-counter]")).to_have_text("1 / 13")
    expect(page.locator("[data-slideshow-dots]")).to_have_count(0)
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 1 of 13")


@pytest.mark.django_db(transaction=True)
def test_arrow_in_text_field_does_not_change_slide(page, live_server):
    student, path = _seed_slideshow_quiz_text("s2")
    _login(page, live_server, "s2")
    page.goto(f"{live_server.url}{path}")
    field = page.locator(".slide.is-active input[type=text]").first
    field.click()
    field.press("ArrowRight")
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 1 of 3")


@pytest.mark.django_db(transaction=True)
def test_arrow_in_select_or_radio_does_not_change_slide(page, live_server):
    # Non-caret answer control: arrows change the control's own selection, NOT
    # the slide.
    student, path = _seed_slideshow_quiz_choice("s3")
    _login(page, live_server, "s3")
    page.goto(f"{live_server.url}{path}")
    ctrl = page.locator(
        ".slide.is-active input[type=radio], .slide.is-active select"
    ).first
    ctrl.focus()
    ctrl.press("ArrowDown")
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 1 of 3")


@pytest.mark.django_db(transaction=True)
def test_arrow_on_bar_advances_slide(page, live_server):
    # Positive case: arrows DO paginate when focus is on the control bar /
    # non-editable content.
    student, path = _seed_slideshow_lesson_3("s4")
    _login(page, live_server, "s4")
    page.goto(f"{live_server.url}{path}")
    page.get_by_role("button", name="Next").focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 2 of 3")


@pytest.mark.django_db(transaction=True)
def test_single_slide_no_control_bar(page, live_server):
    student, path = _seed_slideshow_lesson_single("s5")
    _login(page, live_server, "s5")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator(".slideshow-bar")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_lesson_completes_after_paging_tall_slides(page, live_server):
    # slide 0 is taller than the viewport; the student never scrolls, only pages.
    student, path = _seed_slideshow_lesson_tall("s6")  # 3 slides, slide 0 tall
    _login(page, live_server, "s6")
    page.goto(f"{live_server.url}{path}")
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Next").click()
    expect(page.locator("[data-unit-done]")).to_have_class(re.compile(r"is-complete"))


@pytest.mark.django_db(transaction=True)
def test_finish_hidden_until_last_slide(page, live_server):
    student, path = _seed_slideshow_quiz_3("s7")  # quiz, 3 slides
    _login(page, live_server, "s7")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator("[data-quiz-finish]")).to_be_hidden()
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Next").click()
    expect(page.locator("[data-quiz-finish]")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_math_widget_on_slide_2_renders_at_width(page, live_server):
    # MathElement renders via KaTeX into `.el--math[data-katex]`, which katex.render()
    # rewrites in place into a `.katex` node (there is no live <math-field> on taking
    # pages — that custom element only exists in the builder's math-insert modal, see
    # courses/static/courses/js/math_input.js). Assert on the actual rendered KaTeX
    # container, mirroring tests/test_e2e_quiz_math.py's pattern.
    student, path = _seed_slideshow_quiz_math("s8")  # slide 2 has a math element
    _login(page, live_server, "s8")
    page.goto(f"{live_server.url}{path}")
    page.get_by_role("button", name="Next").click()
    math_node = page.locator(".slide.is-active .el--math .katex").first
    math_node.wait_for(state="attached", timeout=5000)
    box = math_node.bounding_box()
    assert box["width"] > 50  # not collapsed to ~0 (relayout fired)


@pytest.mark.django_db(transaction=True)
def test_author_adds_slide_break_divider_row(page, live_server):
    # Builder authoring UI (Task 12): the "Slide break" palette entry creates
    # directly (no editor form opens) and renders as a divider row.
    author, path = _seed_builder_unit("author1")
    _login(page, live_server, "author1")
    page.goto(f"{live_server.url}{path}")
    page.locator("[data-add-toggle]").click()
    page.locator('[data-add-type="slidebreak"]').click()
    expect(
        page.locator(".element-row--slidebreak, [data-slidebreak-row]")
    ).to_have_count(1)


@pytest.mark.django_db(transaction=True)
def test_nav_buttons_are_arrow_only(page, live_server):
    # Buttons render an icon only (no visible text) but keep an accessible name
    # via aria-label; get_by_role name= still resolves by substring match.
    student, path = _seed_slideshow_lesson_3("s_arrows")
    _login(page, live_server, "s_arrows")
    page.goto(f"{live_server.url}{path}")
    nxt = page.get_by_role("button", name="Next")
    expect(nxt).to_be_visible()
    # aria-label carries the accessible name; no visible text node.
    assert nxt.get_attribute("aria-label") == "Next slide"
    assert (nxt.inner_text() or "").strip() == ""
    prv = page.get_by_role("button", name="Previous")
    assert prv.get_attribute("aria-label") == "Previous slide"


@pytest.mark.django_db(transaction=True)
def test_deck_structure(page, live_server):
    student, path = _seed_slideshow_lesson_3("s_struct")
    _login(page, live_server, "s_struct")
    page.goto(f"{live_server.url}{path}")
    # deck wraps stage (with the slides) and the bar as its footer
    expect(page.locator(".slideshow-deck .slideshow-stage .slide")).to_have_count(3)
    expect(page.locator(".slideshow-deck > .slideshow-bar")).to_have_count(1)
    # head + trailing regions stay OUTSIDE the deck
    expect(page.locator(".slideshow-deck [data-unit-done]")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_bar_position_is_stable_across_slides(page, live_server):
    # The core fix: bar y must not move between a short slide and a tall one.
    student, path = _seed_slideshow_lesson_short_first_tall_later("s_stable")
    _login(page, live_server, "s_stable")
    page.goto(f"{live_server.url}{path}")
    bar = page.locator(".slideshow-bar")
    # Warm-up click: unrelated to the deck under test, this settles a pre-existing
    # queued animation (unit_nav.js centers the active sidebar entry with a
    # window-level `scrollIntoView({behavior:"smooth"})` on load) that Chromium
    # otherwise defers until the first trusted user gesture, which would otherwise
    # land on our first "Next" click and get misread as deck instability. Click a
    # non-interactive part of the bar so slide state (idx) is untouched.
    bar.click()
    page.wait_for_timeout(300)
    y0 = bar.bounding_box()["y"]
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Next").click()  # to the tall slide 2
    y2 = bar.bounding_box()["y"]
    assert abs(y0 - y2) < 2, f"bar moved: {y0} -> {y2}"


@pytest.mark.django_db(transaction=True)
def test_multi_slide_lesson_not_completed_on_load(page, live_server):
    # display:none-at-rest keeps progress.js's IntersectionObserver from marking
    # unvisited slides seen, so a fresh multi-slide lesson is NOT auto-completed.
    student, path = _seed_slideshow_lesson_3("s_noauto")
    _login(page, live_server, "s_noauto")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator(".slideshow-bar")).to_be_visible()  # deck built
    expect(page.locator("[data-unit-done]")).not_to_have_class(
        re.compile(r"is-complete")
    )


@pytest.mark.django_db(transaction=True)
def test_no_js_shows_all_slides(browser, live_server):
    # No-JS fallback: with JavaScript disabled, slideshow.js never runs, so the
    # `html.js` class is never set and no `.slide` is marked `.is-active`. Every
    # slide must therefore stay visible (flat page) — a regression guard for the
    # slide-hiding CSS being wrongly ungated from `html.js` (which would blank the
    # whole unit for no-JS visitors, letting a quiz be submitted unseen).
    student, path = _seed_slideshow_lesson_3("snojs")
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    try:
        _login(page, live_server, "snojs")
        page.goto(f"{live_server.url}{path}")
        # No JS => the control bar was never built.
        expect(page.locator(".slideshow-bar")).to_have_count(0)
        # All three content sections across the three slides remain visible.
        sections = page.locator("[data-slideshow] .slide [data-element-id]")
        expect(sections).to_have_count(3)
        for i in range(3):
            expect(sections.nth(i)).to_be_visible()
    finally:
        context.close()
