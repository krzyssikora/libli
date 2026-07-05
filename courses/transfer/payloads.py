# courses/transfer/payloads.py (Task 6 stub — Task 7 replaces the body)
"""Per-type element `data` validation (§5 per-type invariants). Task 7."""

from django.utils.translation import gettext as _

from courses.transfer.schema import TransferError


def validate_element_data(el, media_kinds):
    """Validate el["data"] for el["type"]; return the set of referenced media ids.
    Task 6 stub: unknown types reject; known types minimally accepted."""
    known = {
        "text",
        "image",
        "video",
        "iframe",
        "math",
        "html",
        "choice",
        "short_text",
        "extended_response",
        "short_numeric",
        "fill_blank",
        "drag_fill_blank",
        "match_pair",
        "drag_to_image",
    }
    # isinstance guard BEFORE the set lookup: a hostile list/dict type value
    # would otherwise raise "unhashable type" → 500. Same guard stays in front
    # of Task 7's VALIDATORS dict dispatch.
    if not isinstance(el["type"], str) or el["type"] not in known:
        raise TransferError(
            _(
                "Unknown element type '%(v)s' — this archive may come from a newer "
                "application version."
            )
            % {"v": str(el["type"])[:40]}
        )
    data = el.get("data")
    if not isinstance(data, dict):
        raise TransferError(_("Element data must be an object."))
    media = data.get("media")
    return {media} if isinstance(media, str) else set()
