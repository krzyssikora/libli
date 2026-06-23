import pytest

from courses.forms import CourseForm
from tests.factories import CohortFactory
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db


def test_form_lists_non_archived_cohorts():
    live = CohortFactory(name="Live")
    archived = CohortFactory(name="Old", archived=True)
    form = CourseForm()
    qs = form.fields["self_enroll_cohorts"].queryset
    assert live in qs
    assert archived not in qs


def test_form_keeps_already_selected_archived_cohort():
    # A cohort archived AFTER being selected must stay rendered, else ModelMultiple-
    # ChoiceField treats it as invalid and silently drops it on the next save.
    archived = CohortFactory(name="Stale", archived=True)
    course = CourseFactory()
    course.self_enroll_cohorts.add(archived)
    form = CourseForm(instance=course)
    assert archived in form.fields["self_enroll_cohorts"].queryset


def test_form_saves_selected_cohorts():
    cohort = CohortFactory(name="Year 11")
    course = CourseFactory()
    form = CourseForm(
        data={
            "title": course.title,
            "slug": course.slug,
            "language": "en",
            "visibility": "open",
            "self_enroll_cohorts": [cohort.pk],
        },
        instance=course,
    )
    assert form.is_valid(), form.errors
    form.save()
    assert list(course.self_enroll_cohorts.all()) == [cohort]
