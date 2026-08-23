"""The dialog's POST endpoint: gating, throttling, sanitising, persistence."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from support.constants import DESCRIPTION_MAX_LENGTH
from support.constants import PAGE_TITLE_MAX_LENGTH
from support.constants import PAGE_URL_MAX_LENGTH
from support.constants import THROTTLE_MAX_REPORTS
from support.models import IssueReport
from support.models import SupportSettings
from tests.factories import UserFactory
from tests.factories import make_ca
from tests.factories import make_student
from tests.test_support_models import _png_bytes

pytestmark = pytest.mark.django_db

URL_NAME = "support:report_create"
Audience = SupportSettings.Audience


def _set_audience(value):
    row = SupportSettings.load()
    row.audience = value
    row.save()


def _payload(**overrides):
    data = {
        "description": "The submit button does nothing.",
        "page_url": "https://libli.example/units/3/",
        "page_title": "Fractions",
        "viewport_w": "1280",
        "viewport_h": "800",
        "theme": "dark",
    }
    data.update(overrides)
    return data


def test_a_permitted_user_creates_one_report(client):
    _set_audience(Audience.ALL)
    student = make_student(client)
    response = client.post(reverse(URL_NAME), _payload())
    assert response.status_code == 201
    assert response.json()["ok"] is True
    report = IssueReport.objects.get()
    assert report.reporter == student
    assert report.page_url == "https://libli.example/units/3/"
    assert report.telemetry["viewport_w"] == 1280
    assert "Student" in report.reporter_roles
    assert student.username in report.reporter_label


def test_a_student_is_refused_when_the_rung_is_course_admins(client):
    """Hiding the menu item is not access control, and the top rung is Everyone."""
    _set_audience(Audience.COURSE_ADMINS)
    make_student(client)
    response = client.post(reverse(URL_NAME), _payload())
    assert response.status_code == 403
    assert IssueReport.objects.count() == 0


def test_a_course_admin_is_allowed_on_that_same_rung(client):
    _set_audience(Audience.COURSE_ADMINS)
    make_ca(client)
    assert client.post(reverse(URL_NAME), _payload()).status_code == 201
    assert "Course Admin" in IssueReport.objects.get().reporter_roles


def test_anonymous_gets_401_json_not_a_redirect(client):
    """fetch() follows a 302 invisibly: the dialog would see a 200 + HTML login
    page, throw on .json(), and die silently with the user's text still in it."""
    response = client.post(reverse(URL_NAME), _payload())
    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/json")


def test_get_is_rejected(client):
    _set_audience(Audience.ALL)
    make_student(client)
    assert client.get(reverse(URL_NAME)).status_code == 405


def test_an_empty_description_is_a_field_error(client):
    _set_audience(Audience.ALL)
    make_student(client)
    response = client.post(reverse(URL_NAME), _payload(description="   "))
    assert response.status_code == 400
    assert "description" in response.json()["errors"]
    assert IssueReport.objects.count() == 0


def test_an_over_long_description_is_a_field_error(client):
    _set_audience(Audience.ALL)
    make_student(client)
    response = client.post(
        reverse(URL_NAME), _payload(description="x" * (DESCRIPTION_MAX_LENGTH + 1))
    )
    assert response.status_code == 400
    assert "description" in response.json()["errors"]
    assert IssueReport.objects.count() == 0


def test_an_over_long_page_title_is_truncated_not_rejected(client):
    """A ModelForm-derived page_title would carry MaxLengthValidator, which fires
    inside _clean_fields BEFORE clean_page_title and would 400 instead."""
    _set_audience(Audience.ALL)
    make_student(client)
    response = client.post(
        reverse(URL_NAME), _payload(page_title="t" * (PAGE_TITLE_MAX_LENGTH + 50))
    )
    assert response.status_code == 201
    assert len(IssueReport.objects.get().page_title) == PAGE_TITLE_MAX_LENGTH


def test_server_assigned_columns_cannot_be_set_from_the_payload(client):
    """Mutant: widen IssueReportForm to fields = "__all__"."""
    _set_audience(Audience.ALL)
    student = make_student(client)
    # UserFactory, NOT make_pa: make_* logs the new user in, and calling
    # make_student twice would try to create a second user named "student" and
    # raise IntegrityError. The test only needs another user's pk.
    other = UserFactory(username="someone-else")
    client.post(
        reverse(URL_NAME),
        _payload(
            status=IssueReport.Status.RESOLVED,
            reporter=other.pk,
            emailed_at="2020-01-01T00:00:00Z",
            telemetry='{"forged": true}',
        ),
    )
    report = IssueReport.objects.get()
    assert report.reporter == student
    assert report.status == IssueReport.Status.OPEN
    assert report.emailed_at is None
    assert "forged" not in report.telemetry


def test_the_sixth_report_in_the_window_is_throttled(client):
    _set_audience(Audience.ALL)
    make_student(client)
    for _ in range(THROTTLE_MAX_REPORTS):
        assert client.post(reverse(URL_NAME), _payload()).status_code == 201
    response = client.post(reverse(URL_NAME), _payload())
    assert response.status_code == 429
    assert response.json()["message"]
    assert IssueReport.objects.count() == THROTTLE_MAX_REPORTS


def test_a_screenshot_is_actually_stored(client, tmp_path):
    """Mutant: bind the form without request.FILES — it validates and saves
    cleanly with the screenshot silently discarded."""
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        _set_audience(Audience.ALL)
        make_student(client)
        upload = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
        response = client.post(reverse(URL_NAME), _payload(screenshot=upload))
        assert response.status_code == 201
        assert IssueReport.objects.get().screenshot.name


def test_a_failure_inside_save_leaves_no_orphaned_file(client, tmp_path, monkeypatch):
    """The DB row rolls back but the file write does not — without the cleanup the
    screenshot stays on disk forever, with no row and so no post_delete.

    _boom performs the REAL save first and only then fails. Stubbing _persist out
    entirely would mean FileField.pre_save never runs, no file is ever written,
    and the assertion passes vacuously — green even with the whole except/delete
    block removed.
    """
    import support.views as views

    real_persist = views._persist
    written = {}

    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        _set_audience(Audience.ALL)
        make_student(client)

        def _boom(report):
            real_persist(report)  # writes the file, inserts the row
            written["path"] = report.screenshot.path
            raise RuntimeError("db is unhappy")

        monkeypatch.setattr(views, "_persist", _boom)
        upload = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
        with pytest.raises(RuntimeError):
            client.post(reverse(URL_NAME), _payload(screenshot=upload))

    # The file really did land on disk mid-transaction...
    assert written["path"]
    # ...and the cleanup removed it, and the row rolled back.
    assert list(tmp_path.rglob("*.png")) == []
    assert IssueReport.objects.count() == 0


def test_an_over_long_page_url_is_truncated_not_rejected(client):
    _set_audience(Audience.ALL)
    make_student(client)
    long_url = "https://libli.example/?q=" + "x" * (PAGE_URL_MAX_LENGTH + 100)
    response = client.post(reverse(URL_NAME), _payload(page_url=long_url))
    assert response.status_code == 201
    assert len(IssueReport.objects.get().page_url) == PAGE_URL_MAX_LENGTH


def test_a_successful_post_registers_an_on_commit_callback(
    client, django_capture_on_commit_callbacks
):
    """Mutant: delete the transaction.on_commit(...) line — without this test,
    every other test in this file and in the email file still passes, because
    those call send_issue_report_email directly.

    Asserts the callback is REGISTERED (execute=False), not that mail was sent:
    this module tests report_create in isolation, so it does not depend on
    email delivery succeeding. The delivery assertion (execute=True) lives in
    test_support_emails.py::test_a_successful_post_actually_delivers.
    """
    _set_audience(Audience.ALL)
    make_student(client)
    with django_capture_on_commit_callbacks() as callbacks:
        assert client.post(reverse(URL_NAME), _payload()).status_code == 201
    assert len(callbacks) == 1
