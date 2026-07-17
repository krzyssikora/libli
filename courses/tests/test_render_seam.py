import pytest

from courses.models import FillGateElement
from courses.models import FillTableElement
from courses.models import GalleryElement
from courses.models import GuessNumberElement
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import SwitchGateElement
from courses.models import SwitchGridElement
from courses.models import TableElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

# Every concrete render() the generic branch can reach. A signature change that
# TypeErrors any of these breaks EVERY lesson containing that type -- the exact
# class of break plan-review and code-review both caught on the mark-done build.
# (model, required_kwargs) -- GuessNumberElement.target is NOT NULL with no default,
# so a bare .create() IntegrityErrors instead of testing the signature.
CONCRETES = [
    (TextElement, {}),
    (FillGateElement, {}),
    (SwitchGateElement, {}),
    (GuessNumberElement, {"target": 42}),
    (SwitchGridElement, {}),
    (TableElement, {}),
    (FillTableElement, {}),
    (GalleryElement, {}),
    (TabsElement, {}),
    (TwoColumnElement, {}),
]


@pytest.mark.parametrize(
    "model,kwargs", CONCRETES, ids=[m.__name__ for m, _ in CONCRETES]
)
def test_render_accepts_the_state_kwargs(model, kwargs):
    _course, unit = make_course_with_unit()
    obj = model.objects.create(**kwargs)
    el = add_element(unit, obj)
    # No TypeError, and no exception from any template.
    obj.render(element=el, state={}, slug="x", node_pk=unit.pk)


def test_fillgate_renders_the_eid():
    # NB this does NOT prove provenance: with one join row, a self-lookup and the
    # passed `element` resolve to the SAME pk, and it passes even before this task's
    # change (render(self, **_kwargs) absorbs element=/state= without a TypeError).
    # Provenance is covered with teeth by
    # test_leaf_render_does_not_self_look_up_its_join_row below.
    _course, unit = make_course_with_unit()
    obj = FillGateElement.objects.create(stem="", answers=[])
    el = add_element(unit, obj)
    html = obj.render(element=el, state={}, slug="x", node_pk=unit.pk)
    assert str(el.pk) in html


def test_eid_is_zero_sentinel_when_no_join_row():
    # eid == 0 means "a content object with no join row" (transient/mid-create).
    obj = FillGateElement.objects.create(stem="", answers=[])
    obj.render(element=None, state={}, slug=None, node_pk=None)  # no TypeError


def test_markdone_checked_is_resolved_from_the_join_row_key():
    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    i2 = MarkDoneItem.objects.create(element=obj, content="b")
    # Keyed by the JOIN-ROW pk. Keying by obj.pk (the old content-pk space) must NOT
    # resolve -- that is the whole point of the re-key.
    html = obj.render(
        element=el, state={el.pk: {"items": [i1.pk]}}, slug="s", node_pk=unit.pk
    )
    # Exactly one ticked box, and it is i1. ("checkbox" does not contain "checked".)
    assert html.count("checked") == 1
    # Scope the search to the ITEM LIST before indexing. Searching the whole document is
    # fragile: the hidden `element` field renders value="<pk>" BEFORE the list, and
    # Element / MarkDoneElement / MarkDoneItem draw from independent Postgres sequences
    # that are not reset between tests -- so that number can equal i2.pk, and the offset
    # comparison would fail against a CORRECT implementation.
    items_html = html[html.index('<ul class="markdone__list"') :]
    assert str(i1.pk) in items_html and str(i2.pk) in items_html  # both rendered
    i1_pos = items_html.index(f'value="{i1.pk}"')
    i2_pos = items_html.index(f'value="{i2.pk}"')
    assert i1_pos < items_html.index("checked") < i2_pos  # the tick sits on i1, not i2


def test_container_eid_comes_from_the_passed_row_not_join_row(monkeypatch):
    """Pin the containers' eid provenance BY IDENTITY: assertNumQueries cannot police
    them, because resolved_tabs() still calls join_row() (and must). Patch join_row to
    raise -- if render() still re-derives eid, this fails loudly.
    """
    _course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data={"tabs": [{"id": "t000001", "label": "One"}]})
    el = add_element(unit, obj)
    real = TabsElement.join_row
    calls = {"n": 0}

    def counting(self):
        calls["n"] += 1
        return real(self)

    monkeypatch.setattr(TabsElement, "join_row", counting)
    html = obj.render(element=el, state={}, slug="x", node_pk=unit.pk)
    assert str(el.pk) in html
    # resolved_tabs() legitimately calls join_row ONCE. If render() also calls it for
    # eid, this is 2 -- the lookup this task deletes.
    assert calls["n"] == 1


LEAF_SITES = [
    (FillGateElement, {}),
    (SwitchGateElement, {}),
    (GuessNumberElement, {"target": 42}),
    (SwitchGridElement, {}),
    (FillTableElement, {}),
]


@pytest.mark.parametrize(
    "model,kwargs", LEAF_SITES, ids=[m.__name__ for m, _ in LEAF_SITES]
)
def test_leaf_render_does_not_self_look_up_its_join_row(monkeypatch, model, kwargs):
    """The five leaves must take eid from the PASSED row, not re-derive it.

    Deterministic by construction: make `.elements` explode. A raw assertNumQueries
    baseline would need a magic number, and could not police Tabs/TwoColumn anyway --
    their resolved_*() join_row() call survives by design, so a re-introduced eid
    lookup would hide inside the total.
    """
    _course, unit = make_course_with_unit()
    obj = model.objects.create(**kwargs)
    el = add_element(unit, obj)

    class _Boom:
        def __get__(self, instance, owner):
            raise AssertionError(
                "render() self-looked-up its join row; take eid from `element`"
            )

    monkeypatch.setattr(model, "elements", _Boom())
    html = obj.render(element=el, state={}, slug="x", node_pk=unit.pk)
    assert str(el.pk) in html


def test_markdone_ignores_the_old_content_pk_key():
    # Falsification guard for the re-key: state keyed by the CONTENT pk must resolve
    # to nothing now. Without this, a half-done migration looks green.
    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    html = obj.render(
        element=el, state={obj.pk: {"items": [i1.pk]}}, slug="s", node_pk=unit.pk
    )
    if obj.pk != el.pk:  # if the two pk spaces happen to coincide, the test is vacuous
        assert "checked" not in html


def test_markdone_tolerates_a_drifted_blob_and_renders_fresh():
    # Read-side fail-open: a malformed stored blob is treated as absent, never a 500.
    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    MarkDoneItem.objects.create(element=obj, content="a")
    for drifted in ({el.pk: "nope"}, {el.pk: {"items": "abc"}}, {el.pk: {}}):
        html = obj.render(element=el, state=drifted, slug="s", node_pk=unit.pk)
        assert "checked" not in html


@pytest.mark.parametrize(
    "model,kwargs", CONCRETES, ids=[m.__name__ for m, _ in CONCRETES]
)
@pytest.mark.parametrize("placement", ["top", "tabs", "twocolumn"])
def test_lesson_renders_200_with_each_concrete(client, model, kwargs, placement):
    """The spec's [S1] gate: render a LESSON containing each concrete, top-level AND
    nested, asserting 200. The direct render() test above cannot catch a
    render_element/context-key mismatch -- it bypasses the tag, the context builder
    and the view, which is exactly what Task 3 Step 6 changes.
    """
    from django.urls import reverse

    from courses.models import Element
    from courses.models import Enrollment
    from tests.factories import make_verified_user

    course, unit = make_course_with_unit()
    obj = model.objects.create(**kwargs)
    if placement == "top":
        add_element(unit, obj)
    elif placement == "tabs":
        parent_obj = TabsElement.objects.create(
            data={"tabs": [{"id": "t000001", "label": "One"}]}
        )
        parent = add_element(unit, parent_obj)
        Element.objects.create(
            unit=unit, content_object=obj, parent=parent, tab_id="t000001"
        )
    else:
        parent_obj = TwoColumnElement.objects.create(
            data={"columns": [{"id": "c000001"}, {"id": "c000002"}]}
        )
        parent = add_element(unit, parent_obj)
        Element.objects.create(
            unit=unit, content_object=obj, parent=parent, tab_id="c000001"
        )
    student = make_verified_user(username="seam", email="seam@school.edu")
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
