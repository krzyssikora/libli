import pytest

from tests.factories import DragToImageQuestionElementFactory
from tests.factories import DragZoneFactory
from tests.factories import add_element
from tests.factories import make_quiz_unit  # quiz unit helper

pytestmark = pytest.mark.django_db


def _q_on_unit():
    unit = make_quiz_unit()
    q = DragToImageQuestionElementFactory()
    DragZoneFactory(question=q, correct_label="A", x=0.1, y=0.2, w=0.3, h=0.3, order=0)
    DragZoneFactory(question=q, correct_label="B", x=0.5, y=0.5, w=0.2, h=0.2, order=1)
    el = add_element(unit, q)
    return q, el


def test_render_has_badges_with_geometry_dataattrs_and_selects():
    q, el = _q_on_unit()
    html = q.render(element=el, mode="lesson")
    # numbered badges carry data-zone + fractional geometry for the JS overlay
    assert 'data-zone="0"' in html and 'data-x="0.1"' in html
    assert 'data-zone="1"' in html
    # no-JS select list below the image
    assert html.count('name="slot"') == 2
    # image + alt rendered
    assert "<img" in html and "data-dnd" in html


def test_geometry_dataattrs_use_period_decimal_under_localized_locale():
    """dnd.js reads the badge data-x/y/w/h via parseFloat(), which only understands a
    '.' decimal. Under a locale whose decimal separator is ',' (e.g. Polish) Django
    would otherwise localize {{ z.w }} to '0,3', which parseFloat() reads as 0 — the
    overlay drop targets then size to 0% and become invisible/unhittable ("no-drop
    everywhere"). The attributes must render unlocalized regardless of active locale."""
    from django.utils import translation

    q, el = _q_on_unit()
    with translation.override("pl"):
        html = q.render(element=el, mode="lesson")
    # '.'-decimal geometry survives; the localized ','-decimal form must NOT appear.
    assert 'data-x="0.1"' in html and 'data-w="0.3"' in html
    assert 'data-x="0,1"' not in html and 'data-w="0,3"' not in html


def test_render_does_not_leak_which_label_is_correct_pre_reveal():
    # The chip pool legitimately lists ALL labels (that is how DnD works), so the
    # no-leak invariant (spec §7.1) is NOT "no accepted text in the HTML" — it is
    # "pre-reveal HTML must not indicate WHICH label is correct per zone". Assert the
    # reveal block (the only thing that ties a zone to its accepted label) is absent,
    # and no per-zone correct-marker markup is present, when there is no mark_result.
    q, el = _q_on_unit()
    html = q.render(element=el, mode="quiz")
    assert "question__reveal" not in html  # reveal partial not rendered pre-reveal
    assert "answer-correct" not in html  # no per-zone correctness marker
    assert "data-correct" not in html
