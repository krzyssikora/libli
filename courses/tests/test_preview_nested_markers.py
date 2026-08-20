"""Nested elements must be locatable in the EDITOR PREVIEW and invisible on the
STUDENT page. See docs/superpowers/specs/2026-08-20-preview-nested-element-locate-design.md.

SCOPING IS LOAD-BEARING AND DIFFERS PER TEST:
  * Editor page: the EDITOR pane also carries [data-element-id] (on the el-act-edit
    buttons in _element_row.html), so an unscoped assertion passes vacuously on a
    broken build. Parse ONCE and root the selector at [data-scope="preview"].
  * Student page: there IS NO [data-scope="preview"] node -- it exists only in the
    editor's _preview.html. Rooting there selects zero nodes and "neither half is
    present" is trivially true, leaving mutants c1 and c2 both alive. So the student
    test selects the .<container>__child wrappers directly and asserts the selection
    is NON-EMPTY first.
"""

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from courses.models import BeforeAfterElement
from courses.models import CalloutElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db

CHILD_CLASSES = [
    "tabs__child",
    "twocolumn__child",
    "spoiler__child",
    "callout__child",
    "ba__child",
]


def _text(body="x"):
    return TextElement.objects.create(body=f"<p>{body}</p>")


def _fixed_tabs_data():
    """default_data() mints ids with secrets.token_hex(3) (models.py:1785), which are
    rendered into data-tab-id, id="tabs-{eid}-{tid}-panel", the matching -label id and
    aria-labelledby. Two renders of the SAME tree would therefore differ every time,
    which would make Task 11's master-vs-master control diff impossible to satisfy.
    Overwrite the ids with fixed literals; the shape is taken from default_data() so
    this stays correct if the shape changes."""
    d = TabsElement.default_data()
    for i, t in enumerate(d["tabs"], start=1):
        t["id"] = f"t{i:06d}"
    return d


def _fixed_columns_data():
    """Same, for TwoColumnElement -- ids are minted with secrets.token_hex(3)
    (models.py:1971) and rendered into data-column-id."""
    d = TwoColumnElement.default_data()
    for i, c in enumerate(d["columns"], start=1):
        c["id"] = f"c{i:06d}"
    return d


def _containers(unit):
    """One of each of the five containers at top level, each holding one text child.

    Fixtures are built with DIRECT Element(parent=...) rows -- as
    test_image_size_render.py does -- NOT through builder.resolve_scope, whose
    clause 3/4 depth rules would couple this test to the nesting policy it is not
    testing.

    Returns {child_class: child_join_pk}.
    """
    out = {}

    tabs = TabsElement.objects.create(data=_fixed_tabs_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, parent=None)
    tab_id = tabs.data["tabs"][0]["id"]
    out["tabs__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-tab"), parent=tabs_join, tab_id=tab_id
    ).pk

    two = TwoColumnElement.objects.create(data=_fixed_columns_data())
    two_join = Element.objects.create(unit=unit, content_object=two, parent=None)
    col_id = two.data["columns"][0]["id"]
    out["twocolumn__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-col"), parent=two_join, tab_id=col_id
    ).pk

    sp = SpoilerElement.objects.create(label="s")
    sp_join = Element.objects.create(unit=unit, content_object=sp, parent=None)
    out["spoiler__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-spoiler"), parent=sp_join,
        tab_id=SpoilerElement.SLOT_ID,
    ).pk

    co = CalloutElement.objects.create(heading="C")
    co_join = Element.objects.create(unit=unit, content_object=co, parent=None)
    out["callout__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-callout"), parent=co_join,
        tab_id=CalloutElement.SLOT_ID,
    ).pk

    ba = BeforeAfterElement.objects.create()
    ba_join = Element.objects.create(unit=unit, content_object=ba, parent=None)
    out["ba__child"] = Element.objects.create(
        unit=unit, content_object=_text("in-ba"), parent=ba_join,
        tab_id=BeforeAfterElement.SLOT_IDS[0],
    ).pk

    return out


def test_editor_preview_marks_every_nested_child(client):
    """Mutants: (a1) drop the marker from ONE template -> RED (all five asserted, not
    a sample). (a2) emit data-element-id WITHOUT the prev-el class -> RED (the pair is
    asserted on ONE node; the consumer selector is .prev-el[data-element-id=...], so
    the class is as load-bearing as the attribute)."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    pks = _containers(unit)

    html = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode()
    soup = BeautifulSoup(html, "html.parser")

    for cls in CHILD_CLASSES:
        sel = f'[data-scope="preview"] .{cls}.prev-el[data-element-id="{pks[cls]}"]'
        assert soup.select_one(sel) is not None, f"missing marker pair for .{cls}"

    # child.pk is the Element JOIN ROW pk -- the same identity the editor rows carry
    # as data-element, and the same one setHighlight/scrollPreviewTo are called with.
    row = soup.select_one(f'.el-row[data-element="{pks["callout__child"]}"]')
    assert row is not None, "the marker pk is not the editor row's data-element pk"


def test_editor_preview_marks_a_depth_3_child(client):
    """Depth 3 proves the recursion carries editor_preview across TWO
    CONTAINER_MODELS barriers. The pair is NAMED (tabs inside a spoiler) rather than
    left to choice: the pairs differ in risk (callout-in-callout is the mildest) and
    this mirrors the shape e2e 5 exercises."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    sp = SpoilerElement.objects.create(label="s")
    sp_join = Element.objects.create(unit=unit, content_object=sp, parent=None)
    tabs = TabsElement.objects.create(data=_fixed_tabs_data())
    tabs_join = Element.objects.create(
        unit=unit, content_object=tabs, parent=sp_join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    deep = Element.objects.create(
        unit=unit, content_object=_text("deep"), parent=tabs_join,
        tab_id=tabs.data["tabs"][0]["id"],
    )

    html = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode()
    soup = BeautifulSoup(html, "html.parser")
    sel = (
        f'[data-scope="preview"] .spoiler__child '
        f'.tabs__child.prev-el[data-element-id="{deep.pk}"]'
    )
    assert soup.select_one(sel) is not None


def test_student_page_carries_neither_marker_half(client):
    """Mutants: (c1) drop the {% if editor_preview %} gate -> RED.
    (c2) gate the ATTRIBUTE but not the CLASS -> RED (both halves asserted; a
    class-only leak would put prev-el on every student page while an
    attribute-only assertion stayed green).

    NOT scoped to [data-scope="preview"] -- see the module docstring."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _containers(unit)

    # The student lesson route is `courses:lesson_unit` (courses/urls.py:27) and its
    # kwarg is `node_pk`, NOT `pk` (views.py:807 `def lesson_unit(request, slug,
    # node_pk)`). This is the shape tests/test_e2e_tabs.py::_lesson_url already uses.
    html = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    soup = BeautifulSoup(html, "html.parser")

    wrappers = [n for cls in CHILD_CLASSES for n in soup.select(f".{cls}")]
    # Without this the whole test is vacuous for the same reason the preview-rooted
    # selector would be: an empty selection satisfies every "is absent" assertion.
    assert wrappers, "no child wrappers rendered -- fixture or URL is wrong"
    for n in wrappers:
        cls_ = n.get("class")
        assert not n.has_attr("data-element-id"), f"leaked attr on {cls_}"
        assert "prev-el" not in (cls_ or []), f"leaked class on {cls_}"
