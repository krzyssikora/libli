from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings

from courses.fillblank import SENTINEL as _LAL_SENTINEL
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
from courses.models import MultiGridQuestionElement
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


def test_build_spoiler_truncates_over_120_char_label(tmp_path):
    # SpoilerElement.label is varchar(120); a longer LAL reveal label must be
    # truncated (as reveal_gate does) rather than raising a DB DataError on load.
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {"type": "spoiler", "label": "x" * 200, "body": "<p>b</p>"},
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert len(obj.label) == 120


def test_choice_grid_deletes_without_protected_error(tmp_path):
    # Reload = delete-and-rebuild; deleting a ChoiceGrid must not trip
    # GridRow.correct_column's PROTECT FK (Django cascade-ordering edge case).
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "choice_grid",
            "columns": ["tak", "nie"],
            "rows": [{"statement": "A", "correct": 1}],
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    pk = obj.pk
    obj.delete()  # must NOT raise ProtectedError
    assert not ChoiceGridQuestionElement.objects.filter(pk=pk).exists()


def test_build_multi_grid(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    obj = build_element(
        course,
        unit,
        {
            "type": "multi_grid",
            "columns": ["2", "3", "5"],
            "rows": [
                {"statement": "432", "correct": [0, 1]},
                {"statement": "250", "correct": [0, 2]},
            ],
        },
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )
    assert isinstance(obj, MultiGridQuestionElement)
    assert [c.label for c in obj.columns.all()] == ["2", "3", "5"]
    rows = list(obj.rows.all())
    # correct_columns is a *set* per row (all-or-nothing grading)
    assert sorted(c.label for c in rows[0].correct_columns.all()) == ["2", "3"]
    assert sorted(c.label for c in rows[1].correct_columns.all()) == ["2", "5"]


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


def _write_png(path):
    from io import BytesIO

    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    buf = BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "PNG")
    path.write_bytes(buf.getvalue())


def test_build_fill_table_resolves_image_cell_media(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    _write_png(tmp_path / "x" / "static" / "g.png")
    el = {
        "type": "fill_table",
        "data": {
            "cells": [
                [
                    {"kind": "image", "media_src": "static/g.png", "alt": "graph"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        },
    }
    obj = build_element(
        course, unit, el, source_root=tmp_path, source_dir="x", allow_html=False
    )
    assert isinstance(obj, FillTableElement)
    cell = obj.data["cells"][0][0]
    assert cell["kind"] == "image"
    asset = MediaAsset.objects.get(pk=cell["media"])
    assert asset.course == course and asset.kind == "image"
    assert cell["alt"] == "graph"


def test_build_fill_table_image_dedups_on_reload(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    _write_png(tmp_path / "x" / "static" / "g.png")
    el = {
        "type": "fill_table",
        "data": {
            "cells": [
                [
                    {"kind": "image", "media_src": "static/g.png", "alt": ""},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        },
    }
    build_element(
        course, unit, el, source_root=tmp_path, source_dir="x", allow_html=False
    )
    build_element(
        course, unit, el, source_root=tmp_path, source_dir="x", allow_html=False
    )
    assert MediaAsset.objects.filter(course=course, kind="image").count() == 1


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
    # per-option feedback round-trips (the mult_choice widget relies on this)
    assert obj.choices.get(text="b").feedback == "no"


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


def test_build_spoiler_nested_creates_children_in_order():
    from courses.models import SpoilerElement
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {
        "type": "spoiler",
        "label": "Answer",
        "elements": [
            {"type": "text", "body": "<p>step 1</p>"},
            {"type": "text", "body": "<p>step 2</p>"},
        ],
    }
    obj = build_element(
        course, unit, el, source_root="", source_dir="", allow_html=False
    )
    assert isinstance(obj, SpoilerElement)
    join = obj.join_row()
    kids = list(join.children.order_by("order", "pk"))
    assert [k.tab_id for k in kids] == [SpoilerElement.SLOT_ID, SpoilerElement.SLOT_ID]
    assert [k.content_object.body for k in kids] == ["<p>step 1</p>", "<p>step 2</p>"]


def test_build_spoiler_empty_elements_list_builds_empty_disclosure():
    from courses.models import SpoilerElement
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {"type": "spoiler", "label": "L", "elements": []}  # key present, no body
    obj = build_element(
        course, unit, el, source_root="", source_dir="", allow_html=False
    )
    assert isinstance(obj, SpoilerElement)
    assert obj.resolved_children() == []
    assert obj.body == ""


def test_build_spoiler_legacy_body_still_flat():
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {"type": "spoiler", "label": "L", "body": "<p>legacy</p>"}
    obj = build_element(
        course, unit, el, source_root="", source_dir="", allow_html=False
    )
    assert obj.resolved_children() == []
    assert "<p>legacy</p>" in obj.body


def test_build_spoiler_rejects_container_child():
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {
        "type": "spoiler",
        "label": "L",
        "elements": [{"type": "tabs", "tabs": []}],  # container child -> refuse
    }
    with pytest.raises(LoaderError):
        build_element(course, unit, el, source_root="", source_dir="", allow_html=False)


def test_build_spoiler_flagged_child_builds_html_under_allow_html():
    # A FLAGGED child (parser could not map some block inside the spoiler) is NOT
    # blocked by the static-leaf allowlist: it follows build_element's flagged
    # branch, which under --allow-html builds an HtmlElement child — mirroring the
    # top-level flagged-element escape, not a new hard block.
    from courses.models import HtmlElement
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {
        "type": "spoiler",
        "label": "L",
        "elements": [
            {"type": "text", "body": "<p>a</p>"},
            {
                "flagged": True,
                "type": "html",
                "raw": "<div>x</div>",
                "reason": "unmapped",
            },
        ],
    }
    obj = build_element(
        course, unit, el, source_root="", source_dir="", allow_html=True
    )
    kids = list(obj.join_row().children.order_by("order", "pk"))
    assert [type(k.content_object).__name__ for k in kids] == [
        "TextElement",
        "HtmlElement",
    ]
    assert isinstance(kids[1].content_object, HtmlElement)


def test_build_spoiler_flagged_child_still_errors_without_allow_html():
    # Without --allow-html, a flagged child raises via build_element's flagged
    # branch (the "pass --allow-html" path), same as a top-level flagged element.
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {
        "type": "spoiler",
        "label": "L",
        "elements": [
            {
                "flagged": True,
                "type": "html",
                "raw": "<div>x</div>",
                "reason": "unmapped",
            }
        ],
    }
    with pytest.raises(LoaderError):
        build_element(course, unit, el, source_root="", source_dir="", allow_html=False)


def test_build_spoiler_accepts_reveal_gate_child():
    # Task 1 widening: an interactive leaf now loads as a spoiler child instead
    # of raising (was test_build_spoiler_rejects_reveal_gate_child).
    from courses.models import RevealGateElement
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {
        "type": "spoiler",
        "label": "L",
        "elements": [{"type": "reveal_gate", "label": "x"}],
    }
    obj = build_element(
        course, unit, el, source_root="", source_dir="", allow_html=False
    )
    kids = obj.resolved_children()
    assert len(kids) == 1
    assert isinstance(kids[0].content_object, RevealGateElement)


def test_build_spoiler_accepts_fillblank_child():
    # Task 1 widening: fillblank (canonical fill_blank) now loads as a spoiler
    # child instead of raising (was test_build_spoiler_rejects_fillblank_child).
    from courses.fillblank import SENTINEL
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {
        "type": "spoiler",
        "label": "L",
        "elements": [
            {
                "type": "fillblank",
                "stem": f"x = {SENTINEL}0{SENTINEL}",
                "blanks": [["0"]],
            }
        ],
    }
    obj = build_element(
        course, unit, el, source_root="", source_dir="", allow_html=False
    )
    kids = obj.resolved_children()
    assert len(kids) == 1
    assert isinstance(kids[0].content_object, FillBlankQuestionElement)


@pytest.mark.parametrize(
    "child",
    [
        {"type": "reveal_gate", "label": "pokaż"},
        {"type": "switch_gate", "stem": "s", "options": ["a", "b"], "answer": 0},
        {"type": "fill_gate", "stem": "s", "answers": [["1"]]},
        {
            "type": "switch_grid",
            "prompt": "",
            "lines": [{"stem": "s", "cyclers": [{"options": ["a", "b"], "answer": 0}]}],
        },
        {
            "type": "fillblank",
            "stem": f"x = {_LAL_SENTINEL}0{_LAL_SENTINEL}",
            "blanks": [["0"]],
        },
        {
            "type": "fill_table",
            "data": {"cells": [[{"kind": "answer", "answer": "1"}]]},
        },
    ],
)
def test_loader_accepts_interactive_spoiler_child(child):
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {"type": "spoiler", "label": "rozwiązanie", "elements": [child]}
    spoiler = build_element(
        course, unit, el, source_root="", source_dir="", allow_html=False
    )
    kids = spoiler.resolved_children()
    assert len(kids) == 1


# --- missing-source-media tolerance ------------------------------------------
# A missing source file must not abort the whole part: the offending element is
# skipped (not created) and recorded in the `missing` sink so the command can
# warn. Mirrors the tolerant course-export convention (missing image/video ->
# not a hard failure). Pre-fix, get_or_create_asset raised bare FileNotFoundError.


def test_build_image_missing_source_is_skipped_not_raised(tmp_path):
    from courses.models import ImageElement

    course = CourseFactory()
    unit = _unit(course)
    missing = []
    obj = build_element(
        course,
        unit,
        {"type": "image", "media_src": "static/gone.png", "alt": "x"},
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
        missing=missing,
    )
    assert obj is None
    assert Element.objects.filter(unit=unit).count() == 0
    assert ImageElement.objects.count() == 0
    assert MediaAsset.objects.count() == 0
    assert len(missing) == 1
    assert missing[0][1] == "image" and "gone.png" in missing[0][2]


def test_build_video_missing_source_is_skipped_not_raised(tmp_path):
    from courses.models import VideoElement

    course = CourseFactory()
    unit = _unit(course)
    missing = []
    obj = build_element(
        course,
        unit,
        {"type": "video", "media_src": "static/gone.mp4"},
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
        missing=missing,
    )
    assert obj is None
    assert Element.objects.filter(unit=unit).count() == 0
    assert VideoElement.objects.count() == 0
    assert len(missing) == 1 and missing[0][1] == "video"


def test_build_image_remote_url_src_is_treated_as_missing(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    missing = []
    obj = build_element(
        course,
        unit,
        {"type": "image", "media_src": "https://example.com/a.png", "alt": "x"},
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
        missing=missing,
    )
    assert obj is None
    assert len(missing) == 1 and "https://example.com/a.png" in missing[0][2]


def test_build_missing_image_inside_spoiler_skips_only_that_child(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    missing = []
    el = {
        "type": "spoiler",
        "label": "rozwiązanie",
        "elements": [
            {"type": "text", "body": "<p>hi</p>"},
            {"type": "image", "media_src": "static/gone.png", "alt": "x"},
        ],
    }
    spoiler = build_element(
        course,
        unit,
        el,
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
        missing=missing,
    )
    # The spoiler still builds; only the missing image child is dropped.
    assert len(spoiler.resolved_children()) == 1
    assert len(missing) == 1 and missing[0][1] == "image"


def test_build_fill_table_missing_image_cell_degrades_to_static(tmp_path):
    course = CourseFactory()
    unit = _unit(course)
    missing = []
    el = {
        "type": "fill_table",
        "data": {
            "cells": [
                [
                    {"kind": "image", "media_src": "static/gone.png", "alt": "g"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        },
    }
    obj = build_element(
        course,
        unit,
        el,
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
        missing=missing,
    )
    assert isinstance(obj, FillTableElement)
    cell = obj.data["cells"][0][0]
    assert cell["kind"] != "image"  # degraded to a (static) cell, no dangling media
    assert MediaAsset.objects.count() == 0
    assert len(missing) == 1 and missing[0][1] == "image"
