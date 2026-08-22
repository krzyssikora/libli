"""Triage list/detail/status/delete/screenshot, and their permission gates."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from support.models import IssueReport
from tests.factories import make_pa
from tests.factories import make_teacher
from tests.test_support_models import _png_bytes

pytestmark = pytest.mark.django_db


def _report(**kwargs):
    kwargs.setdefault("description", "It broke")
    return IssueReport.objects.create(**kwargs)


def test_a_pa_sees_only_open_reports_by_default(client):
    make_pa(client)
    _report(description="still open")
    _report(description="already done", status=IssueReport.Status.RESOLVED)
    body = client.get(reverse("support:report_list")).content.decode()
    assert "still open" in body
    assert "already done" not in body


def test_status_all_shows_both_and_a_bogus_value_falls_back_to_open(client):
    make_pa(client)
    _report(description="still open")
    _report(description="already done", status=IssueReport.Status.RESOLVED)
    both = client.get(reverse("support:report_list"), {"status": "all"})
    assert "already done" in both.content.decode()
    bogus = client.get(reverse("support:report_list"), {"status": "nonsense"})
    assert "already done" not in bogus.content.decode()


def test_a_teacher_gets_403_not_a_login_redirect(client):
    """permission_required defaults to raise_exception=False, which 302s."""
    make_teacher(client)
    report = _report()
    for name, args in (
        ("support:report_list", []),
        ("support:report_detail", [report.pk]),
        ("support:screenshot", [report.pk]),
    ):
        assert client.get(reverse(name, args=args)).status_code == 403


def test_anonymous_is_redirected_to_login_rather_than_403(client):
    report = _report()
    response = client.get(reverse("support:report_detail", args=[report.pk]))
    assert response.status_code == 302
    assert "/login" in response["Location"] or "accounts" in response["Location"]


def test_resolving_records_who_and_when(client):
    pa = make_pa(client)
    report = _report()
    client.post(
        reverse("support:report_set_status", args=[report.pk]),
        {"status": IssueReport.Status.RESOLVED},
    )
    report.refresh_from_db()
    assert report.status == IssueReport.Status.RESOLVED
    assert report.resolved_by == pa
    assert report.resolved_at is not None


def test_resolving_twice_preserves_the_original_triager(client):
    first = make_pa(client, username="first-pa")
    report = _report()
    client.post(
        reverse("support:report_set_status", args=[report.pk]),
        {"status": IssueReport.Status.RESOLVED},
    )
    report.refresh_from_db()
    original_at = report.resolved_at
    make_pa(client, username="second-pa")
    client.post(
        reverse("support:report_set_status", args=[report.pk]),
        {"status": IssueReport.Status.RESOLVED},
    )
    report.refresh_from_db()
    assert report.resolved_by == first
    assert report.resolved_at == original_at


def test_reopening_clears_the_resolution(client):
    make_pa(client)
    report = _report(status=IssueReport.Status.RESOLVED)
    client.post(
        reverse("support:report_set_status", args=[report.pk]),
        {"status": IssueReport.Status.OPEN},
    )
    report.refresh_from_db()
    assert report.status == IssueReport.Status.OPEN
    assert report.resolved_by is None
    assert report.resolved_at is None


def test_a_bogus_status_is_400_and_leaves_the_row_alone(client):
    make_pa(client)
    report = _report()
    response = client.post(
        reverse("support:report_set_status", args=[report.pk]), {"status": "banana"}
    )
    assert response.status_code == 400
    report.refresh_from_db()
    assert report.status == IssueReport.Status.OPEN


def test_a_pa_can_delete_a_report_and_its_file(client, tmp_path):
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        make_pa(client)
        report = _report()
        report.screenshot.save(
            "shot.png", SimpleUploadedFile("shot.png", _png_bytes()), save=True
        )
        response = client.post(
            reverse("support:report_delete", args=[report.pk]), {"status": "all"}
        )
        assert response.status_code == 302
        # The filter must survive the round-trip; dropping the hidden input and
        # its validation would otherwise leave this test green.
        assert response["Location"].endswith("?status=all")
        assert IssueReport.objects.count() == 0
        assert list(tmp_path.rglob("*.png")) == []


def test_a_bogus_delete_filter_falls_back_to_the_default(client):
    make_pa(client)
    report = _report()
    response = client.post(
        reverse("support:report_delete", args=[report.pk]), {"status": "../evil"}
    )
    assert response["Location"].endswith("?status=open")


def test_a_teacher_cannot_delete_and_get_does_not_delete(client):
    make_teacher(client)
    report = _report()
    assert (
        client.post(reverse("support:report_delete", args=[report.pk])).status_code
        == 403
    )
    make_pa(client)
    assert (
        client.get(reverse("support:report_delete", args=[report.pk])).status_code
        == 405
    )
    assert IssueReport.objects.count() == 1


def test_screenshot_404s_when_absent_or_missing_from_disk(client, tmp_path):
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        make_pa(client)
        empty = _report()
        assert (
            client.get(reverse("support:screenshot", args=[empty.pk])).status_code
            == 404
        )
        withfile = _report()
        withfile.screenshot.save(
            "shot.png", SimpleUploadedFile("shot.png", _png_bytes()), save=True
        )
        path = withfile.screenshot.path
        import os

        os.remove(path)
        assert (
            client.get(reverse("support:screenshot", args=[withfile.pk])).status_code
            == 404
        )


def test_screenshot_is_served_inline_with_a_server_derived_type(client, tmp_path):
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        make_pa(client)
        report = _report()
        report.screenshot.save(
            "shot.png", SimpleUploadedFile("shot.png", _png_bytes()), save=True
        )
        response = client.get(reverse("support:screenshot", args=[report.pk]))
        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert response["Content-Disposition"].startswith("inline")


def test_a_hostile_page_url_is_never_an_href(client):
    make_pa(client)
    report = _report(page_url="javascript:alert(1)")
    body = client.get(
        reverse("support:report_detail", args=[report.pk])
    ).content.decode()
    assert 'href="javascript:' not in body


def test_an_unmailed_report_is_flagged_in_the_detail_page(client):
    make_pa(client)
    report = _report()
    body = client.get(
        reverse("support:report_detail", args=[report.pk])
    ).content.decode()
    assert "not emailed" in body.lower()
