"""Export: serialize a course/subtree content graph to the archive format (§2)."""

import json
import os
import zipfile

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
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
    return {"url": el.url, "title": el.title}


def _ser_math(el, ids):
    return {"latex": el.latex}


def _ser_html(el, ids):
    return {"html": el.html}


def _ser_choice(el, ids):
    return {
        **_question_fields(el),
        "multiple": el.multiple,
        "choices": [
            {"text": c.text, "is_correct": c.is_correct} for c in el.choices.all()
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


# type_key -> (model, serializer). The 14-entry registry; Task 6's importer-side
# registry in schema.py mirrors these keys — keep both in lockstep.
SERIALIZERS = {
    "text": (TextElement, _ser_text),
    "image": (ImageElement, _ser_image),
    "video": (VideoElement, _ser_video),
    "iframe": (IframeElement, _ser_iframe),
    "math": (MathElement, _ser_math),
    "html": (HtmlElement, _ser_html),
    "choice": (ChoiceQuestionElement, _ser_choice),
    "short_text": (ShortTextQuestionElement, _ser_short_text),
    "extended_response": (ExtendedResponseQuestionElement, _ser_extended),
    "short_numeric": (ShortNumericQuestionElement, _ser_numeric),
    "fill_blank": (FillBlankQuestionElement, _ser_fill_blank),
    "drag_fill_blank": (DragFillBlankQuestionElement, _ser_drag_fill),
    "match_pair": (MatchPairQuestionElement, _ser_match_pair),
    "drag_to_image": (DragToImageQuestionElement, _ser_drag_to_image),
}

_MODEL_TO_KEY = {model: key for key, (model, _fn) in SERIALIZERS.items()}


def serialize_element_data(concrete, media_ids):
    key = _MODEL_TO_KEY.get(type(concrete))
    if key is None:  # pragma: no cover — every ElementBase subclass is registered
        raise TransferError(f"Unserializable element model: {type(concrete).__name__}")
    _model, fn = SERIALIZERS[key]
    return key, fn(concrete, media_ids)


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
        element_dicts = []
        i = 0
        unit_pks = [n.pk for n in nodes if n.kind == "unit"]
        joins_by_unit = {}
        for join in (
            Element.objects.filter(unit_id__in=unit_pks)
            .order_by("unit_id", "order", "pk")
            .prefetch_related("content_object")
        ):
            joins_by_unit.setdefault(join.unit_id, []).append(join)
        for n in nodes:
            for join in joins_by_unit.get(n.pk, []):
                i += 1
                if join.content_object is None:  # dangling GFK: concrete row gone
                    raise TransferError(
                        _(
                            "Unit “%(unit)s” contains a broken element — repair or "
                            "delete it before exporting."
                        )
                        % {"unit": n.title}
                    )
                type_key, data = serialize_element_data(join.content_object, media_ids)
                element_dicts.append(
                    {
                        "id": f"e{i}",
                        "unit": node_ids[n.pk],
                        "title": join.title,
                        "type": type_key,
                        "data": data,
                    }
                )

        media_dicts = []
        total_bytes = 0
        for mid, asset in media_ids.items():
            ext = os.path.splitext(asset.original_filename)[1].lower()
            try:
                total_bytes += asset.file.size
            except OSError as exc:  # orphaned FileField: row intact, file gone
                raise TransferError(
                    _("Media file missing from storage: %(name)s")
                    % {"name": asset.original_filename}
                ) from exc
            media_dicts.append(
                {
                    "id": mid,
                    "kind": asset.kind,
                    "name": asset.name,
                    "original_filename": asset.original_filename,
                    "file": f"media/{mid}{ext}",
                }
            )

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
        return manifest, document, media_ids.items()


def write_archive(course, node, fileobj, source_host=""):
    manifest, document, media_assets = build_export(course, node, source_host)
    entry_by_mid = {m["id"]: m["file"] for m in document["media"]}
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr("course.json", json.dumps(document, ensure_ascii=False))
        for mid, asset in media_assets:
            with asset.file.open("rb") as src, zf.open(entry_by_mid[mid], "w") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)


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
