"""The one-off rewrite of legacy Open edX `jump_to_id` links.

The links are `<a href="/jump_to_id/<32-hex>">` left in mat-pp by the LAL
import. Each hex is an Open edX `url_name`; the mapping from hex to libli node
was derived from the surviving Studio outline and verified by hand, and ships
beside the command as data.

The failure this module exists to prevent is NOT "the rewrite crashes" -- it is
a target pk that has since moved, silently repointing a link at an unrelated
lesson. That is undetectable by reading the result, so the command refuses the
whole run on any drift rather than rewriting what it can.
"""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from courses.models import Element
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

HEX_A = "a" * 32
HEX_B = "b" * 32


def _link(hexid, text="tutaj"):
    return f'<p>Zobacz <a href="/jump_to_id/{hexid}">{text}</a>.</p>'


@pytest.fixture
def scene():
    """A course with one lesson holding a legacy link, and a target unit."""
    course, unit = make_course_with_unit(slug="mat-pp")
    target = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Cel"
    )
    te = TextElement.objects.create(body=_link(HEX_A))
    Element.objects.create(unit=unit, title="", content_object=te)
    return course, unit, target, te


def _map_file(tmp_path, target, *, title=None, extra=None):
    doc = {
        "course_slug": "mat-pp",
        "targets": {
            HEX_A: {
                "node_pk": target.pk,
                "title": title if title is not None else target.title,
                "kind": target.kind,
                "edx_name": "Cel",
                "uses": 1,
            }
        },
    }
    if extra:
        doc["targets"].update(extra)
    p = tmp_path / "map.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _run(tmp_path, mapfile, **kw):
    args = {"map": mapfile}
    args.update(kw)
    call_command("fix_jump_to_id_links", **args)


def test_the_link_is_rewritten_to_the_mapped_permalink(scene, tmp_path):
    _course, _unit, target, te = scene
    _run(tmp_path, _map_file(tmp_path, target), snapshot=str(tmp_path / "s.json"))
    te.refresh_from_db()
    assert f'href="/courses/n/{target.pk}/"' in te.body
    assert "jump_to_id" not in te.body


def test_the_anchor_text_is_left_alone(scene, tmp_path):
    """Only the href moves. The visible words are the author's copy, and this
    command has no business touching them."""
    _course, _unit, target, te = scene
    _run(tmp_path, _map_file(tmp_path, target), snapshot=str(tmp_path / "s.json"))
    te.refresh_from_db()
    assert ">tutaj</a>" in te.body


def test_an_absolute_localhost_href_is_rewritten_too(scene, tmp_path):
    """31 of the 32 real links are relative and one is absolute
    (http://127.0.0.1:8000/jump_to_id/...). A pattern anchored at the leading
    slash silently leaves that one behind -- and it is the shape the bug was
    first reported as.
    """
    _course, _unit, target, te = scene
    te.body = f'<p><a href="http://127.0.0.1:8000/jump_to_id/{HEX_A}">tu</a></p>'
    te.save()
    _run(tmp_path, _map_file(tmp_path, target), snapshot=str(tmp_path / "s.json"))
    te.refresh_from_db()
    assert f'href="/courses/n/{target.pk}/"' in te.body
    assert "127.0.0.1" not in te.body


def test_a_drifted_target_title_aborts_the_whole_run(scene, tmp_path):
    """THE guard. A pk that has moved since the mapping was verified would
    repoint a link at an unrelated lesson, and nothing about the result would
    look wrong. Recording the title and re-checking it is what turns that
    silent mis-point into a refusal.
    """
    _course, _unit, target, te = scene
    before = te.body
    mapfile = _map_file(tmp_path, target, title="A different title entirely")
    with pytest.raises(CommandError, match="title"):
        _run(tmp_path, mapfile, snapshot=str(tmp_path / "s.json"))
    te.refresh_from_db()
    assert te.body == before  # nothing written


def test_an_unmapped_id_in_the_database_aborts_the_run(scene, tmp_path):
    """Refuse rather than rewrite what is known and leave the rest. A partial
    pass looks successful and leaves dead links nobody goes back for.
    """
    _course, unit, target, _te = scene
    orphan = TextElement.objects.create(body=_link(HEX_B))
    Element.objects.create(unit=unit, title="", content_object=orphan)
    with pytest.raises(CommandError, match=HEX_B[:8]):
        _run(tmp_path, _map_file(tmp_path, target), snapshot=str(tmp_path / "s.json"))
    orphan.refresh_from_db()
    assert HEX_B in orphan.body


def test_a_target_in_another_course_aborts_the_run(scene, tmp_path):
    """Scoped to mat-pp. A pk that resolves to some other course's node is the
    same silent mis-point as a drifted title, one step further out."""
    _course, _unit, _target, te = scene
    foreign = ContentNodeFactory(
        course=CourseFactory(slug="other"), kind="unit", unit_type="lesson", parent=None
    )
    mapfile = _map_file(tmp_path, foreign)
    with pytest.raises(CommandError, match="course"):
        _run(tmp_path, mapfile, snapshot=str(tmp_path / "s.json"))


def test_dry_run_writes_nothing_and_needs_no_snapshot(scene, tmp_path):
    _course, _unit, target, te = scene
    before = te.body
    _run(tmp_path, _map_file(tmp_path, target), dry_run=True)
    te.refresh_from_db()
    assert te.body == before


def test_a_write_run_without_a_snapshot_is_refused(scene, tmp_path):
    """The snapshot is the only way back. Making it optional means the one run
    that needed it is the one that did not take it."""
    _course, _unit, target, te = scene
    with pytest.raises(CommandError, match="snapshot"):
        _run(tmp_path, _map_file(tmp_path, target))


def test_restore_puts_every_body_back_byte_identical(scene, tmp_path):
    """A snapshot nobody can apply is not a rollback. Byte-identical, because
    'close enough' on a rich-text body is a silent content edit."""
    _course, _unit, target, te = scene
    before = te.body
    snap = str(tmp_path / "s.json")
    _run(tmp_path, _map_file(tmp_path, target), snapshot=snap)
    te.refresh_from_db()
    assert te.body != before

    call_command("fix_jump_to_id_links", restore=snap)
    te.refresh_from_db()
    assert te.body == before


def test_the_report_names_every_rewritten_anchor_and_its_new_target(scene, tmp_path):
    """The verification list. Lesson URLs alone say where to look; the anchor
    text and its new target are what make a link checkable at a glance."""
    _course, unit, target, _te = scene
    report = tmp_path / "r.json"
    _run(
        tmp_path,
        _map_file(tmp_path, target),
        snapshot=str(tmp_path / "s.json"),
        report=str(report),
    )
    doc = json.loads(report.read_text(encoding="utf-8"))
    row = doc["lessons"][0]
    assert row["unit_pk"] == unit.pk
    assert row["url"].endswith(f"/courses/n/{unit.pk}/")
    assert row["anchors"][0]["text"] == "tutaj"
    assert row["anchors"][0]["new_href"] == f"/courses/n/{target.pk}/"


def test_restore_is_byte_identical_even_for_a_body_save_would_rewrite(scene, tmp_path):
    """Pins `.update()` over `.save()` on the restore path.

    TextElement.save() runs normalize_body, which strips event handlers and
    collapses a visually-empty body to "". Restoring through save() would
    therefore "restore" a body the database never held -- a silent content edit
    performed by the rollback. The row is seeded through .update() because
    save() would sanitise it on the way in, which is exactly how such a row
    comes to exist in the first place.
    """
    _course, _unit, target, te = scene
    dirty = f'<p onclick="x()">Zobacz <a href="/jump_to_id/{HEX_A}">tutaj</a>.</p>'
    TextElement.objects.filter(pk=te.pk).update(body=dirty)

    snap = str(tmp_path / "s.json")
    _run(tmp_path, _map_file(tmp_path, target), snapshot=snap)
    call_command("fix_jump_to_id_links", restore=snap)

    te.refresh_from_db()
    assert te.body == dirty
