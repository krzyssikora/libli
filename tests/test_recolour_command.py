"""The command's contract: validation, the gate, dry-run, and the exclusions."""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from courses.models import ContentNode
from courses.models import Element
from courses.models import TextElement
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db

RED = '<span style="color: red;">założenie</span>'
STORED = "założenie"
COLOURED = '<span class="tc-red">założenie</span>'


def _out(tmp_path, files):
    for rel, payload in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), "utf-8")
    return tmp_path


def _course_with(body, part_title="P", slug="mat-pp"):
    course = CourseFactory(slug=slug)
    part = ContentNode.objects.create(
        course=course, parent=None, order=0, kind="part", title=part_title
    )
    ch = ContentNode.objects.create(
        course=course, parent=part, order=0, kind="chapter", title="C"
    )
    unit = ContentNode.objects.create(
        course=course, parent=ch, order=0, kind="unit", title="U", unit_type="lesson"
    )
    el = TextElement.objects.create(body=body)
    Element.objects.create(unit=unit, content_object=el)
    return course, part, el


def _run(tmp_path, **kw):
    args = ["--course", kw.pop("course", "mat-pp"), "--json-dir", str(tmp_path)]
    for pair in kw.pop("exclude", []):
        args += ["--exclude", pair]
    if kw.pop("apply", False):
        args.append("--apply")
    from io import StringIO

    buf = StringIO()
    call_command("recolour_imported_content", *args, stdout=buf)
    return buf.getvalue()


def _simple_tree(tmp_path):
    return _out(
        tmp_path, {"010_p/010_u.json": {"elements": [{"type": "text", "body": RED}]}}
    )


def test_dry_run_is_the_default_and_writes_nothing(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    out = _run(tmp_path)
    assert "DRY RUN" in out
    assert TextElement.objects.get().body == STORED


def test_apply_rewrites_the_matching_field(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    _run(tmp_path, apply=True)
    assert TextElement.objects.get().body == COLOURED


def test_an_edited_element_is_skipped(tmp_path):
    _course_with(STORED + " (poprawione)")
    _simple_tree(tmp_path)
    with pytest.raises(CommandError):  # 0 matches -> the gate halts the run
        _run(tmp_path, apply=True)
    assert TextElement.objects.get().body == STORED + " (poprawione)"


def test_every_node_title_is_unchanged(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    before = dict(ContentNode.objects.values_list("pk", "title"))
    _run(tmp_path, apply=True)
    assert dict(ContentNode.objects.values_list("pk", "title")) == before


def test_a_second_run_reports_already_applied_and_exits_cleanly(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    _run(tmp_path, apply=True)
    out = _run(tmp_path, apply=True)
    assert "already applied" in out.lower()
    assert TextElement.objects.get().body == COLOURED


def test_a_dirname_absent_from_out_is_an_error(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    with pytest.raises(CommandError, match="no such part directory"):
        _run(tmp_path, exclude=["999_typo=1"])


def test_a_pk_from_another_course_is_an_error(tmp_path):
    _course_with(STORED)
    other, other_part, _el = _course_with(STORED, slug="other")
    _simple_tree(tmp_path)
    with pytest.raises(CommandError, match="does not belong"):
        _run(tmp_path, exclude=[f"010_p={other_part.pk}"])


def test_a_missing_pk_is_a_source_side_only_exclusion(tmp_path):
    # The part whose node was deleted from the DB.
    _course_with(STORED)
    _out(
        tmp_path,
        {
            "010_p/010_u.json": {"elements": [{"type": "text", "body": RED}]},
            "020_q/010_u.json": {"elements": [{"type": "text", "body": RED}]},
        },
    )
    out = _run(tmp_path, exclude=["020_q="])
    assert "source-side only" in out
    # The exclusion LINE names 020_q; the per-part table must not.
    table = out.split("per part:")[1].split("skipped:")[0]
    assert "010_p" in table
    assert "020_q" not in table


def test_the_exclusion_protects_hand_edited_content_that_matches_a_key(tmp_path):
    # The DB-side failure being blocked: a key built from an ELIGIBLE part can
    # match text that is byte-identical inside an EXCLUDED part.
    course, part, el = _course_with(STORED, part_title="Excluded")
    ch = ContentNode.objects.create(
        course=course, parent=part, order=1, kind="chapter", title="C2"
    )
    unit2 = ContentNode.objects.create(
        course=course, parent=ch, order=0, kind="unit", title="U2", unit_type="lesson"
    )
    twin = TextElement.objects.create(body=STORED)
    Element.objects.create(unit=unit2, content_object=twin)
    _out(
        tmp_path,
        {
            "010_p/010_u.json": {"elements": [{"type": "text", "body": RED}]},
            "001_zbiory_liczbowe/010_u.json": {"elements": []},
        },
    )
    with pytest.raises(CommandError):  # everything excluded -> nothing matches
        _run(tmp_path, exclude=[f"001_zbiory_liczbowe={part.pk}"], apply=True)
    twin.refresh_from_db()
    assert twin.body == STORED


def test_one_dirname_may_be_paired_with_SEVERAL_pks(tmp_path):
    # The spec's "one source part mapping to several nodes after manual
    # restructuring" case. Both named subtrees must be excluded, not just the last
    # pk seen -- an append-style parser that overwrote would silently recolour a
    # hand-edited subtree.
    course, part_a, _el = _course_with(STORED, part_title="A")
    part_b = ContentNode.objects.create(
        course=course, parent=None, order=1, kind="part", title="B"
    )
    ch = ContentNode.objects.create(
        course=course, parent=part_b, order=0, kind="chapter", title="C"
    )
    unit_b = ContentNode.objects.create(
        course=course, parent=ch, order=0, kind="unit", title="U", unit_type="lesson"
    )
    twin = TextElement.objects.create(body=STORED)
    Element.objects.create(unit=unit_b, content_object=twin)
    _simple_tree(tmp_path)
    with pytest.raises(CommandError):  # both subtrees gone -> nothing matches
        _run(
            tmp_path,
            exclude=[f"010_p={part_a.pk}", f"010_p={part_b.pk}"],
            apply=True,
        )
    twin.refresh_from_db()
    assert twin.body == STORED
    assert TextElement.objects.filter(body=STORED).count() == 2


def test_a_region_refusal_is_named_AND_counts_against_the_gate(tmp_path):
    # A refusal is a real shortfall in delivered colour, so it belongs in the
    # denominator where an operator sees it -- here it drops a 2-occurrence run to
    # 50% and halts it. The report is written before the gate raises, so the
    # buffer is still readable.
    from io import StringIO

    _course_with(STORED)
    _out(
        tmp_path,
        {
            "010_p/010_u.json": {
                "elements": [
                    {"type": "text", "body": RED},
                    {
                        "type": "text",
                        "body": 'a \\(<span style="color: red;">x</span>+y\\) b',
                    },
                ]
            }
        },
    )
    buf = StringIO()
    with pytest.raises(CommandError, match="acceptance gate NOT met"):
        call_command(
            "recolour_imported_content",
            "--course",
            "mat-pp",
            "--json-dir",
            str(tmp_path),
            stdout=buf,
        )
    out = buf.getvalue()
    assert "protected-region" in out
    assert "50.0%" in out


def test_the_dry_run_NAMES_each_matched_field(tmp_path):
    # Spec safety property 3 makes the dry-run report the place an operator spots an
    # ACCIDENTAL match -- author-written text that happens to equal an imported key.
    # A report of counts alone cannot do that job, so the listing is load-bearing.
    _course_with(STORED)
    _simple_tree(tmp_path)
    out = _run(tmp_path)
    assert "matches:" in out
    assert "TextElement(" in out
    assert "założenie" in out.split("matches:")[1]


def test_list_matches_is_accepted_and_lists_everything(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    from io import StringIO

    buf = StringIO()
    call_command(
        "recolour_imported_content",
        "--course",
        "mat-pp",
        "--json-dir",
        str(tmp_path),
        "--list-matches",
        stdout=buf,
    )
    out = buf.getvalue()
    assert "matches:" in out
    assert "more; pass --list-matches" not in out


def test_both_tc_class_counts_are_reported(tmp_path):
    # Two counts, because the spec's source-side expectation is per OCCURRENCE
    # while the map writes per DISTINCT KEY. Reporting only one makes Task 8's
    # span-only-colouriser diagnostic unverdictable.
    _course_with(STORED)
    _simple_tree(tmp_path)
    out = _run(tmp_path)
    assert "tc-* classes (distinct keys)" in out
    assert "tc-* classes (occurrences)" in out


def test_an_unknown_course_is_an_error(tmp_path):
    _simple_tree(tmp_path)
    with pytest.raises(CommandError):
        _run(tmp_path, course="nope")


def test_a_malformed_exclude_pair_is_an_error(tmp_path):
    _course_with(STORED)
    _simple_tree(tmp_path)
    with pytest.raises(CommandError, match="dirname=pk"):
        _run(tmp_path, exclude=["010_p"])
