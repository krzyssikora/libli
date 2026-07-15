"""Playwright e2e for the two-column layout content element (plan Task 11). Drives
the REAL user gestures end-to-end -- clicks the actual buttons, uses the actual
<select>, types with the keyboard -- no page.evaluate shortcuts (this repo's standing
lesson: an e2e that bypasses the real gesture ships broken UX green).

Covers:
  1. Authoring: add the two-column element via the real add-menu gesture, grow it to
     3 columns via the real <select>, Save.
  2. Per-column add: drive column 1's and column 3's OWN nested "Add element -> Text"
     (two different per-column add-menus), type distinct bodies, Save each.
  3. Student view: the taking/lesson view renders three columns SIDE BY SIDE (same
     row, increasing x), each child in the column it was added to, the untouched
     middle column empty.
  4. Shrink (3 -> 2): re-open the element's editor, drop the count back to 2 via the
     real <select>, Save; the third column's child MOVES to the new last column
     (not deleted) -- both in the editor's nested row list and in the re-rendered
     student view.

Modeled on tests/test_e2e_tabs.py (shared harness idiom: login, seed helpers,
add-menu gestures, RTE typing). Marked e2e (excluded from the default run)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Shared login / seed helpers (duplicated per this repo's e2e convention --
# see test_e2e_tabs.py / test_e2e_gallery.py, each file is self-contained).
# ---------------------------------------------------------------------------


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


def _seed_unit(owner, slug):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _columns_rows(page):
    """The three (then two) per-column `<details class=columns-rows>` sections in
    the editor's two-column row, in column order."""
    return page.locator(
        '[data-scope="editor"] .el-row--twocolumn .el-row__columns '
        "> details.columns-rows"
    )


def _wait_columns_state(page, expected_counts):
    """Poll until the editor's per-column nested-row counts match exactly.

    A Save's fetch is fire-and-forget from the caller's point of view (the click
    returns immediately; applyFragments swaps the pane only once the response
    lands), so a naive wait_for_selector for a selector that already matched the
    STALE pane returns instantly without proving the swap happened. Acting on that
    stale pane detaches the very node the next gesture is mid-click on. Polling the
    actual per-column counts is the only race-free checkpoint."""
    page.wait_for_function(
        """(expected) => {
            const details = document.querySelectorAll(
                '[data-scope="editor"] .el-row--twocolumn .el-row__columns '
                + '> details.columns-rows');
            if (details.length !== expected.length) return false;
            return Array.from(details).every((d, i) =>
                d.querySelectorAll('.element-list--nested .el-row').length
                    === expected[i]);
        }""",
        arg=expected_counts,
    )


def _add_text_child(page, column_details, body):
    """Drive that column's OWN nested add-menu -> Text, type `body`, Save. Mirrors
    test_e2e_tabs.py's nested-add gesture, scoped to one column's <details>."""
    column_details.locator("[data-add-toggle]").click()
    column_details.locator("[data-add-type='text']").click()
    surface = page.locator("[data-edit-slot] form[data-op='element-save'] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type(body)
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()


@pytest.mark.django_db(transaction=True)
def test_grow_add_children_shrink_and_student_view(page, live_server):
    from courses.models import Element

    pa = _make_pa_user("tc_e2e")
    course, unit = _seed_unit(pa, "tc-e2e")
    _login(page, live_server, "tc_e2e")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    # --- 1. Add the two-column element via the real add-menu gesture. ---
    page.locator("[data-add-toggle]").first.click()
    page.locator("[data-add-type='twocolumn']").click()
    page.wait_for_selector("[data-edit-slot] .el-editor--twocolumn")

    # Grow to 3 columns via the real <select>, then Save.
    page.locator("[data-edit-slot] select[name='column_count']").select_option("3")
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()

    _wait_columns_state(page, [0, 0, 0])
    rows = _columns_rows(page)
    assert rows.count() == 3

    # --- 2. Add a distinct text child into column 1 (open by default) ... ---
    _add_text_child(page, rows.nth(0), "Alpha text")
    _wait_columns_state(page, [1, 0, 0])

    # ... and into column 3 (closed by default -- open it first via its summary).
    rows = _columns_rows(page)
    col3 = rows.nth(2)
    col3.locator("summary").click()
    _add_text_child(page, col3, "Charlie text")
    _wait_columns_state(page, [1, 0, 1])

    # Both children persisted, scoped to the right column ids, under the same join.
    join = Element.objects.get(unit=unit, parent__isnull=True)
    col_ids = [c["id"] for c in join.content_object.data["columns"]]
    assert len(col_ids) == 3
    alpha = Element.objects.get(parent=join, tab_id=col_ids[0])
    charlie = Element.objects.get(parent=join, tab_id=col_ids[2])
    assert alpha.content_object.body == "Alpha text"
    assert charlie.content_object.body == "Charlie text"

    # The editor's own nested row lists reflect the same placement.
    rows = _columns_rows(page)
    assert rows.nth(0).locator(".element-list--nested .el-row").count() == 1
    assert rows.nth(1).locator(".element-list--nested .el-row").count() == 0
    assert rows.nth(2).locator(".element-list--nested .el-row").count() == 1

    # --- 3. Student/taking view: three columns, side by side, right children. ---
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("[data-twocolumn]")
    columns = page.locator("[data-twocolumn] .twocolumn__column")
    assert columns.count() == 3
    assert "Alpha text" in (columns.nth(0).text_content() or "")
    assert columns.nth(1).get_attribute("data-empty") == ""
    assert "Charlie text" in (columns.nth(2).text_content() or "")

    # Side by side: same row (overlapping vertical band), strictly increasing x.
    boxes = [columns.nth(i).bounding_box() for i in range(3)]
    assert all(b is not None for b in boxes)
    tops = [b["y"] for b in boxes]
    assert max(tops) - min(tops) < 5, f"columns not on the same row: {tops}"
    xs = [b["x"] for b in boxes]
    assert xs[0] < xs[1] < xs[2], f"columns not left-to-right: {xs}"

    # --- 4. Shrink 3 -> 2: the third column's child MOVES to the new last column. ---
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"] .el-row--twocolumn')
    page.locator(f'.el-act-edit[data-element-id="{join.pk}"]').click()
    page.wait_for_selector("[data-edit-slot] .el-editor--twocolumn")
    page.locator("[data-edit-slot] select[name='column_count']").select_option("2")
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()

    _wait_columns_state(page, [1, 1])
    rows = _columns_rows(page)
    assert rows.count() == 2
    # Alpha stayed in column 1; Charlie moved into the (now last) column 2 -- neither
    # was deleted.
    assert "Alpha text" in (rows.nth(0).text_content() or "")
    assert "Charlie text" in (rows.nth(1).text_content() or "")

    alpha.refresh_from_db()
    charlie.refresh_from_db()
    join.content_object.refresh_from_db()
    new_col_ids = [c["id"] for c in join.content_object.data["columns"]]
    assert len(new_col_ids) == 2
    assert alpha.tab_id == new_col_ids[0]
    assert charlie.tab_id == new_col_ids[-1]  # moved, not deleted

    # And the student view now shows 2 columns with Charlie's text present (moved).
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("[data-twocolumn]")
    columns = page.locator("[data-twocolumn] .twocolumn__column")
    assert columns.count() == 2
    assert "Alpha text" in (columns.nth(0).text_content() or "")
    assert "Charlie text" in (columns.nth(1).text_content() or "")
