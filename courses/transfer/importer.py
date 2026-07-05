"""Import: archive/document validation, preview, and transactional commit (§4/§5)."""

import json
import os
import tempfile
import types
import zipfile
from contextlib import contextmanager

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db.models import Q
from django.utils.translation import gettext as _

from courses.media import truncate_filename
from courses.models import Subject
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


def read_entry_bytes(zf, info, cap, what):
    if info.file_size > cap:
        raise TransferError(
            _("%(name)s exceeds the configured limit of %(limit)d bytes.")
            % {"name": what, "limit": cap}
        )
    out = b""
    # zipfile itself raises BadZipFile/zlib.error mid-read on tampered entries
    # (CRC or size mismatch) — map ALL read failures to TransferError, and keep
    # our own byte count as defense in depth against lying headers.
    try:
        with zf.open(info) as fh:
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                out += chunk
                if len(out) > info.file_size:  # lying header
                    raise TransferError(
                        _("%(name)s is larger than its declared size.") % {"name": what}
                    )
    except TransferError:
        raise
    except Exception as exc:  # BadZipFile, zlib.error, OSError
        raise TransferError(
            _("The archive entry %(name)s is corrupt.") % {"name": what}
        ) from exc
    return out


def extract_entry_to_tempfile(zf, info):
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    read = 0
    try:
        with zf.open(info) as fh:
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                read += len(chunk)
                if read > info.file_size:
                    raise TransferError(
                        _("%(name)s is larger than its declared size.")
                        % {"name": info.filename}
                    )
                spool.write(chunk)
    except TransferError:
        spool.close()
        raise
    except Exception as exc:  # BadZipFile, zlib.error, OSError
        spool.close()
        raise TransferError(
            _("The archive entry %(name)s is corrupt.") % {"name": info.filename}
        ) from exc
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
        # Read the ACTUAL decompressed bytes rather than trusting the
        # attacker-declared info.file_size (classic zip-bomb: valid CRC,
        # understated declared size). read_entry_bytes aborts once real bytes
        # exceed min(max_bytes, info.file_size), so this rejects both an
        # honest oversized file and a lying-header one.
        read_entry_bytes(
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
