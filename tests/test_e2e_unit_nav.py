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


@pytest.mark.django_db(transaction=True)
def test_active_unit_scroll_does_not_move_window(browser, live_server):
    """Load-time rail auto-scroll must NOT scroll the window/article.

    The active (last) unit has a tall article so the page overflows the viewport
    (window.scrollY CAN change); with the pre-fix `scrollIntoView` the queued
    window scroll pushed scrollY non-zero, with the container-scoped fix it stays 0.
    """
    from courses.models import TextElement
    from tests.factories import add_element

    _make_student("e2e_nav_nojump")
    course, units = _seed_nav_course("e2e_nav_nojump", "e2e-nav-nojump", num_units=35)
    last_unit = units[-1]
    tall = "".join(f"<p>Para {i}</p>" for i in range(200))
    add_element(last_unit, TextElement.objects.create(body=tall))

    # reduced-motion → instant scroll (rail AND, pre-fix, the window scroll) settles
    # synchronously, so the poll-then-read below is deterministic.
    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_nav_nojump")
    unit_url = f"{live_server.url}/courses/{course.slug}/u/{last_unit.pk}/"
    page.goto(unit_url)

    # Precondition: the page really overflows, so the guard below can't go vacuous.
    assert page.evaluate(
        "() => document.documentElement.scrollHeight > window.innerHeight"
    ), "seed did not overflow the viewport; window-no-jump guard would be vacuous"

    # Wait until the rail has scrolled the active (last) item down.
    tree = page.locator("[data-unit-tree]")
    page.wait_for_function("el => el.scrollTop > 0", arg=tree.element_handle())

    assert page.evaluate("() => window.scrollY") == 0, (
        "load-time auto-scroll moved the window/article"
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
            "'a[href],button:not([disabled]),summary,[tabindex]:not([tabindex=\"-1\"])')]"
            ".filter(e => e.checkVisibility());"
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


# ---------------------------------------------------------------------------
# Folding groups (<details>) — seed + tests
# ---------------------------------------------------------------------------


def _seed_grouped_course(username, slug, num_chapters=6, units_per_chapter=8):
    """A course with several chapters, current unit in the MIDDLE chapter so both an
    earlier and a later sibling are observably shut."""
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    User = get_user_model()
    student = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=student)
    EnrollmentFactory(student=student, course=course)

    chapters, units = [], []
    for c in range(num_chapters):
        chapter = ContentNodeFactory(
            course=course,
            kind="chapter",
            parent=None,
            unit_type=None,
            title=f"Chapter {c + 1}",
        )
        chapters.append(chapter)
        for u in range(units_per_chapter):
            units.append(
                ContentNodeFactory(
                    course=course,
                    kind="unit",
                    unit_type="lesson",
                    parent=chapter,
                    title=f"C{c + 1} Unit {u + 1}",
                )
            )
    middle = units[len(units) // 2]
    middle_chapter = middle.parent

    # A SECTION nested inside the current (open) chapter. Without this the seed is a
    # flat set of sibling chapters, and the chevron test's negative half cannot detect
    # the bug it exists to catch: the hazard is `details[open] .unit-tree__chevron`
    # matching a CLOSED group that is a DESCENDANT of an open one. Sibling chapters are
    # not descendants, so a buggy descendant selector would leave them unrotated and
    # would pass.
    nested_section = ContentNodeFactory(
        course=course,
        kind="section",
        parent=middle_chapter,
        unit_type=None,
        title="Nested Section",
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=nested_section,
        title="Nested Unit 1",
    )
    return course, chapters, units, middle, nested_section


@pytest.mark.django_db(transaction=True)
def test_current_chapter_open_siblings_shut(browser, live_server):
    _make_student("e2e_fold")
    course, chapters, _units, middle, _sec = _seed_grouped_course(
        "e2e_fold", "e2e-fold"
    )

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_fold")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    # all_text_contents(), NOT all_inner_texts(): .unit-tree__grouptitle inherits
    # text-transform: uppercase from the chapter micro-type rule, and innerText reflects
    # RENDERED text — so inner_text would yield "CHAPTER 4" and the comparison would
    # invert the RED/GREEN cycle (passing before Step 3's selector fix, failing after).
    open_titles = rail.locator(
        "details[open] > summary .unit-tree__grouptitle"
    ).all_text_contents()
    open_titles = [t.strip() for t in open_titles]
    # The nested section inside the current chapter is SHUT, so one group is open.
    assert open_titles == [middle.parent.title], (
        f"exactly the current chapter should be open, got {open_titles}"
    )

    shut = rail.locator("details:not([open])")
    # every other chapter, plus the nested section inside the open one
    assert shut.count() == len(chapters) - 1 + 1, "every other group should be shut"
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_clicking_a_folded_summary_reveals_its_units(browser, live_server):
    _make_student("e2e_reveal")
    course, _chapters, _units, middle, _sec = _seed_grouped_course(
        "e2e_reveal", "e2e-reveal"
    )

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_reveal")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    first_unit_of_ch1 = rail.get_by_role("link", name="C1 Unit 1")
    assert not first_unit_of_ch1.is_visible(), "Chapter 1 should start folded"

    rail.locator("summary", has_text="Chapter 1").first.click()  # real click
    first_unit_of_ch1.wait_for(state="visible")
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_chapter_microtype_survives_the_details_nesting(browser, live_server):
    """The highest-risk change in 2A: the > child combinator stops matching once
    <details> is interposed, and chapters silently lose their uppercase micro-type.
    Baseline is the literal current value (courses.css:540-542), not 'same as today'."""
    _make_student("e2e_micro")
    course, _chapters, _units, middle, _sec = _seed_grouped_course(
        "e2e_micro", "e2e-micro"
    )
    from tests.factories import ContentNodeFactory

    # the childless shape
    ContentNodeFactory(
        course=course,
        kind="chapter",
        parent=None,
        unit_type=None,
        title="Empty Chapter",
    )

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_micro")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    for locator, shape in (
        (rail.locator("details > summary.unit-tree__head").first, "<details> shape"),
        (rail.locator("div.unit-tree__head").first, "childless shape"),
    ):
        style = locator.evaluate(
            "el => { const s = getComputedStyle(el);"
            " return {tt: s.textTransform, fs: s.fontSize}; }"
        )
        assert style["tt"] == "uppercase", f"{shape}: lost uppercase ({style['tt']})"
        # .64rem against the 16px root = 10.24px.
        assert abs(float(style["fs"].rstrip("px")) - 10.24) < 0.5, (
            f"{shape}: font-size drifted ({style['fs']})"
        )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_chevron_rotates_only_for_the_open_group(browser, live_server):
    """Both halves in one test so they cannot drift apart: a missing rule satisfies the
    negative assertion perfectly while shipping a chevron that never rotates."""
    _make_student("e2e_chev")
    course, _chapters, _units, middle, _sec = _seed_grouped_course(
        "e2e_chev", "e2e-chev"
    )

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_chev")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    open_t = rail.locator(
        "details[open] > summary > .unit-tree__chevron"
    ).first.evaluate("el => getComputedStyle(el).transform")
    # Target the NESTED section specifically — a closed group INSIDE the open chapter.
    # A sibling closed chapter would not detect the descendant-selector bug, because it
    # is not a descendant of the open one.
    shut_t = rail.locator(
        "details[open] details:not([open]) > summary > .unit-tree__chevron"
    ).first.evaluate("el => getComputedStyle(el).transform")
    assert open_t not in ("none", "matrix(1, 0, 0, 1, 0, 0)"), (
        f"open group's chevron does not rotate ({open_t})"
    )
    assert shut_t in ("none", "matrix(1, 0, 0, 1, 0, 0)"), (
        f"closed NESTED group's chevron is rotated ({shut_t}) — the rotation selector "
        f"is a descendant selector; it must be the direct-child chain"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_drawer_focus_trap_holds_at_a_folded_summary(browser, live_server):
    """<summary> is natively tabbable but matches none of focusable()'s selectors, so
    without widening it, Tab from a trailing folded summary escapes the drawer."""
    _make_student("e2e_trap")
    course, _chapters, _units, middle, _sec = _seed_grouped_course(
        "e2e_trap", "e2e-trap"
    )

    ctx = browser.new_context(
        reduced_motion="reduce", viewport={"width": 480, "height": 800}
    )
    page = ctx.new_page()
    _login(page, live_server, "e2e_trap")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    page.locator("[data-unit-drawer-open]").click()
    page.locator("[data-unit-drawer]").wait_for(state="visible")

    last_summary = page.locator("[data-unit-drawer] details:not([open]) > summary").last
    last_summary.focus()
    page.keyboard.press("Tab")

    inside = page.evaluate(
        "() => !!document.activeElement.closest('[data-unit-drawer]')"
    )
    assert inside, (
        "Tab escaped the drawer from a folded summary — focusable() must include "
        "summary"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_drawer_shows_the_current_chain_open(browser, live_server):
    """The drawer has its own container and centring path, so it gets its own cover."""
    _make_student("e2e_drawer_fold")
    course, chapters, _units, middle, _sec = _seed_grouped_course(
        "e2e_drawer_fold", "e2e-drawer-fold"
    )

    ctx = browser.new_context(
        reduced_motion="reduce", viewport={"width": 480, "height": 800}
    )
    page = ctx.new_page()
    _login(page, live_server, "e2e_drawer_fold")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    page.locator("[data-unit-drawer-open]").click()
    drawer = page.locator("[data-unit-drawer]")
    drawer.wait_for(state="visible")

    open_titles = [
        t.strip()
        for t in drawer.locator(
            "details[open] > summary .unit-tree__grouptitle"
        ).all_text_contents()  # not inner_text — see the rail test's note on uppercase
    ]
    assert open_titles == [middle.parent.title]
    assert drawer.locator("details:not([open])").count() == len(chapters) - 1 + 1
    ctx.close()


# ---------------------------------------------------------------------------
# Worst-case summary row — screenshot harness (review artifact, not coverage)
# ---------------------------------------------------------------------------

WORST_CASE_TITLE = "Wprowadzenie do funkcji trygonometrycznych i ich zastosowania"


def _seed_worst_case_row(username, slug):
    """Pinned synthetic worst case for the screenshot review: the deepest nesting, a
    long title, and a full 12/12 counter — plus a childless group whose title must line
    up with the <details> shape's."""
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import UnitProgressFactory

    student = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=student)
    EnrollmentFactory(student=student, course=course)

    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Part One"
    )
    chapter = ContentNodeFactory(
        course=course, kind="chapter", parent=part, unit_type=None, title="Chapter One"
    )
    section = ContentNodeFactory(
        course=course,
        kind="section",
        parent=chapter,
        unit_type=None,
        title=WORST_CASE_TITLE,
    )
    units = [
        ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type="lesson",
            parent=section,
            title=f"Unit {i + 1}",
            obligatory=True,
        )
        for i in range(12)
    ]
    for unit in units:
        UnitProgressFactory(student=student, unit=unit, completed=True)
    ContentNodeFactory(
        course=course,
        kind="chapter",
        parent=part,
        unit_type=None,
        title="Childless Chapter",
    )
    return course, units[0]


@pytest.mark.django_db(transaction=True)
def test_capture_worst_case_row(browser, live_server, tmp_path):
    """Screenshot harness for the worst-case summary row. Not an assertion test — it
    exists to produce the review artifact. DELETE before opening the PR."""
    _make_student("e2e_worst")
    course, first_unit = _seed_worst_case_row("e2e_worst", "e2e-worst")

    for scheme in ("light", "dark"):
        ctx = browser.new_context(reduced_motion="reduce", color_scheme=scheme)
        page = ctx.new_page()
        _login(page, live_server, "e2e_worst")
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{first_unit.pk}/")
        page.locator("[data-unit-tree]").screenshot(
            path=str(tmp_path / f"rail-{scheme}.png")
        )

        page.set_viewport_size({"width": 480, "height": 800})
        page.locator("[data-unit-drawer-open]").click()
        page.locator("[data-unit-drawer]").screenshot(
            path=str(tmp_path / f"drawer-{scheme}.png")
        )
        ctx.close()
    print(f"screenshots in {tmp_path}")


# ---------------------------------------------------------------------------
# Re-centring on expand + the active marker
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_expanding_the_rail_recentres_the_active_unit(browser, live_server):
    """The bug: centring ran only on load and only when not collapsed, so expanding a
    collapsed rail left the student at scroll-top with the active unit far away."""
    _make_student("e2e_recentre")
    # 40 units in the CURRENT chapter. With the default 8, the folded tree is ~400px
    # inside a 720px rail — it never scrolls, the active row is always inside the
    # visible band, and the poll below succeeds with OR without centerActive(). The
    # test could never go red. (The pre-existing test_active_unit_scrolled_into_view
    # needed 35 VISIBLE units for the same reason.) Only the open chapter's units are
    # visible, so they must carry the count.
    course, _chapters, units, middle, _sec = _seed_grouped_course(
        "e2e_recentre", "e2e-recentre", num_chapters=3, units_per_chapter=40
    )
    # The LAST unit of the current chapter, not the middle one. Overflowing the rail is
    # not sufficient: the active row must start OUTSIDE the visible band, or the poll
    # below succeeds at scrollTop=0 with or without centerActive(). (The pre-existing
    # test_active_unit_scrolled_into_view targets the last of 35 for the same reason.)
    target = [u for u in units if u.parent == middle.parent][-1]

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_recentre")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{target.pk}/")

    # Precondition: the rail overflows AND the active row would be out of view at
    # the top.
    overflow = page.locator("[data-unit-tree]").evaluate(
        "el => el.scrollHeight - el.clientHeight"
    )
    assert overflow > 0, f"rail does not scroll (overflow={overflow}); seed more units"
    out_of_band_at_top = page.evaluate(
        """() => {
             const rail = document.querySelector('[data-unit-tree]');
             const act = rail.querySelector('.unit-tree__unit.is-active');
             const prev = rail.scrollTop;
             rail.scrollTop = 0;
             const r = act.getBoundingClientRect(), t = rail.getBoundingClientRect();
             const out = r.bottom > t.bottom || r.top < t.top;
             rail.scrollTop = prev;
             return out;
           }"""
    )
    assert out_of_band_at_top, (
        "the active row is visible at scrollTop=0, so this test cannot detect a "
        "missing re-centre — target a unit further down the current chapter"
    )

    toggle = page.locator("[data-unit-tree-toggle]")
    toggle.click()  # collapse (real gesture)
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    toggle.click()  # expand
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('unit-tree-collapsed')"
    )

    # Poll: centerActive() may animate. Assert the active row sits inside the rail's
    # visible band, not merely that scrollTop moved.
    page.wait_for_function(
        """() => {
             const rail = document.querySelector('[data-unit-tree]');
             const act = rail && rail.querySelector('.unit-tree__unit.is-active');
             if (!act) return false;
             const r = act.getBoundingClientRect(), t = rail.getBoundingClientRect();
             return r.top >= t.top && r.bottom <= t.bottom;
           }""",
        timeout=5000,
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_active_marker_is_strong_and_width_neutral(browser, live_server):
    _make_student("e2e_marker")
    course, _chapters, _units, middle, _sec = _seed_grouped_course(
        "e2e_marker", "e2e-marker"
    )

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_marker")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    active = rail.locator(".unit-tree__unit.is-active").first
    # Scope the comparison row to the OPEN chapter. `.unit-tree__unit:not(.is-active)`
    # in DOM order is the first unit of Chapter 1, inside a CLOSED <details> — and
    # Playwright returns None from bounding_box() for a non-rendered element, so the
    # subtraction below would raise TypeError and the assertion could never run.
    inactive = rail.locator("details[open] > ul .unit-tree__unit:not(.is-active)").first

    assert active.evaluate("el => getComputedStyle(el).fontWeight") == "700"

    # Width-neutral: the active row's text starts at the same x as its siblings'.
    abox = active.locator(".unit-tree__label").bounding_box()
    ibox = inactive.locator(".unit-tree__label").bounding_box()
    assert abox is not None and ibox is not None, (
        "both rows must be rendered to compare"
    )
    ax, ix = abox["x"], ibox["x"]
    assert abs(ax - ix) < 1.0, (
        f"active row's text jogged by {ax - ix:.1f}px — widen the bar without changing "
        f"the box (inset box-shadow or ::before), or compensate padding-left"
    )

    # Focus ring: driven by a REAL Tab. Chromium's :focus-visible heuristic does not
    # apply reliably to a programmatic .focus() with no prior keyboard interaction.
    # Tab forward until the active row has keyboard focus (bounded, so a regression
    # fails rather than hangs). Tabbing is what arms :focus-visible.
    page.locator("[data-unit-tree-toggle]").focus()
    for _ in range(200):
        page.keyboard.press("Tab")
        if page.evaluate(
            "() => !!document.activeElement.classList"
            " && document.activeElement.classList.contains('is-active')"
        ):
            break
    else:
        raise AssertionError("never reached the active row by tabbing")
    ring = active.evaluate(
        "el => { const s = getComputedStyle(el);"
        " return {w: s.outlineWidth, o: s.outlineOffset}; }"
    )
    assert ring["w"] not in ("0px", ""), "no focus-visible ring on the active row"
    # The ring shares --primary with the accent bar by design (one ring colour for the
    # whole rail); what keeps them tellable apart is the OFFSET — a flush inset bar on
    # the left edge versus an outline standing off the whole row.
    assert ring["o"] not in ("0px", ""), (
        f"focus ring has no offset ({ring['o']}) — it will merge into the accent bar"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_done_and_active_row_keeps_the_active_colour(browser, live_server):
    """A completed current unit must not render in .is-done's faint --text-tertiary —
    it is the one row the student most needs to find."""
    _make_student("e2e_doneactive")
    course, _chapters, units, middle, _sec = _seed_grouped_course(
        "e2e_doneactive", "e2e-doneactive"
    )
    from django.contrib.auth import get_user_model

    from tests.factories import UnitProgressFactory

    student = get_user_model().objects.get(username="e2e_doneactive")
    UnitProgressFactory(student=student, unit=middle, completed=True)
    # A SECOND completed unit in the same (open) chapter, so a done-but-not-active
    # comparison row always exists. Without it the comparison below is skipped and the
    # test asserts nothing about the cascade.
    other_done = next(
        u for u in units if u.parent == middle.parent and u.pk != middle.pk
    )
    UnitProgressFactory(student=student, unit=other_done, completed=True)

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_doneactive")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    active = rail.locator(".unit-tree__unit.is-active").first
    assert "is-done" in (active.get_attribute("class") or ""), (
        "seed did not mark it done"
    )

    active_colour = active.evaluate("el => getComputedStyle(el).color")
    done_only = rail.locator(".unit-tree__unit.is-done:not(.is-active)").first
    # No `if count()` guard: an absent comparison row is a seeding failure and must fail
    # the test, not silently skip its only meaningful assertion.
    assert done_only.count() == 1, "seed must include a done-only row"
    assert active_colour != done_only.evaluate("el => getComputedStyle(el).color"), (
        "done+active resolves to the faint --text-tertiary — .is-active must win "
        "(check it comes AFTER .is-done in source order)"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_centering_is_skipped_when_the_active_group_is_folded(browser, live_server):
    """The folded-active guard. NOTE: this passes VACUOUSLY before centerActive() lands
    (today the expand does nothing at all). Its only meaningful run is the deliberate
    falsification: delete `if (!active.checkVisibility()) return;` and it fails with
    __scrollToCalls == 1."""
    _make_student("e2e_guard")
    course, _chapters, _units, middle, _sec = _seed_grouped_course(
        "e2e_guard", "e2e-guard", num_chapters=3, units_per_chapter=40
    )
    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_guard")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    # Real click: fold the chapter that contains the active unit. (Verified against this
    # repo's Playwright Chromium: after folding, the active link keeps a truthy
    # offsetParent and a stale non-zero rect — only checkVisibility() sees it hidden.)
    page.locator("[data-unit-tree] details[open] > summary").first.click()
    page.wait_for_function(
        "() => !document.querySelector('[data-unit-tree] .unit-tree__unit.is-active')"
        "        .checkVisibility()"
    )

    page.evaluate(
        """() => {
             const rail = document.querySelector('[data-unit-tree]');
             window.__scrollToCalls = 0;
             const real = rail.scrollTo.bind(rail);
             rail.scrollTo = function () {
               window.__scrollToCalls++;
               return real.apply(this, arguments);
             };
           }"""
    )

    toggle = page.locator("[data-unit-tree-toggle]")
    toggle.click()  # collapse (real gesture)
    toggle.click()  # expand   (real gesture) -> centerActive() runs
    assert page.evaluate("() => window.__scrollToCalls") == 0, (
        "centerActive() scrolled the rail for an element with no layout box — the "
        "visibility guard is missing, and the rail will jump to a stale-rect position"
    )
    ctx.close()
