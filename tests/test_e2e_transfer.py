"""Playwright e2e for the course export/import feature (course-export-import spec):
a full-course round trip (export via the builder's Export button, re-import via the
Import course upload -> preview -> confirm flow) and a subtree transfer via the
insertion picker (export a chapter subtree from course A, import it into course B
under an existing part). Mirrors tests/test_e2e_builder.py's fixtures/patterns.
Marked e2e (excluded from the default run). REAL gestures only — no page.evaluate
shortcuts; file upload uses set_input_files on the actual <input type=file>, the
insertion choice uses select_option on the actual <select>, downloads are captured
via page.expect_download() around the real Export click."""

import os

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# Task 12's view tests stage real zips through courses.transfer.staging — without
# redirecting TRANSFER_STAGING_DIR, that would write into BASE_DIR/transfer_staging/
# during this e2e run (test_transfer_views.py uses the same guard).
@pytest.fixture(autouse=True)
def _staging_tmp(settings, tmp_path):
    settings.TRANSFER_STAGING_DIR = tmp_path / "staging"


def _login(page, live_server, username):
    # Selectors mirror the proven helper in tests/test_e2e_builder.py (allauth's
    # login field is name="login").
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _add_course_perm(user):
    user.user_permissions.add(
        Permission.objects.get(codename="add_course", content_type__app_label="courses")
    )


@pytest.mark.django_db(transaction=True)
def test_full_course_export_import_round_trip(page, live_server, tmp_path):
    """Export a small course from the builder, then re-import it from the manage
    list; the imported copy lands under a suffixed slug and shows up in the list."""
    from courses.models import Course
    from tests.factories import ContentNodeFactory
    from tests.factories import ElementFactory

    owner = make_verified_user(
        username="owner1", email="owner1@t.example.com", password=TEST_PASSWORD
    )
    _add_course_perm(owner)  # import_course_view requires courses.add_course
    # slug matches slugify(title): import_course derives the new slug from the
    # TITLE via unique_course_slug, so the re-import only collides (and gets the
    # "-2" suffix) if the source course's own slug is that same base.
    course = Course.objects.create(title="Algebra I", slug="algebra-i", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Lesson One"
    )
    ElementFactory(unit=unit)  # a text element in the unit

    _login(page, live_server, "owner1")

    # --- Export via the real button on the builder page --------------------
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    with page.expect_download() as download_info:
        page.locator("a", has_text="Export").click()
    download = download_info.value
    archive_path = tmp_path / "algebra-i-export.zip"
    download.save_as(archive_path)

    # --- Import course via the real upload -> preview -> confirm flow ------
    page.goto(f"{live_server.url}/manage/courses/")
    page.locator("a", has_text="Import course").click()
    page.wait_for_selector("input#id_archive", state="attached")
    page.locator("input#id_archive").set_input_files(str(archive_path))
    page.locator("form.form button[type='submit']").click()

    page.wait_for_selector(f"text={course.title}")
    page.locator("button", has_text="Confirm import").click()

    # Confirm redirects into the new course's builder — wait for the tree to render.
    page.wait_for_selector('[data-scope="top"]', state="attached")

    new_course = Course.objects.exclude(pk=course.pk).get(title=course.title)
    assert new_course.slug == f"{course.slug}-2"
    assert page.url == f"{live_server.url}/manage/courses/{new_course.slug}/build/"
    assert new_course.nodes.filter(title="Lesson One").exists()

    # --- The imported course now appears in the manage list ----------------
    page.goto(f"{live_server.url}/manage/courses/")
    export_href = reverse("courses:manage_course_export", args=[new_course.slug])
    assert page.locator(f'a[href="{export_href}"]').count() == 1


@pytest.mark.django_db(transaction=True)
def test_subtree_import_via_insertion_picker(page, live_server, tmp_path):
    """Export a chapter subtree from course A via the per-node action, then import
    it into course B under an existing part using the real insertion <select>."""
    from courses.models import ContentNode
    from courses.models import Course
    from tests.factories import ContentNodeFactory

    owner = make_verified_user(
        username="owner2", email="owner2@t.example.com", password=TEST_PASSWORD
    )
    course_a = Course.objects.create(
        title="Course A",
        slug="course-a-e2e",
        owner=owner,
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    # ContentNodeFactory's default unit_type="lesson" is only valid for kind="unit"
    # (a non-unit node with a unit_type fails model validation on export/save — "Only
    # units may have a unit_type"), so non-unit nodes are created directly.
    chapter = ContentNode.objects.create(
        course=course_a, kind="chapter", parent=None, title="Root Chapter"
    )
    ContentNodeFactory(
        course=course_a,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        title="Leaf Unit",
    )
    # Full depth (model defaults: uses_parts/chapters/sections all True).
    course_b = Course.objects.create(title="Course B", slug="course-b-e2e", owner=owner)
    part = ContentNode.objects.create(
        course=course_b, kind="part", parent=None, title="Part One"
    )

    _login(page, live_server, "owner2")

    # --- Export the chapter subtree via the real per-node action -----------
    page.goto(f"{live_server.url}/manage/courses/{course_a.slug}/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    # The chapter's child unit is nested INSIDE the same <li> (via its own scope
    # <ol>), so a bare descendant selector would also match the unit's export
    # link. Scope to the row's own .tree__rowhead (a direct child of the <li>)
    # to get only the chapter's own action.
    row = page.locator(f'li[data-node="{chapter.pk}"]')
    with page.expect_download() as download_info:
        row.locator(':scope > .tree__rowhead a[aria-label="Export subtree"]').click()
    download = download_info.value
    archive_path = tmp_path / "chapter-export.zip"
    download.save_as(archive_path)

    # --- Import into course B via "Import content" + the insertion picker --
    page.goto(f"{live_server.url}/manage/courses/{course_b.slug}/build/")
    page.locator("a", has_text="Import content").click()
    page.wait_for_selector("input#id_archive", state="attached")
    page.locator("input#id_archive").set_input_files(str(archive_path))
    page.locator("form.form button[type='submit']").click()

    page.wait_for_selector("#id_insertion", state="attached")
    page.locator("#id_insertion").select_option(str(part.pk))
    page.locator("button", has_text="Confirm import").click()

    # Confirm redirects back into course B's builder.
    page.wait_for_selector(f'[data-scope="{part.pk}"]', state="attached")
    part_scope = page.locator(f'[data-scope="{part.pk}"]')
    assert part_scope.locator('.tree__title[value="Root Chapter"]').count() == 1

    new_chapter = course_b.nodes.get(kind="chapter", title="Root Chapter")
    assert new_chapter.parent_id == part.pk
