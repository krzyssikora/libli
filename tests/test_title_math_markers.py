"""data-math-title marker coverage (spec §1).

A regex over raw source is NOT acceptable -- per this repo's own experience
regexes match docstrings and comments. Every assertion here is over RENDERED
output: a view response, or render_to_string for the one branch no view reaches.
"""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
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


def _marked_texts(html):
    """Every [data-math-title] element's text, whitespace-normalised."""
    soup = BeautifulSoup(html, "html.parser")
    return [" ".join(el.get_text().split()) for el in soup.select("[data-math-title]")]


def _marked(html, selector):
    """Elements matching `selector` that carry the marker attribute.

    Attribute presence ONLY -- deliberately not a text check, because several
    fixtures below mark maths-free titles on purpose (the analytics leaf headers
    under maths_on="group" are the clearest case). The "visible text keeps its
    delimiters" property is pinned separately, by
    test_the_visible_title_keeps_its_raw_delimiters.
    """
    return BeautifulSoup(html, "html.parser").select(f"{selector}[data-math-title]")


# --- math.js's selector -------------------------------------------------------
def test_math_js_selector_includes_the_marker():
    """Anchored to the querySelectorAll ARGUMENT, not to the file.

    A bare `"[data-math-title]" in src` is satisfied by the COMMENT this same
    task writes above renderInlineText ("Inline \\(...\\) math typed into ... a
    node TITLE ([data-math-title], ...)"), so dropping the entry from the actual
    selector would leave it green -- the single most load-bearing line of the
    feature, undetected until the Task 11 e2e six tasks later. This file's own
    docstring says regexes match comments; that cuts both ways."""
    import re
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "courses/static/courses/js/math.js"
    ).read_text(encoding="utf-8")
    assert re.search(
        r'querySelectorAll\(\s*"[^"]*\[data-math-title\][^"]*"\s*\)', src
    ), "[data-math-title] is not in renderInlineText's querySelectorAll argument"


# --- the lesson page: heading, nav buttons, tree (x2), crumb ------------------
def _lesson_body(client, *, maths_on="far", node="unitA"):
    course, unit, nodes = make_title_course(maths_on=maths_on)
    login_student(client, course)
    url = reverse(
        "courses:lesson_unit",
        kwargs={"slug": course.slug, "node_pk": nodes[node].pk},
    )
    return client.get(url).content.decode()


def test_lesson_heading_is_marked(client):
    assert _marked(_lesson_body(client, maths_on="unitA"), "h1.lesson-unit__title")


def test_nav_button_titles_are_marked(client):
    """View unitB, NOT unitA: unitA is the first unit in the course, so
    unit_nav.prev is None and _unit_footer.html:17-21 renders the DISABLED branch
    with no .unit-foot__navtitle at all. Only the `next` span would exist, and the
    prev marker at :14 could be dropped with this test still green.

    unitB has both a prev and a next, so the count assertion pins both sites."""
    body = _lesson_body(client, maths_on="unitB", node="unitB")
    assert len(_marked(body, "span.unit-foot__navtitle")) == 2


def test_tree_unit_labels_are_marked(client):
    assert _marked(_lesson_body(client), "span.unit-tree__label")


def test_tree_group_titles_are_marked(client):
    assert _marked(_lesson_body(client), "span.unit-tree__grouptitle")


def test_breadcrumb_labels_are_marked(client):
    body = _lesson_body(client)
    labels = _marked(body, "span.unit-crumbs__label")
    assert labels
    # The course crumb is an <a class="unit-crumbs__label"> and is OUT OF SCOPE
    # (Course.title is a different field on a different model).
    assert not _marked(body, "a.unit-crumbs__label")


def test_the_childless_container_branch_is_marked():
    """_unit_tree_node.html:60 is unreachable through any view: build_outline
    prunes every zero-child container under BOTH "hide" and "keep", pinned by
    test_unit_nav_render.py::test_a_genuinely_empty_group_is_pruned_not_rendered.
    Covered by a bare render only."""

    class _N:
        pk = 1
        kind = "chapter"
        title = MATHS_TITLE

    class _C:
        language = "pl"
        slug = "c"

    html = render_to_string(
        "courses/_unit_tree_node.html",
        {
            "item": {"node": _N(), "is_unit": False, "children": []},
            "course": _C(),
            "current_pk": None,
        },
    )
    assert _marked(html, "span.unit-tree__grouptitle")


def test_the_visible_title_keeps_its_raw_delimiters(client):
    """THE OVER-APPLICATION GUARD, and the only test that catches it.

    The most natural way to get this feature wrong is to pipe the VISIBLE
    interpolation through |strip_math_delimiters as well as the title=
    attribute. That silently disables typesetting on every marked surface while
    leaving the attribute in place -- so every other marker test here, which
    asserts attribute presence only, stays green. KaTeX needs the delimiters in
    the TEXT; the filter belongs on the attribute alone.

    Checks the four sites where the same title is interpolated twice in one tag
    (visible text + title= tooltip), which is exactly where the mistake is made.
    """
    body = _lesson_body(client, maths_on="unitA", node="unitA")
    soup = BeautifulSoup(body, "html.parser")

    for selector in ("span.unit-tree__label", "h1.lesson-unit__title"):
        els = soup.select(f"{selector}[data-math-title]")
        assert els, f"no marked {selector} rendered"
        assert any("\\(" in el.get_text() for el in els), (
            f"{selector}: the VISIBLE title lost its delimiters -- "
            "strip_math_delimiters was applied to the text, not just title="
        )

    # ...and the tooltip on the same element IS stripped. Both halves together
    # are what distinguish "correctly wired" from "filter applied everywhere".
    labels = soup.select("span.unit-tree__label[title]")
    assert labels
    assert all("\\(" not in el["title"] for el in labels)


# --- the quiz page ------------------------------------------------------------
def test_quiz_heading_is_marked(client):
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
    assert _marked(client.get(url).content.decode(), "h1.lesson-unit__title")


# --- the outline page ---------------------------------------------------------
def test_outline_unit_and_group_titles_are_marked(client):
    course, _unit, _nodes = make_title_course(maths_on="far")
    login_student(client, course)
    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    assert _marked(body, "span.outline-unit__title")
    assert _marked(body, "span.outline-node__title")


# --- quiz results: the TITLE-ALONE rule --------------------------------------
def test_quiz_results_heading_marks_the_title_alone(client):
    """`{{ unit.title }} — {% trans "results" %}`: marking the shared <h1> would
    typeset the translated word too."""
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        order=0,
        title=MATHS_TITLE,
    )
    student = login_student(client, course)
    QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    url = reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    body = client.get(url).content.decode()
    assert MATHS_TITLE in _marked_texts(body)
    assert not _marked(body, "h1.result__title")


# --- course results -----------------------------------------------------------
def test_course_results_row_titles_are_marked(client):
    course = CourseFactory()
    _quiz = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        order=0,
        title=MATHS_TITLE,
    )
    login_student(client, course)
    url = reverse("courses:course_results", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    # Precondition, stated rather than assumed: build_course_results appends a
    # "not_started" row for EVERY quiz unit (build_course_results), so a quiz with
    # no submission still renders. Without this the positive assertion below
    # could fail for fixture reasons and read as a wiring bug.
    assert MATHS_TITLE in body, "the results row did not render"
    assert _marked(body, "span.result-row__title")


# --- analytics ----------------------------------------------------------------
def _analytics_bodies(client, *, maths_on):
    """(matrix_body, breakdown_body) for a course seeded by make_title_course,
    viewed by the course owner. `expand` opens part2 so its GROUP header renders.

    Adds a QUIZ unit: make_title_course creates only unit_type="lesson", so
    _breakdown_node.html's `{% if item.node.unit_type == "quiz" %}` branch
    (:4-21, holding the :6 marker) would never render and the :24 lesson branch
    -- same class -- would satisfy the assertion on its own."""
    pa = make_pa(client)
    course, _unit, nodes = make_title_course(maths_on=maths_on)
    course.owner = pa
    course.save(update_fields=["owner"])
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=nodes["part2"],
        order=1,
        title=MATHS_TITLE if maths_on == "far" else "Quiz zwykly",
    )
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    matrix_url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    matrix = client.get(f"{matrix_url}?expand={nodes['part2'].pk}").content.decode()
    breakdown_url = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    breakdown = client.get(breakdown_url).content.decode()
    return matrix, breakdown


def test_analytics_matrix_group_header_is_marked(client):
    matrix, _b = _analytics_bodies(client, maths_on="group")
    assert _marked(matrix, "span.analytics__group-title")


def test_analytics_matrix_leaf_headers_are_marked(client):
    """BOTH leaf branches, with selectors that cannot be satisfied by the group
    cell. analytics_matrix.html:110 keeps `analytics__colhead` on the group <th>
    and only ADDS `analytics__group`, so a bare `th.analytics__colhead span`
    selector matches the group-title span the test above already asserted --
    leaving the expandable <a> (:114) and the non-expandable <span> (:115)
    unmarked with the suite still green.

    The `?expand=` fixture produces both: part2 is expanded (so its own children
    are leaves) while part1 is an unexpanded, child-bearing leaf -> expandable."""
    matrix, _b = _analytics_bodies(client, maths_on="group")
    leaf_th = "th.analytics__colhead:not(.analytics__group)"
    expandable = _marked(matrix, f"{leaf_th} a.analytics__expand")
    plain = _marked(matrix, f"{leaf_th} span")
    assert expandable, "expandable leaf header <a> is unmarked"
    assert plain, "non-expandable leaf header <span> is unmarked"


def test_analytics_breakdown_titles_are_marked(client):
    """BOTH unit branches plus the group branch, selected DISTINCTLY.

    The quiz branch (:6) and the lesson branch (:24) share the class
    `breakdown-unit__title`, so neither a truthiness check nor a `>= 2` count
    pins them: the fixture has THREE lesson units and one quiz, so dropping the
    quiz marker still leaves three marked spans and `3 >= 2` passes. What
    separates them structurally is the pill -- the quiz branch always emits one
    (`{% with p=item.pill %}`), the lesson branch never does."""
    _m, breakdown = _analytics_bodies(client, maths_on="far")
    quiz = _marked(
        breakdown, "div.breakdown-unit:has(.pill) > span.breakdown-unit__title"
    )
    lesson = _marked(
        breakdown,
        "div.breakdown-unit:not(:has(.pill)) > span.breakdown-unit__title",
    )
    assert quiz, "the quiz unit branch (_breakdown_node.html:6) is unmarked"
    assert lesson, "the lesson unit branch (:24) is unmarked"
    assert _marked(breakdown, "span.breakdown-node__title")


# --- review queue + review submission: the TITLE-ALONE rule ------------------
def _review_setup(client, unit_title):
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
        stem="<p>Explain plainly.</p>",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    Element.objects.create(unit=unit, content_object=q)
    # display_name MUST be set explicitly: UserFactory defaults it to
    # factory.Faker("name") (tests/factories.py:63), and review_queue.html:15
    # renders `display_name|default:username` -- so a test asserting on "anna"
    # while the factory renders a random Faker name CANNOT FAIL under any
    # implementation, including the mutant it exists to catch.
    student = UserFactory(username="anna", display_name="Anna Nowak")
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=unit,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    # A SECOND submission, IN_PROGRESS, so review_queue.html:30 renders at all.
    # A SUBMITTED row lands in data["awaiting"] (courses/review.py:248-255) and
    # only exercises the :15 branch; :30 is inside {% if in_progress %}, which
    # stays empty without this -- the same duplicated-branch gap the analytics
    # leaf-header test closes with :not(.analytics__group).
    other = UserFactory(username="bogdan", display_name="Bogdan Lis")
    EnrollmentFactory(student=other, course=course)
    QuizSubmission.objects.create(
        student=other,
        unit=unit,
        status=QuizSubmission.Status.IN_PROGRESS,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    return course, sub


def test_review_queue_marks_the_title_alone_not_the_student_name(client):
    course, _sub = _review_setup(client, MATHS_TITLE)
    url = reverse("courses:manage_review_queue", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    assert "Anna Nowak" in body, "the student name did not render at all"
    assert "Bogdan Lis" in body, "the in-progress row did not render"
    marked = _marked_texts(body)
    # BOTH branches -- the awaiting row (:15) and the in-progress row (:30) --
    # carry the title, and neither carries a student name.
    assert marked.count(MATHS_TITLE) == 2
    assert all("Anna Nowak" not in t and "Bogdan Lis" not in t for t in marked)


def test_review_submission_marks_the_title_alone(client):
    course, sub = _review_setup(client, MATHS_TITLE)
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )
    body = client.get(url).content.decode()
    marked = _marked_texts(body)
    assert MATHS_TITLE in marked
    assert not _marked(body, "h1.review-topbar__title")


# --- editor + preview ---------------------------------------------------------
# A title DISTINCT from MATHS_TITLE, so the crumb assertion cannot be satisfied
# by the <h1>: _editor_body gives the unit MATHS_TITLE, and editor.html:80 marks
# that h1 -- so asserting `MATHS_TITLE in _marked_texts(body)` would stay green
# with the per-ancestor crumb marker never added at all, which is precisely the
# "wired at some sites, not others" gap these tests exist to close.
MATHS_PART_TITLE = r"Czesc \(a_1\)"


def _editor_body(client, title=MATHS_TITLE):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    part = ContentNodeFactory(
        course=course,
        kind="part",
        parent=None,
        unit_type=None,
        order=0,
        title=MATHS_PART_TITLE,
    )
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=0,
        title=title,
    )
    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    return client.get(url).content.decode()


def test_editor_heading_and_preview_heading_are_marked(client):
    body = _editor_body(client)
    assert _marked(body, "h1.editor-head__title")
    assert _marked(body, "h2.prev-unit-title")


def test_editor_crumb_marks_each_ancestor_title_not_the_path(client):
    """.editor-crumb__path also holds course.title, which is out of scope.

    Asserts on MATHS_PART_TITLE, not MATHS_TITLE: only the ancestor's own title
    pins the :75 site independently of the :80 heading."""
    body = _editor_body(client)
    assert MATHS_PART_TITLE in body, "the ancestor crumb did not render"
    assert MATHS_PART_TITLE in _marked_texts(body)
    assert not _marked(body, "span.editor-crumb__path")


# --- notes + tags: three marked sites that nothing else pins ------------------
# Without these, dropping data-math-title from all three leaves Tasks 5 AND 9
# fully green -- Task 9 asserts only on KaTeX assets and on the title being
# present, neither of which sees the attribute.


def test_course_notes_unit_heading_is_marked(client):
    from notes.models import Note

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        order=0,
        title=MATHS_TITLE,
    )
    student = login_student(client, course)
    Note.objects.create(author=student, unit=unit, body="a note")
    body = client.get(
        reverse("notes:course_notes", kwargs={"slug": course.slug})
    ).content.decode()
    assert _marked(body, "h2.course-notes__unit-title")


def _tagged(client, title):
    from tags import services as tag_services

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        order=0,
        title=title,
    )
    student = login_student(client, course)
    tag_services.tag_unit(student, unit, "algebra")
    return course, unit


def test_tags_hub_unit_link_is_marked(client):
    _tagged(client, MATHS_TITLE)
    body = client.get(reverse("tags:my_tags")).content.decode()
    assert _marked(body, "div.tag-section__units li a")


def test_tags_panel_heading_marks_the_title_alone(client):
    """panel_page.html:5 is `<h1>{{ unit.title }} — {% trans "Tags" %}</h1>` --
    structurally identical to quiz_results.html:12, so the marker goes on an
    inner span and NOT on the shared <h1>. Reachable only via the invalid-tag
    no-JS POST (422)."""
    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        order=0,
        title=MATHS_TITLE,
    )
    login_student(client, course)
    resp = client.post(
        reverse("tags:tag_add", kwargs={"slug": course.slug, "node_pk": unit.pk}),
        {"name": ""},
    )
    assert resp.status_code == 422
    body = resp.content.decode()
    assert MATHS_TITLE in _marked_texts(body)
    assert not _marked(body, "h1")


# --- the exclusions -----------------------------------------------------------
def test_the_editor_settings_title_input_is_neither_marked_nor_filtered(client):
    """Path C, the edit buffer: typesetting or stripping it corrupts what is saved.
    _unit_settings.html:12 is `<input type="text" name="title" value="{{ unit.title }}"
    required>`, and it is the only input[name="title"] on the editor page."""
    body = _editor_body(client)
    soup = BeautifulSoup(body, "html.parser")
    field = soup.select_one('input[name="title"]')
    assert field is not None
    assert field.get("value") == MATHS_TITLE
    assert "data-math-title" not in field.attrs


def test_the_rename_result_payload_is_neither_marked_nor_filtered(client):
    """<data value=> read by JS -- a fragment endpoint, so drive the rename POST.

    THE FRAGMENT PATH IS NARROW (views_manage.py:816-881): node_rename returns
    _rename_result.html only when _wants_fragment(request) is true AND the POST
    carries neither `has_settings` (which re-renders the unit panel) nor
    ctx="editor" (which redirects to the editor page). So: the fetch header, and
    `node` / `title` / `token` only."""
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        order=0,
        title="Before",
    )
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": course.slug}),
        {
            "node": unit.pk,
            "title": MATHS_TITLE,
            "token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200, resp.content.decode()[:400]
    payload = BeautifulSoup(resp.content.decode(), "html.parser").select_one(
        "data[value]"
    )
    assert payload is not None, "the rename fragment did not render _rename_result.html"
    assert payload["value"] == MATHS_TITLE
    assert "data-math-title" not in payload.attrs


def test_the_builder_rename_input_is_neither_marked_nor_filtered(client):
    """The THIRD Path-C edit buffer, and the only one not otherwise pinned.

    `_tree_node.html:49` is `<input class="tree__title" type="text" name="title"
    value="{{ node.title }}">`. The plan's own note stresses that :49 (permanent
    edit buffer) and :50 (deferred builder tooltip) are different kinds of site
    in the same tag -- exactly the confusion a later builder task could resolve
    wrongly with nothing red. Rendered via the builder page.
    """
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        order=0,
        title=MATHS_TITLE,
    )
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    field = BeautifulSoup(body, "html.parser").select_one("input.tree__title")
    assert field is not None, "the builder rename input did not render"
    assert field.get("value") == MATHS_TITLE  # unfiltered
    assert "data-math-title" not in field.attrs  # unmarked
