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


def test_catalog_detail_full_page_for_eligible(client):
    make_login(client, "d1")
    course = _open_course_with_unit(title="Detail Me")
    resp = client.get(reverse("courses:catalog_detail", args=[course.slug]))
    assert resp.status_code == 200
    assert b"Detail Me" in resp.content
    # not-enrolled -> Enroll form present
    assert reverse("courses:self_enroll", args=[course.slug]).encode() in resp.content


def test_catalog_detail_fragment_via_xhr(client):
    make_login(client, "d2")
    course = _open_course_with_unit()
    resp = client.get(
        reverse("courses:catalog_detail", args=[course.slug]),
        HTTP_X_REQUESTED_WITH="fetch",  # matches the _wants_fragment helper
    )
    assert resp.status_code == 200
    assert b"catalog-detail" in resp.content  # the fragment's root element class
    assert b"<html" not in resp.content  # bare fragment, NOT wrapped in the base layout


def test_catalog_detail_404_for_ineligible(client):
    make_login(client, "d3")
    course = CourseFactory(visibility="assigned")
    ContentNodeFactory(course=course, kind="unit")
    resp = client.get(reverse("courses:catalog_detail", args=[course.slug]))
    assert resp.status_code == 404


def test_catalog_detail_enrolled_but_ineligible_shows_outline_not_enroll(client):
    # Highest-risk branch: enrolled, but course no longer eligible (flipped to
    # assigned). Body must branch on is_enrolled, not the gate -> show outline link,
    # NO enroll form.
    student = make_login(client, "d4")
    course = _open_course_with_unit()
    EnrollmentFactory(student=student, course=course, source="self")
    course.visibility = "assigned"
    course.save(update_fields=["visibility"])
    resp = client.get(reverse("courses:catalog_detail", args=[course.slug]))
    assert resp.status_code == 200
    assert (
        reverse("courses:course_outline", args=[course.slug]).encode() in resp.content
    )
    assert b"Open course" in resp.content  # positive: enrolled branch rendered
    assert (
        reverse("courses:self_enroll", args=[course.slug]).encode() not in resp.content
    )
