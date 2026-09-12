from datetime import timedelta  # stdlib FIRST — I001 checks section order

import pytest
from django.utils import timezone


@pytest.mark.django_db
def test_status_key_moves_active_to_pending_to_closed():
    from demo.models import DemoKit
    from tests.factories import make_course

    course = make_course(slug="c1")
    kit = DemoKit.objects.create(
        label="SP 12",
        slug="sp-12",
        course=course,
        seed=1,
        pupil_count=20,
        expires_at=timezone.now() + timedelta(days=14),
    )
    assert kit.status_key == "active"

    kit.expires_at = timezone.now() - timedelta(days=1)
    assert kit.status_key == "pending_purge"

    kit.closed_at = timezone.now()
    kit.closed_reason = DemoKit.ClosedReason.EXPIRED
    assert kit.status_key == "closed_expired"

    kit.closed_reason = DemoKit.ClosedReason.REVOKED
    assert kit.status_key == "closed_revoked"


@pytest.mark.django_db
def test_slug_is_not_unique_so_a_school_can_get_a_second_kit():
    """A closed kit's row is retained, so a unique slug would block for ever."""
    from demo.models import DemoKit
    from tests.factories import make_course

    course = make_course(slug="c1")
    for _ in range(2):
        DemoKit.objects.create(
            label="SP 12",
            slug="sp-12",
            course=course,
            seed=1,
            pupil_count=20,
            expires_at=timezone.now() + timedelta(days=14),
        )
    assert DemoKit.objects.filter(slug="sp-12").count() == 2
