import re

import pytest
from django.urls import reverse
from django.utils import timezone

from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db

AUTHED_PAGE = "courses:my_courses"


def _get_html(client):
    return client.get(reverse(AUTHED_PAGE)).content.decode()


def test_bell_trigger_is_a_link_without_role_button(client):
    make_login(client, "owner")
    html = _get_html(client)
    m = re.search(r"<a[^>]*bell__trigger[^>]*>", html)
    assert m, "bell trigger anchor not found"
    tag = m.group(0)
    assert reverse("notifications:list") in tag  # no-JS fallback href
    assert "data-menu-trigger" in tag
    assert 'aria-haspopup="true"' in tag
    assert "role=" not in tag  # stays a link, not role=button


def test_old_notifications_nav_link_removed(client):
    make_login(client, "owner")
    html = _get_html(client)
    # The old link used the app-nav__link class pointing at the list; it's gone.
    assert 'app-nav__link" href="{}"'.format(reverse("notifications:list")) not in html


def test_badge_shows_exact_count_when_small(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(user, course)
    services.notify_enrolled(user, course)
    assert '<span class="nav-badge">2</span>' in _get_html(client)


def test_badge_caps_at_99_plus(client):
    user = make_login(client, "owner")
    Notification.objects.bulk_create(
        Notification(
            recipient=user,
            kind=Notification.Kind.ENROLLED,
            target_type="course",
            target_id=1,
            data={},
        )
        for _ in range(100)
    )
    assert "99+" in _get_html(client)


def test_panel_renders_kind_message_and_unread_row(client):
    user = make_login(client, "owner")
    course = CourseFactory(title="Astronomy")
    services.notify_enrolled(user, course)
    html = _get_html(client)
    assert "You were enrolled in Astronomy" in html
    assert "notif-menu__row--unread" in html


def test_unread_resolvable_row_carries_mark_read_attr(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(user, course)
    n = Notification.objects.filter(recipient=user).first()
    html = _get_html(client)
    assert (
        'data-mark-read-url="{}"'.format(
            reverse("notifications:mark_read", args=[n.pk])
        )
        in html
    )


def test_read_row_omits_mark_read_attr_but_stays_row(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(user, course)
    Notification.objects.filter(recipient=user).update(read_at=timezone.now())
    html = _get_html(client)
    assert "notif-menu__row" in html
    assert "data-mark-read-url" not in html


def test_urlless_row_is_non_link_row(client):
    user = make_login(client, "owner")
    Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type="course",
        target_id=1,
        data={},
    )
    html = _get_html(client)
    assert "notif-menu__row" in html
    assert "data-mark-read-url" not in html


def test_mark_all_read_only_when_unread(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(user, course)
    assert reverse("notifications:mark_all_read") in _get_html(client)
    Notification.objects.filter(recipient=user).update(read_at=timezone.now())
    assert reverse("notifications:mark_all_read") not in _get_html(client)


def test_see_all_footer_present_with_rows(client):
    user = make_login(client, "owner")
    services.notify_enrolled(user, CourseFactory())
    # Assert the footer's own class, not the bare "See all" text — a future
    # unrelated "See all" elsewhere on the shared header/page could false-pass.
    assert "notif-menu__seeall" in _get_html(client)


def test_empty_state_when_no_notifications(client):
    make_login(client, "owner")
    assert "You have no notifications yet." in _get_html(client)
