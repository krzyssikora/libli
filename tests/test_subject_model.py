import pytest
from django.utils import translation

from courses.models import Subject

pytestmark = pytest.mark.django_db


def test_title_returns_en_under_en_locale():
    s = Subject.objects.create(title_en="Mathematics", title_pl="Matematyka", slug="m")
    with translation.override("en"):
        assert s.title == "Mathematics"


def test_title_returns_pl_under_pl_locale():
    s = Subject.objects.create(title_en="Mathematics", title_pl="Matematyka", slug="m")
    with translation.override("pl"):
        assert s.title == "Matematyka"


def test_title_falls_back_to_en_when_pl_blank():
    s = Subject.objects.create(title_en="Mathematics", title_pl="", slug="m")
    with translation.override("pl"):
        assert s.title == "Mathematics"


def test_str_uses_title_property():
    s = Subject.objects.create(title_en="Science", slug="sci")
    assert str(s) == "Science"


def test_default_ordering_is_title_en():
    Subject.objects.create(title_en="Zoology", slug="z")
    Subject.objects.create(title_en="Algebra", slug="a")
    assert [s.title_en for s in Subject.objects.all()] == ["Algebra", "Zoology"]
