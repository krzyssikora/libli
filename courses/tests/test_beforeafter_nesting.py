import pytest

from courses import builder
from courses.builder import NestingError
from courses.models import BeforeAfterElement
from courses.models import Element
from courses.models import TabsElement
from tests.factories import make_course_with_unit


def _ba(unit, parent=None, tab=""):
    obj = BeforeAfterElement.objects.create()
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "slot", [BeforeAfterElement.BEFORE_SLOT_ID, BeforeAfterElement.AFTER_SLOT_ID]
)
def test_resolve_scope_accepts_both_slots(slot):
    """Mutant: registry lambda emits only one slot -> the other 400s."""
    _course, unit = make_course_with_unit()
    join = _ba(unit)
    got_join, got_slot = builder.resolve_scope(unit, str(join.pk), slot, "text")
    assert got_join == join and got_slot == slot


@pytest.mark.django_db
def test_resolve_scope_rejects_an_unknown_slot():
    _course, unit = make_course_with_unit()
    join = _ba(unit)
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(join.pk), "bogus", "text")


@pytest.mark.django_db
def test_before_after_nests_inside_another_container():
    """Seam 4: without "before_after" in NESTABLE_TYPE_KEYS this raises."""
    _course, unit = make_course_with_unit()
    top = Element.objects.create(
        unit=unit,
        content_object=TabsElement.objects.create(data=TabsElement.default_data()),
    )
    tab_id = top.content_object.data["tabs"][0]["id"]
    join, slot = builder.resolve_scope(unit, str(top.pk), tab_id, "beforeafter")
    assert join == top and slot == tab_id


@pytest.mark.django_db
def test_a_graded_question_is_accepted_as_a_child_of_a_lesson_before_after():
    """Was `test_a_graded_question_is_still_refused_as_a_child`, whose docstring
    named this very change as its mutant: "add "choice" to NESTABLE_TYPE_KEYS ->
    accepted". The refusal is now conditional on unit.unit_type, and
    make_course_with_unit() builds a LESSON. The quiz-refusal companion lands with
    the resolve_scope clause that makes it pass, not here.

    Mutant: drop "choice" from NESTABLE_TYPE_KEYS -> NestingError.
    """
    _course, unit = make_course_with_unit()
    join = _ba(unit)
    parent, tab = builder.resolve_scope(
        unit, str(join.pk), BeforeAfterElement.BEFORE_SLOT_ID, "choice"
    )
    assert parent == join
    assert tab == BeforeAfterElement.BEFORE_SLOT_ID


@pytest.mark.django_db
def test_a_non_widened_question_type_is_still_refused_as_a_child():
    """The widening is THREE keys plus the pre-existing fill_blank, not "questions".
    extended_response stays top-level-only, so the allowlist still has teeth."""
    _course, unit = make_course_with_unit()
    join = _ba(unit)
    with pytest.raises(NestingError):
        builder.resolve_scope(
            unit, str(join.pk), BeforeAfterElement.BEFORE_SLOT_ID, "extended_response"
        )


def test_form_key_alias_exists():
    """Without the alias the card is offered nested and every click 400s."""
    assert builder._NESTABLE_FORM_KEY_ALIASES["beforeafter"] == "before_after"


def test_registry_cap_is_none():
    """A fixed-slot container is never truncated, so its cap is None -- not 2.
    None is what makes paste_allowed SKIP the position check rather than apply a
    bound that happens to work.
    """
    assert builder._CONTAINER_REGISTRY[BeforeAfterElement][3] is None


def test_slot_key_entry_is_the_fixed_id_set():
    from courses.transfer.payloads import _CONTAINER_SLOT_KEY

    assert _CONTAINER_SLOT_KEY["before_after"] == frozenset(BeforeAfterElement.SLOT_IDS)


def test_nestable_keys_are_a_subset_of_serializers():
    """The sibling-invariant guard every transfer test carries. This is what
    catches seam 4 landing before the export.py SERIALIZERS registration.
    """
    from courses.transfer.export import SERIALIZERS

    assert "before_after" in builder.NESTABLE_TYPE_KEYS
    assert builder.NESTABLE_TYPE_KEYS <= set(SERIALIZERS)
