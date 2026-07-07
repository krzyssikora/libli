"""Media-asset library services: CRUD assets and track where each is used."""

import os

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


def create_asset(course, kind, uploaded_file, user, name=""):
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
    return asset


def rename_asset(asset, name):
    """Set the display name (trimmed; empty clears to the filename fallback). The
    255-cap is enforced by the caller (view) before this is reached."""
    asset.name = (name or "").strip()
    asset.save(update_fields=["name"])
    return asset


@transaction.atomic
def delete_asset(asset):
    if usage_count(asset) > 0:
        raise AssetInUseError()
    try:
        asset.delete()
    except ProtectedError as exc:  # concurrent attach raced the usage re-check
        raise AssetInUseError() from exc
