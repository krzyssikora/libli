"""Playwright e2e for the builder-tree layout refresh: L/Q unit badges, the 2:1
column ratio, and single-line title truncation. Self-contained (own PA/login
helpers, per the repo e2e convention). Marked e2e — run foreground only."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

# Long enough to overflow the tree column at the fixed narrow viewport set below,
# so the truncation assertion is viewport-deterministic, not environment-dependent.
# Kept under the ContentNode.title CharField(max_length=200) limit.
LONG_TITLE = "A deliberately very long unit title that must truncate " * 3


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


@pytest.mark.django_db(transaction=True)
def test_builder_tree_layout(page, live_server, tmp_path):
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import Element
    from courses.models import TextElement

    _make_pa_user("pa")
    course = Course.objects.create(slug="layout-demo", title="Layout Demo")
    lesson = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title=LONG_TITLE
    )
    # Give the lesson a long-summary element so the unit panel's .element-list has a
    # row whose .element-list__summary must ellipsis-truncate at the narrowed width.
    Element.objects.create(
        unit=lesson,
        content_object=TextElement.objects.create(
            body="<p>"
            + ("A very long element summary that must truncate. " * 6)
            + "</p>"
        ),
    )
    ContentNode.objects.create(
        course=course, kind="unit", unit_type="quiz", title="Quick check"
    )

    # Fixed narrow viewport so the long title deterministically overflows the tree
    # column regardless of the CI default.
    page.set_viewport_size({"width": 1000, "height": 800})
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}/manage/courses/layout-demo/build/")

    # Badges: exactly the L and Q letters render in the tree.
    badges = page.locator(".tree__badge--unit")
    texts = sorted(badges.all_inner_texts())
    assert texts == ["L", "Q"], f"expected L and Q unit badges, got {texts}"

    # Column ratio ~2:1 (tree vs panel). Viewport-INDEPENDENT: follows only from the
    # 2fr/1fr grid track split, not the absolute width.
    tree_box = page.locator(".builder__tree").bounding_box()
    panel_box = page.locator(".builder__panel").bounding_box()
    ratio = tree_box["width"] / panel_box["width"]
    assert 1.7 < ratio < 2.4, f"tree:panel width ratio {ratio:.2f} not ~2:1"

    # Long title truncates on one line: content overflows the input box. Measured on
    # the UNFOCUSED input — Chromium does report scrollWidth > clientWidth for a
    # single-line text control, verified by falsification (a short title gives
    # 371 == 371 and this assertion goes red), so no text-measuring fallback is needed.
    # `*=`, not `=`: LONG_TITLE (line 17) is the phrase repeated three times, so an
    # exact value selector matches nothing and the test would die on a timeout.
    title = page.locator('.tree__title[value*="deliberately very long"]').first
    metrics = title.evaluate("el => ({sw: el.scrollWidth, cw: el.clientWidth})")
    assert metrics["sw"] > metrics["cw"], (
        "long title is not overflowing (not truncated)"
    )

    # Capture light + dark. This app themes via a `data-theme` attribute on the root.
    page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
    page.screenshot(path=str(tmp_path / "builder_tree_light.png"), full_page=True)
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
    page.screenshot(path=str(tmp_path / "builder_tree_dark.png"), full_page=True)

    # (d) Unit panel at the narrowed 1/3 width: select the lesson unit so its detail
    # panel renders (with the seeded element list), then screenshot light + dark.
    page.locator('.tree__title[value*="deliberately very long"]').first.click()
    page.wait_for_selector(".builder__panel .element-list")

    # The 2:1 ratio must SURVIVE selecting a unit — the content-heavy unit panel must
    # not balloon the 1fr track back (requires .builder__panel min-width:0). Without
    # it the ratio collapses to ~0.73.
    utree = page.locator(".builder__tree").bounding_box()
    upanel = page.locator(".builder__panel").bounding_box()
    uratio = utree["width"] / upanel["width"]
    assert 1.7 < uratio < 2.4, f"ratio {uratio:.2f} broke on unit select"

    # No horizontal page overflow: the narrowed 1/3 panel's element list must truncate,
    # not spill (element-list__item / panel / tree all need min-width:0).
    no_overflow = page.evaluate(
        "() => { const d = document.documentElement;"
        " return d.scrollWidth <= d.clientWidth; }"
    )
    assert no_overflow, "page overflows horizontally after selecting a unit"

    page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
    page.screenshot(path=str(tmp_path / "unit_panel_light.png"), full_page=True)
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
    page.screenshot(path=str(tmp_path / "unit_panel_dark.png"), full_page=True)
    print(f"SCREENSHOTS: {tmp_path}")


LONG_BODY = "<p>" + ("Filler paragraph to make this element list tall. " * 8) + "</p>"

# 80, not 25. _unit_panel.html renders each element as ONE ellipsised ~24px row, and the
# panel cap at the 700px test viewport is calc(100vh - 32px) = 668px. At 25 elements the
# overflow is within noise of font metrics, so the `overflow > 0` and `scrollTop > 0`
# preconditions would be flaky. 80 rows (~1900px) makes it unambiguous.
TALL_ELEMENT_COUNT = 80


def _seed_tall_course(slug):
    """A course whose tree overflows the viewport and whose first unit has enough
    elements that its panel overflows too."""
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import Element
    from courses.models import TextElement

    course = Course.objects.create(slug=slug, title="Tall Demo")
    units = [
        ContentNode.objects.create(
            course=course, kind="unit", unit_type="lesson", title=f"Unit {i + 1}"
        )
        for i in range(40)
    ]
    # BOTH of the first two units get a tall element list. Unit 2 needs it because
    # the scroll-reset test swaps from Unit 1 to Unit 2: if Unit 2's panel were
    # short, the browser would clamp scrollTop to 0 on its own the moment the
    # content shrank, and the test would pass with or without setPanel() — unable
    # to go red for the right reason.
    for unit in units[:2]:
        for _ in range(TALL_ELEMENT_COUNT):
            Element.objects.create(
                unit=unit,
                content_object=TextElement.objects.create(body=LONG_BODY),
            )
    return course, units[0]


@pytest.mark.django_db(transaction=True)
def test_panel_stays_reachable_on_a_long_tree(page, live_server):
    """Clicking a unit at the bottom of a long tree leaves both actions on screen."""
    _make_pa_user("pa_sticky")
    course, _first = _seed_tall_course("sticky-demo")

    page.set_viewport_size({"width": 1280, "height": 700})
    _login(page, live_server, "pa_sticky")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")

    # Scroll to the very bottom of the page, then click the LAST unit in the tree.
    page.mouse.wheel(0, 20000)
    page.locator('.tree__title[value="Unit 40"]').click()
    page.locator(".panel__seam").wait_for(state="visible")

    vh = page.evaluate("() => window.innerHeight")
    for label in ("+ Add element", "Open editor"):
        box = page.locator(".builder__panel").get_by_text(label).first.bounding_box()
        assert box is not None, f"{label!r} has no box"
        assert 0 <= box["y"] and box["y"] + box["height"] <= vh, (
            f"{label!r} is outside the viewport "
            f"(y={box['y']}, h={box['height']}, vh={vh})"
        )


@pytest.mark.django_db(transaction=True)
def test_tall_panel_keeps_actions_on_screen(page, live_server):
    """An element-heavy unit's panel scrolls internally; the seam stays pinned."""
    _make_pa_user("pa_tall")
    course, first = _seed_tall_course("tall-demo")

    page.set_viewport_size({"width": 1280, "height": 700})
    _login(page, live_server, "pa_tall")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")
    page.locator('.tree__title[value="Unit 1"]').click()
    page.locator(".panel__seam").wait_for(state="visible")

    # Scroll the page down so the panel is actually PINNED before asserting. This is
    # not a convenience: at scrollY == 0 sticky does nothing (it never lifts an element
    # above its flow position), and the panel's flow top is .app-header (~54px) +
    # .app-main's padding (var(--space-8) = 32px) ≈ 86px. With max-height =
    # 100vh - 32px = 668px, the panel's bottom would sit at ~754px against a 700px
    # viewport — so the seam is below the fold by arithmetic, no matter how correct
    # the CSS is. The complaint this feature fixes is precisely about the scrolled
    # state, so that is what to assert.
    page.mouse.wheel(0, 400)
    page.wait_for_function(
        "() => document.querySelector('.builder__panel')"
        ".getBoundingClientRect().top <= 20"
    )

    # The panel really is overflowing (otherwise this test proves nothing).
    overflow = page.locator(".builder__panel").evaluate(
        "el => el.scrollHeight - el.clientHeight"
    )
    assert overflow > 0, (
        "panel is not a scroll container — is the .builder__panel "
        "max-height/overflow rule applied?"
    )

    vh = page.evaluate("() => window.innerHeight")
    box = (
        page.locator(".builder__panel").get_by_text("Open editor").first.bounding_box()
    )
    assert box["y"] + box["height"] <= vh, "seam is below the fold on a tall panel"

    # The seam must be OPAQUE, or panel content scrolls under the button labels — the
    # degradation the sticky seam exists to prevent. (--surface-default does not exist
    # in tokens.css; an invalid token here would paint transparent and still "pass" a
    # position-only assertion.)
    bg = page.locator(".panel__seam").evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent"), (
        f"sticky seam has no painted background ({bg}) — check the token name is real"
    )


@pytest.mark.django_db(transaction=True)
def test_panel_not_sticky_when_stacked(page, live_server):
    """At <=720px the columns stack: no sticky, and no nested scroll container."""
    _make_pa_user("pa_stack")
    course, _first = _seed_tall_course("stack-demo")

    page.set_viewport_size({"width": 600, "height": 800})
    _login(page, live_server, "pa_stack")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")

    style = page.locator(".builder__panel").evaluate(
        "el => { const s = getComputedStyle(el);"
        " return {pos: s.position, mh: s.maxHeight, ov: s.overflowY}; }"
    )
    assert style["pos"] == "static", f"expected static when stacked, got {style['pos']}"
    assert style["mh"] == "none", (
        f"max-height must be reset when stacked, got {style['mh']}"
    )
    assert style["ov"] == "visible", (
        f"overflow must be reset when stacked, got {style['ov']}"
    )


@pytest.mark.django_db(transaction=True)
def test_panel_scroll_resets_between_units(page, live_server):
    """Selecting another unit opens its panel at the top, not mid-scroll."""
    _make_pa_user("pa_reset")
    course, _first = _seed_tall_course("reset-demo")

    page.set_viewport_size({"width": 1280, "height": 700})
    _login(page, live_server, "pa_reset")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")

    # Open the element-heavy unit and scroll its panel down (real wheel over the panel).
    page.locator('.tree__title[value="Unit 1"]').click()
    page.locator(".panel__seam").wait_for(state="visible")
    panel = page.locator(".builder__panel")
    panel.hover()
    page.mouse.wheel(0, 2000)
    # POLL, don't read once. Playwright's mouse.wheel() dispatches the event but does
    # not wait for the scroll to be applied, so an immediate scrollTop read is a race:
    # it happened to land locally and returned 0 on the slower CI runner.
    page.wait_for_function(
        "() => document.querySelector('.builder__panel').scrollTop > 0",
        timeout=5000,
    )

    # Select a different unit through the real tree control.
    page.locator('.tree__title[value="Unit 2"]').click()
    page.wait_for_function(
        "() => document.querySelector('.builder__panel').textContent.includes('Unit 2')"
    )
    # The NEW panel must also be able to hold a non-zero scrollTop, or the browser
    # clamps it to 0 by itself and this assertion proves nothing.
    assert panel.evaluate("el => el.scrollHeight - el.clientHeight") > 0, (
        "Unit 2's panel does not overflow; it cannot demonstrate the reset"
    )
    assert panel.evaluate("el => el.scrollTop") == 0, (
        "new panel opened mid-scroll — every swap must go through setPanel()"
    )


@pytest.mark.django_db(transaction=True)
def test_notice_bar_is_visible_and_opaque_while_panel_scrolled(page, live_server):
    """A network notice raised while the panel is scrolled down stays on screen.

    Trigger: abort a TREE form's POST (the reorder arrows). notice() prepends into the
    panel regardless of which form fired, and a tree form has inPanel == False so the
    panel innerHTML is never replaced — the bar survives.

    NOT the panel's own form: _unit_panel.html contains no form at all (unit settings
    moved to the editor page). NOT the 409 path either: that would need a manufactured
    stale token, and it applies the server's _conflict_scope fragment (swapping the
    tree scope under the very button that fired it) plus raises its own conflict
    notice — two moving parts this test is not about.
    """
    _make_pa_user("pa_notice")
    course, _first = _seed_tall_course("notice-demo")

    page.set_viewport_size({"width": 1280, "height": 700})
    _login(page, live_server, "pa_notice")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")
    page.locator('.tree__title[value="Unit 1"]').click()
    page.locator(".panel__seam").wait_for(state="visible")

    panel = page.locator(".builder__panel")
    panel.hover()
    page.mouse.wheel(0, 2000)
    # Same race as the scroll-reset test: wait for the scroll to actually apply. This
    # test's whole premise is "a notice raised while the panel is scrolled down", so if
    # the wheel had not landed it would assert against an unscrolled panel and pass
    # vacuously — a silent false green rather than a failure.
    page.wait_for_function(
        "() => document.querySelector('.builder__panel').scrollTop > 0",
        timeout=5000,
    )

    def _abort_posts(route):
        # Named handler, not a multi-line lambda: `ruff format --check` runs on tests/.
        if route.request.method == "POST":
            route.abort()
        else:
            route.continue_()

    page.route("**/manage/courses/**", _abort_posts)
    # A tree reorder form — the panel has none. Its .catch calls notice(network).
    # `:not([disabled])` is REQUIRED: _move_buttons.html renders "up" first and disables
    # it on the first node, so the naive .first selector picks a disabled button and
    # Playwright's actionability check hangs for 30s on a failure unrelated to the
    # notice.
    # Narrowed to data-op="reorder": every row now also carries
    # form.tree__rename[data-op="rename"] whose visually-hidden submit precedes the
    # cluster in document order — .first would pick that clipped button and .click()
    # would hang on the hit-target check for the full timeout.
    page.locator(
        ".builder__tree form[data-op=\"reorder\"] button[type='submit']:not([disabled])"
    ).first.click()

    bar = page.locator(".builder__panel > .op-error")
    bar.wait_for(state="visible")
    box = bar.bounding_box()
    vh = page.evaluate("() => window.innerHeight")
    assert 0 <= box["y"] <= vh, "notice bar is off screen while the panel is scrolled"
    bg = bar.evaluate("el => getComputedStyle(el).backgroundColor")
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent"), (
        f"notice bar has no painted background ({bg}) — "
        "content will scroll under its text"
    )
