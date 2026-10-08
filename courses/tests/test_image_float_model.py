import pytest

from courses.models import ImageElement

SIZES = ["small", "medium", "large", "full"]


def test_float_right_defaults_to_false():
    assert ImageElement().float_right is False


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("flag", [True, False])
def test_floats_only_for_a_flagged_small(size, flag):
    # D2: Small only. A stored True on Medium/Large/Full (import, legacy) is ignored.
    expected = flag and size == "small"
    assert ImageElement(size=size, float_right=flag).floats is expected
