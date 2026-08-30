"""The command's contract: dry-run, repointing, idempotency, reporting."""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError

from courses.models import ContentNode
from courses.models import Element
from courses.models import MathElement
from courses.models import SpoilerElement
from courses.models import TableElement
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db

RULED = ' style="border-bottom: 1px solid black;"'


def _source(tmp_path, name="130_x.html", body=None):
    body = body or (
        f'<table class="my_table_noborder"><tr{RULED}>'
        r"<td>\(7\)</td><td>\(4\)</td></tr>"
        r"<tr><td>\(6\)</td><td>\(\)</td></tr></table>"
    )
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


def _marked(column):
    """The `_source` table with the highlight on one of the two top cells.

    Same cell TEXT either way, so both files land under one text key -- the only
    difference is which cell carries `\\htmlClass`.
    """
    attrs = ["", ""]
    attrs[column] = ' class="red_on_yellow"'
    return (
        f'<table class="my_table_noborder"><tr{RULED}>'
        rf"<td{attrs[0]}>\(7\)</td><td{attrs[1]}>\(4\)</td></tr>"
        r"<tr><td>\(6\)</td><td>\(\)</td></tr></table>"
    )


def _course_with_table(cells, slug="mat-pp"):
    """A table join NESTED in a spoiler -- the shape all 71 real elements take.

    Every one of the converted elements sits inside a spoiler, so it carries a
    `parent` and `tab_id`. A flat join asserts `parent_id is None` against a
    field nothing ever set, and never exercises that
    `Element.objects.filter(unit_id__in=...)` reaches nested joins at all --
    which is the mechanism the whole real run depended on (children KEEP their
    `unit` FK, see the Element docstring).

    `"math"` is in `builder.NESTABLE_TYPE_KEYS` (courses/builder.py:94), so the
    repointed element is legal inside a spoiler and stays exportable.
    """
    course = CourseFactory(slug=slug)
    part = ContentNode.objects.create(
        course=course, parent=None, order=0, kind="part", title="Wielomiany"
    )
    unit = ContentNode.objects.create(
        course=course, parent=part, order=0, kind="unit", title="U", unit_type="lesson"
    )
    spoiler = SpoilerElement.objects.create(label="Rozwiazanie")
    spoiler_join = Element.objects.create(unit=unit, content_object=spoiler, order=0)
    table = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": cells})
    )
    join = Element.objects.create(
        unit=unit,
        content_object=table,
        order=3,
        title="T",
        parent=spoiler_join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    return course, part, unit, table, join


def _cells():
    return [
        [{"html": r"\(7\)"}, {"html": r"\(4\)"}],
        [{"html": r"\(6\)"}, {"html": r"\(\)"}],
    ]


def _run(part, src, **kw):
    call_command(
        "convert_long_division",
        course="mat-pp",
        part_id=part.pk,
        source_dir=str(src),
        **kw,
    )


def test_dry_run_changes_nothing(tmp_path):
    _, part, _, table, join = _course_with_table(_cells())
    _run(part, _source(tmp_path))
    join.refresh_from_db()
    assert join.content_type == ContentType.objects.get_for_model(TableElement)
    assert join.object_id == table.pk
    assert MathElement.objects.count() == 0


def test_apply_repoints_the_join_and_keeps_the_table_row(tmp_path):
    _, part, _, table, join = _course_with_table(_cells())
    _run(part, _source(tmp_path), apply=True)
    join.refresh_from_db()
    assert join.content_type == ContentType.objects.get_for_model(MathElement)
    assert join.content_object.latex.startswith("\\begin{array}{rr}")
    # NEVER deleted: the orphan row is the revert path.
    assert TableElement.objects.filter(pk=table.pk).exists()


def test_apply_preserves_position_and_title(tmp_path):
    # The spec names `parent` and `tab_id` as binding: the join must stay in the
    # spoiler it was in. `save(update_fields=["content_type", "object_id"])`
    # keeps them by construction -- this is the test that would catch a rewrite
    # to a full save() of a re-fetched or reconstructed row.
    _, part, unit, _, join = _course_with_table(_cells())
    parent_id = join.parent_id
    assert parent_id is not None  # the fixture really is nested
    _run(part, _source(tmp_path), apply=True)
    join.refresh_from_db()
    # ... and the conversion really ran. Without this every assertion below is
    # also satisfied by a run that found nothing to convert -- MEASURED: a filter
    # that skips nested joins leaves the whole test green.
    assert join.content_type == ContentType.objects.get_for_model(MathElement)
    assert join.unit_id == unit.pk
    assert join.order == 3
    assert join.title == "T"
    assert join.parent_id == parent_id
    assert join.tab_id == SpoilerElement.SLOT_ID


def _table():
    return TableElement.objects.create(
        data=TableElement.normalize_data({"cells": _cells()})
    )


def _offset_sequences(table_ahead_by):
    """Leave the TableElement pk sequence exactly `table_ahead_by` ahead of the
    MathElement one (negative puts MathElement ahead).

    Postgres sequences are NOT rolled back with the test transaction -- only the
    rows are -- so the gap between two models' sequences when a test starts is
    whatever the tests that ran before it on this xdist worker happened to leave.
    Under `-n auto` xdist's default `load` scheduler hands each test to whichever
    worker is free, so that set is TIMING-dependent and varies run to run on one
    commit. This helper makes the gap an INPUT instead of an accident.

    Levelling first is what makes the offset absolute rather than relative to an
    unknown starting gap: each pass bumps whichever sequence is behind by exactly
    one, so the gap shrinks by one and the loop terminates.
    """
    t, m = _table(), MathElement.objects.create(latex="x")
    while t.pk != m.pk:
        if t.pk < m.pk:
            t = _table()
        else:
            m = MathElement.objects.create(latex="x")
    for _ in range(abs(table_ahead_by)):
        if table_ahead_by > 0:
            _table()
        else:
            MathElement.objects.create(latex="x")


@pytest.mark.parametrize("table_ahead_by", [-3, 0, 1, 2, 3, 4, 8])
def test_apply_prints_the_pk_it_overwrote(tmp_path, capsys, table_ahead_by):
    # The orphaned TableElement is the whole revert path, and the repoint is the
    # last moment anything knows which row it is -- --list-matches carries the
    # join, the unit and the source ident, none of which name it. The mat-pp run
    # shipped without this line and its map had to be reconstructed from content.
    #
    # `table=<old> -> math=<new>` must not be satisfiable by the two pks
    # COINCIDING, or a command that printed one pk in both slots would pass. The
    # parametrisation is the regression: this held only by luck until 2026-08-30,
    # when CI hit `assert 11 != 11` on a green branch that touches none of this.
    _offset_sequences(table_ahead_by)
    _, part, unit, table, join = _course_with_table(_cells())
    # Build the table FIRST, then drive the math sequence past its pk. A fixed
    # count of spare rows cannot do this: it separates the two sequences only when
    # they already started close, and collides outright when the table sequence
    # leads by exactly the count. Bumping until the pk is provably greater makes
    # the command's own MathElement land strictly higher whatever came before.
    while True:
        if MathElement.objects.create(latex="x").pk > table.pk:
            break
    _run(part, _source(tmp_path), apply=True)
    join.refresh_from_db()
    assert table.pk != join.object_id
    out = capsys.readouterr().out
    expected = f"el={join.pk} unit={unit.pk} table={table.pk} -> math={join.object_id}"
    assert expected in out


def test_second_run_converts_nothing(tmp_path):
    _, part, _, _, _ = _course_with_table(_cells())
    src = _source(tmp_path)
    _run(part, src, apply=True)
    assert MathElement.objects.count() == 1
    _run(part, src, apply=True)
    assert MathElement.objects.count() == 1


def test_an_unresolvable_table_aborts_the_whole_run(tmp_path):
    # The gate between an unresolvable table and a WRONG write, and the only
    # thing that makes "refuses to write and reports" true of the COMMAND rather
    # than of `resolve` alone. Two source tables, identical cell text, the
    # highlight on a different cell: one text key, two distinct marked LaTeX
    # strings, no unmarked variant to fall back on -- `resolve` returns None.
    _, part, _, table, join = _course_with_table(_cells())
    (tmp_path / "130_x.html").write_text(_marked(0), encoding="utf-8")
    (tmp_path / "131_x.html").write_text(_marked(1), encoding="utf-8")
    with pytest.raises(CommandError, match="nothing written"):
        _run(part, tmp_path, apply=True)
    # ... and --apply really did write nothing.
    assert MathElement.objects.count() == 0
    join.refresh_from_db()
    assert join.content_type == ContentType.objects.get_for_model(TableElement)
    assert join.object_id == table.pk


def test_a_table_outside_the_part_is_untouched(tmp_path):
    course, part, _, _, _ = _course_with_table(_cells())
    other = ContentNode.objects.create(
        course=course, parent=None, order=1, kind="part", title="Other"
    )
    other_unit = ContentNode.objects.create(
        course=course, parent=other, order=0, kind="unit", title="O", unit_type="lesson"
    )
    t2 = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": _cells()})
    )
    j2 = Element.objects.create(unit=other_unit, content_object=t2)
    _run(part, _source(tmp_path), apply=True)
    j2.refresh_from_db()
    assert j2.content_type == ContentType.objects.get_for_model(TableElement)


def test_a_source_table_with_no_stored_counterpart_is_reported(tmp_path, capsys):
    # The real run hits this twice: 450#2 and 450#5, whose lesson was rewritten
    # by hand. It must be reported, never invented.
    _course_with_table(_cells())
    part = ContentNode.objects.get(title="Wielomiany")
    src = _source(tmp_path)
    (src / "450_x.html").write_text(
        f'<table class="my_table_noborder"><tr{RULED}>'
        r"<td>\(x^2\)</td></tr><tr><td>\(y\)</td></tr></table>",
        encoding="utf-8",
    )
    _run(part, src)
    out = capsys.readouterr().out
    assert "450_x#0" in out
    assert "no stored counterpart" in out


def test_an_already_applied_rerun_reports_nothing_absent(tmp_path, capsys):
    # Re-running after --apply leaves no TableElement joins in the subtree, so
    # nothing matches and EVERY source table is absent from the converted set.
    # Reported naively that is the whole corpus (73 lines on mat-pp) printed as
    # lost content, immediately before `converted 0`.
    _course_with_table(_cells())
    part = ContentNode.objects.get(title="Wielomiany")
    src = _source(tmp_path)
    (src / "450_x.html").write_text(
        f'<table class="my_table_noborder"><tr{RULED}>'
        r"<td>\(x^2\)</td></tr><tr><td>\(y\)</td></tr></table>",
        encoding="utf-8",
    )
    _run(part, src, apply=True)
    capsys.readouterr()  # the first run legitimately reports 450_x#0 absent
    _run(part, src, apply=True)
    out = capsys.readouterr().out
    assert "no stored counterpart" not in out
    assert "already applied" in out


def test_a_byte_identical_twin_is_not_reported_absent(tmp_path, capsys):
    # `resolve` returns the FIRST of several byte-identical plain candidates, so
    # the twins stay unclaimed by ident while their content is fully converted.
    # Keying absence on ident would report them as lost content. MEASURED on the
    # real corpus: 150#0 and 155#0 are the same 204 characters, 150#1 and 155#1
    # the same 307 -- ident-keyed reports 4 absent, latex-keyed reports the 2 that
    # genuinely have none.
    _course_with_table(_cells())
    part = ContentNode.objects.get(title="Wielomiany")
    src = _source(tmp_path)
    twin = (src / "130_x.html").read_text(encoding="utf-8")
    (src / "155_x.html").write_text(twin, encoding="utf-8")  # same table, other file
    _run(part, src)
    out = capsys.readouterr().out
    assert "155_x#0" not in out
    assert "no stored counterpart" not in out


def test_converted_element_renders_as_a_katex_math_block(tmp_path):
    # Rendered through the DISPATCH, not by template name: ElementBase.render
    # picks `courses/elements/{self._meta.model_name}.html`, so the repoint is
    # what selects mathelement.html over tableelement.html. Naming the template
    # here would make `el--table not in html` true by construction and leave a
    # repoint that produced an unrenderable element passing every test above.
    _, part, _, _, join = _course_with_table(_cells())
    _run(part, _source(tmp_path), apply=True)
    join.refresh_from_db()
    html = join.content_object.render(element=join)
    assert 'class="el el--math"' in html
    assert "data-katex" in html
    assert "\\begin{array}{rr}" in html
    assert "el--table" not in html
