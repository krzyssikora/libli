import pytest

from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_external_id_defaults_blank_and_persists():
    u = UserFactory()
    c = CourseFactory()
    g = GroupFactory()
    assert u.external_id == "" and c.external_id == "" and g.external_id == ""
    u.external_id = "S-123"
    c.external_id = "MATH-A"
    g.external_id = "7B"
    u.save(update_fields=["external_id"])
    c.save(update_fields=["external_id"])
    g.save(update_fields=["external_id"])
    u.refresh_from_db()
    c.refresh_from_db()
    g.refresh_from_db()
    assert u.external_id == "S-123"
    assert c.external_id == "MATH-A"
    assert g.external_id == "7B"
