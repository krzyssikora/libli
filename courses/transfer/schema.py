"""Course transfer archive format: constants, error type, document validation.

Format spec: docs/superpowers/specs/2026-07-05-course-export-import-design.md §2/§5.
"""

import math

from django.conf import settings
from django.utils.translation import gettext as _

from courses.color_bands import is_valid_stored
from courses.constants import COURSE_LANGUAGES

FORMAT_VERSION = 5
KIND_COURSE = "course"
KIND_SUBTREE = "subtree"


class TransferError(Exception):
    """Any export/import rejection. `message` is user-facing and translated."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def _err(msg, **kw):
    raise TransferError(msg % kw if kw else msg)


def check_str(value, what, *, max_length=None, required=False):
    if not isinstance(value, str):
        _err(_("%(what)s must be text."), what=what)
    if required and not value.strip():
        _err(_("%(what)s must not be blank."), what=what)
    if max_length is not None and len(value) > max_length:
        _err(_("%(what)s is longer than %(n)d characters."), what=what, n=max_length)
    return value


def check_bool(value, what):
    if not isinstance(value, bool):
        _err(_("%(what)s must be true or false."), what=what)
    return value


def check_int_or_null(value, what):
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _err(_("%(what)s must be a non-negative integer or null."), what=what)
    return value


def check_decimal_str(value, what, max_digits, decimal_places):
    from decimal import Decimal
    from decimal import InvalidOperation

    if not isinstance(value, str):
        _err(_("%(what)s must be a decimal string."), what=what)
    try:
        d = Decimal(value)
    except InvalidOperation:
        _err(_("%(what)s is not a valid decimal number."), what=what)
    # Finite check MUST precede as_tuple() arithmetic: Decimal("Infinity")
    # has exponent "F" (NaN: "n"), so `-exponent` would TypeError → 500.
    if not d.is_finite():
        _err(_("%(what)s is not a valid decimal number."), what=what)
    exponent = -d.as_tuple().exponent
    digits = len(d.as_tuple().digits)
    if exponent > decimal_places or digits - exponent > max_digits - decimal_places:
        _err(_("%(what)s has too many digits."), what=what)
    return d


def check_float(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _err(_("%(what)s must be a number."), what=what)
    # An arbitrary-precision JSON int (no size cap in json.loads) can overflow
    # float(); NaN/Infinity also parse as JSON floats by default. Both must
    # reject via TransferError, never raise OverflowError -> 500.
    try:
        result = float(value)
    except OverflowError:
        _err(_("%(what)s is not a valid number."), what=what)
    if not math.isfinite(result):
        _err(_("%(what)s is not a valid number."), what=what)
    return result


def check_list(value, what):
    if not isinstance(value, list):
        _err(_("%(what)s must be a list."), what=what)
    return value


def _exact_keys(obj, keys, what):
    if not isinstance(obj, dict):
        _err(_("%(what)s must be an object."), what=what)
    for k in keys:
        if k not in obj:
            _err(_("%(what)s is missing the key '%(key)s'."), what=what, key=k)
    for k in obj:
        if k not in keys:
            _err(_("%(what)s contains an unknown key '%(key)s'."), what=what, key=k)


def validate_document(doc, *, kind, target_allowed_kinds=None):
    from courses.models import ContentNode
    from courses.ordering import kinds_for_flags
    from courses.transfer.payloads import validate_element_data  # Task 7

    is_course = kind == KIND_COURSE
    _exact_keys(
        doc,
        (["course"] if is_course else ["context"]) + ["nodes", "elements", "media"],
        "course.json",
    )
    nodes = check_list(doc["nodes"], "nodes")
    elements = check_list(doc["elements"], "elements")
    media = check_list(doc["media"], "media")

    if is_course:
        c = doc["course"]
        _exact_keys(
            c,
            [
                "title",
                "language",
                "overview",
                "html_css",
                "html_js",
                "uses_parts",
                "uses_chapters",
                "uses_sections",
                "color_bands",
                "subjects",
            ],
            "course",
        )
        check_str(c["title"], _("course title"), max_length=200, required=True)
        # isinstance guards before EVERY dict-membership test: a hostile list/
        # dict value would otherwise raise "unhashable type" → 500.
        if not isinstance(c["language"], str) or c["language"] not in dict(
            COURSE_LANGUAGES
        ):
            _err(_("Unknown course language '%(v)s'."), v=str(c["language"])[:20])
        for f in ("overview", "html_css", "html_js"):
            check_str(c[f], f)
        for f in ("uses_parts", "uses_chapters", "uses_sections"):
            check_bool(c[f], f)
        bands = check_list(c["color_bands"], "color_bands")
        if bands and not is_valid_stored(bands):
            _err(_("color_bands does not match the expected shape."))
        for s in check_list(c["subjects"], "subjects"):
            _exact_keys(s, ["title_en", "title_pl"], "subject")
            check_str(s["title_en"], "title_en", max_length=200)
            check_str(s["title_pl"], "title_pl", max_length=200)
        allowed = kinds_for_flags(
            c["uses_parts"], c["uses_chapters"], c["uses_sections"]
        )
    else:
        ctx = doc["context"]
        _exact_keys(
            ctx,
            [
                "source_course_title",
                "root_kind",
                "required_kinds",
                "html_css",
                "html_js",
            ],
            "context",
        )
        check_str(ctx["source_course_title"], "source_course_title")
        if not isinstance(ctx["root_kind"], str) or (
            ctx["root_kind"] not in ContentNode.RANK
        ):
            _err(_("Unknown root kind '%(v)s'."), v=str(ctx["root_kind"])[:20])
        check_list(ctx["required_kinds"], "required_kinds")  # informational only
        check_str(ctx["html_css"], "html_css")
        check_str(ctx["html_js"], "html_js")
        allowed = list(target_allowed_kinds or [])

    if len(nodes) > settings.TRANSFER_MAX_NODES:
        _err(_("Too many nodes (limit %(n)d)."), n=settings.TRANSFER_MAX_NODES)
    if len(elements) > settings.TRANSFER_MAX_ELEMENTS:
        _err(_("Too many elements (limit %(n)d)."), n=settings.TRANSFER_MAX_ELEMENTS)
    if len(media) > settings.TRANSFER_MAX_MEDIA_ENTRIES:
        _err(
            _("Too many media entries (limit %(n)d)."),
            n=settings.TRANSFER_MAX_MEDIA_ENTRIES,
        )

    seen_ids = set()

    def _claim_id(v, what):
        check_str(v, what, required=True)
        if v in seen_ids:
            _err(_("Duplicate internal id '%(v)s'."), v=v)
        seen_ids.add(v)

    node_kind = {}
    roots = 0
    for nd in nodes:
        _exact_keys(
            nd,
            [
                "id",
                "parent",
                "kind",
                "title",
                "unit_type",
                "obligatory",
                "html_seed_js",
            ],
            _("node"),
        )
        _claim_id(nd["id"], _("node id"))
        if not isinstance(nd["kind"], str) or nd["kind"] not in ContentNode.RANK:
            _err(_("Unknown node kind '%(v)s'."), v=str(nd["kind"])[:20])
        if nd["kind"] not in allowed:
            _err(
                _(
                    "The archive contains a '%(kind)s' node, which this structure "
                    "does not allow."
                ),
                kind=nd["kind"],
            )
        check_str(nd["title"], _("node title"), max_length=200, required=True)
        check_bool(nd["obligatory"], "obligatory")
        check_str(nd["html_seed_js"], "html_seed_js")
        if nd["kind"] == "unit":
            if nd["unit_type"] not in ("lesson", "quiz"):
                _err(_("A unit's unit_type must be 'lesson' or 'quiz'."))
        elif nd["unit_type"] is not None:
            _err(_("Only units may have a unit_type."))
        if nd["parent"] is None:
            roots += 1
        else:
            if not isinstance(nd["parent"], str) or nd["parent"] not in node_kind:
                _err(
                    _("Node parent '%(v)s' does not refer to an earlier node."),
                    v=str(nd["parent"])[:50],
                )
            if (
                ContentNode.RANK[node_kind[nd["parent"]]]
                >= ContentNode.RANK[nd["kind"]]
            ):
                _err(_("A node's kind must be strictly deeper than its parent's."))
        node_kind[nd["id"]] = nd["kind"]

    if not is_course:
        if roots != 1:
            _err(_("A subtree archive must contain exactly one root node."))
        if nodes and nodes[0]["parent"] is None:
            if nodes[0]["kind"] != doc["context"]["root_kind"]:
                _err(_("The subtree root does not match the declared root kind."))

    media_kinds = {}
    file_names = set()
    for m in media:
        _exact_keys(
            m, ["id", "kind", "name", "original_filename", "file"], _("media entry")
        )
        _claim_id(m["id"], _("media id"))
        if m["kind"] not in ("image", "video"):
            _err(_("Unknown media kind '%(v)s'."), v=str(m["kind"])[:20])
        check_str(m["name"], "name", max_length=255)
        check_str(
            m["original_filename"], "original_filename", max_length=255, required=True
        )
        check_str(m["file"], "file", required=True)
        if not m["file"].startswith("media/"):
            _err(_("Media file locator must live under media/."))
        if m["file"] in file_names:
            _err(_("Two media entries share the file %(v)s."), v=m["file"])
        file_names.add(m["file"])
        media_kinds[m["id"]] = m["kind"]

    referenced_media = set()
    for el in elements:
        # `parent`/`tab` are the format-3 nesting refs (tabs element children).
        # v2 archives carry neither key; v3 carries both. setdefault first so a legacy
        # archive gains them and passes the exact-keys check, and so downstream code
        # (validate_nesting, the two-pass importer) never KeyErrors. Same shape as the
        # v1->v2 iframe width/height shim.
        if isinstance(el, dict):
            el.setdefault("parent", None)
            el.setdefault("tab", "")
        _exact_keys(
            el, ["id", "unit", "title", "type", "data", "parent", "tab"], _("element")
        )
        _claim_id(el["id"], _("element id"))
        check_str(el["title"], _("element title"), max_length=200)
        if (
            not isinstance(el["unit"], str)
            or el["unit"] not in node_kind
            or node_kind[el["unit"]] != "unit"
        ):
            _err(_("Element '%(v)s' must belong to a unit node."), v=el["id"])
        refs = validate_element_data(el, media_kinds)  # Task 7; returns media ids used
        referenced_media |= refs

    # Cross-element nesting refs (parent/tab). Runs AFTER the per-element loop so
    # every tabs element's data["tabs"] is already shape-checked. Imported locally
    # to avoid the payloads<->schema module-level circular import (payloads.py does
    # `from courses.transfer.schema import check_str` at module level).
    from courses.transfer.payloads import validate_nesting

    validate_nesting(elements)

    for m in media:
        if m["id"] not in referenced_media:
            _err(_("Media entry '%(v)s' is not referenced by any element."), v=m["id"])
