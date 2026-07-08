import pytest

from courses.models import SlideBreakElement
from courses.models import TextElement
from courses.slideshow import partition_into_slides
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element


def _unit():
    return ContentNodeFactory(course=CourseFactory(), kind="unit", unit_type="lesson")


def _text(unit):
    # returns the Element join-row
    return add_element(unit, TextElement.objects.create(body="x"))


def _brk(unit):
    return add_element(unit, SlideBreakElement.objects.create())


@pytest.mark.django_db
def test_no_breaks_single_slide():
    u = _unit()
    els = [_text(u), _text(u)]
    assert partition_into_slides(els) == [els]  # identity preserved


@pytest.mark.django_db
def test_split_and_identity():
    u = _unit()
    a, b = _text(u), _text(u)
    brk = _brk(u)
    c = _text(u)
    slides = partition_into_slides([a, b, brk, c])
    assert slides == [[a, b], [c]]
    assert brk not in slides[0] and brk not in slides[1]  # break consumed


@pytest.mark.django_db
def test_leading_trailing_consecutive_breaks_drop_empties():
    u = _unit()
    b0, a, b1, b2, c, b3 = _brk(u), _text(u), _brk(u), _brk(u), _text(u), _brk(u)
    # no empty slides
    assert partition_into_slides([b0, a, b1, b2, c, b3]) == [[a], [c]]


@pytest.mark.django_db
def test_only_breaks_yields_no_slides():
    u = _unit()
    assert partition_into_slides([_brk(u), _brk(u)]) == []


@pytest.mark.django_db
def test_empty_input():
    assert partition_into_slides([]) == []
