# tests/test_transfer_import.py
import io
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
from courses.models import Subject
from courses.models import TextElement
from courses.models import VideoElement
from courses.transfer.export import build_export
from courses.transfer.export import write_archive
from courses.transfer.importer import import_course
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.schema import TransferError
from tests.factories import UserFactory
from tests.test_transfer_archive import make_zip
from tests.test_transfer_validation import base_course_doc
from tests.test_transfer_validation import node
from tests.test_transfer_validation import text_el

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    # The import path writes real files through default_storage. Without this
    # redirect, tests would pollute the repo's media/ dir and the orphan-file
    # assertions would scan pre-existing files instead of a clean sandbox.
    settings.MEDIA_ROOT = tmp_path


def _import_zip(buf, user, expected_kind="course", target_course=None):
    with open_archive(buf, expected_kind=expected_kind) as (zf, mani, doc, media):
        validate_archive_document(
            zf, mani, doc, media, kind=expected_kind, target_course=target_course
        )
        return import_course(zf, mani, doc, media, user)


NON_DEFAULT_BANDS = [
    {"key": "none", "label": "x", "min": 0, "color": "#111111"},
    {"key": "weak", "label": "x", "min": 30, "color": "#222222"},
    {"key": "ok", "label": "x", "min": 55, "color": "#333333"},
    {"key": "good", "label": "x", "min": 70, "color": "#444444"},
    {"key": "excellent", "label": "x", "min": 95, "color": "#555555"},
]


def image_el(eid, unit, media_id, alt="", figcaption=""):
    return {
        "id": eid,
        "unit": unit,
        "title": "",
        "type": "image",
        "data": {"media": media_id, "alt": alt, "figcaption": figcaption},
        "parent": None,
        "tab": "",
    }


def video_el(eid, unit, url=None, media=None):
    return {
        "id": eid,
        "unit": unit,
        "title": "",
        "type": "video",
        "data": {"url": url, "media": media},
        "parent": None,
        "tab": "",
    }


def _mk_full_source_course():
    """A source course exercising all 14 element types, each import-valid per
    Task 7's validators, with non-default course-level properties that must
    NOT survive into the imported course (visibility/external_id/cohorts) and
    media used across three element types (image/video/drag_to_image)."""
    subject = Subject.objects.create(
        title_en="Math", title_pl="Matematyka", slug="math"
    )
    course = Course.objects.create(
        title="Src",
        slug="src",
        language="en",
        overview="An overview",
        html_css="body{color:red}",
        html_js="console.log(1)",
        uses_parts=True,
        uses_chapters=True,
        uses_sections=True,
        color_bands=NON_DEFAULT_BANDS,
        visibility="open",
        external_id="EXT-123",
    )
    course.subjects.add(subject)

    image_asset = MediaAsset.objects.create(
        course=course,
        kind="image",
        file=SimpleUploadedFile("pic.png", b"\x89PNG fake image bytes"),
        original_filename="pic.png",
        name="Picture",
    )
    video_asset = MediaAsset.objects.create(
        course=course,
        kind="video",
        file=SimpleUploadedFile("clip.mp4", b"fake video bytes right here"),
        original_filename="clip.mp4",
        name="Clip",
    )
    d2i_asset = MediaAsset.objects.create(
        course=course,
        kind="image",
        file=SimpleUploadedFile("diagram.png", b"diagram bytes go here too"),
        original_filename="diagram.png",
    )

    part = ContentNode.objects.create(course=course, kind="part", title="P1")
    chap = ContentNode.objects.create(
        course=course, kind="chapter", title="C1", parent=part
    )
    sect = ContentNode.objects.create(
        course=course, kind="section", title="S1", parent=chap
    )
    unit = ContentNode.objects.create(
        course=course,
        kind="unit",
        title="U1",
        parent=sect,
        unit_type="lesson",
        html_seed_js="var x = 1;",
    )

    def attach(concrete, title=""):
        return Element.objects.create(unit=unit, title=title, content_object=concrete)

    attach(TextElement.objects.create(body="<p>hello</p>"), title="Text")
    attach(ImageElement.objects.create(media=image_asset, alt="alt", figcaption="cap"))
    attach(VideoElement.objects.create(media=video_asset))
    attach(
        IframeElement.objects.create(
            url="https://www.geogebra.org/embed/abc", title="Geo", width=800, height=760
        )
    )
    attach(MathElement.objects.create(latex="x^2"))
    attach(HtmlElement.objects.create(html="<b>raw</b>"))

    choice_q = ChoiceQuestionElement.objects.create(
        stem="Pick one", multiple=False, max_marks=Decimal("2.00")
    )
    Choice.objects.create(question=choice_q, text="A", is_correct=True)
    Choice.objects.create(question=choice_q, text="B", is_correct=False)
    attach(choice_q)

    st_q = ShortTextQuestionElement.objects.create(accepted="answer1\nanswer2")
    attach(st_q)

    er_q = ExtendedResponseQuestionElement.objects.create(
        required_keywords="alpha", marking_mode="A"
    )
    attach(er_q)

    num_q = ShortNumericQuestionElement.objects.create(
        value=Decimal("3.14"), tolerance=Decimal("0.01")
    )
    attach(num_q)

    fb_q = FillBlankQuestionElement.objects.create(stem="a ￿0￿ b")
    Blank.objects.create(question=fb_q, accepted="x\ny")
    attach(fb_q)

    df_q = DragFillBlankQuestionElement.objects.create(stem="c ￿0￿ d", distractors="z")
    DragBlank.objects.create(question=df_q, correct_token="tok")
    attach(df_q)

    mp_q = MatchPairQuestionElement.objects.create(distractors="extra")
    MatchPair.objects.create(question=mp_q, left="L1", right="R1")
    attach(mp_q)

    d2i_q = DragToImageQuestionElement.objects.create(
        media=d2i_asset, alt="diagram", distractors="junk"
    )
    DragZone.objects.create(
        question=d2i_q,
        correct_label="Zone1",
        x=0.5,
        y=0.1,
        w=0.5000000000000001,
        h=0.2,
    )
    attach(d2i_q)

    return course


def _assert_graphs_equal(source_course, imported_course):
    _mani1, src_doc, src_media_items, _p1 = build_export(source_course)
    _mani2, imp_doc, imp_media_items, _p2 = build_export(imported_course)

    def node_fields(n):
        return {
            k: n[k]
            for k in ("kind", "title", "unit_type", "obligatory", "html_seed_js")
        }

    assert [node_fields(n) for n in src_doc["nodes"]] == [
        node_fields(n) for n in imp_doc["nodes"]
    ]
    assert [(e["type"], e["title"]) for e in src_doc["elements"]] == [
        (e["type"], e["title"]) for e in imp_doc["elements"]
    ]
    assert len(src_doc["elements"]) == 14

    for se, ie in zip(src_doc["elements"], imp_doc["elements"], strict=True):
        assert se["data"] == ie["data"]

    assert len(src_doc["media"]) == len(imp_doc["media"])
    src_by_id = {mid: asset for mid, asset, _ in src_media_items}
    imp_by_id = {mid: asset for mid, asset, _ in imp_media_items}
    for sm, im in zip(src_doc["media"], imp_doc["media"], strict=True):
        assert sm["kind"] == im["kind"]
        assert sm["name"] == im["name"]
        assert sm["original_filename"] == im["original_filename"]
        src_asset = src_by_id[sm["id"]]
        imp_asset = imp_by_id[im["id"]]
        with src_asset.file.open("rb") as sf, imp_asset.file.open("rb") as if_:
            assert sf.read() == if_.read()


# --- full course round trip --------------------------------------------------


def test_full_course_round_trip_new_course_shape():
    source = _mk_full_source_course()
    buf = io.BytesIO()
    write_archive(source, None, buf)
    buf.seek(0)
    importer = UserFactory()

    imported = _import_zip(buf, importer)

    assert imported.slug == "src-2"
    assert imported.owner == importer
    assert imported.visibility == "assigned"
    assert imported.external_id == ""
    assert imported.self_enroll_cohorts.count() == 0
    assert list(imported.subjects.values_list("title_en", flat=True)) == ["Math"]
    assert imported.color_bands == NON_DEFAULT_BANDS


def test_full_course_round_trip_graph_equality():
    source = _mk_full_source_course()
    buf = io.BytesIO()
    write_archive(source, None, buf)
    buf.seek(0)
    importer = UserFactory()

    imported = _import_zip(buf, importer)

    _assert_graphs_equal(source, imported)


def test_empty_color_bands_round_trips():
    course = Course.objects.create(title="Empty", slug="empty", color_bands=[])
    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    importer = UserFactory()

    imported = _import_zip(buf, importer)

    assert imported.color_bands == []


# --- sanitizer re-entry -------------------------------------------------------


def test_script_tag_stripped_from_text_body_on_import():
    doc = base_course_doc(
        nodes=[node("n1")],
        elements=[text_el("e1", "n1", body="<p>hi</p><script>alert(1)</script>")],
    )
    buf = make_zip(document=doc)
    importer = UserFactory()

    course = _import_zip(buf, importer)

    body = TextElement.objects.get(elements__unit__course=course).body
    assert "<script" not in body
    assert "hi" in body


def test_watch_url_stored_canonical_on_import(settings):
    settings.ALLOWED_EMBED_DOMAINS = ["www.youtube.com", "youtube.com"]
    doc = base_course_doc(
        nodes=[node("n1")],
        elements=[
            video_el("e1", "n1", url="https://www.youtube.com/watch?v=abc12345678")
        ],
    )
    buf = make_zip(document=doc)
    importer = UserFactory()

    course = _import_zip(buf, importer)

    video = VideoElement.objects.get(elements__unit__course=course)
    assert "watch?v=" not in video.url
    assert "/embed/" in video.url


# --- backstop: change between validate and commit -----------------------------


def _domain_race_zip():
    img = {
        "id": "m1",
        "kind": "image",
        "name": "",
        "original_filename": "a.png",
        "file": "media/m1.png",
    }
    doc = base_course_doc(
        nodes=[node("n1")],
        elements=[
            image_el("e1", "n1", "m1"),
            video_el("e2", "n1", url="https://www.youtube.com/embed/abc12345678"),
        ],
        media=[img],
    )
    return make_zip(document=doc, entries=[("media/m1.png", b"x" * 20)])


def test_domain_removed_after_validate_rolls_back_and_cleans_media(settings, tmp_path):
    settings.ALLOWED_EMBED_DOMAINS = ["www.youtube.com", "youtube.com"]
    buf = _domain_race_zip()
    importer = UserFactory()

    with open_archive(buf, expected_kind="course") as (zf, mani, document, media):
        validate_archive_document(zf, mani, document, media, kind="course")
        # Simulate an admin narrowing the allow-list between preview and confirm.
        settings.ALLOWED_EMBED_DOMAINS = ["player.vimeo.com"]
        with pytest.raises(TransferError) as excinfo:
            import_course(zf, mani, document, media, importer)

    # The failing element ("e2", the video) must be NAMED in the message —
    # not just a bare Django validation string.
    message = str(excinfo.value)
    assert "e2" in message
    assert "video" in message

    assert Course.objects.count() == 0
    assert MediaAsset.objects.count() == 0
    media_dir = tmp_path / "courses" / "media"
    assert not media_dir.exists() or not any(media_dir.rglob("*"))


# --- controller-directed: unexpected exceptions never leak past TransferError -


def test_unexpected_exception_wrapped_as_transfer_error_and_cleaned_up(
    monkeypatch, tmp_path
):
    img = {
        "id": "m1",
        "kind": "image",
        "name": "",
        "original_filename": "a.png",
        "file": "media/m1.png",
    }
    doc = base_course_doc(
        nodes=[node("n1")],
        elements=[image_el("e1", "n1", "m1")],
        media=[img],
    )
    buf = make_zip(document=doc, entries=[("media/m1.png", b"x" * 20)])
    importer = UserFactory()

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("courses.transfer.importer._create_nodes", _boom)

    with open_archive(buf, expected_kind="course") as (zf, mani, document, media):
        validate_archive_document(zf, mani, document, media, kind="course")
        with pytest.raises(TransferError):
            import_course(zf, mani, document, media, importer)

    assert Course.objects.count() == 0
    assert MediaAsset.objects.count() == 0
    media_dir = tmp_path / "courses" / "media"
    assert not media_dir.exists() or not any(media_dir.rglob("*"))
