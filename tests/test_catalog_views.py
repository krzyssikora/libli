import pytest
from django.urls import reverse

from tests.factories import CohortFactory
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import SubjectFactory
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _open_course_with_unit(**kw):
    course = CourseFactory(visibility="open", **kw)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    return course


def test_catalog_shows_open_course_and_marks_enrolled(client):
    student = make_login(client, "v2")
    open1 = _open_course_with_unit(title="Astro")
    enrolled = _open_course_with_unit(title="Bio")
    EnrollmentFactory(student=student, course=enrolled, source="group")
    resp = client.get(reverse("courses:catalog"))
    assert resp.status_code == 200
    assert open1 in resp.context["courses"]
    assert enrolled.pk in resp.context["enrolled_ids"]


def test_catalog_subject_filter(client):
    make_login(client, "v3")
    math = SubjectFactory(title="Math")
    _open_course_with_unit(title="Algebra", subject=math)
    _open_course_with_unit(title="History")  # no subject
    resp = client.get(reverse("courses:catalog"), {"subject": math.pk})
    titles = [c.title for c in resp.context["courses"]]
    assert titles == ["Algebra"]


def test_catalog_text_search_matches_title(client):
    make_login(client, "v4")
    _open_course_with_unit(title="Photosynthesis")
    _open_course_with_unit(title="Trigonometry")
    resp = client.get(reverse("courses:catalog"), {"q": "synth"})
    titles = [c.title for c in resp.context["courses"]]
    assert titles == ["Photosynthesis"]


def test_catalog_language_filter(client):
    make_login(client, "v5")
    _open_course_with_unit(title="EN course", language="en")
    _open_course_with_unit(title="PL course", language="pl")
    resp = client.get(reverse("courses:catalog"), {"language": "pl"})
    titles = [c.title for c in resp.context["courses"]]
    assert titles == ["PL course"]


def test_catalog_staff_sees_only_empty_set_open_courses(client):
    # make_pa logs in a Platform Admin. The 3a signal removes staff from all cohorts,
    # so a staff user has NO CohortMembership -> cohort_id is None -> only empty-set
    # courses.
    make_pa(client, username="vpa")
    open_all = _open_course_with_unit(title="Open to all")
    restricted = _open_course_with_unit(title="Restricted")
    restricted.self_enroll_cohorts.add(CohortFactory(name="Z"))
    resp = client.get(reverse("courses:catalog"))
    courses = list(resp.context["courses"])
    assert open_all in courses
    assert restricted not in courses
