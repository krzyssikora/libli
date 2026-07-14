# tests/test_transfer_export.py
import io
import json
import zipfile
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import MediaAsset
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import TextElement
from courses.models import VideoElement
from courses.transfer.export import MediaIdMap
from courses.transfer.export import _placeholder_bytes
from courses.transfer.export import _placeholder_filename
from courses.transfer.export import _placeholder_size
from courses.transfer.export import build_export
from courses.transfer.export import export_filename
from courses.transfer.export import serialize_element_data
from courses.transfer.export import write_archive
from courses.transfer.export import write_archive_from

pytestmark = pytest.mark.django_db


@pytest.fixture
def course():
    return Course.objects.create(title="Src", slug="src")


@pytest.fixture
def image_asset(course, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.uploadedfile import SimpleUploadedFile

    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file=SimpleUploadedFile("pic.png", b"\x89PNG fake"),
        original_filename="pic.png",
    )


def test_text_element(course):
    el = TextElement.objects.create(body="<p>hello</p>")
    key, data = serialize_element_data(el, MediaIdMap())
    assert key == "text"
    assert data == {"body": "<p>hello</p>"}


def test_image_element_registers_media(course, image_asset):
    el = ImageElement.objects.create(media=image_asset, alt="a", figcaption="c")
    ids = MediaIdMap()
    key, data = serialize_element_data(el, ids)
    assert key == "image"
    assert data == {"media": "m1", "alt": "a", "figcaption": "c"}
    assert ids.items() == [("m1", image_asset)]


def test_media_id_map_is_stable_on_reuse(course, image_asset):
    ids = MediaIdMap()
    el1 = ImageElement.objects.create(media=image_asset)
    el2 = ImageElement.objects.create(media=image_asset)
    serialize_element_data(el1, ids)
    _, data2 = serialize_element_data(el2, ids)
    assert data2["media"] == "m1"
    assert len(ids.items()) == 1


def test_video_url_variant(course):
    el = VideoElement.objects.create(url="https://www.youtube.com/embed/x")
    key, data = serialize_element_data(el, MediaIdMap())
    assert key == "video"
    assert data == {"url": "https://www.youtube.com/embed/x", "media": None}


def test_video_file_variant(course, image_asset):
    el = VideoElement.objects.create(media=image_asset)
    key, data = serialize_element_data(el, MediaIdMap())
    assert key == "video"
    assert data == {"url": None, "media": "m1"}


def test_choice_question(course):
    q = ChoiceQuestionElement.objects.create(
        stem="Pick", multiple=False, max_marks=Decimal("2.50")
    )
    Choice.objects.create(question=q, text="A", is_correct=True)
    Choice.objects.create(question=q, text="B", is_correct=False)
    key, data = serialize_element_data(q, MediaIdMap())
    assert key == "choice"
    assert data["multiple"] is False
    assert data["max_marks"] == "2.50"
    assert data["max_attempts"] == 1
    assert data["choices"] == [
        {"text": "A", "is_correct": True, "feedback": ""},
        {"text": "B", "is_correct": False, "feedback": ""},
    ]


def test_short_numeric_decimals_are_strings(course):
    q = ShortNumericQuestionElement.objects.create(
        value=Decimal("3.14159265"), tolerance=Decimal("0.001")
    )
    _, data = serialize_element_data(q, MediaIdMap())
    assert data["value"] == "3.14159265"
    assert data["tolerance"] == "0.001"


def test_all_14_types_have_a_serializer(course, image_asset):
    q_kwargs = {}
    fixtures = [
        TextElement.objects.create(body="b"),
        ImageElement.objects.create(media=image_asset),
        VideoElement.objects.create(url="https://www.youtube.com/embed/x"),
        IframeElement.objects.create(url="https://www.youtube.com/embed/y"),
        MathElement.objects.create(latex="x^2"),
        HtmlElement.objects.create(html="<b>raw</b>"),
        ChoiceQuestionElement.objects.create(stem="s", **q_kwargs),
        ShortTextQuestionElement.objects.create(accepted="a\nb", **q_kwargs),
        ExtendedResponseQuestionElement.objects.create(
            required_keywords="k", **q_kwargs
        ),
        ShortNumericQuestionElement.objects.create(value=Decimal("1"), **q_kwargs),
        FillBlankQuestionElement.objects.create(stem="￿0￿", **q_kwargs),
        DragFillBlankQuestionElement.objects.create(
            stem="￿0￿", distractors="d", **q_kwargs
        ),
        MatchPairQuestionElement.objects.create(distractors="", **q_kwargs),
        DragToImageQuestionElement.objects.create(media=image_asset, **q_kwargs),
    ]
    keys = {serialize_element_data(el, MediaIdMap())[0] for el in fixtures}
    assert keys == {
        "text",
        "image",
        "video",
        "iframe",
        "math",
        "html",
        "choice",
        "short_text",
        "extended_response",
        "short_numeric",
        "fill_blank",
        "drag_fill_blank",
        "match_pair",
        "drag_to_image",
    }


def test_fill_blank_children_and_sentinel_stem(course):
    q = FillBlankQuestionElement.objects.create(stem="a ￿0￿ b")
    Blank.objects.create(question=q, accepted="x\ny", case_sensitive=False)
    _, data = serialize_element_data(q, MediaIdMap())
    assert data["stem"] == "a ￿0￿ b"
    assert data["blanks"] == [{"accepted": "x\ny", "case_sensitive": False}]


def test_drag_to_image_zones(course, image_asset):
    q = DragToImageQuestionElement.objects.create(media=image_asset, alt="pic")
    DragZone.objects.create(question=q, correct_label="L", x=0.1, y=0.2, w=0.3, h=0.4)
    _, data = serialize_element_data(q, MediaIdMap())
    assert data["zones"] == [
        {"correct_label": "L", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    ]
    assert data["media"] == "m1"


def test_match_pair_and_drag_fill_children(course):
    mp = MatchPairQuestionElement.objects.create(distractors="z")
    MatchPair.objects.create(question=mp, left="L", right="R")
    _, mp_data = serialize_element_data(mp, MediaIdMap())
    assert mp_data["pairs"] == [{"left": "L", "right": "R"}]
    df = DragFillBlankQuestionElement.objects.create(stem="￿0￿")
    DragBlank.objects.create(question=df, correct_token="tok")
    _, df_data = serialize_element_data(df, MediaIdMap())
    assert df_data["blanks"] == [{"correct_token": "tok"}]


def _mk_tree(course):
    part = ContentNode.objects.create(course=course, kind="part", title="P1")
    chap = ContentNode.objects.create(
        course=course, kind="chapter", title="C1", parent=part
    )
    unit = ContentNode.objects.create(
        course=course, kind="unit", title="U1", parent=chap, unit_type="lesson"
    )
    return part, chap, unit


def _attach(unit, concrete, title=""):
    return Element.objects.create(unit=unit, title=title, content_object=concrete)


def test_build_export_full_course_document(course, image_asset):
    part, chap, unit = _mk_tree(course)
    _attach(unit, TextElement.objects.create(body="hi"))
    _attach(unit, ImageElement.objects.create(media=image_asset, alt="a"))
    manifest, doc, media, _problems = build_export(course)
    assert manifest["format_version"] == 4
    assert manifest["kind"] == "course"
    assert manifest["course"] == {"title": "Src", "slug": "src"}
    assert doc["course"]["title"] == "Src"
    assert "slug" not in doc["course"]
    assert [n["kind"] for n in doc["nodes"]] == ["part", "chapter", "unit"]
    assert doc["nodes"][0]["parent"] is None
    assert doc["nodes"][1]["parent"] == doc["nodes"][0]["id"]
    assert "order" not in doc["nodes"][0]
    assert [e["type"] for e in doc["elements"]] == ["text", "image"]
    assert doc["elements"][0]["unit"] == doc["nodes"][2]["id"]
    assert [m["id"] for m in doc["media"]] == ["m1"]
    assert doc["media"][0]["file"] == "media/m1.png"
    assert media[0][1] == image_asset


def test_referenced_only_media(course, image_asset, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    unused = MediaAsset.objects.create(
        course=course,
        kind="image",
        file=SimpleUploadedFile("unused.png", b"x"),
        original_filename="unused.png",
    )
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset))
    _manifest, doc, media, _problems = build_export(course)
    assert len(doc["media"]) == 1
    assert unused.pk not in {a.pk for _mid, a, _ in media}


def test_non_unit_empty_string_unit_type_exports_as_null(course):
    # Admin-saved rows can hold unit_type="" on non-units; export normalizes.
    part = ContentNode.objects.create(course=course, kind="part", title="P")
    ContentNode.objects.filter(pk=part.pk).update(unit_type="")
    _manifest, doc, _media, _problems = build_export(course)
    assert doc["nodes"][0]["unit_type"] is None


def test_build_export_subtree_context(course):
    part, chap, unit = _mk_tree(course)
    manifest, doc, _media, _problems = build_export(course, node=chap)
    assert manifest["kind"] == "subtree"
    assert manifest["node"] == {"title": "C1", "kind": "chapter"}
    assert doc["context"]["root_kind"] == "chapter"
    assert sorted(doc["context"]["required_kinds"]) == ["chapter", "unit"]
    assert "course" not in doc
    assert doc["nodes"][0]["parent"] is None  # root's parent nulled
    assert [n["kind"] for n in doc["nodes"]] == ["chapter", "unit"]


def test_write_archive_roundtrips_zip(course, image_asset):
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset))
    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
        assert names == {"manifest.json", "course.json", "media/m1.png"}
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["media_total_bytes"] == image_asset.file.size
        assert zf.read("media/m1.png") == image_asset.file.open("rb").read()


def test_export_filename(course):
    import datetime

    part, chap, unit = _mk_tree(course)
    d = datetime.date(2026, 7, 5)
    assert export_filename(course, None, d) == "src-export-2026-07-05.zip"
    assert export_filename(course, chap, d) == "src-c1-export-2026-07-05.zip"
    chap.title = "!!!"
    assert export_filename(course, chap, d) == "src-content-export-2026-07-05.zip"


# --- Task 1: placeholder asset + helpers ---


def test_placeholder_filename_forces_png_stem():
    assert _placeholder_filename("photo.jpg") == "photo.png"
    assert _placeholder_filename("demo.png") == "demo.png"
    assert _placeholder_filename("pic") == "pic.png"
    assert (
        _placeholder_filename(".foo") == ".foo.png"
    )  # splitext(".foo") -> stem ".foo"
    assert _placeholder_filename("") == "image.png"  # empty stem falls back
    assert _placeholder_filename(".") == "image.png"


def test_placeholder_asset_is_a_valid_importable_image():
    import io

    from PIL import Image

    from courses.validators import effective_image_extensions
    from courses.validators import effective_max_image_bytes

    data = _placeholder_bytes()
    assert _placeholder_size() == len(data)
    # a real, openable PNG
    Image.open(io.BytesIO(data)).verify()
    # passes the import media gates for an image entry named "*.png"
    assert "png" in {e.lower().lstrip(".") for e in effective_image_extensions()}
    assert _placeholder_size() < effective_max_image_bytes()


# --- Task 2: tolerant build_export ---
def _delete_asset_file(asset):
    """Remove the backing file but keep the MediaAsset row (orphaned FileField)."""
    asset.file.storage.delete(asset.file.name)


def _make_broken_join(unit):
    """Create a dangling GFK: an Element join whose object_id points at a
    nonexistent concrete row, so `join.content_object is None`. Do NOT delete the
    concrete row — every concrete element declares GenericRelation(Element)
    (models.py:264 "cascade: deleting this removes its join-row"), so a delete
    would cascade-remove the join entirely (leaving NO join, not a dangling one).
    Repoint object_id via .update() to bypass the cascade."""
    join = _attach(unit, TextElement.objects.create(body="orphan"))
    Element.objects.filter(pk=join.pk).update(object_id=9_999_999)  # nonexistent pk
    return join


def test_missing_image_becomes_placeholder_with_problem(course, image_asset):
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset, alt="a"))
    _delete_asset_file(image_asset)
    _manifest, doc, media_assets, problems = build_export(course)
    # element kept, still references the media
    assert [e["type"] for e in doc["elements"]] == ["image"]
    assert doc["elements"][0]["data"]["media"] == "m1"
    # media entry kept, flagged placeholder, forced .png name
    assert len(doc["media"]) == 1
    assert doc["media"][0]["file"] == "media/m1.png"
    assert doc["media"][0]["original_filename"].endswith(".png")
    assert media_assets == [("m1", image_asset, True)]
    assert problems == [
        {
            "type": "missing_image",
            "filename": image_asset.original_filename,
            "units": ["U1"],
        }
    ]


def test_missing_jpg_image_placeholder_forces_png_name_end_to_end(
    course, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    jpg = MediaAsset.objects.create(
        course=course,
        kind="image",
        file=SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff fake jpg"),
        original_filename="photo.jpg",
    )
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=jpg))
    _delete_asset_file(jpg)
    _m, doc, _ma, _p = build_export(course)
    # stem preserved, extension forced to .png (matches the placeholder bytes)
    assert doc["media"][0]["original_filename"] == "photo.png"
    assert doc["media"][0]["file"] == "media/m1.png"


def test_missing_image_lists_all_referencing_units(
    course, image_asset, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    # two DIFFERENT units, both referencing the same (missing) image asset
    part = ContentNode.objects.create(course=course, kind="part", title="P")
    u1 = ContentNode.objects.create(
        course=course, kind="unit", title="Bonus", parent=part, unit_type="lesson"
    )
    u2 = ContentNode.objects.create(
        course=course, kind="unit", title="Bonus", parent=part, unit_type="lesson"
    )
    Element.objects.create(
        unit=u1, title="", content_object=ImageElement.objects.create(media=image_asset)
    )
    Element.objects.create(
        unit=u2, title="", content_object=ImageElement.objects.create(media=image_asset)
    )
    _delete_asset_file(image_asset)
    _m, _doc, _ma, problems = build_export(course)
    assert len(problems) == 1
    assert problems[0]["type"] == "missing_image"
    # two distinct units (pk-deduped) share a title → collapsed to "Bonus (×2)"
    # rather than the awkward "Bonus, Bonus"
    assert problems[0]["units"] == ["Bonus (×2)"]


def test_units_keeps_distinct_titles_separate(course, image_asset, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    part = ContentNode.objects.create(course=course, kind="part", title="P")
    u1 = ContentNode.objects.create(
        course=course, kind="unit", title="Alpha", parent=part, unit_type="lesson"
    )
    u2 = ContentNode.objects.create(
        course=course, kind="unit", title="Beta", parent=part, unit_type="lesson"
    )
    Element.objects.create(
        unit=u1, title="", content_object=ImageElement.objects.create(media=image_asset)
    )
    Element.objects.create(
        unit=u2, title="", content_object=ImageElement.objects.create(media=image_asset)
    )
    _delete_asset_file(image_asset)
    _m, _doc, _ma, problems = build_export(course)
    # distinct titles listed as-is, first-seen order, no count suffix
    assert problems[0]["units"] == ["Alpha", "Beta"]


def test_missing_video_file_drops_element_with_problem(course, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    vid = MediaAsset.objects.create(
        course=course,
        kind="video",
        file=SimpleUploadedFile("clip.mp4", b"\x00\x00\x00\x18ftyp"),
        original_filename="clip.mp4",
    )
    part, chap, unit = _mk_tree(course)
    _attach(unit, VideoElement.objects.create(media=vid))
    _delete_asset_file(vid)
    _m, doc, media_assets, problems = build_export(course)
    # element dropped, media omitted
    assert doc["elements"] == []
    assert doc["media"] == []
    assert media_assets == []
    assert problems == [
        {"type": "dropped_video", "filename": "clip.mp4", "units": ["U1"]}
    ]


def test_broken_element_dropped_with_problem(course):
    part, chap, unit = _mk_tree(course)
    _make_broken_join(unit)  # dangling GFK (no cascade — see helper)
    _m, doc, media_assets, problems = build_export(course)
    assert doc["elements"] == []
    assert problems == [{"type": "broken_element", "units": ["U1"]}]


def test_cross_type_problem_ordering_is_walk_order(
    course, image_asset, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    part, chap, unit = _mk_tree(course)
    # order in the unit: broken text, then missing image, then missing video
    _make_broken_join(unit)  # -> broken (walk 1)
    _attach(
        unit, ImageElement.objects.create(media=image_asset)
    )  # -> missing_image (walk 2)
    vid = MediaAsset.objects.create(
        course=course,
        kind="video",
        file=SimpleUploadedFile("clip.mp4", b"x"),
        original_filename="clip.mp4",
    )
    _attach(unit, VideoElement.objects.create(media=vid))  # -> dropped_video (walk 3)
    _delete_asset_file(image_asset)
    _delete_asset_file(vid)
    _m, _doc, _ma, problems = build_export(course)
    assert [p["type"] for p in problems] == [
        "broken_element",
        "missing_image",
        "dropped_video",
    ]


def test_kept_element_ids_contiguous_despite_skips(
    course, image_asset, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    part, chap, unit = _mk_tree(course)
    _make_broken_join(unit)  # broken -> skipped (does not consume an e-id)
    _attach(unit, TextElement.objects.create(body="keep1"))
    _attach(unit, TextElement.objects.create(body="keep2"))
    _m, doc, _ma, _p = build_export(course)
    assert [e["id"] for e in doc["elements"]] == [
        "e1",
        "e2",
    ]  # no gap from the skipped one


def test_healthy_course_has_no_problems_and_false_placeholder_flags(
    course, image_asset
):
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset))
    _m, doc, media_assets, problems = build_export(course)
    assert problems == []
    assert media_assets == [("m1", image_asset, False)]
    assert doc["media"][0]["file"] == "media/m1.png"  # real .png asset keeps its ext


def test_two_broken_in_one_unit_yield_two_problems(course):
    part, chap, unit = _mk_tree(course)
    _make_broken_join(unit)
    _make_broken_join(unit)  # two distinct broken joins in one unit
    _m, doc, _ma, problems = build_export(course)
    assert doc["elements"] == []
    assert [p["type"] for p in problems] == ["broken_element", "broken_element"]


def test_media_total_bytes_counts_placeholder_and_excludes_dropped(
    course, image_asset, settings, tmp_path
):
    from courses.transfer.export import _placeholder_size

    settings.MEDIA_ROOT = tmp_path
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset))  # -> placeholder
    vid = MediaAsset.objects.create(
        course=course,
        kind="video",
        file=SimpleUploadedFile("clip.mp4", b"xxxxx"),
        original_filename="clip.mp4",
    )
    _attach(unit, VideoElement.objects.create(media=vid))  # -> dropped
    _delete_asset_file(image_asset)
    _delete_asset_file(vid)
    manifest, _doc, _ma, _p = build_export(course)
    # placeholder size counted, dropped video's bytes excluded
    assert manifest["media_total_bytes"] == _placeholder_size()


# --- Task 3: write_archive_from ---


def test_write_archive_from_writes_placeholder_and_omits_dropped(
    course, image_asset, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset))
    vid = MediaAsset.objects.create(
        course=course,
        kind="video",
        file=SimpleUploadedFile("clip.mp4", b"x"),
        original_filename="clip.mp4",
    )
    _attach(unit, VideoElement.objects.create(media=vid))
    _delete_asset_file(image_asset)  # -> placeholder
    _delete_asset_file(vid)  # -> dropped
    manifest, document, media_assets, _problems = build_export(course)
    buf = io.BytesIO()
    write_archive_from(manifest, document, media_assets, buf)
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
        assert "media/m1.png" in names  # placeholder image
        assert not any(n.endswith(".mp4") for n in names)  # dropped video absent
        assert zf.read("media/m1.png") == _placeholder_bytes()
