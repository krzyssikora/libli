import pytest

from accounts.forms import UserEditForm
from courses.forms import CourseForm
from grouping.forms import GroupForm
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_course_form_saves_external_id():
    c = CourseFactory()  # sets neither subjects nor owner
    # Deliberately minimal bound data: CourseFactory seeds no subjects/owner, so
    # omitting them here doesn't clear anything. If the factory later seeds them,
    # add them to `data` to avoid silently clearing the M2M / owner FK on save.
    form = CourseForm(
        data={
            "title": c.title,
            "slug": c.slug,
            "language": c.language,
            "overview": "",
            "visibility": c.visibility,
            "structure": "flat",
            "external_id": "MATH-A",
            "html_css": "",
            "html_js": "",
        },
        instance=c,
    )
    assert form.is_valid(), form.errors
    form.save()
    c.refresh_from_db()
    assert c.external_id == "MATH-A"


def test_group_form_saves_external_id():
    g = GroupFactory()
    form = GroupForm(data={"name": g.name, "external_id": "7B"}, instance=g)
    assert form.is_valid(), form.errors
    form.save()
    g.refresh_from_db()
    assert g.external_id == "7B"


def test_user_edit_form_saves_external_id():
    u = UserFactory()
    form = UserEditForm(
        data={"display_name": u.display_name, "external_id": "S-9"},
        instance=u,
        editing_self=True,
    )
    assert form.is_valid(), form.errors
    form.save()
    u.refresh_from_db()
    assert u.external_id == "S-9"
