import pytest
from django.utils import translation

from notifications.models import Notification

pytestmark = pytest.mark.django_db


def test_kind_labels_translated_to_polish():
    with translation.override("pl"):
        assert str(Notification.Kind.QUIZ_GRADED.label) == "Quiz oceniony"
        assert str(Notification.Kind.ENROLLED.label) == "Zapisano na kurs"
        assert (
            str(Notification.Kind.QUIZ_NEEDS_REVIEW.label) == "Quiz wymaga sprawdzenia"
        )
