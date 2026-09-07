"""The LAL loader writes a caption that was authored as PLAIN TEXT.

`lesson.py` fills `figcaption` from BeautifulSoup's `get_text()`, so the JSON
holds characters, not markup. From FORMAT_VERSION 14 the column is read as HTML,
so the loader has to escape on the way in -- exactly as migration 0062 did for
the rows already in the database. Without it a caption reading `a < b` loses
everything from the `<` onward the moment nh3 sees it.

scripts/lal_import/ is deliberately NOT changed: it is the offline HTML->JSON
step, no re-import is planned, and its output is plain text either way -- this
loader is the live boundary that reads that output.
"""

from pathlib import Path

import pytest

from courses.lal_loader.builders import build_element
from courses.models import ImageElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db

PNG = Path(__file__).resolve().parents[2] / "courses/lal_loader"


def _unit(course):
    return ContentNodeFactory(course=course, kind="unit")


def _build(tmp_path, caption):
    """A real 1x1 PNG on disk: the image branch skips the element entirely when
    the source file is missing, which would make every assertion here vacuous."""
    course = CourseFactory()
    unit = _unit(course)
    src = tmp_path / "x"
    src.mkdir(exist_ok=True)
    (src / "p.png").write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c6300010000050001a5f645ee0000000049454e44ae"
            "426082"
        )
    )
    return build_element(
        course,
        unit,
        {"type": "image", "media_src": "p.png", "alt": "a", "figcaption": caption},
        source_root=tmp_path,
        source_dir="x",
        allow_html=False,
    )


def test_an_ampersand_ends_up_escaped(tmp_path):
    """Pins the OUTCOME, not the mechanism: this one passes without the loader
    escape too, because nh3 normalises a bare `&` in text content by itself. The
    two tests below are the ones that can tell the versions apart."""
    obj = _build(tmp_path, "Tom & Jerry")
    assert isinstance(obj, ImageElement)
    assert obj.figcaption == "Tom &amp; Jerry"


def test_a_caption_that_reads_like_markup_is_stored_as_characters(tmp_path):
    """`<b>` is IN the caption subset, so an unescaped plain-text caption that
    happens to contain it starts rendering as bold -- the loader's JSON is
    get_text() output, where those characters were meant to be read."""
    obj = _build(tmp_path, "<b>lit</b>")
    assert obj.figcaption == "&lt;b&gt;lit&lt;/b&gt;"


def test_the_loader_escapes_a_less_than_before_nh3_can_eat_it(tmp_path):
    """The failure mode: unescaped, ImageElement.save()'s sanitiser reads `<b`
    as a tag that never closes and stores `\\(a` -- the caption is truncated on
    the way in, and no test that only checks "an ImageElement was created"
    would ever see it."""
    obj = _build(tmp_path, "\\(a<b\\)")
    assert obj.figcaption == "\\(a&lt;b\\)"


def test_a_plain_caption_is_unchanged(tmp_path):
    assert _build(tmp_path, "Rysunek 1").figcaption == "Rysunek 1"


def test_an_absent_caption_stays_empty(tmp_path):
    assert _build(tmp_path, "").figcaption == ""


@pytest.mark.parametrize("caption", ["a & b", "x > y", "<b>lit</b>"])
def test_what_the_loader_stores_survives_the_next_save(tmp_path, caption):
    """The stored value is re-sanitised on every later edit. If escaping and
    sanitising disagree, the first edit of an imported image silently rewrites
    its caption."""
    obj = _build(tmp_path, caption)
    before = obj.figcaption
    obj.save()
    obj.refresh_from_db()
    assert obj.figcaption == before
