import pytest

from courses.forms import SubjectForm
from courses.models import Subject

pytestmark = pytest.mark.django_db


def test_create_derives_slug_from_title_en():
    form = SubjectForm(
        data={"title_en": "Pure Mathematics", "title_pl": "", "slug": ""}
    )
    assert form.is_valid(), form.errors
    subject = form.save()
    assert subject.slug == "pure-mathematics"


def test_derived_slug_collision_gets_suffix():
    Subject.objects.create(title_en="Math", slug="math")
    form = SubjectForm(data={"title_en": "Math", "title_pl": "", "slug": ""})
    assert form.is_valid(), form.errors
    assert form.save().slug == "math-2"


def test_edit_blank_slug_retains_existing():
    subject = Subject.objects.create(title_en="Math", slug="math")
    form = SubjectForm(
        data={"title_en": "Mathematics", "title_pl": "", "slug": ""}, instance=subject
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.slug == "math"  # NOT re-derived to "mathematics"
    assert saved.title_en == "Mathematics"


def test_edit_with_new_explicit_slug_is_accepted():
    subject = Subject.objects.create(title_en="Math", slug="math")
    form = SubjectForm(
        data={"title_en": "Math", "title_pl": "", "slug": "pure-math"}, instance=subject
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.slug == "pure-math"


def test_explicit_duplicate_slug_is_a_field_error():
    Subject.objects.create(title_en="Math", slug="math")
    form = SubjectForm(data={"title_en": "Other", "title_pl": "", "slug": "math"})
    assert not form.is_valid()
    assert "slug" in form.errors


def test_title_pl_optional():
    form = SubjectForm(data={"title_en": "Science", "title_pl": "", "slug": "sci"})
    assert form.is_valid(), form.errors
