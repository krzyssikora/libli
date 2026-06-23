"""UX fixes: roster picker cohort filter + name search, and quiz feedback that
suppresses redundant detail on fully-correct answers and is set apart visually."""

import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from grouping import services
from grouping.models import Group
from institution.roles import TEACHER
from institution.roles import seed_roles
from tests.factories import CohortFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import ShortTextQuestionElement
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


# ── Fix #1: roster picker cohort filter + name search ────────────────────────


def _answer_url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


def test_roster_picker_has_cohort_filter_and_search_controls(client):
    make_pa(client)
    CourseFactory()  # a course must exist for the group form
    resp = client.get(reverse("grouping:group_create"))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "data-roster-cohort" in body, "cohort filter <select> hook missing"
    assert "data-roster-search" in body, "name search <input> hook missing"


def test_roster_student_labels_carry_cohort_and_name_data(client):
    make_pa(client)
    CourseFactory()
    cohort = CohortFactory(name="Year 7")
    student = UserFactory(username="alice7")
    # UserFactory's post_save already gave the student a Default-cohort membership;
    # reassign in place (defaults-on-create won't move them, so use the service).
    services.assign_student_to_cohort(student, cohort)
    resp = client.get(reverse("grouping:group_create"))
    body = resp.content.decode()
    assert f'data-cohort="{cohort.slug}"' in body
    assert 'data-name="alice7"' in body


def test_roster_picker_ignores_cohort_query_param(client):
    """Filtering is client-side now: the server returns ALL students regardless of
    any ?cohort= query, so a checked student outside the filter is never dropped."""
    make_pa(client)
    CourseFactory()
    other_cohort = CohortFactory(name="Year 9")
    student = UserFactory(username="bob")  # in the Default cohort, not Year 9
    url = reverse("grouping:group_create") + f"?cohort={other_cohort.slug}"
    resp = client.get(url)
    picker_ids = {u.pk for u in resp.context["all_students"]}
    assert student.pk in picker_ids


def test_both_pickers_are_searchable_roster_components(client):
    """Students AND teachers each get a searchable roster component (a list wrapped
    with data-roster-list plus its own name-search box)."""
    make_pa(client)
    CourseFactory()
    resp = client.get(reverse("grouping:group_create"))
    body = resp.content.decode()
    assert body.count("data-roster-list") == 2, "students + teachers each need a list"
    assert body.count("data-roster-search") == 2, "each picker needs a name search"


def test_pickers_show_server_rendered_selected_counts(client):
    """On edit, each picker shows how many are already added (server-rendered so it is
    correct with JS off; the script keeps it live thereafter)."""
    seed_roles()
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    group = Group.objects.create(name="7A", course=course)
    s1, s2 = UserFactory(), UserFactory()
    services.add_students_to_group(group, [s1, s2])
    teacher = UserFactory()
    teacher.groups.add(AuthGroup.objects.get(name=TEACHER))
    group.teachers.add(teacher)

    resp = client.get(reverse("grouping:group_edit", args=[group.pk]))
    body = resp.content.decode()
    # Each picker exposes its saved baseline (data-roster-saved) so the script can
    # show "Added: N (saved: M)" once the live selection diverges from it.
    assert 'data-roster-saved="2"' in body, "students saved-count of 2 missing"
    assert 'data-roster-saved="1"' in body, "teachers saved-count of 1 missing"


# ── Fix #2: quiz feedback (correct = terse + set-apart panel) ─────────────────


def _quiz_q(client, *, accepted="Paris", explanation="It's Paris.", max_attempts=1):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?",
        accepted=accepted,
        explanation=explanation,
        max_attempts=max_attempts,
    )
    el = add_element(unit, q)
    return unit, el


def test_correct_answer_hides_reveal_but_keeps_explanation(client):
    unit, el = _quiz_q(client)
    resp = client.post(
        _answer_url(unit, el), {"answer": "Paris"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    body = resp.content.decode()
    assert "Correct" in body
    assert "It's Paris." in body, "author explanation should remain when correct"
    assert "Correct answer:" not in body, "answer reveal is redundant when correct"


def test_correct_feedback_is_wrapped_in_a_panel(client):
    unit, el = _quiz_q(client)
    resp = client.post(
        _answer_url(unit, el), {"answer": "Paris"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    body = resp.content.decode()
    assert "question__feedback-panel" in body
    assert "is-correct" in body


def test_incorrect_feedback_keeps_reveal_in_a_panel(client):
    unit, el = _quiz_q(client, max_attempts=1)
    resp = client.post(
        _answer_url(unit, el), {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    body = resp.content.decode()
    assert "question__feedback-panel" in body
    assert "is-incorrect" in body
    assert "Correct answer:" in body, "reveal still shown when wrong on last attempt"


# ── Fix #2: results page mirrors the live feedback ───────────────────────────


def test_results_correct_question_hides_reveal_keeps_explanation_in_panel(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", explanation="Bravo.", max_attempts=1
    )
    el = add_element(unit, q)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(
        f"{base}/q/{el.pk}/answer/", {"answer": "Paris"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    client.post(f"{base}/finish/")
    body = client.get(f"{base}/results/").content.decode()
    assert "Bravo." in body
    assert "question__feedback-panel" in body
    assert "Correct answer:" not in body, "results should not re-list a correct answer"
