import pytest

from courses.models import MarkDoneElement
from courses.models import MarkDoneItem

pytestmark = pytest.mark.django_db


def test_roundtrip_serialize_validate_build():
    from courses.transfer.export import SERIALIZERS
    from courses.transfer.importer import BUILDERS
    from courses.transfer.payloads import VALIDATORS

    el = MarkDoneElement.objects.create(prompt="Prep")
    MarkDoneItem.objects.create(element=el, content="one")
    MarkDoneItem.objects.create(element=el, content="two")
    model, ser = SERIALIZERS["mark_done"]
    payload = ser(el, {})
    assert payload == {"prompt": "Prep", "items": ["one", "two"]}
    VALIDATORS["mark_done"](payload, "e1", {})  # no raise
    new_el, items = BUILDERS["mark_done"](payload, {})
    new_el.save()
    for it in items:
        it.element = new_el
        it.full_clean()
        it.save()
    assert [i.content for i in new_el.items.all()] == ["one", "two"]


def test_validator_rejects_bad_shape():
    from courses.transfer.payloads import VALIDATORS
    from courses.transfer.schema import TransferError

    with pytest.raises(TransferError):
        VALIDATORS["mark_done"]({"prompt": "x"}, "e1", {})  # missing items
    with pytest.raises(TransferError):
        VALIDATORS["mark_done"](
            {"prompt": "x", "items": ["a" * 600]}, "e1", {}
        )  # MAX_LEN
