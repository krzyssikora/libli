import pytest
from django.core.exceptions import ValidationError

from institution.models import MAX_RETENTION_DAYS
from institution.models import Institution

pytestmark = pytest.mark.django_db


def test_retention_field_default_is_90():
    assert Institution.load().notification_retention_days == 90


def test_retention_field_rejects_over_ceiling():
    inst = Institution.load()
    inst.notification_retention_days = MAX_RETENTION_DAYS + 1
    with pytest.raises(ValidationError):
        inst.full_clean()


def test_retention_field_accepts_zero_and_ceiling():
    inst = Institution.load()
    for v in (0, MAX_RETENTION_DAYS):
        inst.notification_retention_days = v
        inst.full_clean()  # no raise
