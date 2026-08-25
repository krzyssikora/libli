"""The editor must report a container's OWN text whatever its children are doing.

Two defects, one template region (`_element_row.html`, the spoiler and callout
branches -- the two container types that carry a `body` of their own):

1. The "has text" hint lives inside the `{% empty %}` arm of the children loop, so
   it is structurally UNREACHABLE once a child exists. Since #214 the body renders
   ABOVE the children on the student page, so exactly when both are present -- the
   case where an author most needs to know the text is there -- the editor says
   nothing about it at all.
2. A body cleared in the RTE used to leave `<p><br></p>` behind, which made the
   hint fire on an element carrying no text. That half is fixed on the write path
   (see test_blank_richtext_body.py); pinned here from the EDITOR's side, because
   the write-path fix and the template guard are independent and either could
   regress alone.

The fix is a body preview row rendered above the children list whenever the body
is non-blank, mirroring where the text actually renders.
"""

import pytest
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TextElement
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db

BODY_ROW = 'class="el-bodyrow'
EXCERPT = "Consider a right triangle"


def _editor_html(client, course, unit):
    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    resp = client.get(url)
    # Assert 200 first: a 403/302 otherwise surfaces as "el-bodyrow not in html"
    # and misdirects the debugging (same guard as test_callout_editor_row.py).
    assert resp.status_code == 200
    return resp.content.decode()


def _make(client, model, *, body, children):
    pa = make_pa(client, "pa")
    course, unit = make_course_with_unit(owner=pa)
    kw = {"kind": "example"} if model is CalloutElement else {}
    obj = model.objects.create(body=body, **kw)
    join = add_element(unit, obj)
    for i in range(children):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=f"<p>CHILD-{i}</p>"),
            parent=join,
            tab_id=model.SLOT_ID,
        )
    return course, unit


MODELS = [CalloutElement, SpoilerElement]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_body_row_shows_the_text_when_children_are_also_present(client, model):
    """Defect 1. `children=1` is the whole point -- with no child the old
    `{% empty %}` hint already fired, so a zero-child fixture cannot fail here."""
    course, unit = _make(
        client, model, body=f"<p>{EXCERPT} with legs a and b.</p>", children=1
    )
    html = _editor_html(client, course, unit)
    assert BODY_ROW in html
    assert EXCERPT in html


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_body_row_is_absent_when_there_is_no_text(client, model):
    course, unit = _make(client, model, body="", children=1)
    html = _editor_html(client, course, unit)
    assert BODY_ROW not in html


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_body_row_opens_this_container_s_own_edit_form(client, model):
    """The row is the only way to reach the body once children exist, so it must
    carry BOTH attributes editor.js:561-564 reads -- it fetches `data-form-url`
    and then scrolls/aligns by `data-element-id`. A row with one but not the other
    renders identically and does nothing on click."""
    course, unit = _make(client, model, body="<p>Body text</p>", children=1)
    html = _editor_html(client, course, unit)
    join = Element.objects.get(unit=unit, parent__isnull=True)
    form_url = reverse(
        "courses:manage_element_form", kwargs={"slug": course.slug, "pk": join.pk}
    )
    # One tag must carry all three: el-select (the delegated click target),
    # the id, and the url. Asserting them separately would pass on three
    # different elements in the row.
    marker = (
        f'class="el-bodyrow el-select" data-element-id="{join.pk}" '
        f'data-form-url="{form_url}"'
    )
    assert marker in html


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_a_body_cleared_in_the_rte_leaves_no_trace_in_the_editor(client, model):
    """Defect 2, from the editor's side. `<p><br></p>` is the MEASURED Ctrl+A +
    Delete output of the RTE surface."""
    course, unit = _make(client, model, body="<p><br></p>", children=0)
    html = _editor_html(client, course, unit)
    assert BODY_ROW not in html
    assert "has text" not in html
    assert "is empty." in html


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_a_body_cleared_in_the_rte_renders_no_blank_line(client, model):
    """Defect 2, from the STUDENT page's side -- the blank line the user reported.
    Asserted on the rendered element, not on the stored field: the `{% if el.body %}`
    guard in the two element templates is what actually emits the empty paragraph."""
    kw = {"kind": "example"} if model is CalloutElement else {}
    obj = model.objects.create(body="<p><br></p>", **kw)
    out = obj.render()
    assert "__body" not in out
    assert "<br>" not in out
