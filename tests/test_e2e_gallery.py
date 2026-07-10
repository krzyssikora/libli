"""Playwright e2e for the gallery/carousel content element's editor half
(plan Task 7): add via the real add-menu gesture, pick two images through the
media-picker "append mode", type a description, reorder, and Save. Drives the
REAL UI gestures throughout (clicks, keyboard typing) — no page.evaluate
shortcuts. Modeled on tests/test_e2e_table_editor.py and
tests/test_e2e_media_picker.py. Marked e2e (excluded from the default run)."""

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


def _setup(page, live_server, username, slug):
    """Course + lesson unit + two course-scoped image assets, logged in as a
    Platform Admin, sitting on the editor page for the unit."""
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import MediaAssetFactory

    _make_pa_user(username)
    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    asset_a = MediaAssetFactory(course=course, kind="image", file="courses/media/a.png")
    asset_b = MediaAssetFactory(course=course, kind="image", file="courses/media/b.png")
    _login(page, live_server, username)
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"]')
    return unit, asset_a, asset_b


def _add_gallery(page):
    """Add a gallery element via the real add-menu gesture. Leaves the freshly
    added gallery's edit form open ([data-edit-slot])."""
    page.locator("[data-add-toggle]").click()
    page.locator("[data-add-type='gallery']").click()
    page.wait_for_selector("[data-edit-slot] [data-gallery-editor]")


def _add_image_via_picker(page, asset_pk):
    """Click 'Add image' (append-mode picker) and pick the given asset by id
    (both fixture assets remain in the grid across picks — the picker does not
    filter out already-added images — so pick by id, not position)."""
    page.locator("[data-edit-slot] [data-gallery-add]").click()
    page.wait_for_selector(".picker-overlay", timeout=5000)
    page.locator(f".picker-overlay .asset-pick[data-asset-id='{asset_pk}']").click()
    page.wait_for_timeout(300)


@pytest.mark.django_db(transaction=True)
def test_gallery_editor_add_reorder_save(page, live_server):
    """Drive the REAL editor UI: add two images, type a description into the
    first row, reorder, and Save; assert the gallery persists with two
    images in the reordered order."""
    from courses.models import Element
    from courses.models import GalleryElement

    unit, asset_a, asset_b = _setup(page, live_server, "gal_rt", "gal-rt")

    _add_gallery(page)

    _add_image_via_picker(page, asset_a.pk)
    _add_image_via_picker(page, asset_b.pk)

    rows = page.locator("[data-edit-slot] [data-gallery-row]")
    assert rows.count() == 2

    first_desc = rows.first.locator("[data-gallery-desc]")
    first_desc.click()
    first_desc.type("area ")

    # Reorder: move the second row up so it becomes first.
    rows.nth(1).locator("[data-gallery-up]").click()

    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-gallery-editor]", state="detached")

    element = Element.objects.get(unit=unit)
    gallery = GalleryElement.objects.get(pk=element.object_id)
    images = gallery.normalized_data["images"]
    assert len(images) == 2
    # Order reflects the reorder: asset_b (moved up) is now first, asset_a
    # (with the typed description) is now second.
    assert images[0]["media"] == asset_b.pk
    assert images[1]["media"] == asset_a.pk
    assert "area" in images[1]["desc"]
