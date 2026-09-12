from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from demo import errors


@pytest.mark.django_db
def test_purge_removes_every_kit_user_and_the_group_and_keeps_the_row():
    """T8. The rep has created a collection and force-submitted first, because
    those are the FKs most likely to block a delete."""
    from django.contrib.auth import get_user_model

    from courses.models import QuizSubmission
    from demo.models import DemoKit
    from demo.services import purge_kit
    from grouping.models import Collection
    from grouping.models import Group
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    Collection.objects.create(name="Demo", course=kit.course, owner=kit.teacher)
    # Force-submit one of the kit's quizzes, so QuizSubmission.submitted_by —
    # the FK this test's docstring singles out — is actually populated. Without
    # this the delete path it claims to exercise is untested (it is SET_NULL, so
    # the test passed either way, which is exactly the problem).
    unfinished = QuizSubmission.objects.filter(
        student__in=kit.users.all(), status=QuizSubmission.Status.IN_PROGRESS
    ).first()
    assert unfinished is not None, "the kit must carry an in-progress submission"
    unfinished.submitted_by = kit.teacher
    unfinished.status = QuizSubmission.Status.SUBMITTED
    unfinished.save(update_fields=["submitted_by", "status"])

    user_ids = list(kit.users.values_list("pk", flat=True))
    group_id = kit.group_id

    purge_kit(kit, reason=DemoKit.ClosedReason.REVOKED)

    assert not get_user_model().objects.filter(pk__in=user_ids).exists()
    assert not Group.objects.filter(pk=group_id).exists()
    kit.refresh_from_db()
    assert kit.closed_at is not None
    assert kit.status_key == "closed_revoked"
    assert kit.teacher_id is None and kit.group_id is None


@pytest.mark.django_db
def test_purge_tolerates_a_half_dismantled_kit():
    """A group deleted by hand must not make the kit un-closable for ever."""
    from demo.models import DemoKit
    from demo.services import purge_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    kit.group.delete()
    kit.refresh_from_db()

    purge_kit(kit, reason=DemoKit.ClosedReason.EXPIRED)
    kit.refresh_from_db()
    assert kit.closed_at is not None


@pytest.mark.django_db
def test_purge_expired_selects_only_expired_open_kits_and_is_idempotent():
    """T15. The idempotence case needs an ALREADY-CLOSED kit whose expires_at is
    past, or it passes because the second run found nothing."""
    from django.contrib.auth import get_user_model

    from demo.models import DemoKit
    from demo.services import purge_expired
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    live = provision_for_test(course, label="Live")
    expired = provision_for_test(course, label="Expired")
    DemoKit.objects.filter(pk=expired.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )

    # --dry-run IS A PREVIEW, and the runbook tells the operator to trust it on
    # prod. Prove it changes nothing: a build that ignores (or inverts) the flag
    # purges the kits here, and without these three assertions every test stays
    # green while the "safe preview" silently destroys a live demo.
    previewed = purge_expired(dry_run=True)
    assert [k.pk for k in previewed] == [expired.pk]
    expired.refresh_from_db()
    assert expired.closed_at is None, "--dry-run closed a kit"
    assert get_user_model().objects.filter(demo_kits=expired).exists(), (
        "--dry-run deleted the kit's users"
    )

    purged = purge_expired()
    assert [k.pk for k in purged] == [expired.pk]

    assert purge_expired() == []  # closed_at IS NULL keeps it idempotent
    live.refresh_from_db()
    assert live.closed_at is None


@pytest.mark.django_db
def test_one_failing_kit_does_not_strand_the_others(monkeypatch):
    """C4 — the runbook tells the operator "each kit has its own transaction, so
    the others still close and the run exits non-zero". Without the try/except in
    purge_expired that sentence is false: the first exception leaves every later
    kit's logins LIVE ON PROD, which is the exact failure the cron warning exists
    for."""
    from demo import services
    from demo.models import DemoKit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    first = provision_for_test(course, label="First")
    second = provision_for_test(course, label="Second")
    DemoKit.objects.filter(pk__in=[first.pk, second.pk]).update(
        expires_at=timezone.now() - timedelta(days=1)
    )

    real_purge = services.purge_kit

    def explode_on_first(kit, *, reason):
        if kit.pk == first.pk:
            raise RuntimeError("boom")
        return real_purge(kit, reason=reason)

    monkeypatch.setattr(services, "purge_kit", explode_on_first)

    with pytest.raises(errors.PurgeFailed) as exc:
        services.purge_expired()

    second.refresh_from_db()
    assert second.closed_at is not None, "the second kit was stranded"
    assert [k.pk for k in exc.value.purged] == [second.pk]
    first.refresh_from_db()
    assert first.closed_at is None


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_extend_moves_from_now_and_flags_a_long_lived_kit():
    """T15b. max(expires_at, now()) matters for a kit that expired yesterday.

    ⚠️ The override is REQUIRED and is not inherited: extend_kit calls
    require_vendor() as its first statement, config/settings/test.py:37 pins
    VENDOR_INSTANCE=False, and provision_for_test's own context manager has
    already exited by the time this test calls extend_kit. Without it the test
    errors on ImproperlyConfigured.
    """
    from demo.models import DemoKit
    from demo.services import extend_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    DemoKit.objects.filter(pk=kit.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )
    kit.refresh_from_db()

    result = extend_kit(kit, days=14)
    assert result.new_expires_at > timezone.now()
    assert result.long_lived is False

    DemoKit.objects.filter(pk=kit.pk).update(
        created_at=timezone.now() - timedelta(days=50)
    )
    kit.refresh_from_db()
    assert extend_kit(kit, days=30).long_lived is True


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_extend_and_revoke_refuse_a_closed_kit():
    """Same override, same reason — and without it the ImproperlyConfigured
    raised by the guard would fail the `pytest.raises(KitAlreadyClosed)` for a
    reason that has nothing to do with the rule under test."""
    from demo.models import DemoKit
    from demo.services import extend_kit
    from demo.services import purge_kit
    from demo.services import revoke_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    purge_kit(kit, reason=DemoKit.ClosedReason.REVOKED)
    kit.refresh_from_db()

    with pytest.raises(errors.KitAlreadyClosed):
        extend_kit(kit, days=7)
    with pytest.raises(errors.KitAlreadyClosed):
        revoke_kit(kit)


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_the_cleanup_half_is_exempt_from_the_vendor_guard():
    """R8: guarding a cleanup path is the one way the guard could leave
    stranger-known logins alive on prod."""
    from demo.services import purge_expired
    from demo.services import revoke_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())  # provisions with the flag ON
    revoke_kit(kit)  # must NOT raise with the flag off
    kit.refresh_from_db()
    assert kit.status_key == "closed_revoked"
    assert purge_expired() == []


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_extend_is_guarded_by_the_vendor_flag():
    """The OTHER half of R8, which nothing else covers. The exemption test above
    proves purge/revoke stay open; this proves extend does not — without it, a
    build that dropped require_vendor() from extend_kit is green everywhere."""
    from django.core.exceptions import ImproperlyConfigured

    from demo.services import extend_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course())
    with pytest.raises(ImproperlyConfigured) as exc:
        extend_kit(kit, days=7)
    assert "LIBLI_VENDOR_INSTANCE" in str(exc.value)
