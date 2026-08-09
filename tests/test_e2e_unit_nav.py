"""Playwright e2e for batch-2 unit-nav: desktop collapse rail, auto-scroll, the
mobile drawer, folding chapter groups, the pinned table-of-contents icon (its
visibility, focus handling, and layout across breakpoints), and the 46rem prose
cap it makes room for. See the test names below for coverage.

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


def _collapse(page):
    """Collapse via the real gesture and wait for the state class."""
    page.locator("[data-unit-tree-toggle]").click()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )


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


def _seed_text_and_table_unit(username, slug):
    """A lesson unit holding one text element and one table element.

    None of this file's existing seeds attach content elements — they build course
    structure only. Shape follows tests/test_e2e_wide_content_scroll.py.
    """
    from django.contrib.auth import get_user_model

    from courses.models import Enrollment
    from courses.models import TableElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import add_element

    student = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")

    add_element(
        unit,
        TextElement.objects.create(
            body="<p>" + ("Lorem ipsum dolor sit amet. " * 40) + "</p>"
        ),
    )

    # The cell key is "html", NOT "text": TableElement._cell() reads
    # raw.get("html") (courses/models.py:885), so normalize_data would rewrite a
    # "text" key to {"html": ""} and every cell would render blank. The width
    # assertion would still pass — .el--table is a block box that fills the column
    # whatever the cells hold — so the seed's wrongness would be invisible to this
    # test and only surface as an empty table in Task 9's screenshot sweep.
    cells = [[{"html": f"r{r}c{c}"} for c in range(4)] for r in range(3)]
    add_element(
        unit, TableElement.objects.create(data={"cells": cells, "border": "grid"})
    )

    return course, unit


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_desktop_tree_collapse_persists(browser, live_server):
    """Toggle collapses tree; class lands on <html>; reload restores; toggle back."""
    _make_student("e2e_nav_collapse")
    course, units = _seed_nav_course("e2e_nav_collapse", "e2e-nav-collapse")
    first_unit = units[0]

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
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

    # Toggle back → expanded. The rail toggle is display:none while collapsed, so
    # the pin is now the only way back — that IS the feature.
    page.locator("[data-unit-tree-pin]").click()
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
    Baseline is the literal current value (courses.css:540-542), not 'same as today'.

    Originally also checked the "childless shape" (a chapter with zero children,
    rendered as a plain <div class="unit-tree__head"> per _unit_tree_node.html's
    else-branch) -- but the unit-publish-state feature's container pruning
    (courses/rollups.py build_outline: `if prune: d["children"] = [k for k in
    d["children"] if k["is_unit"] or k["children"]]`, applied under BOTH "hide"
    and "keep") now drops any group with zero children from its parent's list
    before the template ever sees it, under every viewer. That branch is
    unreachable from a real course structure now, for anyone -- see
    tests/test_unit_nav_render.py::test_a_genuinely_empty_group_is_pruned_not_rendered,
    which pins the absence of `<div class="unit-tree__head"` directly. Keeping a
    dead second iteration here would either hang on the 30s Playwright timeout
    (as it did) or silently pass on stale DOM once xdist ordering coincidentally
    left one around -- neither is a real assertion, so the branch is dropped
    rather than special-cased around the pruning it can no longer survive.
    """
    _make_student("e2e_micro")
    course, _chapters, _units, middle, _sec = _seed_grouped_course(
        "e2e_micro", "e2e-micro"
    )

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_micro")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    locator = rail.locator("details > summary.unit-tree__head").first
    style = locator.evaluate(
        "el => { const s = getComputedStyle(el);"
        " return {tt: s.textTransform, fs: s.fontSize}; }"
    )
    assert style["tt"] == "uppercase", f"lost uppercase ({style['tt']})"
    # .64rem against the 16px root = 10.24px.
    assert abs(float(style["fs"].rstrip("px")) - 10.24) < 0.5, (
        f"font-size drifted ({style['fs']})"
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

    ctx = browser.new_context(
        reduced_motion="reduce", viewport={"width": 1440, "height": 900}
    )
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
    pin = page.locator("[data-unit-tree-pin]")
    toggle.click()  # collapse (real gesture)
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    pin.click()  # expand — the rail toggle is hidden in this state
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
    ctx = browser.new_context(
        reduced_motion="reduce", viewport={"width": 1440, "height": 900}
    )
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
    pin = page.locator("[data-unit-tree-pin]")
    toggle.click()  # collapse (real gesture)
    pin.click()  # expand   (real gesture) -> centerActive() runs
    assert page.evaluate("() => window.__scrollToCalls") == 0, (
        "centerActive() scrolled the rail for an element with no layout box — the "
        "visibility guard is missing, and the rail will jump to a stale-rect position"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_collapsing_removes_the_rail_and_the_pin_is_the_way_back(browser, live_server):
    """The rail LEAVES the layout; the pin is the only route back.

    The leading assertion (pin hidden while expanded) is not padding: omitting the
    base `.unit-toc-pin { display: none }` rule, or writing the reveal unscoped,
    would render the pin permanently — beside an expanded rail, and on mobile beside
    the drawer trigger. Every other test in this set stays green through that, which
    is probably the single most likely CSS mistake in the change.
    """
    _make_student("e2e_pin_back")
    course, units = _seed_nav_course("e2e_pin_back", "e2e-pin-back")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_back")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")

    rail = page.locator("[data-unit-tree]")
    pin = page.locator("[data-unit-tree-pin]")
    toggle = page.locator("[data-unit-tree-toggle]")

    assert rail.is_visible(), "the rail should start expanded"
    assert not pin.is_visible(), (
        "the pin must be hidden while the tree is expanded — its base rule is "
        "display:none and only the collapsed reveal shows it"
    )
    assert toggle.get_attribute("aria-expanded") == "true"
    assert pin.get_attribute("aria-expanded") == "true", (
        "both controls must agree on aria-expanded, including the hidden one"
    )

    toggle.click()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    assert not rail.is_visible(), (
        "the rail must be display:none when collapsed, not a 2.4rem sliver"
    )
    assert pin.is_visible(), "the pin must be the visible way back"
    assert toggle.get_attribute("aria-expanded") == "false"
    assert pin.get_attribute("aria-expanded") == "false"

    pin.click()
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    assert rail.is_visible(), "clicking the pin must restore the rail"
    assert not pin.is_visible(), "the pin must hide again once the rail is back"
    assert toggle.get_attribute("aria-expanded") == "true"
    assert pin.get_attribute("aria-expanded") == "true"

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_collapsed_state_survives_reload_with_the_pin_visible(browser, live_server):
    """Pre-paint restore, plus the FIRST-PAINT half of the aria invariant.

    Only the .unit-tree__toggle assertion can detect a missing boot call: it is
    server-rendered aria-expanded="true", so on a collapsed reload the boot call is
    the only thing that corrects it to "false". The pin's assertion is a same-state
    consistency check — its server-rendered "false" already matches the collapsed
    state, so it stays green with the boot call deleted.
    """
    _make_student("e2e_pin_reload")
    course, units = _seed_nav_course("e2e_pin_reload", "e2e-pin-reload")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_reload")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")

    page.locator("[data-unit-tree-toggle]").click()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    page.reload()

    assert "unit-tree-collapsed" in (page.locator("html").get_attribute("class") or "")
    assert not page.locator("[data-unit-tree]").is_visible()
    assert page.locator("[data-unit-tree-pin]").is_visible()
    # Before any click on the restored page.
    toggle = page.locator("[data-unit-tree-toggle]")
    assert toggle.get_attribute("aria-expanded") == "false"
    pin_el = page.locator("[data-unit-tree-pin]")
    assert pin_el.get_attribute("aria-expanded") == "false"

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_focus_moves_to_the_control_that_becomes_visible(browser, live_server):
    """Whichever control was clicked becomes display:none, so focus must move or
    the browser drops it to <body> and a keyboard user loses their place."""
    _make_student("e2e_pin_focus")
    course, units = _seed_nav_course("e2e_pin_focus", "e2e-pin-focus")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_focus")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")

    page.locator("[data-unit-tree-toggle]").click()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    assert page.evaluate(
        "() => document.activeElement.hasAttribute('data-unit-tree-pin')"
    ), "collapsing must focus the pin"

    # Driven by a REAL Tab, mirroring the proven idiom at
    # tests/test_e2e_unit_nav.py:768-792. Chromium's :focus-visible heuristic does
    # not reliably arm on a programmatic .focus() with no prior keyboard input, so
    # blur first and tab in. Bounded, so a regression fails rather than hangs.
    page.evaluate("() => document.activeElement.blur()")
    for _ in range(200):
        page.keyboard.press("Tab")
        if page.evaluate(
            "() => !!document.activeElement"
            " && document.activeElement.hasAttribute('data-unit-tree-pin')"
        ):
            break
    else:
        raise AssertionError("never reached the pin by tabbing")

    ring = page.evaluate(
        "() => { const s = getComputedStyle("
        "document.querySelector('[data-unit-tree-pin]'));"
        " return {style: s.outlineStyle, offset: s.outlineOffset}; }"
    )
    assert ring["style"] != "none", (
        f"no focus-visible ring on the pin (outline-style={ring['style']!r})"
    )
    assert ring["offset"] not in ("0px", ""), (
        f"the focus ring has no offset ({ring['offset']}) — it merges into the "
        f"button border"
    )

    page.locator("[data-unit-tree-pin]").click()
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    assert page.evaluate(
        "() => document.activeElement.hasAttribute('data-unit-tree-toggle')"
    ), "expanding must focus the rail toggle"

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_pin_is_hidden_at_mobile_width_in_both_states(browser, live_server):
    """At <=640px there is NO clickable control: courses.css hides .unit-tree (so
    the rail toggle is unclickable) and the pin's base rule hides it. So the
    expanded half is taken before any gesture, and the collapsed half is reached by
    collapsing at desktop width and resizing down — which exercises the resize path
    for free. Do not substitute a page.evaluate class flip.
    """
    _make_student("e2e_pin_mobile")
    course, units = _seed_nav_course("e2e_pin_mobile", "e2e-pin-mobile")
    url = f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/"

    ctx = browser.new_context(viewport={"width": 480, "height": 800})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_mobile")
    page.goto(url)
    assert page.locator("[data-unit-tree-pin]").count() == 1, (
        "the pin must exist in the DOM (hidden, not absent) at mobile width"
    )
    assert not page.locator("[data-unit-tree-pin]").is_visible(), (
        "expanded at mobile width: the pin must be hidden"
    )

    page.set_viewport_size({"width": 1440, "height": 900})
    page.locator("[data-unit-tree-toggle]").click()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    page.set_viewport_size({"width": 480, "height": 800})
    assert not page.locator("[data-unit-tree-pin]").is_visible(), (
        "collapsed at mobile width: the pin must still be hidden — the footer "
        "drawer owns contents navigation below 641px"
    )

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_collapsing_reclaims_the_full_rail_width_above_the_breakpoint(
    browser, live_server
):
    """The test for the PURPOSE of the feature.

    Expected delta is ~224px — the full 14rem rail — NOT 262px. The two 38.4px
    quantities cancel: the shell gains 38.4px by overhanging and immediately spends
    38.4px on the pin's lane, so the article column goes 696 -> 920.
    """
    _make_student("e2e_pin_width")
    course, units = _seed_nav_course("e2e_pin_width", "e2e-pin-width")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_width")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")
    assert page.evaluate("() => matchMedia('(min-width: 1040px)').matches") is True

    before = page.evaluate(
        "() => document.querySelector('.lesson').getBoundingClientRect().width"
    )
    _collapse(page)
    after = page.evaluate(
        "() => document.querySelector('.lesson').getBoundingClientRect().width"
    )

    assert abs((after - before) - 224) <= 2, (
        f"expected the column to grow by the full 14rem rail (~224px), got "
        f"{after - before:.1f}px ({before:.1f} -> {after:.1f})"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_narrow_desktop_band_is_width_neutral(browser, live_server):
    """Below 1040px there is no overhang, so the lane sits inside the shell. The
    2.4rem lane exactly equals the sliver it replaces, so this band is neutral
    against today rather than worse.

    The container is derived at RUNTIME rather than hard-coded, so the assertion
    survives any future change to scrollbar behaviour or app-main's padding.

    Measure `.unit-shell` with getBoundingClientRect, NOT `.app-main` with
    getComputedStyle. The shell is the actual containing box of the two flex
    children, so `main == shell - lane` needs no padding arithmetic at all --
    and `box-sizing: border-box` is global here (reset.css:2), which makes
    `getComputedStyle(x).width` ambiguous between the border box and the content
    box. Sidestep the ambiguity rather than reason about it.
    """
    _make_student("e2e_pin_narrow")
    course, units = _seed_nav_course("e2e_pin_narrow", "e2e-pin-narrow")

    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_narrow")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")
    assert page.evaluate("() => matchMedia('(min-width: 1040px)').matches") is False
    assert page.evaluate("() => matchMedia('(min-width: 641px)').matches") is True

    _collapse(page)
    shell = page.evaluate(
        "() => document.querySelector('.unit-shell').getBoundingClientRect().width"
    )
    main = page.evaluate(
        "() => document.querySelector('.unit-shell__main')"
        ".getBoundingClientRect().width"
    )
    assert abs(main - (shell - 38.4)) <= 2, (
        f"expected the main column to be shell-38.4px ({shell - 38.4:.1f}), "
        f"got {main:.1f} — below 1040px the lane sits INSIDE the shell, so the "
        f"column loses exactly one lane and nothing else"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "width,expect_overhang",
    [(1440, True), (1060, True), (1010, False)],
    ids=["wide", "just-above", "just-below"],
)
def test_pin_is_never_clipped_or_offscreen(
    browser, live_server, width, expect_overhang
):
    """1060/1010 rather than 1040/1039: the latter pair puts BOTH cases on the same
    side of the media query once the scrollbar is subtracted, making them identical
    in behaviour while appearing to test both branches. Each case asserts its
    matchMedia value before measuring, so an unusual scrollbar fails loudly.

    The containment assertion is EXACT (left >= 0) — the +/-2px used elsewhere would
    swallow the margins this test measures.
    """
    user = f"e2e_pin_clip_{width}"
    _make_student(user)
    course, units = _seed_nav_course(user, f"e2e-pin-clip-{width}")

    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, user)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")
    assert (
        page.evaluate("() => matchMedia('(min-width: 1040px)').matches")
        is expect_overhang
    ), f"window {width} landed on the wrong side of the 1040px breakpoint"

    _collapse(page)
    rect = page.evaluate(
        "() => { const r = document.querySelector('[data-unit-tree-pin]')"
        ".getBoundingClientRect();"
        " return {l: r.left, t: r.top, w: r.width, h: r.height}; }"
    )
    assert rect["l"] >= 0, f"the pin hangs off the left edge: left={rect['l']:.1f}"
    assert rect["t"] >= 0, f"the pin hangs off the top edge: top={rect['t']:.1f}"

    hit = page.evaluate(
        "() => { const b = document.querySelector('[data-unit-tree-pin]');"
        "const r = b.getBoundingClientRect();"
        "const el = document.elementFromPoint("
        "r.left + r.width / 2, r.top + r.height / 2);"
        "return !!el && b.contains(el); }"
    )
    assert hit, "the pin is not hit-testable at its centre"

    # The assertion that actually guards the no-overflow:hidden precondition.
    # A rect or centre hit-test CANNOT detect it: the pin overhangs 38.4px into
    # .app-main's 20px padding, so under overflow:hidden 20px stays inside the clip
    # and the centre lands ~0.8px on the visible side.
    # body and <html> are walked as a deliberate TRIPWIRE, not because they can clip
    # (body has no margin so its box spans the viewport; the root's overflow
    # propagates to the viewport). A red on those two means "re-check whether this
    # propagates to the viewport", NOT "the pin is clipped".
    clipping = page.evaluate(
        "() => { const out = [];"
        "for (let n = document.querySelector('.unit-shell').parentElement;"
        "     n; n = n.parentElement) {"
        "  const o = getComputedStyle(n).overflowX;"
        "  if (o !== 'visible') out.push(n.tagName + '.' + n.className + ':' + o);"
        "} return out; }"
    )
    assert clipping == [], (
        f"an ancestor of .unit-shell clips overflow-x, which would amputate the "
        f"overhanging pin: {clipping}"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_content_column_aligns_with_the_strip_above_it(browser, live_server):
    """At >=1040px the shell's box starts 38.4px left of the strip, but .unit-shell
    paints nothing and the pin exactly fills that overhang — so the content COLUMN
    lands on the strip's left edge. (The visible prose stays inset a further 24px by
    the article's own padding, unchanged from today; this asserts the column box,
    which is what the negative margin controls.)
    """
    _make_student("e2e_pin_align")
    course, units = _seed_nav_course("e2e_pin_align", "e2e-pin-align")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_align")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")
    assert page.evaluate("() => matchMedia('(min-width: 1040px)').matches") is True

    _collapse(page)
    edges = page.evaluate(
        "() => ({"
        " main: document.querySelector('.unit-shell__main')"
        ".getBoundingClientRect().left,"
        " strip: document.querySelector('.unit-strip').getBoundingClientRect().left,"
        " pin: document.querySelector('[data-unit-tree-pin]')"
        ".getBoundingClientRect().left"
        "})"
    )
    assert abs(edges["main"] - edges["strip"]) <= 1, (
        f"the content column must align with the strip above it: "
        f"main={edges['main']:.1f} strip={edges['strip']:.1f}"
    )
    assert abs((edges["strip"] - edges["pin"]) - 38.4) <= 1, (
        f"the pin must sit exactly one lane left of the strip: "
        f"gap={edges['strip'] - edges['pin']:.1f}, expected 38.4"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_prose_is_capped_while_the_table_takes_the_full_column(browser, live_server):
    """46rem = 736px. Measure the ELEMENT roots, not the enclosing
    <section class="lesson-block"> — that stays 872px either way and would make the
    assertion vacuous.
    """
    _make_student("e2e_pin_cap")
    course, unit = _seed_text_and_table_unit("e2e_pin_cap", "e2e-pin-cap")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_cap")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    _collapse(page)

    text_w = page.evaluate(
        "() => document.querySelector('.el--text').getBoundingClientRect().width"
    )
    table_w = page.evaluate(
        "() => document.querySelector('.el--table').getBoundingClientRect().width"
    )
    assert text_w <= 736 + 2, f"prose must cap at 46rem (736px), got {text_w:.1f}"
    assert table_w > 736 + 2, (
        f"the table must take the full column, got {table_w:.1f} — if this equals "
        f"the prose width the cap has leaked onto wide content"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_quiz_chrome_is_capped_across_both_page_states(browser, live_server):
    """The quiz entries (.lesson-unit__title, [data-quiz-preview-notice],
    .quiz-finish) exist only for _quiz_article.html; without this the whole suite
    stays green if all three are deleted.

    TWO loads with ONE actor. previewing = not enrolled and read_only =
    quiz_submitted or not enrolled, and the finish form sits behind
    {% if not read_only %} — so the banner and the finish form can never coexist.
    The course OWNER satisfies can_access_course without being enrolled, which is
    exactly what makes previewing true while the page still loads; enrolling the
    same user via the ORM and reloading flips to the other state. Do not use two
    users: _login cannot switch identity, because allauth redirects an already
    authenticated visitor away from the login page.
    """
    from courses.models import ShortTextQuestionElement
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import add_element
    from tests.factories import make_quiz_unit

    actor = _make_student("e2e_pin_quiz")
    course = CourseFactory(slug="e2e-pin-quiz", owner=actor)
    unit = make_quiz_unit(course=course)
    q = ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7")
    add_element(unit, q)

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_quiz")
    # The quiz route is /courses/<slug>/u/<node_pk>/quiz/ -- NOT /q/<pk>/.
    url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"

    # Load A — owner, NOT enrolled: banner renders, no finish form.
    page.goto(url)
    _collapse(page)
    assert page.locator("[data-quiz-preview-notice]").count() == 1
    assert page.locator(".quiz-finish").count() == 0
    for sel in (".lesson-unit__title", "[data-quiz-preview-notice]", ".el--question"):
        w = page.evaluate(
            f"() => document.querySelector({sel!r}).getBoundingClientRect().width"
        )
        assert w <= 736 + 2, f"{sel} must cap at 736px, got {w:.1f}"

    # Load B — same session, now enrolled: finish form renders, no banner.
    EnrollmentFactory(course=course, student=actor)
    page.reload()
    # Re-assert the collapsed state AFTER the reload. Every assertion below is
    # one-sided (<= 738), and the EXPANDED quiz column at 1440 is 648px — also
    # under 738 — so without this guard all six would pass while measuring the
    # wrong state. Load A is safe because _collapse() waits on the class; Load B
    # would otherwise rely silently on the pre-paint restore surviving reload.
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    assert page.locator("[data-quiz-preview-notice]").count() == 0
    assert page.locator(".quiz-finish").count() == 1
    for sel in (".lesson-unit__title", ".quiz-finish", ".el--question"):
        w = page.evaluate(
            f"() => document.querySelector({sel!r}).getBoundingClientRect().width"
        )
        assert w <= 736 + 2, f"{sel} must cap at 736px, got {w:.1f}"

    ctx.close()
