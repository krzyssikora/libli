from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings

from courses.lal_loader.builders import LoaderError
from courses.lal_loader.builders import build_element
from courses.lal_loader.guards import assert_iframe_hosts_allowlisted
from courses.lal_loader.guards import assert_no_foreign_top_level
from courses.lal_loader.guards import ensure_depth_policy
from courses.lal_loader.guards import owned_part_orders
from courses.lal_loader.guards import resolve_course
from courses.lal_loader.media import get_or_create_asset
from courses.lal_loader.media import resolve_source
from courses.lal_loader.tree import prune_orphans
from courses.lal_loader.tree import rebuild_unit_elements
from courses.lal_loader.tree import upsert_node
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import FillGateElement
from courses.models import FillTableElement
from courses.models import MediaAsset
from courses.models import RevealGateElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SwitchGateElement
from courses.models import SwitchGridElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.validators import validate_embed_url
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db


def test_mediaasset_has_content_hash_field():
    course = CourseFactory()
    a = MediaAsset.objects.create(
        course=course,
        kind="image",
        original_filename="x.png",
        content_hash="a" * 64,
    )
    a.refresh_from_db()
    assert a.content_hash == "a" * 64


def test_content_hash_is_indexed():
    field = MediaAsset._meta.get_field("content_hash")
    assert field.db_index is True


def test_edpuzzle_and_lumi_allowlisted():
    hosts = {h.lower() for h in settings.ALLOWED_EMBED_DOMAINS}
    assert "edpuzzle.com" in hosts
    assert "app.lumi.education" in hosts


def test_edpuzzle_embed_url_validates():
    # Should NOT raise now that the host is allowlisted.
    validate_embed_url("https://edpuzzle.com/embed/media/63fdefbfd6b9684157f590c5")


def test_resolve_source_joins_root_dir_src(tmp_path):
    p = resolve_source(tmp_path, "001_x", "static/a.png")
    assert p == Path(tmp_path) / "001_x" / "static" / "a.png"


def test_dedup_reuses_asset_for_identical_bytes(tmp_path):
    course = CourseFactory()
    f = tmp_path / "a.png"
    f.write_bytes(b"PNGBYTES")
    g = tmp_path / "b.png"
    g.write_bytes(b"PNGBYTES")  # same bytes, different name
    a1 = get_or_create_asset(course, "image", f)
    a2 = get_or_create_asset(course, "image", g)
    assert a1.pk == a2.pk  # deduped by content, not name
    assert a1.content_hash and len(a1.content_hash) == 64


def test_different_bytes_make_different_assets(tmp_path):
    course = CourseFactory()
    f = tmp_path / "a.png"
    f.write_bytes(b"ONE")
    g = tmp_path / "a.png2"
    g.write_bytes(b"TWO")
    assert (
        get_or_create_asset(course, "image", f).pk
        != get_or_create_asset(course, "image", g).pk
    )


def _unit(course):
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )


def test_build_text_element(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {"type": "text", "body": "<p>hi</p>"},
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, TextElement)
    assert Element.objects.filter(unit=unit).count() == 1


def test_build_reveal_gate(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {"type": "reveal_gate", "label": "pokaż dalej"},
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, RevealGateElement)
    assert obj.label == "pokaż dalej"
    assert Element.objects.filter(unit=unit).count() == 1


def test_build_choice_grid(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "choice_grid",
            "columns": ["tak", "nie"],
            "rows": [
                {"statement": "Czy A?", "correct": 1},
                {"statement": "Czy B?", "correct": 0},
            ],
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, ChoiceGridQuestionElement)
    assert [c.label for c in obj.columns.all()] == ["tak", "nie"]
    rows = list(obj.rows.all())
    assert rows[0].correct_column.label == "nie"
    assert rows[1].correct_column.label == "tak"


def test_build_tabs_nests_children_under_join_with_tab_id(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "tabs",
            "tabs": [
                {
                    "id": "t000000",
                    "label": "Sposób I",
                    "elements": [{"type": "text", "body": "<p>a</p>"}],
                },
                {
                    "id": "t000001",
                    "label": "Sposób II",
                    "elements": [
                        {"type": "text", "body": "<p>b</p>"},
                        {"type": "math", "latex": "x"},
                    ],
                },
            ],
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, TabsElement)
    assert [t["label"] for t in obj.data["tabs"]] == ["Sposób I", "Sposób II"]
    join = Element.objects.get(object_id=obj.pk, content_type__model="tabselement")
    # top-level rows: only the tabs join row (children have parent set)
    assert Element.objects.filter(unit=unit, parent__isnull=True).count() == 1
    kids = Element.objects.filter(unit=unit, parent=join)
    assert kids.count() == 3
    assert set(kids.values_list("tab_id", flat=True)) == {"t000000", "t000001"}
    assert kids.filter(tab_id="t000001").count() == 2


def test_build_fill_gate(tmp_path):
    from courses.fillblank import SENTINEL

    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "fill_gate",
            "stem": "Krok: " + SENTINEL + "0" + SENTINEL,
            "answers": [["8"]],
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, FillGateElement)
    assert obj.answers == [["8"]]
    assert SENTINEL + "0" + SENTINEL in obj.stem
    assert Element.objects.filter(unit=unit).count() == 1


def test_build_fillblank(tmp_path):
    from courses.fillblank import SENTINEL

    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "fillblank",
            "stem": "Odp: " + SENTINEL + "0" + SENTINEL,
            "blanks": [["0.5", "0,5"]],
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, FillBlankQuestionElement)
    blanks = list(obj.blanks.all())
    assert len(blanks) == 1
    assert blanks[0].accepted == "0.5\n0,5"
    assert SENTINEL + "0" + SENTINEL in obj.stem
    assert Element.objects.filter(unit=unit).count() == 1


def test_build_fill_table(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "fill_table",
            "data": {
                "header_row": True,
                "header_col": False,
                "border": "grid",
                "cells": [
                    [
                        {"kind": "static", "html": "wymiar"},
                        {"kind": "static", "html": "błąd"},
                    ],
                    [
                        {"kind": "static", "html": r"\(50,5\)"},
                        {"kind": "answer", "answer": "0.5|0,5"},
                    ],
                ],
            },
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, FillTableElement)
    cells = obj.data["cells"]
    assert cells[1][1]["kind"] == "answer"
    assert cells[1][1]["answer"] == "0.5|0,5"
    assert Element.objects.filter(unit=unit).count() == 1


def test_build_switch_gate(tmp_path):
    from courses.fillblank import SENTINEL

    course = CourseFactory()
    unit = _unit(course)
    stem = "Dla x=4: " + SENTINEL + "0" + SENTINEL
    obj = build_element(
        course,
        unit,
        {
            "type": "switch_gate",
            "stem": stem,
            # parser emits options already escaped (decode_contents); the model's
            # sanitize_cell is idempotent on the &gt; entity.
            "options": ["&gt;&gt; wybierz &gt;&gt;", r"\(-1\)", r"\(0\)"],
            "answer": 2,
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, SwitchGateElement)
    assert obj.answer == 2
    assert obj.options == ["&gt;&gt; wybierz &gt;&gt;", r"\(-1\)", r"\(0\)"]
    assert SENTINEL + "0" + SENTINEL in obj.stem
    assert Element.objects.filter(unit=unit).count() == 1


def test_build_switch_grid(tmp_path):
    from courses.fillblank import SENTINEL

    course = CourseFactory()
    unit = _unit(course)
    token = SENTINEL + "0" + SENTINEL
    obj = build_element(
        course,
        unit,
        {
            "type": "switch_grid",
            "prompt": "",
            "lines": [
                {
                    "stem": r"\(A\) " + token + r" \(B\)",
                    "cyclers": [{"options": [r"\(\cup\)", r"\(\cap\)"], "answer": 1}],
                }
            ],
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, SwitchGridElement)
    assert len(obj.lines) == 1
    assert obj.lines[0]["cyclers"][0]["answer"] == 1
    assert token in obj.lines[0]["stem"]
    assert Element.objects.filter(unit=unit).count() == 1


def test_build_choice_with_choices(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "choice",
            "stem": "<p>Q</p>",
            "multiple": True,
            "choices": [
                {"text": "a", "is_correct": True, "feedback": ""},
                {"text": "b", "is_correct": False, "feedback": "no"},
            ],
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, ChoiceQuestionElement)
    assert obj.multiple is True
    assert obj.choices.count() == 2
    assert obj.choices.filter(is_correct=True).count() == 1


def test_build_numeric(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {"type": "numeric", "stem": "<p>n</p>", "value": "2.5", "tolerance": "0"},
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, ShortNumericQuestionElement)
    assert obj.value == Decimal("2.5")


def test_build_numeric_with_points_sets_max_marks(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "numeric",
            "stem": "<p>n</p>",
            "value": "2.5",
            "tolerance": "0",
            "points": "0.5",
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, ShortNumericQuestionElement)
    assert obj.max_marks == Decimal("0.5")


def test_build_shorttext(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "shorttext",
            "stem": "<p>t</p>",
            "accepted": ["ala", "ola"],
            "case_sensitive": False,
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, ShortTextQuestionElement)
    assert obj.accepted == "ala\nola"


def test_flagged_element_refused_without_allow_html(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    with pytest.raises(LoaderError):
        build_element(
            course,
            unit,
            {"type": "html", "flagged": True, "raw": "<x/>"},
            source_root=tmp_path,
            source_dir="x",
            allow_html=False,
        )


def test_over_500_char_choice_raises_loader_error(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    with pytest.raises(LoaderError):
        build_element(
            course,
            unit,
            {
                "type": "choice",
                "stem": "<p>Q</p>",
                "multiple": False,
                "choices": [{"text": "x" * 501, "is_correct": True, "feedback": ""}],
            },
            source_root=tmp_path,
            source_dir="x",
            allow_html=False,
        )


def test_escaped_math_in_stem_survives_sanitize_on_save(tmp_path):
    # Spec §5: a \(a<b\) span (parser-escaped to \(a&lt;b\)) must survive the model's
    # sanitize_html on save — verified through a real QuestionElement.stem, not a
    # bare nh3.clean call.
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "numeric",
            "stem": r"<p>gdy \(a&lt;b\)</p>",
            "value": "1",
            "tolerance": "0",
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    obj.refresh_from_db()
    assert r"\(a&lt;b\)" in obj.stem


def test_choice_literal_math_stored_then_autoescapes(tmp_path):
    # C1 end-to-end: the parser stores literal '<' in Choice.text; Django autoescape
    # (the choice template) then renders the single correct \(y&lt;z\).
    from django.utils.html import escape

    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "choice",
            "stem": "<p>Q</p>",
            "multiple": True,
            "choices": [{"text": r"\(y<z\)", "is_correct": True, "feedback": ""}],
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    text = obj.choices.first().text
    assert text == r"\(y<z\)"  # stored literal
    assert escape(text) == r"\(y&lt;z\)"  # autoescape -> single entity


def test_resolve_course_missing_raises():
    with pytest.raises(LoaderError):
        resolve_course("does-not-exist")


def test_ensure_policy_raises_when_off_without_flag():
    course = CourseFactory(uses_parts=False, uses_chapters=True)
    with pytest.raises(LoaderError):
        ensure_depth_policy(course, set_policy=False)


def test_ensure_policy_sets_when_flagged():
    course = CourseFactory(uses_parts=False, uses_chapters=False, uses_sections=True)
    ensure_depth_policy(course, set_policy=True)
    course.refresh_from_db()
    assert course.uses_parts and course.uses_chapters
    assert course.uses_sections is False  # sections turned off (spec §4.4)


def test_owned_part_orders_reads_all_manifests(tmp_path):
    for folder, order in [("001_a", 0), ("005_b", 1)]:
        d = tmp_path / folder
        d.mkdir()
        (d / "manifest.json").write_text(
            f'{{"part": {{"order": {order}}}, "chapters": []}}', "utf-8"
        )
    assert owned_part_orders(tmp_path) == {0, 1}


def test_foreign_top_level_node_refused():
    course = CourseFactory()
    ContentNode.objects.create(
        course=course, parent=None, kind="part", title="foreign", order=9
    )
    with pytest.raises(LoaderError):
        assert_no_foreign_top_level(course, owned={0, 1})


def test_owned_top_level_node_ok():
    course = CourseFactory()
    ContentNode.objects.create(
        course=course, parent=None, kind="part", title="mine", order=0
    )
    assert_no_foreign_top_level(course, owned={0, 1})  # no raise


def test_iframe_host_not_allowlisted_raises():
    with pytest.raises(LoaderError):
        assert_iframe_hosts_allowlisted(
            [{"type": "iframe", "url": "https://evil.example/x"}]
        )


def test_upsert_is_idempotent_and_renames_in_place():
    course = CourseFactory()
    n1 = upsert_node(course, None, 0, "part", "orig")
    n2 = upsert_node(course, None, 0, "part", "renamed")
    assert n1.pk == n2.pk  # same node, matched by (course, order)
    n2.refresh_from_db()
    assert n2.title == "renamed"
    assert ContentNode.objects.filter(course=course, parent=None).count() == 1


def test_prune_deletes_higher_index_orphans():
    course = CourseFactory()
    part = upsert_node(course, None, 0, "part", "p")
    for i in range(3):
        upsert_node(course, part, i, "chapter", f"c{i}")
    prune_orphans(course, part, keep_count=2)  # keep orders 0,1; drop 2
    assert ContentNode.objects.filter(parent=part).count() == 2


def test_rebuild_wipes_then_recreates_in_order(tmp_path):
    course = CourseFactory()
    unit = upsert_node(course, None, 0, "unit", "u", unit_type="lesson")
    els = [
        {"type": "text", "body": "<p>one</p>"},
        {"type": "text", "body": "<p>two</p>"},
    ]
    rebuild_unit_elements(
        course, unit, els, source_root=tmp_path, source_dir="x", allow_html=False
    )
    rebuild_unit_elements(
        course, unit, els, source_root=tmp_path, source_dir="x", allow_html=False
    )
    rows = list(Element.objects.filter(unit=unit).order_by("order"))
    assert len(rows) == 2  # rebuilt, not duplicated
    assert TextElement.objects.filter(elements__unit=unit).count() == 2
    assert rows[0].order < rows[1].order  # JSON array order preserved
