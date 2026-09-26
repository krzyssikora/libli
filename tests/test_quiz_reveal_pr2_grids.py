"""Grid-only reveal behaviour (spec 2026-09-25 §2.2 grid radios, §5a nested)."""

import re

import pytest
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import GridRow
from courses.models import UnitProgress
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.reveal_pr2_kit import build
from tests.reveal_pr2_kit import key
from tests.reveal_pr2_kit import paint
from tests.reveal_pr2_kit import parts
from tests.reveal_pr2_kit import post
from tests.reveal_pr2_kit import yours


def _quiz(client):
    user = make_login(client, "gstu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return unit


def _fetch(client, unit, el, data):
    return client.post(
        f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/",
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _page(client, unit):
    return client.get(
        reverse(
            "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    ).content.decode()


@pytest.mark.django_db
def test_key_copy_radios_are_nameless_and_the_students_pick_stays_checked(client):
    # Spec §2.2: a key-copy radio still named row_<pk> would join the student's
    # radio group in the same form and uncheck the student's pick.
    unit = _quiz(client)
    kit = build("choicegrid", max_attempts=1)
    el = add_element(unit, kit.question)
    body = _fetch(client, unit, el, kit.half).content.decode()
    student_radios = re.findall(r"<input[^>]*type=\"radio\"[^>]*>", yours(body))
    checked = [r for r in student_radios if "checked" in r]
    assert len(checked) == 2 and all('name="row_' in r for r in checked)
    key_radios = re.findall(r"<input[^>]*type=\"radio\"[^>]*>", key(body))
    assert key_radios and all("name=" not in r and "disabled" in r for r in key_radios)
    assert sum("checked" in r for r in key_radios) == 2


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["choicegrid", "multigrid"])
def test_grid_row_added_after_answer(client, kind):
    unit = _quiz(client)
    kit = build(kind, max_attempts=1)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    q = kit.question
    if kind == "choicegrid":
        GridRow.objects.create(
            question=q, order=2, statement="Sthree", correct_column=q.columns.first()
        )
    else:
        row = q.rows.create(order=2, statement="Sthree")
        row.correct_columns.set([q.columns.first()])
    page = _page(client, unit)
    assert paint(kind, yours(page)) == ["correct", "incorrect", "incorrect"]
    assert len(parts(kind, key(page))) == 3
    kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    client.post(reverse("courses:quiz_finish", kwargs=kw))
    assert client.get(reverse("courses:quiz_results", kwargs=kw)).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["choicegrid", "multigrid"])
def test_lesson_grid_nested_in_callout_paints_on_nojs_and_restore(client, kind):
    student = make_student(client, f"nest_{kind}")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    callout_row = add_element(unit, CalloutElement.objects.create(kind="example"))
    kit = build(kind)
    nested = Element.objects.create(
        unit=unit,
        content_object=kit.question,
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": nested.pk},
    )
    body = client.post(url, kit.half).content.decode()  # no-JS
    assert paint(kind, yours(body)) == ["correct", "incorrect"]
    page = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert paint(kind, yours(page)) == ["correct", "incorrect"]  # restore
    assert "question__reveal" not in page and "data-answer-key" not in page


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("checked", "sibling"), [("dragfill", "choicegrid"), ("choicegrid", "dragfill")]
)
def test_nojs_lesson_check_leaves_a_sibling_of_another_type_unpainted(
    client, checked, sibling
):
    # The render() feedback_for_pk guard: the no-JS lesson re-render hands ONE
    # page-level mark_result to every question; a grid reading a dnd reveal (or
    # the reverse) would mis-paint or raise.
    student = make_student(client, f"sib_{checked}")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    kit = build(checked)
    el = add_element(unit, kit.question)
    other = build(sibling)
    add_element(unit, other.question)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, kit.half)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert paint(checked, yours(html)).count("incorrect") == 1
    sibling_html = html.split("data-answer-yours")[2]
    assert paint(sibling, sibling_html)[:2] == [None, None]


@pytest.mark.django_db
def test_lesson_restore_of_a_grid_uses_the_stored_answer(client):
    student = make_student(client, "gres")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    kit = build("multigrid")
    el = add_element(unit, kit.question)
    stored = kit.question.build_answer(post(kit.half))
    UnitProgress.objects.update_or_create(
        student=student,
        unit=unit,
        defaults={"element_state": {str(el.pk): {"answer": stored}}},
    )
    page = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert paint("multigrid", yours(page)) == ["correct", "incorrect"]
