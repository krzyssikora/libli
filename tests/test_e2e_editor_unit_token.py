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


def _add_second_element(unit):
    """A second element, so delete and reorder have something to act on."""
    from courses.models import TextElement
    from tests.factories import add_element

    return add_element(unit, TextElement.objects.create(body="<p>Second</p>"))


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


def _rename_via_settings(page, title):
    """Open the Settings <details> and save a new title — the reported flow."""
    page.locator("details.unit-settings > summary").click()
    box = page.locator("details.unit-settings input[name='title']")
    box.wait_for(state="visible")
    box.fill(title)
    page.locator("details.unit-settings button[type='submit']").click()
    page.wait_for_selector(".editor-head__title")


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
    _rename_via_settings(page, "Renamed On First Try")

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


# ── Every OTHER op that bumps unit.updated ───────────────────────────────────
# save_element is not the only one: reorder_element and delete_element both end
# in unit.save(update_fields=["updated"]) (courses/builder.py), and an add runs a
# save under the hood. All of them swap the panes, so all of them must leave the
# unit-level token carriers fresh. The original guard only covered the edit path,
# which left the others resting on the assumption that one funnel serves them all
# — these pin it instead.


@pytest.mark.django_db(transaction=True)
def test_settings_saves_first_try_after_adding_an_element(page, live_server):
    """Adding an element is the commonest authoring action, not editing one."""
    _make_pa_user("tok_add")
    _login(page, live_server, "tok_add")
    unit = _seed("tok_add", "tok-add")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')

    page.locator("[data-add-toggle]").first.click()
    page.locator("[data-add-type='text']").first.click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("added")
    page.locator("[data-edit-slot] button[type='submit']").click()
    page.wait_for_selector(
        "[data-edit-slot] form[data-op='element-save']", state="detached"
    )

    stale = _stale_token_carriers(page)
    _rename_via_settings(page, "Renamed After Add")

    assert page.locator(".op-error").count() == 0, (
        f"conflict notice on the first settings save after an ADD; stale={stale}"
    )
    unit.refresh_from_db()
    assert unit.title == "Renamed After Add"


@pytest.mark.django_db(transaction=True)
def test_settings_saves_first_try_after_deleting_an_element(page, live_server):
    _make_pa_user("tok_del")
    _login(page, live_server, "tok_del")
    unit = _seed("tok_del", "tok-del")
    _add_second_element(unit)

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.once("dialog", lambda d: d.accept())
    page.locator("form[data-op='element-delete'] button").first.click()
    page.wait_for_function(
        "() => document.querySelectorAll('.el-row[data-element]').length === 1"
    )

    stale = _stale_token_carriers(page)
    _rename_via_settings(page, "Renamed After Delete")

    assert page.locator(".op-error").count() == 0, (
        f"conflict notice on the first settings save after a DELETE; stale={stale}"
    )
    unit.refresh_from_db()
    assert unit.title == "Renamed After Delete"


@pytest.mark.django_db(transaction=True)
def test_settings_saves_first_try_after_reordering_elements(page, live_server):
    _make_pa_user("tok_ord")
    _login(page, live_server, "tok_ord")
    unit = _seed("tok_ord", "tok-ord")
    _add_second_element(unit)

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    first_before = page.locator(".el-row[data-element]").first.get_attribute(
        "data-element"
    )
    # Move the FIRST row DOWN, not up. "Up" on the first row is a boundary no-op,
    # which builder.reorder_node returns without saving — so it never bumps the
    # token and the test would pass without exercising anything.
    page.locator("form[data-op='element-move'] button[value='down']").first.click()
    # Applied once the first row is a different element.
    page.wait_for_function(
        "(before) => {"
        " const r = document.querySelector('.el-row[data-element]');"
        " return r && r.getAttribute('data-element') !== before; }",
        arg=first_before,
    )

    stale = _stale_token_carriers(page)
    _rename_via_settings(page, "Renamed After Reorder")

    assert page.locator(".op-error").count() == 0, (
        f"conflict notice on the first settings save after a REORDER; stale={stale}"
    )
    unit.refresh_from_db()
    assert unit.title == "Renamed After Reorder"
