import os
import pytest
from tests.factories import TEST_PASSWORD, make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _pa(username):
    from django.contrib.auth.models import Group
    from institution.roles import PLATFORM_ADMIN, seed_roles
    seed_roles()
    u = make_verified_user(username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD)
    u.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return u


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    f = page.locator("form[action*='login']")
    f.locator("input[name='login']").fill(username)
    f.locator("input[name='password']").fill(TEST_PASSWORD)
    f.locator("button[type='submit']").click()


def _unit(username, slug):
    from django.contrib.auth import get_user_model
    from tests.factories import ContentNodeFactory, CourseFactory
    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    return ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None, title="U")


def _editor_url(live_server, unit):
    return f"{live_server.url}/manage/courses/{unit.course.slug}/build/unit/{unit.pk}/edit/"


@pytest.mark.django_db(transaction=True)
def test_rte_math_button_inserts_into_stem(browser, live_server):
    _pa("m_rte")
    unit = _unit("m_rte", "m-rte")
    ctx = browser.new_context(); page = ctx.new_page()
    _login(page, live_server, "m_rte")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    # add a single-choice question
    page.locator("[data-add-toggle]").click()
    page.locator("[data-add-type='choice-single']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    # open math widget from the RTE toolbar, type LaTeX into the math-field, insert
    page.locator("[data-edit-slot] [data-cmd='math']").first.click()
    page.wait_for_selector(".math-modal:not([hidden]) math-field")
    page.locator(".math-modal math-field").type("x^2")
    page.locator(".math-modal [data-math-insert]").click()
    # the hidden stem textarea now contains the delimited LaTeX
    val = page.locator("[data-edit-slot] textarea[name='stem']").input_value()
    assert "\\(" in val and "x^2" in val and "\\)" in val
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_choice_field_math_button_and_preview(browser, live_server):
    _pa("m_ch")
    unit = _unit("m_ch", "m-ch")
    ctx = browser.new_context(); page = ctx.new_page()
    _login(page, live_server, "m_ch")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator("[data-add-toggle]").click()
    page.locator("[data-add-type='choice-single']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    # focus the first choice input, open its math widget, insert
    row = page.locator("[data-edit-slot] [data-choice-row]").first
    row.locator("input[name='choices-0-text']").click()
    row.locator("[data-math-trigger]").click()
    page.wait_for_selector(".math-modal:not([hidden]) math-field")
    page.locator(".math-modal math-field").type("\\frac{1}{2}")
    page.locator(".math-modal [data-math-insert]").click()
    assert "\\(" in row.locator("input[name='choices-0-text']").input_value()
    # live preview renders KaTeX for the inserted math
    page.wait_for_function(
        "() => document.querySelectorAll('[data-edit-slot] [data-math-preview] .katex').length > 0",
        timeout=6000,
    )
    ctx.close()
