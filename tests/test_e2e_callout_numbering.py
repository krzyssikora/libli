"""R2: saving a callout without touching the checkbox must not un-number it.

An unchecked checkbox transmits NOTHING, so a POST missing the key is
indistinguishable from a deliberate untick -- the same failure shape as the
existing `el_title` trap, where a POST missing that key blanks the element title.

THE INSTRUMENT IS THE RE-OPENED FORM'S CHECKBOX STATE, not the number visible in
the preview: a visible-number assertion also goes red for a missing context site
and for a dropped barrier key, so its failure would not identify R2.

Marked e2e (excluded from the default run; run with `-m e2e`). Fixture/login/
interaction idiom copied from tests/test_e2e_editor.py.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    # Mirror the proven helper in test_e2e_editor/test_e2e_smoke (allauth's login
    # field is name="login"); scope to the login form so the shell header's submit
    # buttons (language switch, Log out) aren't clicked instead.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _editor_url(live_server, unit):
    return (
        f"{live_server.url}/manage/courses/{unit.course.slug}"
        f"/build/unit/{unit.pk}/edit/"
    )


@pytest.mark.django_db(transaction=True)
def test_saving_a_callout_without_touching_the_checkbox_keeps_it_numbered(
    page, live_server
):
    from courses.models import CalloutElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import add_element

    # 1. Seed a lesson unit with one numbered callout and open the editor.
    owner = _make_pa_user("ed_num")
    course = CourseFactory(slug="ed-num", owner=owner)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Numbering Round Trip",
    )
    callout = CalloutElement.objects.create(
        kind="example", numbered=True, heading="Original heading", body="<p>x</p>"
    )
    join = add_element(unit, callout)

    _login(page, live_server, "ed_num")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')

    row = page.locator(f'.el-row[data-element="{join.pk}"]')

    # 2. Click the callout row's edit button; wait for the form.
    row.locator(".el-act-edit").click()
    form = row.locator('[data-edit-slot] form[data-op="element-save"]')
    form.wait_for(state="visible")

    # 3. Assert the checkbox is checked.
    checkbox = form.locator('input[type="checkbox"][name="numbered"]')
    assert checkbox.is_checked(), "callout must start numbered"

    # 4. Change ONLY the heading input; do not touch the checkbox.
    heading_input = form.locator('input[name="heading"]')
    heading_input.fill("Updated heading")

    # 5. Save; wait for the fragment swap to settle.
    form.locator('button[type="submit"]').click()
    # The saved element's heading now shows in the swapped-in preview.
    preview = page.locator('[data-scope="preview"]')
    preview.get_by_text("Updated heading").wait_for()

    # 6. Re-open the same callout's form.
    row = page.locator(f'.el-row[data-element="{join.pk}"]')
    row.locator(".el-act-edit").click()
    form = row.locator('[data-edit-slot] form[data-op="element-save"]')
    form.wait_for(state="visible")

    # 7. Assert the checkbox is STILL checked.
    checkbox = form.locator('input[type="checkbox"][name="numbered"]')
    assert checkbox.is_checked(), (
        "saving without touching the checkbox must not un-number the callout"
    )

    # 8. Additionally re-read the row: CalloutElement.objects.get(...).numbered is True.
    assert CalloutElement.objects.get(pk=callout.pk).numbered is True
