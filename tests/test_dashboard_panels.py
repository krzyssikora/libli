from datetime import timedelta

import pytest
from bs4 import BeautifulSoup
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.services import mark_onboarded
from courses.models import ContentNode
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def _polish(client):
    from core.middleware import LANGUAGE_SESSION_KEY

    session = client.session
    session[LANGUAGE_SESSION_KEY] = "pl"
    session.save()


def _studio(resp):
    soup = BeautifulSoup(resp.content, "html.parser")
    return soup.select_one('section[data-section="manage"]')


def _teaching_setup(client, username, *, archived=False):
    user = make_login(client, username)
    course = CourseFactory(title="Taught Course")
    group = GroupFactory(course=course, archived=archived)
    group.teachers.add(user)
    return user, course


def test_teaching_panel_lists_taught_course_with_links(client):
    _user, course = _teaching_setup(client, "dash_teach")
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="teaching"' in body
    assert "Taught Course" in body
    assert reverse("courses:course_outline", kwargs={"slug": course.slug}) in body
    assert reverse("courses:manage_analytics", kwargs={"slug": course.slug}) in body


def test_teaching_panel_excludes_archived_group_course(client):
    _user, course = _teaching_setup(client, "dash_teach_arch", archived=True)
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    # archived-group course is not listed; no data-section=teaching for this user
    assert "Taught Course" not in body


def test_group_only_teacher_sees_teaching_not_generic_not_browse(client):
    # make_login user is NOT in the Teacher role group (is_teacher flag False),
    # but teaches via Group.teachers -> the widened gate must show Teaching and
    # suppress both the generic empty-state and the student Browse button.
    _user, _course = _teaching_setup(client, "dash_group_only")
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="teaching"' in body
    assert 'data-section="generic"' not in body
    # Assert the DASHBOARD Browse button is suppressed, scoped to its wrapper
    # (`<p class="dash-browse">…Browse courses…</p>`). Do NOT assert
    # `reverse("courses:catalog") not in body`: the nav still renders the
    # students-only Browse link at this point (it is not removed until Task 4),
    # so the whole-body check would false-fail here.
    assert "dash-browse" not in body


def test_role_teacher_with_no_taught_courses_sees_empty_state(client):
    make_teacher(client, "dash_role_teacher")  # Teacher role -> is_teacher True
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="teaching"' in body
    assert "No classes assigned yet." in body


def test_studio_panel_owner_sees_title_list_and_all_courses(client):
    owner = make_login(client, "studio_owner")
    course = CourseFactory(title="My Owned Course", owner=owner)
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="manage"' in body
    assert ">Studio<" in body  # panel title
    assert "My Owned Course" in body
    assert reverse("courses:manage_builder", kwargs={"slug": course.slug}) in body
    assert reverse("courses:manage_course_list") in body  # "All courses"


def test_studio_new_course_hidden_for_owner_without_add_course(client):
    owner = make_login(client, "studio_plain_owner")
    CourseFactory(title="Owned", owner=owner)
    resp = client.get(reverse("home"))
    # can_manage_courses True via ownership, but no add_course perm
    assert reverse("courses:manage_course_create") not in resp.content.decode()


def test_studio_new_course_shown_for_add_course_holder(client):
    from core.services import mark_onboarded

    make_pa(client, "studio_pa")  # PLATFORM_ADMIN holds courses.add_course
    mark_onboarded()  # avoid the first-run wizard redirect
    resp = client.get(reverse("home"))
    assert reverse("courses:manage_course_create") in resp.content.decode()


def test_studio_row_title_goes_to_builder_and_view_to_outline(client):
    owner = make_login(client, "studio_view")
    course = CourseFactory(title="Algebra", owner=owner)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    row = _studio(resp).select_one("li.dash-row")
    title = row.select_one("a.dash-row__title")
    action = row.select_one("a.dash-row__action")
    assert title["href"] == reverse(
        "courses:manage_builder", kwargs={"slug": course.slug}
    )
    assert action["href"] == reverse(
        "courses:course_outline", kwargs={"slug": course.slug}
    )
    assert not action.has_attr("target") and not title.has_attr("target")
    assert len(row.select("a")) == 2
    assert client.get(action["href"]).status_code == 200


def test_studio_view_link_names_the_course_without_math_delimiters(client):
    owner = make_login(client, "studio_math")
    CourseFactory(title=r"Pole \(x^2\)", owner=owner)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    action = _studio(resp).select_one("a.dash-row__action")
    hidden = action.select_one(".visually-hidden").get_text()
    assert "Pole x^2" in hidden and r"\(" not in hidden


def test_studio_view_action_is_not_the_widok_noun_in_polish(client):
    owner = make_login(client, "studio_pl")
    CourseFactory(title="Algebra", owner=owner)
    _polish(client)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    action = _studio(resp).select_one("a.dash-row__action")
    visible = action.find(string=True, recursive=False).strip()
    assert visible and visible != "Widok"


def test_teaching_row_title_carries_dash_row_title(client):
    _user, course = _teaching_setup(client, "teach_title")
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    title = BeautifulSoup(resp.content, "html.parser").select_one(
        'section[data-section="teaching"] li.dash-row a.dash-row__title'
    )
    assert title["href"] == reverse(
        "courses:course_outline", kwargs={"slug": course.slug}
    )


def _card(resp):
    return BeautifulSoup(resp.content, "html.parser").select_one("[data-last-edited]")


def _unit(course, **kw):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson", **kw
    )


def _pin(node, dt):
    ContentNode.objects.filter(pk=node.pk).update(updated=dt)


def _lesson_url(course, node):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": node.pk}
    )


def test_last_edited_shows_latest_updated_owned_unit(client):
    base = timezone.now()
    owner = make_login(client, "le_latest")
    course = CourseFactory(title="Geo", owner=owner)
    older_pk_unit = _unit(course, title="First")  # lower pk
    newer_pk_unit = _unit(course, title="Second")
    _pin(older_pk_unit, base + timedelta(minutes=5))
    _pin(newer_pk_unit, base)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    card = _card(resp)
    links = card.select("a")
    assert len(links) == 1 and not links[0].has_attr("target")
    assert links[0]["href"] == _lesson_url(course, older_pk_unit)
    assert "First" in links[0].get_text() and "Geo" in links[0].get_text()
    assert "Last edited" in card.get_text()
    assert "Last edited" not in links[0].get_text()


def test_last_edited_tie_breaks_on_higher_pk(client):
    base = timezone.now()
    owner = make_login(client, "le_tie")
    course = CourseFactory(title="Tie", owner=owner)
    low = _unit(course, title="Low")
    high = _unit(course, title="High")
    _pin(low, base)
    _pin(high, base)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    link = _card(resp).select_one("a")
    assert high.pk > low.pk
    assert link["href"] == _lesson_url(course, high)
    assert "High" in link.get_text()


def test_last_edited_draft_unit_is_shown_and_opens(client):
    owner = make_login(client, "le_draft")
    course = CourseFactory(title="Draft course", owner=owner)
    unit = _unit(course, title="Hidden draft", published=False)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    href = _card(resp).select_one("a")["href"]
    assert href == _lesson_url(course, unit)
    assert client.get(href).status_code == 200


def test_last_edited_quiz_links_to_quiz_unit(client):
    owner = make_login(client, "le_quiz")
    course = CourseFactory(title="Quiz course", owner=owner)
    unit = make_quiz_unit(course, parent=None, title="The quiz")
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    assert _card(resp).select_one("a")["href"] == reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )


def test_last_edited_strips_math_from_both_titles(client):
    owner = make_login(client, "le_math")
    course = CourseFactory(title=r"Kurs \(y\)", owner=owner)
    _unit(course, title=r"Pole \(x^2\)")
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    text = _card(resp).get_text()
    assert "Pole x^2" in text and "Kurs y" in text
    assert r"\(" not in text


def test_last_edited_skips_containers(client):
    base = timezone.now()
    owner = make_login(client, "le_container")
    course = CourseFactory(title="Cont", owner=owner)
    unit = _unit(course, title="Real unit")
    section = ContentNodeFactory(
        course=course, parent=None, kind="section", unit_type=None, title="Sec"
    )
    _pin(unit, base)
    _pin(section, base + timedelta(minutes=5))
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    assert _card(resp).select_one("a")["href"] == _lesson_url(course, unit)


def test_last_edited_ignores_other_authors_for_platform_admin(client):
    base = timezone.now()
    pa = make_pa(client, "le_pa")
    mark_onboarded()
    own = _unit(CourseFactory(title="PA course", owner=pa), title="Mine")
    other = _unit(CourseFactory(title="Other course"), title="Theirs")
    _pin(own, base)
    _pin(other, base + timedelta(hours=1))
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    text = _card(resp).get_text()
    assert "Mine" in text and "Theirs" not in text


def test_no_card_when_studio_shows_but_nothing_owned(client):
    make_pa(client, "le_none")
    mark_onboarded()
    _unit(CourseFactory(title="Someone else's"))
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert resp.status_code == 200 and 'data-section="manage"' in body
    assert "data-last-edited" not in body and "Last edited" not in body


def test_last_edited_query_skipped_for_students(client):
    make_student(client, "le_student")
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(reverse("home"))
    assert resp.status_code == 200
    assert 'data-section="manage"' not in resp.content.decode()
    assert not any('"updated" DESC' in q["sql"] for q in ctx.captured_queries)
