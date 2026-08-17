"""Media-asset library services: CRUD assets and track where each is used."""

import os

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.db.models import ProtectedError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

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
        from courses.derivatives import generate_derivatives

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
    every element referencing it is untouched. The superseded file is removed.

    `uploaded_file` MUST be an uncommitted upload (an InMemory/TemporaryUploaded
    File). _validate_file short-circuits on a committed FieldFile, so passing
    one would skip BOTH the extension and the size check.
    """
    if not uploaded_file.size:
        # MediaAsset.clean() has no LOWER size bound -- only the upload FORM
        # rejects an empty file. Without this a 0-byte upload would validate,
        # commit, and destroy the old bytes with no undo.
        raise ValidationError(_("The submitted file is empty."))
    old_name = asset.file.name
    old_storage = asset.file.storage
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
