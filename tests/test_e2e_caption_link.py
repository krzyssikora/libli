"""Playwright e2e: put a source link in an image caption and read it as a student.

Drives the REAL editor rather than the form, because the whole claim of this
feature is that the shared RTE machinery reaches the caption with no JavaScript
of its own -- `initRte` finding the textarea, `wireRte` finding the toolbar
through `closest(".el-editor--text")`, and the link dialog's callback writing
into the surface. A form-level test cannot see any of that: it would pass on a
build where the toolbar is inert and the surface never mounts.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

SOURCE_URL = "https://example.org/photo"


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


def _seed(owner, caption):
    """A published unit holding one image whose caption is plain words. The
    <img> src 404s (no bytes on disk) and that is fine -- every assertion here
    is about the <figcaption>, and a missing image still renders its figure."""
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import Element
    from courses.models import ImageElement
    from courses.models import MediaAsset

    course = Course.objects.create(title="Astro", slug="astro", owner=owner)
    part = ContentNode.objects.create(course=course, kind="part", title="Part A")
    chapter = ContentNode.objects.create(
        course=course, kind="chapter", parent=part, title="Ch"
    )
    unit = ContentNode.objects.create(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        title="Lesson",
        published=True,
    )
    media = MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/pillars.png",
        original_filename="pillars.png",
    )
    image = ImageElement.objects.create(media=media, alt="pillars", figcaption=caption)
    Element.objects.create(unit=unit, content_object=image)
    return course, unit, image


def _open_editor(page, live_server, course, unit):
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"]')


def _save_open_element(page):
    """Click Save and wait for the save itself, not for something already true.

    Waiting on `.element-list [data-element]` -- the idiom in
    test_e2e_link_dialog.py -- is a no-op here: that test ADDS an element, so the
    row appearing is a real state change, while this one EDITS a row that was on
    the page from the start. The wait returned instantly and the assertions read
    the database before the POST had landed, which reads exactly like a rejected
    save. Waiting on the response, then on the edit surface being torn down by
    the fragment swap, waits out the gap instead of sampling it."""
    with page.expect_response(
        lambda r: r.request.method == "POST" and "element" in r.url
    ) as got:
        page.click(
            '[data-edit-slot] form[data-op="element-save"] button[type="submit"]'
        )
    # A 422 is otherwise INVISIBLE: only the two [data-scope] panes swap, so a
    # rejected save leaves the page looking untouched.
    assert got.value.status == 200, got.value.status
    page.locator("[data-edit-slot] .rte-surface").wait_for(state="detached")


@pytest.mark.django_db(transaction=True)
def test_add_a_source_link_to_a_caption_and_read_it_as_a_student(page, live_server):
    from courses.models import Enrollment
    from courses.models import ImageElement

    owner = _make_pa_user("cap")
    course, unit, image = _seed(owner, "Photo: NASA")
    _login(page, live_server, "cap")
    _open_editor(page, live_server, course, unit)

    page.click(f".el-act-edit[data-element-id='{image.pk}']")
    surface = page.locator("[data-edit-slot] .rte-surface")
    # The surface EXISTING is the first real claim: it only appears because
    # initRte enhanced a [data-rte-source] textarea that used to be an <input>.
    surface.wait_for(state="visible")
    assert surface.inner_text().strip() == "Photo: NASA"

    surface.click()
    page.keyboard.press("Control+End")
    # Select the last word deterministically -- dblclick would land on whatever
    # word sits at the container's centre.
    page.keyboard.press("Control+Shift+ArrowLeft")
    assert page.evaluate("() => window.getSelection().toString()") == "NASA"

    # The toolbar being wired is the second claim: without the .el-editor--text
    # wrapper, wireRte never finds it and this click does nothing at all.
    page.locator("[data-edit-slot] [data-cmd='link']").click()
    dialog = page.locator(".link-dialog")
    dialog.wait_for(state="visible")
    dialog.locator("[data-tab='url']").click()
    dialog.locator("[data-link-url]").fill(SOURCE_URL)
    assert dialog.locator("[data-link-text]").input_value() == "NASA"
    dialog.locator("[data-link-insert]").click()
    dialog.wait_for(state="hidden")
    # Wait for the close HANDLER, not just the dialog: dialog.close() clears the
    # `open` attribute synchronously but only QUEUES the close event, and every
    # real effect runs in that queued task.
    page.wait_for_function(
        "() => !!document.querySelector('[data-edit-slot] .rte-surface a')"
    )

    _save_open_element(page)

    stored = ImageElement.objects.get(pk=image.pk).figcaption
    assert f'href="{SOURCE_URL}"' in stored, stored
    assert ">NASA</a>" in stored, stored
    # The un-linked half must survive: an insert that replaced the whole caption
    # would still satisfy both assertions above.
    assert stored.startswith("Photo: "), stored

    Enrollment.objects.create(student=owner, course=course)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    link = page.locator(f"figcaption a[href='{SOURCE_URL}']")
    link.wait_for()
    assert link.inner_text() == "NASA"
    # And the caption is an anchor on the page, not escaped characters of one.
    assert "&lt;a" not in page.locator("figcaption").inner_html()


@pytest.mark.django_db(transaction=True)
def test_a_caption_authored_as_two_lines_keeps_its_words_apart(page, live_server):
    """The surface emits one <div> per ENTER-separated line and `div` is outside
    CAPTION_TAGS, so this is the path where nh3's unwrap would silently store
    "onetwo". Driven through the real surface because a server-side test cannot
    prove the surface actually emits the markup the sanitiser is written for."""
    from courses.models import ImageElement

    owner = _make_pa_user("cap2")
    course, unit, image = _seed(owner, "")
    _login(page, live_server, "cap2")
    _open_editor(page, live_server, course, unit)

    page.click(f".el-act-edit[data-element-id='{image.pk}']")
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("Pierwsza")
    page.keyboard.press("Enter")
    page.keyboard.type("Druga")

    _save_open_element(page)

    stored = ImageElement.objects.get(pk=image.pk).figcaption
    assert "PierwszaDruga" not in stored, stored
    assert stored == "Pierwsza<br>Druga", stored
