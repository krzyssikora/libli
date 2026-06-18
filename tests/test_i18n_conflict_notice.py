"""#9b-i18n: every JS conflict notice converges on ONE translated msgid."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = "This changed elsewhere — reloaded to the latest."
OLD = "This changed elsewhere — refreshed to the latest."
OLD_PICKER = "This changed elsewhere — please reload."


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_stale_conflict_wordings_remain():
    for rel in (
        "courses/static/courses/js/editor.js",
        "courses/static/courses/js/media_picker.js",
        "courses/static/courses/js/builder.js",
        "templates/courses/manage/builder.html",
    ):
        body = _read(rel)
        assert OLD not in body, f"{rel} still has the 'refreshed' wording"
        assert OLD_PICKER not in body, f"{rel} still has the 'please reload' wording"


def test_editor_and_manager_emit_data_msg_conflict():
    assert "data-msg-conflict" in _read("templates/courses/manage/editor/editor.html")
    assert "data-msg-conflict" in _read("templates/courses/manage/media/manager.html")


def test_canonical_wording_present_as_fallback():
    assert CANON in _read("courses/static/courses/js/editor.js")
    assert CANON in _read("courses/static/courses/js/media_picker.js")
