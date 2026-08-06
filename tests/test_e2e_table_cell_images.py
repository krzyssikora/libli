"""Measured browser tests for table cell image sizing (slice C2).

The sizing claims in the spec are only real if measured in a browser. Every trap below
is inherited from C1's harness; read the preamble in this task before changing anything.
"""

import os

import pytest

from courses.models import Element
from courses.models import TableElement
from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

# BOTH markers, module-wide. transaction=True is mandatory, not hygiene: without it
# the live_server thread uses a different connection and cannot see rows created in
# the test's transaction, so every seeded unit/element/asset is simply absent. Every
# test in tests/test_e2e_table_editor.py and tests/test_e2e_image_size.py carries it,
# and it applies to the student-side tests here just as much as the editor-side ones.
pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

PA_USERNAME = "pa-cellimg"

# The MEASURED reference geometry (spec: "Why sizing is not optional"): a 648px content
# column, five columns, one image cell plus four text cells.
MEDIUM_CAP = 160.0


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists.

    live_server's `_MediaFilesHandler` reads `settings.MEDIA_ROOT` per request to
    decide what `/media/<path>` serves -- pointing it at tmp_path before
    make_image_asset writes any bytes is what makes a freshly created fixture image
    resolve at all, not an optional convenience.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


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


def _unit(username, slug):
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )


def _editor_url(live_server, unit):
    return (
        f"{live_server.url}/manage/courses/{unit.course.slug}"
        f"/build/unit/{unit.pk}/edit/"
    )


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _add_table(page, live_server, unit):
    """Add a table element to `unit` via the real add-menu gesture. Leaves the
    freshly-added table's edit form open ([data-edit-slot])."""
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator("[data-add-toggle]").click()
    page.locator('[data-add-type="table"]').click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]")


def _save(page):
    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]", state="detached")


def _reopen(page, live_server, unit, element):
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(f"[data-element='{element.pk}'] .el-act-edit").click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]")


def _goto_editor(page, live_server, username, unit):
    _login(page, live_server, username)
    page.goto(
        f"{live_server.url}/manage/courses/{unit.course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"]')


def _open_edit(page, element_pk):
    page.locator(f'.el-act-edit[data-element-id="{element_pk}"]').click()
    page.wait_for_selector("[data-edit-slot] [data-filltable-editor]")


def _seed_table(unit, *, size, neighbour_text):
    """Attach a 5-column table (image + four text cells) to `unit`.

    This SHAPE is load-bearing — kept for continuity with the spec, not because any
    OTHER shape would defeat the test: it is the shape the neighbour-text-squeeze
    defect was originally measured in (a Task 9 spike found it also fires on other
    shapes) and the one the spec's headline number — 160.0px with short neighbour
    text and 160.0px with long neighbour text — refers to. See the Task 9 spike
    report (.superpowers/sdd/2026-08-05-table-cell-images/spike-cell-img-stability.md)
    for the full measurement.

    add_element() is what makes the element reachable from the lesson page; the asset
    must belong to unit.course, because MediaAsset is course-scoped.
    """
    asset = make_image_asset(unit.course, filename="graph.png", size=(1586, 612))
    row = [{"kind": "image", "media": asset.pk, "alt": "graph", "size": size,
            "halign": "left", "valign": "top"}]
    row += [{"html": neighbour_text, "halign": "left", "valign": "top"}
            for _ in range(4)]
    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid", "cells": [row],
    }))
    add_element(unit, el)
    return el, asset


def _rendered_box(page, selector=".cell-img"):
    """The image's rendered box.

    getComputedStyle().width is the BORDER box (reset.css sets box-sizing: border-box
    globally), so measure the <img> itself, never a padded container. Await decode
    first: an undecoded <img> legitimately reports naturalWidth 0.
    """
    page.wait_for_selector(selector)
    return page.evaluate(
        """async (sel) => {
             const img = document.querySelector(sel);
             if (!img.complete) await img.decode();
             const r = img.getBoundingClientRect();
             return {w: r.width, h: r.height,
                     nw: img.naturalWidth, nh: img.naturalHeight};
           }""",
        selector,
    )


def _open_editor_with_empty_table(page, live_server, slug):
    """Seed a unit, log in, add an empty 2x2 table, and return
    (unit, element, editor)."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, slug)
    element = _add_table(page, live_server, unit)
    return unit, element, page.locator("[data-table-editor]").first


def _open_editor_with_image_cell(page, live_server, slug):
    """Same, but the table is SAVED with one image cell already in it — so the editor
    renders td[data-image] from the server, which is the path the reload-side tests need
    (the stash is empty there, which is the dominant Remove-image case).

    Uses _reopen, NOT a bare goto(_editor_url): `_editor_url` is the unit-BUILDER page,
    and the element's edit form is opened on demand. _reopen does the three things that
    actually make [data-table-editor] exist — waits for [data-scope="editor"], clicks
    [data-element='<pk>'] .el-act-edit, then waits for
    [data-edit-slot] [data-table-editor].
    """
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, slug)
    asset = make_image_asset(unit.course, filename="a.png", size=(1586, 612))
    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid",
        # TWO rows: table_editor.js sets `b.disabled = rows <= 1` on every
        # [data-row-delete], so a one-row table makes the row-delete test time out
        # waiting for an enabled button - a failure on the CORRECT build.
        "cells": [[{"kind": "image", "media": asset.pk, "alt": "seeded alt",
                    "size": "medium", "halign": "left", "valign": "top"},
                   {"html": "text", "halign": "left", "valign": "top"}],
                  [{"html": "r2c1", "halign": "left", "valign": "top"},
                   {"html": "r2c2", "halign": "left", "valign": "top"}]],
    }))
    # add_element RETURNS the Element join row, and _reopen's locator is
    # [data-element='<Element.pk>'] - passing the TableElement's pk makes it miss and
    # the click time out, failing six editor tests on a CORRECT build.
    element = add_element(unit, el)
    _reopen(page, live_server, unit, element)
    return unit, element, page.locator("[data-edit-slot] [data-table-editor]").first


def test_medium_preset_is_stable_against_neighbouring_text(
    page, live_server, _isolated_media
):
    """THE one genuinely new assertion: lengthening text in a NEIGHBOURING cell must no
    longer change the image's rendered width. Nothing below the browser layer can
    observe this — it is the whole reason the slice exists."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)

    unit_a = _unit(PA_USERNAME, "c2-short")
    _seed_table(unit_a, size="medium", neighbour_text="ok")
    page.goto(_lesson_url(live_server, unit_a))
    w_short = _rendered_box(page)["w"]

    unit_b = _unit(PA_USERNAME, "c2-long")
    _seed_table(unit_b, size="medium", neighbour_text="a much longer neighbour " * 8)
    page.goto(_lesson_url(live_server, unit_b))
    w_long = _rendered_box(page)["w"]

    assert w_short == pytest.approx(MEDIUM_CAP, abs=1.0)
    assert w_long == pytest.approx(MEDIUM_CAP, abs=1.0)
    assert w_short == pytest.approx(w_long, abs=1.0)


def test_full_is_the_control_and_still_moves(page, live_server, _isolated_media):
    """Asserts the defect is REAL: the same shape at `full` is content-negotiated, so
    lengthening a neighbour SHRINKS the image. Without this control, a broken build that
    pinned every width to a constant would pass the test above.

    DIRECTION only, deliberately no absolute pixel pins. The spec's 426.2/285.7 figures
    were measured on a page, asset and text this fixture does not reproduce, and a +-2px
    assertion on a deliberately content-negotiated width is the one number here that
    cannot be predicted from the CSS.
    """
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)

    unit_a = _unit(PA_USERNAME, "c2-full-short")
    _seed_table(unit_a, size="full", neighbour_text="ok")
    page.goto(_lesson_url(live_server, unit_a))
    w_short = _rendered_box(page)["w"]

    unit_b = _unit(PA_USERNAME, "c2-full-long")
    _seed_table(unit_b, size="full", neighbour_text="a much longer neighbour " * 8)
    page.goto(_lesson_url(live_server, unit_b))
    w_long = _rendered_box(page)["w"]

    assert w_short > MEDIUM_CAP + 50          # `full` is NOT cap-bound
    assert w_long < w_short - 50              # and it MOVES with neighbour text


@pytest.mark.parametrize("natural", [(1586, 612), (494, 1492), (60, 40)])
def test_medium_is_a_square_box_not_a_width(
    page, live_server, _isolated_media, natural
):
    """One preset, comparable visual weight, any aspect ratio: at Medium a 1586x612
    image lands ~160x62 and a 494x1492 one ~53x160.

    (60, 40) is the third param deliberately: both larger assets exceed the 160px
    cap in one axis, so `min(cap, cap*ratio, natural)` always resolves to one of the
    cap-derived terms and the `natural` (naturalWidth/naturalHeight) arm of the
    clamp never binds. A 60x40 asset is under the cap in BOTH axes, so the formula
    must instead resolve to the natural size itself (60x40, not upscaled) for this
    arm to execute at all."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, f"c2-ratio-{natural[0]}")
    asset = make_image_asset(unit.course, filename="a.png", size=natural)
    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": asset.pk, "alt": "", "size": "medium",
                    "halign": "left", "valign": "top"},
                   {"html": "x", "halign": "left", "valign": "top"}]],
    }))
    add_element(unit, el)
    page.goto(_lesson_url(live_server, unit))
    box = _rendered_box(page)
    # CAPS ONLY SHRINK, so compute the expectation from the same formula the CSS
    # implements, clamped by the intrinsic size. A hard-coded pixel pair would fail on
    # the CORRECT build for any asset smaller than the cap.
    ratio = box["nw"] / box["nh"]
    exp_w = min(MEDIUM_CAP, MEDIUM_CAP * ratio, box["nw"])
    exp_h = min(MEDIUM_CAP, MEDIUM_CAP / ratio, box["nh"])
    assert box["w"] == pytest.approx(exp_w, abs=2.0)
    assert box["h"] == pytest.approx(exp_h, abs=2.0)


def test_a_ta_center_image_cell_centres_its_bounded_image(
    page, live_server, _isolated_media
):
    """halign is text-align on the <td>, which has NO effect on a display:block child.
    With an 80/160/240px cap inside a 648px column the image is almost always narrower
    than its cell, so without the margin rules it would sit flush left whatever the
    author picks — while the align buttons stay enabled and serialize() faithfully
    writes halign. This is the C1 precedent, where centring fit-content figures was
    exactly this class of bug."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-centre")
    asset = make_image_asset(unit.course, filename="a.png", size=(1586, 612))
    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": asset.pk, "alt": "", "size": "medium",
                    "halign": "center", "valign": "top"}]],
    }))
    add_element(unit, el)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".cell-img")
    offsets = page.evaluate(
        """() => {
             const img = document.querySelector('.cell-img');
             const td = img.closest('td');
             const i = img.getBoundingClientRect(), c = td.getBoundingClientRect();
             return {left: i.left - c.left, right: c.right - i.right};
           }"""
    )
    assert offsets["left"] == pytest.approx(offsets["right"], abs=2.0)
    assert offsets["left"] > 2.0        # genuinely inset, not flush left


def test_the_page_never_scrolls_even_when_the_table_scroller_does(
    page, live_server, _isolated_media
):
    """Renamed from test_no_shape_produces_horizontal_scroll: that name asserted
    `.el--table__scroll` itself never overflows, which was never true — a Task 9 spike
    (.superpowers/sdd/2026-08-05-table-cell-images/spike-cell-img-stability.md) found
    this exact fixture already overflows the scroller by ~160px at a 296px viewport
    from the four long TEXT cells alone, nothing to do with the image. What IS true
    and worth guarding: `.el--table__scroll`'s `overflow-x: auto` (tableelement.html
    / courses.css) is what absorbs that overflow, so the outer PAGE never gains a
    horizontal scrollbar of its own, at any viewport — not "no shape produces
    horizontal scroll" but "no shape lets that scroll escape its designated
    container".
    """
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-scroll")
    _seed_table(unit, size="medium", neighbour_text="a much longer neighbour " * 8)
    for width in (1280, 296):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(_lesson_url(live_server, unit))
        page.wait_for_selector(".el--table__scroll")
        overflow = page.evaluate(
            """() => {
                 const doc = document.scrollingElement;
                 const s = document.querySelector('.el--table__scroll');
                 return {page: doc.scrollWidth - doc.clientWidth,
                         scroller: s.scrollWidth - s.clientWidth};
               }"""
        )
        assert overflow["page"] <= 1, (width, overflow)
        if width == 296:
            # Positive control: this fixture genuinely overflows the SCROLLER at the
            # narrow viewport (the four long text cells alone exceed it), so the page
            # assertion above is not vacuously true for lack of anything to absorb.
            assert overflow["scroller"] > 50, (width, overflow)


def test_the_toolbar_is_visible_with_nothing_focused(page, live_server):
    """The discoverability fix: an author opening a table saw a bare grid and no
    controls, with nothing signalling that clicking a cell reveals eighteen of them."""
    _unit_, _el, editor = _open_editor_with_empty_table(page, live_server, "c2-vis")
    assert editor.locator("[data-table-toolbar]").is_visible()


def test_cell_scoped_buttons_are_disabled_before_any_focus(page, live_server):
    """Exhaustive over the predicate table. The five colour swatches are NOT in scope:
    they come from _rte_swatches.html, shared by six toolbars whose editors have no
    `disabled` mechanism, and keep their pre-wire() enabled window by design."""
    _unit_, _el, editor = _open_editor_with_empty_table(page, live_server, "c2-dis")
    # Scoped to the TOOLBAR, not the whole editor: newCell() gives every grid <td>
    # its own data-halign="left"/data-valign="top" defaults, so an editor-wide
    # locator for those two selectors resolves to the toolbar button AND every
    # grid cell — a Playwright strict-mode violation unrelated to what this test
    # checks (button disabled-ness), not a product defect.
    toolbar = editor.locator("[data-table-toolbar]")
    for sel in ['[data-cmd="bold"]', '[data-cmd="italic"]', '[data-cmd="underline"]',
                '[data-cmd="math"]', "[data-image-toggle]",
                '[data-halign="left"]', '[data-halign="center"]',
                '[data-halign="right"]', '[data-valign="top"]',
                '[data-valign="middle"]', '[data-valign="bottom"]']:
        assert toolbar.locator(sel).is_disabled(), sel


def test_clicking_an_image_cell_reveals_and_populates_the_controls(
    page, live_server, _isolated_media
):
    _unit_, _el, editor = _open_editor_with_image_cell(page, live_server, "c2-reveal")
    editor.locator("td[data-image]").first.click()
    assert editor.locator("[data-image-alt]").is_visible()
    assert editor.locator("[data-image-size]").is_visible()
    assert editor.locator("[data-image-remove]").is_visible()
    # POPULATED, not merely shown — a toolbar-level control otherwise displays a stale
    # value from the previously focused image cell.
    assert editor.locator("[data-image-size]").input_value() == "medium"
    assert editor.locator("[data-image-alt]").input_value() == "seeded alt"
    # THE spec-mandated pin, which exists in no other test: "focus an image cell,
    # assert a [data-cmd] button is disabled". Its mutant is writing the isImage
    # derivation BELOW the [data-cmd] loop in refreshToolbarState - `var` hoisting
    # then makes the predicate `!focusCell || undefined` -> falsy -> B/I/U, math and
    # the swatches stay ENABLED on a focused image cell, where clicking math appends
    # a text node that serialize()'s image branch silently discards. Invisible to
    # every source-level test the plan writes.
    assert editor.locator('[data-cmd="bold"]').is_disabled()
    assert editor.locator('[data-cmd="math"]').is_disabled()
    # And the image button must stay ENABLED - it is the re-pick path.
    assert editor.locator("[data-image-toggle]").is_enabled()


def test_conversion_path_populates_without_a_refocus(
    page, live_server, _isolated_media
):
    """THE regression that proves the two-way rewrite landed. The picker path runs
    neither focusin nor (pre-slice) refreshToolbarState, and
    removeAttribute("contenteditable") BLURS the cell rather than re-focusing it — so a
    test that re-focuses cannot see the defect. Never re-focus here."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-convert")
    make_image_asset(unit.course, filename="pickable.png", size=(1586, 612))
    _element = _add_table(page, live_server, unit)
    editor = page.locator("[data-table-editor]").first
    editor.locator("td[contenteditable]").first.click()
    editor.locator("[data-image-toggle]").click()
    page.wait_for_selector(".picker-overlay")
    page.locator(".picker-overlay .asset-pick").first.click()
    # NO re-focus, no second click on the cell.
    assert editor.locator("[data-image-size]").is_visible()
    assert editor.locator("[data-image-size]").input_value() == "medium"
    assert editor.locator("[data-image-remove]").is_visible()


def test_changing_size_twice_leaves_exactly_one_modifier_class(
    page, live_server, _isolated_media
):
    """classList.add alone accumulates, and the four modifiers are single-class
    selectors of identical specificity — so the winner would be decided by
    stylesheet source order rather than the author's pick."""
    _unit_, _el, editor = _open_editor_with_image_cell(page, live_server, "c2-twice")
    editor.locator("td[data-image]").first.click()
    for value in ("large", "small"):
        editor.locator("[data-image-size]").select_option(value)
    classes = editor.locator("td[data-image] img").first.get_attribute("class")
    mods = [c for c in classes.split() if c.startswith("table-editor__img--")]
    assert mods == ["table-editor__img--small"]


def test_remove_image_on_a_reloaded_editor_yields_an_empty_cell(
    page, live_server, _isolated_media
):
    """The NO-STASH case is the DOMINANT one, not an edge case: the stash is
    populated only by an in-session conversion, so any author who saves, reloads and
    then removes a server-rendered image cell hits it. A bare `stash.html` would
    write the string "undefined"."""
    _unit_, _el, editor = _open_editor_with_image_cell(page, live_server, "c2-remove")
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-image-remove]").click()
    cell = editor.locator("td").first
    assert cell.inner_html().strip() == ""
    assert cell.get_attribute("data-image") is None
    assert cell.get_attribute("contenteditable") == "true"


def test_convert_repick_then_remove_restores_the_original_text(
    page, live_server, _isolated_media
):
    """The re-pick data-loss path: setImageCell stashes UNCONDITIONALLY today, so on
    a re-pick s.html is overwritten with the preview <img> markup. Remove image then
    restores an <img> into a contenteditable cell, sanitize_cell strips it to "" at
    save, and the author's original text is permanently and silently lost. Needs TWO
    assets."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-repick")
    make_image_asset(unit.course, filename="one.png", size=(800, 600))
    make_image_asset(unit.course, filename="two.png", size=(800, 600))
    _element = _add_table(page, live_server, unit)
    editor = page.locator("[data-table-editor]").first
    cell = editor.locator("td[contenteditable]").first
    cell.click()
    cell.type("original words")
    editor.locator("[data-image-toggle]").click()
    page.wait_for_selector(".picker-overlay")
    page.locator(".picker-overlay .asset-pick").nth(0).click()
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-image-toggle]").click()          # RE-PICK
    page.wait_for_selector(".picker-overlay")
    page.locator(".picker-overlay .asset-pick").nth(1).click()
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-image-remove]").click()
    assert "original words" in editor.locator("td").first.inner_html()


def test_deleting_the_row_holding_the_focused_image_cell_hides_the_controls(
    page, live_server, _isolated_media
):
    """focusCell is never re-nulled by any delete path, so it would keep pointing at a
    DETACHED <td>: the controls stay visible AND populated, and edits write to a node no
    longer in the grid — silently lost at the next serialize()."""
    _unit_, _el, editor = _open_editor_with_image_cell(page, live_server, "c2-del")
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-row-delete]").first.click()
    assert editor.locator("[data-image-size]").is_hidden()
    assert editor.locator("[data-image-remove]").is_hidden()


def test_filltable_size_select_reveals_populates_and_swaps_the_preview(
    page, live_server, _isolated_media
):
    """The ONLY executed coverage for the half of the slice Task 8 exists to ship.

    Task 8's other tests are all source-scanners (`"size:" in seg`), and its
    form/model round-trip never runs JS. Nothing else in this module touches the
    FILL table — the conversion-path test above drives [data-table-editor] and
    asserts `table-editor__img`, i.e. the plain table. Without this test, the
    "reverts every image cell to `full` on every save" defect class Task 8 names has
    no behavioural pin.

    Seed a fill table with an image cell AND an answer cell (FillTableElementForm
    requires at least one answer cell, so an image-only grid cannot be saved), then
    use tests/test_e2e_filltable.py's _goto_editor + _open_edit(page, element_pk) -
    NOT the plain table's _reopen, whose wait selector is [data-table-editor].
    """
    from courses.models import FillTableElement

    # NO explicit _login here: _goto_editor calls _login itself (unlike the plain
    # table's _reopen). A second login navigates to /accounts/login/ while already
    # authenticated, allauth redirects to LOGIN_REDIRECT_URL, the login form never
    # appears, and the fill() times out - on a fully correct build.
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-fill-size")
    asset = make_image_asset(unit.course, filename="f.png", size=(1586, 612))
    el = FillTableElement.objects.create(data=FillTableElement.normalize_data({
        "prompt": "", "case_sensitive": False, "header_row": False,
        "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": asset.pk, "alt": "",
                    "size": "medium", "halign": "left", "valign": "top"},
                   {"kind": "answer", "answer": "x",
                    "halign": "left", "valign": "top"}]],
    }))
    element = add_element(unit, el)
    # NOT _reopen: it ends
    # `wait_for_selector("[data-edit-slot] [data-table-editor]")`, hard-wired to the
    # PLAIN table root. _edit_filltable.html renders `data-filltable-editor` and
    # never `data-table-editor` (the two roots are disjoint - which is also what
    # makes Task 7's pick.closest("[data-table-editor]") dispatch correct), so
    # _reopen would time out here on a fully correct build.
    _goto_editor(page, live_server, PA_USERNAME, unit)
    _open_edit(page, element.pk)
    editor = page.locator("[data-edit-slot] [data-filltable-editor]").first

    editor.locator("td[data-image]").first.click()
    assert editor.locator("[data-image-size]").is_visible()
    assert editor.locator("[data-image-size]").input_value() == "medium"

    # Same spec-mandated pin for the FILL table, whose predicate additionally ORs
    # isAnswer - and whose derivations Task 6 Step 5 hoists above the deleted early
    # return. Both files need it; neither had it.
    assert editor.locator('[data-cmd="bold"]').is_disabled()
    assert editor.locator("[data-answer-toggle]").is_enabled()   # focus exists

    editor.locator("[data-image-size]").select_option("small")
    classes = editor.locator("td[data-image] img").first.get_attribute("class")
    mods = [c for c in classes.split() if c.startswith("filltable-editor__img--")]
    assert mods == ["filltable-editor__img--small"]


def test_typing_in_the_alt_input_updates_the_cell_and_the_preview(
    page, live_server, _isolated_media
):
    """The plain table's alt-input listener is created FROM SCRATCH in Task 7 Step 8
    item 4 (`table_editor.js` has zero occurrences of `imageAlt` today), and nothing
    else in the plan exercises it - the reveal test pins refreshToolbarState's
    POPULATION, not the listener. The fill table's twin is already covered by
    tests/test_e2e_filltable.py::test_author_two_image_cells_with_distinct_alts, so
    the plain table was the only unguarded side.

    The preview assertion is the load-bearing half: it catches an implementer
    copying the fill table's `.filltable-editor__img` lookup verbatim, which is
    exactly the divergence the plan flags.
    """
    _unit_, _el, editor = _open_editor_with_image_cell(page, live_server, "c2-alt")
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-image-alt]").fill("a new description")
    td = editor.locator("td[data-image]").first
    assert td.get_attribute("data-alt") == "a new description"
    assert td.locator("img").get_attribute("alt") == "a new description"


def test_header_toggle_then_remove_image_restores_the_stashed_text(
    page, live_server, _isolated_media
):
    """toggleHeaderCell builds a NEW element and calls td.replaceWith(next);
    attributes are copied but a Map stash key is not, so without Task 7 Step 8 item
    9's re-keying the stash is orphaned and Remove image restores "" instead of the
    author's text. Silent data loss on a reachable path - [data-header-toggle] is
    enabled whenever a non-locked cell is focused - and test_editor_twin_drift.py
    cannot see it (toggleHeaderCell stays DIVERGENT).
    """
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-hdr")
    make_image_asset(unit.course, filename="h.png", size=(800, 600))
    _add_table(page, live_server, unit)
    editor = page.locator("[data-edit-slot] [data-table-editor]").first
    cell = editor.locator("td[contenteditable]").first
    cell.click()
    cell.type("stashed words")
    editor.locator("[data-image-toggle]").click()
    page.wait_for_selector(".picker-overlay")
    page.locator(".picker-overlay .asset-pick").first.click()
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-header-toggle]").click()
    editor.locator("th[data-image]").first.click()
    editor.locator("[data-image-remove]").click()
    assert "stashed words" in editor.locator("th").first.inner_html()


def test_an_image_cell_survives_a_save_and_reopen(page, live_server, _isolated_media):
    """THE pin for the slice's two silent data-loss modes, neither of which had a
    behavioural test before:

      * serialize() reading a bare `td.dataset.media` (a STRING) instead of
        parseInt(..., 10) - _cell requires isinstance(media, int), so the cell
        degrades to empty text on save;
      * the template emitting data-media="{{ cell.media }}" instead of `.pk` -
        which renders "MediaAsset object (5)", parseInt yields NaN, JSON.stringify
        writes null.

    Both pass every server-side test that constructs data directly. Only a real
    convert -> save -> reopen cycle catches them.
    """
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-roundtrip")
    asset = make_image_asset(unit.course, filename="rt.png", size=(1586, 612))
    # _add_table returns None and CANNOT return an element: the add path is
    # create-on-first-save, so no Element row exists until _save(page).
    _add_table(page, live_server, unit)
    editor = page.locator("[data-edit-slot] [data-table-editor]").first
    editor.locator("td[contenteditable]").first.click()
    editor.locator("[data-image-toggle]").click()
    page.wait_for_selector(".picker-overlay")
    page.locator(".picker-overlay .asset-pick").first.click()
    _save(page)

    # Stored shape: a real int pk, not None and not a degraded text cell.
    # needs `from courses.models import Element`
    element = Element.objects.get(unit=unit)
    cell = element.content_object.data["cells"][0][0]
    assert cell["kind"] == "image"
    assert cell["media"] == asset.pk
    assert cell["size"] == "medium"          # the editor-insert default

    # And it comes back as an image cell in the editor, with data-media as the pk.
    _reopen(page, live_server, unit, element)
    reopened = page.locator("[data-edit-slot] [data-table-editor]").first
    td = reopened.locator("td[data-image]").first
    assert td.get_attribute("data-media") == str(asset.pk)
    assert td.get_attribute("data-size") == "medium"


def test_a_row_insert_before_any_focus_does_not_throw(page, live_server):
    """The bare !focusCell.isConnected mutant, and the ONLY test that can catch it:
    focusCell is null until the first focusin, and the row handles are
    hover-revealed chrome reachable from page load. A TypeError there aborts the
    handler and leaves the grid half-edited and UNSERIALIZED. Note
    tests/test_e2e_table_editor.py cannot catch this — both its scenarios click and
    type into a cell before inserting a row."""
    # Arm the listener AFTER setup: _open_editor_with_empty_table performs the
    # allauth login and two navigations, and an unrelated JS error on either page
    # would fail this test with a message pointing at the disconnect predicate.
    _unit_, _el, editor = _open_editor_with_empty_table(page, live_server, "c2-insert")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    editor.locator("[data-row-insert]").first.click()
    assert errors == []
