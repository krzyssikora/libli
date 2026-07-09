"""Playwright e2e for the table content element (plan Task 7): the WYSIWYG
editor (pinned toolbar, own B/I/U execCommand, alignment, real row-insert
handle, math-protected typing) and the save/reopen/consumption round-trip.

Drives the REAL UI gestures throughout (clicks, keyboard typing) — no
page.evaluate shortcuts. Marked e2e (excluded from the default run)."""

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
    # Selectors mirror the proven helper in tests/test_e2e_smoke.py (allauth's
    # login field is name="login").
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _unit(username, slug):
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )


def _editor_url(live_server, unit):
    return (
        f"{live_server.url}/manage/courses/{unit.course.slug}"
        f"/build/unit/{unit.pk}/edit/"
    )


def _add_table(page, live_server, unit):
    """Add a table element to `unit` via the real add-menu gesture. Leaves the
    freshly-added table's edit form open ([data-edit-slot])."""
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator("[data-add-toggle]").click()
    page.locator('[data-add-type="table"]').click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]")


def _format_first_cell_and_add_row(page):
    """Real-gesture sequence shared by both scenarios: click the first cell,
    type a literal '<' both as plain text and inside \\(...\\) math, select
    all, Bold, center-align, then insert a row via the real hover handle."""
    cell = page.locator("[data-edit-slot] [data-table-grid] td[contenteditable]").first
    cell.click()
    page.keyboard.type("a<b")
    page.keyboard.type("\\(x<5\\)")
    page.keyboard.press("Control+A")
    page.locator("[data-edit-slot] [data-table-toolbar] [data-cmd='bold']").click()
    page.locator("[data-edit-slot] [data-table-toolbar] [data-halign='center']").click()
    page.locator("[data-edit-slot] [data-table-grid] [data-row-insert]").last.click()


def _save(page):
    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]", state="detached")


def _reopen(page, live_server, unit, element):
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(f"[data-element='{element.pk}'] .el-act-edit").click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]")


@pytest.mark.django_db(transaction=True)
def test_table_editor_add_format_align_row_and_roundtrip(page, live_server):
    """Add a table, format+align a cell, add a row via the real insert
    handle, and Save. Assert: (1) the persisted cell html is single-escaped
    (the editor-path double-escape guard from Task 1's sanitiser), (2)
    reopening the element shows the round-tripped content in the grid, and
    (3) the student-facing render typesets the cell's math via KaTeX."""
    from django.urls import reverse

    from courses.models import Element
    from courses.models import TableElement

    _make_pa_user("tbl_rt")
    _login(page, live_server, "tbl_rt")
    unit = _unit("tbl_rt", "tbl-rt")

    _add_table(page, live_server, unit)
    _format_first_cell_and_add_row(page)
    _save(page)

    element = Element.objects.get(unit=unit)
    table = TableElement.objects.get(pk=element.object_id)
    data = table.normalized_data
    assert len(data["cells"]) == 3
    assert len(data["cells"][0]) == 2
    first = data["cells"][0][0]
    assert first["halign"] == "center"
    assert "<b>" in first["html"]
    assert r"a&lt;b" in first["html"]
    # Single-escape guard (Task 1): the math span's literal '<' must appear
    # escaped exactly once, never double-escaped.
    assert r"\(x&lt;5\)" in first["html"]
    assert r"\(x&amp;lt;5\)" not in first["html"]

    # Reopen the element: the server re-renders the grid from the saved data
    # and table_editor.js's init-serialize (hidden field empty on this
    # unbound GET) mirrors it straight back — the grid must reflect it.
    _reopen(page, live_server, unit, element)
    reopened_cells = page.locator(
        "[data-edit-slot] [data-table-grid] td[contenteditable]"
    )
    assert reopened_cells.count() == 6
    reopened_text = reopened_cells.first.inner_text()
    assert "a<b" in reopened_text
    assert "\\(x<5\\)" in reopened_text

    # Student-facing consumption: the table renders (course owner can view the
    # lesson page directly) AND its cell math is typeset client-side by KaTeX
    # (math.js .el--table + has_math wiring). The raw \(x<5\) source is consumed
    # by rendering, so assert a .katex node appears inside the table rather than
    # the raw delimiter source; the non-math text "a<b" still shows.
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{path}")
    table = page.locator(".el--table")
    table.wait_for(state="attached", timeout=5000)
    assert "a<b" in table.inner_text()
    # KaTeX typesets the \(x<5\) cell math -> a rendered .katex node appears.
    page.locator(".el--table .katex").first.wait_for(state="attached", timeout=5000)
    assert page.locator(".el--table .katex").count() > 0


@pytest.mark.django_db(transaction=True)
def test_table_edit_preserves_content_when_only_label_changed(page, live_server):
    """Regression: reopening a saved table and changing ONLY the element's
    optional label (never touching the grid) must NOT wipe the table back to
    the default 2x2 — table_editor.js's init-serialize on the edit path must
    have captured the existing (server-rendered) content into the hidden
    field before Save."""
    from courses.models import Element
    from courses.models import TableElement

    _make_pa_user("tbl_lbl")
    _login(page, live_server, "tbl_lbl")
    unit = _unit("tbl_lbl", "tbl-lbl")

    _add_table(page, live_server, unit)
    _format_first_cell_and_add_row(page)
    _save(page)

    element = Element.objects.get(unit=unit)
    before = TableElement.objects.get(pk=element.object_id).normalized_data

    _reopen(page, live_server, unit, element)
    page.locator("[data-edit-slot] input[name='el_title']").fill("Renamed")
    _save(page)

    after = TableElement.objects.get(pk=element.object_id).normalized_data
    assert after["cells"] == before["cells"]
    assert len(after["cells"]) == 3
    assert after["cells"][0][0]["halign"] == "center"
    element.refresh_from_db()
    assert element.title == "Renamed"
