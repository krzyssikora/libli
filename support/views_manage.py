"""PA triage surface. Every view stacks login_required above permission_required.

raise_exception=True is mandatory, not decoration: permission_required defaults
to False, which redirects to LOGIN_URL (302) instead of raising PermissionDenied,
and every 403 this feature asserts would silently become a 302. login_required on
top gives an anonymous visitor — a stale bookmark, or the report_detail link this
design puts in every email opened after the session expired — log-in-then-return
rather than a bare 403.
"""

import mimetypes

from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from support.constants import LIST_PAGE_SIZE
from support.models import IssueReport
from support.policy import role_labels
from support.telemetry import safe_page_link
from support.telemetry import telemetry_rows

STATUS_FILTERS = ("open", "resolved", "all")
DEFAULT_FILTER = "open"


def _filter_value(request):
    value = request.GET.get("status", DEFAULT_FILTER)
    return value if value in STATUS_FILTERS else DEFAULT_FILTER


@login_required
@permission_required("support.view_issuereport", raise_exception=True)
def report_list(request):
    status = _filter_value(request)
    reports = IssueReport.objects.all()
    if status != "all":
        reports = reports.filter(status=status)
    page = Paginator(reports, LIST_PAGE_SIZE).get_page(request.GET.get("page"))
    for report in page:
        report.role_labels = role_labels(report.reporter_roles)
    return render(
        request,
        "support/manage/report_list.html",
        {"page_obj": page, "status": status, "status_filters": STATUS_FILTERS},
    )


@login_required
@permission_required("support.view_issuereport", raise_exception=True)
def report_detail(request, pk):
    report = get_object_or_404(IssueReport, pk=pk)
    return render(
        request,
        "support/manage/report_detail.html",
        {
            "report": report,
            "roles": role_labels(report.reporter_roles),
            "telemetry": telemetry_rows(report.telemetry),
            "page_link": safe_page_link(report.page_url),
            "status": _filter_value(request),
        },
    )


@require_POST
@login_required
@permission_required("support.change_issuereport", raise_exception=True)
def report_set_status(request, pk):
    target = request.POST.get("status")
    if target not in (IssueReport.Status.OPEN, IssueReport.Status.RESOLVED):
        return HttpResponseBadRequest("unknown status")
    report = get_object_or_404(IssueReport, pk=pk)
    if report.status != target:
        # A no-op on the current status must not overwrite an existing
        # resolved_by/resolved_at and lose who actually triaged it.
        report.status = target
        if target == IssueReport.Status.RESOLVED:
            report.resolved_by = request.user
            report.resolved_at = timezone.now()
        else:
            report.resolved_by = None
            report.resolved_at = None
        report.save(update_fields=["status", "resolved_by", "resolved_at"])
    return redirect("support:report_detail", pk=pk)


@require_POST
@login_required
@permission_required("support.delete_issuereport", raise_exception=True)
def report_delete(request, pk):
    report = get_object_or_404(IssueReport, pk=pk)
    report.delete()  # post_delete removes the screenshot file
    # The filter arrives as a hidden input on the confirmation form, validated
    # against the same set — never HTTP_REFERER, which is an open redirect.
    status = request.POST.get("status")
    status = status if status in STATUS_FILTERS else DEFAULT_FILTER
    return redirect(f"{reverse('support:report_list')}?status={status}")


@login_required
@permission_required("support.view_issuereport", raise_exception=True)
def screenshot(request, pk):
    report = get_object_or_404(IssueReport, pk=pk)
    if not report.screenshot:
        raise Http404("no screenshot")
    try:
        handle = report.screenshot.open("rb")
    except (FileNotFoundError, OSError) as exc:
        # A DB restored against a fresh volume must 404, not 500.
        raise Http404("screenshot missing from storage") from exc
    # Content type from the STORED extension, never from anything the client sent.
    content_type = (
        mimetypes.guess_type(report.screenshot.name.lower())[0]
        or "application/octet-stream"
    )
    response = FileResponse(handle, content_type=content_type)
    response["Content-Disposition"] = "inline"
    return response
