"""Playwright e2e for WS3: inline add/edit, element drag-drop, embed paste, media
rename, picker kind-lock, toolbar active-state. Marked e2e (run with -m e2e).

Mirrors the proven helpers in test_e2e_editor.py / test_e2e_builder_ws2.py: the
session-scoped DJANGO_ALLOW_ASYNC_UNSAFE fixture, the PLATFORM_ADMIN seed, the
allauth login (name="login"), and the editor URL (courses:manage_editor:
/manage/courses/<slug>/build/unit/<pk>/edit/). The native-HTML5-DnD reorder uses
the dispatchEvent simulation helper (Playwright's drag_to fires pointer events,
not the dragstart/dragover/drop that editor_dnd.js listens for)."""

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


def _seed_unit(pa, slug="ws3"):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


def _open_add(page, add_type):
    """Open the add-menu, click a type card, and wait for the per-type editor partial
    to mount inside the appended new-row's [data-edit-slot]."""
    page.locator("[data-add-toggle]").click()
    page.locator(f"[data-add-type='{add_type}']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")


def _simulate_drag(page, src_selector, dst_selector):
    """Dispatch native HTML5 DnD events programmatically.

    Playwright's drag_to uses pointer events internally and does NOT fire the
    dragstart/dragover/drop that editor_dnd.js listens for. dispatchEvent-based
    simulation is the standard workaround for HTML5 DnD under Playwright. The
    clientY values are real bounding-box midpoints so editor_dnd's drop-line
    positioning (which compares e.clientY to each row midpoint) computes a
    correct insert position."""
    page.evaluate(
        """([srcSel, dstSel]) => {
            const src = document.querySelector(srcSel);
            const dst = document.querySelector(dstSel);
            if (!src || !dst)
                throw new Error('selector not found: ' + srcSel + ' | ' + dstSel);
            const dt = new DataTransfer();
            const srcRect = src.getBoundingClientRect();
            const dstRect = dst.getBoundingClientRect();
            src.dispatchEvent(new DragEvent('dragstart', {
                bubbles: true, cancelable: true, dataTransfer: dt,
                clientX: srcRect.x + srcRect.width / 2,
                clientY: srcRect.y + srcRect.height / 2,
            }));
            dst.dispatchEvent(new DragEvent('dragover', {
                bubbles: true, cancelable: true, dataTransfer: dt,
                clientX: dstRect.x + dstRect.width / 2,
                clientY: dstRect.y + dstRect.height / 2,
            }));
            dst.dispatchEvent(new DragEvent('drop', {
                bubbles: true, cancelable: true, dataTransfer: dt,
                clientX: dstRect.x + dstRect.width / 2,
                clientY: dstRect.y + dstRect.height / 2,
            }));
            src.dispatchEvent(new DragEvent('dragend', {
                bubbles: true, cancelable: true, dataTransfer: dt,
            }));
        }""",
        [src_selector, dst_selector],
    )


@pytest.mark.django_db(transaction=True)
def test_inline_add_text_persists(page, live_server):
    """+ Text -> type into the RTE source -> Save -> the element persists and the
    body text shows in the preview."""
    from courses.models import Element
    from courses.models import TextElement

    pa = _make_pa_user("ws3a")
    course, unit = _seed_unit(pa, "ws3a")
    _login(page, live_server, "ws3a")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    _open_add(page, "text")
    # text_toolbar.js mounts a contenteditable .rte-surface and hides the textarea;
    # typing into the surface syncs back to textarea[name=body] on input.
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("Hello world")

    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()
    # Wait for the save round-trip: the swapped-in preview must show the body text
    # (not the editor's own RTE surface, which already holds it pre-save).
    preview = page.locator('[data-scope="preview"]')
    preview.get_by_text("Hello world").wait_for()

    assert Element.objects.filter(unit=unit).count() == 1
    assert TextElement.objects.filter(body__icontains="Hello world").count() == 1


@pytest.mark.django_db(transaction=True)
def test_element_dnd_reorder(page, live_server):
    """Dragging the first row's grip onto the third row reorders via editor_dnd.js;
    the first element is no longer at order 0 in the DB."""
    from courses.models import Element
    from courses.models import TextElement

    pa = _make_pa_user("ws3d")
    course, unit = _seed_unit(pa, "ws3d")
    els = [
        Element.objects.create(
            unit=unit, content_object=TextElement.objects.create(body=f"<p>E{i}</p>")
        )
        for i in range(3)
    ]
    _login(page, live_server, "ws3d")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector(".el-row")

    _simulate_drag(
        page,
        f'.el-row[data-element="{els[0].pk}"] .ica--grip',
        f'.el-row[data-element="{els[2].pk}"]',
    )
    # Wait for the DB to reflect the reorder (the POST + fragment swap is async).
    page.wait_for_function(
        """([unitPk, firstPk]) => {
            const rows = Array.from(
                document.querySelectorAll('[data-scope=\"editor\"] .el-row'));
            return rows.length === 3
                && rows[0].getAttribute('data-element') !== String(firstPk);
        }""",
        arg=[unit.pk, els[0].pk],
        timeout=5000,
    )
    order = list(
        Element.objects.filter(unit=unit).order_by("order").values_list("pk", flat=True)
    )
    assert order[0] != els[0].pk


@pytest.mark.django_db(transaction=True)
def test_embed_paste_reject_stores_nothing(page, live_server):
    """Pasting a non-whitelisted <iframe> embed renders a .field-error and stores
    no IframeElement."""
    from courses.models import IframeElement

    pa = _make_pa_user("ws3e")
    course, unit = _seed_unit(pa, "ws3e")
    _login(page, live_server, "ws3e")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    _open_add(page, "iframe")
    page.locator("[data-edit-slot] [data-embed-input]").fill(
        '<iframe src="https://evil.example.com/x"></iframe>'
    )
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()
    page.wait_for_selector(".field-error")

    assert IframeElement.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_picker_kind_locked_to_image(page, live_server):
    """The image editor's media picker is server-side kind-locked: only image assets
    appear (the video asset is excluded)."""
    from courses.models import MediaAsset

    pa = _make_pa_user("ws3p")
    course, unit = _seed_unit(pa, "ws3p")
    MediaAsset.objects.create(
        course=course, kind="image", file="i.png", original_filename="pic.png"
    )
    MediaAsset.objects.create(
        course=course, kind="video", file="v.mp4", original_filename="clip.mp4"
    )
    _login(page, live_server, "ws3p")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    _open_add(page, "image")
    page.wait_for_selector("[data-edit-slot] [data-pick-media]")
    page.locator("[data-edit-slot] [data-pick-media]").click()
    page.wait_for_selector(".picker")

    assert page.locator(".asset-pick", has_text="pic.png").count() == 1
    assert page.locator(".asset-pick", has_text="clip.mp4").count() == 0
