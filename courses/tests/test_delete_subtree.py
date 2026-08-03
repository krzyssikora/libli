"""Delete path: the whole subtree under a deleted container must go, at EVERY depth.

A concrete element row is reachable only through the Element GFK join, which DB
cascade cannot traverse. Deleting a container cascades its descendants' JOIN rows
but leaves their concretes behind unless something walks the tree first. These
tests pin that walk -- and, just as importantly, pin where it must NOT reach.
"""

import json

import pytest

from courses import builder
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.tests.test_nesting_rule import _mk
from tests.factories import make_course_with_unit

# NOTE the paths: `tests.factories`, NOT `courses.tests.factories` (which does not
# exist), and `_mk` is the SHARED ORM fixture builder from test_nesting_rule.py --
# do not fork a parallel one here.


def _token(unit):
    """The optimistic-concurrency token builder/save takes: unit.updated.isoformat().
    Refreshed from the DB first, so the microsecond value matches what _check_token
    compares against (mirrors tests/test_tabs_form_views.py's _post)."""
    unit.refresh_from_db()
    return unit.updated.isoformat()


@pytest.mark.django_db
def test_deleting_a_container_removes_grandchild_concretes():
    """Depth-3 subtree: tabs > spoiler > text. The text concrete is reachable only
    through the GFK, which DB cascade cannot traverse."""
    course, unit = make_course_with_unit()
    tabs = _mk(unit, "tabs")
    tab_id = tabs.content_object.data["tabs"][0]["id"]
    spoiler = _mk(unit, "spoiler", parent=tabs, tab=tab_id)
    text = _mk(unit, "text", parent=spoiler, tab=SpoilerElement.SLOT_ID)
    text_pk = text.content_object.pk

    builder.delete_element(course, tabs.pk, _token(unit))

    assert not TextElement.objects.filter(pk=text_pk).exists()
    assert not SpoilerElement.objects.filter(pk=spoiler.object_id).exists()
    assert not Element.objects.filter(pk__in=[tabs.pk, spoiler.pk, text.pk]).exists()


@pytest.mark.django_db
def test_delete_collects_a_child_whose_tab_id_matches_no_slot():
    """resolved_tabs() runs the DESTRUCTIVE normalize_data and SKIPS children whose
    tab_id resolves to no slot. The collector must descend join.children instead, or
    this child's concrete orphans -- a REGRESSION vs today's filter(parent=el)."""
    course, unit = make_course_with_unit()
    tabs = _mk(unit, "tabs")
    nosuch = "taaaaaa"  # well-formed, but minted ids are random -- never a real slot
    assert nosuch not in {t["id"] for t in tabs.content_object.data["tabs"]}
    orphan = _mk(unit, "text", parent=tabs, tab=nosuch)
    orphan_pk = orphan.content_object.pk
    # The read-side accessor already ignores it; the delete path must not.
    assert all(
        orphan.pk not in {c.pk for c in kids}
        for _tab, kids in tabs.content_object.resolved_tabs()
    )

    builder.delete_element(course, tabs.pk, _token(unit))

    assert not TextElement.objects.filter(pk=orphan_pk).exists()


@pytest.mark.django_db
def test_removing_a_tab_keeps_sibling_tab_content():
    """Two assertions. The second is what catches the wrong collection root:
    rooting at the tabs join sweeps KEPT tabs' descendants too, leaving live
    Element rows pointing at deleted concretes -- silent destruction, no error.

    FIXTURE: THREE tabs. tab A: spoiler > text_a | tab B: spoiler > text_b | tab C.
    Three, not two, because TabsElement.MIN_TABS == 2 and TabsElementForm.clean_data
    rejects any payload with fewer than 2 tabs: submitting a single survivor makes
    save_element raise ElementFormInvalid BEFORE `old_ids - new_ids` is computed, so
    nothing would be removed and the test would pass vacuously.
    """
    course, unit = make_course_with_unit()
    tabs = _mk(unit, "tabs")
    obj = tabs.content_object
    tab_a, tab_b = (t["id"] for t in obj.data["tabs"])
    tab_c = TabsElement.new_tab_id({tab_a, tab_b})
    obj.data = {"tabs": [*obj.data["tabs"], {"id": tab_c, "label": "C"}]}
    obj.save()  # normalize_labels_and_ids is non-destructive: all three survive
    assert len(obj.data["tabs"]) == 3

    sp_a = _mk(unit, "spoiler", parent=tabs, tab=tab_a)
    text_a_pk = _mk(
        unit, "text", parent=sp_a, tab=SpoilerElement.SLOT_ID
    ).content_object.pk
    sp_b = _mk(unit, "spoiler", parent=tabs, tab=tab_b)
    text_b_pk = _mk(
        unit, "text", parent=sp_b, tab=SpoilerElement.SLOT_ID
    ).content_object.pk

    # ACT: submit the TWO survivors, so exactly tab A's id disappears.
    payload = json.dumps(
        {"tabs": [{"id": tab_b, "label": "B"}, {"id": tab_c, "label": "C"}]}
    )
    builder.save_element(
        course,
        unit.pk,
        "tabs",
        str(tabs.pk),
        {"unit_token": _token(unit), "unit": str(unit.pk), "data": payload},
        {},
    )

    assert not TextElement.objects.filter(pk=text_a_pk).exists()  # removed tab
    assert TextElement.objects.filter(pk=text_b_pk).exists()  # KEPT tab
    assert not SpoilerElement.objects.filter(pk=sp_a.object_id).exists()
    assert SpoilerElement.objects.filter(pk=sp_b.object_id).exists()
    assert not Element.objects.filter(parent=tabs, tab_id=tab_a).exists()


@pytest.mark.django_db
def test_delete_terminates_on_a_parent_cycle():
    """The one genuinely reachable cycle: delete_element starts from a
    request-supplied element_pk, so an element inside a corrupt cycle IS reachable
    (unlike the export walk, which starts from parent__isnull=True roots).

    Dropping the collector's `seen` guard turns this into a RecursionError -- the
    reason the walk is recursive rather than an iterative worklist, which would
    instead spin forever (pytest-timeout is not installed, so a hanging mutant can
    never be verified RED)."""
    course, unit = make_course_with_unit()
    a = _mk(unit, "tabs")
    b = _mk(unit, "tabs", parent=a, tab=a.content_object.data["tabs"][0]["id"])
    a.parent = b
    a.save(update_fields=["parent"])

    builder.delete_element(course, a.pk, _token(unit))  # must not hang/RecursionError

    assert not Element.objects.filter(pk__in=[a.pk, b.pk]).exists()
    assert not TabsElement.objects.filter(
        pk__in=[a.object_id, b.object_id]
    ).exists()  # both concretes collected, neither orphaned
