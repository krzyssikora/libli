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


def test_title_alt_under_en_shows_pl_reference():
    s = Subject.objects.create(title_en="Mathematics", title_pl="Matematyka", slug="m")
    with translation.override("en"):
        assert s.title_alt == "Matematyka"


def test_title_alt_under_pl_shows_en_reference():
    s = Subject.objects.create(title_en="Mathematics", title_pl="Matematyka", slug="m")
    with translation.override("pl"):
        assert s.title_alt == "Mathematics"


def test_title_alt_empty_when_pl_blank_under_pl():
    # PL primary already falls back to EN, so there is no extra reference to show
    # (the empty value renders as "—", which signals "no Polish name yet").
    s = Subject.objects.create(title_en="Mathematics", title_pl="", slug="m")
    with translation.override("pl"):
        assert s.title_alt == ""


def test_title_alt_empty_when_pl_blank_under_en():
    s = Subject.objects.create(title_en="Mathematics", title_pl="", slug="m")
    with translation.override("en"):
        assert s.title_alt == ""
