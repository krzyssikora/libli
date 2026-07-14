"""Export: serialize a course/subtree content graph to the archive format (§2)."""

import json
import os
import zipfile

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from courses.models import CalloutElement
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import FillGateElement
from courses.models import FillTableElement
from courses.models import GalleryElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import RevealGateElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SlideBreakElement
from courses.models import SpoilerElement
from courses.models import SwitchGateElement
from courses.models import SwitchGridElement
from courses.models import TableElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import VideoElement
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import KIND_COURSE
from courses.transfer.schema import KIND_SUBTREE
from courses.transfer.schema import TransferError


class MediaIdMap:
    """Stable asset-pk -> internal id ("m1", "m2", …) in first-reference order."""

    def __init__(self):
        self._by_pk = {}
        self._assets = []

    def register(self, asset):
        if asset.pk not in self._by_pk:
            self._by_pk[asset.pk] = f"m{len(self._assets) + 1}"
            self._assets.append(asset)
        return self._by_pk[asset.pk]

    def items(self):
        return [(self._by_pk[a.pk], a) for a in self._assets]


def _question_fields(q):
    return {
        "stem": q.stem,
        "explanation": q.explanation,
        "marking_mode": q.marking_mode,
        "max_attempts": q.max_attempts,
        "max_marks": str(q.max_marks),
    }


def _ser_text(el, ids):
    return {"body": el.body}


def _ser_image(el, ids):
    return {"media": ids.register(el.media), "alt": el.alt, "figcaption": el.figcaption}


def _ser_video(el, ids):
    if el.media_id is not None:
        return {"url": None, "media": ids.register(el.media)}
    return {"url": el.url, "media": None}


def _ser_iframe(el, ids):
    return {"url": el.url, "title": el.title, "width": el.width, "height": el.height}


def _ser_math(el, ids):
    return {"latex": el.latex}


def _ser_html(el, ids):
    return {"html": el.html}


def _ser_slide_break(concrete, media_ids):
    return {}


def _ser_reveal_gate(concrete, media_ids):
    return {"label": concrete.label}


def _ser_spoiler(concrete, media_ids):
    return {"label": concrete.label, "body": concrete.body}


def _ser_callout(concrete, media_ids):
    return {
        "kind": concrete.kind,
        "heading": concrete.heading,
        "body": concrete.body,
    }


def _ser_fill_gate(concrete, media_ids):
    return {"stem": concrete.stem, "answers": concrete.answers}


def _ser_switch_gate(
    concrete, media_ids
):  # real serializers take (concrete, media_ids)
    return {
        "stem": concrete.stem,
        "options": concrete.options,
        "answer": concrete.answer,
    }


def _ser_switch_grid(concrete, media_ids):
    return {"prompt": concrete.prompt, "lines": concrete.lines}


def _ser_table(el, ids):
    # Return the table dict DIRECTLY (not {"data": el.data}). Every serializer
    # returns the type-specific fields that BECOME the element's `data` block
    # (e.g. _ser_text -> {"body": ...}); the importer calls
    # BUILDERS["table"](el["data"], assets). Wrapping in another {"data": ...}
    # would double-wrap, so _build_table's normalize_data would find no "cells"
    # and silently fall back to the default 2x2, discarding imported content.
    return dict(el.data)


def _ser_fill_table(el, ids):
    # Return the data dict DIRECTLY, mirroring _ser_table (see its comment): the
    # importer calls BUILDERS["fill_table"](el["data"], assets) with this shape.
    return dict(el.data)


def _ser_tabs(el, ids):
    # Labels + stable ids only. The children are separate elements carrying `parent`
    # and `tab` refs; a tabs element itself references no media. Use the
    # NON-DESTRUCTIVE normalizer (mirrors save()): never pad/truncate the tab list,
    # so the serialized `tabs` is always a superset of the tabs resolved_tabs() walks,
    # and every emitted child's `tab` ref is present in this list.
    return {"tabs": [dict(t) for t in el.normalize_labels_and_ids(el.data)["tabs"]]}


def _ser_choice(el, ids):
    return {
        **_question_fields(el),
        "multiple": el.multiple,
        "choices": [
            {"text": c.text, "is_correct": c.is_correct, "feedback": c.feedback}
            for c in el.choices.all()
        ],
    }


def _ser_short_text(el, ids):
    return {
        **_question_fields(el),
        "accepted": el.accepted,
        "case_sensitive": el.case_sensitive,
    }


def _ser_extended(el, ids):
    return {
        **_question_fields(el),
        "required_keywords": el.required_keywords,
        "forbidden_keywords": el.forbidden_keywords,
    }


def _ser_numeric(el, ids):
    return {
        **_question_fields(el),
        "value": str(el.value),
        "tolerance": str(el.tolerance),
    }


def _ser_fill_blank(el, ids):
    return {
        **_question_fields(el),
        "blanks": [
            {"accepted": b.accepted, "case_sensitive": b.case_sensitive}
            for b in el.blanks.all()
        ],
    }


def _ser_drag_fill(el, ids):
    return {
        **_question_fields(el),
        "distractors": el.distractors,
        "blanks": [{"correct_token": b.correct_token} for b in el.dragblanks.all()],
    }


def _ser_match_pair(el, ids):
    return {
        **_question_fields(el),
        "distractors": el.distractors,
        "pairs": [{"left": p.left, "right": p.right} for p in el.pairs.all()],
    }


def _ser_choice_grid(el, ids):
    cols = list(el.columns.all())
    index = {c.pk: i for i, c in enumerate(cols)}
    return {
        **_question_fields(el),
        "columns": [{"label": c.label} for c in cols],
        "rows": [
            {"statement": r.statement, "correct": index[r.correct_column_id]}
            for r in el.rows.all()
        ],
    }


def _ser_gallery(el, ids):
    norm = el.normalize_data(el.data)
    return {
        "desc_pos": norm["desc_pos"],
        "images": [
            {"media": ids.register(_ma), "desc": img["desc"]}
            for img, _ma in _gallery_assets(el, norm)
        ],
    }


def _gallery_assets(el, norm):
    """Yield (image_dict, MediaAsset) for resolvable ids, in order. Unresolved
    ids are skipped (they cannot be exported)."""
    from courses.models import MediaAsset

    ids = [img["media"] for img in norm["images"]]
    assets = MediaAsset.objects.in_bulk(ids)
    for img in norm["images"]:
        a = assets.get(img["media"])
        if a is not None:
            yield img, a


def _ser_drag_to_image(el, ids):
    return {
        **_question_fields(el),
        "media": ids.register(el.media),
        "alt": el.alt,
        "distractors": el.distractors,
        "zones": [
            {"correct_label": z.correct_label, "x": z.x, "y": z.y, "w": z.w, "h": z.h}
            for z in el.zones.all()
        ],
    }


# type_key -> (model, serializer). The 18-entry registry (incl. "slide_break",
# "table", "gallery", "reveal_gate"); the importer-side registries in payloads.py
# (VALIDATORS) and importer.py (BUILDERS) mirror these keys — keep all three in
# lockstep.
SERIALIZERS = {
    "text": (TextElement, _ser_text),
    "image": (ImageElement, _ser_image),
    "video": (VideoElement, _ser_video),
    "iframe": (IframeElement, _ser_iframe),
    "math": (MathElement, _ser_math),
    "html": (HtmlElement, _ser_html),
    "slide_break": (SlideBreakElement, _ser_slide_break),
    "reveal_gate": (RevealGateElement, _ser_reveal_gate),
    "spoiler": (SpoilerElement, _ser_spoiler),
    "callout": (CalloutElement, _ser_callout),
    "fill_gate": (FillGateElement, _ser_fill_gate),
    "switch_gate": (SwitchGateElement, _ser_switch_gate),
    "switch_grid": (SwitchGridElement, _ser_switch_grid),
    "choice": (ChoiceQuestionElement, _ser_choice),
    "short_text": (ShortTextQuestionElement, _ser_short_text),
    "extended_response": (ExtendedResponseQuestionElement, _ser_extended),
    "short_numeric": (ShortNumericQuestionElement, _ser_numeric),
    "fill_blank": (FillBlankQuestionElement, _ser_fill_blank),
    "drag_fill_blank": (DragFillBlankQuestionElement, _ser_drag_fill),
    "match_pair": (MatchPairQuestionElement, _ser_match_pair),
    "choice_grid": (ChoiceGridQuestionElement, _ser_choice_grid),
    "drag_to_image": (DragToImageQuestionElement, _ser_drag_to_image),
    "table": (TableElement, _ser_table),
    "fill_table": (FillTableElement, _ser_fill_table),
    "gallery": (GalleryElement, _ser_gallery),
    "tabs": (TabsElement, _ser_tabs),
}

_MODEL_TO_KEY = {model: key for key, (model, _fn) in SERIALIZERS.items()}


def serialize_element_data(concrete, media_ids):
    key = _MODEL_TO_KEY.get(type(concrete))
    if key is None:  # pragma: no cover — every ElementBase subclass is registered
        raise TransferError(f"Unserializable element model: {type(concrete).__name__}")
    _model, fn = SERIALIZERS[key]
    return key, fn(concrete, media_ids)


def _element_mids(type_key, data):
    """All media ids an element references, routed by the element TYPE KEY (not
    by sniffing the data shape): a gallery reads its `images[].media` list; every
    other media-bearing type reads the scalar `media`."""
    if type_key == "gallery":
        return [
            img["media"]
            for img in (data.get("images") or [])
            if isinstance(img, dict) and isinstance(img.get("media"), str)
        ]
    m = data.get("media")
    return [m] if isinstance(m, str) else []


def _ordered_nodes(course, root=None):
    """Snapshot the whole node list in one query, then walk depth-first in
    (order, pk) sibling order. Parent always precedes child (format invariant)."""
    cmap = {}
    for n in course.nodes.all().order_by("order", "pk"):
        cmap.setdefault(n.parent_id, []).append(n)
    out = []

    def walk(pid):
        for n in cmap.get(pid, []):
            out.append(n)
            walk(n.pk)

    if root is None:
        walk(None)
    else:
        out.append(root)
        walk(root.pk)
    return out


def _node_dict(node, nid, parent_internal):
    return {
        "id": nid,
        "parent": parent_internal,
        "kind": node.kind,
        "title": node.title,
        # `or None`: admin-saved non-unit rows can hold "" (CharField, clean()
        # only rejects truthy values) — keep the archive canonical (null) so a
        # legitimately exported course survives the strict null-only import rule.
        "unit_type": node.unit_type or None,
        "obligatory": node.obligatory,
        "html_seed_js": node.html_seed_js,
    }


def walk_unit_joins(unit_pk, joins_by_unit):
    """Yield (join, parent_join_or_None, tab_id) for one unit, parents before
    children, each element EXACTLY ONCE. `joins_by_unit` holds only top-level joins
    (parent__isnull=True); a tabs element's children are expanded inline here via
    resolved_tabs(), so they arrive in their within-tab `order` -- which is what
    makes the import's payload-order pass reproduce that order without serializing
    `order` itself.

    Children are reached ONLY through resolved_tabs(): a child whose tab_id matches
    no tab (reachable only via a direct DB edit or a read-side truncation) is
    deliberately OMITTED from the archive. Exporting one would produce a payload
    whose `tab` ref fails the import validator, so the archive could never be
    re-imported. Do NOT "fix" this by iterating join.children.all() directly.
    """
    for join in joins_by_unit.get(unit_pk, []):
        yield join, None, ""
        obj = join.content_object
        if isinstance(obj, TabsElement):
            for tab, children in obj.resolved_tabs():
                for child in children:
                    yield child, join, tab["id"]


def build_export(course, node=None, source_host=""):
    with transaction.atomic():
        nodes = _ordered_nodes(course, root=node)
        node_ids = {}
        node_dicts = []
        for i, n in enumerate(nodes, start=1):
            nid = f"n{i}"
            node_ids[n.pk] = nid
            parent_internal = (
                None
                if (node is not None and n.pk == node.pk)
                else node_ids.get(n.parent_id)
            )
            node_dicts.append(_node_dict(n, nid, parent_internal))

        media_ids = MediaIdMap()
        unit_pks = [n.pk for n in nodes if n.kind == "unit"]
        # Query only TOP-LEVEL joins; walk_unit_joins expands each tabs element's
        # children inline (parents before children), so every element is visited
        # EXACTLY ONCE and no child needs a recursive query here.
        joins_by_unit = {}
        for join in (
            Element.objects.filter(unit_id__in=unit_pks, parent__isnull=True)
            .order_by("unit_id", "order", "pk")
            .prefetch_related("content_object")
        ):
            joins_by_unit.setdefault(join.unit_id, []).append(join)

        # Pass 2: walk elements. walk_index counts EVERY join (incl. skipped
        # broken ones) so all problem types share one ordering space (§1).
        pending = []  # (walk_index, element_dict_without_id, mids_list)
        broken = []  # (walk_index, unit_title)
        mid_refs = {}  # mid -> [(walk_index, unit_pk, unit_title), ...] first-seen
        walk_index = 0
        walk_index_by_join_pk = {}  # join.pk -> its walk_index (parent precedes child)
        for n in nodes:
            for join, parent_join, tab_id in walk_unit_joins(n.pk, joins_by_unit):
                walk_index += 1
                walk_index_by_join_pk[join.pk] = walk_index
                # Parents always precede their children in the walk, so a child's
                # parent walk_index is already recorded by the time we reach it.
                parent_walk_index = (
                    walk_index_by_join_pk[parent_join.pk] if parent_join else None
                )
                if join.content_object is None:  # dangling GFK: concrete row gone
                    broken.append((walk_index, n.title))
                    continue
                type_key, data = serialize_element_data(join.content_object, media_ids)
                # all mids this element references, routed by type_key (a scalar
                # `media`-bearing type yields a 0/1-element list; a gallery yields
                # its images[].media list) — see _element_mids.
                mids = _element_mids(type_key, data)
                for mid in mids:
                    mid_refs.setdefault(mid, []).append((walk_index, n.pk, n.title))
                pending.append(
                    (
                        walk_index,
                        {
                            "unit": node_ids[n.pk],
                            "title": join.title,
                            "type": type_key,
                            "data": data,
                            "parent": parent_walk_index,  # int walk_index or None
                            "tab": tab_id,
                        },
                        mids,
                    )
                )

        # Pass 3: resolve each distinct registered asset's FINAL status here,
        # combining storage.exists() with a guarded .size (§1 step 3).
        status = {}  # mid -> "real" | "placeholder" | "dropped"
        total_bytes = 0
        for mid, asset in media_ids.items():
            present = bool(asset.file.name) and asset.file.storage.exists(
                asset.file.name
            )
            if present:
                try:
                    total_bytes += asset.file.size
                    status[mid] = "real"
                except OSError:  # present-but-unreadable -> treat as missing
                    present = False
            if not present:
                if asset.kind == "image":
                    status[mid] = "placeholder"
                    total_bytes += _placeholder_size()
                else:
                    status[mid] = "dropped"

        # Pass 4: emit elements (exclude those referencing a dropped mid);
        # assign e-ids over kept elements only (no gaps, §1 step 4). Drop if ANY
        # referenced mid was dropped (images never drop — they become
        # placeholders — so galleries are kept; videos still drop as before).
        element_dicts = []
        eid_by_walk = {}  # walk_index -> "e#" for kept elements
        eidx = 0
        for wi, edict, mids in pending:
            if any(status.get(mid) == "dropped" for mid in mids):
                continue
            eidx += 1
            eid = f"e{eidx}"
            eid_by_walk[wi] = eid
            element_dicts.append({"id": eid, **edict})
        # Resolve each element's `parent` (carried as the parent's walk_index int)
        # to that parent's e-id. A parent is always a tabs element, which references
        # no media and so is never dropped, and always precedes its children in the
        # walk -- so its walk_index is guaranteed present in eid_by_walk.
        for d in element_dicts:
            if d["parent"] is not None:
                d["parent"] = eid_by_walk[d["parent"]]

        # Pass 5: emit media (exclude dropped); flag placeholders. Mids may be
        # non-contiguous after a drop and are NOT renumbered (§1 step 5).
        media_dicts = []
        media_assets = []
        for mid, asset in media_ids.items():
            if status[mid] == "dropped":
                continue
            is_placeholder = status[mid] == "placeholder"
            if is_placeholder:
                ofn = _placeholder_filename(asset.original_filename)
                ext = ".png"
            else:
                ofn = asset.original_filename
                ext = os.path.splitext(asset.original_filename)[1].lower()
            media_dicts.append(
                {
                    "id": mid,
                    "kind": "image" if is_placeholder else asset.kind,
                    "name": asset.name,
                    "original_filename": ofn,
                    "file": f"media/{mid}{ext}",
                }
            )
            media_assets.append((mid, asset, is_placeholder))

        # Build the problems list, then stable-sort by walk index (§1 ordering).
        def _units_for(mid):
            # pk-dedupe (a single unit referencing the asset twice is listed
            # once), then collapse repeated identical titles into "Title (×N)"
            # so two distinct same-named units read as "Bonus lesson (×2)" rather
            # than the awkward "Bonus lesson, Bonus lesson". First-seen order.
            seen = set()
            counts = {}
            order = []
            for _wi, upk, ut in mid_refs[mid]:
                if upk in seen:
                    continue
                seen.add(upk)
                if ut not in counts:
                    order.append(ut)
                counts[ut] = counts.get(ut, 0) + 1
            return [ut if counts[ut] == 1 else f"{ut} (×{counts[ut]})" for ut in order]

        asset_by_mid = dict(media_ids.items())
        problems = []
        for wi, unit_title in broken:
            problems.append(
                {"__wi": wi, "type": "broken_element", "units": [unit_title]}
            )
        for mid, refs in mid_refs.items():
            if status[mid] == "placeholder":
                ptype = "missing_image"
            elif status[mid] == "dropped":
                ptype = "dropped_video"
            else:
                continue
            asset = asset_by_mid[mid]
            problems.append(
                {
                    "__wi": refs[0][0],
                    "type": ptype,
                    "filename": asset.original_filename,
                    "units": _units_for(mid),
                }
            )
        problems.sort(key=lambda p: p["__wi"])  # stable; walk-order across types
        problems = [{k: v for k, v in p.items() if k != "__wi"} for p in problems]

        if node is None:
            head = {
                "course": {
                    "title": course.title,
                    "language": course.language,
                    "overview": course.overview,
                    "html_css": course.html_css,
                    "html_js": course.html_js,
                    "uses_parts": course.uses_parts,
                    "uses_chapters": course.uses_chapters,
                    "uses_sections": course.uses_sections,
                    "color_bands": course.color_bands,
                    "subjects": [
                        {"title_en": s.title_en, "title_pl": s.title_pl}
                        for s in course.subjects.all().order_by("title_en", "pk")
                    ],
                }
            }
        else:
            head = {
                "context": {
                    "source_course_title": course.title,
                    "root_kind": node.kind,
                    "required_kinds": sorted({n["kind"] for n in node_dicts}),
                    "html_css": course.html_css,
                    "html_js": course.html_js,
                }
            }

        document = {
            **head,
            "nodes": node_dicts,
            "elements": element_dicts,
            "media": media_dicts,
        }
        manifest = {
            "format_version": FORMAT_VERSION,
            "kind": KIND_COURSE if node is None else KIND_SUBTREE,
            "exported_at": timezone.now().isoformat(),
            "source": {"instance": source_host, "app_version": ""},
            "course": {"title": course.title, "slug": course.slug},
            "media_total_bytes": total_bytes,
        }
        if node is not None:
            manifest["node"] = {"title": node.title, "kind": node.kind}
        return manifest, document, media_assets, problems


def write_archive_from(manifest, document, media_assets, fileobj):
    """Write a pre-built archive (from build_export) into fileobj."""
    entry_by_mid = {m["id"]: m["file"] for m in document["media"]}
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr("course.json", json.dumps(document, ensure_ascii=False))
        for mid, asset, is_placeholder in media_assets:
            if is_placeholder:
                zf.writestr(entry_by_mid[mid], _placeholder_bytes())
                continue
            with asset.file.open("rb") as src, zf.open(entry_by_mid[mid], "w") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)


def write_archive(course, node, fileobj, source_host=""):
    manifest, document, media_assets, _problems = build_export(
        course, node, source_host
    )
    write_archive_from(manifest, document, media_assets, fileobj)


def export_filename(course, node, today):
    if node is None:
        return f"{course.slug}-export-{today.isoformat()}.zip"
    seg = slugify(node.title) or "content"
    return f"{course.slug}-{seg}-export-{today.isoformat()}.zip"


_PLACEHOLDER_PATH = os.path.join(
    os.path.dirname(__file__), "assets", "missing_image_placeholder.png"
)


def _placeholder_bytes():
    """Bytes of the bundled 'missing image' placeholder (package data, §2)."""
    with open(_PLACEHOLDER_PATH, "rb") as f:
        return f.read()


def _placeholder_size():
    return os.path.getsize(_PLACEHOLDER_PATH)


def _placeholder_filename(original):
    """Original filename stem forced to a `.png` extension, falling back to
    `image.png` for an empty/dots-only stem (§2). Uses os.path.splitext
    (consistent with the extension handling elsewhere in this module).

    NB: this refines the spec §2 formula `(splitext[0] or "image")`, which
    mishandles a lone "." — `os.path.splitext(".")[0] == "."` is truthy, so that
    formula yields "..png". The `strip(".")` guard maps "", ".", ".." → "image";
    ".foo" keeps its ".foo" stem → ".foo.png"."""
    stem = os.path.splitext(original or "")[0]
    if not stem.strip("."):  # empty or dots-only ("", ".", "..")
        stem = "image"
    return f"{stem}.png"
