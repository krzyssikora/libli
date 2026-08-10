"""strip_math_delimiters: the plain-text half of LaTeX-in-titles (spec §4).

Unit tests here; the eleven per-(file, line) wiring assertions live in Task 2
of the same file.
"""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy

from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from courses.templatetags.courses_extras import strip_math_delimiters
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_pa
from tests.helpers_title_math import MATHS_TITLE
from tests.helpers_title_math import MATHS_TITLE_STRIPPED
from tests.helpers_title_math import login_student
from tests.helpers_title_math import make_title_course

pytestmark = pytest.mark.django_db


def test_strips_an_inline_pair():
    assert strip_math_delimiters(r"\(x^2\)") == "x^2"


def test_strips_a_display_pair():
    assert strip_math_delimiters(r"\[a\]") == "a"


def test_strips_both_kinds_in_one_title():
    assert strip_math_delimiters(r"Solve \(x\) then \[y\]") == "Solve x then y"


def test_a_title_with_no_delimiters_keeps_its_content():
    assert strip_math_delimiters("Rozwiaz rownanie") == "Rozwiaz rownanie"


def test_an_unmatched_opener_is_removed_too():
    # Naive left-to-right replacement, REGARDLESS of pairing (spec §4).
    assert strip_math_delimiters(r"\(x") == "x"


def test_a_stray_closer_is_removed_too():
    assert strip_math_delimiters(r"x\)") == "x"


def test_none_renders_as_the_string_none():
    # Matches Django's own default rendering of None in a template. A filter
    # that raised would take down the whole page render (spec §Error handling).
    assert strip_math_delimiters(None) == "None"


def test_a_lazy_proxy_resolves_to_its_text():
    assert strip_math_delimiters(gettext_lazy("Review")) == "Review"


def test_an_int_renders_as_its_digits():
    assert strip_math_delimiters(7) == "7"


def test_returns_a_plain_str_not_safestring_when_delimiters_present():
    out = strip_math_delimiters(mark_safe(r"\(x\)"))
    assert type(out) is str


def test_the_strip_openers_agree_with_the_detector():
    """THE FORK GUARD. _MATH_DELIMS is a deliberate, minimal fork: the filter needs
    the two CLOSERS, which has_math_delimiters does not expose, so it cannot simply
    delegate the way titles_have_math does.

    What must never drift is the OPENERS. If a third opener is ever added to
    has_math_delimiters, every gate would arm for it while the filter left the raw
    delimiter sitting in a title= attribute and in <title> -- and nothing else in
    this suite would go red. Task 3 pins the detection side; this pins the strip
    side.
    """
    from courses.htmlsandbox import has_math_delimiters
    from courses.templatetags.courses_extras import _MATH_DELIMS

    openers = [d for d in _MATH_DELIMS if has_math_delimiters(d)]
    assert openers, "no _MATH_DELIMS entry is recognised by has_math_delimiters"
    # Anything the detector recognises, the filter must remove -- so a title made
    # of every opener strips to nothing the detector would still flag.
    assert not has_math_delimiters(strip_math_delimiters("".join(_MATH_DELIMS)))


def test_returns_a_plain_str_not_safestring_on_the_no_delimiter_path():
    """The tempting optimisation -- return the input untouched when it holds no
    delimiter -- would pass a SafeString straight through and silently lose
    autoescaping in a title= attribute. SafeString.__str__ returns self, so even
    a str() coercion does not strip the safe marker."""
    out = strip_math_delimiters(mark_safe("Plain title"))
    assert out == "Plain title"
    assert type(out) is str


def _lesson_body(client, *, maths_on):
    course, unit, nodes = make_title_course(maths_on=maths_on)
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    return client.get(url).content.decode(), course, unit, nodes


def _attr_values(html, selector, attr):
    return [
        el.get(attr, "") for el in BeautifulSoup(html, "html.parser").select(selector)
    ]


# --- (1) _unit_tree_node.html:15 -- the tree UNIT label tooltip ---------------
def test_tree_unit_label_tooltip_is_stripped(client):
    body, *_ = _lesson_body(client, maths_on="far")
    titles = _attr_values(body, "span.unit-tree__label", "title")
    assert MATHS_TITLE_STRIPPED in titles
    assert all("\\(" not in t for t in titles)


# --- (2) _unit_tree_node.html:25 -- the tree GROUP title tooltip --------------
def test_tree_group_title_tooltip_is_stripped(client):
    body, *_ = _lesson_body(client, maths_on="group")
    titles = _attr_values(body, "span.unit-tree__grouptitle", "title")
    assert MATHS_TITLE_STRIPPED in titles
    assert all("\\(" not in t for t in titles)


# --- (3) _unit_crumbs.html:34 -- the ancestor crumb <li title=> ---------------
def test_crumb_li_tooltip_is_stripped(client):
    course, unit, nodes = make_title_course(maths_on="none")
    nodes["part1"].title = MATHS_TITLE
    nodes["part1"].save(update_fields=["title"])
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    body = client.get(url).content.decode()
    titles = _attr_values(body, "li.unit-crumbs__item", "title")
    assert MATHS_TITLE_STRIPPED in titles
    assert all("\\(" not in t for t in titles)


# --- (4)+(5) _unit_crumbs.html:27 and :29 -- the collapsed crumb --------------
def _deep_course_with_maths_in_hidden_path():
    """>1 ancestor so the ellipsis crumb renders (it is gated on ancestor COUNT),
    with the maths title on an ancestor that hidden_path ACTUALLY CONTAINS.

    THE TRAP: `build_unit_nav` sets `hidden_path` to
    `HIDDEN_PATH_SEP.join(a.title for a in ancestors[:-1])` -- ALL BUT THE
    DEEPEST -- and `ancestors` comes from `_current_ancestors`, which already
    excludes the unit itself.
    For part1 -> chapter -> deep, `ancestors == [part1, chapter]` and
    `ancestors[:-1] == [part1]`. So the maths must go on **part1**; putting it on
    the chapter leaves hidden_path maths-free and both tests below fail no matter
    how correctly the filter is wired.
    """
    course, _unit, nodes = make_title_course(maths_on="none")
    part1 = nodes["part1"]
    part1.title = MATHS_TITLE  # ancestors[:-1] == [part1]
    part1.save(update_fields=["title"])
    chapter = ContentNodeFactory(
        course=course,
        kind="chapter",
        parent=part1,
        unit_type=None,
        order=0,
        title="Rozdzial zwykly",  # the DEEPEST ancestor: dropped by [:-1]
    )
    deep = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        order=0,
        obligatory=True,
        title="Lekcja gleboka",
    )
    return course, deep


def test_collapsed_crumb_tooltip_is_stripped(client):
    course, deep = _deep_course_with_maths_in_hidden_path()
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": deep.pk}
    )
    body = client.get(url).content.decode()
    titles = _attr_values(body, "li.unit-crumbs__item--ellipsis", "title")
    assert titles, "the collapsed crumb did not render"
    assert all("\\(" not in t for t in titles)
    assert any(MATHS_TITLE_STRIPPED in t for t in titles)


def test_collapsed_crumb_accessible_name_is_stripped(client):
    """The .visually-hidden span IS the collapsed crumb's accessible name. Without
    stripping, a maths ancestor is read aloud as "backslash paren x caret 2" on an
    otherwise fully typeset page."""
    course, deep = _deep_course_with_maths_in_hidden_path()
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": deep.pk}
    )
    body = client.get(url).content.decode()
    soup = BeautifulSoup(body, "html.parser")
    sr = soup.select("li.unit-crumbs__item--ellipsis span.visually-hidden")
    assert sr, "the collapsed crumb's SR-only name did not render"
    texts = [s.get_text() for s in sr]
    assert all("\\(" not in t for t in texts)
    assert any(MATHS_TITLE_STRIPPED in t for t in texts)


# --- (6) _unit_footer.html:37 -- the part-progress chip tooltip ---------------
def test_part_progress_chip_tooltip_is_stripped(client):
    course, _unit, nodes = make_title_course(maths_on="none")
    nodes["part1"].title = MATHS_TITLE
    nodes["part1"].save(update_fields=["title"])
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit",
        kwargs={"slug": course.slug, "node_pk": nodes["unitA"].pk},
    )
    body = client.get(url).content.decode()
    titles = _attr_values(body, "span.unit-foot__part", "title")
    assert titles, "the part chip did not render"
    assert all("\\(" not in t for t in titles)
    assert any(MATHS_TITLE_STRIPPED in t for t in titles)


# --- (7)-(11) the five <title> elements ---------------------------------------
def _head_title(html):
    return BeautifulSoup(html, "html.parser").select_one("title").get_text()


def test_lesson_unit_browser_tab_is_stripped(client):
    body, _c, _u, _n = _lesson_body(client, maths_on="unitA")
    assert "\\(" not in _head_title(body)
    assert MATHS_TITLE_STRIPPED in _head_title(body)


def test_quiz_unit_browser_tab_is_stripped(client):
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
    body = client.get(url).content.decode()
    assert "\\(" not in _head_title(body)
    assert MATHS_TITLE_STRIPPED in _head_title(body)


def _submitted_quiz(client, title):
    """A SUBMITTED quiz whose unit title is `title`, and its logged-in student."""
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        order=0,
        title=title,
    )
    student = login_student(client, course)
    QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    return course, quiz


def test_quiz_results_browser_tab_is_stripped(client):
    course, quiz = _submitted_quiz(client, MATHS_TITLE)
    url = reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    body = client.get(url).content.decode()
    assert "\\(" not in _head_title(body)
    assert MATHS_TITLE_STRIPPED in _head_title(body)


def test_editor_browser_tab_is_stripped(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        order=0,
        title=MATHS_TITLE,
    )
    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    body = client.get(url).content.decode()
    assert "\\(" not in _head_title(body)
    assert MATHS_TITLE_STRIPPED in _head_title(body)


def _review_url_with_unit_title(client, title):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        order=0,
        title=title,
    )
    q = ExtendedResponseQuestionElement.objects.create(
        stem="<p>Explain plainly.</p>",
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


def test_review_submission_browser_tab_is_stripped(client):
    url = _review_url_with_unit_title(client, MATHS_TITLE)
    body = client.get(url).content.decode()
    assert "\\(" not in _head_title(body)
    assert MATHS_TITLE_STRIPPED in _head_title(body)
