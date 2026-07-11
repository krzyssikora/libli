"""Playwright e2e for the editor view toggle (Editor/Split/Preview) + width model.

Mirrors the helpers in test_e2e_editor_ws3.py: DJANGO_ALLOW_ASYNC_UNSAFE session
fixture, PLATFORM_ADMIN seed, allauth login, and the courses:manage_editor URL.
Drives the REAL button clicks and a REAL reload (no page.evaluate shortcut)."""

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


def _seed_unit(pa, slug="viewtog"):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


@pytest.mark.django_db
def test_toggle_switches_and_persists(page, live_server):
    pa = _make_pa_user("pa")
    course, unit = _seed_unit(pa)
    page.set_viewport_size({"width": 1400, "height": 900})  # wide: two-column split
    _login(page, live_server, "pa")
    page.goto(_editor_url(live_server, course, unit))

    grid = page.locator(".editor-grid")
    editor_pane = page.locator('[data-scope="editor"]')
    preview_pane = page.locator('[data-scope="preview"]')

    # Default split: both panes visible, toggle revealed (enhancer removed [hidden]).
    assert "is-mode-split" in (grid.get_attribute("class") or "")
    page.wait_for_selector("[data-view-toggle]", state="visible")
    assert editor_pane.is_visible() and preview_pane.is_visible()

    # Wide split is genuinely two side-by-side columns (not stacked): preview sits to
    # the right of the editor and their vertical extents overlap (same row).
    eb = editor_pane.bounding_box()
    pb = preview_pane.bounding_box()
    assert pb["x"] > eb["x"]
    assert pb["y"] < eb["y"] + eb["height"] and eb["y"] < pb["y"] + pb["height"]

    # Click Preview: editor pane hidden, class + storage updated.
    page.locator('[data-view="preview"]').click()
    assert "is-mode-preview" in (grid.get_attribute("class") or "")
    assert not editor_pane.is_visible()
    assert preview_pane.is_visible()
    assert page.evaluate("localStorage.getItem('libli-editor-view')") == "preview"

    # Reload: persists to Preview end-state (pre-paint stamps it before paint).
    page.reload()
    grid = page.locator(".editor-grid")
    assert "is-mode-preview" in (grid.get_attribute("class") or "")
    assert not page.locator('[data-scope="editor"]').is_visible()


@pytest.mark.django_db
def test_corrupt_stored_value_falls_back_to_split(page, live_server):
    pa = _make_pa_user("pa2")
    course, unit = _seed_unit(pa, slug="viewtog2")
    page.set_viewport_size({"width": 1400, "height": 900})
    _login(page, live_server, "pa2")
    page.goto(_editor_url(live_server, course, unit))
    page.evaluate("localStorage.setItem('libli-editor-view', 'garbage')")
    page.reload()
    grid = page.locator(".editor-grid")
    assert "is-mode-split" in (grid.get_attribute("class") or "")


@pytest.mark.django_db
def test_narrow_viewport_stacks_split(page, live_server):
    pa = _make_pa_user("pa3")
    course, unit = _seed_unit(pa, slug="viewtog3")
    page.set_viewport_size({"width": 1000, "height": 900})  # <70rem/1120px: stacks
    _login(page, live_server, "pa3")
    page.goto(_editor_url(live_server, course, unit))
    ed = page.locator('[data-scope="editor"]').bounding_box()
    pv = page.locator('[data-scope="preview"]').bounding_box()
    # Stacked: preview sits below the editor (not side-by-side).
    assert pv["y"] >= ed["y"] + ed["height"] - 5


@pytest.mark.django_db
def test_solo_editor_pane_is_wider_than_split(page, live_server):
    """Regression: Editor-only mode caps the editor pane at --editor-solo-max (54rem),
    which is deliberately WIDER than its split cap --editor-split-max (48rem). A bug had
    the solo pane collapse to its content width (item-level width:100%+max-width on the
    flex pane inside a 1fr column), rendering solo NARROWER than split. Guard the
    intent: on a wide screen (both caps reachable) solo editor pane > split editor."""
    pa = _make_pa_user("pa4")
    course, unit = _seed_unit(pa, slug="viewtog4")
    # 1680px is wide enough for split's editor to reach its full 48rem cap, so the
    # comparison is cap-vs-cap (54rem vs 48rem), not screen-limited.
    page.set_viewport_size({"width": 1680, "height": 950})
    _login(page, live_server, "pa4")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    def editor_pane_width():
        return page.evaluate(
            "Math.round(document.querySelector('[data-scope=\"editor\"]')"
            ".getBoundingClientRect().width)"
        )

    # Split (default): editor reaches its 48rem cap (~768px at this viewport).
    split_w = editor_pane_width()
    # Editor-only: editor pane should reach its 54rem cap (~864px) — wider than split.
    page.locator('[data-view="editor"]').click()
    page.wait_for_timeout(200)
    solo_w = editor_pane_width()

    assert solo_w > split_w, (
        f"solo editor pane ({solo_w}px) must be wider than split ({split_w}px)"
    )
    # And it should actually reach ~54rem (864px), not merely edge past split.
    assert solo_w >= 820, f"solo editor pane should reach ~54rem, got {solo_w}px"
