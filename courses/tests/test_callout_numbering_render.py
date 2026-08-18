"""Rendering of the callout number. Assertions are in ENGLISH: LANGUAGE_CODE is "en"
and conftest's _reset_active_language activates it around every test."""

import pytest

from courses.models import CalloutElement
from courses.models import Element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

UNNUMBERED_CUSTOM_HEADING = '<span class="callout__heading">Suma ciagu</span>'


def _rendered(el, join, numbers):
    return el.render(
        element=join, state={}, slug="s", node_pk=1, page={"callout_numbers": numbers}
    )


def test_a_numbered_callout_shows_label_space_number():
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {join.pk: 3})
    assert 'Example <span class="callout__number">3</span>' in html


def test_a_numbered_callout_has_no_trailing_period_without_a_heading():
    """Spec D7. Mutant: emit `{{ number }}.` -> this fails."""
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(kind="task", numbered=True, body="")
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {join.pk: 2})
    assert '<span class="callout__number">2</span></span>' in html


def test_a_numbered_callout_with_a_custom_heading_reads_label_number_period_heading():
    """D4 -- the ONE row of the spec's table that changes existing semantics, and the
    only branch with zero real rows exercising it (0 of 369 callouts have a heading).

    Mutant A: swap the label/heading order.
    Mutant B: emit `display_heading` instead of `heading` in the numbered branch,
              which renders the custom text twice or drops the label.
    """
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(
        kind="example", heading="Suma ciagu", numbered=True, body=""
    )
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {join.pk: 3})
    assert (
        '<span class="callout__heading">Example '
        '<span class="callout__number">3</span>. Suma ciagu</span>'
    ) in html


def test_an_unnumbered_callout_renders_exactly_as_before():
    """The custom heading still REPLACES the label when unnumbered -- unchanged
    behaviour. Mutant: make the numbered branch unconditional -> this fails."""
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(
        kind="example", heading="Suma ciagu", numbered=False, body=""
    )
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {})
    assert UNNUMBERED_CUSTOM_HEADING in html
    assert "callout__number" not in html


def test_a_callout_absent_from_the_map_renders_no_number():
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {})
    assert "callout__number" not in html
    assert '<span class="callout__heading">Example</span>' in html


def test_render_without_an_element_does_not_raise():
    """CalloutElement.render's signature is `element=None`, and eight sites in
    test_callout_render.py call .render() bare. Mutant: drop the
    `element is not None` guard -> AttributeError on NoneType.pk."""
    html = CalloutElement(kind="example", numbered=True, body="").render()
    assert "callout__number" not in html
