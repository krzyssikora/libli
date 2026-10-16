"""§3 latency bound 3: the per-request push budget."""

import logging
from unittest import mock

import pytest
from django.core.signals import request_started
from django.db import close_old_connections

from notifications.models import Notification
from notifications.push import deliver_notification_push
from notifications.push import reset_push_budget
from notifications.tests.push_helpers import FCM
from notifications.tests.push_helpers import live_session_for
from notifications.tests.push_helpers import make_sub
from notifications.tests.push_helpers import push_settings
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    c = Clock()
    with mock.patch("notifications.push.monotonic", c):
        yield c


def _n(user):
    return Notification.objects.create(
        recipient=user,
        kind="enrolled",
        target_type="course",
        target_id=1,
        data={"course_title": "C", "course_slug": "c"},
    )


@pytest.fixture
def three_subs(settings):
    push_settings(settings)
    user = UserFactory()
    key = live_session_for(user)
    for i in range(3):
        make_sub(user, key, endpoint=f"{FCM}{i}")
    return user


def test_pushes_after_the_deadline_are_skipped_with_one_warning(
    three_subs, clock, caplog
):
    calls = []

    def slow(**kwargs):
        calls.append(kwargs)
        clock.now += 6  # each call "takes" 6 s; the 10 s budget allows two

    with (
        mock.patch("pywebpush.webpush", side_effect=slow),
        caplog.at_level(logging.WARNING),
    ):
        deliver_notification_push(_n(three_subs))
        deliver_notification_push(_n(three_subs))
    assert len(calls) == 2
    warnings = [r for r in caplog.records if "push budget exhausted" in r.getMessage()]
    assert len(warnings) == 1


def test_request_started_resets_the_budget(three_subs, clock):
    # mutant: no request_started receiver
    with mock.patch("pywebpush.webpush") as webpush:
        deliver_notification_push(_n(three_subs))
        clock.now += 60
        # Django's test client does the same: close_old_connections (also on
        # request_started) would close the test transaction's connection.
        request_started.disconnect(close_old_connections)
        try:
            request_started.send(sender=None)
        finally:
            request_started.connect(close_old_connections)
        deliver_notification_push(_n(three_subs))
    assert webpush.call_count == 6


def test_reset_push_budget_lets_a_later_direct_call_push(three_subs, clock):
    with mock.patch("pywebpush.webpush") as webpush:
        deliver_notification_push(_n(three_subs))
        clock.now += 60
        reset_push_budget()
        deliver_notification_push(_n(three_subs))
    assert webpush.call_count == 6


def test_without_a_reset_a_stale_deadline_skips(three_subs, clock):
    # the property the autouse conftest fixture exists for
    with mock.patch("pywebpush.webpush") as webpush:
        deliver_notification_push(_n(three_subs))
        clock.now += 60
        deliver_notification_push(_n(three_subs))
    assert webpush.call_count == 3
