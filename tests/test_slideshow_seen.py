import json

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from courses.models import SlideBreakElement
from courses.models import UnitProgress
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_student
from tests.factories import seed_slideshow_unit


@pytest.mark.django_db
def test_completion_ignores_break_and_unions(client):
    course = CourseFactory()
    student = make_student(client)  # logs the client in
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "lesson", layout=["t", "brk", "t", "t"])
    content_pks = list(
        unit.elements.exclude(
            content_type=ContentType.objects.get_for_model(SlideBreakElement)
        ).values_list("pk", flat=True)
    )
    url = reverse("courses:seen", kwargs={"slug": course.slug, "node_pk": unit.pk})
    # Two disjoint partial POSTs; union must be retained and completion reached.
    half = len(content_pks) // 2
    client.post(url, json.dumps(content_pks[:half]), content_type="application/json")
    r = client.post(
        url, json.dumps(content_pks[half:]), content_type="application/json"
    )
    assert r.json()["completed"] is True
    prog = UnitProgress.objects.get(student=student, unit=unit)
    assert set(prog.seen_element_ids) == set(content_pks)  # union, not replace
