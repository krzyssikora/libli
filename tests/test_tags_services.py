import pytest
from django.core.exceptions import ValidationError

from tags import services
from tags.models import TAG_NAME_MAX_LEN

pytestmark = pytest.mark.django_db


def test_normalize_name_collapses_whitespace():
    assert services.normalize_name("  to   do \n") == "to do"


def test_clean_name_rejects_empty():
    with pytest.raises(ValidationError):
        services._clean_name("   ")


def test_clean_name_rejects_over_length():
    with pytest.raises(ValidationError):
        services._clean_name("x" * (TAG_NAME_MAX_LEN + 1))
