from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings

from courses.lal_loader.builders import LoaderError
from courses.lal_loader.builders import build_element
from courses.lal_loader.media import get_or_create_asset
from courses.lal_loader.media import resolve_source
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import MediaAsset
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
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
