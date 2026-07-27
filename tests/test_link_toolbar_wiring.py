from pathlib import Path

TEXT_TOOLBAR = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "js"
    / "text_toolbar.js"
)


def test_prompt_is_gone():
    assert "window.prompt" not in TEXT_TOOLBAR.read_text(encoding="utf-8")


def test_guards_on_both_modules():
    # The dialog's export is a capability signal; the same reasoning extends to the
    # second module. Without this, a missing script tag or a collectstatic gap opens
    # the dialog and then throws when the result comes back.
    src = TEXT_TOOLBAR.read_text(encoding="utf-8")
    assert "window.libliLinkDialog" in src
    assert "window.libliLinkApply" in src


def test_detached_surface_surfaces_the_conflict_message():
    # The spec's error table promises "the result is discarded with the existing
    # conflict message". A bare `return` is the same data loss with no feedback.
    src = TEXT_TOOLBAR.read_text(encoding="utf-8")
    assert "data-msg-conflict" in src
    assert "op-error" in src


def test_range_is_cloned():
    # getRangeAt(0) returns the selection's LIVE Range, and showModal() focuses the
    # dialog's first focusable child, which collapses/replaces the document selection
    # -- mutating the very object the insertion and the dismissal caret-restore rely
    # on. The math command has the same unguarded pattern, but its modal is a plain
    # div, not a showModal() dialog.
    src = TEXT_TOOLBAR.read_text(encoding="utf-8")
    assert "cloneRange()" in src
