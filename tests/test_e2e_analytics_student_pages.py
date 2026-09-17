"""Computed-style checks for the analytics student pages (spec §7.4: T14, T33,
T33b, T33c). Each rule is A/B'd in place where a test can neutralise the rule,
otherwise by the plan's listed mutants.

Marked e2e (excluded from the default run; use -m e2e)."""

import os
from decimal import Decimal
from itertools import pairwise

import pytest
from django.urls import reverse

from tests.factories import TEST_PASSWORD

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


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
    page.wait_for_load_state()


def _neutralise(page, css):
    page.add_style_tag(content=css)


def _box(locator):
    return locator.evaluate(
        """el => {
             const r = el.getBoundingClientRect();
             return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width};
           }"""
    )


def _style(locator, prop):
    return locator.evaluate("(el, p) => getComputedStyle(el)[p]", prop)


def _token_colour(page, token):
    """The browser's resolved `color: var(<token>)`, via a throwaway probe
    element (a CSS custom property cannot be read directly from `getComputedStyle`
    on `:root`; it must be applied to a `color`-like property first)."""
    return page.evaluate(
        """(t) => { const p = document.createElement('span');
                     p.style.color = `var(${t})`; document.body.appendChild(p);
                     const c = getComputedStyle(p).color; p.remove(); return c; }""",
        token,
    )


def _seed_breakdown(client, username):
    from courses.models import Element
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import QuestionElement
    from courses.models import QuizSubmission
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import UnitProgressFactory
    from tests.factories import UserFactory
    from tests.factories import make_pa

    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Chapter"
    )

    def unit(title, unit_type, **kw):
        return ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type=unit_type,
            parent=ch,
            title=title,
            **kw,
        )

    done = unit("Done lesson", "lesson", obligatory=True)
    unit("Extra lesson", "lesson", obligatory=False)
    scored = unit("Scored quiz", "quiz")
    awaiting = unit("Awaiting quiz", "quiz")
    Element.objects.create(
        unit=scored,
        content_object=ShortTextQuestionElement.objects.create(
            stem="<p>Q</p>", accepted="a", max_marks=Decimal("1")
        ),
    )
    Element.objects.create(
        unit=awaiting,
        content_object=ExtendedResponseQuestionElement.objects.create(
            stem="<p>E</p>",
            required_keywords="",
            forbidden_keywords="",
            marking_mode=QuestionElement.MarkingMode.REVIEW,
            max_marks=Decimal("1"),
        ),
    )
    student = UserFactory(first_name="Anna", last_name="Nowak")
    EnrollmentFactory(student=student, course=course)
    UnitProgressFactory(student=student, unit=done, completed=True)
    QuizSubmission.objects.create(
        student=student,
        unit=scored,
        status="submitted",
        score=Decimal("1"),
        max_score=Decimal("1"),
    )
    QuizSubmission.objects.create(
        student=student,
        unit=awaiting,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    return course, student, awaiting


def _open_breakdown(page, live_server, client, username):
    course, student, awaiting = _seed_breakdown(client, username)
    _login(page, live_server, username)
    path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{live_server.url}{path}")
    page.wait_for_selector(".breakdown-unit")
    return course, student, awaiting


def _row(page, title):
    return page.locator(".breakdown-unit").filter(
        has=page.locator(".breakdown-unit__title", has_text=title)
    )


def test_t14_quiz_title_link_is_underlined_without_hover(page, live_server, client):
    _open_breakdown(page, live_server, client, "e2e_sp_link")
    link = _row(page, "Scored quiz").locator("a.breakdown-unit__link")
    assert "underline" in _style(link, "textDecorationLine")
    assert _style(link, "color") == _token_colour(page, "--accent")
    _neutralise(page, ".breakdown-unit__link{text-decoration:none;color:inherit}")
    assert "underline" not in _style(link, "textDecorationLine")


def test_t33_breakdown_right_column(page, live_server, client):
    _open_breakdown(page, live_server, client, "e2e_sp_column")
    scored = _row(page, "Scored quiz")
    pill = scored.locator(".pill")
    assert abs(_box(scored)["r"] - _box(pill)["r"]) <= 1

    awaiting = _row(page, "Awaiting quiz")
    a_pill, review = (
        awaiting.locator(".pill"),
        awaiting.locator(".breakdown-unit__review"),
    )
    assert _box(a_pill)["r"] < _box(review)["l"]  # pill, then link
    assert _box(review)["l"] - _box(a_pill)["r"] < 24  # travelling together
    assert abs(_box(awaiting)["r"] - _box(review)["r"]) <= 1

    extra = _row(page, "Extra lesson")
    title, tag = (
        extra.locator(".breakdown-unit__title"),
        extra.locator(".breakdown-unit__tag"),
    )
    todo = extra.locator(".badge--todo")
    assert _box(title)["r"] <= _box(tag)["l"] < _box(todo)["l"]
    assert _box(tag)["l"] - _box(title)["r"] < 24  # the tag follows the title
    assert abs(_box(extra)["r"] - _box(todo)["r"]) <= 1

    _neutralise(page, ".breakdown-unit .pill,.badge--todo{margin-left:0}")
    assert _box(scored)["r"] - _box(pill)["r"] > 50
    assert _box(extra)["r"] - _box(todo)["r"] > 50


def test_t33_breakdown_lesson_titles_share_one_colour(page, live_server, client):
    _open_breakdown(page, live_server, client, "e2e_sp_colour")
    done = _row(page, "Done lesson").locator(".breakdown-unit__title")
    extra = _row(page, "Extra lesson").locator(".breakdown-unit__title")
    assert "is-done" in (done.get_attribute("class") or "")
    assert _style(done, "color") == _style(extra, "color")
    _neutralise(page, ".breakdown-unit__title.is-done{color:var(--text-secondary)}")
    assert _style(done, "color") != _style(extra, "color")


def test_t33_per_question_header_pill_is_not_pushed(page, live_server, client):
    course, student, awaiting = _open_breakdown(page, live_server, client, "e2e_sp_hdr")
    path = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": awaiting.pk},
    )
    page.goto(f"{live_server.url}{path}")
    status = page.locator(".answers__status")
    pill, review = status.locator(".pill"), status.locator(".answers__review")
    assert abs(_box(pill)["l"] - _box(status)["l"]) <= 1
    assert _box(review)["l"] - _box(pill)["r"] < 24


def test_t33c_todo_marker_is_not_painted_as_done(page, live_server, client):
    _open_breakdown(page, live_server, client, "e2e_sp_todo")
    done = _row(page, "Done lesson").locator(".badge--done")
    todo = _row(page, "Extra lesson").locator(".badge--todo")
    assert _style(todo, "backgroundColor") != _style(done, "backgroundColor")
    assert _style(todo, "borderTopColor") != _style(done, "borderTopColor")


def _seed_choice_page(client, username):
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import Element
    from courses.models import QuestionResponse
    from courses.models import QuizSubmission
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import UserFactory
    from tests.factories import make_pa

    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Choice quiz"
    )
    question = ChoiceQuestionElement.objects.create(
        stem="<p>Pick</p>", max_marks=Decimal("1"), multiple=True
    )
    picked = None
    for order, text in enumerate(("Alpha", "Beta", "Gamma")):
        choice = Choice.objects.create(
            question=question, text=text, is_correct=text == "Beta", order=order
        )
        if text == "Alpha":
            picked = choice
    el = Element.objects.create(unit=quiz, content_object=question)
    student = UserFactory(first_name="Anna", last_name="Nowak")
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("1"),
    )
    QuestionResponse.objects.create(
        submission=sub,
        element=el,
        latest_answer=[picked.pk],
        fraction=Decimal("0"),
        attempt_count=1,
    )
    return reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": quiz.pk},
    )


@pytest.mark.parametrize("width", [1280, 390])
def test_t33_option_headers_visible_on_desktop_hidden_on_a_phone(
    page, live_server, client, width
):
    path = _seed_choice_page(client, f"e2e_sp_th{width}")
    _login(page, live_server, f"e2e_sp_th{width}")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{live_server.url}{path}")
    ths = page.locator("table.answers__options th")
    # Every th, not just the first: the trailing plain th (no -mark class) is
    # collapsed ONLY by the ".answers__options th" half of the selector.
    count = ths.count()
    assert count >= 2
    if width == 1280:
        for i in range(count):
            assert _box(ths.nth(i))["w"] > 20
    else:
        for i in range(count):
            assert _box(ths.nth(i))["w"] <= 1
        th = ths.first
        _neutralise(
            page,
            # (0,2,1): must out-rank the collapse rule's th.answers__options-mark half
            ".answers__options th.answers__options-mark{position:static;width:auto;"
            "height:auto;clip:auto;margin:0}",
        )
        assert _box(th)["w"] > 20


def _seed_fillblank_page(client, username):
    from courses.fillblank import SENTINEL
    from courses.models import Blank
    from courses.models import Element
    from courses.models import FillBlankQuestionElement
    from courses.models import QuestionResponse
    from courses.models import QuizSubmission
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import UserFactory
    from tests.factories import make_pa

    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Gaps quiz"
    )
    t0, t1 = f"{SENTINEL}0{SENTINEL}", f"{SENTINEL}1{SENTINEL}"
    question = FillBlankQuestionElement.objects.create(
        stem=f"<p>{t0} and {t1}</p>", max_marks=Decimal("1")
    )
    Blank.objects.create(question=question, accepted="2", order=0)
    Blank.objects.create(question=question, accepted="4", order=1)
    el = Element.objects.create(unit=quiz, content_object=question)
    student = UserFactory(first_name="Anna", last_name="Nowak")
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("0.5"),
        max_score=Decimal("1"),
    )
    QuestionResponse.objects.create(
        submission=sub,
        element=el,
        latest_answer=["2", "a considerably longer wrong answer"],
        fraction=Decimal("0.5"),
        attempt_count=1,
    )
    return reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": quiz.pk},
    )


def test_t33_multi_part_grid_aligns_columns_on_desktop(page, live_server, client):
    path = _seed_fillblank_page(client, "e2e_sp_grid")
    _login(page, live_server, "e2e_sp_grid")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{live_server.url}{path}")
    parts = page.locator(".answers__parts--columned > .answers__part")
    given = [_box(parts.nth(i).locator(".answers__given-cell")) for i in range(2)]
    expected_cells = [
        _box(parts.nth(i).locator(".answers__expected")) for i in range(2)
    ]
    assert abs(given[0]["l"] - given[1]["l"]) <= 1
    assert abs(expected_cells[0]["l"] - expected_cells[1]["l"]) <= 1
    header = page.locator(".answers__header-row > span")
    assert abs(_box(header.nth(2))["l"] - expected_cells[1]["l"]) <= 1
    assert _style(parts.nth(1).locator(".answers__expected-label"), "display") == "none"
    # B leg: without the grid the rows are independent flex lines again.
    _neutralise(
        page,
        ".answers__parts--columned{display:block}"
        ".answers__parts--columned .answers__part{display:flex}",
    )
    moved = [_box(parts.nth(i).locator(".answers__expected")) for i in range(2)]
    assert abs(moved[0]["l"] - moved[1]["l"]) > 20


def test_t33_multi_part_block_fallback_on_a_phone(page, live_server, client):
    path = _seed_fillblank_page(client, "e2e_sp_grid390")
    _login(page, live_server, "e2e_sp_grid390")
    page.set_viewport_size({"width": 390, "height": 900})
    page.goto(f"{live_server.url}{path}")
    part = page.locator(".answers__parts--columned > .answers__part").nth(1)
    assert _style(page.locator(".answers__header-row"), "display") == "none"
    assert _style(page.locator(".answers__parts--columned"), "display") == "block"
    assert _style(part, "flexDirection") == "column"
    label = part.locator(".answers__expected-label")
    assert _style(label, "display") != "none" and _box(label)["w"] > 0


@pytest.mark.parametrize("width", [1280, 390])
def test_t33_back_button_stays_beside_a_long_title(page, live_server, client, width):
    from courses.models import ContentNode

    username = f"e2e_sp_head{width}"
    course, student, awaiting = _seed_breakdown(client, username)
    ContentNode.objects.filter(pk=awaiting.pk).update(
        title="A deliberately long quiz title that would push the back button " * 2
    )
    _login(page, live_server, username)
    page.set_viewport_size({"width": width, "height": 900})
    path = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": awaiting.pk},
    )
    page.goto(f"{live_server.url}{path}")
    head = page.locator(".answers .manage__head")
    heading, button = head.locator(".answers__heading"), head.locator(".btn")
    if width == 1280:
        assert _box(button)["t"] < _box(heading)["b"]  # same line
        assert abs(_box(head)["r"] - _box(button)["r"]) <= 1
        _neutralise(page, ".answers .manage__head{flex-wrap:wrap}")
        assert _box(button)["t"] >= _box(heading)["b"] - 1
    else:
        assert _box(button)["t"] >= _box(heading)["b"] - 1  # wraps below, as today
    # the shared header on another page still wraps
    page.set_viewport_size({"width": 1280, "height": 900})
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    page.goto(f"{live_server.url}{matrix_path}")
    assert _style(page.locator(".manage__head").first, "flexWrap") == "wrap"


def _seed_outcomes(client, username):
    from courses.models import Element
    from courses.models import QuestionResponse
    from courses.models import QuizSubmission
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_pa
    from tests.factories import make_verified_user

    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Outcomes"
    )
    student = make_verified_user(
        username=f"{username}_s",
        email=f"{username}_s@t.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("1.5"),
        max_score=Decimal("3"),
    )
    for fraction in ("1", "0.5", "0"):
        el = Element.objects.create(
            unit=quiz,
            content_object=ShortTextQuestionElement.objects.create(
                stem="<p>Q</p>", accepted="a", max_marks=Decimal("1")
            ),
        )
        QuestionResponse.objects.create(
            submission=sub,
            element=el,
            latest_answer="x",
            fraction=Decimal(fraction),
            attempt_count=1,
        )
    return pa, student, course, quiz


OUTCOMES = ("correct", "partial", "incorrect")
OUTCOME_TOKEN = {
    "correct": "--success",
    "partial": "--warning",
    "incorrect": "--danger",
}


def _contrast(fg, bg):
    """WCAG contrast ratio of two computed `rgb(...)`/`rgba(...)` colours (opaque)."""

    def luminance(css):
        inner = css[css.index("(") + 1 : css.index(")")]
        r, g, b = (int(v) / 255 for v in inner.split(",")[:3])
        lin = [
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            for c in (r, g, b)
        ]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_t33b_badge_has_its_own_opaque_surface_on_both_pages(
    page, live_server, client, theme
):
    username = f"e2e_sp_badge_{theme}"
    pa, student, course, quiz = _seed_outcomes(client, username)
    for user in (pa, student):
        user.theme = theme
        user.save(update_fields=["theme"])

    _login(page, live_server, username)
    teacher_path = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": quiz.pk},
    )
    page.goto(f"{live_server.url}{teacher_path}")
    text_primary = _token_colour(page, "--text-primary")
    for outcome in OUTCOMES:
        outcome_colour = _token_colour(page, OUTCOME_TOKEN[outcome])
        item = page.locator(f"li.answers__item.is-{outcome}")
        badge = item.locator(".answers__verdict .badge")
        bg = _style(badge, "backgroundColor")
        assert bg not in ("rgba(0, 0, 0, 0)", "transparent"), outcome
        assert bg != _style(item, "backgroundColor"), outcome
        assert _contrast(_style(badge, "color"), bg) >= 4.5, (outcome, theme)
        assert _style(badge, "color") == text_primary, outcome
        assert _style(badge, "borderTopColor") == outcome_colour, outcome
        assert _style(item, "borderLeftWidth") == "4px", outcome
        assert _style(item, "borderLeftColor") == outcome_colour, outcome

    page.context.clear_cookies()
    _login(page, live_server, f"{username}_s")
    results_path = reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    page.goto(f"{live_server.url}{results_path}")
    for outcome in OUTCOMES:
        outcome_colour = _token_colour(page, OUTCOME_TOKEN[outcome])
        panel = page.locator(f".question__feedback-panel--{outcome}")
        badge = panel.locator(".badge")
        bg = _style(badge, "backgroundColor")
        assert bg not in ("rgba(0, 0, 0, 0)", "transparent"), outcome
        assert bg != _style(panel, "backgroundColor"), outcome
        assert _contrast(_style(badge, "color"), bg) >= 4.5, (outcome, theme)
        assert _style(badge, "color") == text_primary, outcome
        assert _style(badge, "borderTopColor") == outcome_colour, outcome


# --- results-table spec (2026-09-17) §2.4 / §7: the Results table --------------------
RT_LONG_TITLE = "Bardzo długi tytuł quizu na trzecim poziomie zagnieżdżenia tego kursu"
RT_MATH_TITLE = (
    # A SINGLE brace group around the whole formula body: no top-level relation
    # or binary operator, so KaTeX emits exactly one `.base` run, which the
    # vendored `.katex .base{display:inline-block; white-space:nowrap}` makes
    # one atomic inline box (unbreakable) -- not the app.css punctuation rule.
    # Without the wrapping braces the top-level `=`/`+` would split it into
    # several `.base` runs, which wraps instead of widening the table (T8b).
    r"Wzór \({\sum_{k=1}^{n} k^{2} = \frac{n(n+1)(2n+1)}{6}"
    r" = \int_{0}^{n} x^{2}\,dx + \sqrt{a^{2}+b^{2}+c^{2}+d^{2}+e^{2}}}\)"
)
# Spec §7 T8a: a FLOOR, measured by plan Task 7 on this fixture and on mat-pp before
# it was committed. A design pass may raise it, never lower it.
RT_TITLE_SHARE_FLOOR = 0.30
# Spec §2.3's computed padding-inline-start of d0..d3 title cells, in rem, by width.
RT_DEPTH_REM = {
    1280: (0.5, 1.5, 2.5, 3.5),
    600: (0.5, 1.0, 1.5, 2.0),
    390: (0.25, 0.75, 1.25, 1.75),
}


def _seed_results_table(client, username, *, theme="light", deep_title=RT_LONG_TITLE):
    """The Results-table fixture, rendered in Polish for a PA who owns the course:

    Część pierwsza (d0)               3/5   812,5/960,5  85%
      Rozdział z sekcjami (d1)        3/5   812,5/960,5  85%
        Sekcja pełna (d2)             2/4   804/850      95%
          <deep_title> (d3)           800/800  100%
          Mały quiz (d3)              4/50     8%
          Quiz do sprawdzenia (d3)    awaiting review + its Review link
          Quiz w toku (d3)            in progress
        Sekcja z jednym quizem (d2)   one quiz: no figures
          Jedyny quiz (d3)            8,5/110,5  8%
    Część druga (d0)                  one quiz: no figures
      Quiz nierozpoczęty (d1)         not started
    Cały kurs (total, first)          3/6   812,5/960,5  85%
    """
    from courses.models import Element
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import QuestionElement
    from courses.models import QuizSubmission
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import UserFactory
    from tests.factories import make_pa

    pa = make_pa(client, username)
    pa.language = "pl"
    pa.theme = theme
    pa.save(update_fields=["language", "theme"])
    course = CourseFactory(owner=pa)
    student = UserFactory(
        first_name="Anna", last_name="Nowak", display_name="Anna Nowak"
    )
    EnrollmentFactory(student=student, course=course)

    def node(parent, kind, title, **kw):
        kw.setdefault("unit_type", None)
        return ContentNodeFactory(
            course=course, parent=parent, kind=kind, title=title, **kw
        )

    def quiz(parent, title):
        return node(parent, "unit", title, unit_type="quiz")

    def submitted(unit, score, max_score):
        QuizSubmission.objects.create(
            student=student,
            unit=unit,
            status=QuizSubmission.Status.SUBMITTED,
            score=Decimal(score),
            max_score=Decimal(max_score),
        )

    chapter = node(
        node(None, "part", "Część pierwsza"), "chapter", "Rozdział z sekcjami"
    )
    full = node(chapter, "section", "Sekcja pełna")
    submitted(quiz(full, deep_title), "800", "800")
    submitted(quiz(full, "Mały quiz"), "4", "50")
    awaiting = quiz(full, "Quiz do sprawdzenia")
    Element.objects.create(
        unit=awaiting,
        content_object=ExtendedResponseQuestionElement.objects.create(
            stem="<p>E</p>",
            required_keywords="",
            forbidden_keywords="",
            marking_mode=QuestionElement.MarkingMode.REVIEW,
            max_marks=Decimal("1"),
        ),
    )
    submitted(awaiting, "0", "0")
    QuizSubmission.objects.create(
        student=student,
        unit=quiz(full, "Quiz w toku"),
        status=QuizSubmission.Status.IN_PROGRESS,
    )
    single = node(chapter, "section", "Sekcja z jednym quizem")
    submitted(quiz(single, "Jedyny quiz"), "8.5", "110.5")
    quiz(node(None, "part", "Część druga"), "Quiz nierozpoczęty")
    return course, student


def _open_results_table(
    page,
    live_server,
    client,
    username,
    *,
    width,
    theme="light",
    deep_title=RT_LONG_TITLE,
):
    course, student = _seed_results_table(
        client, username, theme=theme, deep_title=deep_title
    )
    _login(page, live_server, username)
    page.set_viewport_size({"width": width, "height": 900})
    path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    page.goto(f"{live_server.url}{path}?mode=results")
    page.wait_for_selector("table.results-table")
    return course, student


def _rt_row(page, title):
    return page.locator("table.results-table tbody tr").filter(
        has=page.locator("th", has_text=title)
    )


def _lines(locator):
    """How many line boxes the element's own text occupies."""
    return locator.evaluate(
        """el => { const r = document.createRange(); r.selectNodeContents(el);
             const tops = new Set();
             for (const b of r.getClientRects()) {
               if (b.width > 0) tops.add(Math.round(b.top));
             }
             return tops.size; }"""
    )


def _text_edges(locator):
    """Gaps between the element's text and its content box: {left, right} in px."""
    return locator.evaluate(
        """el => { const r = document.createRange(); r.selectNodeContents(el);
             const t = r.getBoundingClientRect(); const c = el.getBoundingClientRect();
             const s = getComputedStyle(el);
             const left = c.left + parseFloat(s.borderLeftWidth)
               + parseFloat(s.paddingLeft);
             const right = c.right - parseFloat(s.borderRightWidth)
               - parseFloat(s.paddingRight);
             return {left: t.left - left, right: right - t.right}; }"""
    )


def _effective_background(locator):
    """The first non-transparent background at or above the element."""
    return locator.evaluate(
        """el => { for (let n = el; n; n = n.parentElement) {
               const c = getComputedStyle(n).backgroundColor;
               if (c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c;
             }
             return null; }"""
    )


def _page_fits(page):
    return page.evaluate(
        "() => document.documentElement.scrollWidth"
        " <= document.documentElement.clientWidth"
    )


def _px(value):
    return float(value.removesuffix("px"))


@pytest.mark.parametrize("width", [1280, 600, 390])
def test_rt_t5d_title_indent_grows_with_depth_at_every_width(
    page, live_server, client, width
):
    _open_results_table(page, live_server, client, f"e2e_rt_indent{width}", width=width)
    rem = page.evaluate(
        "() => parseFloat(getComputedStyle(document.documentElement).fontSize)"
    )
    pads = []
    for depth in range(4):
        cell = page.locator(f"table.results-table tbody th.results-table__d{depth}")
        pads.append(_px(_style(cell.first, "paddingInlineStart")))
    assert all(deeper > shallower for shallower, deeper in pairwise(pads)), pads
    for got, want in zip(pads, RT_DEPTH_REM[width], strict=True):
        assert abs(got - want * rem) < 0.5, (width, pads)


def test_rt_t8a_phone_table_fits_and_keeps_the_title_share(page, live_server, client):
    _open_results_table(page, live_server, client, "e2e_rt_phone", width=390)
    # No formula title: a KaTeX formula would set the title column's minimum width.
    assert page.locator("table.results-table .katex").count() == 0
    awaiting = _rt_row(page, "Quiz do sprawdzenia")
    assert awaiting.locator("a.breakdown-unit__review").count() == 1
    assert _page_fits(page)
    wrap = page.locator(".results-table-wrap")
    scroll_w, client_w = wrap.evaluate("el => [el.scrollWidth, el.clientWidth]")
    assert scroll_w <= client_w, (scroll_w, client_w)
    title_w = _box(page.locator("table.results-table thead th.results-table__title"))
    share = title_w["w"] / _box(page.locator("table.results-table"))["w"]
    print(f"[rt] title share at 390px: {share:.3f}")
    assert share >= RT_TITLE_SHARE_FLOOR, share
    total = page.locator("tr.results-table__total")
    single_line = (
        total.locator("td").nth(1),  # 812,5/960,5
        total.locator("td").nth(2),  # 85%
        _rt_row(page, RT_LONG_TITLE).locator("td").nth(2),  # 100%
        _rt_row(page, "Rozdział z sekcjami").locator("td").nth(0),  # 3/5
    )
    for cell in single_line:
        assert _lines(cell) == 1, cell.text_content()


def test_rt_t8b_a_long_formula_scrolls_the_table_not_the_page(
    page, live_server, client
):
    _open_results_table(
        page, live_server, client, "e2e_rt_formula", width=390, deep_title=RT_MATH_TITLE
    )
    page.wait_for_selector("table.results-table .katex")
    wrap = page.locator(".results-table-wrap")
    scroll_w, client_w = wrap.evaluate("el => [el.scrollWidth, el.clientWidth]")
    assert scroll_w > client_w  # precondition: the formula really widens the table
    assert _page_fits(page)


def test_rt_t8c_numbers_are_right_aligned(page, live_server, client):
    _open_results_table(page, live_server, client, "e2e_rt_align", width=1280)
    cells = _rt_row(page, "Mały quiz").locator("td")
    # „4/50" sits under the total's „812,5/960,5", „8%" under „100%": narrower than
    # their columns, so only the alignment decides where the text sits.
    for cell in (cells.nth(1), cells.nth(2)):
        edges = _text_edges(cell)
        assert abs(edges["right"]) <= 1, edges
        assert edges["left"] > 1, edges


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_rt_t13_heading_rows_are_tinted_and_bold_and_headers_align(
    page, live_server, client, theme
):
    _open_results_table(
        page, live_server, client, f"e2e_rt_rows_{theme}", width=1280, theme=theme
    )
    base = _token_colour(page, "--surface-base")
    heading = _rt_row(page, "Sekcja pełna")
    lone_heading = _rt_row(
        page, "Sekcja z jednym quizem"
    )  # no figures, still a heading
    total = page.locator("tr.results-table__total")
    for row in (heading, lone_heading, total):
        assert "results-table__section" in row.get_attribute("class")
        assert _style(row, "backgroundColor") == base
    quiz_title = _rt_row(page, "Mały quiz").locator("th")
    assert _effective_background(quiz_title) != base
    for cell in (
        heading.locator("th"),
        heading.locator("td").nth(0),
        heading.locator("td").nth(1),
        total.locator("th"),
    ):
        assert int(_style(cell, "fontWeight")) >= 600
    assert int(_style(quiz_title, "fontWeight")) < 600
    assert _style(quiz_title, "textAlign") in ("start", "left")
    headers = page.locator("table.results-table thead th.results-table__num").all()
    assert len(headers) == 2
    for header in headers:  # „Wynik" and „%": each narrower than its column's data
        edges = _text_edges(header)
        assert abs(edges["right"]) <= 1, (header.text_content(), edges)
        assert edges["left"] > 1, (header.text_content(), edges)


def test_rt_t13b_desktop_pills_stay_on_one_line(page, live_server, client):
    _open_results_table(page, live_server, client, "e2e_rt_pills", width=1280)
    pills = page.locator("table.results-table .pill").all()
    assert len(pills) == 3  # awaiting, in progress, not started
    for pill in pills:
        assert _lines(pill) == 1, pill.text_content()


def test_rt_t13c_a_coloured_cell_shows_its_band_not_the_tint(page, live_server, client):
    from courses.color_bands import band_style
    from courses.color_bands import default_color_bands

    _open_results_table(page, live_server, client, "e2e_rt_band", width=1280)
    hex_colour = band_style(95, default_color_bands())["bg"]  # Sekcja pełna: 95%
    band = "rgb({}, {}, {})".format(
        *(int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    )
    cell = _rt_row(page, "Sekcja pełna").locator("td").nth(2)
    assert _style(cell, "backgroundColor") == band
    assert band != _token_colour(page, "--surface-base")


def test_rt_t13d_the_total_row_has_a_heavier_rule_below(page, live_server, client):
    _open_results_table(page, live_server, client, "e2e_rt_total", width=1280)
    strong = _token_colour(page, "--border-strong")
    cells = page.locator(
        "tr.results-table__total > th, tr.results-table__total > td"
    ).all()
    assert len(cells) == 4
    for cell in cells:
        assert _style(cell, "borderBottomWidth") == "2px"
        assert _style(cell, "borderBottomColor") == strong
