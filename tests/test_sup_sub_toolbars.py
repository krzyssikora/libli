"""Every toolbar whose output keeps <sup>/<sub> offers both buttons."""

import re
from pathlib import Path

import pytest

EDITOR_TEMPLATES = Path("templates/courses/manage/editor")
CMDS = ("superscript", "subscript")
ICONS = {"superscript": "ed-superscript", "subscript": "ed-subscript"}

PROSE_TOOLBARS = (
    "_rte_toolbar.html",
    "_edit_text.html",
    "_edit_callout.html",
    "_edit_spoiler.html",
)
CELL_TOOLBARS = ("_edit_table.html", "_edit_filltable.html")


def _button(template, cmd):
    source = (EDITOR_TEMPLATES / template).read_text(encoding="utf-8")
    match = re.search(rf'<button[^>]*data-cmd="{cmd}"[^>]*>.*?</button>', source)
    assert match, f'{template} has no data-cmd="{cmd}" button'
    return match.group(0)


@pytest.mark.parametrize("cmd", CMDS)
@pytest.mark.parametrize("template", PROSE_TOOLBARS + CELL_TOOLBARS)
def test_toolbar_has_the_button_with_its_icon(template, cmd):
    assert f'href="#{ICONS[cmd]}"' in _button(template, cmd)


@pytest.mark.parametrize("cmd", CMDS)
@pytest.mark.parametrize("template", CELL_TOOLBARS)
def test_cell_toolbar_button_starts_disabled(template, cmd):
    # With no cell focused there is nothing for it to act on; wire() enables it.
    assert " disabled" in _button(template, cmd)


@pytest.mark.parametrize("cmd", CMDS)
def test_both_icons_are_defined(cmd):
    editor = (EDITOR_TEMPLATES / "editor.html").read_text(encoding="utf-8")
    assert f'<symbol id="{ICONS[cmd]}"' in editor


@pytest.mark.parametrize("cmd", CMDS)
def test_caption_toolbar_has_no_such_button(cmd):
    # sanitize_caption would strip the output: the button would silently do nothing.
    caption = (EDITOR_TEMPLATES / "_rte_toolbar_caption.html").read_text(
        encoding="utf-8"
    )
    assert f'data-cmd="{cmd}"' not in caption
