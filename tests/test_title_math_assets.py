"""Shared KaTeX partials, defect 3 (missing math.js), and the per-page gate."""

import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_pa
from tests.helpers_title_math import login_student

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
JS_PARTIAL = ROOT / "templates/courses/_katex_js.html"
CSS_PARTIAL = ROOT / "templates/courses/_katex_css.html"

KATEX_JS = "courses/vendor/katex/katex.min.js"
KATEX_CSS = "courses/vendor/katex/katex.min.css"
MATH_JS = "courses/js/math.js"
QUESTION_JS = "courses/js/question.js"


# --- the partials themselves --------------------------------------------------
def test_js_partial_self_loads_static():
    """Template libraries are NOT inherited from the including template; omitting
    {% load static %} here is a TemplateSyntaxError."""
    assert "{% load static %}" in JS_PARTIAL.read_text(encoding="utf-8")


def test_css_partial_self_loads_static():
    assert "{% load static %}" in CSS_PARTIAL.read_text(encoding="utf-8")


def test_js_partial_keeps_the_load_bearing_script_order():
    """math_reflow.js pre-hooks renderMathInElement/katex.render with a SINGLE
    install attempt and no deferred retry, precisely because it is loaded after
    both vendor files. text_colour.js post-hooks the same two globals. math.js
    runs the document pass and must be last."""
    src = JS_PARTIAL.read_text(encoding="utf-8")
    order = [
        "courses/vendor/katex/katex.min.js",
        "courses/vendor/katex/contrib/auto-render.min.js",
        "courses/js/math_reflow.js",
        "courses/js/text_colour.js",
        "courses/js/math.js",
    ]
    positions = [src.index(name) for name in order]
    assert positions == sorted(positions), f"script order changed: {order}"


def test_every_script_in_the_js_partial_is_deferred():
    """A single non-deferred tag silently reorders execution -- source order only
    guarantees execution order AMONG defer scripts. Worse, a non-deferred math.js
    runs DURING parsing and typesets nothing below its own tag, a failure that
    looks exactly like a missing marker."""
    src = JS_PARTIAL.read_text(encoding="utf-8")
    # Match TAGS, not lines: a line-based count changes when a tag wraps across
    # two lines or a comment merely mentions "<script", and under-counts two tags
    # on one line -- brittle for exactly the edit (adding a KaTeX-family asset)
    # this assertion is meant to police. \b so "<scripting" cannot match.
    tags = re.findall(r"<script\b[^>]*>", src)
    assert len(tags) == 5, f"expected 5 script tags, found {len(tags)}: {tags}"
    assert all(re.search(r"\sdefer(\s|>)", t) for t in tags), tags


# --- defect 3 -----------------------------------------------------------------
def _submitted_quiz_results_url(client, *, unit_title, stem):
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        order=0,
        title=unit_title,
    )
    q = ExtendedResponseQuestionElement.objects.create(
        stem=stem,
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    Element.objects.create(unit=quiz, content_object=q)
    student = login_student(client, course)
    QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    return reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )


def _review_url(client, *, unit_title, stem):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        order=0,
        title=unit_title,
    )
    q = ExtendedResponseQuestionElement.objects.create(
        stem=stem,
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    Element.objects.create(unit=unit, content_object=q)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=unit,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    return reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )


def test_quiz_results_now_ships_math_js_before_question_js(client):
    """A gate test phrased as "contains the KaTeX <script>" is green on this page
    BOTH before and after the change -- it already emits four KaTeX tags today. So
    without this assertion the one thing defect 3 promises to fix is pinned by
    nothing, and the §2 ordering constraint is unpinned too."""
    url = _submitted_quiz_results_url(
        client, unit_title="Plain", stem=r"<p>Explain \(x^2\).</p>"
    )
    body = client.get(url).content.decode()
    assert MATH_JS in body
    assert QUESTION_JS in body
    assert body.index(MATH_JS) < body.index(QUESTION_JS)


def test_review_submission_now_ships_math_js_before_question_js(client):
    url = _review_url(client, unit_title="Plain", stem=r"<p>Explain \(x^2\).</p>")
    body = client.get(url).content.decode()
    assert MATH_JS in body
    assert QUESTION_JS in body
    assert body.index(MATH_JS) < body.index(QUESTION_JS)


def test_review_submission_still_ships_question_js(client):
    """PRESERVE the retained question.js: dropping it regresses maths rendering in
    the read-only stem/answer and breaks
    test_review_views.py::test_review_loads_katex_when_stem_has_math."""
    url = _review_url(client, unit_title="Plain", stem=r"<p>Explain \(x^2\).</p>")
    assert QUESTION_JS in client.get(url).content.decode()


# --- the editor stays unconditional ------------------------------------------
def test_editor_ships_katex_for_a_unit_with_no_maths_anywhere(client):
    """The editor has NO {% if has_math %} wrapper and computes no has_math: it
    ships KaTeX on every unit because MathLive and the live preview need it
    regardless of content. Pins the behaviour the shared partial must preserve."""
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        order=0,
        title="Plain title",
    )
    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    body = client.get(url).content.decode()
    assert KATEX_JS in body
    assert KATEX_CSS in body
    assert MATH_JS in body


def test_editor_still_ships_mathlive_outside_the_shared_partial(client):
    """mathlive.min.js + math_input.js are NOT part of _katex_js.html -- no other
    page has a MathLive authoring surface."""
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        order=0,
        title="Plain title",
    )
    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    body = client.get(url).content.decode()
    assert "courses/vendor/mathlive/mathlive.min.js" in body
    assert "courses/js/math_input.js" in body
