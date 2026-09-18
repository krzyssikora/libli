"""The one-off removal of the space the LAL import left before punctuation.

The LAL source HTML was pretty-printed, and the importer copied its whitespace
verbatim, so `<strong>naturalne</strong>.` was stored as

    <strong>
        naturalne
    </strong>
    .

which a browser renders as "naturalne ." -- the whitespace INSIDE the closing
tag renders too, so both runs have to go. The failure this module guards is the
opposite one: a rewrite that reaches into LaTeX (where `\\\\ ,` -> `\\\\,` is a
spacing command), into an answer key, or into a division sign `6 : 2`.
"""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from courses.management.commands.fix_space_before_punctuation import tighten
from courses.models import Blank
from courses.models import ContentNode
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import FillTableElement
from courses.models import MathElement
from courses.models import SwitchGateElement
from courses.models import SwitchGridElement
from courses.models import TableElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

# --- the pure rewrite ---------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # the reported shape: whitespace inside AND after the closing tag
        (
            "są\n    <strong>\n        naturalne\n    </strong>\n    .\n</p>",
            "są\n    <strong>\n        naturalne</strong>.\n</p>",
        ),
        ("<u>x</u>\n , czyli", "<u>x</u>, czyli"),
        ('<a href="/n/1/">\n tablic\n </a>\n .', '<a href="/n/1/">\n tablic</a>.'),
        ("<em>a</em>\n :\n</p>", "<em>a</em>:\n</p>"),
        # nested closing tags
        ("<strong><u>x </u></strong> ?", "<strong><u>x</u></strong>?"),
        # after inline maths and after a gate slot sentinel
        (r"\(3\) , bo", r"\(3\), bo"),
        ("￿0￿\n                .", "￿0￿."),
        # plain text, every mark in the set
        ("a ; b", "a; b"),
        ("a !", "a!"),
        ("(np. 3 )", "(np. 3)"),
    ],
)
def test_tighten_removes_the_space_before_punctuation(before, after):
    assert tighten(before) == (after, 1)


@pytest.mark.parametrize(
    "text",
    [
        # inside maths: KaTeX ignores it, and `\\ ,` -> `\\,` changes the maths
        r"\(a \\ , b\)",
        r"\[ f(x) , g(x) \]",
        "$$ a , b $$",
        # an ellipsis, and a mark after one
        "1, 5, 13, ...",
        "czy wolno ... ?",
        r"\(a_{n-1}\),... , \(a_2\)",
        # a division sign or ratio written on one line
        "6 : 2 = 3",
        # a mark opening a line or following a block tag is not "after a word"
        "<p>\n    ?",
        "<br>\n , dalej",
        "</li>\n .",
        # inside a tag's attributes
        '<a title="a , b" href="/x/">t</a>',
        # quotes and an opening bracket are never touched
        "to „słowo” i ( nawias",
        # a non-breaking space is deliberate
        "a&nbsp;:",
        # found in the mat-pp dry run: a mark listed or quoted as a SYMBOL,
        # an emoticon, and brackets spaced on both sides on purpose
        "spośród: !, @, #",
        "oraz ? możemy",
        "najładniejszy? ;) Jego",
        "jeśli ( założenie ) to ( teza )",
    ],
)
def test_tighten_leaves_these_alone(text):
    assert tighten(text) == (text, 0)


def test_tighten_counts_every_fix_in_one_string():
    assert tighten("<b>a</b> , <b>b</b> .") == ("<b>a</b>, <b>b</b>.", 2)


# --- the command --------------------------------------------------------------


BAD = "<p>są <strong>\n naturalne\n </strong>\n .</p>"
GOOD = "<p>są <strong>\n naturalne</strong>.</p>"


def _add(unit, obj):
    Element.objects.create(unit=unit, title="", content_object=obj)
    return obj


@pytest.fixture
def scene():
    course, unit = make_course_with_unit(slug="mat-pp")
    old = timezone.now() - timezone.timedelta(days=30)
    ContentNode.objects.filter(pk=unit.pk).update(updated=old)
    te = _add(unit, TextElement.objects.create(body=BAD))
    return course, unit, te, old


def _run(**kw):
    call_command("fix_space_before_punctuation", course="mat-pp", **kw)


@pytest.mark.django_db
def test_the_body_is_fixed_and_the_unit_marked_updated(scene, tmp_path):
    _c, unit, te, old = scene
    _run(snapshot=str(tmp_path / "s.json"))
    te.refresh_from_db()
    unit.refresh_from_db()
    assert te.body == GOOD
    assert unit.updated > old


@pytest.mark.django_db
def test_every_display_field_is_fixed(scene, tmp_path):
    _c, unit, _te, _old = scene
    gate = _add(unit, SwitchGateElement.objects.create(stem="x ￿0￿ .", options=["a"]))
    grid = _add(
        unit,
        SwitchGridElement.objects.create(
            prompt="p",
            lines=[{"stem": "￿0￿ .", "cyclers": [{"options": ["a"], "answer": 0}]}],
        ),
    )
    table = _add(
        unit,
        TableElement.objects.create(
            data={
                "cells": [[{"html": "<b>a</b> ,", "halign": "left"}]],
                "border": "rows",
            }
        ),
    )
    q = _add(
        unit,
        FillBlankQuestionElement.objects.create(stem="<u>x</u> .", explanation="y ."),
    )
    _run(snapshot=str(tmp_path / "s.json"))
    for o in (gate, grid, table, q):
        o.refresh_from_db()
    assert gate.stem == "x ￿0￿."
    assert grid.lines[0]["stem"] == "￿0￿."
    assert grid.lines[0]["cyclers"] == [{"options": ["a"], "answer": 0}]
    assert table.data["cells"][0][0] == {"html": "<b>a</b>,", "halign": "left"}
    assert (q.stem, q.explanation) == ("<u>x</u>.", "y.")


@pytest.mark.django_db
def test_maths_answer_keys_and_fill_tables_are_not_touched(scene, tmp_path):
    _c, unit, _te, _old = scene
    math = _add(unit, MathElement.objects.create(latex="a , b"))
    q = _add(unit, FillBlankQuestionElement.objects.create(stem="s"))
    blank = Blank.objects.create(question=q, accepted="3 ,5")
    ft = _add(
        unit,
        FillTableElement.objects.create(data={"cells": [[{"html": "a ,"}]]}),
    )
    ft_data = FillTableElement.objects.get(pk=ft.pk).data
    _run(snapshot=str(tmp_path / "s.json"))
    assert MathElement.objects.get(pk=math.pk).latex == "a , b"
    assert Blank.objects.get(pk=blank.pk).accepted == "3 ,5"
    assert FillTableElement.objects.get(pk=ft.pk).data == ft_data


@pytest.mark.django_db
def test_another_course_is_not_touched(scene, tmp_path):
    _course, other_unit = make_course_with_unit(slug="inny")
    other = _add(other_unit, TextElement.objects.create(body=BAD))
    _run(snapshot=str(tmp_path / "s.json"))
    assert TextElement.objects.get(pk=other.pk).body == BAD


@pytest.mark.django_db
def test_the_write_bypasses_save_so_only_whitespace_changes(scene, tmp_path):
    """normalize_body would also rewrite an unsanitised body; the fix must not."""
    _c, unit, _te, _old = scene
    raw = '<p onclick="x">a <b>b</b> .</p>'
    te = TextElement.objects.create(body="")
    TextElement.objects.filter(pk=te.pk).update(body=raw)
    _add(unit, te)
    _run(snapshot=str(tmp_path / "s.json"))
    assert TextElement.objects.get(pk=te.pk).body == '<p onclick="x">a <b>b</b>.</p>'


@pytest.mark.django_db
def test_dry_run_writes_nothing_and_needs_no_snapshot(scene, capsys):
    _c, unit, te, old = scene
    _run(dry_run=True)
    te.refresh_from_db()
    unit.refresh_from_db()
    assert te.body == BAD
    assert unit.updated == old
    out = capsys.readouterr().out
    assert f"unit {unit.pk}" in out
    assert "1 fix(es)" in out


@pytest.mark.django_db
def test_dry_run_shows_only_fixes_that_will_be_written(scene, capsys):
    """A cycler option is an answer key: it must not appear as a planned fix."""
    _c, unit, _te, _old = scene
    _add(
        unit,
        SwitchGridElement.objects.create(
            prompt="p",
            lines=[
                {"stem": "slot .", "cyclers": [{"options": ["opcja ,"], "answer": 0}]}
            ],
        ),
    )
    _run(dry_run=True)
    out = capsys.readouterr().out
    assert "slot ." in out
    assert "opcja" not in out


@pytest.mark.django_db
def test_a_write_run_without_a_snapshot_is_refused(scene):
    with pytest.raises(CommandError, match="--snapshot"):
        _run()
    scene[2].refresh_from_db()
    assert scene[2].body == BAD


@pytest.mark.django_db
def test_an_unknown_course_is_refused(db):
    with pytest.raises(CommandError, match="no course"):
        _run(dry_run=True)


@pytest.mark.django_db
def test_restore_puts_every_field_back_byte_identical(scene, tmp_path):
    _c, unit, te, _old = scene
    grid = _add(
        unit,
        SwitchGridElement.objects.create(
            prompt="p", lines=[{"stem": "a .", "cyclers": []}]
        ),
    )
    snap = tmp_path / "s.json"
    _run(snapshot=str(snap))
    assert json.loads(snap.read_text(encoding="utf-8"))
    call_command("fix_space_before_punctuation", restore=str(snap))
    assert TextElement.objects.get(pk=te.pk).body == BAD
    assert SwitchGridElement.objects.get(pk=grid.pk).lines == [
        {"stem": "a .", "cyclers": []}
    ]


@pytest.mark.django_db
def test_a_second_run_finds_nothing(scene, tmp_path, capsys):
    _run(snapshot=str(tmp_path / "s.json"))
    capsys.readouterr()
    _run(dry_run=True)
    assert "0 fix(es)" in capsys.readouterr().out
