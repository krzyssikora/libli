"""Playwright e2e for batch-2 unit-nav: desktop collapse rail + auto-scroll.

Tests:
  1. test_desktop_tree_collapse_persists: toggle collapses the tree;
     class lands on <html>; reload restores via the pre-paint script (no
     flash); toggle back removes it; reload confirms expanded.
  2. test_active_unit_scrolled_into_view: 35-unit course; navigate to
     the last unit; the tree auto-scrolls so the active item is visible
     (reduced-motion context makes the JS take the instant "auto" branch
     so the wait_for_function poll settles deterministically).
  3. test_prev_next_traverses_lesson_and_quiz: Prev/Next traversal across
     a lesson→quiz→lesson sequence; pins that the 302 redirect from
     lesson_unit to quiz_unit is followed correctly and that a disabled
     prev is rendered on the first unit.

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


def _seed_traversal_course(username, slug):
    """Create a course with one part containing [lesson A, quiz B, lesson C].

    Returns (course, lesson_a, quiz_b, lesson_c). The student is enrolled.
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
    lesson_a = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part, title="Lesson A"
    )
    quiz_b = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=part, title="Quiz B"
    )
    lesson_c = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part, title="Lesson C"
    )
    return course, lesson_a, quiz_b, lesson_c


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


# ---------------------------------------------------------------------------
# Mobile drawer tests (Task 6)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_mobile_drawer_open_close_scrim_and_esc(browser, live_server):
    """FAB opens drawer; closes on scrim tap and Esc; focus returns to FAB."""
    _make_student("e2e_drawer_close")
    course, units = _seed_nav_course(
        "e2e_drawer_close", "e2e-drawer-close", num_units=5
    )
    first_unit = units[0]

    ctx = browser.new_context(viewport={"width": 390, "height": 780})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2e_drawer_close")
        unit_url = f"{live_server.url}/courses/{course.slug}/u/{first_unit.pk}/"
        page.goto(unit_url)

        fab = page.locator("[data-unit-drawer-open]")
        # Progressive enhancement: JS sets fab.hidden = False so it becomes visible.
        assert fab.is_visible(), "FAB should be visible on mobile (JS revealed it)"

        # Open drawer.
        fab.click()
        drawer = page.locator("[data-unit-drawer]")
        assert drawer.is_visible(), "Drawer should be visible after FAB click"

        # Close on scrim tap.
        page.locator(".unit-drawer__scrim").click(position={"x": 5, "y": 5})
        assert drawer.is_hidden(), "Drawer should close on scrim tap"

        # Reopen, then close on Esc.
        fab.click()
        assert drawer.is_visible(), "Drawer should reopen on FAB click"
        page.keyboard.press("Escape")
        assert drawer.is_hidden(), "Drawer should close on Escape key"

        # Focus should have returned to the FAB.
        assert (
            page.evaluate(
                "document.activeElement?.getAttribute('data-unit-drawer-open') !== null"
            )
            is True
        ), "Focus should return to FAB after close"
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_mobile_drawer_focus_trap(browser, live_server):
    """Focus trap: Shift+Tab from first focusable wraps to last, inside drawer."""
    _make_student("e2e_drawer_trap")
    course, units = _seed_nav_course("e2e_drawer_trap", "e2e-drawer-trap", num_units=5)
    first_unit = units[0]

    ctx = browser.new_context(viewport={"width": 390, "height": 780})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2e_drawer_trap")
        unit_url = f"{live_server.url}/courses/{course.slug}/u/{first_unit.pk}/"
        page.goto(unit_url)

        fab = page.locator("[data-unit-drawer-open]")
        fab.click()
        drawer = page.locator("[data-unit-drawer]")
        assert drawer.is_visible(), "Drawer should be open"

        # Focus the close button (first focusable) via evaluate (observation only).
        page.evaluate(
            "document.querySelector('[data-unit-drawer] .unit-drawer__close')?.focus()"
        )

        # Shift+Tab from first focusable must wrap to last, staying inside drawer.
        page.keyboard.press("Shift+Tab")

        inside = page.evaluate(
            "!!document.querySelector('[data-unit-drawer]')"
            ".contains(document.activeElement)"
        )
        assert inside is True, "Focus must stay inside the drawer after Shift+Tab"

        is_last = page.evaluate(
            "(() => {"
            " const p = document.querySelector"
            "('[data-unit-drawer] .unit-drawer__panel');"
            " const f = [...p.querySelectorAll("
            "'a[href],button:not([disabled]),[tabindex]:not([tabindex=\"-1\"])')]"
            ".filter(e => e.offsetParent);"
            " return document.activeElement === f[f.length - 1];"
            "})()"
        )
        assert is_last is True, "Focus must wrap to the last focusable in the drawer"
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Prev/Next traversal test (Task 7)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_prev_next_traverses_lesson_and_quiz(browser, live_server):
    """Next from lesson A reaches quiz B via 302; Prev returns to lesson A.

    The footer Next link always uses the lesson_unit URL; when the destination
    is a quiz the server redirects (302) to quiz_unit.  This test pins that
    redirect path and confirms: disabled-prev renders for the first unit.
    """
    _make_student("e2e_traversal")
    course, lesson_a, _quiz_b, _lesson_c = _seed_traversal_course(
        "e2e_traversal", "e2e-traversal"
    )

    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2e_traversal")

        unit_url = f"{live_server.url}/courses/{course.slug}/u/{lesson_a.pk}/"
        page.goto(unit_url)

        # Next → quiz B (lesson_unit URL; server 302s quizzes to quiz_unit)
        page.locator(".unit-foot__nav--primary").click()
        page.wait_for_url("**/quiz/")  # landed on the quiz unit

        # Prev → back to lesson A
        page.locator(".unit-foot__nav:not(.unit-foot__nav--primary)").click()
        page.wait_for_url(f"**/u/{lesson_a.pk}/")

        # First unit has a disabled prev (a span, not a link)
        assert page.locator(".unit-foot__nav--disabled").count() >= 1, (
            "Expected a disabled prev nav on the first unit"
        )
    finally:
        ctx.close()
