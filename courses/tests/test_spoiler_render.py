import pytest

from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _spoiler_with_children(n):
    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="Show", body="")
    join = Element.objects.create(unit=unit, content_object=sp)
    for i in range(n):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=f"<p>child {i}</p>"),
            parent=join,
            tab_id=SpoilerElement.SLOT_ID,
        )
    return sp


def test_children_share_one_rule_wrapper():
    """The revealed region must be ONE box so the left rule is CONTINUOUS. Per-child
    borders cannot be: a child's inner element margins collapse THROUGH the child
    (measured: 16px gaps between the child boxes), so the rule would come out
    segmented. The wrapper is also what gives the element-based spoiler the indent
    the legacy body-only spoiler has always had."""
    html = _spoiler_with_children(3).render()
    assert html.count('class="spoiler__children"') == 1
    assert html.count('class="spoiler__child"') == 3
    # Every child sits INSIDE the wrapper — nothing left stranded outside the rule.
    region = html.split('class="spoiler__children"')[1]
    assert region.count('class="spoiler__child"') == 3


def test_single_child_gets_the_rule_too():
    """The rule went missing for ANY element-based spoiler, not just multi-child
    ones — a one-child spoiler looked just as unbounded."""
    assert 'class="spoiler__children"' in _spoiler_with_children(1).render()


def test_legacy_body_spoiler_gets_no_wrapper():
    """The body path already carries its own rule on `.spoiler__body`; wrapping it
    too would double the border."""
    html = SpoilerElement.objects.create(label="S", body="<p>a</p>").render()
    assert "spoiler__children" not in html
    assert 'class="el el--text spoiler__body"' in html


def test_render_shows_label_and_body():
    el = SpoilerElement.objects.create(label="Show solution", body="<p>answer</p>")
    html = el.render()
    assert "<details" in html and 'class="spoiler"' in html
    assert "<summary" in html and "Show solution" in html
    assert 'class="el el--text spoiler__body"' in html
    assert "<p>answer</p>" in html


def test_render_default_label_when_blank():
    el = SpoilerElement.objects.create(label="", body="<p>x</p>")
    html = el.render()
    assert "Reveal" in html  # {% trans "Reveal" %} default under the EN catalog


def test_render_carries_both_show_and_hide_labels():
    # Two-way toggle: the collapsed ("show") and open ("Hide") labels both ship in
    # the DOM; CSS swaps which is visible on [open]. Guards the "still says Reveal
    # after opening" regression.
    el = SpoilerElement.objects.create(label="Show solution", body="<p>x</p>")
    html = el.render()
    assert "spoiler__label--show" in html and "Show solution" in html
    assert "spoiler__label--hide" in html and "Hide" in html
