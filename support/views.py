"""The report dialog's POST endpoint."""

import logging

from django.db import transaction
from django.http import JsonResponse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.services import role_names_for
from support.constants import REPORTER_LABEL_MAX_LENGTH
from support.emails import send_issue_report_email
from support.forms import IssueReportForm
from support.policy import can_report
from support.policy import role_snapshot
from support.policy import throttle_exceeded
from support.storage import ScreenshotStorage
from support.telemetry import sanitise

logger = logging.getLogger(__name__)


def _json(payload, status):
    return JsonResponse(payload, status=status)


def _error(message, status):
    return _json({"ok": False, "message": message, "errors": {}}, status)


def build_label(user):
    email = user.email or ""
    label = f"{user.display_name or user.username} ({user.username})"
    if email:
        label = f"{label} <{email}>"
    return label[:REPORTER_LABEL_MAX_LENGTH]


def _persist(report):
    """Isolated so a test can monkeypatch a failure INSIDE the save."""
    report.save()


@require_POST
def report_create(request):
    # No @login_required: fetch() follows a 302 invisibly, so an anonymous POST
    # must be an observable 401 rather than a redirect to the login page.
    if not request.user.is_authenticated:
        return _error(_("Please log in again to send this report."), 401)

    role_names = role_names_for(request)
    if not can_report(request.user, role_names=role_names):
        return _error(_("You do not have access to issue reporting."), 403)

    if throttle_exceeded(request.user):
        return _error(
            _("You have sent a few reports already. Please try again later."), 429
        )

    form = IssueReportForm(request.POST, request.FILES)
    if not form.is_valid():
        errors = {
            field: [item["message"] for item in items]
            for field, items in form.errors.get_json_data().items()
        }
        return _json({"ok": False, "message": None, "errors": errors}, 400)

    saved_name = None
    try:
        with transaction.atomic():
            report = form.save(commit=False)
            report.reporter = request.user
            report.reporter_label = build_label(request.user)
            report.reporter_roles = role_snapshot(role_names)
            report.telemetry = sanitise(request)
            try:
                _persist(report)  # <- the screenshot file is written HERE
            finally:
                # `finally`, NOT the next statement. _persist is exactly where the
                # failure is raised, so a plain assignment after it would never run
                # on the failure path — saved_name would stay None and the cleanup
                # below would silently no-op, which is the bug this whole block
                # exists to prevent. By this point pre_save has set the storage
                # name, so it is captured on both paths.
                saved_name = report.screenshot.name or None
            transaction.on_commit(lambda: send_issue_report_email(report))
    except Exception:
        # Filesystem writes are not transactional: on rollback the row vanishes
        # while the file stays on disk forever — no row means no post_delete, and
        # no PA can ever see or delete it. saved_name is initialised before the
        # outer try so a failure BEFORE _persist (where no file was written) also
        # takes a safe path.
        if saved_name:
            ScreenshotStorage().delete(saved_name)
        raise

    return _json({"ok": True, "message": _("Thank you — your report was sent.")}, 201)
