"""PR 3 spec §5: the one e2e — issue a kit through the tab, use its Teacher login,
revoke it through the confirm dialog. Marked e2e (run with -m e2e)."""

import os

import pytest
from django.urls import reverse
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

REVOKE_PROMPT = "Revoke this demo kit? Its logins are deleted immediately."


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username, password):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(password)
    form.locator("button[type='submit']").click()
    page.wait_for_url(lambda url: "/accounts/login/" not in url)


@pytest.mark.django_db(transaction=True)
def test_issue_use_and_revoke_a_demo_kit(
    page, browser, live_server, settings, monkeypatch
):
    from django.contrib.auth.models import Group

    from demo.constants import MIN_PUPILS
    from demo.models import DemoKit
    from institution import views_manage
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles
    from tests.demo.fixtures import small_course
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_verified_user

    settings.VENDOR_INSTANCE = True
    seed_roles()
    admin = make_verified_user(
        username="demo_pa", email="demo_pa@t.example.com", password=TEST_PASSWORD
    )
    admin.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    course = small_course()
    real = views_manage.provision_kit
    monkeypatch.setattr(
        views_manage, "provision_kit", lambda *a, **kw: real(*a, seed=4242, **kw)
    )
    demo_tab = f"{live_server.url}{reverse('institution:settings')}?tab=demo"

    _login(page, live_server, "demo_pa", TEST_PASSWORD)
    page.goto(demo_tab)
    page.select_option("#id_course", str(course.pk))
    page.fill("#id_label", "SP 12")
    page.fill("#id_pupils", str(MIN_PUPILS))
    page.locator("[data-demo-submit]").click()

    card = page.locator("[data-demo-card]")
    expect(card).to_be_visible(timeout=120_000)
    username = card.locator("[data-demo-teacher-username]").inner_text()
    password = card.locator("[data-demo-teacher-password]").inner_text()
    kit = DemoKit.objects.get()

    teacher_context = browser.new_context()
    try:
        teacher_page = teacher_context.new_page()
        _login(teacher_page, live_server, username, password)
        analytics = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
        landed = teacher_page.goto(f"{live_server.url}{analytics}")
        # goto returns the LAST response of a redirect chain, and a bounce to the
        # login page is a 200 too — so assert WHERE the page ended up as well.
        assert landed.status == 200
        assert teacher_page.url == f"{live_server.url}{analytics}"
    finally:
        teacher_context.close()

    prompts = []

    def accept(dialog):
        prompts.append(dialog.message)
        dialog.accept()

    page.on("dialog", accept)
    page.goto(demo_tab)
    row = page.locator(f'tr[data-demo-kit="{kit.pk}"]')
    row.locator("form[data-demo-revoke] button").click()
    expect(row).to_have_count(0)
    # Without the recording, a Revoke that never prompts still removes the row.
    assert prompts == [REVOKE_PROMPT]
