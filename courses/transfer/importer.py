"""Import: archive/document validation, preview, and transactional commit (§4/§5)."""

import json
import logging
import os
import tempfile
import types
import zipfile
from contextlib import contextmanager
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.validators import FileExtensionValidator
from django.db import IntegrityError
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from courses.forms import unique_course_slug
from courses.media import create_asset
from courses.media import truncate_filename
from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import GalleryElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import RevealGateElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SlideBreakElement
from courses.models import Subject
from courses.models import TableElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import VideoElement
from courses.ordering import legal_child_kinds
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import KIND_COURSE
from courses.transfer.schema import KIND_SUBTREE
from courses.transfer.schema import TransferError
from courses.transfer.schema import _exact_keys
from courses.transfer.schema import validate_document
from courses.validators import effective_image_extensions
from courses.validators import effective_max_image_bytes
from courses.validators import effective_max_video_bytes
from courses.validators import effective_video_extensions

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024


def parse_json_bytes(raw, what):
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        doc = None
    if not isinstance(doc, dict):
        raise TransferError(
            _("The archive's %(name)s is not a valid JSON object.") % {"name": what}
        )
    return doc


def _guarded_read(zf, info, cap, what, sink):
    """Shared guarded-read core for `read_entry_bytes` and
    `extract_entry_to_tempfile` (and the count-only media-size check).

    Reads `info`'s decompressed content in chunks, calling `sink(chunk)` for
    each in-limit chunk, and returns the total byte count read. Aborts with
    TransferError:
    - immediately, if the entry's declared `info.file_size` already exceeds
      `cap` (skipped when `cap` is None — callers that already bytes-capped
      the entry elsewhere, i.e. the tempfile extractor, pass None);
    - mid-read, the moment the running total exceeds `info.file_size` — the
      lying-header guard (a valid CRC with an understated declared size),
      which always applies regardless of `cap`.

    zipfile itself raises BadZipFile/zlib.error mid-read on tampered entries
    (CRC or size mismatch); any such read (or `sink`) failure is mapped to
    TransferError here — never let a raw exception escape this boundary.
    """
    if cap is not None and info.file_size > cap:
        raise TransferError(
            _("%(name)s exceeds the configured limit of %(limit)d bytes.")
            % {"name": what, "limit": cap}
        )
    total = 0
    try:
        with zf.open(info) as fh:
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > info.file_size:  # lying header
                    raise TransferError(
                        _("%(name)s is larger than its declared size.") % {"name": what}
                    )
                sink(chunk)
    except TransferError:
        raise
    except Exception as exc:  # BadZipFile, zlib.error, OSError
        raise TransferError(
            _("The archive entry %(name)s is corrupt.") % {"name": what}
        ) from exc
    return total


def read_entry_bytes(zf, info, cap, what):
    buf = bytearray()
    _guarded_read(zf, info, cap, what, buf.extend)
    return bytes(buf)


def _validate_entry_size(zf, info, cap, what):
    """Count-only counterpart of `read_entry_bytes`: enforces the identical
    declared-size + lying-header guard without accumulating a `bytes` object.
    Used for media validation, where only the enforcement side effect matters
    — building a full in-memory copy of a multi-hundred-MB video just to
    discard it is avoidable memory pressure on the untrusted-upload path."""
    return _guarded_read(zf, info, cap, what, lambda _chunk: None)


def extract_entry_to_tempfile(zf, info):
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    try:
        _guarded_read(zf, info, None, info.filename, spool.write)
    except TransferError:
        spool.close()
        raise
    spool.seek(0)
    return spool


def _validate_manifest(manifest, expected_kind):
    keys = [
        "format_version",
        "kind",
        "exported_at",
        "source",
        "course",
        "media_total_bytes",
    ]
    if manifest.get("kind") == KIND_SUBTREE:
        keys.append("node")
    _exact_keys(manifest, keys, "manifest.json")
    version = manifest["format_version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise TransferError(
            _("manifest.json: format_version must be a positive integer.")
        )
    if version > FORMAT_VERSION:
        raise TransferError(
            _(
                "This archive uses format version %(found)d, but this instance "
                "supports up to version %(max)d. It was exported from a newer "
                "application version."
            )
            % {"found": version, "max": FORMAT_VERSION}
        )
    kind = manifest["kind"]
    if kind not in (KIND_COURSE, KIND_SUBTREE):
        raise TransferError(_("manifest.json: unknown archive kind."))
    if kind != expected_kind:
        if expected_kind == KIND_COURSE:
            raise TransferError(
                _(
                    "This archive contains course content (a subtree), not a whole "
                    "course. Use 'Import content' on the target course's builder "
                    "page instead."
                )
            )
        raise TransferError(
            _(
                "This archive contains a whole course, not a content subtree. "
                "Use 'Import course' on the course list instead."
            )
        )
    if not isinstance(manifest["source"], dict) or not isinstance(
        manifest["course"], dict
    ):
        raise TransferError(_("manifest.json: malformed source/course block."))
    _exact_keys(manifest["source"], ["instance", "app_version"], "source")
    _exact_keys(manifest["course"], ["title", "slug"], "manifest course")
    # The preview renders these — a non-str value would show a Python repr.
    str_fields = [
        manifest["exported_at"],
        manifest["source"]["instance"],
        manifest["source"]["app_version"],
        manifest["course"]["title"],
        manifest["course"]["slug"],
    ]
    if kind == KIND_SUBTREE:
        if not isinstance(manifest["node"], dict):  # a list would pass key loops
            raise TransferError(_("manifest.json: malformed node block."))
        _exact_keys(manifest["node"], ["title", "kind"], "manifest node")
        str_fields += [manifest["node"]["title"], manifest["node"]["kind"]]
    if not all(isinstance(v, str) for v in str_fields):
        raise TransferError(_("manifest.json: malformed text field."))
    total = manifest["media_total_bytes"]
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise TransferError(_("manifest.json: media_total_bytes must be an integer."))
    if total > settings.TRANSFER_MAX_UNCOMPRESSED_BYTES:
        raise TransferError(
            _(
                "This export contains %(found)d bytes of media; this instance "
                "accepts at most %(limit)d bytes."
            )
            % {"found": total, "limit": settings.TRANSFER_MAX_UNCOMPRESSED_BYTES}
        )


def read_archive(fileobj, *, expected_kind):
    fileobj.seek(0, os.SEEK_END)
    size = fileobj.tell()
    fileobj.seek(0)
    if size > settings.TRANSFER_MAX_COMPRESSED_BYTES:
        raise TransferError(
            _(
                "The archive is %(found)d bytes; this instance accepts at most "
                "%(limit)d bytes."
            )
            % {"found": size, "limit": settings.TRANSFER_MAX_COMPRESSED_BYTES}
        )
    try:
        zf = zipfile.ZipFile(fileobj)
    except (zipfile.BadZipFile, OSError) as exc:
        raise TransferError(_("The uploaded file is not a valid zip archive.")) from exc

    try:
        # +2 = manifest.json + course.json, on top of the media entry cap.
        # Guards against a zip-bomb-by-entry-count before we ever iterate the
        # entries to build media_entries below.
        max_entries = settings.TRANSFER_MAX_MEDIA_ENTRIES + 2
        if len(zf.infolist()) > max_entries:
            raise TransferError(
                _("The archive contains too many files (at most %(n)s).")
                % {"n": max_entries}
            )
        infos = [i for i in zf.infolist() if not i.filename.endswith("/")]
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise TransferError(_("The archive contains duplicate entry names."))
        media_entries = {}
        for info in infos:
            name = info.filename
            if name in ("manifest.json", "course.json"):
                continue
            base = name[len("media/") :] if name.startswith("media/") else None
            if (
                base is None
                or not base
                or "/" in base
                or "\\" in name
                or ".." in name
                or name.startswith("/")
            ):
                raise TransferError(
                    _("The archive contains a disallowed entry: %(name)s.")
                    % {"name": name}
                )
            media_entries[name] = info
        if sum(i.file_size for i in infos) > settings.TRANSFER_MAX_UNCOMPRESSED_BYTES:
            raise TransferError(
                _("The archive's contents are too large (limit %(limit)d bytes).")
                % {"limit": settings.TRANSFER_MAX_UNCOMPRESSED_BYTES}
            )
        try:
            mani_info = zf.getinfo("manifest.json")
        except KeyError:
            raise TransferError(_("The archive has no manifest.json.")) from None
        manifest = parse_json_bytes(
            read_entry_bytes(
                zf, mani_info, settings.TRANSFER_MAX_MANIFEST_BYTES, "manifest.json"
            ),
            "manifest.json",
        )
        _validate_manifest(manifest, expected_kind)
        try:
            doc_info = zf.getinfo("course.json")
        except KeyError:
            raise TransferError(_("The archive has no course.json.")) from None
        document = parse_json_bytes(
            read_entry_bytes(
                zf, doc_info, settings.TRANSFER_MAX_COURSE_JSON_BYTES, "course.json"
            ),
            "course.json",
        )
        return zf, manifest, document, media_entries
    except BaseException:
        zf.close()  # never leak the handle — on Windows it blocks the unlink
        raise


@contextmanager
def open_archive(fileobj, *, expected_kind):
    zf, manifest, document, media_entries = read_archive(
        fileobj, expected_kind=expected_kind
    )
    try:
        yield zf, manifest, document, media_entries
    finally:
        zf.close()


def validate_media_entries(zf, document, media_entries):
    listed = {}
    for m in document["media"]:
        if m["file"] not in media_entries:
            raise TransferError(
                _("Media entry '%(id)s' points at a missing archive file %(path)s.")
                % {"id": m["id"], "path": m["file"]}
            )
        listed[m["file"]] = m
    for name in media_entries:
        if name not in listed:
            raise TransferError(
                _("The archive contains an unlisted media file %(path)s.")
                % {"path": name}
            )
    for name, m in listed.items():
        info = media_entries[name]
        fname = truncate_filename(m["original_filename"])
        if m["kind"] == "image":
            exts, max_bytes = effective_image_extensions(), effective_max_image_bytes()
        else:
            exts, max_bytes = effective_video_extensions(), effective_max_video_bytes()

        holder = types.SimpleNamespace(name=fname)  # validator reads .name
        try:
            FileExtensionValidator(allowed_extensions=list(exts))(holder)
        except ValidationError:
            raise TransferError(
                _("Media file %(name)s has a file type this instance does not accept.")
                % {"name": fname}
            ) from None
        # Count the ACTUAL decompressed bytes rather than trusting the
        # attacker-declared info.file_size (classic zip-bomb: valid CRC,
        # understated declared size). _validate_entry_size aborts once real
        # bytes exceed min(max_bytes, info.file_size), so this rejects both an
        # honest oversized file and a lying-header one — without buffering the
        # (possibly hundreds-of-MB) entry into memory just to discard it.
        _validate_entry_size(
            zf,
            info,
            max_bytes,
            _("Media file %(name)s (limit %(limit)d bytes)")
            % {"name": fname, "limit": max_bytes},
        )


def validate_archive_document(
    zf, manifest, document, media_entries, *, kind, target_course=None
):
    target_allowed = target_course.allowed_kinds if target_course else None
    validate_document(document, kind=kind, target_allowed_kinds=target_allowed)
    validate_media_entries(zf, document, media_entries)


def match_subjects(subject_dicts):
    matched, dropped = [], []
    for s in subject_dicts:
        q = Q()
        if s["title_en"].strip():
            q |= Q(title_en__iexact=s["title_en"].strip())
        if s["title_pl"].strip():
            q |= Q(title_pl__iexact=s["title_pl"].strip())
        subj = (
            Subject.objects.filter(q).order_by("title_en", "pk").first() if q else None
        )
        if subj is not None:
            matched.append(subj)
        else:
            dropped.append(s)
    return matched, dropped


def insertion_choices(target_course, root_kind):
    allowed = target_course.allowed_kinds
    choices = []
    if root_kind in legal_child_kinds(None, allowed):
        choices.append({"value": "", "label": _("Top level")})
    cmap = {}
    for n in target_course.nodes.all().order_by("order", "pk"):
        cmap.setdefault(n.parent_id, []).append(n)

    def walk(pid, trail):
        for n in cmap.get(pid, []):
            label = " › ".join(trail + [n.title])
            if n.kind != "unit" and root_kind in legal_child_kinds(n.kind, allowed):
                choices.append({"value": str(n.pk), "label": label})
            walk(n.pk, trail + [n.title])

    walk(None, [])
    return choices


def build_preview(manifest, document, media_entries, *, target_course=None):
    doc = document
    is_course = manifest["kind"] == KIND_COURSE
    preview = {
        "kind": manifest["kind"],
        "title": manifest["course"]["title"]
        if is_course
        else manifest["node"]["title"],
        "source": manifest["source"],
        "node_count": len(doc["nodes"]),
        "element_count": len(doc["elements"]),
        "media_count": len(doc["media"]),
        "media_total_bytes": sum(i.file_size for i in media_entries.values()),
        "has_html_elements": any(e["type"] == "html" for e in doc["elements"]),
        "subjects_matched": [],
        "subjects_dropped": [],
        "context_css_js": None,
        "insertion_choices": None,
    }
    if is_course:
        matched, dropped = match_subjects(doc["course"]["subjects"])
        preview["subjects_matched"] = [s.title for s in matched]
        preview["subjects_dropped"] = [s["title_en"] or s["title_pl"] for s in dropped]
    else:
        ctx = doc["context"]
        if preview["has_html_elements"] and (ctx["html_css"] or ctx["html_js"]):
            preview["context_css_js"] = {
                "html_css": ctx["html_css"],
                "html_js": ctx["html_js"],
            }
        preview["insertion_choices"] = insertion_choices(
            target_course, doc["nodes"][0]["kind"]
        )
    return preview


def _q_kwargs(data):
    return {
        "stem": data["stem"],
        "explanation": data["explanation"],
        "marking_mode": data["marking_mode"],
        "max_attempts": data["max_attempts"],
        "max_marks": Decimal(data["max_marks"]),
    }


def _clean_save(obj):
    obj.full_clean(exclude=["order"] if hasattr(obj, "order") else None)
    obj.save()
    return obj


def _build_text(data, assets):
    return _clean_save(TextElement(body=data["body"])), ()


def _build_image(data, assets):
    el = ImageElement(
        media=assets[data["media"]], alt=data["alt"], figcaption=data["figcaption"]
    )
    return _clean_save(el), ()


def _build_video(data, assets):
    el = VideoElement(
        url=data["url"] or "",
        media=assets[data["media"]] if data["media"] else None,
    )
    return _clean_save(el), ()


def _build_iframe(data, assets):
    return (
        _clean_save(
            IframeElement(
                url=data["url"],
                title=data["title"],
                width=data["width"],
                height=data["height"],
            )
        ),
        (),
    )


def _build_math(data, assets):
    return _clean_save(MathElement(latex=data["latex"])), ()


def _build_html(data, assets):
    return _clean_save(HtmlElement(html=data["html"])), ()


def _build_slide_break(data, assets):
    return SlideBreakElement.objects.create(), ()


def _build_reveal_gate(data, assets):
    return RevealGateElement.objects.create(label=data.get("label", "")), ()


def _build_table(data, assets):
    # normalize_data rectangularises/coerces (validator already rejected
    # over-cap/ragged shapes); save() sanitises every cell's html (Task 2),
    # so import is safe even though the builder bypasses TableElementForm.
    return _clean_save(TableElement(data=TableElement.normalize_data(data))), ()


def _build_gallery(data, assets):
    images = [
        {"media": assets[img["media"]].pk, "desc": img["desc"]}
        for img in data["images"]
    ]
    el = GalleryElement(data={"desc_pos": data["desc_pos"], "images": images})
    return _clean_save(el), ()  # save() normalizes + sanitises each desc


def _build_choice(data, assets):
    q = _clean_save(ChoiceQuestionElement(**_q_kwargs(data), multiple=data["multiple"]))
    rows = [
        Choice(question=q, text=c["text"], is_correct=c["is_correct"])
        for c in data["choices"]
    ]
    return q, rows


def _build_short_text(data, assets):
    q = ShortTextQuestionElement(
        **_q_kwargs(data),
        accepted=data["accepted"],
        case_sensitive=data["case_sensitive"],
    )
    return _clean_save(q), ()


def _build_extended(data, assets):
    q = ExtendedResponseQuestionElement(
        **_q_kwargs(data),
        required_keywords=data["required_keywords"],
        forbidden_keywords=data["forbidden_keywords"],
    )
    return _clean_save(q), ()


def _build_numeric(data, assets):
    q = ShortNumericQuestionElement(
        **_q_kwargs(data),
        value=Decimal(data["value"]),
        tolerance=Decimal(data["tolerance"]),
    )
    return _clean_save(q), ()


def _build_fill_blank(data, assets):
    q = _clean_save(FillBlankQuestionElement(**_q_kwargs(data)))
    rows = [
        Blank(question=q, accepted=b["accepted"], case_sensitive=b["case_sensitive"])
        for b in data["blanks"]
    ]
    return q, rows


def _build_drag_fill(data, assets):
    q = _clean_save(
        DragFillBlankQuestionElement(**_q_kwargs(data), distractors=data["distractors"])
    )
    rows = [
        DragBlank(question=q, correct_token=b["correct_token"]) for b in data["blanks"]
    ]
    return q, rows


def _build_match_pair(data, assets):
    q = _clean_save(
        MatchPairQuestionElement(**_q_kwargs(data), distractors=data["distractors"])
    )
    rows = [
        MatchPair(question=q, left=p["left"], right=p["right"]) for p in data["pairs"]
    ]
    return q, rows


def _build_drag_to_image(data, assets):
    q = _clean_save(
        DragToImageQuestionElement(
            **_q_kwargs(data),
            media=assets[data["media"]],
            alt=data["alt"],
            distractors=data["distractors"],
        )
    )
    rows = [
        DragZone(
            question=q,
            correct_label=z["correct_label"],
            x=z["x"],
            y=z["y"],
            w=z["w"],
            h=z["h"],
        )
        for z in data["zones"]
    ]
    return q, rows


def _build_tabs(data, assets):
    # Tab ids pass through VERBATIM. save() runs only normalize_labels_and_ids, which
    # never rewrites a present, unique, well-formed id -- and the validator has already
    # guaranteed all three. Regenerating here would orphan every child.
    return _clean_save(TabsElement(data={"tabs": data["tabs"]})), ()


BUILDERS = {
    "text": _build_text,
    "image": _build_image,
    "video": _build_video,
    "iframe": _build_iframe,
    "math": _build_math,
    "html": _build_html,
    "slide_break": _build_slide_break,
    "reveal_gate": _build_reveal_gate,
    "choice": _build_choice,
    "short_text": _build_short_text,
    "extended_response": _build_extended,
    "short_numeric": _build_numeric,
    "fill_blank": _build_fill_blank,
    "drag_fill_blank": _build_drag_fill,
    "match_pair": _build_match_pair,
    "drag_to_image": _build_drag_to_image,
    "table": _build_table,
    "gallery": _build_gallery,
    "tabs": _build_tabs,
}


def _create_media(zf, document, media_entries, course, user, created_files):
    assets = {}
    for m in document["media"]:
        info = media_entries[m["file"]]
        spool = extract_entry_to_tempfile(zf, info)
        try:
            wrapped = File(spool, name=truncate_filename(m["original_filename"]))
            asset = create_asset(course, m["kind"], wrapped, user, name=m["name"])
        finally:
            spool.close()  # up to 1000 entries — don't accumulate open handles
        created_files.append(asset.file.name)
        assets[m["id"]] = asset
    return assets


def _validation_detail(exc):
    return "; ".join(exc.messages)[:300] if hasattr(exc, "messages") else str(exc)[:300]


def _create_nodes(document, course, root_parent=None):
    node_map = {}
    for nd in document["nodes"]:
        parent = node_map[nd["parent"]] if nd["parent"] else root_parent
        node = ContentNode(
            course=course,
            parent=parent,
            kind=nd["kind"],
            title=nd["title"],
            unit_type=nd["unit_type"],
            obligatory=nd["obligatory"],
            html_seed_js=nd["html_seed_js"],
        )
        try:
            node.full_clean(exclude=["order"])
            node.save()
        except ValidationError as exc:
            raise TransferError(
                _("Node %(id)s (“%(title)s”) failed validation on import: %(detail)s")
                % {
                    "id": nd["id"],
                    "title": nd["title"],
                    "detail": _validation_detail(exc),
                }
            ) from exc
        node_map[nd["id"]] = node
    return node_map


def _create_elements(document, node_map, assets):
    """Two-pass, for reference resolution. Pass 1 creates every join row with
    parent=None, IN PAYLOAD ORDER -- OrderField's unit-wide max+1 therefore hands out
    strictly increasing `order` values in archive sequence, which is what preserves
    within-tab child order without ever serializing `order`. Pass 2 links children and
    must NOT touch `order`. Two passes also make the import robust to a hand-edited
    archive in which a child precedes its parent."""
    joins = {}
    for el in document["elements"]:
        try:
            concrete, child_rows = BUILDERS[el["type"]](el["data"], assets)
            for row in child_rows:
                row.full_clean(exclude=["order"])
                row.save()
            join = Element(
                unit=node_map[el["unit"]], title=el["title"], content_object=concrete
            )
            join.full_clean(exclude=["order"])
            join.save()
            joins[el["id"]] = join
        except ValidationError as exc:
            raise TransferError(
                _("Element %(id)s (%(type)s) failed validation on import: %(detail)s")
                % {
                    "id": el["id"],
                    "type": el["type"],
                    "detail": _validation_detail(exc),
                }
            ) from exc

    for el in document["elements"]:
        parent_ref = el.get("parent")
        if not parent_ref:
            continue
        join = joins[el["id"]]
        join.parent = joins[parent_ref]
        join.tab_id = el.get("tab") or ""
        join.save(update_fields=["parent", "tab_id"])  # never `order`


def _cleanup_files(created_files):
    from django.core.files.storage import default_storage

    for name in created_files:
        try:
            default_storage.delete(name)
        except OSError:  # best-effort (§4.4)
            pass


def _run_import(work, created_files):
    """Shared commit wrapper: transaction + error mapping + orphan cleanup."""
    try:
        with transaction.atomic():
            return work()
    except TransferError:
        _cleanup_files(created_files)
        raise
    except ValidationError as exc:
        _cleanup_files(created_files)
        detail = "; ".join(exc.messages)[:300] if hasattr(exc, "messages") else ""
        raise TransferError(
            _("The archive's content failed validation on this instance: %(detail)s")
            % {"detail": detail}
        ) from exc
    except IntegrityError as exc:
        _cleanup_files(created_files)
        raise TransferError(
            _(
                "The import could not be completed due to a concurrent change — "
                "please try again."
            )
        ) from exc
    except Exception as exc:
        # Any OTHER unexpected exception must still never surface as a raw
        # 500 — the view only catches TransferError. Convert + log server-side.
        _cleanup_files(created_files)
        logger.exception("Unexpected error during course transfer import")
        raise TransferError(
            _("The import failed unexpectedly. Please check the archive and try again.")
        ) from exc


def import_course(zf, manifest, document, media_entries, user):
    created_files = []

    def work():
        c = document["course"]
        course = Course(
            title=c["title"],
            slug=unique_course_slug(c["title"]),
            language=c["language"],
            overview=c["overview"],
            html_css=c["html_css"],
            html_js=c["html_js"],
            uses_parts=c["uses_parts"],
            uses_chapters=c["uses_chapters"],
            uses_sections=c["uses_sections"],
            color_bands=c["color_bands"],
            owner=user,
        )
        course.full_clean()
        course.save()
        matched, _dropped = match_subjects(c["subjects"])
        course.subjects.set(matched)
        assets = _create_media(zf, document, media_entries, course, user, created_files)
        node_map = _create_nodes(document, course)
        _create_elements(document, node_map, assets)
        return course

    return _run_import(work, created_files)


def import_subtree(
    zf, manifest, document, media_entries, target_course, insertion_node, user
):
    """Graft an exported content subtree into `target_course`, rooted under
    `insertion_node` (a ContentNode of that course, or None for top level).

    Reuses Task 9's machinery: media lands in the target course's library
    (uploaded_by=user), nodes are created with the subtree's root parented at
    insertion_node — OrderField(for_fields=["course", "parent"]) then appends
    the new root after any existing siblings automatically. The subtree's
    context CSS/JS is intentionally never applied to target_course (§2.2)."""
    created_files = []

    def work():
        assets = _create_media(
            zf, document, media_entries, target_course, user, created_files
        )
        node_map = _create_nodes(document, target_course, root_parent=insertion_node)
        _create_elements(document, node_map, assets)
        return node_map[document["nodes"][0]["id"]]

    return _run_import(work, created_files)
