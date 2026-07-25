"""Playwright e2e for the student unit-page breadcrumbs.

The CSS *is* the feature here, so these are the tests that actually protect it.
Three viewports, because 360px and 1280px alone never exercise the state where mids
are visible but squeezed: at 360px they are hidden and at 1280px there is room to
spare. The worst case sits just above the collapse breakpoint, where the 14rem rail
is still present and the column is at its narrowest for four uncollapsed crumbs.

Marked e2e (excluded from the default run). Run focused and in the FOREGROUND — a
background `-m e2e` sweep spawns runaway browsers.
"""

import os

import pytest

from courses.rollups import HIDDEN_PATH_SEP
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_verified_user
from tests.test_unit_nav_render import COLLAPSE_BREAKPOINT_PX

pytestmark = pytest.mark.e2e

NARROW = 360
SQUEEZED = COLLAPSE_BREAKPOINT_PX + 1
WIDE = 1280
ALL_WIDTHS = (NARROW, SQUEEZED, WIDE)


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py — it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_crumb_course(username):
    """course → part → chapter → section → unit, ~60-char titles at every level.

    A new helper rather than an extension of test_e2e_unit_nav._seed_nav_course:
    that one builds a single part with unit children, so it can never yield three
    ancestors. CourseFactory's default title is a factory.Sequence, hence the
    explicit title=.

    Long titles are not decoration — both falsifying mutations below are only
    detectable when the content actually exceeds the column.
    """
    student = _make_student(username)
    long_ = "Sequences Series And Their Convergence Criteria In Depth"  # 56 chars
    course = CourseFactory(title=f"Advanced {long_}", owner=student)
    EnrollmentFactory(student=student, course=course)
    parent = None
    for kind in ("part", "chapter", "section"):
        parent = ContentNodeFactory(
            course=course,
            kind=kind,
            parent=parent,
            unit_type=None,
            title=f"{kind.title()} {long_}",
        )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=parent, title="Unit One"
    )
    return course, unit


def _open(browser, live_server, username, width):
    course, unit = _seed_crumb_course(username)
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector("nav.unit-crumbs")
    return ctx, page


CONTENT_HEIGHT_JS = """() => {
  const list = document.querySelector('.unit-crumbs__list');
  const cs = getComputedStyle(list);
  return list.clientHeight
       - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
}"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("width", ALL_WIDTHS)
def test_strip_never_overflows_and_stays_one_line(browser, live_server, width):
    """THE guard on the whole design.

    Falsifying mutation: change the three modifier floors (--course, --mid, --leaf)
    to `min-width: auto`. That restores each <li>'s content-based minimum — the full
    nowrap width of sep + label — the row refuses to shrink, and this goes red at 360
    and at BREAKPOINT+1.

    Two mutations that do NOT work, recorded so nobody mistakes a wrong mutation for
    a vacuous test: deleting `min-width: 0` from the base .unit-crumbs__item rule
    (every emitted <li> carries a modifier whose floor already overrides it), and
    deleting a `min-width: 0` from .unit-crumbs__label (overflow:hidden already zeroes
    its automatic minimum, and the label carries no min-width at all).
    """
    ctx, page = _open(browser, live_server, f"crumb_fit_{width}", width)
    try:
        overflow = page.evaluate(
            """() => {
              const l = document.querySelector('.unit-crumbs__list');
              return l.scrollWidth - l.clientWidth;
            }"""
        )
        assert overflow <= 0, f"crumb strip overflows its own box by {overflow}px"

        # Page-level tripwire. Deliberately EXEMPT from the falsification requirement:
        # the list's overflow:hidden clips any crumb overflow before it can reach the
        # document, so no single crumb-CSS mutation can turn this red. Kept as a cheap
        # standing guard on invariant 2 against future layout changes elsewhere.
        page_overflow = page.evaluate(
            "() => document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth"
        )
        assert page_overflow <= 0, f"page scrolls horizontally by {page_overflow}px"

        # One line. Reference the COURSE crumb specifically: it is the only crumb that
        # renders at every width (--mid is display:none at 360, --ellipsis at 1280), so
        # "any item" would compare against offsetHeight == 0 and could never pass. The
        # list's block padding is subtracted because the focus-ring fix adds it in both
        # axes and would otherwise eat the tolerance.
        content_h = page.evaluate(CONTENT_HEIGHT_JS)
        item_h = page.locator(".unit-crumbs__item--course").evaluate(
            "el => el.offsetHeight"
        )
        assert content_h <= 1.5 * item_h, f"strip wrapped: {content_h} vs item {item_h}"
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("width", [NARROW, SQUEEZED])
def test_labels_stay_inside_their_crumbs_and_never_overlap(browser, live_server, width):
    """Catches a floor declared in the wrong place.

    Overlap is asserted on the LABELS, not the <li> boxes: sibling flex items in a
    single-line row never overlap without negative margins, so an <li>-level check
    could not go red under any mutation. It is the labels that spill.

    Falsifying mutation: move the three floors off the <li>s onto
    .unit-crumbs__label and put `min-width: 0` back on the items.
    """
    ctx, page = _open(browser, live_server, f"crumb_fit2_{width}", width)
    try:
        boxes = page.evaluate(
            """() => [...document.querySelectorAll('.unit-crumbs__item')]
                 .filter(li => li.getClientRects().length)
                 .map(li => {
                   const label = li.querySelector('.unit-crumbs__label');
                   const r = label.getBoundingClientRect();
                   return {cls: li.className,
                           fits: label.clientWidth <= li.clientWidth,
                           left: r.left, right: r.right,
                           w: label.clientWidth};
                 })"""
        )
        for b in boxes:
            assert b["fits"], f"label overflows its own crumb: {b['cls']}"
        # strict=False is required: ruff selects B, so a bare zip() is a B905
        # failure, and the offset slice is intentionally one shorter. Matches the
        # same adjacent-pair idiom at tests/test_color_bands.py:100.
        for a, b in zip(boxes, boxes[1:], strict=False):
            assert a["right"] <= b["left"] + 0.5, (
                f"labels overlap: {a['cls']} / {b['cls']}"
            )

        # The pinned ends must still have *something* to show. This is what makes
        # Task 6's floor-retune criterion 2 real: without it, a retune that starves
        # the leaf to zero width at 360px passes every other assertion here —
        # `fits` and non-overlap are both trivially true for a zero-width label.
        for b in boxes:
            if "--course" in b["cls"] or "--leaf" in b["cls"]:
                assert b["w"] > 0, f"pinned crumb squeezed to zero width: {b['cls']}"

        if width == SQUEEZED:
            mids = [b for b in boxes if "--mid" in b["cls"]]
            assert mids, "mids must be visible just above the breakpoint"
            assert all(b["w"] > 0 for b in mids)
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_narrow_collapses_mids_behind_the_ellipsis(browser, live_server):
    """Falsifying mutation: delete the `--mid { display: none }` rule from the
    collapse query."""
    ctx, page = _open(browser, live_server, "crumb_narrow", NARROW)
    try:
        assert page.locator(".unit-crumbs__item--mid").count() > 0  # present in DOM
        assert not page.locator(".unit-crumbs__item--mid").first.is_visible()
        assert page.locator(".unit-crumbs__item--ellipsis").is_visible()

        # An orphaned separator is what this catches — a hidden crumb must take its
        # separator with it. Structural in the markup, asserted anyway.
        visible_items = page.evaluate(
            "() => [...document.querySelectorAll('.unit-crumbs__item')]"
            ".filter(e => e.getClientRects().length).length"
        )
        visible_seps = page.evaluate(
            "() => [...document.querySelectorAll('.unit-crumbs__sep')]"
            ".filter(e => e.getClientRects().length).length"
        )
        assert visible_seps == visible_items - 1
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_ellipsis_tooltip_names_exactly_the_hidden_crumbs(browser, live_server):
    """The guard on the invariant coupling hidden_path to the collapse query.

    Reads li.unit-crumbs__item--mid only — separators and the leaf must not be swept
    in — and joins with the imported HIDDEN_PATH_SEP rather than a ", " literal.

    Falsifying mutation: join hidden_path over `ancestors` instead of `ancestors[:-1]`.
    """
    ctx, page = _open(browser, live_server, "crumb_tooltip", NARROW)
    try:
        mids = page.eval_on_selector_all(
            "li.unit-crumbs__item--mid", "els => els.map(e => e.getAttribute('title'))"
        )
        ellipsis_title = page.locator(".unit-crumbs__item--ellipsis").get_attribute(
            "title"
        )
        assert mids
        assert HIDDEN_PATH_SEP.join(mids) == ellipsis_title
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_wide_shows_every_crumb_and_no_ellipsis(browser, live_server):
    """Falsifying mutation: delete `display: none` from the `--ellipsis` modifier —
    the "…" then renders at 1280 alongside the mids it is meant to replace.

    NOT "drop the `screen and`": that yields `@media (max-width: 832px)`, which does
    not match a 1280px viewport under any media type, so every assertion here would
    stay green. (That mutation is the right one for the print test below, which is
    what makes it look plausible here.)
    """
    ctx, page = _open(browser, live_server, "crumb_wide", WIDE)
    try:
        assert page.locator(".unit-crumbs__item--ellipsis").count() == 1
        assert not page.locator(".unit-crumbs__item--ellipsis").is_visible()
        for sel in (".unit-crumbs__item--mid", ".unit-crumbs__item--leaf"):
            for i in range(page.locator(sel).count()):
                w = (
                    page.locator(sel)
                    .nth(i)
                    .evaluate(
                        "el => el.querySelector('.unit-crumbs__label').clientWidth"
                    )
                )
                assert w > 0, f"{sel} label has zero width at {WIDE}px"
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_print_shows_the_whole_path_wrapped(browser, live_server):
    """A screen-only hiding rule once silently destroyed printed content in this
    stylesheet (see the .el--tabs print block). Not shipping that risk untested.

    Falsifying mutation: remove `screen and` from the collapse query — the mids then
    vanish from the printout and the first assertion goes red.
    """
    ctx, page = _open(browser, live_server, "crumb_print", NARROW)
    try:
        page.emulate_media(media="print")
        assert page.locator(".unit-crumbs__item--mid").first.is_visible()
        assert not page.locator(".unit-crumbs__item--ellipsis").is_visible()

        overflow = page.evaluate(
            """() => {
              const l = document.querySelector('.unit-crumbs__list');
              return l.scrollWidth - l.clientWidth;
            }"""
        )
        assert overflow <= 0

        # Wrapped, not clipped: the whole point of the print block.
        content_h = page.evaluate(CONTENT_HEIGHT_JS)
        item_h = page.locator(".unit-crumbs__item--course").evaluate(
            "el => el.offsetHeight"
        )
        assert content_h > 1.5 * item_h, "print output did not wrap"
    finally:
        ctx.close()
