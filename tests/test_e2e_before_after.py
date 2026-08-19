"""Playwright e2e for the "Before / after" container element (plan Task 13). Drives
the REAL student/author gestures end-to-end -- clicks the actual toggle, uses the
actual add-menu/paste buttons -- no page.evaluate shortcuts into beforeafter.js
internals for the primary gesture under test (this repo's standing lesson: an e2e
that bypasses the real gesture ships broken UX green). The one deliberate exception
is `window.__baDisarm()` in test_recovery_clears_hidden_not_just_the_html_classes --
see that test's docstring for why there is no live trigger for it that leaves a
pre-existing `hidden` attribute in place, and why invoking the SAME window-global the
watchdog itself calls still exercises the real recovery contract rather than faking a
click.

STALL vs ABORT are NOT interchangeable, and the boot guard is why:
  * STALL (a page.route handler that never resolves) keeps the deferred script
    pending, so DOMContentLoaded never fires, the watchdog never runs, and
    ba-armed stays applied -- the ONLY way to observe the pre-hide window.
  * ABORT makes the deferred script fail immediately, so DOMContentLoaded fires,
    the watchdog's `if (!window.__beforeAfterBooted) window.__baDisarm();` runs
    (the module never got as far as setting that flag), and the after panel
    becomes VISIBLE. A pre-hide test written against an ABORT is RED on a
    correct build.
A stalled `defer` script blocks BOTH DOMContentLoaded and load, so a plain
page.goto() (default wait_until="load") times out after 30s on a CORRECT build --
navigate with wait_until="commit" for the stall test, and unroute/abort the pending
route before the test ends (an unhandled route can raise at context teardown).

Modeled on tests/test_e2e_twocolumn.py (shared harness idiom: login, seed helpers,
add-menu gestures) and tests/test_e2e_clipboard.py (select-then-paste gesture).
Marked e2e (excluded from the default run; run with -m e2e)."""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Shared login / seed helpers (copied verbatim from tests/test_e2e_twocolumn.py --
# this repo's e2e convention is each file stays self-contained).
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


def _seed_before_after(
    unit, before_body="<p>BEFORE</p>", after_body="<p>AFTER</p>", **kw
):
    """A top-level BeforeAfterElement with one TextElement child per slot. Returns
    (join, before_child, after_child)."""
    from courses.models import BeforeAfterElement
    from courses.models import Element
    from courses.models import TextElement

    ba = BeforeAfterElement.objects.create(**kw)
    join = Element.objects.create(unit=unit, content_object=ba)
    before_child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=before_body),
        parent=join,
        tab_id=BeforeAfterElement.BEFORE_SLOT_ID,
    )
    after_child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=after_body),
        parent=join,
        tab_id=BeforeAfterElement.AFTER_SLOT_ID,
    )
    return join, before_child, after_child


def _ba_rows(page):
    """The two `<div class="ba-rows" data-ba-slot="...">` sections in the editor's
    before/after row, in slot order (before, after). Unlike tabs/columns these are
    plain always-open divs -- no <details> to open first."""
    return page.locator(
        '[data-scope="editor"] .el-row--beforeafter .el-row__ba > .ba-rows'
    )


def _wait_ba_state(page, expected_counts):
    """Poll until the editor's per-slot nested-row counts match exactly. A Save's
    fetch is fire-and-forget from the caller's point of view (mirrors
    test_e2e_twocolumn.py's _wait_columns_state -- see its docstring for why a
    naive wait_for_selector would race the swap)."""
    page.wait_for_function(
        """(expected) => {
            const rows = document.querySelectorAll(
                '[data-scope="editor"] .el-row--beforeafter .el-row__ba > .ba-rows');
            if (rows.length !== expected.length) return false;
            return Array.from(rows).every((d, i) =>
                d.querySelectorAll('.element-list--nested .el-row').length
                    === expected[i]);
        }""",
        arg=expected_counts,
    )


def _add_text_child(page, slot_details, body):
    """Drive that slot's OWN nested add-menu -> Text, type `body`, Save. Copied
    verbatim from tests/test_e2e_twocolumn.py's _add_text_child."""
    slot_details.locator("[data-add-toggle]").click()
    slot_details.locator("[data-add-type='text']").click()
    surface = page.locator("[data-edit-slot] form[data-op='element-save'] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type(body)
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()


# ---------------------------------------------------------------------------
# 1. Basic toggle
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_toggle_swaps_both_ways(page, live_server):
    pa = _make_pa_user("ba_toggle")
    course, unit = _seed_unit(pa, "ba-toggle")
    _seed_before_after(unit, "<p>TOGGLE-BEFORE</p>", "<p>TOGGLE-AFTER</p>")
    _login(page, live_server, "ba_toggle")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("[data-beforeafter]")

    toggle = page.locator(".ba__toggle")
    before_panel = page.locator('[data-ba-side="before"]')
    after_panel = page.locator('[data-ba-side="after"]')

    expect(before_panel).to_be_visible()
    expect(after_panel).to_be_hidden()
    expect(toggle).to_have_attribute("aria-pressed", "false")

    toggle.click()

    expect(after_panel).to_be_visible()
    expect(before_panel).to_be_hidden()
    expect(toggle).to_have_attribute("aria-pressed", "true")

    toggle.click()

    expect(before_panel).to_be_visible()
    expect(after_panel).to_be_hidden()
    expect(toggle).to_have_attribute("aria-pressed", "false")


# ---------------------------------------------------------------------------
# 2. Pre-hide window (STALL)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_after_is_not_visible_while_the_script_is_pending(page, live_server):
    """Mutant: remove the pre-hide <style> -> RED. A plain post-load assertion
    would be GREEN under that mutant, because init sets `hidden` either way --
    stalling is what brackets the pre-paint window rather than measuring the
    settled state.
    """
    pa = _make_pa_user("ba_stall")
    course, unit = _seed_unit(pa, "ba-stall")
    _seed_before_after(unit, "<p>STALL-BEFORE</p>", "<p>STALL-AFTER</p>")
    _login(page, live_server, "ba_stall")
    url = _lesson_url(live_server, unit)

    pending_routes = []
    page.route(
        "**/beforeafter.js", lambda route: pending_routes.append(route)
    )  # never fulfil
    page.goto(url, wait_until="commit")

    # Parsing continues even though the deferred script is pending (defer does not
    # block parsing, only DOMContentLoaded) -- wait for the DOM to be ATTACHED, not
    # for a load event that will never fire while the request is stuck. Waiting for
    # the default "visible" state would wait forever here: the panel is correctly
    # HIDDEN at this point, which is exactly what this test asserts next.
    page.wait_for_selector('[data-ba-side="after"]', state="attached")

    assert "ba-armed" in (page.evaluate("document.documentElement.className") or "")
    expect(page.locator('[data-ba-side="after"]')).to_be_hidden()
    expect(page.locator('[data-ba-side="before"]')).to_be_visible()

    # Release the stalled request before the test ends -- an unhandled route can
    # raise at context teardown.
    for route in pending_routes:
        route.abort()
    page.unroute("**/beforeafter.js")


# ---------------------------------------------------------------------------
# 3. Boot guard (ABORT)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_boot_guard_recovers_from_an_aborted_script(page, live_server):
    """Two mutants:
      * delete the guard -> the after side is stranded
      * watchdog removes only ba-armed -> panels show BUT the headings stay
        hidden and the dead toggle stays visible
    Asserting only "both panels show" leaves the second one green.
    """
    pa = _make_pa_user("ba_abort")
    course, unit = _seed_unit(pa, "ba-abort")
    _seed_before_after(unit, "<p>ABORT-BEFORE</p>", "<p>ABORT-AFTER</p>")
    _login(page, live_server, "ba_abort")
    url = _lesson_url(live_server, unit)

    page.route("**/beforeafter.js", lambda route: route.abort())
    page.goto(url)  # default wait_until="load" is fine: ABORT lets load fire

    before_panel = page.locator('[data-ba-side="before"]')
    after_panel = page.locator('[data-ba-side="after"]')
    headings = page.locator(".ba__side-heading")
    toggle = page.locator(".ba__toggle")

    expect(before_panel).to_be_visible()
    expect(after_panel).to_be_visible()
    # `.ba__side-heading` keeps `.visually-hidden` (a clipped 1x1px box) in every
    # state, and Playwright's to_be_visible() only checks a non-empty bounding
    # box -- it would report a still-clipped heading "visible". Measure the box
    # directly: a genuinely revealed heading is a real text line (height > 1px).
    box0 = headings.nth(0).bounding_box()
    box1 = headings.nth(1).bounding_box()
    assert box0 is not None and box0["height"] > 1, (
        f"heading 0 is still visually-hidden: {box0}"
    )
    assert box1 is not None and box1["height"] > 1, (
        f"heading 1 is still visually-hidden: {box1}"
    )
    expect(toggle).to_be_hidden()

    page.unroute("**/beforeafter.js")


# ---------------------------------------------------------------------------
# 4. Malformed instance does not strand its siblings
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_malformed_instance_does_not_strand_its_siblings(page, live_server):
    """Build three instances and make the middle one malformed before init runs, by
    rewriting the served response to drop its <button class="ba__toggle">.

    The MALFORMED path is the reachable one: `panels.length !== 2 || !toggle` is
    an early return, so no DOM break can make initOne actually *throw*. That
    guard now calls killOne, which is what makes this state assertable at all.

    Mutant: revert the guard to a bare `return` -> instance 2 shows unlabelled
    panels (no .ba--dead, headings stay visually-hidden) with no live control
    to reveal them. (Moving the try/catch to the document level is NOT a
    realizable mutant here: the malformed path is this early `return`, not a
    throw, so relocating the `try` changes nothing observable and the test
    would stay green regardless.)
    """
    pa = _make_pa_user("ba_malformed")
    course, unit = _seed_unit(pa, "ba-malformed")
    for i in (1, 2, 3):
        _seed_before_after(unit, f"<p>MAL-BEFORE-{i}</p>", f"<p>MAL-AFTER-{i}</p>")
    _login(page, live_server, "ba_malformed")
    url = _lesson_url(live_server, unit)

    def _strip_middle_toggle(route):
        resp = route.fetch()
        body = resp.text()
        pattern = re.compile(
            r'<button type="button" class="ba__toggle".*?</button>', re.S
        )
        matches = list(pattern.finditer(body))
        assert len(matches) == 3, (
            f"expected 3 toggles in the served HTML, found {len(matches)}"
        )
        m = matches[1]
        body = body[: m.start()] + body[m.end() :]
        route.fulfill(response=resp, body=body)

    page.route(url, _strip_middle_toggle)
    page.goto(url)
    page.unroute(url)

    instances = page.locator("[data-beforeafter]")
    expect(instances).to_have_count(3)

    dead = instances.nth(1)
    expect(dead).to_have_class(re.compile(r"\bba--dead\b"))
    dead_panels = dead.locator(".ba__panel")
    expect(dead_panels.nth(0)).to_be_visible()
    expect(dead_panels.nth(1)).to_be_visible()
    dead_headings = dead.locator(".ba__side-heading")
    # Same false-negative risk as the abort test above: to_be_visible() cannot
    # tell a genuinely revealed heading from a still-clipped .visually-hidden
    # one. Measure the box instead.
    dead_box0 = dead_headings.nth(0).bounding_box()
    dead_box1 = dead_headings.nth(1).bounding_box()
    assert dead_box0 is not None and dead_box0["height"] > 1, (
        f"dead heading 0 is still visually-hidden: {dead_box0}"
    )
    assert dead_box1 is not None and dead_box1["height"] > 1, (
        f"dead heading 1 is still visually-hidden: {dead_box1}"
    )
    expect(dead.locator(".ba__toggle")).to_have_count(0)  # dropped from the served HTML

    for idx in (0, 2):
        instance = instances.nth(idx)
        toggle = instance.locator(".ba__toggle")
        expect(toggle).to_be_visible()
        expect(instance.locator('[data-ba-side="after"]')).to_be_hidden()
        toggle.click()
        expect(instance.locator('[data-ba-side="after"]')).to_be_visible()
        expect(instance.locator('[data-ba-side="before"]')).to_be_hidden()


# ---------------------------------------------------------------------------
# 5. Recovery clears the per-instance `hidden`, not just the <html> classes
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_recovery_clears_hidden_not_just_the_html_classes(page, live_server):
    """__baDisarm is the window-global recovery entry point the watchdog itself
    calls on DOMContentLoaded -- and the flag it checks
    (`window.__beforeAfterBooted`) is set on the VERY FIRST line of the module, so
    the watchdog can only ever fire before the module has touched a single panel.
    There is therefore no user-reachable path that leaves a pre-existing `hidden`
    attribute in place when __baDisarm runs (test_boot_guard_recovers_from_an_
    aborted_script above covers the only live trigger, and in that scenario no
    panel ever had `hidden` set to begin with). Invoking the SAME global the
    watchdog calls exercises the real per-instance un-hide loop, not a bypassed
    click.

    Mutant: __baDisarm removes only the <html> classes -> the after panel stays
    hidden with no control able to reveal it (removing the classes alone is a
    no-op here besides, since a successful boot has already cleared ba-armed).
    """
    pa = _make_pa_user("ba_recover")
    course, unit = _seed_unit(pa, "ba-recover")
    _seed_before_after(unit, "<p>REC-BEFORE</p>", "<p>REC-AFTER</p>")
    _login(page, live_server, "ba_recover")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("[data-beforeafter]")

    after_panel = page.locator('[data-ba-side="after"]')
    # A normal, successful boot: the after panel is hidden via the `hidden`
    # ATTRIBUTE (init has already run), not the CSS pre-hide (already cleared).
    expect(after_panel).to_be_hidden()
    assert (
        page.evaluate("document.documentElement.classList.contains('ba-armed')")
        is False
    )
    assert (
        page.evaluate(
            "document.querySelector('[data-ba-side=\"after\"]').hasAttribute('hidden')"
        )
        is True
    )

    page.evaluate("window.__baDisarm()")

    expect(after_panel).to_be_visible()


# ---------------------------------------------------------------------------
# 6. Gallery inside the after slot re-measures on reveal
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_gallery_in_after_measures_non_zero_after_press(page, live_server):
    """Mutant: drop the libli:reveal dispatch -> the gallery keeps the zero height
    it measured while hidden.
    """
    from courses.models import BeforeAfterElement
    from courses.models import Element
    from courses.models import GalleryElement
    from tests.factories import make_image_asset

    pa = _make_pa_user("ba_gallery")
    course, unit = _seed_unit(pa, "ba-gallery")
    img_a = make_image_asset(course, filename="ba_a.png")
    img_b = make_image_asset(course, filename="ba_b.png")
    gallery = GalleryElement.objects.create(
        data={
            "desc_pos": "below",
            "images": [
                {"media": img_a.pk, "desc": ""},
                {"media": img_b.pk, "desc": ""},
            ],
        }
    )
    ba = BeforeAfterElement.objects.create()
    join = Element.objects.create(unit=unit, content_object=ba)
    from courses.models import TextElement

    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>GAL-BEFORE</p>"),
        parent=join,
        tab_id=BeforeAfterElement.BEFORE_SLOT_ID,
    )
    Element.objects.create(
        unit=unit,
        content_object=gallery,
        parent=join,
        tab_id=BeforeAfterElement.AFTER_SLOT_ID,
    )
    _login(page, live_server, "ba_gallery")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("[data-beforeafter]")
    page.wait_for_selector(
        '[data-ba-side="after"] .el--gallery.gallery--js', state="attached"
    )

    page.locator(".ba__toggle").click()

    page.wait_for_function(
        """() => {
            const s = document.querySelector('[data-ba-side="after"] .gallery__stage');
            return s && s.offsetHeight > 0;
        }""",
        timeout=5000,
    )
    height = page.evaluate(
        "() => document.querySelector("
        "'[data-ba-side=\"after\"] .gallery__stage').offsetHeight"
    )
    assert height > 0


# ---------------------------------------------------------------------------
# 7. No heading flash on a normal load
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_no_heading_flash_on_a_normal_load(page, live_server):
    """Mutant: set ba-js from the module instead of the prepaint script -> the
    headings paint visible, then vanish.

    A settled-state assertion alone cannot distinguish "never visible" from
    "visible for one frame then hidden" (both end up hidden after the module
    runs). What structurally rules out the flash is that the class-setting
    script is INLINE, BLOCKING, and appears in the served HTML before any
    `.ba__side-heading` markup -- the parser executes it synchronously before
    it ever reaches the heading elements, so `html:not(.ba-js)` can never match
    during the initial parse. Under the mutant, that inline call disappears
    from the response entirely (the class only gets added later, by the
    deferred external module), so the source-order assertion goes RED.
    """
    pa = _make_pa_user("ba_flash")
    course, unit = _seed_unit(pa, "ba-flash")
    _seed_before_after(unit, "<p>FLASH-BEFORE</p>", "<p>FLASH-AFTER</p>")
    _login(page, live_server, "ba_flash")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("[data-beforeafter]")

    html = page.content()
    prepaint_idx = html.index('classList.add("ba-js")')
    heading_idx = html.index("ba__side-heading")
    assert prepaint_idx < heading_idx, (
        "ba-js must be set before the heading markup so html:not(.ba-js) can "
        "never match during the initial parse"
    )
    # And it must be a blocking inline script (no defer/async/src) -- a deferred
    # external script runs AFTER parsing, with no guarantee of running before paint.
    script_start = html.rfind("<script", 0, prepaint_idx)
    script_tag = html[script_start : html.index(">", script_start) + 1]
    assert (
        "defer" not in script_tag
        and "async" not in script_tag
        and "src=" not in script_tag
    )

    # Runtime corroboration of the settled state. `.visually-hidden` is a 1x1px
    # clipped box, NOT display:none -- Playwright's to_be_hidden() only checks
    # display/visibility/opacity and a non-empty bounding box, so it reports this
    # element "visible" regardless (a real false-negative risk this test must not
    # repeat). Measure the box directly instead: the un-hidden (flashed) state
    # resets width/height/position to real values via `!important`, so a tiny
    # bounding box is what proves the heading never left .visually-hidden.
    assert page.evaluate("document.documentElement.classList.contains('ba-js')")
    box = page.locator(".ba__side-heading").first.bounding_box()
    assert box is not None and box["width"] <= 1 and box["height"] <= 1, (
        f"heading is not visually-hidden (flashed visible): {box}"
    )


# ---------------------------------------------------------------------------
# 8. Editor: each fixed slot accepts its own child via the real add-menu
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_editor_slots_accept_a_child_each(page, live_server):
    from courses.models import BeforeAfterElement
    from courses.models import Element

    pa = _make_pa_user("ba_slots")
    course, unit = _seed_unit(pa, "ba-slots")
    _login(page, live_server, "ba_slots")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    top_menu = page.locator("[data-add-menu]:not(.addwrap--nested)")
    top_menu.locator("[data-add-toggle]").click()
    top_menu.locator("[data-add-type='beforeafter']").click()
    page.wait_for_selector("[data-edit-slot] .el-editor--beforeafter")
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()

    _wait_ba_state(page, [0, 0])
    rows = _ba_rows(page)
    expect(rows).to_have_count(2)

    _add_text_child(page, rows.nth(0), "Before text")
    _wait_ba_state(page, [1, 0])
    _add_text_child(page, _ba_rows(page).nth(1), "After text")
    _wait_ba_state(page, [1, 1])

    join = Element.objects.get(unit=unit, parent__isnull=True)
    before_child = Element.objects.get(
        parent=join, tab_id=BeforeAfterElement.BEFORE_SLOT_ID
    )
    after_child = Element.objects.get(
        parent=join, tab_id=BeforeAfterElement.AFTER_SLOT_ID
    )
    assert before_child.content_object.body == "Before text"
    assert after_child.content_object.body == "After text"

    rows = _ba_rows(page)
    assert rows.nth(0).locator(".element-list--nested .el-row").count() == 1
    assert rows.nth(1).locator(".element-list--nested .el-row").count() == 1


# ---------------------------------------------------------------------------
# 9. Editor: select-then-paste into each slot
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_paste_into_each_slot(page, live_server):
    """Mark an element with the row's select control, then paste into BEFORE and
    again into AFTER, driving the real UI.

    A plain GET cannot cover this: _paste_buttons.html is gated on
    `{% if show_move or show_copy %}`, which the paste_buttons tag computes from
    move_slots/copy_slots -- with an empty clipboard the tag renders nothing.

    Mutant: drop {% paste_buttons %} from a slot -> no pastewrap /
    data-op="element-paste" control appears in that slot and the paste is
    impossible.
    """
    from courses.models import BeforeAfterElement
    from courses.models import Element
    from courses.models import TextElement

    pa = _make_pa_user("ba_paste")
    course, unit = _seed_unit(pa, "ba-paste")
    ba = BeforeAfterElement.objects.create()
    join = Element.objects.create(unit=unit, content_object=ba)
    src1 = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>PasteBefore</p>")
    )
    src2 = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>PasteAfter</p>")
    )
    _login(page, live_server, "ba_paste")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    def _mark_and_paste(src_pk, slot_id):
        src_row = page.locator(f'.el-row[data-element="{src_pk}"]')
        src_controls = src_row.locator(
            "> .el-row__head .el-actions form[data-op='element-clip'] button"
        )
        with page.expect_response(lambda r: "element/clip/" in r.url):
            src_controls.click()
        expect(page.locator("#clip-banner")).to_be_visible()

        ba_row = page.locator(f'.el-row[data-element="{join.pk}"]')
        slot = ba_row.locator(f'.ba-rows[data-ba-slot="{slot_id}"]')
        with page.expect_response(lambda r: "element/paste/" in r.url):
            slot.locator("form[data-op='element-paste'] button[value='move']").click()
        expect(page.locator("#clip-banner")).to_have_count(0)

    _mark_and_paste(src1.pk, BeforeAfterElement.BEFORE_SLOT_ID)
    moved1 = page.locator(
        f'.el-row[data-element="{join.pk}"] .ba-rows[data-ba-slot="'
        f'{BeforeAfterElement.BEFORE_SLOT_ID}"] .el-row[data-element="{src1.pk}"]'
    )
    expect(moved1).to_have_count(1)

    _mark_and_paste(src2.pk, BeforeAfterElement.AFTER_SLOT_ID)
    moved2 = page.locator(
        f'.el-row[data-element="{join.pk}"] .ba-rows[data-ba-slot="'
        f'{BeforeAfterElement.AFTER_SLOT_ID}"] .el-row[data-element="{src2.pk}"]'
    )
    expect(moved2).to_have_count(1)

    src1.refresh_from_db()
    src2.refresh_from_db()
    assert (
        src1.parent_id == join.pk and src1.tab_id == BeforeAfterElement.BEFORE_SLOT_ID
    )
    assert src2.parent_id == join.pk and src2.tab_id == BeforeAfterElement.AFTER_SLOT_ID


# ---------------------------------------------------------------------------
# 10. Editor row renders for a NESTED instance
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_editor_row_renders_for_a_NESTED_instance(page, live_server):
    """Mutant: gate the row branch on el.parent_id is None -> RED."""
    from courses.models import BeforeAfterElement
    from courses.models import Element
    from courses.models import TabsElement

    pa = _make_pa_user("ba_nested")
    course, unit = _seed_unit(pa, "ba-nested")
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    t1 = tabs.data["tabs"][0]["id"]
    ba = BeforeAfterElement.objects.create()
    nested_join = Element.objects.create(
        unit=unit, content_object=ba, parent=tabs_join, tab_id=t1
    )
    _login(page, live_server, "ba_nested")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    nested_row = page.locator(f'.el-row[data-element="{nested_join.pk}"]')
    expect(nested_row).to_have_class(re.compile(r"\bel-row--beforeafter\b"))
    assert nested_row.locator(".ba-rows[data-ba-slot]").count() == 2


# ---------------------------------------------------------------------------
# 11-13. Editor PREVIEW toggle -- non-negotiable coverage (see task-13 brief)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_preview_toggle_is_visible_and_works(page, live_server):
    """Mutant: omit editor.html's ba-js prepaint block -> html:not(.ba-js)
    .ba__toggle hides it. The "toggles after a swap" assertion alone cannot
    distinguish this from "not wired".
    """
    pa = _make_pa_user("ba_pv_toggle")
    course, unit = _seed_unit(pa, "ba-pv-toggle")
    _seed_before_after(unit, "<p>PV-BEFORE</p>", "<p>PV-AFTER</p>")
    _login(page, live_server, "ba_pv_toggle")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="preview"]')

    preview = page.locator('[data-scope="preview"]')
    toggle = preview.locator(".ba__toggle")
    before_panel = preview.locator('[data-ba-side="before"]')
    after_panel = preview.locator('[data-ba-side="after"]')

    expect(toggle).to_be_visible()
    expect(before_panel).to_be_visible()
    expect(after_panel).to_be_hidden()

    toggle.click()

    expect(after_panel).to_be_visible()
    expect(before_panel).to_be_hidden()
    expect(toggle).to_have_attribute("aria-pressed", "true")


@pytest.mark.django_db(transaction=True)
def test_preview_toggle_still_works_after_a_fragment_swap(page, live_server):
    """Edit a DIFFERENT element (forcing a preview fragment swap), then toggle.

    Mutants: omit the editor.js re-init call -> the button is dead after the
    swap; break the dataset.baReady guard -> the handler is double-bound and one
    click swaps twice (back to where it started).
    """
    from courses.models import Element
    from courses.models import TextElement

    pa = _make_pa_user("ba_pv_swap")
    course, unit = _seed_unit(pa, "ba-pv-swap")
    _seed_before_after(unit, "<p>SWAP-BEFORE</p>", "<p>SWAP-AFTER</p>")
    other = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>Original other</p>"),
    )
    _login(page, live_server, "ba_pv_swap")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="preview"] .ba__toggle')

    # Force a preview fragment swap by editing the OTHER (non before/after) element.
    other_row = page.locator(
        f'[data-scope="editor"] .el-row[data-element="{other.pk}"]'
    )
    other_row.locator("> .el-row__head .el-select.el-act-edit").click()
    surface = page.locator("[data-edit-slot] form[data-op='element-save'] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type(" appended")
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()
    expect(
        page.locator('[data-scope="preview"]').get_by_text("appended")
    ).to_be_visible()

    preview = page.locator('[data-scope="preview"]')
    toggle = preview.locator(".ba__toggle")
    before_panel = preview.locator('[data-ba-side="before"]')
    after_panel = preview.locator('[data-ba-side="after"]')
    expect(after_panel).to_be_hidden()

    toggle.click()  # ONE click -> exactly one swap

    expect(after_panel).to_be_visible()
    expect(before_panel).to_be_hidden()
    expect(toggle).to_have_attribute("aria-pressed", "true")


@pytest.mark.django_db(transaction=True)
def test_preview_re_init_does_not_touch_html_classes(page, live_server):
    """libliInitBeforeAfter is initAll -- the root-scoped ENHANCER, not the
    document-level boot. The editor page has no ba-armed at all, and re-init
    must never ARM it either.

    Mutant: add `document.documentElement.classList.add("ba-armed")` inside
    `initAll` itself (the function bound to window.libliInitBeforeAfter, and
    the same function the document-level boot calls once at load) -> every
    scoped re-init call editor.js makes after a fragment swap now arms <html>
    too, with no watchdog left to disarm it (the boot's own
    `classList.remove("ba-armed")` only runs once, at initial load, before any
    swap). `ba-armed` shows up in document.documentElement.classList after the
    swap. (The className-unchanged assertion alone would NOT catch this: the
    boot's only pre-existing <html> write, `classList.remove("ba-armed")`, is
    a no-op when the class was never present, so removing that call cannot
    fail an unchanged-className check either -- the class must actually be
    ADDED for any assertion here to move.)
    """
    from courses.models import Element
    from courses.models import TextElement

    pa = _make_pa_user("ba_pv_classes")
    course, unit = _seed_unit(pa, "ba-pv-classes")
    _seed_before_after(unit, "<p>CLS-BEFORE</p>", "<p>CLS-AFTER</p>")
    other = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>Other</p>")
    )
    _login(page, live_server, "ba_pv_classes")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="preview"] .ba__toggle')

    before = page.evaluate("document.documentElement.className")

    other_row = page.locator(
        f'[data-scope="editor"] .el-row[data-element="{other.pk}"]'
    )
    other_row.locator("> .el-row__head .el-select.el-act-edit").click()
    surface = page.locator("[data-edit-slot] form[data-op='element-save'] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type(" appended")
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()
    expect(
        page.locator('[data-scope="preview"]').get_by_text("appended")
    ).to_be_visible()

    assert page.evaluate("document.documentElement.className") == before
    assert not page.evaluate(
        "document.documentElement.classList.contains('ba-armed')"
    ), "re-init must never arm the editor preview page"


# ---------------------------------------------------------------------------
# 14. Screenshots -- light + dark, normal/pressed/no-JS fallback (Step 4)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_screenshots_light_and_dark(page, live_server, browser, tmp_path):
    """Both themes, captured separately, plus the no-JS fallback. For dark set
    User.theme (an authed user's theme wins outright in _resolve_theme_pref), NOT
    the libli_theme cookie -- mirrors test_e2e_tabs.py's carousel screenshot test.
    """
    pa = _make_pa_user("ba_shots")
    course, unit = _seed_unit(pa, "ba-shots")
    _seed_before_after(
        unit,
        "<p>Shot before content</p>",
        "<p>Shot after content</p>",
        button_label="Compare",
    )
    _login(page, live_server, "ba_shots")
    url = _lesson_url(live_server, unit)

    for theme in ("light", "dark"):
        pa.theme = theme
        pa.save(update_fields=["theme"])
        page.goto(url)
        page.wait_for_selector("[data-beforeafter]")
        assert page.locator("html").get_attribute("data-theme") == theme

        el = page.locator("[data-beforeafter]")
        el.screenshot(path=str(tmp_path / f"beforeafter-{theme}-normal.png"))

        page.locator(".ba__toggle").click()
        expect(page.locator('[data-ba-side="after"]')).to_be_visible()
        el.screenshot(path=str(tmp_path / f"beforeafter-{theme}-pressed.png"))

    # No-JS fallback: a separate context with JS disabled, sharing the same
    # logged-in session (storage_state carries the session cookie), current theme
    # is dark (set last above).
    storage_state = page.context.storage_state()
    no_js_context = browser.new_context(
        java_script_enabled=False, storage_state=storage_state
    )
    no_js_page = no_js_context.new_page()
    no_js_page.goto(url)
    no_js_page.wait_for_selector("[data-beforeafter]")
    no_js_page.locator("[data-beforeafter]").screenshot(
        path=str(tmp_path / "beforeafter-nojs-fallback.png")
    )
    no_js_context.close()

    print(f"BEFOREAFTER_SHOTS_DIR={tmp_path}")


# ---------------------------------------------------------------------------
# 15. Editor: an open edit form stays inside its narrow slot
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_open_edit_form_stays_inside_its_slot(page, live_server):
    r"""A slot is half a nested column, so the edit form opened INSIDE one is the
    narrowest place .el-editor is ever laid out -- and .el-editor is a grid whose
    single implicit track is `auto`, i.e. sized to the LARGEST min-content
    contribution among its items. Authored maths is one long token with no space in
    it (`\(x^2+3x+1=0\quad\quad\Rightarrow\quad`), so without a wrap opportunity
    the .rte-surface's min-content is ~342px, the track is pushed to 342 against a
    282px container, and every grid item -- the toolbar included -- is stretched to
    that track and spills past the slot, past the pane and off the viewport edge.
    MEASURED on the broken build at this viewport: surface/toolbar right edge
    793.5 vs the slot's 754, and .pane-body scrolling 11px horizontally.

    Mutant: drop `overflow-wrap: anywhere` from .rte-surface (editor.css) -> RED on
    both assertions. `break-word` is NOT a fix and is RED too: it wraps the same way
    but is defined NOT to affect min-content intrinsic sizes, which is the only
    thing the auto track reads.
    """
    long_maths = (
        r"<p>(16) \(x^2+3x+1=0\quad\quad\Rightarrow\quad "
        r"x=rac{-3-\sqrt{5}}{2}, x=rac{-3+\sqrt{5}}{2}\)</p>"
    )
    # The fixture only exercises the bug if it really contains an unbreakable run
    # wider than the slot; a body that happens to wrap on spaces would pass under
    # the mutant too.
    assert max(len(w) for w in long_maths.split()) >= 30

    pa = _make_pa_user("ba_formfit")
    course, unit = _seed_unit(pa, "ba-formfit")
    _seed_before_after(unit, long_maths, long_maths)
    page.set_viewport_size({"width": 1600, "height": 900})
    _login(page, live_server, "ba_formfit")
    page.goto(_editor_url(live_server, course, unit))

    after_slot = _ba_rows(page).nth(1)
    after_slot.wait_for(state="visible")
    child = after_slot.locator(".element-list--nested .el-row").first
    child.hover()
    child.locator(".el-act-edit").click()
    surface = page.locator("[data-edit-slot] form[data-op='element-save'] .rte-surface")
    surface.wait_for(state="visible")

    slot_box = after_slot.bounding_box()
    surface_box = surface.bounding_box()
    toolbar_box = page.locator(
        "[data-edit-slot] form[data-op='element-save'] .rte-toolbar"
    ).bounding_box()
    # Guard against a vacuous pass on a collapsed/zero-width box.
    assert surface_box["width"] > 100
    assert toolbar_box["width"] > 100
    for name, box in (("surface", surface_box), ("toolbar", toolbar_box)):
        right = box["x"] + box["width"]
        assert right <= slot_box["x"] + slot_box["width"] + 0.5, (
            f"{name} right edge {right} escapes the slot "
            f"{slot_box['x'] + slot_box['width']}"
        )

    # ...and nothing it contains makes the editor pane scroll sideways.
    pane_overflow = page.evaluate(
        """() => { const b = document.querySelector('.editor-pane .pane-body');
                   return b.scrollWidth - b.clientWidth; }"""
    )
    assert pane_overflow == 0, f"editor pane scrolls {pane_overflow}px horizontally"
