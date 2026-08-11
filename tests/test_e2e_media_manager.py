"""Playwright e2e for the media manager's replace action.

Separate from test_e2e_media_picker.py, which drives the in-editor picker, has
no MEDIA_ROOT isolation, and seeds byte-less assets. Both of those would make
the central assertion here -- that the rendered src actually changes -- pass on
a build that replaced nothing.
"""

import os
from io import BytesIO

import pytest
from PIL import Image

from courses.models import ImageElement
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

# Every test below also carries @pytest.mark.django_db(transaction=True),
# matching tests/test_e2e_media_picker.py:83 and tests/test_e2e_before_after.py
# :838. pytest-django's _live_server_helper pulls `transactional_db` in anyway,
# so it changes nothing at runtime -- it is written out so the DB contract is
# visible to a reader rather than implied by a fixture two layers down.


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists.

    autouse deliberately: a fixture defined in a test module is scoped to that
    module and cannot leak, whereas an opt-in redirect that a future test forgets
    would write into -- and, uniquely for THIS feature, DELETE from -- the
    working tree's real media/ directory.

    It is also what makes the served bytes the test's bytes: live_server DOES
    serve /media/ from MEDIA_ROOT, resolved per request (see the module
    docstring of tests/test_e2e_imagezoom.py), which is why the redirect must
    happen BEFORE any asset is created rather than merely before the first page
    load -- otherwise a fixture image's bytes and the path being served diverge.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _png_bytes(size=(4, 4), color="blue"):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _upload_payload(name="replacement.png", color="green"):
    return {"name": name, "mimeType": "image/png", "buffer": _png_bytes(color=color)}


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username, slug, *, with_element=True):
    """A course whose asset has REAL bytes and a storage-assigned name, so the
    replacement genuinely lands on a different URL."""
    owner = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    asset = make_image_asset(course, filename="original.png", color="red")
    if with_element:
        add_element(unit, ImageElement.objects.create(media=asset, alt="a"))
    return owner, course, unit, asset


def _open_manager(page, live_server, username, course):
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/media/")
    page.wait_for_selector(".asset-cell")


@pytest.mark.django_db(transaction=True)
def test_replace_swaps_the_cell_and_the_rendered_image(page, live_server):
    _, course, unit, asset = _seed("pa-repl-e2e", "repl-e2e")
    _open_manager(page, live_server, "pa-repl-e2e", course)
    original_src = asset.file.url

    page.set_input_files("[data-replace-input]", _upload_payload())

    strip = page.locator("[data-replace-strip]")
    strip.wait_for(state="visible")
    assert "replacement.png" in strip.locator("[data-replace-filename]").inner_text()
    # The confirm must not destroy the context the author decides against.
    assert page.locator(".asset-uses").is_visible()

    strip.locator("[data-replace-commit]").click()

    # Wait on the STRIP going away, then assert the filename inside
    # `.asset-fname` -- the server-rendered node. A bare
    # `.asset-cell:has-text("replacement.png")` would be satisfied the instant
    # the strip appears, because :has-text matches DESCENDANTS and
    # [data-replace-filename] holds exactly that name. The wait would then be a
    # no-op and everything after it would race the round-trip.
    page.wait_for_selector("[data-replace-strip]", state="detached")
    page.wait_for_selector('.asset-cell .asset-fname:has-text("replacement.png")')

    editor_url = (
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.goto(editor_url)
    page.wait_for_selector('[data-scope="editor"]')
    new_src = page.locator(".prev-el img").first.get_attribute("src")
    assert new_src != original_src  # it moved...
    assert "replacement" in new_src  # ...and to the file we uploaded


@pytest.mark.django_db(transaction=True)
def test_cancel_changes_nothing_and_sends_no_request(page, live_server):
    _, course, _unit, asset = _seed("pa-repl-cancel", "repl-cancel")
    _open_manager(page, live_server, "pa-repl-cancel", course)

    # Recorded BEFORE the click, so the negative is asserted rather than slept on.
    seen = []
    page.on("request", lambda r: seen.append(r.url) if "/replace/" in r.url else None)

    page.set_input_files("[data-replace-input]", _upload_payload())
    strip = page.locator("[data-replace-strip]")
    strip.wait_for(state="visible")
    strip.locator("[data-replace-cancel]").click()
    # The strip's removal provably post-dates any request the handler would make.
    page.wait_for_selector("[data-replace-strip]", state="detached")

    assert seen == []
    # The input must be CLEARED, not merely abandoned: `change` fires only on a
    # value change, so leaving the old value would make re-picking the SAME file
    # a dead click. Nothing else in this module reads input.value, so without
    # this assertion `closeStrip`'s clearInput argument is untested everywhere.
    assert page.input_value("[data-replace-input]") == ""
    asset.refresh_from_db()
    assert asset.original_filename == "original.png"


@pytest.mark.django_db(transaction=True)
def test_a_422_flashes_the_validator_message(page, live_server):
    _, course, _unit, _asset = _seed("pa-repl-422", "repl-422")
    _open_manager(page, live_server, "pa-repl-422", course)

    page.set_input_files(
        "[data-replace-input]",
        {"name": "clip.mp4", "mimeType": "video/mp4", "buffer": b"\x00" * 256},
    )
    page.locator("[data-replace-commit]").click()

    bar = page.locator(".op-error")
    bar.wait_for(state="visible")
    text = bar.inner_text()
    # CONTAINMENT, not equality: _op_error.html renders
    # "Couldn't apply that change: {{ message }}", so the extracted textContent
    # always carries that prefix. An equality assertion would be red against a
    # correct build. Nobody should "fix" that by stripping the prefix in JS.
    assert "mp4" in text.lower()
    assert "<" not in text  # the fragment was parsed, not dumped
    assert bar.get_attribute("role") == "alert"  # announced, not silent
    assert page.locator("[data-replace-strip]").count() == 0
    assert page.input_value("[data-replace-input]") == ""


@pytest.mark.django_db(transaction=True)
def test_a_server_error_removes_the_strip_and_flashes(page, live_server):
    """Every other e2e here passes with the catch-all branch deleted."""
    _, course, _unit, _asset = _seed("pa-repl-500", "repl-500")
    _open_manager(page, live_server, "pa-repl-500", course)
    page.route("**/replace/", lambda route: route.fulfill(status=500, body="boom"))

    page.set_input_files("[data-replace-input]", _upload_payload())
    page.locator("[data-replace-commit]").click()

    page.wait_for_selector("[data-replace-strip]", state="detached")
    assert page.locator(".op-error").is_visible()
    assert page.input_value("[data-replace-input]") == ""
    focused = page.evaluate("document.activeElement.hasAttribute('data-replace-asset')")
    assert focused  # focus restored, not dropped to <body>


@pytest.mark.django_db(transaction=True)
def test_two_consecutive_replaces_both_succeed(page, live_server):
    """Carries two regressions at once.

    The per-strip `done` closure: hoisted, the second replace is a silent no-op.
    The in-flight flag's LOWERING: it is read in exactly one place, the ⇄ click
    handler -- so the second pass must go through an actual CLICK. A test that
    only ever calls set_input_files never executes that handler, and a flag that
    is raised and never lowered would pass every other test in this module.
    """
    _, course, _unit, _asset = _seed("pa-repl-twice", "repl-twice")
    _open_manager(page, live_server, "pa-repl-twice", course)

    page.set_input_files("[data-replace-input]", _upload_payload("first.png"))
    page.locator("[data-replace-commit]").click()
    # Detached-first, then .asset-fname -- see the note in the happy-path test.
    # Getting this wrong is not cosmetic here: a no-op wait would run the click
    # below while replaceBusy is still true, the handler would return early, no
    # chooser would be raised, and the test would time out ON A CORRECT BUILD.
    page.wait_for_selector("[data-replace-strip]", state="detached")
    page.wait_for_selector('.asset-cell .asset-fname:has-text("first.png")')

    # Second pass THROUGH the button. input.click() raises a file chooser that
    # must be intercepted, or it hangs.
    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(_upload_payload("second.png"))
    page.locator("[data-replace-commit]").click()
    page.wait_for_selector("[data-replace-strip]", state="detached")
    page.wait_for_selector('.asset-cell .asset-fname:has-text("second.png")')


@pytest.mark.django_db(transaction=True)
def test_a_filter_swap_mid_flight_still_updates_the_cell(page, live_server):
    """The replace POST must still be in flight while the filter swaps the grid,
    so the 200 lands on a detached strip and takes the re-query branch.

    CAPTURE-AND-RELEASE, the pattern this suite already uses
    (tests/test_e2e_builder_toggle.py:352, tests/test_e2e_inline_rename.py:326).
    A route handler that returns without fulfil/continue_/abort leaves the
    request PENDING -- test_two_overlapping_tree_fetches_stay_busy_until_both
    _settle asserts TWO are simultaneously in flight before releasing them one
    at a time, which could not happen if returning auto-continued.

    Do NOT block inside the handler waiting on an Event. The comment at
    test_e2e_builder_toggle.py:347-349 says why: "Sleeping inside a sync route
    handler serialises the driver" -- the click would not return, the filter
    would run only after the POST was released, and the branch under test would
    never be exercised while the test still passed.
    """
    _, course, _unit, asset = _seed("pa-repl-filter", "repl-filter")
    _open_manager(page, live_server, "pa-repl-filter", course)

    held = []
    page.route("**/replace/", lambda route: held.append(route))

    page.set_input_files("[data-replace-input]", _upload_payload("late.png"))
    page.locator("[data-replace-commit]").click()

    # Prove the POST actually dispatched before touching the filter: the commit
    # handler disables the button synchronously, immediately before fetch().
    page.wait_for_function(
        "() => { const b = document.querySelector('[data-replace-commit]');"
        "        return b && b.disabled; }"
    )
    for _ in range(50):  # bounded poll on a real condition, not a blind sleep
        if held:
            break
        page.wait_for_timeout(100)
    assert len(held) == 1, "the replace POST never reached the route"

    # Force oldGrid.replaceWith(newGrid) while the POST is still held.
    page.fill("[data-filter-q]", "original")
    page.wait_for_selector("[data-replace-strip]", state="detached")

    held[0].continue_()

    page.wait_for_selector('.asset-cell .asset-fname:has-text("late.png")')
    asset.refresh_from_db()
    assert asset.original_filename == "late.png"
    # The re-query branch moves NO focus: the element that had it is long gone
    # with the swapped-away grid, and stealing focus back would yank a keyboard
    # user out of the filter box they are still typing in.
    assert page.evaluate(
        "() => document.activeElement === document.querySelector('[data-filter-q]')"
    )


@pytest.mark.django_db(transaction=True)
def test_a_filter_that_hides_the_asset_mid_flight_is_a_no_op(page, live_server):
    """The negative half of the re-query branch: `if (live)` is false.

    Filtering the asset OUT means root.querySelector(...) finds nothing, so the
    200 must quietly do nothing rather than throw. Without this the `if (live)`
    guard could be deleted and every other test would stay green.
    """
    _, course, _unit, asset = _seed("pa-repl-gone", "repl-gone")
    _open_manager(page, live_server, "pa-repl-gone", course)

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    held = []
    page.route("**/replace/", lambda route: held.append(route))
    page.set_input_files("[data-replace-input]", _upload_payload("hidden.png"))
    page.locator("[data-replace-commit]").click()
    page.wait_for_function(
        "() => { const b = document.querySelector('[data-replace-commit]');"
        "        return b && b.disabled; }"
    )
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert len(held) == 1

    page.fill("[data-filter-q]", "zzz-matches-nothing")
    page.wait_for_selector(".asset-cell", state="detached")

    # Synchronise on the response, not the clock: the assertions below are only
    # meaningful once the 200 has actually been handled.
    with page.expect_response("**/replace/"):
        held[0].continue_()
    page.wait_for_timeout(100)  # a short settle for the handler, after the wait

    assert errors == [], errors
    assert page.locator(".asset-cell").count() == 0
    asset.refresh_from_db()
    assert asset.original_filename == "hidden.png"  # the replace still committed


@pytest.mark.django_db(transaction=True)
def test_the_drag_warning_appears_only_for_a_drag_to_image_asset(page, live_server):
    from courses.models import DragToImageQuestionElement

    _, course, unit, plain = _seed("pa-repl-warn", "repl-warn", with_element=False)
    dragged = make_image_asset(course, filename="diagram.png", color="green")
    add_element(
        unit,
        DragToImageQuestionElement.objects.create(
            media=dragged, alt="Diagram", distractors=""
        ),
    )
    _open_manager(page, live_server, "pa-repl-warn", course)

    for pk, expect_warning in ((dragged.pk, True), (plain.pk, False)):
        cell = page.locator(f'.asset-cell[data-asset-id="{pk}"]')
        cell.locator("[data-replace-input]").set_input_files(_upload_payload())
        cell.locator("[data-replace-strip]").wait_for(state="visible")
        shown = cell.locator(".asset-replace-confirm__warn").count() > 0
        assert shown is expect_warning, pk
        cell.locator("[data-replace-cancel]").click()
        page.wait_for_selector("[data-replace-strip]", state="detached")


@pytest.mark.django_db(transaction=True)
def test_screenshots_light_and_dark(page, live_server, tmp_path):
    """Four foot states at the grid's MINIMUM column width, both themes.

    Set User.theme, NOT the libli_theme cookie: an authed user's theme wins
    outright in _resolve_theme_pref, so the cookie route silently renders light.

    360px viewport: .asset-grid is repeat(auto-fill, minmax(8rem, 1fr)), so a
    narrow window is what actually pins columns at the 128px minimum where the
    shrink and truncation rules bite. At desktop width they never engage.
    """
    owner, course, unit, in_use = _seed("pa-repl-shots", "repl-shots")
    unused = make_image_asset(course, filename="nobody-uses-me.png", color="green")
    page.set_viewport_size({"width": 360, "height": 900})
    _login(page, live_server, "pa-repl-shots")
    url = f"{live_server.url}/manage/courses/{course.slug}/media/"

    for theme in ("light", "dark"):
        owner.theme = theme
        owner.save(update_fields=["theme"])
        page.goto(url)
        page.wait_for_selector(".asset-cell")
        assert page.locator("html").get_attribute("data-theme") == theme

        unused_cell = page.locator(f'.asset-cell[data-asset-id="{unused.pk}"]')
        in_use_cell = page.locator(f'.asset-cell[data-asset-id="{in_use.pk}"]')

        # 1. unused -- the majority case, and what the .muted truncation is for
        unused_cell.screenshot(path=str(tmp_path / f"replace-{theme}-1-unused.png"))

        # 2. in use, <details> CLOSED -- the only state :not([open]) targets.
        #    Expect the summary truncated and the "▸" marker eaten by the
        #    ellipsis: accepted, but look at it.
        in_use_cell.screenshot(path=str(tmp_path / f"replace-{theme}-2-closed.png"))

        # 3. in use, <details> OPEN -- deliberately left at min-content
        in_use_cell.locator("summary.asset-uses").click()
        page.wait_for_selector("details.asset-uses-detail[open]")
        in_use_cell.screenshot(path=str(tmp_path / f"replace-{theme}-3-open.png"))
        in_use_cell.locator("summary.asset-uses").click()

        # 4. confirm strip open, captured across the WHOLE grid so the
        #    row-height reflow onto the sibling cell is visible
        in_use_cell.locator("[data-replace-input]").set_input_files(
            _upload_payload("a-rather-long-replacement-name.png")
        )
        page.wait_for_selector("[data-replace-strip]")
        page.locator(".asset-grid").screenshot(
            path=str(tmp_path / f"replace-{theme}-4-strip-row.png")
        )
        page.locator("[data-replace-cancel]").click()
        page.wait_for_selector("[data-replace-strip]", state="detached")

    print(f"REPLACE_SHOTS_DIR={tmp_path}")
