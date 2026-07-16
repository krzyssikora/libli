import pytest

from courses.migrations import _state_rekey as rekey

pytestmark = pytest.mark.django_db


def _apps_shim():
    """The real app registry satisfies apps.get_model in these unit tests; the
    migration itself receives the historical registry at runtime."""
    from django.apps import apps

    return apps


def test_forward_rekeys_content_pk_to_join_row_pk_and_wraps_items():
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import UnitProgress
    from tests.factories import add_element
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    student = make_verified_user()
    # Simulate the OLD shape: content pk key, BARE LIST value.
    up = UnitProgress.objects.create(student=student, unit=unit, element_state={})
    old = {str(obj.pk): [i1.pk]}

    new = rekey.forward_state(_apps_shim(), up.unit_id, old)

    assert new == {str(el.pk): {"items": [i1.pk]}}


def test_forward_drops_orphaned_key():
    from courses.models import UnitProgress
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    _course, unit = make_course_with_unit()
    student = make_verified_user()
    up = UnitProgress.objects.create(student=student, unit=unit, element_state={})
    # 999999: no MarkDoneElement, therefore no join row -> already-dead data.
    assert rekey.forward_state(_apps_shim(), up.unit_id, {"999999": [1]}) == {}


def test_backward_unwraps_items_and_drops_non_markdone_blobs():
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import RevealGateElement
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    gate = RevealGateElement.objects.create()
    gate_el = add_element(unit, gate)

    state = {str(el.pk): {"items": [i1.pk]}, str(gate_el.pk): {"open": True}}
    out = rekey.backward_state(_apps_shim(), state)

    # markdone -> content pk + BARE list; the gate blob is DROPPED (checklist_state
    # structurally cannot represent it).
    assert out == {str(obj.pk): [i1.pk]}


def test_forward_rekeys_a_TAB_NESTED_element():
    # [S1] spec requirement. The nested join row is created directly (parent+tab_id),
    # NOT via add_element -- and its pk necessarily differs from the content pk,
    # because the Tabs join row is created first.
    from courses.models import Element
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import TabsElement
    from courses.models import UnitProgress
    from tests.factories import add_element
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000001", "label": "One"}]}
    )
    parent = add_element(unit, tabs)
    obj = MarkDoneElement.objects.create(prompt="P")
    child = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id="t000001"
    )
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    student = make_verified_user()
    up = UnitProgress.objects.create(student=student, unit=unit, element_state={})

    new = rekey.forward_state(_apps_shim(), up.unit_id, {str(obj.pk): [i1.pk]})

    assert new == {str(child.pk): {"items": [i1.pk]}}
    # Element and MarkDoneElement draw from INDEPENDENT sequences, so divergence is
    # overwhelmingly likely but not guaranteed -- skip rather than fail if they collide,
    # since the real assertion above already holds either way.
    if child.pk == obj.pk:
        pytest.skip(
            "Element and MarkDoneElement pks coincided; re-key is untested here"
        )


def test_forward_and_backward_handle_empty_and_absent_state():
    # [S1] spec requirement: "{} and absent state".
    assert rekey.forward_state(_apps_shim(), None, {}) == {}
    assert rekey.forward_state(_apps_shim(), None, None) == {}
    assert rekey.backward_state(_apps_shim(), {}) == {}
    assert rekey.backward_state(_apps_shim(), None) == {}


def test_forward_and_backward_ignore_garbage_without_raising():
    assert rekey.forward_state(_apps_shim(), None, {"x": "nope"}) == {}
    assert rekey.backward_state(_apps_shim(), {"y": "nope"}) == {}
