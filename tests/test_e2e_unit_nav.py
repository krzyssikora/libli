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


# A title whose max-content width runs well past the 736px prose cap. The <h1>
# sits in .lesson-unit__heading at `flex: 0 1 auto` and shrink-wraps to its own
# content, so ContentNodeFactory's short "Node N" sequence title would leave the
# cap assertions in the quiz-chrome test below passing no matter what the CSS says.
WIDE_TITLE = (
    "Przedzialy liczbowe i dzialania na przedzialach oraz ich zastosowania w zadaniach"
)

TITLE_W_JS = (
    "() => document.querySelector('.lesson-unit__title').getBoundingClientRect().width"
)


def _uncapped_title_width(page):
    """The <h1>'s rendered width with the 46rem prose cap NEUTRALISED, restored after.

    The fixture-validity guard for the cap assertions: it measures the quantity
    that actually decides them -- min(the title's max-content, the heading group's
    own line) -- rather than the head's leftover space, which since the heading
    group exists says nothing about how wide the title wants to be.

    page.add_style_tag returns an ElementHandle and the injected rule does NOT
    expire on its own; left in place it would neutralise the cap for the very
    assertion the guard protects, which is why the removal below is in `finally`
    and why this is called separately before EACH of the two assertions rather
    than once for the whole test.

    `!important` is required, not defensive: the cap selector is
    `html.unit-tree-collapsed [data-unit-shell] .lesson-unit__title`, specificity
    (0,3,1), which a bare `.lesson-unit__title` override at (0,1,0) loses to
    however late it is injected.
    """
    style = page.add_style_tag(
        content=".lesson-unit__title { max-width: none !important; }"
    )
    try:
        return page.evaluate(TITLE_W_JS)
    finally:
        style.evaluate("e => e.remove()")


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
def test_quiz_chrome_tracks_the_column_across_both_page_states(browser, live_server):
    """The quiz entries (.lesson-unit__title, [data-quiz-preview-notice],
    .quiz-finish) exist only for _quiz_article.html; without this the whole suite
    stays green if all three are deleted. The .count() assertions carry that; the
    width assertions carry which of them cap and which fill the column.

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
    # WIDE_TITLE, not the factory's "Node N": the <h1> shrink-wraps inside
    # .lesson-unit__heading, so only a title wider than the cap is held BY the cap,
    # and both title assertions below would otherwise pass vacuously.
    unit = make_quiz_unit(course=course, title=WIDE_TITLE)
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
    column = page.evaluate(
        "() => { const a = document.querySelector('.quiz, .lesson');"
        " const s = getComputedStyle(a);"
        " return a.clientWidth - parseFloat(s.paddingLeft)"
        " - parseFloat(s.paddingRight); }"
    )
    # Fixture-validity guard for the cap assertion that follows. `>= 740`, not
    # `> 736`: the assertion is `<= 738`, so a fixture landing in (736, 738] would
    # clear a `> 736` guard and still leave the assertion green whatever the cap
    # does. The quiz head has no done pill, so the heading group spans the whole
    # ~872 collapsed column and 736 + 12 gap + ~46 chip is comfortably inside it --
    # i.e. the cap, not the group, is the smaller bound. That headroom exists only
    # in the COLLAPSED state, which the assertions above have already established.
    uncapped_w = _uncapped_title_width(page)
    assert uncapped_w >= 740, (
        f"this fixture no longer exercises the cap: with max-width neutralised the "
        f"title measures {uncapped_w:.1f}, at or under 736 plus the assertion's own "
        f"2px slack. Lengthen WIDE_TITLE."
    )
    title_w = page.evaluate(TITLE_W_JS)
    assert title_w <= 736 + 2, (
        f".lesson-unit__title must cap at 736px, got {title_w:.1f} "
        f"(uncapped it measures {uncapped_w:.1f})"
    )
    for sel in ("[data-quiz-preview-notice]", ".el--question"):
        w = page.evaluate(
            f"() => document.querySelector({sel!r}).getBoundingClientRect().width"
        )
        assert abs(w - column) < 2, f"{sel} must fill the column {column}, got {w:.1f}"

    # Load B — same session, now enrolled: finish form renders, no banner.
    EnrollmentFactory(course=course, student=actor)
    page.reload()
    # Re-assert the collapsed state AFTER the reload, explicitly. The title
    # assertion is still one-sided (<= 738), the EXPANDED quiz column at 1440 is
    # 648px — under 738 — and the column-equality assertions compare against
    # whatever column is actually rendered, so they hold expanded too. The
    # uncapped-width guard would now catch an expanded run as collateral (at 648
    # the group leaves the title ~590, under 740), but it would report it as a
    # stale fixture rather than as the wrong page state; this wait says what it
    # means. Load A is safe because _collapse() waits on the class; Load B would
    # otherwise rely silently on the pre-paint restore surviving reload.
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    assert page.locator("[data-quiz-preview-notice]").count() == 0
    assert page.locator(".quiz-finish").count() == 1
    column = page.evaluate(
        "() => { const a = document.querySelector('.quiz, .lesson');"
        " const s = getComputedStyle(a);"
        " return a.clientWidth - parseFloat(s.paddingLeft)"
        " - parseFloat(s.paddingRight); }"
    )
    # The guard again, AFTER the reload -- the injected override was removed with
    # the first measurement, and this page state is a fresh document anyway.
    uncapped_w = _uncapped_title_width(page)
    assert uncapped_w >= 740, (
        f"this fixture no longer exercises the cap in the enrolled state: with "
        f"max-width neutralised the title measures {uncapped_w:.1f}. "
        f"Lengthen WIDE_TITLE."
    )
    title_w = page.evaluate(TITLE_W_JS)
    assert title_w <= 736 + 2, (
        f".lesson-unit__title must cap at 736px, got {title_w:.1f} "
        f"(uncapped it measures {uncapped_w:.1f})"
    )
    for sel in (".quiz-finish", ".el--question"):
        w = page.evaluate(
            f"() => document.querySelector({sel!r}).getBoundingClientRect().width"
        )
        assert abs(w - column) < 2, f"{sel} must fill the column {column}, got {w:.1f}"

    ctx.close()


# ---------------------------------------------------------------------------
# Unit kind markers (spec 2026-08-12) — geometry
#
# Every claim below is DIFFERENTIAL: a position measured with the rule present
# proves nothing, so each assertion is either a comparison between two rendered
# rows or a mechanical A/B via page.add_style_tag.
# ---------------------------------------------------------------------------

# Deliberately tiny: the rail-gutter guard needs the label's max-content to sit
# well under the row's content width (a long title fills the row through the
# ellipsis clip and the marker lands flush on the reverted build too), and the
# desktop short-title arm needs the <h1> under ~150px.
SHORT_TITLE = "Wstep"
QUIZ_TITLE = "Test A"
# ONE unbroken token, measured (not derived) wider than the 390px outline title
# column. A multi-word long title wraps at spaces under `overflow-wrap: normal`
# too, which would leave the outline mutant green.
UNBROKEN_TITLE = "Nieprzyporzadkowywalnosciowoscioniezmiennikowosciowoscia"

# Max-content width of an element's TEXT, measured with an off-screen nowrap
# probe carrying the element's own font metrics. Used only by fixture-validity
# guards, and only on plain-text titles: a KaTeX title would not measure this
# way. It reads the quantity the guards actually care about -- how wide the text
# WANTS to be -- which neither getBoundingClientRect (already flexed) nor
# scrollWidth (clamped to clientWidth whenever the box is the wider of the two)
# can report.
MAX_CONTENT_JS = """
(el) => {
  const cs = getComputedStyle(el);
  const p = document.createElement('span');
  p.textContent = el.textContent;
  p.style.position = 'absolute';
  p.style.left = '-9999px';
  p.style.top = '0';
  p.style.whiteSpace = 'pre';
  p.style.fontFamily = cs.fontFamily;
  p.style.fontSize = cs.fontSize;
  p.style.fontWeight = cs.fontWeight;
  p.style.fontStyle = cs.fontStyle;
  p.style.letterSpacing = cs.letterSpacing;
  document.body.appendChild(p);
  const w = p.getBoundingClientRect().width;
  p.remove();
  return w;
}
"""

# The heading group, its <h1>, its chip and the head's completion pill, as plain
# rects. `.unit-done` is the head's actual flex item -- NOT `.unit-done__pill`,
# which on a not-completed fixture is a <button> wrapped in a <form>.
HEAD_BOXES_JS = """
() => {
  const r = e => e ? e.getBoundingClientRect().toJSON() : null;
  const g = document.querySelector('.lesson-unit__heading');
  return {
    group: r(g),
    title: r(g && g.querySelector('.lesson-unit__title')),
    chip: r(g && g.querySelector('.unit-kind-chip')),
    done: r(document.querySelector('.unit-done')),
  };
}
"""


def _seed_marked_group(username, *, slug):
    """A course whose one chapter holds FIVE marked units plus one completion.

    The chapter is the current unit's ancestor, so its <details> renders `open`
    (_unit_tree_node.html sets open only on contains_current) and every row is
    measurable. obligatory=False is explicit everywhere: the model default is True
    and a default-factory unit renders no marker, making every assertion vacuous.

    long_unit is ALSO marked completed (UnitProgressFactory(student=user,
    unit=long_unit, completed=True)) so `.unit-tree__check` renders for the
    completed-row arm -- that tick is behind {% if item.completed %}
    (_unit_tree_node.html:10) and nothing else in this seed produces one.
    Deliberately NOT short_unit: a leading tick eats row width, and short_unit is
    the row whose >=20px free-space guard the rail-gutter arm depends on.

    Returns (user, course, chapter, short_unit, long_unit, quiz_unit, maths_unit,
    token_unit) -- five marked units, because three arms need title shapes the
    others cannot supply:
      * short_unit  -- measurably narrower than the rail row's content box, and an
                       <h1> under ~150px on the desktop unit page.
      * long_unit   -- WIDE_TITLE: multi-word and already proven to measure >= 740
                       as an uncapped <h1> (see test_quiz_chrome_...), which is
                       what makes 736 + 12 + ~78 > the ~756px group line and lets
                       the cap-length row see a `flex-wrap: wrap` mutant.
      * quiz_unit   -- the quiz-side unit-page arms.
      * maths_unit  -- capture_title_math_screenshots.TITLES["long"], the long
                       maths title the existing audit actually measured. NOT
                       helpers_title_math.MATHS_TITLE, which is short, comes from
                       a different module, and may not even wrap in the drawer
                       column.
      * token_unit  -- one unbroken token wider than the 390px outline title
                       column.

    None of this file's other seeds can stand in: _seed_traversal_course,
    _seed_nav_course, _seed_grouped_course and _seed_text_and_table_unit all build
    default-obligatory lessons, which emit no marker at all.
    """
    from django.contrib.auth import get_user_model

    from tests.capture_title_math_screenshots import TITLES
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import UnitProgressFactory

    user = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=user)
    EnrollmentFactory(student=user, course=course)
    chapter = ContentNodeFactory(
        course=course,
        kind="chapter",
        parent=None,
        unit_type=None,
        title="Marked chapter",
    )

    def _unit(title, **kw):
        kw.setdefault("unit_type", "lesson")
        # Explicit, never inherited: ContentNode.obligatory defaults to True and
        # ContentNodeFactory does not set it, so an omitted kwarg silently renders
        # an UNMARKED row and every assertion in this section goes vacuous.
        kw.setdefault("obligatory", False)
        return ContentNodeFactory(
            course=course, kind="unit", parent=chapter, title=title, **kw
        )

    short_unit = _unit(SHORT_TITLE)
    long_unit = _unit(WIDE_TITLE)
    quiz_unit = _unit(QUIZ_TITLE, unit_type="quiz")
    maths_unit = _unit(TITLES["long"])
    token_unit = _unit(UNBROKEN_TITLE)

    UnitProgressFactory(student=user, unit=long_unit, completed=True)

    return (
        user,
        course,
        chapter,
        short_unit,
        long_unit,
        quiz_unit,
        maths_unit,
        token_unit,
    )


def _row(page, scope, pk):
    """The tree row for `pk` inside `scope` ([data-unit-tree-list] or
    [data-unit-drawer-list]). The page renders the tree TWICE -- rail and drawer --
    so an unscoped `.unit-tree__unit` locator is a Playwright strict-mode
    violation, not merely ambiguous."""
    return page.locator(f"{scope} a.unit-tree__unit[href$='/u/{pk}/']")


def _open_drawer(page):
    """Click the footer Contents trigger and wait for [hidden] to come off.

    courses.css gives .unit-drawer display:none at base and reveals it only inside
    @media (max-width: 640px), via .unit-drawer:not([hidden]). Both are named by
    selector rather than by line: they sit below every marker insertion this
    branch made, so a numeral here rots on the next one (it already did, twice).
    It carries a literal `hidden` attribute until unit_nav.js responds to the
    trigger, so nothing inside it has a box before this runs.
    """
    page.locator("[data-unit-drawer-open]").click()
    page.wait_for_selector("[data-unit-drawer]:not([hidden])")


@pytest.mark.django_db(transaction=True)
def test_rail_kind_markers_share_the_right_hand_gutter(browser, live_server):
    """.unit-tree__label's flex-grow is what puts every marker in one gutter.

    Compare `right`, NOT `x`: x is the wrapper's LEFT edge and the wrapper is only
    ~13px wide at the rail's .82rem, so "x is near the row's right content edge"
    is red on a correct build.
    """
    _make_student("e2e_kind_rail")
    _u, course, _ch, short_unit, long_unit, _q, _m, _t = _seed_marked_group(
        "e2e_kind_rail", slug="e2e-kind-rail"
    )

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2e_kind_rail")
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{short_unit.pk}/")

        short_row = _row(page, "[data-unit-tree-list]", short_unit.pk)
        long_row = _row(page, "[data-unit-tree-list]", long_unit.pk)

        # Fixture-validity guard, FIRST. .unit-tree__label already carries
        # overflow:hidden + text-overflow:ellipsis, so a title whose max-content
        # exceeds the row still fills it on the REVERTED build and its marker still
        # lands flush -- with two long titles both assertions below stay green with
        # flex-grow removed. The short row must have real slack.
        content_w = short_row.evaluate(
            "el => { const cs = getComputedStyle(el);"
            " return el.clientWidth - parseFloat(cs.paddingLeft)"
            "        - parseFloat(cs.paddingRight); }"
        )
        natural_w = short_row.locator(".unit-tree__label").evaluate(MAX_CONTENT_JS)
        assert content_w - natural_w >= 20, (
            f"the short row has only {content_w - natural_w:.1f}px of slack "
            f"(label wants {natural_w:.1f}, row content is {content_w:.1f}) -- with a "
            f"title this wide the ellipsis clip fills the row on the reverted build "
            f"too and neither assertion below can go red. Shorten SHORT_TITLE."
        )

        short_kind = short_row.locator(".unit-kind").bounding_box()
        long_kind = long_row.locator(".unit-kind").bounding_box()
        short_box = short_row.bounding_box()
        assert short_kind and long_kind and short_box, (
            "both marked rows must render a .unit-kind -- an unmarked seed makes "
            "every assertion here vacuous"
        )
        short_right = short_kind["x"] + short_kind["width"]
        long_right = long_kind["x"] + long_kind["width"]
        row_right = short_box["x"] + short_box["width"]

        assert abs(short_right - long_right) <= 1, (
            f"markers on a short and a long row do not share a gutter: "
            f"{short_right:.1f} vs {long_right:.1f} -- .unit-tree__label must keep "
            f"flex-grow so a short title still fills the row"
        )
        # .unit-tree__unit's padding is .3rem .5rem (courses.css:766) and it has no
        # right border, so the content edge is exactly right - 8.
        assert abs(short_right - (row_right - 8)) <= 1, (
            f"the marker does not sit in the row's right-hand gutter: marker right "
            f"{short_right:.1f}, row content edge {row_right - 8:.1f}"
        )

        # Still HIDDEN in the rail. Without this an un-hide rule placed OUTSIDE the
        # @media (max-width: 640px) block passes every other assertion in this file
        # while eating ~58px of the rail's ~98px title column. The numeric bound is
        # the point: .visually-hidden renders 1px x 1px with a zero clip rect, which
        # Playwright reports as VISIBLE with a non-empty box.
        sizes = page.eval_on_selector_all(
            "[data-unit-tree-list] .unit-kind__label",
            "els => els.map(e => { const r = e.getBoundingClientRect();"
            " return [r.width, r.height]; })",
        )
        assert sizes, (
            "no .unit-kind__label in the rail -- the seed rendered no markers and "
            "this assertion is vacuous"
        )
        # Each dimension independently, NOT the largest area: a 60x0 box has zero
        # area and would win no area comparison while still proving the label is
        # laid out.
        widest = max(w for w, _h in sizes)
        tallest = max(h for _w, h in sizes)
        assert widest <= 2 and tallest <= 2, (
            f"a rail marker's word is rendered (worst {widest:.1f} wide, "
            f"{tallest:.1f} tall) -- the un-hide rule must stay scoped to "
            f".unit-drawer__list AND inside the <=640px media query"
        )
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("collapsed", [False, True], ids=["expanded", "collapsed"])
def test_desktop_lesson_head_keeps_the_chip_and_the_pill_in_place(
    browser, live_server, collapsed
):
    """The .lesson-unit__heading > .lesson-unit__title reset and the group's own
    flex, on the SHORT-title row.

    Both must sit on the short-title row: with a cap-length title the group's base
    (736 + 12 + ~78 = 826) already exceeds the ~756px line, free space is zero,
    space-between degenerates to flex-start, and the pill assertion holds on the
    broken build too.
    """
    user = f"e2e_kind_head_{int(collapsed)}"
    _make_student(user)
    _u, course, _ch, short_unit, _l, _q, _m, _t = _seed_marked_group(
        user, slug=f"e2e-kind-head-{int(collapsed)}"
    )

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        _login(page, live_server, user)
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{short_unit.pk}/")
        if collapsed:
            _collapse(page)

        b = page.evaluate(HEAD_BOXES_JS)
        assert b["chip"] is not None, "the marked unit rendered no chip"
        assert b["done"] is not None, "the lesson head must render .unit-done"

        # Fixture-validity guard, FIRST. The 200px bound below is red on a CORRECT
        # build once the heading passes ~188px, so the fixture has to stay short.
        # MAX-CONTENT, not the rendered width: on the reverted build the <h1> grows
        # to absorb the group, so a rendered-width guard fires FIRST and reports the
        # missing reset as "shorten SHORT_TITLE" -- it would swallow the assertion
        # this arm exists for. Max-content is the fixture property and is identical
        # on both builds.
        title_w = page.locator(".lesson-unit__title").evaluate(MAX_CONTENT_JS)
        assert title_w < 150, (
            f"the <h1>'s own text measures {title_w:.1f}px -- this fixture no longer "
            f"exercises the reset; the 200px bound below would be red on a correct "
            f"build. Shorten SHORT_TITLE."
        )

        # Written as an absolute bound, NOT as `chip.left == title.right + gap`:
        # adjacency is invariant across both builds, since without the reset the
        # <h1> merely grows and the chip still sits one gap past its right edge.
        offset = b["chip"]["left"] - b["group"]["left"]
        assert offset < 200, (
            f"the chip sits {offset:.1f}px into the heading group -- without "
            f"`.lesson-unit__heading > .lesson-unit__title {{ flex: 0 1 auto }}` the "
            f"<h1> inherits flex:1 1 0% from .lesson-unit__head and absorbs the group"
        )

        # The head's gap is 1rem (courses.css:837). With the group at flex:1 1 auto
        # there is no free space, so space-between puts the pill exactly one gap past
        # the group; with the group shrink-wrapped it flies to the column's far right.
        gap = b["done"]["left"] - b["group"]["right"]
        assert abs(gap - 16) <= 1, (
            f"the completion pill sits {gap:.1f}px past the heading group, expected "
            f"the head's 1rem gap -- .lesson-unit__heading must keep flex: 1 1 auto"
        )
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("collapsed", [False, True], ids=["expanded", "collapsed"])
def test_desktop_quiz_head_keeps_the_chip_beside_the_title(
    browser, live_server, collapsed
):
    """The same reset on the OTHER article template. _quiz_article.html has no
    .unit-done, so the heading group spans the whole column and a missing reset is
    even more visible -- but nothing else in the suite renders this template with a
    chip."""
    user = f"e2e_kind_qhead_{int(collapsed)}"
    _make_student(user)
    _u, course, _ch, _s, _l, quiz_unit, _m, _t = _seed_marked_group(
        user, slug=f"e2e-kind-qhead-{int(collapsed)}"
    )

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        _login(page, live_server, user)
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{quiz_unit.pk}/quiz/")
        if collapsed:
            _collapse(page)

        b = page.evaluate(HEAD_BOXES_JS)
        assert b["chip"] is not None, "the quiz unit rendered no chip"
        assert b["done"] is None, (
            "the quiz head is not supposed to carry .unit-done; if it now does, the "
            "group's line changes and this arm's bound needs re-deriving"
        )
        # MAX-CONTENT, not the rendered width -- see the lesson arm's note: a
        # rendered-width guard fires first on the reverted build and swallows the
        # assertion below.
        title_w = page.locator(".lesson-unit__title").evaluate(MAX_CONTENT_JS)
        assert title_w < 150, (
            f"the <h1>'s own text measures {title_w:.1f}px -- this fixture no longer "
            f"exercises the reset. Shorten QUIZ_TITLE."
        )
        offset = b["chip"]["left"] - b["group"]["left"]
        assert offset < 200, (
            f"the chip sits {offset:.1f}px into the heading group -- the <h1> is "
            f"absorbing the group, so the reset is missing on the quiz template"
        )
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_desktop_cap_length_title_keeps_the_chip_on_the_title_line(
    browser, live_server
):
    """A title at the 736px prose cap must NOT push the chip onto its own line.

    Collapsed only, via the file's _collapse(): the 736px cap applies ONLY in that
    state, so a cap-length assertion is meaningless anywhere else.

    Deliberately NOT `chip.top ~= title.top`: align-items: baseline makes the two
    tops differ by ~10-15px on a correct build. And this row gets no chip-position
    or chip-width assertion -- both builds put chip.left at group.left + 668, and a
    flex: 0 1 auto chip's shrink target is a min violation so it freezes at its
    full width either way.
    """
    _make_student("e2e_kind_cap")
    _u, course, _ch, _s, long_unit, _q, _m, _t = _seed_marked_group(
        "e2e_kind_cap", slug="e2e-kind-cap"
    )

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2e_kind_cap")
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{long_unit.pk}/")
        _collapse(page)

        # Fixture-validity guard, FIRST. Deliberately NOT _uncapped_title_width():
        # that helper neutralises only `max-width`, so on the LESSON head the <h1>
        # is still a flex item shrinking against the completion pill and it reports
        # min(max-content, the group's line) -- ~667px here. That is the quantity
        # the quiz-chrome test wants (a quiz head has no pill, so its group spans
        # the whole column and the cap really is the smaller bound); it is not the
        # quantity this arm needs. Measure the <h1>'s true max-content instead.
        # >= 740, not > 736, is the same bound Task 5's repair uses.
        max_content = page.locator(".lesson-unit__title").evaluate(MAX_CONTENT_JS)
        assert max_content >= 740, (
            f"this fixture no longer reaches the cap: the <h1>'s max-content is "
            f"{max_content:.1f}px, at or under 736 plus slack. Lengthen WIDE_TITLE."
        )

        b = page.evaluate(HEAD_BOXES_JS)
        assert b["chip"] is not None, "the marked unit rendered no chip"
        # The second half of the guard, and the precondition the `flex-wrap: wrap`
        # mutant needs: the <h1>'s flex BASE (max-content clamped by the 736px cap)
        # plus the 12px --space-3 gap plus the chip must overflow the group's line.
        # If they fitted, adding flex-wrap would change nothing and this assertion
        # could never go red.
        base_line = min(max_content, 736) + 12 + b["chip"]["width"]
        assert base_line > b["group"]["width"] + 1, (
            f"the heading group's line ({b['group']['width']:.1f}px) still fits the "
            f"capped title plus gap plus chip ({base_line:.1f}px) — a wrap mutant "
            f"would be invisible here"
        )
        assert b["chip"]["top"] < b["title"]["bottom"] - 1, (
            f"the chip wrapped below the title (chip top {b['chip']['top']:.1f}, "
            f"title bottom {b['title']['bottom']:.1f}) -- .lesson-unit__heading must "
            f"NOT wrap at desktop: 736 + 12 + ~78 exceeds the ~756px group line"
        )
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_drawer_marker_shows_its_word_and_keeps_its_box(browser, live_server):
    """The mobile drawer: the marker's word is revealed, the wrapper keeps its box,
    the glyph-to-word gap survives, and a long maths title never reaches it.

    NOTE ON TEARDOWN: the only page.add_style_tag in this test is the LAST
    measurement performed, and its handle is removed in a `finally` regardless --
    the injected `!important` rule does not expire on its own and it moves the
    marker, so leaving it would corrupt every earlier assertion if the order ever
    changed.
    """
    _make_student("e2e_kind_drawer")
    _u, course, _ch, short_unit, long_unit, _q, _m, _t = _seed_marked_group(
        "e2e_kind_drawer", slug="e2e-kind-drawer"
    )

    ctx = browser.new_context(viewport={"width": 390, "height": 780})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2e_kind_drawer")
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{short_unit.pk}/")
        _open_drawer(page)

        scope = "[data-unit-drawer-list]"
        # Every marker assertion below runs on the LONG-title row, not the short
        # one. The drawer label is `flex: 1 1 auto` with a max-content basis, so a
        # short title leaves the row in SURPLUS: the label simply grows, nothing
        # shrinks, and a `.unit-drawer__list .unit-kind { flex: 0 1 auto;
        # min-width: 0 }` mutant is invisible. Only a title whose max-content runs
        # the row into a large deficit makes the marker's flex: none load-bearing.
        row = _row(page, scope, long_unit.pk)
        parts = row.evaluate(
            "el => { const r = e => e ? e.getBoundingClientRect().toJSON() : null;"
            " const k = el.querySelector('.unit-kind');"
            " return {row: r(el), kind: r(k), label: r(el.querySelector("
            "'.unit-kind__label')), svg: r(k && k.querySelector('svg.icon')),"
            " title: r(el.querySelector('.unit-tree__label')),"
            " check: r(el.querySelector('.unit-tree__check'))}; }"
        )
        assert parts["kind"] and parts["label"] and parts["svg"], (
            "the drawer row rendered no marker -- an unmarked seed makes every "
            "assertion in this test vacuous"
        )
        # Fixture-validity guard for the differential assertion below: the row must
        # really be in deficit, i.e. the title's max-content must exceed the space
        # the row can give it. Without this the marker is never asked to shrink.
        row_content = row.evaluate(
            "el => { const cs = getComputedStyle(el);"
            " return el.clientWidth - parseFloat(cs.paddingLeft)"
            "        - parseFloat(cs.paddingRight); }"
        )
        title_max = row.locator(".unit-tree__label").evaluate(MAX_CONTENT_JS)
        assert title_max > row_content, (
            f"the drawer row is not in deficit (title max-content {title_max:.1f} vs "
            f"{row_content:.1f}px of row) — nothing shrinks, so a shrinkable-marker "
            f"mutant would be invisible. Lengthen WIDE_TITLE."
        )

        # The word is REALLY shown. The numeric thresholds are the point:
        # .visually-hidden is 1px x 1px with a zero clip rect, which Playwright
        # reports as visible with a non-empty box -- so `bounding_box() is not None`
        # can distinguish neither a still-hidden label nor a PARTIAL revert
        # (position: static alone leaves a 1x1 clipped span).
        assert parts["label"]["width"] >= 30 and parts["label"]["height"] >= 8, (
            f"the drawer marker's word measures "
            f"{parts['label']['width']:.1f}x{parts['label']['height']:.1f} -- all six "
            f"of .visually-hidden's declarations must be reset, not just `position`"
        )

        # Differential, so no font metric is hardcoded: under a shrinkable-marker
        # mutant the children keep their sizes while the wrapper is cut below its
        # min-content, so they spill out of it. An absolute "~91px +/- 1" would be
        # a guess at a word width and would likely be red on a correct build.
        assert parts["label"]["right"] <= parts["kind"]["right"] + 1, (
            f"the marker's word overflows its own wrapper (label right "
            f"{parts['label']['right']:.1f} vs marker right "
            f"{parts['kind']['right']:.1f}) -- .unit-drawer__list .unit-kind must not "
            f"be made shrinkable"
        )

        # gap: var(--space-1) on .unit-kind. A flex container drops whitespace-only
        # text between items, so deleting the gap takes this cleanly to 0.
        #
        # THE CORRECT-BUILD VALUE IS 3.0, NOT 4.0, and the band's lower edge is
        # therefore where a correct build SITS -- it is not slack. `.visually-hidden`
        # is declared THREE times: app.css defines the six declarations the drawer
        # un-hide resets, but notes/static/notes/css/notes.css:4 and
        # tags/static/tags/css/tags.css:6 redeclare it with `margin: -1px`, and both
        # load AFTER courses.css, so the -1px left margin survives the un-hide and
        # eats 1px of the gap. MEASURED, not reasoned: Task 7's gap mutant (delete
        # `gap` from .unit-kind) read label.left - svg.right = -1.0, not 0.
        # The band still discriminates: correct 3.0 vs mutant -1.0 is a clean 4px
        # delta, and 3.0 clears `abs(g - 4) <= 1` exactly at its lower edge. Left
        # as-is deliberately -- this comment exists so that edge is read as the
        # correct build's own value and not as slack to be spent. Do NOT widen it.
        glyph_gap = parts["label"]["left"] - parts["svg"]["right"]
        assert abs(glyph_gap - 4) <= 1, (
            f"glyph-to-word gap is {glyph_gap:.1f}px, expected --space-1 (4px) on "
            f".unit-kind less the 1px left margin notes.css/tags.css leave on "
            f".visually-hidden, i.e. ~3.0px"
        )

        # Containment. Holds on BOTH builds (after a shrink the row still has zero
        # free space and the marker still ends at the padding edge), so it carries no
        # mutant -- the differential assertion above is the discriminating one.
        assert parts["kind"]["right"] <= parts["row"]["right"] - 8 + 1, (
            f"the marker escapes the row's .5rem padding edge: "
            f"{parts['kind']['right']:.1f} vs {parts['row']['right'] - 8:.1f}"
        )

        # STANDING TRIPWIRE — carries no mutant. It guards a FIGURE, not a rule:
        # courses.css's maths-surface note records the drawer's title column as
        # 209.7px, measured here (390x780, a squeezed row: long title + completion
        # tick + marker; 238.5px on a short marked row). Before that it wrongly
        # quoted the RAIL's ~98px, and the drawer panel is left:0;right:0, so the
        # two differ by more than 2x.
        #
        # 120 is not arbitrary and is not a layout requirement: it sits roughly
        # midway between the rail's 98 and the measured 209.7, so it fires only if
        # the drawer column ever regresses toward rail width -- i.e. exactly when
        # the recorded figure would have gone wrong again. No CSS change under test
        # moves this number, which is why it carries no mutant.
        squeezed_w = parts["title"]["width"]
        assert squeezed_w > 120, (
            f"the drawer title column measured {squeezed_w:.1f}px -- if it really "
            f"has narrowed toward the rail's ~98px, courses.css's maths note needs "
            f"re-measuring, not this bound relaxing"
        )

        # Row shape for this same COMPLETED additional unit: one flex line, tick +
        # label + marker sharing a top (.unit-drawer__list .unit-tree__unit is
        # align-items: flex-start, so a wrapped label hangs them all from the top).
        tops = {
            "check": parts["check"] and parts["check"]["top"],
            "label": parts["title"] and parts["title"]["top"],
            "kind": parts["kind"]["top"],
        }
        assert None not in tops.values(), (
            f"the completed additional row is missing a part: {tops} -- the seed must "
            f"mark long_unit completed AND obligatory=False"
        )
        spread = max(tops.values()) - min(tops.values())
        assert spread <= 6, (
            f"the completed additional row is not one flex line: tops {tops} spread "
            f"over {spread:.1f}px"
        )

        # Maths re-check. The original audit measured .katex only against controls
        # that LEAD a unit row or live on group rows, so it carries no evidence for a
        # right-hand neighbour. Expected outcome: NO intersection. If it DOES
        # intersect that is a design change (containment on the drawer label's maths,
        # or moving the marker) -- do not widen the tolerance.
        page.wait_for_selector(f"{scope} .katex", state="attached")
        assert page.locator(f"{scope} .unit-kind").first.bounding_box() is not None, (
            "no drawer marker has a box -- the intersection loop below would be "
            "vacuous, and an empty list is the DEFAULT outcome for an unmarked seed"
        )
        maths = page.evaluate(
            """(sel) => {
                 const s = document.querySelector(sel);
                 const box = e => e.getBoundingClientRect();
                 const marks = [...s.querySelectorAll('.unit-kind')].map(box)
                   .filter(r => r.width > 0 && r.height > 0);
                 const katex = [...s.querySelectorAll('.katex')].map(box)
                   .filter(r => r.width > 0 && r.height > 0);
                 const hits = [];
                 for (const m of katex) for (const k of marks) {
                   if (m.left < k.right && m.right > k.left &&
                       m.top < k.bottom && m.bottom > k.top) {
                     hits.push([m.left, m.top, m.right, m.bottom,
                                k.left, k.top, k.right, k.bottom]);
                   }
                 }
                 return {marks: marks.length, katex: katex.length, hits: hits};
               }""",
            scope,
        )
        assert maths["marks"] > 0, "no laid-out .unit-kind in the drawer"
        assert maths["katex"] > 0, (
            "no laid-out .katex in the drawer -- maths_unit's title did not typeset "
            "and the intersection loop is vacuous"
        )
        assert maths["hits"] == [], (
            f"a .katex box in a drawer title overlaps a .unit-kind marker: "
            f"{maths['hits']} -- this is a DESIGN change, not a tolerance to widen"
        )

        # LAST assertion on this page, and the only add_style_tag here. A/B the
        # drawer label's wrap points against the PRE-CHANGE computed value. It has to
        # be named explicitly: add_style_tag can only ADD a declaration, and
        # `flex: none` / `flex: 1 1 0` would change the label's base size and redden
        # a correct build.
        label = _row(page, scope, long_unit.pk).locator(".unit-tree__label")
        before = label.evaluate("el => el.getBoundingClientRect().height")
        style = page.add_style_tag(
            content=".unit-drawer__list .unit-tree__label"
            " { flex: 0 1 auto !important; }"
        )
        try:
            after = label.evaluate("el => el.getBoundingClientRect().height")
        finally:
            style.evaluate("e => e.remove()")
        assert abs(after - before) <= 1, (
            f"giving the drawer label flex-grow moved its wrap points: "
            f"{before:.1f} -> {after:.1f}px tall"
        )
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_phone_unit_head_drops_the_chip_under_the_title(browser, live_server):
    """The SOLE pin for the mobile .lesson-unit__heading rule.

    test_e2e_unit_head_layout.py structurally cannot cover it -- its fixture
    renders no chip at all. At 390px the <h1> keeps flex-basis: 100% -- from
    `.lesson-unit__head .lesson-unit__title` inside courses.css's 640px query,
    named by selector because a numeral there rots on every insertion above it --
    the group wraps, and the chip starts a fresh flex line at the group's
    content-box left under the default justify-content: flex-start (the group has
    no padding). Both assertions are exact, not "near".
    """
    _make_student("e2e_kind_phead")
    _u, course, _ch, short_unit, _l, _q, _m, _t = _seed_marked_group(
        "e2e_kind_phead", slug="e2e-kind-phead"
    )

    ctx = browser.new_context(viewport={"width": 390, "height": 780})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2e_kind_phead")
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{short_unit.pk}/")

        b = page.evaluate(HEAD_BOXES_JS)
        assert b["chip"] is not None, "the marked unit rendered no chip"
        assert b["chip"]["top"] >= b["title"]["bottom"] - 1, (
            f"the chip stayed on the title's line at 390px (chip top "
            f"{b['chip']['top']:.1f}, title bottom {b['title']['bottom']:.1f}) -- "
            f"the mobile `.lesson-unit__heading {{ flex-basis: 100%; "
            f"flex-wrap: wrap }}` rule is missing"
        )
        assert abs(b["chip"]["left"] - b["group"]["left"]) <= 1, (
            f"the chip does not start a fresh flex line at the group's left edge: "
            f"chip {b['chip']['left']:.1f} vs group {b['group']['left']:.1f}"
        )
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_outline_marked_row_does_not_overflow_at_phone_width(browser, live_server):
    """The chip can add ~90px to a 390px outline row, so the title column must be
    able to break an unbreakable token. A multi-word long title wraps at spaces
    under `overflow-wrap: normal` too, which is why this drives token_unit."""
    _make_student("e2e_kind_outline")
    _u, course, _ch, _s, _l, _q, _m, token_unit = _seed_marked_group(
        "e2e_kind_outline", slug="e2e-kind-outline"
    )

    ctx = browser.new_context(viewport={"width": 390, "height": 780})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2e_kind_outline")
        page.goto(f"{live_server.url}/courses/{course.slug}/")

        li = page.locator(f"#node-{token_unit.pk}")
        title = li.locator(".outline-unit__title")
        assert li.locator(".unit-kind-chip").count() == 1, (
            "the outline row rendered no kind chip -- the seed is unmarked and the "
            "squeeze this arm measures does not exist"
        )

        # Fixture-validity guard, FIRST: the token is MEASURED wider than the
        # rendered title column, not derived from a character count.
        column = title.evaluate("el => el.clientWidth")
        token = title.evaluate(MAX_CONTENT_JS)
        assert token > column + 20, (
            f"the title's single token measures {token:.1f}px against a "
            f"{column:.1f}px column -- it no longer overflows, so `overflow-wrap` "
            f"has nothing to break. Lengthen UNBROKEN_TITLE."
        )

        overflow = title.evaluate("el => el.scrollWidth - el.clientWidth")
        assert overflow <= 1, (
            f".outline-unit__title overflows its own box by {overflow:.1f}px -- "
            f"`overflow-wrap: anywhere` must stay on it"
        )

        edges = page.evaluate(
            "(pk) => { const li = document.getElementById('node-' + pk);"
            " return {li: li.getBoundingClientRect().right,"
            " unit: li.querySelector('.outline-unit').getBoundingClientRect().right};"
            " }",
            token_unit.pk,
        )
        # STANDING TRIPWIRE — carries no mutant. The <li> is the row's own flex
        # container, so the row cannot exceed it under either build; this exists to
        # catch a future change that lets it, not to discriminate this one. The
        # scrollWidth assertion above is the discriminating check.
        assert edges["unit"] <= edges["li"] + 1, (
            f"the unit row escapes its <li>: {edges['unit']:.1f} vs {edges['li']:.1f}"
        )

        # STANDING TRIPWIRE — carries no mutant, for the same reason. NOT because
        # the title clips: .outline-unit__title carries no `overflow` declaration,
        # so an atom too wide for the title column is PAINTED OVER its neighbour
        # rather than truncated — that is exactly the 25.1px residual recorded in
        # the maths-audit comment in courses.css (the .outline-unit__title /
        # .unit-kind-chip "fifth surface"). It stays inside the row's own box, so
        # removing `overflow-wrap` reddens the scrollWidth assertion above without
        # ever reaching the document edge. This
        # is here for the wider class of regression (any marked row pushing the
        # page into horizontal scroll at phone width), not for the rule under test.
        page_overflow = page.evaluate(
            "() => document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth"
        )
        assert page_overflow <= 0, (
            f"the outline page scrolls horizontally by {page_overflow}px at 390 wide"
        )
    finally:
        ctx.close()
