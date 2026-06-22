"""Playwright e2e for the in-editor 'Choose media' picker — the REAL click flow.

Guards a regression class that earlier slipped: the picker's open handler set the
target <select>/preview, then openModal() called closeModal() which nulled them, so
every asset-pick was a silent no-op. The drag-to-image canvas e2e drove the picker
synthetically (setting data-media-url directly), so the real click path was untested.
These tests click "Choose media" and a library asset for real, asserting the <select>
gets the value — and, for drag-to-image, that the canvas stage then builds.

Marked e2e (excluded from the default run; run with `-m e2e`)."""

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
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _setup(page, live_server, username, slug, unit_type):
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import MediaAssetFactory

    _make_pa_user(username)
    User = get_user_model()
    owner = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="U"
    )
    asset = MediaAssetFactory(course=course, kind="image", file="courses/media/x.png")
    _login(page, live_server, username)
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"]')
    return asset


def _add_and_pick(page, add_type):
    page.locator("[data-add-toggle]").click()
    page.locator(f"[data-add-type='{add_type}']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    page.locator("[data-edit-slot] [data-pick-media]").click()
    page.wait_for_selector(".picker-overlay", timeout=5000)
    page.locator(".picker-overlay .asset-pick").first.click()
    page.wait_for_timeout(400)


@pytest.mark.django_db(transaction=True)
def test_image_element_picker_selects_asset(page, live_server):
    asset = _setup(page, live_server, "pick_img", "pick-img", "lesson")
    _add_and_pick(page, "image")
    sel = page.locator("[data-edit-slot] select[name='media']").input_value()
    assert sel == str(asset.pk), f"image media select not set by picker: {sel!r}"
    assert page.locator(".picker-overlay").count() == 0  # picker closed on select


@pytest.mark.django_db(transaction=True)
def test_dragimage_picker_selects_and_builds_canvas(page, live_server):
    asset = _setup(page, live_server, "pick_di", "pick-di", "quiz")
    _add_and_pick(page, "dragtoimagequestion")
    sel = page.locator("[data-edit-slot] select[name='media']").input_value()
    assert sel == str(asset.pk), f"drag-to-image media select not set: {sel!r}"
    # select -> change dispatch -> [data-media-preview] data-media-url -> the
    # MutationObserver builds the zone-drawing canvas, so the author can draw zones.
    page.wait_for_selector("[data-edit-slot] .zone-stage", timeout=5000)
