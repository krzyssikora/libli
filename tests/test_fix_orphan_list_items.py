"""The one-off repair of the list structure the LAL import broke.

Bodies are planted with QuerySet.update(): TextElement.save() runs normalize_body,
which would repair them on the way in (wrapping the run in a bare <ul> -- the very
guess this command exists to replace with the source's answer).
"""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from courses.models import ContentNode
from courses.models import Element
from courses.models import TextElement
from tests.factories import make_course_with_unit

SOURCE = """<html><body>
<ol class="bold">
  <li>Rozwiązanie dla kąta ostrego <img src="static/a.png"/></li>
  <li>Wysokość wyliczamy z sinusa kąta</li>
  <li>Kończymy podstawiając wysokość</li>
</ol>
<ul><li>punkt przecięcia z osią OX</li></ul>
<ol start="3"><li>jak dzielić wielomiany?</li><li>czy dane wyrażenie dzieli</li></ol>
<ol><li>tak</li></ol><ol><li>tak</li></ol>
</body></html>"""

ORPHAN_OL = (
    "<p></p><li>\n Wysokość wyliczamy z sinusa kąta\n</li>\n"
    "<li>Kończymy podstawiając wysokość</li>\n<p>dalej</p>"
)
FIXED_OL = (
    '<ol start="2"><li>\n Wysokość wyliczamy z sinusa kąta\n</li>\n'
    "<li>Kończymy podstawiając wysokość</li></ol>\n<p>dalej</p>"
)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "lal"
    (root / "100_geometria_2").mkdir(parents=True)
    (root / "100_geometria_2" / "130_pole.html").write_text(SOURCE, encoding="utf-8")
    return root


@pytest.fixture
def scene():
    course, unit = make_course_with_unit(slug="mat-pp")
    old = timezone.now() - timezone.timedelta(days=30)
    ContentNode.objects.filter(pk=unit.pk).update(updated=old)
    return course, unit, old


def _text(unit, body):
    te = TextElement.objects.create(body="<p>x</p>")
    Element.objects.create(unit=unit, title="", content_object=te)
    TextElement.objects.filter(pk=te.pk).update(body=body)
    return te


def _run(source, **kw):
    call_command(
        "fix_orphan_list_items", course="mat-pp", source_root=str(source), **kw
    )


def _body(te):
    return TextElement.objects.get(pk=te.pk).body


@pytest.mark.django_db
def test_orphan_run_takes_the_source_list_and_number(scene, source, tmp_path):
    _c, unit, old = scene
    te = _text(unit, ORPHAN_OL)
    _run(source, snapshot=str(tmp_path / "s.json"))
    assert _body(te) == FIXED_OL
    unit.refresh_from_db()
    assert unit.updated > old


@pytest.mark.django_db
def test_a_bulleted_source_run_stays_bulleted(scene, source, tmp_path):
    te = _text(scene[1], "<li>punkt przecięcia z osią OX</li>")
    _run(source, snapshot=str(tmp_path / "s.json"))
    assert _body(te) == "<ul><li>punkt przecięcia z osią OX</li></ul>"


@pytest.mark.django_db
def test_lost_author_start_is_restored(scene, source, tmp_path):
    te = _text(scene[1], "<ol><li>jak dzielić wielomiany?</li></ol>")
    _run(source, snapshot=str(tmp_path / "s.json"))
    assert _body(te) == '<ol start="3"><li>jak dzielić wielomiany?</li></ol>'


@pytest.mark.django_db
def test_a_list_already_starting_at_one_is_untouched(scene, source, tmp_path, capsys):
    te = _text(scene[1], "<ol><li>Rozwiązanie dla kąta ostrego</li></ol>")
    _run(source, dry_run=True)
    assert "0 field(s)" in capsys.readouterr().out
    assert _body(te) == "<ol><li>Rozwiązanie dla kąta ostrego</li></ol>"


@pytest.mark.django_db
def test_empty_paragraphs_are_dropped(scene, source, tmp_path):
    te = _text(scene[1], "<p></p>jak to zrobić?<p></p>")
    _run(source, snapshot=str(tmp_path / "s.json"))
    assert _body(te) == "jak to zrobić?"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "item",
    [
        "tak",  # ambiguous in the source AND too short to trust
        "nie ma tego w źródle wcale",  # absent
    ],
)
def test_an_unidentified_run_falls_back_to_ul_and_is_reported(
    scene, source, tmp_path, capsys, item
):
    te = _text(scene[1], f"<li>{item}</li>")
    _run(source, snapshot=str(tmp_path / "s.json"))
    assert _body(te) == f"<ul><li>{item}</li></ul>"
    out = capsys.readouterr().out
    assert "UNRESOLVED" in out and "1 run(s) not found" in out


@pytest.mark.django_db
def test_dry_run_writes_nothing(scene, source, capsys):
    te = _text(scene[1], ORPHAN_OL)
    _run(source, dry_run=True)
    assert _body(te) == ORPHAN_OL
    out = capsys.readouterr().out
    assert "[dry-run] nothing written" in out and repr(FIXED_OL) in out


@pytest.mark.django_db
def test_a_write_run_without_a_snapshot_is_refused(scene, source):
    te = _text(scene[1], ORPHAN_OL)
    with pytest.raises(CommandError, match="--snapshot"):
        _run(source)
    assert _body(te) == ORPHAN_OL


@pytest.mark.django_db
def test_a_missing_source_root_is_refused(scene, tmp_path):
    with pytest.raises(CommandError, match="--source-root"):
        _run(tmp_path / "nope", dry_run=True)


@pytest.mark.django_db
def test_restore_puts_every_field_back_byte_identical(scene, source, tmp_path):
    te = _text(scene[1], ORPHAN_OL)
    snap = tmp_path / "s.json"
    _run(source, snapshot=str(snap))
    assert json.loads(snap.read_text(encoding="utf-8"))
    call_command("fix_orphan_list_items", restore=str(snap))
    assert _body(te) == ORPHAN_OL


@pytest.mark.django_db
def test_a_second_run_finds_nothing(scene, source, tmp_path, capsys):
    _text(scene[1], ORPHAN_OL)
    _run(source, snapshot=str(tmp_path / "s.json"))
    capsys.readouterr()
    _run(source, dry_run=True)
    assert "0 field(s)" in capsys.readouterr().out
