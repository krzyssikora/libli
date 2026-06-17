import os

from django.db import transaction
from django.db.models import Count
from django.db.models import ProtectedError
from django.db.models import Q

from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import VideoElement


class AssetInUseError(Exception):
    """A MediaAsset still referenced by an element cannot be deleted → HTTP 409."""


def usage_count(asset):
    return (
        ImageElement.objects.filter(media=asset).count()
        + VideoElement.objects.filter(media=asset).count()
    )


def assets_with_usage(course, kind=None, q=None):
    """Course assets annotated with a bulk usage count (avoids a per-asset N+1),
    optionally filtered by exact `kind` and a trimmed `q` substring over name OR
    original_filename. Blank/None `q` or `kind` = no filter for that dimension."""
    qs = course.media_assets.all()
    if kind in ("image", "video"):
        qs = qs.filter(kind=kind)
    q = (q or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(original_filename__icontains=q))
    return list(
        qs.annotate(
            img_uses=Count("imageelement", distinct=True),
            vid_uses=Count("videoelement", distinct=True),
        ).order_by("-created")
    )


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
