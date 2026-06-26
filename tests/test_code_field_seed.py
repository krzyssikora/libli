import pytest

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_unit_settings_wraps_seed_js_in_code_field(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U1"
    )
    # The editor page renders _unit_settings.html for the unit.
    url = f"/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    resp = client.get(url)
    assert (
        resp.status_code == 200
    )  # clear failure if auth/URL is wrong, not a substring miss
    body = resp.content.decode()
    assert 'name="html_seed_js"' in body
    # The seed textarea is now inside the code-field shell with the JS hook.
    assert "data-code-field" in body
    assert "code-field__gutter" in body
    assert 'class="code"' not in body  # the old bare-textarea class is gone
