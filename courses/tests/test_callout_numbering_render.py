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


def test_the_form_exposes_numbered():
    from courses.element_forms import CalloutElementForm

    assert "numbered" in CalloutElementForm.Meta.fields


def test_the_editor_partial_renders_the_checkbox(client):
    """Assert ATTRIBUTE SUBSTRINGS, not a whole tag: the markup carries
    `{% if form.numbered.value %}checked{% endif %}`, so the rendered output is
    `... name="numbered" checked>` or `... name="numbered" >` -- the literal
    `<input type="checkbox" name="numbered">` is a substring of NEITHER, and
    asserting it would be red on a correct build.
    """
    from django.urls import reverse

    from tests.factories import CourseFactory
    from tests.factories import ContentNodeFactory
    from tests.factories import make_pa

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "callout", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    body = resp.content.decode()
    assert 'type="checkbox"' in body
    assert 'name="numbered"' in body
    # The ticked default IS R2: a new callout must arrive checked.
    assert 'name="numbered" checked' in body


def test_an_unnumbered_instance_renders_the_box_unchecked():
    from courses.element_forms import CalloutElementForm

    el = CalloutElement(kind="tip", numbered=False)
    form = CalloutElementForm(instance=el)
    assert form["numbered"].value() is False


def test_element_summary_never_shows_a_number(client):
    """D6: the collapsed editor row list is deliberately unchanged.

    Do NOT assert `element_summary(el) == el.display_heading`: that branch is
    literally `return el.display_heading`, so both sides move together under the
    mutant and the assertion is a tautology. The discriminating assertions are the
    hardcoded literal and the no-digit check.

    Mutant: fold the number into display_heading -> this fails, while the template
    mutants in this file would all still pass.
    """
    # A registered @register.filter (courses_manage_extras.py:129-130); the callout
    # branch at :157-158 is `return el.display_heading`. Callable directly as a plain
    # function.
    from courses.templatetags.courses_manage_extras import element_summary

    el = CalloutElement(kind="example", numbered=True, heading="")
    summary = element_summary(el)
    assert summary == "Example"
    assert not any(ch.isdigit() for ch in summary)


def test_the_seeded_demo_tip_callout_is_not_numbered():
    """The only production CalloutElement construction site outside _build_callout.
    A seeded Tip arriving numbered contradicts D2 in the very course the help
    screenshots are taken against.

    Mutant: drop `numbered=False` from seed_demo_course._callout -> this fails.
    """
    import inspect

    from courses.management.commands import seed_demo_course

    src = inspect.getsource(seed_demo_course.Command._callout)
    assert "numbered=False" in src
