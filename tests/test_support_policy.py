"""Audience policy, config caching and throttling."""

import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import STUDENT
from institution.roles import TEACHER
from institution.roles import seed_roles
from support.constants import THROTTLE_MAX_REPORTS
from support.models import IssueReport
from support.models import SupportSettings
from support.policy import AUDIENCE_GROUPS
from support.policy import can_report
from support.policy import role_labels
from support.policy import role_snapshot
from support.policy import throttle_exceeded
from tests.factories import UserFactory
from tests.factories import make_pa
from tests.factories import make_student

pytestmark = pytest.mark.django_db

Audience = SupportSettings.Audience


@pytest.fixture(autouse=True)
def _clear_config_cache():
    cache.clear()
    yield
    cache.clear()


def _user_with_role(role_name, **kwargs):
    seed_roles()
    user = UserFactory(**kwargs)
    user.groups.add(AuthGroup.objects.get(name=role_name))
    return user


def _set_audience(value):
    settings_row = SupportSettings.load()
    settings_row.audience = value
    settings_row.save()


@pytest.mark.parametrize(
    ("audience", "role", "expected"),
    [
        (Audience.ADMINS, PLATFORM_ADMIN, True),
        (Audience.ADMINS, COURSE_ADMIN, False),
        (Audience.ADMINS, TEACHER, False),
        (Audience.ADMINS, STUDENT, False),
        (Audience.COURSE_ADMINS, PLATFORM_ADMIN, True),
        (Audience.COURSE_ADMINS, COURSE_ADMIN, True),
        (Audience.COURSE_ADMINS, TEACHER, False),
        (Audience.COURSE_ADMINS, STUDENT, False),
        (Audience.TEACHERS, PLATFORM_ADMIN, True),
        (Audience.TEACHERS, COURSE_ADMIN, True),
        (Audience.TEACHERS, TEACHER, True),
        (Audience.TEACHERS, STUDENT, False),
        (Audience.ALL, PLATFORM_ADMIN, True),
        (Audience.ALL, COURSE_ADMIN, True),
        (Audience.ALL, TEACHER, True),
        (Audience.ALL, STUDENT, True),
    ],
)
def test_can_report_matrix(audience, role, expected):
    _set_audience(audience)
    assert can_report(_user_with_role(role)) is expected


def test_audience_groups_covers_every_rung():
    """The matrix parametrisation and the runtime lookup share one constant."""
    assert set(AUDIENCE_GROUPS) == {a.value for a in Audience}


def test_platform_admin_can_always_report_even_on_the_narrowest_rung():
    _set_audience(Audience.ADMINS)
    assert can_report(_user_with_role(PLATFORM_ADMIN)) is True


def test_superuser_outside_the_group_can_report():
    """accounts/services.py treats superusers outside the PA group as a separate
    recovery path — and that account is the one most likely to be debugging."""
    _set_audience(Audience.ADMINS)
    assert can_report(UserFactory(is_superuser=True)) is True


def test_the_all_rung_admits_a_user_holding_no_role_group():
    """Evaluated as a group intersection, 'Everyone' would deny a fresh
    createsuperuser account or an SSO account before role assignment."""
    _set_audience(Audience.ALL)
    assert can_report(UserFactory()) is True


def test_inactive_and_anonymous_cannot_report():
    from django.contrib.auth.models import AnonymousUser

    _set_audience(Audience.ALL)
    assert can_report(UserFactory(is_active=False)) is False
    assert can_report(AnonymousUser()) is False


def test_an_extra_reporter_can_report_immediately_after_being_added():
    """Mutant: remove the m2m_changed invalidation receiver."""
    _set_audience(Audience.ADMINS)
    teacher = _user_with_role(TEACHER)
    assert can_report(teacher) is False
    SupportSettings.load().extra_reporters.add(teacher)
    assert can_report(teacher) is True


def test_changing_the_audience_takes_effect_immediately():
    """Mutant: remove the post_save invalidation receiver."""
    _set_audience(Audience.ADMINS)
    student = _user_with_role(STUDENT)
    assert can_report(student) is False
    _set_audience(Audience.ALL)
    assert can_report(student) is True


def test_with_no_settings_row_nothing_explodes_and_students_cannot_report():
    """The M2M must never be read off an unsaved SupportSettings() fallback —
    that raises ValueError, and can_report runs on every authenticated render."""
    assert SupportSettings.objects.count() == 0
    assert can_report(_user_with_role(STUDENT)) is False


def test_a_warm_cache_costs_no_settings_queries_on_a_render(client):
    """Exercises the RENDER path, not can_report() alone: a context processor
    that bypassed get_support_config() would otherwise go unnoticed. The filter
    also catches the through table, whose name contains this substring."""
    _set_audience(Audience.ALL)
    make_student(client)
    client.get(reverse("home"))  # warm the bundle
    with CaptureQueriesContext(connection) as ctx:
        client.get(reverse("home"))
    settings_queries = [
        q for q in ctx.captured_queries if "support_supportsettings" in q["sql"]
    ]
    assert settings_queries == []


def test_an_authenticated_render_issues_one_role_names_query(client):
    """Only statements selecting auth_group.name count: base.html's perms.*
    lookups make the auth backend join auth_group too, so counting every
    auth_group statement would be FALSE on a correct build.

    mark_onboarded() is mandatory. core/views.py:home redirects any holder of
    institution.change_institution into institution:setup while the install is
    not onboarded, and the seeded Institution row starts with onboarded=False —
    so a PA GET of /home/ would be a 302 that renders no template, runs no
    context processors, and counts ZERO role queries, failing on a correct build.
    tests/test_dashboard_panels.py and tests/test_nav_structure.py do the same.
    """
    from core.services import mark_onboarded

    make_pa(client)
    mark_onboarded()
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(reverse("home"))
    assert response.status_code == 200  # not a redirect
    role_queries = [
        q for q in ctx.captured_queries if '"auth_group"."name"' in q["sql"]
    ]
    assert len(role_queries) == 1


def test_throttle_uses_a_rolling_window_not_a_clock_hour():
    student = make_student_reporter()
    _backdate(_make_reports(student, THROTTLE_MAX_REPORTS), minutes=61)
    assert throttle_exceeded(student) is False
    _backdate(_make_reports(student, THROTTLE_MAX_REPORTS), minutes=59)
    assert throttle_exceeded(student) is True


def make_student_reporter():
    _set_audience(Audience.ALL)
    return _user_with_role(STUDENT)


def _make_reports(user, count):
    return [
        IssueReport.objects.create(reporter=user, description=f"r{i}")
        for i in range(count)
    ]


def _backdate(reports, *, minutes):
    """created_at is auto_now_add, which IGNORES any value assigned before save() —
    the rows must be backdated with a queryset update afterwards."""
    when = timezone.now() - timezone.timedelta(minutes=minutes)
    IssueReport.objects.filter(pk__in=[r.pk for r in reports]).update(created_at=when)


def test_role_labels_falls_back_to_the_raw_name():
    assert role_labels("Teacher,Retired Role") == ["Teacher", "Retired Role"]
    assert role_labels("") == []


def test_role_snapshot_is_canonically_ordered():
    """Mutant: join the frozenset directly. ROLE_NAMES order is
    [Student, Teacher, Course Admin, Platform Admin], so a set-iteration join
    would produce either ordering depending on the hash seed — making assertions
    flaky and the comma-boundary truncation drop a different role run to run."""
    assert role_snapshot(frozenset({COURSE_ADMIN, TEACHER})) == "Teacher,Course Admin"


def test_role_snapshot_sorts_non_standard_groups_after_the_known_ones():
    assert (
        role_snapshot(frozenset({"Zebra", TEACHER, "Alpha"})) == "Teacher,Alpha,Zebra"
    )
