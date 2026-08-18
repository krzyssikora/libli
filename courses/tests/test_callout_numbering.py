"""The callout numbering walk and its data layer."""

import pytest

from courses.models import KIND_DEFAULT_NUMBERED
from courses.models import CalloutElement

pytestmark = pytest.mark.django_db


def test_kind_default_numbered_covers_every_kind():
    """Mutant: delete one entry -> a sixth kind (or a renamed one) silently gets
    no per-kind decision at backfill and at legacy-archive import."""
    assert set(KIND_DEFAULT_NUMBERED) == {k.value for k in CalloutElement.Kind}


def test_kind_default_numbered_values():
    assert KIND_DEFAULT_NUMBERED["example"] is True
    assert KIND_DEFAULT_NUMBERED["task"] is True
    assert KIND_DEFAULT_NUMBERED["warning"] is True
    assert KIND_DEFAULT_NUMBERED["note"] is False
    assert KIND_DEFAULT_NUMBERED["tip"] is False


def test_model_default_is_a_flat_true_regardless_of_kind():
    """D2 is scoped to backfill and legacy import. An author-created Note is born
    numbered; the author unticks. Mutant: add a per-kind form/model initial -> this
    fails, which is the point (see spec section 1)."""
    assert CalloutElement(kind="note").numbered is True
    assert CalloutElement(kind="example").numbered is True


def test_kind_label_ignores_a_custom_heading():
    """kind_label is the KIND's label; display_heading is the author-facing one."""
    el = CalloutElement(kind="example", heading="Suma ciagu")
    assert el.kind_label == "Example"
    assert el.display_heading == "Suma ciagu"


def test_display_heading_falls_back_to_kind_label():
    el = CalloutElement(kind="warning", heading="")
    assert el.display_heading == "Important"
    assert el.display_heading == el.kind_label


def test_kind_label_survives_an_unknown_kind():
    """The string fallback key.
    Mutant: `KIND_DEFAULT_HEADING[self.kind]` -> KeyError."""
    el = CalloutElement(kind="bogus", heading="")
    assert el.kind_label == "Example"
