import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import TabsElement
from courses.models import UnitProgress
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _markdone(prompt="Prep", items=("one", "two")):
    el = MarkDoneElement.objects.create(prompt=prompt)
    made = [MarkDoneItem.objects.create(element=el, content=c) for c in items]
    return el, made


def _lesson_url(course, unit):
    return reverse(
        "courses:lesson_unit",
        kwargs={"slug": course.slug, "node_pk": unit.pk},
    )


def test_enrolled_student_sees_checked_items(client):
    student = make_login(client, "stu")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    el, (i1, i2) = _markdone()
    row = add_element(unit, el)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"items": [i1.pk]}}
    )

    body = client.get(_lesson_url(course, unit)).content.decode()

    assert f'name="element" value="{el.pk}"' in body
    # i1 is checked and its row carries the `on` class.
    assert f'value="{i1.pk}"' in body
    assert "checked" in body
    assert "markdone__item on" in body


def test_non_enrolled_author_sees_own_checked_items(client):
    # A non-enrolled viewer who can access the lesson (the course owner) has their own
    # saved checklist state re-rendered on GET — build_lesson_context reads an existing
    # UnitProgress row without requiring enrollment (and without creating one).
    owner = make_login(client, "own")
    course, unit = make_course_with_unit(owner=owner)
    el, (i1, i2) = _markdone()
    row = add_element(unit, el)
    UnitProgress.objects.create(
        student=owner, unit=unit, element_state={str(row.pk): {"items": [i1.pk]}}
    )

    body = client.get(_lesson_url(course, unit)).content.decode()

    assert f'value="{i1.pk}"' in body
    assert "checked" in body
    assert "markdone__item on" in body


def test_passive_non_enrolled_viewer_gets_no_progress_row(client):
    # A non-enrolled viewer with NO existing row does not get one created on GET.
    owner = make_login(client, "own")
    course, unit = make_course_with_unit(owner=owner)
    el, _ = _markdone()
    add_element(unit, el)

    client.get(_lesson_url(course, unit))

    assert not UnitProgress.objects.filter(student=owner, unit=unit).exists()


def test_nested_in_tabs_checklist_resolves_checked(client):
    # Proves Task 3's container injection reaches a tab-nested checklist: the checked
    # set is resolved from element_state and rendered `checked` + `on`.
    student = make_login(client, "stu")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000001", "label": "One"}]}
    )
    parent = Element.objects.create(unit=unit, content_object=tabs)
    el, (i1, i2) = _markdone()
    row = Element.objects.create(
        unit=unit, content_object=el, parent=parent, tab_id="t000001"
    )
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"items": [i1.pk]}}
    )

    body = client.get(_lesson_url(course, unit)).content.decode()

    assert f'name="element" value="{el.pk}"' in body
    assert "checked" in body
    assert "markdone__item on" in body


def test_drifted_element_state_row_renders_the_lesson_fresh(client):
    # Read-side fail-open at the build_lesson_context level: a hand-written drifted
    # row must render 200, not 500 from inside a template tag.
    from django.urls import reverse

    from courses.models import Enrollment
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import UnitProgress
    from tests.factories import add_element
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    course, unit = make_course_with_unit()
    el = MarkDoneElement.objects.create(prompt="P")
    add_element(unit, el)
    MarkDoneItem.objects.create(element=el, content="a")
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    UnitProgress.objects.create(
        student=student,
        unit=unit,
        element_state={"not-an-int": {"items": [1]}, "999": "not-a-dict"},
    )
    client.force_login(student)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
