"""Export-side views (Task 4). Task 12 adds the import half here too."""

import os
import tempfile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from courses.access import can_manage_course
from courses.models import ContentNode
from courses.models import Course
from courses.ordering import legal_child_kinds
from courses.transfer import staging
from courses.transfer.export import export_filename
from courses.transfer.export import write_archive
from courses.transfer.importer import build_preview
from courses.transfer.importer import import_course
from courses.transfer.importer import import_subtree
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.schema import KIND_COURSE
from courses.transfer.schema import KIND_SUBTREE
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


# --- Import (Task 12) --------------------------------------------------------

# gettext_lazy: a module-level constant with eager gettext would freeze to the
# import-time language (the PR #46 footgun).
_EXPIRED_MSG = gettext_lazy(
    "The staged upload has expired or was not found — please upload the archive again."
)


def _render_upload(request, *, target_course=None, error=None, status=200):
    return render(
        request,
        "courses/manage/import_course.html",
        {"target_course": target_course, "error": error},
        status=status,
    )


def _handle_upload(request, *, slot, expected_kind, target_course=None):
    upload = request.FILES.get("archive")
    if upload is None:
        return _render_upload(
            request,
            target_course=target_course,
            error=_("Choose a .zip archive to import."),
            status=422,
        )
    # Pre-stage size check: don't stream a multi-GiB body to the staging dir
    # only to reject it; read_archive re-checks as defense in depth.
    if upload.size > settings.TRANSFER_MAX_COMPRESSED_BYTES:
        return _render_upload(
            request,
            target_course=target_course,
            status=422,
            error=_(
                "The archive is %(found)d bytes; this instance accepts at "
                "most %(limit)d bytes."
            )
            % {
                "found": upload.size,
                "limit": settings.TRANSFER_MAX_COMPRESSED_BYTES,
            },
        )
    course_pk = target_course.pk if target_course else None
    token, path = staging.stage(request.session, slot, upload, course_pk=course_pk)
    try:
        # §1: validate BEFORE preview — build_preview assumes a validated
        # document, so this untrusted archive must pass validate_archive_document
        # before build_preview ever sees it.
        with (
            open(path, "rb") as fh,
            open_archive(fh, expected_kind=expected_kind) as (
                zf,
                manifest,
                document,
                media_entries,
            ),
        ):
            validate_archive_document(
                zf,
                manifest,
                document,
                media_entries,
                kind=expected_kind,
                target_course=target_course,
            )
            preview = build_preview(
                manifest, document, media_entries, target_course=target_course
            )
    except OSError:  # superseded/unlinked by a concurrent second-tab stage
        return _render_upload(
            request, target_course=target_course, error=_EXPIRED_MSG, status=422
        )
    except TransferError as exc:
        staging.discard(request.session, slot, token)
        return _render_upload(
            request, target_course=target_course, error=exc.message, status=422
        )
    if expected_kind == KIND_SUBTREE and not preview["insertion_choices"]:
        staging.discard(request.session, slot, token)
        return _render_upload(
            request,
            target_course=target_course,
            status=422,
            error=_(
                "This subtree cannot be placed anywhere in this course's structure."
            ),
        )
    return render(
        request,
        "courses/manage/import_preview.html",
        {"preview": preview, "token": token, "target_course": target_course},
    )


def _handle_confirm(request, *, slot, expected_kind, target_course=None):
    course_pk = target_course.pk if target_course else None
    claimed = staging.claim(
        request.session, slot, request.POST.get("token", ""), course_pk=course_pk
    )
    if claimed is None:
        return _render_upload(
            request, target_course=target_course, error=_EXPIRED_MSG, status=422
        )
    try:
        with (
            open(claimed, "rb") as fh,
            open_archive(fh, expected_kind=expected_kind) as (
                zf,
                manifest,
                document,
                media_entries,
            ),
        ):
            # §4.2: full re-validation against CURRENT state at confirm time —
            # the DB may have changed since the preview was rendered.
            validate_archive_document(
                zf,
                manifest,
                document,
                media_entries,
                kind=expected_kind,
                target_course=target_course,
            )
            if expected_kind == KIND_COURSE:
                new_course = import_course(
                    zf, manifest, document, media_entries, request.user
                )
                messages.success(
                    request,
                    _("Course “%(title)s” imported.") % {"title": new_course.title},
                )
                return redirect("courses:manage_builder", slug=new_course.slug)
            insertion = None
            raw = request.POST.get("insertion", "")
            if raw:
                try:
                    pk = int(raw)
                except ValueError:
                    raise TransferError(_("Invalid insertion point.")) from None
                # §2: scoped lookup — a forged/stale node id from ANOTHER course
                # (or one deleted between preview and confirm) 404s here, rather
                # than being passed unscoped into import_subtree.
                insertion = get_object_or_404(ContentNode, pk=pk, course=target_course)
            root_kind = document["nodes"][0]["kind"]
            parent_kind = insertion.kind if insertion else None
            if root_kind not in legal_child_kinds(
                parent_kind, target_course.allowed_kinds
            ):
                raise TransferError(
                    _("A '%(kind)s' cannot be placed there.") % {"kind": root_kind}
                )
            import_subtree(
                zf,
                manifest,
                document,
                media_entries,
                target_course,
                insertion,
                request.user,
            )
            messages.success(request, _("Content imported."))
            return redirect("courses:manage_builder", slug=target_course.slug)
    except TransferError as exc:
        return _render_upload(
            request, target_course=target_course, error=exc.message, status=422
        )
    finally:
        # §3: the staging module does not self-clean claimed slots — this is
        # the only place the claimed archive ever gets deleted, on success,
        # on a TransferError, AND on any other exception (e.g. Http404 from
        # the scoped get_object_or_404 above) since `finally` always runs.
        try:
            os.unlink(claimed)
        except OSError:
            pass


@login_required
@permission_required("courses.add_course", raise_exception=True)
def import_course_view(request):
    if request.method == "POST":
        return _handle_upload(
            request, slot=staging.SLOT_COURSE, expected_kind=KIND_COURSE
        )
    return _render_upload(request)


@login_required
@permission_required("courses.add_course", raise_exception=True)
@require_POST
def import_course_confirm(request):
    return _handle_confirm(request, slot=staging.SLOT_COURSE, expected_kind=KIND_COURSE)


@login_required
@permission_required("courses.add_course", raise_exception=True)
@require_POST
def import_course_cancel(request):
    staging.discard(request.session, staging.SLOT_COURSE, request.POST.get("token", ""))
    messages.info(request, _("Import cancelled."))
    return redirect("courses:manage_course_list")


def _target_or_403(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    return course


@login_required
def import_content_view(request, slug):
    course = _target_or_403(request, slug)
    if request.method == "POST":
        return _handle_upload(
            request,
            slot=staging.SLOT_SUBTREE,
            expected_kind=KIND_SUBTREE,
            target_course=course,
        )
    return _render_upload(request, target_course=course)


@login_required
@require_POST
def import_content_confirm(request, slug):
    course = _target_or_403(request, slug)
    return _handle_confirm(
        request,
        slot=staging.SLOT_SUBTREE,
        expected_kind=KIND_SUBTREE,
        target_course=course,
    )


@login_required
@require_POST
def import_content_cancel(request, slug):
    course = _target_or_403(request, slug)
    staging.discard(
        request.session, staging.SLOT_SUBTREE, request.POST.get("token", "")
    )
    messages.info(request, _("Import cancelled."))
    return redirect("courses:manage_builder", slug=course.slug)
