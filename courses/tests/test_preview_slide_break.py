"""The editor's live preview shows a marker where a slide break sits.

slidebreakelement.html is intentionally empty (students never see a break -- it is
consumed by partition_into_slides), but the preview renders every top-level element
through the student template, so without its own branch a break is an invisible empty
<section> and the author cannot see where one slide ends.
"""

import re

import pytest
from django.urls import reverse

from courses.models import SlideBreakElement
from courses.models import TextElement
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _preview_html(client, layout):
    owner = make_login(client, "owner")
    course, unit = make_course_with_unit(owner=owner)
    for token in layout:
        if token == "brk":
            add_element(unit, SlideBreakElement.objects.create())
        else:
            add_element(unit, TextElement.objects.create(body=token))
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    start = body.index('data-scope="preview"')
    return body[start:]


def test_preview_marks_each_slide_break_between_its_neighbours(client):
    preview = _preview_html(client, ["alpha", "brk", "beta", "brk", "gamma"])
    markers = [m.start() for m in re.finditer(r'prev-slidebreak(?=[\s"])', preview)]
    # One lead marker for slide 1 (no break precedes it) + one per break.
    assert len(markers) == 3
    a, b, g = (preview.index(w) for w in ("alpha", "beta", "gamma"))
    assert markers[0] < a < markers[1] < b < markers[2] < g


def test_preview_without_a_break_shows_no_marker(client):
    preview = _preview_html(client, ["alpha", "beta"])
    assert "prev-slidebreak" not in preview


# --- numbering: must match the slides students get from partition_into_slides ---


def _labels(preview):
    """Each marker's visible label, in document order."""
    return re.findall(r'class="prev-slidebreak__label"[^>]*>([^<]*)<', preview)


def test_markers_number_the_slides_with_a_lead_marker_for_slide_one(client):
    preview = _preview_html(client, ["alpha", "brk", "beta", "brk", "gamma"])
    assert _labels(preview) == ["Slide 1 of 3", "Slide 2 of 3", "Slide 3 of 3"]
    assert preview.index("Slide 1 of 3") < preview.index("alpha")


def test_breaks_that_make_no_slide_stay_unnumbered(client):
    # Leading, doubled and trailing breaks: students get exactly 2 slides.
    layout = ["brk", "alpha", "brk", "brk", "beta", "brk"]
    preview = _preview_html(client, layout)
    assert _labels(preview) == [
        "Slide 1 of 2",
        "Slide break",
        "Slide 2 of 2",
        "Slide break",
    ]


def test_numbering_agrees_with_partition_into_slides():
    from courses.slideshow import preview_slide_marks

    class _Row:
        def __init__(self, pk, is_break):
            self.pk = pk
            self.content_object = SlideBreakElement() if is_break else TextElement()

    layout = "b t b b t t b t b"
    rows = [_Row(i, tok == "b") for i, tok in enumerate(layout.split())]
    marks = preview_slide_marks(rows)
    assert marks == {
        "total": 3,
        "lead": False,
        "breaks": {0: 1, 2: None, 3: 2, 6: 3, 8: None},
    }
    assert preview_slide_marks([]) == {"total": 0, "lead": False, "breaks": {}}
    no_breaks = [_Row(0, False)]
    assert preview_slide_marks(no_breaks)["lead"] is False


def test_an_editor_fragment_swap_keeps_the_slide_numbers(client):
    """_render_editor_fragments (every add/save/move/delete). Mutant: wire
    slide_marks only into _editor_page -> the first load is numbered and every
    later swap falls back to plain "Slide break"."""
    owner = make_login(client, "owner")
    course, unit = make_course_with_unit(owner=owner)
    for token in ["alpha", "brk", "beta"]:
        if token == "brk":
            add_element(unit, SlideBreakElement.objects.create())
        else:
            add_element(unit, TextElement.objects.create(body=token))
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "text", "unit": unit.pk, "unit_token": unit.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert _labels(resp.content.decode()) == ["Slide 1 of 2", "Slide 2 of 2"]
