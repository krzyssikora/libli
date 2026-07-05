# tests/test_transfer_export.py
from decimal import Decimal

import pytest

from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Course
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
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
from courses.transfer.export import serialize_element_data

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
        {"text": "A", "is_correct": True},
        {"text": "B", "is_correct": False},
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
