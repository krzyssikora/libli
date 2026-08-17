"""Media-asset library services: CRUD assets and track where each is used."""

import os

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.db.models import ProtectedError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from courses.derivatives import delete_derivative_files
from courses.derivatives import generate_derivatives
from courses.models import DragToImageQuestionElement
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import VideoElement

# Every concrete element model that holds a (PROTECT) FK named `media` to a MediaAsset,
# with its short human label. The single source of truth for "what can use an asset" —
# usage_count, the manager's count annotations, and the "where used" list all derive
# from this, so a new media-referencing element type only needs adding here.
_MEDIA_REF_MODELS = (
    (ImageElement, _("Image")),
    (VideoElement, _("Video")),
    (DragToImageQuestionElement, _("Drag to image")),
)


class AssetInUseError(Exception):
    """A MediaAsset still referenced by an element cannot be deleted → HTTP 409."""


def usage_count(asset):
    return sum(
        model.objects.filter(media=asset).count() for model, _label in _MEDIA_REF_MODELS
    )


def _usages_for(assets):
    """Map asset_pk -> list of {unit_pk, unit_title, type_label, element_title} for the
    'where used' view. Bulk: a fixed number of queries regardless of how many assets."""
    out = {a.pk: [] for a in assets}
    if not out:
        return out
    ids = list(out)
    for model, label in _MEDIA_REF_MODELS:
        rows = model.objects.filter(media_id__in=ids).prefetch_related("elements__unit")
        for el in rows:
            for join in el.elements.all():
                out[el.media_id].append(
                    {
                        "unit_pk": join.unit_id,
                        "unit_title": join.unit.title,
                        "type_label": label,
                        "element_title": join.title,
                    }
                )
    return out


def attach_usage(asset):
    """Attach img_uses/vid_uses/di_uses + usages to a SINGLE asset (single-cell renders
    after upload/rename). The list view uses assets_with_usage instead."""
    asset.img_uses = ImageElement.objects.filter(media=asset).count()
    asset.vid_uses = VideoElement.objects.filter(media=asset).count()
    asset.di_uses = DragToImageQuestionElement.objects.filter(media=asset).count()
    asset.usages = _usages_for([asset])[asset.pk]
    return asset


def assets_with_usage(course, kind=None, q=None):
    """Course assets annotated with bulk per-type usage counts (avoids a per-asset N+1)
    and an attached `.usages` list (for the 'where used' detail), optionally filtered by
    exact `kind` and a trimmed `q` substring over name OR original_filename. Blank/None
    `q` or `kind` = no filter for that dimension."""
    qs = course.media_assets.all()
    if kind in ("image", "video"):
        qs = qs.filter(kind=kind)
    q = (q or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(original_filename__icontains=q))
    assets = list(
        qs.annotate(
            img_uses=Count("imageelement", distinct=True),
            vid_uses=Count("videoelement", distinct=True),
            di_uses=Count("dragtoimagequestionelement", distinct=True),
        ).order_by("-created")
    )
    usages = _usages_for(assets)
    for a in assets:
        a.usages = usages[a.pk]
    return assets


def truncate_filename(name, limit=255):
    """Path-stripped basename, truncated to `limit` but PRESERVING the extension
    (spec: 'verylong….png', not a bare 'verylong…')."""
    base = os.path.basename(name or "")
    if len(base) <= limit:
        return base
    stem, dot, ext = base.rpartition(".")
    if dot and len(ext) + 1 < limit:
        return stem[: limit - len(ext) - 1] + "." + ext
    return base[:limit]


def create_asset(course, kind, uploaded_file, user, name="", generate=True):
    """Create a MediaAsset and, by default, generate its image derivatives.

    `generate=False` is for bulk paths (the transfer importer) that must not
    pay per-asset generation cost inside a request-held transaction; those
    rows stay pending until the backfill command runs. generate_derivatives
    never raises -- a failed generation records DerivativesState.FAILED and
    leaves thumb/web blank, it never breaks the asset creation itself.
    """
    asset = MediaAsset(
        course=course,
        kind=kind,
        file=uploaded_file,
        original_filename=truncate_filename(uploaded_file.name),
        name=(name or "").strip()[:255],
        uploaded_by=user,
    )
    asset.full_clean()  # per-kind extension + size validators (ValidationError -> 422)
    asset.save()
    if generate:
        generate_derivatives(asset)
        asset.save(
            update_fields=["width", "height", "thumb", "web", "derivatives_state"]
        )
    return asset


def rename_asset(asset, name):
    """Set the display name (trimmed; empty clears to the filename fallback). The
    255-cap is enforced by the caller (view) before this is reached."""
    asset.name = (name or "").strip()
    asset.save(update_fields=["name"])
    return asset


def _delete_file_if_unshared(name, storage):
    """Drop a superseded file from storage, unless another MediaAsset row still
    points at the same name.

    courses/signals.py's post_delete receiver has no such guard: it keys on
    file.name alone, so two rows sharing a name share a lifetime. Migration
    0008 copied storage references verbatim, so shared names exist in real data.
    Deferred via on_commit for the same reason the signal defers -- a
    rolled-back replace must not strand a live row whose file is already gone.
    """
    if not name:
        return
    if MediaAsset.objects.filter(file=name).exists():
        return

    def _remove():
        if storage.exists(name):
            storage.delete(name)

    transaction.on_commit(_remove)


@transaction.atomic
def replace_asset(asset, uploaded_file):
    """Swap the bytes behind an existing asset, preserving pk, kind and name so
    every element referencing it is untouched. The superseded original and
    (for images) its derivatives are removed.

    `uploaded_file` MUST be an uncommitted upload (an InMemory/TemporaryUploaded
    File). _validate_file short-circuits on a committed FieldFile, so passing
    one would skip BOTH the extension and the size check.

    ORDERING IS PINNED. Generating derivatives AFTER the step-3 save without
    extending update_fields silently drops the five new fields. Generating them
    BEFORE it reads asset.file while it is still an uncommitted UploadedFile:
    Pillow advances the stream and Django then writes to storage from the
    current position, truncating the stored original.
    """
    if not uploaded_file.size:
        # MediaAsset.clean() has no LOWER size bound -- only the upload FORM
        # rejects an empty file. Without this a 0-byte upload would validate,
        # commit, and destroy the old bytes with no undo.
        raise ValidationError(_("The submitted file is empty."))

    # --- Step 1: capture, before any reassignment --------------------------
    old_name = asset.file.name
    old_storage = asset.file.storage
    old_thumb_name = asset.thumb.name
    old_web_name = asset.web.name
    derivative_storage = asset.thumb.storage

    # --- Step 2 + 3: assign, validate, commit the original -----------------
    asset.file = uploaded_file
    asset.original_filename = truncate_filename(uploaded_file.name)
    asset.content_hash = ""  # a STALE hash would mis-dedup a later LAL import
    # Validate exactly what this writes. `uploaded_by` is the load-bearing
    # exclusion: null=True WITHOUT blank=True, so clean_fields() raises "This
    # field cannot be blank." for every LAL-imported / migrated / seeded row.
    # course/kind/name would pass anyway and are listed to express the rule.
    # `created` is deliberately NOT listed: auto_now_add makes it
    # editable=False, so Field.validate() early-returns and excluding it would
    # be a no-op that reads as load-bearing. clean() runs regardless of
    # `exclude` and still branches on the untouched self.kind, which is where
    # the per-kind extension/size validation lives.
    asset.full_clean(exclude=["course", "kind", "name", "uploaded_by"])
    asset.save(update_fields=["file", "original_filename", "content_hash"])

    # Computed HERE, not inside the except block below. asset.file.name is
    # already committed and nothing between here and the except block ever
    # reassigns it, so this is safe to compute unconditionally now. It must
    # NOT be computed after a failure: Django 5.2's save_base wraps its write
    # in transaction.mark_for_rollback_on_error, which marks the enclosing
    # atomic block for rollback on ANY exception raised inside it -- so a
    # genuine DB error from step 5's save below poisons this transaction, and
    # an ORM query issued from the except block would itself raise
    # TransactionManagementError, demoting the real error to __context__ and
    # skipping the storage cleanup that was supposed to run after it.
    # _delete_file_if_unshared itself would be a no-op in the except block for
    # the same reason it always was here -- it defers via on_commit (never
    # runs on a rolling-back transaction) and its own exists() check would see
    # this row's own step-3 write -- so this inlines just the share check.
    new_original_is_shared = asset.file.name != old_name and (
        MediaAsset.objects.filter(file=asset.file.name).exclude(pk=asset.pk).exists()
    )

    # --- Steps 4 + 5, guarded ----------------------------------------------
    # The try begins HERE, not at the top: everything above can raise while
    # asset.thumb.name still holds the OLD, LIVE name, and a handler reading it
    # off the instance would destroy the surviving row's derivatives.
    try:
        generate_derivatives(asset)  # reads a COMMITTED FieldFile
        asset.save(
            update_fields=["width", "height", "thumb", "web", "derivatives_state"]
        )
    except Exception:
        # Django 5.2 has transaction.on_commit but NO on_rollback, and the
        # rollback happens at the @atomic decorator boundary after control has
        # left this function -- so cleanup must be immediate and inline. The
        # transaction may already be poisoned by the exception being handled
        # (see the new_original_is_shared comment above), so this block is
        # STORAGE-ONLY -- no ORM access after a failure has occurred.
        #
        # A regenerated derivative that happens to reuse an OLD name (only
        # possible when both the old derivative and the old original's bytes
        # were already missing before this call) is deliberately excluded
        # here and left on disk: it is the name step 6 would otherwise retire
        # for a row that is about to roll back to it, so deleting it now
        # would strand the rolled-back row pointing at nothing. The
        # alternative -- treating it as "new" and deleting it -- is strictly
        # worse, so the rolled-back row keeps a stale-but-present file
        # instead of a missing one.
        new_derivatives = [
            n
            for n in (asset.thumb.name, asset.web.name)
            if n and n not in (old_thumb_name, old_web_name)
        ]
        delete_derivative_files(new_derivatives, derivative_storage)
        if (
            asset.file.name
            and asset.file.name != old_name
            and not new_original_is_shared
            and old_storage.exists(asset.file.name)
        ):
            old_storage.delete(asset.file.name)
        raise

    # --- Step 6: retire the superseded files, deferred ---------------------
    # Safe to delete old_thumb_name/old_web_name by NAME alone, with no
    # sibling check, only because every current write path that can ever
    # populate thumb/web goes through FieldFile.save() (collision-suffixed by
    # storage) or blanks the field to "" -- unlike `file`, no code path
    # assigns a derivative name verbatim the way migration 0008 did for
    # `file`. A future feature that ever copies `.thumb`/`.web` names
    # verbatim between rows (e.g. a "copy course media" bulk action) would
    # silently break this.
    def _retire():
        stale = []
        if asset.thumb.name != old_thumb_name:
            stale.append(old_thumb_name)
        if asset.web.name != old_web_name:
            stale.append(old_web_name)
        delete_derivative_files(stale, derivative_storage)

    transaction.on_commit(_retire)
    # Storage hands back the SAME name when the old file was already missing,
    # in which case the "old" file is the one just written.
    if asset.file.name != old_name:
        _delete_file_if_unshared(old_name, old_storage)
    return asset


@transaction.atomic
def delete_asset(asset):
    if usage_count(asset) > 0:
        raise AssetInUseError()
    try:
        asset.delete()
    except ProtectedError as exc:  # concurrent attach raced the usage re-check
        raise AssetInUseError() from exc
