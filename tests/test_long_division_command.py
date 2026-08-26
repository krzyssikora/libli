"""The command's contract: dry-run, repointing, idempotency, reporting."""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command

from courses.models import ContentNode
from courses.models import Element
from courses.models import MathElement
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


def _course_with_table(cells, slug="mat-pp"):
    course = CourseFactory(slug=slug)
    part = ContentNode.objects.create(
        course=course, parent=None, order=0, kind="part", title="Wielomiany"
    )
    unit = ContentNode.objects.create(
        course=course, parent=part, order=0, kind="unit", title="U", unit_type="lesson"
    )
    table = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": cells})
    )
    join = Element.objects.create(unit=unit, content_object=table, order=3, title="T")
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
    _, part, unit, _, join = _course_with_table(_cells())
    _run(part, _source(tmp_path), apply=True)
    join.refresh_from_db()
    assert join.unit_id == unit.pk
    assert join.order == 3
    assert join.title == "T"
    assert join.parent_id is None


def test_second_run_converts_nothing(tmp_path):
    _, part, _, _, _ = _course_with_table(_cells())
    src = _source(tmp_path)
    _run(part, src, apply=True)
    assert MathElement.objects.count() == 1
    _run(part, src, apply=True)
    assert MathElement.objects.count() == 1


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
    # The join is repointed, so the element template that runs for it changes
    # from tableelement.html to mathelement.html. Without this, a repoint that
    # produced an unrenderable element would still pass every test above.
    from django.template.loader import render_to_string

    _, part, _, _, join = _course_with_table(_cells())
    _run(part, _source(tmp_path), apply=True)
    join.refresh_from_db()
    html = render_to_string(
        "courses/elements/mathelement.html", {"el": join.content_object}
    )
    assert 'class="el el--math"' in html
    assert "data-katex" in html
    assert "\\begin{array}{rr}" in html
    assert "el--table" not in html
