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
from tests.helpers_title_math import MATHS_TITLE
from tests.helpers_title_math import login_student
from tests.helpers_title_math import make_title_course

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


# =============================================================================
# The gate: pages that already compute has_math
# =============================================================================


def _assert_katex_present(body):
    assert KATEX_JS in body, "KaTeX script missing"
    assert KATEX_CSS in body, "KaTeX stylesheet missing"


def _assert_katex_absent(body):
    assert KATEX_JS not in body
    assert KATEX_CSS not in body


def _lesson_url(course, unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )


def test_lesson_loads_katex_for_a_maths_title_on_the_unit_itself(client):
    course, unit, _n = make_title_course(maths_on="unitA")
    login_student(client, course)
    _assert_katex_present(client.get(_lesson_url(course, unit)).content.decode())


def test_lesson_loads_no_katex_when_nothing_carries_maths(client):
    course, unit, _n = make_title_course(maths_on="none")
    login_student(client, course)
    _assert_katex_absent(client.get(_lesson_url(course, unit)).content.decode())


def test_lesson_loads_katex_for_a_maths_title_sections_away(client):
    """THE TREE TRAP. On a unit page the contents tree is unit_nav["tree"], which
    build_unit_nav sets to the ENTIRE course outline, and _unit_tree_node.html
    renders all of it into the DOM whether collapsed or not. Scanning only unit /
    prev / next leaves a maths title three sections away rendering raw -- and it
    fails silently, because the page looks correct for the unit under test.

    This is the assertion that fails if the scan is narrowed. Without it the
    narrowing is invisible."""
    course, unit, nodes = make_title_course(maths_on="far")
    login_student(client, course)
    body = client.get(_lesson_url(course, unit)).content.decode()
    # Precondition: the viewed unit and BOTH its neighbours really are maths-free.
    assert "\\(" not in nodes["unitA"].title
    assert "\\(" not in nodes["unitB"].title
    assert "\\(" not in nodes["part1"].title
    _assert_katex_present(body)


def test_quiz_unit_with_zero_questions_loads_katex_for_a_maths_title(client):
    """The fixture MUST have zero questions: has_math = bool(questions) or ...
    (views.py:1318), so any quiz with a single question already loads KaTeX and
    the positive assertion would be vacuous."""
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        order=0,
        title=MATHS_TITLE,
    )
    login_student(client, course)
    url = reverse("courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk})
    _assert_katex_present(client.get(url).content.decode())


def test_quiz_unit_with_zero_questions_and_no_maths_loads_none(client):
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        order=0,
        title="Plain quiz",
    )
    login_student(client, course)
    url = reverse("courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk})
    _assert_katex_absent(client.get(url).content.decode())


def test_quiz_results_loads_katex_for_a_maths_title(client):
    url = _submitted_quiz_results_url(
        client, unit_title=MATHS_TITLE, stem="<p>Explain plainly.</p>"
    )
    _assert_katex_present(client.get(url).content.decode())


def test_quiz_results_loads_no_katex_without_maths(client):
    url = _submitted_quiz_results_url(
        client, unit_title="Plain", stem="<p>Explain plainly.</p>"
    )
    _assert_katex_absent(client.get(url).content.decode())


def test_review_submission_loads_katex_for_a_maths_title(client):
    url = _review_url(client, unit_title=MATHS_TITLE, stem="<p>Explain plainly.</p>")
    _assert_katex_present(client.get(url).content.decode())


def test_review_submission_loads_no_katex_without_maths(client):
    url = _review_url(client, unit_title="Plain", stem="<p>Explain plainly.</p>")
    _assert_katex_absent(client.get(url).content.decode())


def test_the_title_widening_is_applied_at_all_three_unit_render_sites():
    """The ONLY detector for the _quiz_render_feedback site.

    Two of the three sites are covered behaviourally by the tests above; the
    third cannot be -- its fixture necessarily has >=1 question, so
    has_math = bool(questions) is already True and a gate assertion is vacuous.
    Without this, an implementation that widens two of three ships fully green.

    Counts CALLS, not the statement body: the helper's own `def` line and its
    docstring do not match `_widen_has_math_for_titles(ctx, node)`, so this does
    not fall into the regexes-match-docstrings trap. It is a source assertion by
    necessity, not by preference."""
    import ast
    import inspect

    from courses import views

    src = inspect.getsource(views)
    tree = ast.parse(src)
    callers = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        and any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_widen_has_math_for_titles"
            for n in ast.walk(fn)
        )
    }
    assert callers == {
        "full_lesson_render_context",
        "quiz_unit",
        "_quiz_render_feedback",
    }, f"title widening applied at the wrong set of render sites: {sorted(callers)}"


# =============================================================================
# The gate: pages that gain has_math (outline + course results)
# =============================================================================


def test_course_outline_loads_katex_for_a_maths_title(client):
    course, _unit, _n = make_title_course(maths_on="far")
    login_student(client, course)
    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    _assert_katex_present(client.get(url).content.decode())


def test_course_outline_loads_katex_for_a_maths_group_title(client):
    """The outline renders group titles too (_outline_node.html:21), and
    build_outline's tree is what the scan walks -- so a GROUP-only maths title
    must arm the gate."""
    course, _unit, _n = make_title_course(maths_on="group")
    login_student(client, course)
    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    _assert_katex_present(client.get(url).content.decode())


def test_course_outline_loads_no_katex_without_maths(client):
    course, _unit, _n = make_title_course(maths_on="none")
    login_student(client, course)
    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    _assert_katex_absent(client.get(url).content.decode())


def _course_results_url_with_quiz_title(client, title):
    course = CourseFactory()
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        order=0,
        title=title,
    )
    login_student(client, course)
    return reverse("courses:course_results", kwargs={"slug": course.slug})


def test_course_results_loads_katex_for_a_maths_row_title(client):
    url = _course_results_url_with_quiz_title(client, MATHS_TITLE)
    body = client.get(url).content.decode()
    # A quiz with no submission still renders: build_course_results appends a
    # "not_started" row for every quiz unit (build_course_results).
    assert MATHS_TITLE in body, "the results row did not render"
    _assert_katex_present(body)


def test_course_results_loads_no_katex_without_maths(client):
    url = _course_results_url_with_quiz_title(client, "Plain quiz")
    _assert_katex_absent(client.get(url).content.decode())
