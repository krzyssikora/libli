import re
from datetime import timedelta

import pytest
from django.contrib import messages as django_messages
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from demo.constants import DEFAULT_DAYS
from demo.constants import LONG_LIVED_DAYS
from demo.models import DemoKit
from demo.services import revoke_kit
from tests.demo.fixtures import small_course
from tests.demo.helpers import provision_for_test
from tests.demo.tab_helpers import demo_tab_url
from tests.demo.tab_helpers import soup
from tests.factories import make_teacher


def _extend(client, kit, **data):
    return client.post(
        reverse("institution:settings_demo_extend", kwargs={"kit_id": kit.pk}), data
    )


def _revoke(client, kit, **data):
    return client.post(
        reverse("institution:settings_demo_revoke", kwargs={"kit_id": kit.pk}), data
    )


def _messages(response, level=None):
    found = list(get_messages(response.wsgi_request))
    return [str(m) for m in found if level is None or m.level == level]


def test_extend_moves_an_active_kit_by_the_default_and_does_not_warn(pa_client, vendor):
    """P12."""
    kit = provision_for_test(small_course())
    before = kit.expires_at

    response = _extend(pa_client, kit)

    kit.refresh_from_db()
    assert kit.expires_at == before + timedelta(days=DEFAULT_DAYS)
    success = _messages(response, django_messages.SUCCESS)
    assert any(date_format(timezone.localtime(kit.expires_at)) in m for m in success)
    assert _messages(response, django_messages.WARNING) == []


def test_extend_restarts_a_pending_purge_kit_from_now(pa_client, vendor):
    kit = provision_for_test(small_course())
    DemoKit.objects.filter(pk=kit.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )

    _extend(pa_client, kit)

    kit.refresh_from_db()
    target = timezone.now() + timedelta(days=DEFAULT_DAYS)
    assert abs((kit.expires_at - target).total_seconds()) < 60
    assert kit.status_key == "active"


def test_extend_warns_about_a_long_lived_kit(pa_client, vendor):
    kit = provision_for_test(small_course())
    DemoKit.objects.filter(pk=kit.pk).update(
        created_at=timezone.now() - timedelta(days=50)
    )

    response = _extend(pa_client, kit)

    warnings = _messages(response, django_messages.WARNING)
    assert len(warnings) == 1
    assert f"more than {LONG_LIVED_DAYS} days" in warnings[0]


def test_extend_refuses_a_closed_kit(pa_client, vendor):
    kit = provision_for_test(small_course())
    revoke_kit(kit)
    kit.refresh_from_db()
    before = kit.expires_at

    response = _extend(pa_client, kit)

    kit.refresh_from_db()
    assert kit.expires_at == before
    assert _messages(response, django_messages.ERROR)


@pytest.mark.parametrize(("posted", "suffix"), [("1", "&all=1"), ("x", "")])
def test_extend_returns_to_the_list_it_came_from(pa_client, vendor, posted, suffix):
    kit = provision_for_test(small_course())

    response = _extend(pa_client, kit, all=posted)

    assert response["Location"] == demo_tab_url() + suffix


def test_revoke_closes_the_kit_and_deletes_its_logins(pa_client, vendor):
    """P13."""
    kit = provision_for_test(small_course())
    user_ids = list(kit.users.values_list("pk", flat=True))

    response = _revoke(pa_client, kit)

    kit.refresh_from_db()
    assert kit.closed_reason == DemoKit.ClosedReason.REVOKED
    assert not get_user_model().objects.filter(pk__in=user_ids).exists()
    assert _messages(response, django_messages.SUCCESS)


def test_revoke_refuses_a_closed_kit(pa_client, vendor):
    kit = provision_for_test(small_course())
    revoke_kit(kit)

    response = _revoke(pa_client, kit)

    assert _messages(response, django_messages.ERROR)


@pytest.mark.parametrize(("posted", "suffix"), [("1", "&all=1"), ("x", "")])
def test_revoke_returns_to_the_list_it_came_from(pa_client, vendor, posted, suffix):
    kit = provision_for_test(small_course())

    response = _revoke(pa_client, kit, all=posted)

    assert response["Location"] == demo_tab_url() + suffix


def test_a_closed_row_has_no_actions(pa_client, vendor):
    """Asserted on ?all=1 — the default list excludes closed kits, so asserting
    there would be vacuous — and against an open row on the same page, so the
    test cannot pass because action forms never render at all."""
    course = small_course()
    closed = provision_for_test(course, label="Closed")
    open_kit = provision_for_test(course, label="Open")
    revoke_kit(closed)

    page = soup(pa_client.get(demo_tab_url(show_all=True)))

    closed_row = page.select_one(f'tr[data-demo-kit="{closed.pk}"]')
    open_row = page.select_one(f'tr[data-demo-kit="{open_kit.pk}"]')
    assert closed_row.select("form") == []
    assert open_row.select_one("form[data-demo-extend]") is not None
    assert open_row.select_one("form[data-demo-revoke]") is not None


def test_the_revoke_confirm_names_the_kit_and_escapes_its_label(pa_client, vendor):
    """On a phone, at the table's right scroll end, nothing else on screen says
    which kit a Revoke acts on. The label is operator input, so it must arrive in
    the attribute escaped, never as markup."""
    course = small_course()
    kit = provision_for_test(course, label="SP 12")
    tagged = provision_for_test(course, label="<b>x</b>")

    response = pa_client.get(demo_tab_url())
    page = soup(response)

    form = page.select_one(f'tr[data-demo-kit="{kit.pk}"] form[data-demo-revoke]')
    prompt = form["data-confirm"]
    assert f"#{kit.pk} " in prompt, prompt
    assert "SP 12" in prompt, prompt

    # Raw attributes, not the Label cell (which shows the same label escaped too).
    raw_prompts = re.findall(r'data-confirm="([^"]*)"', response.content.decode())
    tagged_prompts = [p for p in raw_prompts if f"#{tagged.pk} " in p]
    assert len(tagged_prompts) == 1, raw_prompts
    assert "&lt;b&gt;x&lt;/b&gt;" in tagged_prompts[0], tagged_prompts
    tagged_form = page.select_one(
        f'tr[data-demo-kit="{tagged.pk}"] form[data-demo-revoke]'
    )
    assert tagged_form.select("b") == []


def test_extend_and_revoke_404_on_a_school_box_for_a_real_open_kit(pa_client):
    """P3. A REAL open kit: against a missing id the views' own kit lookup 404s,
    which would keep this green with the vendor check deleted."""
    kit = provision_for_test(small_course())
    before = kit.expires_at

    assert _extend(pa_client, kit).status_code == 404
    assert _revoke(pa_client, kit).status_code == 404

    kit.refresh_from_db()
    assert kit.closed_at is None
    assert kit.expires_at == before


def test_the_actions_need_change_institution(client, vendor):
    kit = provision_for_test(small_course())
    make_teacher(client)

    assert _extend(client, kit).status_code == 403
    assert _revoke(client, kit).status_code == 403
