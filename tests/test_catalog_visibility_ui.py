"""Phase 3b follow-up: surface a course's self-enrolment status on the manage
surfaces (a badge in the manage course list + clearer visibility-field labels),
so an author can tell at a glance whether a course is open for self-enrolment."""

import pytest
from django.urls import reverse

from courses.forms import CourseForm
from tests.factories import CohortFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_manage_list_marks_open_course_for_all_students(client):
    make_pa(client)
    CourseFactory(title="Open All", visibility="open")  # no cohorts = all students
    content = client.get(reverse("courses:manage_course_list")).content.decode()
    assert "Open All" in content
    assert "all students" in content  # the open-to-everyone scope


def test_manage_list_shows_cohort_scope_for_restricted_open_course(client):
    make_pa(client)
    course = CourseFactory(title="Restricted", visibility="open")
    course.self_enroll_cohorts.add(CohortFactory(name="Year 9"))
    content = client.get(reverse("courses:manage_course_list")).content.decode()
    assert "Year 9" in content


def test_manage_list_marks_assigned_course(client):
    make_pa(client)
    CourseFactory(title="Closed One", visibility="assigned")
    content = client.get(reverse("courses:manage_course_list")).content.decode()
    assert "Assigned" in content


def test_courseform_visibility_has_help_and_self_enrolment_label():
    form = CourseForm()
    assert form.fields["visibility"].help_text  # explains open vs assigned
    labels = dict(form.fields["visibility"].choices)
    # the "open" option must clarify it means self-enrolment, not bare "Open"
    assert "self" in str(labels["open"]).lower()
