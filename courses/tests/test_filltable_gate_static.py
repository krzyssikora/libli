"""Source guards for the fill-table gate's client side.

A boot flag that is never assigned makes lesson_unit.html's watchdog disarm the
pre-hide on EVERY load, quietly defeating it -- with no visible symptom, because
the content is merely revealed early.
"""

from pathlib import Path

SRC = Path("courses/static/courses/js/filltable.js").read_text(encoding="utf-8")


def test_boot_flag_is_assigned():
    assert "window.__fillTableBooted = true" in SRC


def test_cascade_call_is_guarded_by_the_gate_attribute():
    # Without the attribute guard an UNGATED table also cascades, moving focus
    # and scrolling on every correct answer.
    assert 'hasAttribute("data-reveal-gate")' in SRC
    assert "window.libliRevealCascade" in SRC


def test_save_flag_stays_done_only():
    # _val_done strips anything else; writing `open` here would be dead code.
    assert "saveFlag(root, { done: true })" in SRC


def test_cascade_keeps_the_solved_table_on_screen():
    # cascadeFrom reads `hideWrapper = opts.hideWrapper !== false`, so OMITTING
    # the option means TRUE: gateWrap.hidden = true, and app.css:1125
    # (.lesson-block[hidden] { display: none !important }) deletes the solved
    # table and its notes from the page. For a button gate that is right -- the
    # control has been consumed. For a fill-table the wrapper IS the student's
    # work. Nothing else catches this: the restore path recomputes hideWrapper
    # itself as gate.matches(RESTORABLE) and is immune.
    assert "{ hideWrapper: false }" in SRC
