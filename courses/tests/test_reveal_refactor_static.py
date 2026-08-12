from pathlib import Path

SRC = Path("courses/static/courses/js/reveal.js").read_text(encoding="utf-8")


def test_exports_cascade():
    assert "window.libliRevealCascade" in SRC


def test_click_enhancement_is_narrowed_to_plain_gate():
    # The click-binding selector must not match the fill-gate container. NOTE: this is a
    # source-presence guard only; the BEHAVIORAL no-grading-bypass guarantee (clicking
    # inside the fill-gate container reveals nothing) is asserted by Task 12 e2e item 4.
    assert "button.reveal-gate[data-reveal-gate]" in SRC


def test_focus_targets_fill_gate_input():
    # Focus resolution must special-case a fill-gate (its <div> is not focusable).
    assert "data-fillgate" in SRC and 'input[name="blank"]' in SRC


def test_focus_targets_fill_table_input():
    # Focus resolution must special-case a fill-table gate -- its <div> is not
    # focusable. The :not([disabled]) qualifier is defensive: a disabled input
    # cannot take focus, and cascadeFrom only ever calls focusTargetIn on a
    # just-revealed wrapper, so no reachable path reaches it with disabled
    # inputs today. Pinned so the qualifier is not "cleaned up" later.
    assert "data-filltablegate" in SRC
    assert ".filltable__input:not([disabled])" in SRC
