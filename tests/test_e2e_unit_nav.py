"""Playwright e2e for batch-2 unit-nav: desktop collapse rail + auto-scroll.

Tests:
  1. test_desktop_tree_collapse_persists: toggle collapses the tree;
     class lands on <html>; reload restores via the pre-paint script (no
     flash); toggle back removes it; reload confirms expanded.
  2. test_active_unit_scrolled_into_view: 35-unit course; navigate to
     the last unit; the tree auto-scrolls so the active item is visible
     (reduced-motion context makes the JS take the instant "auto" branch
     so the wait_for_function poll settles deterministically).

Marked e2e (excluded from the default run; run with -m e2e).
Mirrors the harness in test_e2e_quiz.py (_allow_async_unsafe, _login,
make_verified_user, pytestmark, ORM seeding).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_student(username):
    """Create a verified student user."""
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _login(page, live_server, username):
    """Log in via the allauth HTML form."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _seed_nav_course(username, slug, num_units=35):
    """Create a course with one part containing num_units lesson units.

    Returns (course, units) where units is a list of ContentNode in creation
    order (ascending). The student is enrolled.
    """
    from django.contrib.auth import get_user_model

    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    User = get_user_model()
    student = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Part 1"
    )
    units = []
    for i in range(num_units):
        unit = ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type="lesson",
            parent=part,
            title=f"Unit {i + 1}",
        )
        units.append(unit)
    return course, units


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_desktop_tree_collapse_persists(browser, live_server):
    """Toggle collapses tree; class lands on <html>; reload restores; toggle back."""
    _make_student("e2e_nav_collapse")
    course, units = _seed_nav_course("e2e_nav_collapse", "e2e-nav-collapse")
    first_unit = units[0]

    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "e2e_nav_collapse")

    unit_url = f"{live_server.url}/courses/{course.slug}/u/{first_unit.pk}/"
    page.goto(unit_url)
    assert page.locator("[data-unit-tree]").is_visible()

    # Collapse via the toggle button (real click gesture).
    page.locator("[data-unit-tree-toggle]").click()
    assert "unit-tree-collapsed" in page.locator("html").get_attribute("class"), (
        "Expected unit-tree-collapsed on <html> after toggle click"
    )

    # Reload → pre-paint script reads localStorage and restores class before paint.
    page.reload()
    html_cls = page.locator("html").get_attribute("class") or ""
    assert "unit-tree-collapsed" in html_cls, (
        "Expected unit-tree-collapsed to persist across reload (pre-paint restore)"
    )

    # Toggle back → expanded; reload to confirm persistence.
    page.locator("[data-unit-tree-toggle]").click()
    page.reload()
    html_cls = page.locator("html").get_attribute("class") or ""
    assert "unit-tree-collapsed" not in html_cls, (
        "Expected unit-tree-collapsed removed after toggle-back; "
        "reload confirms expanded"
    )

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_active_unit_scrolled_into_view(browser, live_server):
    """Active unit below the fold in a 35-unit tree auto-scrolls into view."""
    _make_student("e2e_nav_scroll")
    # 35 units × ~30 px/row ≈ 1050 px > 720 px default viewport → off-screen.
    course, units = _seed_nav_course("e2e_nav_scroll", "e2e-nav-scroll", num_units=35)
    last_unit = units[-1]

    # reduced_motion="reduce" → JS reads matchMedia → takes the instant "auto" branch,
    # so scrollIntoView completes synchronously; the wait_for_function poll settles
    # deterministically without racing a smooth animation.
    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_nav_scroll")

    unit_url = f"{live_server.url}/courses/{course.slug}/u/{last_unit.pk}/"
    page.goto(unit_url)

    # Scope to the inline tree: the mobile drawer renders a SECOND .is-active node;
    # a bare ".unit-tree__unit.is-active" locator hits Playwright strict-mode.
    active = page.locator("[data-unit-tree] .unit-tree__unit.is-active")
    assert active.count() == 1, (
        f"Expected exactly 1 active node in [data-unit-tree], got {active.count()}"
    )

    tree = page.locator("[data-unit-tree]")
    tree_handle = tree.element_handle()

    # Poll until the tree's scroll container has scrolled down.
    # Even with reduced-motion the JS is deferred, so we poll rather than read once.
    page.wait_for_function("el => el.scrollTop > 0", arg=tree_handle)

    tbox = tree.bounding_box()
    abox = active.bounding_box()
    assert tbox is not None and abox is not None
    assert abox["y"] >= tbox["y"], (
        f"Active unit top ({abox['y']:.1f}) is above tree top ({tbox['y']:.1f})"
    )
    assert abox["y"] + abox["height"] <= tbox["y"] + tbox["height"], (
        f"Active unit bottom ({abox['y'] + abox['height']:.1f}) "
        f"exceeds tree bottom ({tbox['y'] + tbox['height']:.1f})"
    )

    ctx.close()
