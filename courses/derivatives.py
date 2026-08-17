"""Image derivatives for MediaAsset: a 512px thumb and an 896px web copy.

Everything image-processing lives here. The rules below are ordered, and four
of them exist because the obvious implementation was measured to be wrong --
each carries the measurement in a comment. Do not reorder without re-reading
them.
"""

import io
import logging
import os

from django.core.files.base import ContentFile
from PIL import Image
from PIL import ImageOps

from courses.models import DerivativesState

logger = logging.getLogger(__name__)

# Imported by courses/templatetags/courses_media_extras.py. These appear in the
# generator, the filenames and the `w` descriptors, so a future width change
# must not be able to drift the tag away from the bytes on disk.
#
# THUMB_WIDTH stays 512, NOT raised to 720, despite the measurements doc
# (2026-08-17-media-image-derivatives-measurements.md, Section 4) finding the
# DPR-3 raise condition fires for the asset-thumb picker box. Decision:
# accept the shortfall rather than raise the constant. Magnitude: 512/720 =
# 0.711x, i.e. effective DPR 2.13 instead of 3.0. Reachability (Section 6):
# only at viewports <=308px, below every mainstream phone's narrowest common
# CSS width (320px), and only on the two staff-only media surfaces (picker up
# to 308px, manager up to 280px -- Section 6.2). See Section 4 of the
# measurements doc for the full reasoning and the cheaper remedy (a fluid
# srcset preset, PR 2, zero regeneration cost).
THUMB_WIDTH = 512
WEB_WIDTH = 896

# WebP refuses either dimension above this.
_WEBP_MAX_DIMENSION = 16383

_ENCODER_KWARGS = {
    # method (0-6) swings lossless encode time several-fold, and generation runs
    # synchronously inside an upload request and in a loop over ~950 images.
    # exact=True preserves RGB values under fully-transparent pixels.
    "format": "WEBP",
    "lossless": True,
    "method": 4,
    "exact": True,
}


def _encode(img):
    """Encode to bytes in memory. Separate function so tests can force the
    discard branch without a pathological fixture."""
    buf = io.BytesIO()
    img.save(buf, **_ENCODER_KWARGS)
    return buf.getvalue()


def delete_derivative_files(names, storage):
    """Delete derivative files by NAME, immediately.

    Names, not an asset: every caller needs to delete files that are no longer
    the asset's -- replace_asset and backfill --force delete SUPERSEDED names
    captured before regeneration, and post_delete runs when the row is gone.

    Deletes IMMEDIATELY and does not defer. Stated because the neighbouring
    _delete_file_if_unshared in courses/media.py DOES call transaction.on_commit
    itself, so local precedent points the wrong way -- and the replace_asset
    failure handler needs an immediate delete, since an on_commit callback
    registered on a transaction that is about to roll back never runs.

    The falsy guard belongs here, not at the call sites: post_delete passes
    [thumb.name, web.name], both blank for every video and every skipped/failed
    row, and FileSystemStorage.delete("") raises ValueError while
    storage.exists("") is TRUTHY (it stats MEDIA_ROOT).
    """
    for name in names:
        if not name:
            continue
        try:
            if storage.exists(name):
                storage.delete(name)
        except Exception:  # noqa: BLE001 - cleanup must never mask the real error
            logger.exception("could not delete derivative %s", name)


def generate_derivatives(asset):
    """Populate width/height/thumb/web/derivatives_state. Never raises.

    Assigns asset.derivatives_state on the instance AND returns it: callers list
    that field in update_fields, so a version that only returned the value would
    persist the stale one while the correct one was discarded as an unused
    return.
    """
    # --- Rule 0: reset before any branch can return -------------------------
    # Every early-return path would otherwise leave the PREVIOUS image's values
    # in place -- on a replace where the new original is 500px wide, step 6
    # skips `web` and asset.web would still point at the old picture.
    asset.thumb = ""
    asset.web = ""
    asset.width = None
    asset.height = None
    asset.derivatives_state = ""

    if asset.kind != "image":
        asset.derivatives_state = DerivativesState.SKIPPED
        return asset.derivatives_state

    written = []
    storage = asset.thumb.storage
    try:
        asset.file.open("rb")
        try:
            raw = asset.file.read()
        finally:
            asset.file.close()

        with Image.open(io.BytesIO(raw)) as opened:
            # --- Rule 2: probe animation BEFORE any transpose ---------------
            # ImageOps.exif_transpose returns a BASE Image, not the format
            # subclass, so is_animated is ABSENT on the result and
            # getattr(..., False) is unconditionally False. Verified on a real
            # mat-pp asset: fibonacci_spiral.gif opens as GifImageFile with
            # is_animated=True, n_frames=22; after transpose the attribute is
            # gone. Probing after would flatten all 18 animated GIFs.
            is_animated = bool(getattr(opened, "is_animated", False))
            img = ImageOps.exif_transpose(opened)

            asset.width, asset.height = img.width, img.height

            if is_animated:
                asset.derivatives_state = DerivativesState.SKIPPED
                return asset.derivatives_state

            # --- Rule 5: normalise mode BEFORE resizing ---------------------
            # Image.resize downgrades resample to NEAREST for modes "1" and
            # "P", silently ignoring LANCZOS. Verified on Pillow 12.2.0.
            has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
            img = img.convert("RGBA" if has_alpha else "RGB")

            source_size = asset.file.size
            stem = os.path.splitext(os.path.basename(asset.file.name))[0]

            for target, field in ((THUMB_WIDTH, "thumb"), (WEB_WIDTH, "web")):
                if img.width <= target:
                    continue
                # --- Rule 6: clamp the scaled dimension to >= 1, and skip a
                # target whose derived height exceeds the WebP dimension cap.
                # An extremely wide/flat source (e.g. 3000x1) rounds the
                # scaled height to 0, which Pillow's resize() rejects with
                # ValueError("height and width must be > 0"). Measured:
                # without this clamp a 3000x1 source lands in FAILED instead
                # of encoding a degenerate-but-valid (512, 1) / (896, 1) pair.
                height = max(1, round(img.height * target / img.width))
                # A tall source (e.g. 600x20000) scales to (512, 17067) and
                # Pillow's WebP encoder raises ValueError("encoding error 5:
                # Image size exceeds WebP limit of 16383 pixels"). That is a
                # structurally impossible image, not a transient failure, so
                # it must land in SKIPPED, not FAILED -- the backfill retries
                # FAILED on every run, forever, for a source that can never
                # succeed.
                if height > _WEBP_MAX_DIMENSION:
                    continue
                # --- Rule 7: encode to a buffer first, discard if not smaller
                payload = _encode(img.resize((target, height), Image.LANCZOS))
                if len(payload) >= source_size:
                    # A lossless WebP can exceed a JPEG source. `break`, not
                    # `continue`: thumb runs before web, and rule 7's own
                    # monotonicity note (a 512px lossless WebP is never
                    # larger than the 896px one of the same source) means the
                    # web candidate would be discarded too. If that
                    # monotonicity is ever violated, `break`'s worst case is
                    # a missed `web` write (falls back to the original --
                    # a performance loss, never a wrong image); `continue`'s
                    # worst case is a `web`-without-`thumb` row, which
                    # violates the invariant the render path assumes is
                    # impossible.
                    break
                name = f"{stem}-{target}.webp"
                getattr(asset, field).save(name, ContentFile(payload), save=False)
                written.append(getattr(asset, field).name)

        asset.derivatives_state = (
            DerivativesState.OK if written else DerivativesState.SKIPPED
        )
        return asset.derivatives_state

    except Image.DecompressionBombError:
        # NOT one of the spec's enumerated rules -- added by review. Pillow
        # raises this at Image.open() above 2x MAX_IMAGE_PIXELS (~178.9 MP at
        # the default). Same category as rule 6's WebP dimension cap: a
        # structurally impossible image, not a transient failure. Left as
        # FAILED, the backfill would retry it every run, forever, paying the
        # full decode cost each time to fail identically.
        asset.derivatives_state = DerivativesState.SKIPPED
        return asset.derivatives_state

    except Exception:  # noqa: BLE001 - the contract is "never raises"
        # Broad, and around the storage writes too: FieldFile.save can raise
        # SuspiciousFileOperation, permission/quota errors, or backend-specific
        # exceptions that are not Pillow exceptions.
        logger.exception("derivative generation failed for asset %s", asset.pk)
        delete_derivative_files(written, storage)
        # Re-blank explicitly. Rule 0 ran BEFORE the writes, and
        # FieldFile.save ends by writing the name back onto the instance, so a
        # successful thumb write re-populated the field after rule 0 cleared it.
        asset.thumb = ""
        asset.web = ""
        # width/height too: rule 0 nulled them, but the assignment at rule 3 runs
        # BEFORE any storage write, so a failed row would otherwise persist
        # dimensions -- and "width populated with both derivatives blank" is
        # exactly the ambiguous shape derivatives_state exists to disambiguate.
        asset.width = None
        asset.height = None
        asset.derivatives_state = DerivativesState.FAILED
        return asset.derivatives_state
