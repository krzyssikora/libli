"""Recipient resolution, envelope shape and delivery bookkeeping."""

from unittest import mock

import pytest
from django.conf import settings as dj_settings
from django.contrib.auth.models import Group as AuthGroup
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

import support.emails
from institution.models import Institution
from institution.roles import PLATFORM_ADMIN
from institution.roles import seed_roles
from support.emails import send_issue_report_email
from support.models import IssueReport
from support.models import SupportSettings
from tests.factories import UserFactory
from tests.test_support_models import _png_bytes

pytestmark = pytest.mark.django_db


def _pa(email="pa@school.example", **kwargs):
    seed_roles()
    user = UserFactory(email=email, **kwargs)
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


def _report(**kwargs):
    kwargs.setdefault("description", "It broke")
    kwargs.setdefault("reporter_label", "Ada (ada) <ada@school.example>")
    return IssueReport.objects.create(**kwargs)


def test_recipients_union_pas_and_extra_addresses_in_bcc():
    _pa(email="pa@school.example")
    row = SupportSettings.load()
    row.extra_emails = ["helpdesk@school.example"]
    row.save()
    send_issue_report_email(_report())
    message = mail.outbox[0]
    assert set(message.bcc) == {"pa@school.example", "helpdesk@school.example"}
    assert message.to == [dj_settings.DEFAULT_FROM_EMAIL]


def test_recipients_are_deduplicated_case_insensitively():
    _pa(email="pa@school.example")
    row = SupportSettings.load()
    row.extra_emails = ["PA@School.Example"]
    row.save()
    send_issue_report_email(_report())
    assert len(mail.outbox[0].bcc) == 1


def test_an_inactive_pa_and_an_emailless_pa_are_not_recipients():
    _pa(email="active@school.example")
    _pa(email="inactive@school.example", is_active=False)
    _pa(email="")
    send_issue_report_email(_report())
    assert mail.outbox[0].bcc == ["active@school.example"]


def test_no_recipients_means_no_message_and_no_emailed_at():
    """to=[DEFAULT_FROM_EMAIL] makes an empty bcc a perfectly valid message, so
    without the short-circuit send() would return 1 and emailed_at would lie."""
    report = _report()
    send_issue_report_email(report)
    report.refresh_from_db()
    assert mail.outbox == []
    assert report.emailed_at is None


def test_a_newline_in_the_display_name_cannot_split_the_subject():
    _pa()
    report = _report(reporter_label="Ada\r\nBcc: evil@x.test")
    send_issue_report_email(report)
    assert "\n" not in mail.outbox[0].subject
    assert "\r" not in mail.outbox[0].subject


def test_the_subject_carries_the_report_id():
    """Without it every report from one reporter shares a byte-identical subject
    and mail clients thread them into an undifferentiated pile."""
    _pa()
    report = _report()
    send_issue_report_email(report)
    assert str(report.pk) in mail.outbox[0].subject


def test_the_body_links_to_the_report_detail_page():
    _pa()
    report = _report()
    send_issue_report_email(report)
    path = reverse("support:report_detail", args=[report.pk])
    assert path in mail.outbox[0].body


def test_the_screenshot_is_attached(tmp_path):
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        _pa()
        report = _report()
        report.screenshot.save(
            "shot.png", SimpleUploadedFile("shot.png", _png_bytes()), save=True
        )
        send_issue_report_email(report)
        assert len(mail.outbox[0].attachments) == 1


def test_emailed_at_is_stamped_without_clobbering_a_concurrent_status_change():
    _pa()
    report = _report()
    IssueReport.objects.filter(pk=report.pk).update(status=IssueReport.Status.RESOLVED)
    send_issue_report_email(report)  # `report` still holds status=open in memory
    report.refresh_from_db()
    assert report.emailed_at is not None
    assert report.status == IssueReport.Status.RESOLVED


def test_a_send_that_raises_still_leaves_the_report(monkeypatch):
    _pa()
    report = _report()

    def _boom(self, *args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(
        "django.core.mail.EmailMultiAlternatives.send", _boom, raising=True
    )
    send_issue_report_email(report)  # must NOT raise
    report.refresh_from_db()
    assert report.emailed_at is None
    assert IssueReport.objects.count() == 1


def test_the_message_uses_the_institution_language_not_the_reporters():
    """An A/B, because a single English check proves nothing: English is both the
    institution default AND the untranslated msgid, so the mutant ("override to
    the reporter's language") would produce an identical subject.

    Asserts on the observed active language rather than catalog text, so it runs
    now (no Polish catalog needed — Task 12 is six tasks away) and does not
    re-break whenever the Polish wording is edited.
    """
    from django.utils import translation

    from core.services import invalidate_site_config

    observed = {}
    real_render = support.emails.render_to_string

    def _spy(template, ctx):
        observed["language"] = translation.get_language()
        return real_render(template, ctx)

    inst = Institution.load()
    inst.default_language = "pl"
    inst.save()
    invalidate_site_config()

    reporter = UserFactory(username="polly", email="polly@school.example")
    _pa()
    with translation.override("en"):  # the REPORTER's language, deliberately not pl
        with mock.patch.object(support.emails, "render_to_string", _spy):
            send_issue_report_email(_report(reporter=reporter))
    assert observed["language"] == "pl"


def test_a_javascript_page_url_is_never_an_href_in_the_email():
    _pa()
    send_issue_report_email(_report(page_url="javascript:alert(1)"))
    html = mail.outbox[0].alternatives[0][0]
    assert 'href="javascript:' not in html


def test_a_successful_post_actually_delivers(
    client, django_capture_on_commit_callbacks
):
    """The other half of Task 4's callback-registration test: now that both the
    real emails module and support:report_detail exist, prove the wired callback
    delivers. Mutant: delete the transaction.on_commit(...) line in the view."""
    from support.models import SupportSettings as _S
    from tests.factories import make_student

    _pa()
    row = _S.load()
    row.audience = _S.Audience.ALL
    row.save()
    make_student(client)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("support:report_create"), {"description": "It broke"}
        )
    assert response.status_code == 201
    assert len(mail.outbox) == 1
