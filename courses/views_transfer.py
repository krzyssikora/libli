"""Export-side views (Task 4). Task 12 adds the import half here too."""

import tempfile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_GET

from courses.access import can_manage_course
from courses.models import ContentNode
from courses.models import Course
from courses.transfer.export import export_filename
from courses.transfer.export import write_archive
from courses.transfer.schema import TransferError


def _stream_archive(request, course, node):
    # Spool fully before streaming: a mid-build failure raises here and returns a
    # clean error response, never a truncated zip (§3).
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    try:
        write_archive(course, node, spool, source_host=request.get_host())
    except TransferError as exc:  # e.g. a media file missing from storage
        spool.close()
        messages.error(request, exc.message)
        # Builder is the deliberate landing spot even for list-page exports:
        # it's the repair surface for a broken element/media reference.
        return redirect("courses:manage_builder", slug=course.slug)
    spool.seek(0)
    return FileResponse(
        spool,
        as_attachment=True,
        filename=export_filename(course, node, timezone.localdate()),
        content_type="application/zip",
    )


@login_required
@require_GET
def export_course(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    return _stream_archive(request, course, None)


@login_required
@require_GET
def export_subtree(request, slug, pk):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    node = get_object_or_404(ContentNode, pk=pk, course=course)  # scoped: forged → 404
    return _stream_archive(request, course, node)
