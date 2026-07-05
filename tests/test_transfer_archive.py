# tests/test_transfer_archive.py
import io
import json
import zipfile

import pytest

from courses.transfer.importer import open_archive
from courses.transfer.schema import TransferError


def make_manifest(**over):
    m = {
        "format_version": 1,
        "kind": "course",
        "exported_at": "2026-07-05T12:00:00+00:00",
        "source": {"instance": "test", "app_version": ""},
        "course": {"title": "T", "slug": "t"},
        "media_total_bytes": 0,
    }
    m.update(over)
    return m


def make_zip(entries=None, manifest=None, document=None):
    """entries: extra (name, bytes) pairs. Returns BytesIO of a zip with
    manifest.json + course.json (+ extras)."""
    doc = (
        document
        if document is not None
        else {
            "course": {
                "title": "T",
                "language": "en",
                "overview": "",
                "html_css": "",
                "html_js": "",
                "uses_parts": True,
                "uses_chapters": True,
                "uses_sections": True,
                "color_bands": [],
                "subjects": [],
            },
            "nodes": [],
            "elements": [],
            "media": [],
        }
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest or make_manifest()))
        zf.writestr("course.json", json.dumps(doc))
        for name, data in entries or []:
            zf.writestr(name, data)
    buf.seek(0)
    return buf


def _reject(buf, needle, kind="course"):
    with pytest.raises(TransferError) as exc:
        with open_archive(buf, expected_kind=kind):
            pass
    assert needle.lower() in exc.value.message.lower()
    return exc.value.message


def test_happy_path():
    with open_archive(make_zip(), expected_kind="course") as (zf, mani, doc, media):
        assert mani["kind"] == "course"
        assert doc["nodes"] == []
        assert media == {}


def test_not_a_zip():
    _reject(io.BytesIO(b"plain text"), "zip")


def test_compressed_cap(settings):
    settings.TRANSFER_MAX_COMPRESSED_BYTES = 10
    _reject(make_zip(), "at most 10")  # message names the configured limit


def test_uncompressed_declared_cap(settings):
    settings.TRANSFER_MAX_UNCOMPRESSED_BYTES = 8
    _reject(make_zip(), "large")


def test_manifest_size_cap(settings):
    settings.TRANSFER_MAX_MANIFEST_BYTES = 4
    _reject(make_zip(), "manifest")


def test_course_json_size_cap(settings):
    settings.TRANSFER_MAX_COURSE_JSON_BYTES = 4
    _reject(make_zip(), "course.json")


def test_duplicate_entry_names_reject():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(make_manifest()))
        zf.writestr("course.json", "{}")
        zf.writestr("course.json", "{}")  # duplicate
    buf.seek(0)
    _reject(buf, "duplicate")


def test_path_traversal_rejects():
    _reject(make_zip(entries=[("../evil.txt", b"x")]), "entry")
    _reject(make_zip(entries=[("media/sub/dir.png", b"x")]), "entry")
    _reject(make_zip(entries=[("other.txt", b"x")]), "entry")


def test_directory_entries_ignored():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(make_manifest()))
        zf.writestr(
            "course.json",
            json.dumps(
                {
                    "course": {
                        "title": "T",
                        "language": "en",
                        "overview": "",
                        "html_css": "",
                        "html_js": "",
                        "uses_parts": True,
                        "uses_chapters": True,
                        "uses_sections": True,
                        "color_bands": [],
                        "subjects": [],
                    },
                    "nodes": [],
                    "elements": [],
                    "media": [],
                }
            ),
        )
        zf.writestr("media/", b"")  # zero-length dir entry → ignored
    buf.seek(0)
    with open_archive(buf, expected_kind="course"):
        pass  # no raise


def test_newer_format_version_named():
    msg = _reject(make_zip(manifest=make_manifest(format_version=99)), "version")
    assert "99" in msg


def test_version_below_one_rejects():
    _reject(make_zip(manifest=make_manifest(format_version=0)), "version")


def test_nondict_manifest_node_rejects():
    mani = make_manifest(kind="subtree", node=["title", "kind"])
    _reject(make_zip(manifest=mani), "node", kind="subtree")


def test_kind_mismatch_points_at_other_entry():
    _reject(make_zip(), "content", kind="subtree")  # course zip at subtree entry


def test_unknown_manifest_key_rejects():
    _reject(make_zip(manifest=make_manifest(surprise=1)), "surprise")


def test_nonstring_manifest_text_field_rejects():
    _reject(
        make_zip(manifest=make_manifest(course={"title": {"a": 1}, "slug": "t"})),
        "text",
    )


def test_missing_manifest_rejects():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("course.json", "{}")
    buf.seek(0)
    _reject(buf, "manifest")


def test_malformed_json_rejects():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", "{not json")
        zf.writestr("course.json", "{}")
    buf.seek(0)
    _reject(buf, "json")


def test_deeply_nested_json_rejects_not_500():
    deep = "[" * 200_000 + "]" * 200_000
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(make_manifest()))
        zf.writestr("course.json", deep)
    buf.seek(0)
    _reject(buf, "json")


def test_lying_header_counted_read(settings):
    # Declared sizes pass the cap, but a tampered header must not allow reading
    # more than declared: build a zip, then shrink the central-directory size.
    import struct  # noqa: F401  (documenting intent; simplest check below)

    buf = make_zip(entries=[("media/m1.png", b"A" * 1000)])
    with zipfile.ZipFile(buf) as zf:
        info = zf.getinfo("media/m1.png")
        info.file_size = 10  # lie: declared 10, actual 1000
        from courses.transfer.importer import read_entry_bytes

        with pytest.raises(TransferError):
            read_entry_bytes(zf, info, cap=10_000, what="media/m1.png")
