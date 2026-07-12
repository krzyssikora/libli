"""Per-type element `data` validation (§5 per-type invariants). Task 7.

Mirrors courses/transfer/export.py's serializers exactly: the shapes here are
the same contract, just read instead of written. Every rejection raises
TransferError (translated) — never a raw exception on hostile input.
"""

import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from courses.embed import extract_embed_url
from courses.fillblank import SENTINEL
from courses.models import DragZone
from courses.models import TableElement
from courses.switchgate import SENTINEL_TOKEN
from courses.transfer.schema import TransferError
from courses.transfer.schema import _exact_keys
from courses.transfer.schema import check_bool
from courses.transfer.schema import check_decimal_str
from courses.transfer.schema import check_float
from courses.transfer.schema import check_int_or_null
from courses.transfer.schema import check_list
from courses.transfer.schema import check_str
from courses.validators import validate_embed_url
from courses.video_url import canonicalize_video_url


def _err(msg, **kw):
    raise TransferError(msg % kw if kw else msg)


def _lines(blob):
    return [ln for ln in (blob or "").splitlines() if ln.strip()]


def _reject_embed(raw, elid):
    _err(
        _(
            "Element '%(el)s': the embed URL '%(url)s' is not accepted on this "
            "instance."
        ),
        el=elid,
        url=str(raw)[:200],
    )


def _canonical_embed(raw, elid, canonicalizer):
    try:
        url = canonicalizer(raw)
        validate_embed_url(url)
        return url
    except ValidationError:
        _reject_embed(raw, elid)


def _canonical_video_embed(raw, elid):
    """Validate a video embed URL exactly as VideoElement accepts it on save.

    Prefer canonicalization (normalizes a pasted `watch?v=` link to `/embed/…`),
    but fall back to `validate_embed_url` alone when the input can't be
    canonicalized yet is still an allow-listed https URL the model would store.
    Import must never be STRICTER than `VideoElement.clean()` (which runs only
    `validate_embed_url`), or a video URL the source instance legitimately holds
    fails to round-trip — e.g. a seeded `/embed/<non-standard-id>` whose id is
    not the 11 chars `canonicalize_video_url` demands.
    """
    try:
        url = canonicalize_video_url(raw)
        validate_embed_url(url)
        return url
    except ValidationError:
        pass
    try:
        validate_embed_url(raw)
        return raw
    except ValidationError:
        _reject_embed(raw, elid)


def _check_question_fields(data, elid):
    check_str(data["stem"], _("stem"))
    check_str(data["explanation"], _("explanation"))
    if data["marking_mode"] not in ("A", "N", "R"):
        _err(_("Element '%(el)s': unknown marking mode."), el=elid)
    check_int_or_null(data["max_attempts"], "max_attempts")
    d = check_decimal_str(data["max_marks"], "max_marks", 7, 2)
    if d < Decimal("0.01"):
        _err(_("Element '%(el)s': max_marks must be at least 0.01."), el=elid)


Q_KEYS = ["stem", "explanation", "marking_mode", "max_attempts", "max_marks"]


def _require_media(data_media, elid, media_kinds, want_kind):
    if not isinstance(data_media, str) or data_media not in media_kinds:
        _err(_("Element '%(el)s' references an unknown media id."), el=elid)
    if media_kinds[data_media] != want_kind:
        _err(_("Element '%(el)s' requires %(kind)s media."), el=elid, kind=want_kind)
    return {data_media}


_TOKEN_RE = re.compile(re.escape(SENTINEL) + r"(\d+)" + re.escape(SENTINEL))


def _check_token_stem(stem, n, elid):
    found = [int(m.group(1)) for m in _TOKEN_RE.finditer(stem)]
    if found != list(range(n)):  # exact 0..n-1, each once, ascending appearance
        _err(
            _("Element '%(v)s': the stem's blank tokens do not match its blank rows."),
            v=elid,
        )
    if SENTINEL in _TOKEN_RE.sub("", stem):
        _err(
            _("Element '%(v)s': the stem contains stray reserved characters."),
            v=elid,
        )


# --- per-type validators -----------------------------------------------------


def _val_text(data, elid, media_kinds):
    _exact_keys(data, ["body"], _("text data"))
    check_str(data["body"], _("body"))
    return set()


def _val_image(data, elid, media_kinds):
    _exact_keys(data, ["media", "alt", "figcaption"], _("image data"))
    refs = _require_media(data["media"], elid, media_kinds, "image")
    check_str(data["alt"], "alt", max_length=255)
    check_str(data["figcaption"], "figcaption", max_length=255)
    return refs


def _val_video(data, elid, media_kinds):
    _exact_keys(data, ["url", "media"], _("video data"))
    has_url = data["url"] is not None
    has_media = data["media"] is not None
    if has_url == has_media:
        _err(_("Element '%(el)s': provide exactly one of url or media."), el=elid)
    if has_url:
        check_str(data["url"], "url", required=True)
        data["url"] = _canonical_video_embed(data["url"], elid)
        return set()
    return _require_media(data["media"], elid, media_kinds, "video")


def _val_iframe(data, elid, media_kinds):
    # width/height are optional (added in FORMAT_VERSION 2). setdefault first so a
    # legacy v1 archive (which has neither) gains them and passes the exact-keys
    # check, and so downstream _build_iframe never KeyErrors.
    data.setdefault("width", None)
    data.setdefault("height", None)
    _exact_keys(data, ["url", "title", "width", "height"], _("iframe data"))
    check_str(data["url"], "url", required=True)
    check_str(data["title"], "title", max_length=255)
    check_int_or_null(data["width"], "width")
    check_int_or_null(data["height"], "height")
    data["url"] = _canonical_embed(data["url"], elid, extract_embed_url)
    return set()


def _val_math(data, elid, media_kinds):
    _exact_keys(data, ["latex"], _("math data"))
    check_str(data["latex"], _("latex"), required=True)
    return set()


def _val_html(data, elid, media_kinds):
    _exact_keys(data, ["html"], _("html data"))
    check_str(data["html"], _("html"))
    return set()


def _val_slide_break(data, elid, media_kinds):
    return set()


def _val_reveal_gate(data, elid, media_kinds):
    return set()


def _val_fill_gate(data, elid, media_kinds):
    stem = data.get("stem", "")
    answers = data.get("answers", [])
    if (
        not isinstance(stem, str)
        or not isinstance(answers, list)
        or not all(
            isinstance(alt, list) and all(isinstance(x, str) for x in alt)
            for alt in answers
        )
    ):
        _err(_("Element '%(el)s': malformed fill-gate payload."), el=elid)
    return set()  # no media refs


def _val_switch_gate(data, elid, media_kinds):
    stem = data.get("stem", "")
    options = data.get("options", [])
    answer = data.get("answer", None)
    if not isinstance(stem, str) or stem.count(SENTINEL_TOKEN) != 1:
        _err(
            _("Element '%(el)s': switch_gate stem must have exactly one choice token."),
            el=elid,
        )
    if (
        not isinstance(options, list)
        or len(options) < 2
        or not all(isinstance(o, str) for o in options)
    ):
        _err(
            _("Element '%(el)s': switch_gate needs at least two string options."),
            el=elid,
        )
    elif (
        not isinstance(answer, int)
        or isinstance(answer, bool)
        or not (0 <= answer < len(options))
    ):
        _err(
            _("Element '%(el)s': switch_gate answer must be an index within options."),
            el=elid,
        )
    return set()


def _val_choice(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["multiple", "choices"], _("choice data"))
    _check_question_fields(data, elid)
    check_bool(data["multiple"], "multiple")
    choices = check_list(data["choices"], "choices")
    if len(choices) < 2:
        _err(
            _("Element '%(el)s': a choice question needs at least two choices."),
            el=elid,
        )
    n_correct = 0
    for c in choices:
        _exact_keys(c, ["text", "is_correct"], _("choice"))
        check_str(c["text"], _("choice text"), max_length=500, required=True)
        check_bool(c["is_correct"], "is_correct")
        n_correct += c["is_correct"]
    if n_correct < 1:
        _err(_("Element '%(el)s': at least one choice must be correct."), el=elid)
    if not data["multiple"] and n_correct != 1:
        _err(
            _(
                "Element '%(el)s': a single-choice question needs exactly one "
                "correct choice."
            ),
            el=elid,
        )
    return set()


def _val_short_text(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["accepted", "case_sensitive"], _("short_text data"))
    _check_question_fields(data, elid)
    check_str(data["accepted"], "accepted")
    if not _lines(data["accepted"]):
        _err(
            _("Element '%(el)s': accepted answers must have at least one line."),
            el=elid,
        )
    check_bool(data["case_sensitive"], "case_sensitive")
    return set()


def _val_extended_response(data, elid, media_kinds):
    _exact_keys(
        data,
        Q_KEYS + ["required_keywords", "forbidden_keywords"],
        _("extended_response data"),
    )
    _check_question_fields(data, elid)
    check_str(data["required_keywords"], "required_keywords")
    check_str(data["forbidden_keywords"], "forbidden_keywords")
    if data["marking_mode"] == "A" and not (
        _lines(data["required_keywords"]) or _lines(data["forbidden_keywords"])
    ):
        _err(
            _(
                "Element '%(el)s': automatic marking needs at least one required "
                "or forbidden keyword."
            ),
            el=elid,
        )
    return set()


def _val_short_numeric(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["value", "tolerance"], _("short_numeric data"))
    _check_question_fields(data, elid)
    check_decimal_str(data["value"], "value", 20, 8)
    tolerance = check_decimal_str(data["tolerance"], "tolerance", 20, 8)
    if tolerance < 0:
        _err(_("Element '%(el)s': tolerance must not be negative."), el=elid)
    return set()


def _val_fill_blank(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["blanks"], _("fill_blank data"))
    _check_question_fields(data, elid)
    blanks = check_list(data["blanks"], "blanks")
    if not blanks:
        _err(_("Element '%(el)s': at least one blank is required."), el=elid)
    for b in blanks:
        _exact_keys(b, ["accepted", "case_sensitive"], _("blank"))
        check_str(b["accepted"], "accepted")
        if not _lines(b["accepted"]):
            _err(
                _(
                    "Element '%(el)s': a blank's accepted answers must have at "
                    "least one line."
                ),
                el=elid,
            )
        check_bool(b["case_sensitive"], "case_sensitive")
    _check_token_stem(data["stem"], len(blanks), elid)
    return set()


def _val_drag_fill_blank(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["distractors", "blanks"], _("drag_fill_blank data"))
    _check_question_fields(data, elid)
    check_str(data["distractors"], "distractors")
    blanks = check_list(data["blanks"], "blanks")
    if not blanks:
        _err(_("Element '%(el)s': at least one blank is required."), el=elid)
    for b in blanks:
        _exact_keys(b, ["correct_token"], _("blank"))
        check_str(b["correct_token"], _("correct token"), max_length=500, required=True)
    _check_token_stem(data["stem"], len(blanks), elid)
    return set()


def _val_match_pair(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["distractors", "pairs"], _("match_pair data"))
    _check_question_fields(data, elid)
    check_str(data["distractors"], "distractors")
    pairs = check_list(data["pairs"], "pairs")
    if not pairs:
        _err(_("Element '%(el)s': at least one pair is required."), el=elid)
    for p in pairs:
        _exact_keys(p, ["left", "right"], _("pair"))
        check_str(p["left"], _("pair left"), max_length=500, required=True)
        check_str(p["right"], _("pair right"), max_length=500, required=True)
    return set()


def _val_drag_to_image(data, elid, media_kinds):
    _exact_keys(
        data,
        Q_KEYS + ["media", "alt", "distractors", "zones"],
        _("drag_to_image data"),
    )
    _check_question_fields(data, elid)
    refs = _require_media(data["media"], elid, media_kinds, "image")
    check_str(data["alt"], "alt", max_length=255)
    check_str(data["distractors"], "distractors")
    zones = check_list(data["zones"], "zones")
    if not zones:
        _err(_("Element '%(el)s': at least one zone is required."), el=elid)
    for z in zones:
        _exact_keys(z, ["correct_label", "x", "y", "w", "h"], _("zone"))
        check_str(z["correct_label"], _("zone label"), max_length=500, required=True)
        probe = DragZone(
            correct_label=z["correct_label"],
            x=check_float(z["x"], "x"),
            y=check_float(z["y"], "y"),
            w=check_float(z["w"], "w"),
            h=check_float(z["h"], "h"),
        )
        try:
            probe.clean()  # the exact model mirror incl. ZONE_COORD_EPSILON
        except ValidationError as exc:
            _err(
                _("Element '%(el)s': %(detail)s"),
                el=elid,
                detail="; ".join(exc.messages),
            )
    return refs


def _val_gallery(data, elid, media_kinds):
    from courses.models import GalleryElement

    _exact_keys(data, ["desc_pos", "images"], _("gallery data"))
    if (
        data["desc_pos"] not in GalleryElement.CAPTION_POSITIONS
    ):  # single source of truth
        _err(_("Element '%(el)s' has an invalid gallery position."), el=elid)
    if not isinstance(data["images"], list):
        _err(_("Element '%(el)s' has malformed gallery images."), el=elid)
    refs = set()
    for img in data["images"]:
        if not isinstance(img, dict):
            _err(_("Element '%(el)s' has a malformed gallery image."), el=elid)
        _exact_keys(img, ["media", "desc"], _("gallery image"))
        refs |= _require_media(img["media"], elid, media_kinds, "image")
        check_str(img["desc"], "desc", max_length=100000)
    return refs  # shape-only; 2-20 bound is NOT re-enforced on import (see spec)


def _val_table(data, elid, media_kinds):
    # `data` is the table dict DIRECTLY (header_row/header_col/border/cells),
    # matching _ser_table's un-wrapped return and _build_table's call shape.
    _exact_keys(data, ["header_row", "header_col", "border", "cells"], _("table data"))
    check_bool(data["header_row"], "header_row")
    check_bool(data["header_col"], "header_col")
    if data["border"] not in TableElement.BORDERS:
        _err(_("Element '%(el)s': unknown table border style."), el=elid)
    rows = check_list(data["cells"], "cells")
    if len(rows) > TableElement.MAX_ROWS:
        _err(
            _("Element '%(el)s': a table may have at most %(n)d rows."),
            el=elid,
            n=TableElement.MAX_ROWS,
        )
    widths = set()
    for row in rows:
        cells = check_list(row, "cells row")
        widths.add(len(cells))
    if not rows or widths == {0}:
        _err(_("Element '%(el)s': a table needs at least one cell."), el=elid)
    if len(widths) != 1:
        _err(
            _("Element '%(el)s': all table rows must have the same number of cells."),
            el=elid,
        )
    n_cols = next(iter(widths))
    if n_cols > TableElement.MAX_COLS:
        _err(
            _("Element '%(el)s': a table may have at most %(n)d columns."),
            el=elid,
            n=TableElement.MAX_COLS,
        )
    for row in rows:
        for cell in row:
            _exact_keys(cell, ["html", "halign", "valign"], _("table cell"))
            check_str(cell["html"], "cell html")
            if cell["halign"] not in TableElement.HALIGN:
                _err(_("Element '%(el)s': unknown cell horizontal alignment."), el=elid)
            if cell["valign"] not in TableElement.VALIGN:
                _err(_("Element '%(el)s': unknown cell vertical alignment."), el=elid)
    return set()


def _val_tabs(data, elid, media_kinds):
    from courses.models import TabsElement

    _exact_keys(data, ["tabs"], _("tabs data"))
    tabs = data["tabs"]
    if not isinstance(tabs, list):
        _err(_("Element '%(el)s' has malformed tabs."), el=elid)
    if not (TabsElement.MIN_TABS <= len(tabs) <= TabsElement.MAX_TABS):
        # REJECT rather than repair: this is what keeps normalize_data's destructive
        # padding/truncation from ever firing on imported data, so a child's `tab` ref
        # can never be validated against a different tab list than the one imported.
        _err(_("Element '%(el)s' has an invalid number of tabs."), el=elid)
    seen = set()
    for tab in tabs:
        if not isinstance(tab, dict):
            _err(_("Element '%(el)s' has a malformed tab."), el=elid)
        _exact_keys(tab, ["id", "label"], _("tab"))
        tid = tab["id"]
        if not isinstance(tid, str) or not TabsElement.TAB_ID_RE.fullmatch(tid):
            _err(_("Element '%(el)s' has a malformed tab id."), el=elid)
        if tid in seen:
            # Duplicates would be regenerated by save()'s normalizer, orphaning the
            # child that referenced the later one. Reject instead.
            _err(_("Element '%(el)s' has duplicate tab ids."), el=elid)
        seen.add(tid)
        check_str(tab["label"], "label", max_length=TabsElement.LABEL_MAX)
    return set()  # a tabs element references no media


def validate_nesting(elements):
    """Cross-element checks the per-element validators cannot see. Rejects (never
    repairs) an unknown/ill-typed parent, an unknown tab, a non-nestable child, and a
    parent chain deeper than one level -- that depth bound is what lets the editor's
    recursive row template terminate without a guard."""
    from courses.builder import NESTABLE_TYPE_KEYS

    # Step 4a applies the v2 shim before _exact_keys, so both keys are present.
    by_id = {el["id"]: el for el in elements}
    for el in elements:
        parent_ref = el["parent"]
        if parent_ref is None:
            continue
        parent = by_id.get(parent_ref)
        if parent is None:
            _err(_("Element '%(el)s' references an unknown parent."), el=el["id"])
        if parent["type"] != "tabs":
            _err(
                _("Element '%(el)s' has a parent that is not a tabs element."),
                el=el["id"],
            )
        if parent["parent"] is not None:
            _err(_("Element '%(el)s' is nested more than one level deep."), el=el["id"])
        if el["tab"] not in {t["id"] for t in parent["data"]["tabs"]}:
            _err(
                _("Element '%(el)s' references a tab its parent does not have."),
                el=el["id"],
            )
        if el["type"] not in NESTABLE_TYPE_KEYS:
            _err(
                _("Element '%(el)s' may not be nested inside a tabs element."),
                el=el["id"],
            )


VALIDATORS = {
    "text": _val_text,
    "image": _val_image,
    "video": _val_video,
    "iframe": _val_iframe,
    "math": _val_math,
    "html": _val_html,
    "slide_break": _val_slide_break,
    "reveal_gate": _val_reveal_gate,
    "fill_gate": _val_fill_gate,
    "switch_gate": _val_switch_gate,
    "choice": _val_choice,
    "short_text": _val_short_text,
    "extended_response": _val_extended_response,
    "short_numeric": _val_short_numeric,
    "fill_blank": _val_fill_blank,
    "drag_fill_blank": _val_drag_fill_blank,
    "match_pair": _val_match_pair,
    "drag_to_image": _val_drag_to_image,
    "table": _val_table,
    "gallery": _val_gallery,
    "tabs": _val_tabs,
}


def validate_element_data(el, media_kinds):
    """Validate el["data"] for el["type"]; return the set of referenced media ids.

    Mutates el["data"] to store canonicalized embed URLs (video/iframe) so that
    commit persists exactly what was checked.
    """
    # isinstance guard BEFORE the dict lookup: a hostile list/dict type value
    # would otherwise raise "unhashable type" -> 500.
    if not isinstance(el["type"], str) or el["type"] not in VALIDATORS:
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
    return VALIDATORS[el["type"]](data, el["id"], media_kinds)
