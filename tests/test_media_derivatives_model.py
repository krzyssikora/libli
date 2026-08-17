import pytest

from courses.models import DerivativesState
from tests.factories import CourseFactory
from tests.factories import make_image_asset


@pytest.mark.django_db
def test_new_fields_default_to_the_pending_state(course_with_image_media_root):
    """Blank-is-safe: a freshly created asset carries no derivative claims.

    width/height are PositiveIntegerField(null=True) so their untouched value is
    None, NOT "" — a test written as "all five stay ''" asserts the wrong thing
    for two of them.
    """
    course = CourseFactory()
    asset = make_image_asset(course, "x.png", size=(1000, 800))
    assert asset.thumb.name in ("", None)
    assert asset.web.name in ("", None)
    assert asset.width is None
    assert asset.height is None
    assert asset.derivatives_state == ""


@pytest.mark.django_db
def test_derivatives_state_choices_are_the_three_terminal_values():
    """The four values are load-bearing for backfill idempotency, so a typo'd
    literal must be a hard error rather than a row silently reprocessed forever."""
    assert DerivativesState.OK == "ok"
    assert DerivativesState.SKIPPED == "skipped"
    assert DerivativesState.FAILED == "failed"
    assert set(DerivativesState.values) == {"ok", "skipped", "failed"}


@pytest.mark.django_db
def test_derivative_fields_accept_a_long_name(course_with_image_media_root):
    """max_length=200, not Django's default 100: the derivatives/ prefix is 12
    chars longer than courses/media/, plus a -896.webp suffix and any storage
    collision suffix. At 100, get_available_name silently truncates stems for the
    long-named assets the LAL import produced."""
    course = CourseFactory()
    asset = make_image_asset(course, "x.png", size=(1000, 800))
    long_name = "courses/media/derivatives/" + ("a" * 150) + "-896.webp"
    assert len(long_name) > 100
    asset.web.name = long_name
    asset.save(update_fields=["web"])
    asset.refresh_from_db()
    assert asset.web.name == long_name
