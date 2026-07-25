"""Playwright e2e: unit-level forms keep a FRESH token across element edits.

Regression guard. builder.save_element bumps unit.updated, and the save response
swaps [data-scope="editor"] / [data-scope="preview"], which re-renders every token
carrier INSIDE those panes. Two unit-level forms live OUTSIDE both panes in
editor.html and kept the token the page was first rendered with:

  * the Settings <details> form   (_unit_settings.html, name="token")
  * the Lesson/Quiz type toggle   (editor.html, name="token")

So after any element edit the author's next settings save / type switch hit
_check_token with a stale value, got "This changed elsewhere — reloaded to the
latest", and only succeeded on the retry after that reload. Both are asserted to
work on the FIRST attempt here.

Marked e2e (excluded from the default run; run with -m e2e). Harness mirrors
test_e2e_editor.py.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
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
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username, slug, title="Lesson One"):
    from django.contrib.auth import get_user_model

    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import add_element

    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title=title
    )
    add_element(unit, TextElement.objects.create(body="<p>First</p>"))
    return unit


def _editor_url(live_server, unit):
    return (
        f"{live_server.url}/manage/courses/{unit.course.slug}"
        f"/build/unit/{unit.pk}/edit/"
    )


def _edit_and_save_element(page):
    """Open the existing element's edit form and save it — the exact action that
    bumps unit.updated and swaps the panes."""
    page.locator("button.el-act-edit").first.click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type(" edited")
    page.locator("[data-edit-slot] button[type='submit']").click()
    # The swap is done when the edit form is gone.
    page.wait_for_selector(
        "[data-edit-slot] form[data-op='element-save']", state="detached"
    )


def _stale_token_carriers(page):
    """Every unit-level token input still holding a value older than the pane's."""
    return page.evaluate(
        """() => {
          const pane = document.querySelector('[data-scope="editor"]');
          const fresh = pane && pane.getAttribute('data-updated');
          const unit = pane && pane.getAttribute('data-unit');
          const out = [];
          document.querySelectorAll('form input[name="token"]').forEach((i) => {
            const node = i.form && i.form.querySelector('input[name="node"]');
            if (!node || node.value !== unit) return;
            if (i.value !== fresh) {
              out.push({
                form: i.form.className || '(no class)',
                got: i.value,
                want: fresh,
              });
            }
          });
          return out;
        }"""
    )


@pytest.mark.django_db(transaction=True)
def test_settings_title_saves_on_first_attempt_after_an_element_edit(page, live_server):
    """Edit an element, then rename via Settings — must save on the FIRST submit."""
    _make_pa_user("tok_set")
    _login(page, live_server, "tok_set")
    unit = _seed("tok_set", "tok-set")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _edit_and_save_element(page)

    # Precondition: without the fix this is exactly where the token goes stale.
    stale = _stale_token_carriers(page)

    page.locator("details.unit-settings > summary").click()
    title = page.locator("details.unit-settings input[name='title']")
    title.wait_for(state="visible")
    title.fill("Renamed On First Try")
    page.locator("details.unit-settings button[type='submit']").click()
    page.wait_for_selector(".editor-head__title")

    assert page.locator(".op-error").count() == 0, (
        "Got the 'changed elsewhere' conflict notice on the first settings save "
        f"after an element edit. Stale token carriers after the swap: {stale}"
    )
    assert page.locator(".editor-head__title").inner_text().strip() == (
        "Renamed On First Try"
    )
    unit.refresh_from_db()
    assert unit.title == "Renamed On First Try"


@pytest.mark.django_db(transaction=True)
def test_type_toggle_switches_on_first_attempt_after_an_element_edit(page, live_server):
    """Same stale-token carrier, second form: the Lesson/Quiz toggle."""
    _make_pa_user("tok_type")
    _login(page, live_server, "tok_type")
    unit = _seed("tok_type", "tok-type")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _edit_and_save_element(page)

    stale = _stale_token_carriers(page)

    page.locator(".type-toggle__btn[value='quiz']").click()
    page.wait_for_selector(".editor-head__title")

    assert page.locator(".op-error").count() == 0, (
        "Got the 'changed elsewhere' conflict notice on the first type switch "
        f"after an element edit. Stale token carriers after the swap: {stale}"
    )
    unit.refresh_from_db()
    assert unit.unit_type == "quiz"


@pytest.mark.django_db(transaction=True)
def test_no_unit_token_carrier_is_left_stale_by_a_swap(page, live_server):
    """Directly pin the invariant: after an element save, EVERY unit-level token
    input matches the freshly-rendered pane's data-updated."""
    _make_pa_user("tok_inv")
    _login(page, live_server, "tok_inv")
    unit = _seed("tok_inv", "tok-inv")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')

    # Precondition: the carriers exist at all, so a green run can't mean "found none".
    assert page.locator('form input[name="token"]').count() >= 2

    _edit_and_save_element(page)

    stale = _stale_token_carriers(page)
    assert stale == [], f"unit-level token carriers left stale after a swap: {stale}"
