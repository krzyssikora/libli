"""Playwright e2e for the four image size presets (plan slice C1, Task 8).

The CSS source tests (courses/tests/test_image_size_css.py) only prove a rule is
*present* in courses.css. They cannot prove what the browser actually computes for a
given fixture at a given viewport, because that number is the output of a `min()` over
three quantities (a width cap, a height cap, and the image's own intrinsic size) that
only a real layout engine resolves. This module is the load-bearing measurement: it
seeds one tall and one wide image at each of the four presets, opens the real lesson
page at two viewports, and asserts the rendered `getBoundingClientRect()` against the
same formula the CSS is supposed to implement.

Both fixtures are required, not one: at the desktop viewport the tall fixture is
height-bound at every preset (and intrinsic-bound at `full`), so `max-width` is never
exercised by it there — only the wide fixture exercises the width caps. Conversely at
the phone viewport the wide fixture is width-bound at all four presets. Neither fixture
alone would touch every rule this slice added.
"""

import os

import pytest

from courses.models import CalloutElement
from courses.models import Element
from courses.models import ImageElement
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TwoColumnElement
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

PA_USERNAME = "pa-imgsize"

# Presets x their percentage caps (as fractions), read here only to build the RUNTIME
# formula in the browser — never to assert a literal pixel number of our own.
WIDTH_FRACTIONS = {"small": 0.25, "medium": 0.50, "large": 0.75, "full": 1.0}
HEIGHT_FRACTIONS = {"small": 0.30, "medium": 0.45, "large": 0.60, "full": 1.00}

DESKTOP = {"width": 1280, "height": 900}
PHONE = {"width": 360, "height": 640}


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


def _save_open_form(page):
    """Submit the open edit form and WAIT for the resulting fragment swap to land.

    The barrier keys on node IDENTITY, not on a selector. editor.js's applyFragments
    REPLACES both [data-scope] panes, so `wait_for_selector('figure.el--image')` is
    satisfied by the *pre-save* node still sitting in the DOM and returns immediately
    -- MEASURED: the pre-save figure reads isConnected === true when it resolves. The
    swap then lands later in the test, replacing the form under a subsequent click and
    resetting the preview figure to its server-rendered class (el--image--full), which
    is what made test_live_preview_survives_a_save_swap flaky under load: in isolation
    the swap arrives before the radio click, under load after it.

    Both call sites have a preview figure on screen when they save.
    """
    fig = page.locator('[data-scope="preview"] figure.el--image').element_handle()
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()
    # arg= is KEYWORD-ONLY on wait_for_function (unlike evaluate); positional raises.
    page.wait_for_function("el => !el.isConnected", arg=fig)


def _await_decoded(page, locator):
    """Wait for an <img> to actually have pixels before measuring it.

    locator.wait_for() defaults to state="visible", which only needs a non-empty box --
    and an <img> whose bytes have not arrived still gets one from its alt text, so
    naturalWidth can legitimately read 0. Measuring before this resolves races the
    decode: every box read below depends on it running first.
    """
    locator.wait_for()
    page.wait_for_function(
        "el => el.complete && el.naturalWidth > 0", arg=locator.element_handle()
    )


@pytest.fixture
def seeded(db, _isolated_media):
    """(owner, course, unit, tall, wide).

    Both dependencies are declared explicitly rather than relied on for autouse
    ordering, matching every seeding fixture in tests/test_e2e_imagezoom.py.
    `_isolated_media` must run BEFORE make_image_asset writes any bytes; `db` must run
    before any ORM call.
    """
    owner = _make_pa_user(PA_USERNAME)
    course, unit = _seed_unit(owner, "imgsize")
    tall = make_image_asset(course, "tall.png", size=(297, 719), color="magenta")
    wide = make_image_asset(course, "wide.png", size=(948, 719), color="magenta")
    for shape, asset in (("tall", tall), ("wide", wide)):
        for preset in ("small", "medium", "large", "full"):
            el = ImageElement.objects.create(
                media=asset, alt=f"{shape}-{preset}", size=preset
            )
            add_element(unit, el)
    return owner, course, unit, tall, wide


def _measure(page, shape, preset):
    """getBoundingClientRect() of the <img> identified by `alt="{shape}-{preset}"`,
    plus everything the formula needs read at runtime: the containing block's content
    width, the viewport height, and the image's own intrinsic size."""
    img = page.locator(f"img[alt='{shape}-{preset}']")
    _await_decoded(page, img)
    natural = img.evaluate("el => [el.naturalWidth, el.naturalHeight]")
    fig = img.locator("xpath=..")
    container = fig.locator("xpath=..")
    cw = container.evaluate("el => parseFloat(getComputedStyle(el).width)")
    vh = page.evaluate("window.innerHeight")
    rect = img.evaluate(
        "el => { const r = el.getBoundingClientRect(); return [r.width, r.height]; }"
    )
    return natural, cw, vh, rect


def _check_preset(page, shape, preset):
    """Return None if `shape-preset` matches the formula, else a description of the
    mismatch. A non-raising check (rather than a bare assert) so the caller can run
    every one of the sixteen combinations in one pass instead of stopping at the
    first failure -- the falsification step needs to see the WHOLE pass/fail matrix
    per mutant, not just its first casualty."""
    (nw, nh), cw, vh, (rw, rh) = _measure(page, shape, preset)
    ratio = nw / nh
    wcap = cw * WIDTH_FRACTIONS[preset]
    hcap = vh * HEIGHT_FRACTIONS[preset]
    h = min(hcap, wcap / ratio, nh)
    w = h * ratio
    if abs(rh - h) > 1 or abs(rw - w) > 1:
        return f"{shape}-{preset}: got {rw:.1f}x{rh:.1f}, want {w:.1f}x{h:.1f}"
    return None


def _assert_harness(page, tall, wide):
    """A 404'd image reports 0x0, so this distinguishes 'the preset is wrong' from
    'the fixture never loaded' -- without it every box assertion below would fail
    identically and uninformatively."""
    for shape, (want_w, want_h) in (("tall", (297, 719)), ("wide", (948, 719))):
        img = page.locator(f"img[alt='{shape}-small']")
        _await_decoded(page, img)
        nw, nh = img.evaluate("el => [el.naturalWidth, el.naturalHeight]")
        assert (nw, nh) == (want_w, want_h), f"{shape}: harness image is {nw}x{nh}"


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_preset_bounding_boxes(page, live_server, seeded, viewport):
    owner, course, unit, tall, wide = seeded
    _login(page, live_server, owner.username)
    page.set_viewport_size(viewport)
    page.goto(_lesson_url(live_server, unit))

    _assert_harness(page, tall, wide)

    failures = [
        msg
        for shape in ("tall", "wide")
        for preset in ("small", "medium", "large", "full")
        if (msg := _check_preset(page, shape, preset)) is not None
    ]
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Task 9: figure geometry, live preview, print, zoom, nested containers
# ---------------------------------------------------------------------------

# Centring tolerance for every "roughly centred" assertion in this task. A bare
# float == is flaky under sub-pixel layout; leaving "roughly equal" unpinned would
# hide a real off-centre bug.
CENTRE_TOL = 1


@pytest.fixture
def geom(db, seeded):
    """(owner, course, geom_unit, preview_unit, preview_join). `db` declared
    explicitly, same house precedent as `seeded`.

    geom_unit    -- rows 1-4 + row 6 (ten images; every one located by its unique alt)
    preview_unit -- row 5 only, so the editor page holds exactly one image row
    preview_join -- row 5's ELEMENT join row. Step 2's editor locator keys on
                    data-element-id, which is the join pk, NOT the alt and NOT the
                    ImageElement pk -- so it cannot be derived from anything else here.
    """
    owner, course, unit, tall, wide = seeded

    # Rows 1-4 (+ 6) go on a FRESH unit -- not Task 8's eight-image `unit` -- so
    # this task's alt locators never share a page with those images.
    geom_unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Geometry"
    )

    # Row 1: one figure per capped preset, no caption, tall fixture.
    for preset in ("small", "medium", "large"):
        add_element(
            geom_unit,
            ImageElement.objects.create(
                media=tall, alt=f"centred-{preset}", size=preset
            ),
        )

    # Row 2: a ~200-char caption made of ordinary spaced words -- an unbroken
    # 200-char token would overflow its figure and give the whole page a
    # horizontal scrollbar, a real side effect on other cases sharing this page.
    long_caption = ("a longer caption about the diagram " * 6)[:200]
    add_element(
        geom_unit,
        ImageElement.objects.create(
            media=tall, alt="captioned", size="small", figcaption=long_caption
        ),
    )

    # Row 3 reuses row 1's centred-small -- no new element.

    # Row 4: `full`, plain and captioned.
    add_element(
        geom_unit,
        ImageElement.objects.create(media=tall, alt="full-plain", size="full"),
    )
    add_element(
        geom_unit,
        ImageElement.objects.create(
            media=tall, alt="full-captioned", size="full", figcaption=long_caption
        ),
    )

    # Row 5: live preview -- its own unit inside Task 8's course, NOT `_seed_unit`
    # (which mints a whole new Course). MediaAsset is course-scoped and
    # builder.save_element passes course=course for images, so a fresh course
    # here would leave `wide` outside the rendered media queryset and every save
    # in Step 2 would 422.
    preview_unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Preview"
    )
    preview_join = add_element(
        preview_unit,
        ImageElement.objects.create(media=wide, alt="preview-target", size="full"),
    )

    # Row 6: one nested child per container, small preset, wide fixture.
    spoiler_join = add_element(geom_unit, SpoilerElement.objects.create(label="s"))
    Element.objects.create(
        unit=geom_unit,
        content_object=ImageElement.objects.create(
            media=wide, alt="nested-spoiler", size="small"
        ),
        parent=spoiler_join,
        tab_id=SpoilerElement.SLOT_ID,
    )

    callout_join = add_element(geom_unit, CalloutElement.objects.create(kind="note"))
    Element.objects.create(
        unit=geom_unit,
        content_object=ImageElement.objects.create(
            media=wide, alt="nested-callout", size="small"
        ),
        parent=callout_join,
        tab_id=CalloutElement.SLOT_ID,
    )

    # Tabs/two-column key children on a MINTED id: default_data() must be used
    # (a bare .objects.create() normalizes {} to an empty slot list, and
    # data["tabs"][0] would raise IndexError), and the id must be read off the
    # SAVED instance -- normalize_data() (read-side, destructive) would mint a
    # brand-new id at render time and silently orphan the child.
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = add_element(geom_unit, tabs)
    second_tab_id = tabs.data["tabs"][1]["id"]
    Element.objects.create(
        unit=geom_unit,
        content_object=ImageElement.objects.create(
            media=wide, alt="nested-tabs", size="small"
        ),
        parent=tabs_join,
        tab_id=second_tab_id,
    )

    twocol = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    twocol_join = add_element(geom_unit, twocol)
    first_col_id = twocol.data["columns"][0]["id"]
    Element.objects.create(
        unit=geom_unit,
        content_object=ImageElement.objects.create(
            media=wide, alt="nested-twocolumn", size="small"
        ),
        parent=twocol_join,
        tab_id=first_col_id,
    )

    return owner, course, geom_unit, preview_unit, preview_join


def _rect(locator):
    return locator.evaluate("el => el.getBoundingClientRect()")


def _assert_centred(inner_rect, outer_rect, label):
    left = inner_rect["left"] - outer_rect["left"]
    right = outer_rect["right"] - inner_rect["right"]
    assert abs(left - right) <= CENTRE_TOL, (
        f"{label}: left offset {left:.2f} vs right offset {right:.2f}"
    )


def test_figure_geometry(page, live_server, geom):
    owner, course, geom_unit, _preview_unit, _preview_join = geom
    _login(page, live_server, owner.username)
    page.set_viewport_size(DESKTOP)
    page.goto(_lesson_url(live_server, geom_unit))

    # --- figure centred (no caption), one per capped preset. The ONLY coverage
    # of the figure-centring rule: Task 8's box assertions check dimensions, not
    # position, and stay green with the figure rule deleted. div.lesson-block__body
    # is fig.parentElement, the same containing block Task 8 measures.
    for preset in ("small", "medium", "large"):
        img = page.locator(f"img[alt='centred-{preset}']")
        _await_decoded(page, img)
        fig = img.locator("xpath=..")
        container = fig.locator("xpath=..")
        _assert_centred(_rect(fig), _rect(container), f"centred-{preset}")

    # --- image centred under a long caption: the figcaption widens the figure
    # past the (unconstrained) image, and only a long caption exercises this.
    cap_img = page.locator("img[alt='captioned']")
    _await_decoded(page, cap_img)
    cap_fig = cap_img.locator("xpath=..")
    _assert_centred(_rect(cap_img), _rect(cap_fig), "captioned image-in-figure")

    # No-caption, height-bound centring case: DELETED. Measured at 1280x900,
    # small, tall fixture (centred-small, reused from row 1): figure width
    # ~111.52px vs image width ~111.50px -- equal within the 1px centring
    # tolerance, i.e. Chromium's fit-content figure shrink-wraps to the image's
    # CONSTRAINED contribution, not its unconstrained max-content contribution.
    # Both offsets are therefore 0 by construction, the assertion would pass
    # vacuously, and no mutant could redden it (branch 3 of Task 9 Step 1;
    # see the commit message). Reason 2 is removed from Task 5's img
    # margin-inline comment in courses.css for the same reason: this
    # measurement disproves it as a real path to a figure wider than its image.

    # --- `full` unchanged: stated as concrete post-conditions, since there is
    # no earlier run to diff against.
    plain_img = page.locator("img[alt='full-plain']")
    _await_decoded(page, plain_img)
    plain_fig = plain_img.locator("xpath=..")
    plain_container = plain_fig.locator("xpath=..")
    plain_fig_rect = _rect(plain_fig)
    plain_container_rect = _rect(plain_container)
    # PC1: the figure did NOT shrink-wrap -- its width equals the containing
    # block's content width (`full` is excluded from the fit-content group).
    assert abs(plain_fig_rect["width"] - plain_container_rect["width"]) <= CENTRE_TOL, (
        f"full-plain figure width {plain_fig_rect['width']:.2f} != "
        f"container width {plain_container_rect['width']:.2f}"
    )
    # PC2: the figure carries no margin-inline:auto -- its left offset is 0.
    plain_left_offset = plain_fig_rect["left"] - plain_container_rect["left"]
    assert abs(plain_left_offset) <= CENTRE_TOL, (
        f"full-plain figure left offset {plain_left_offset:.2f}"
    )

    # PC3 is measured on `full-captioned`, not `full-plain`: `full-plain`'s
    # figure spans the whole column against a much narrower image and is never
    # "exactly as wide as the image", so PC3 would be trivially unfalsifiable
    # there. `full` is excluded from the `fit-content` group, so in the shipped
    # build the figure is an ordinary block spanning the column regardless of
    # the caption; PC3 pins the image's own offset inside it. (The `fit-content`
    # reasoning only applies under the Task-9 falsification mutant that adds
    # `full` to that group -- there, the ~200-char caption's max-content
    # contribution would exceed the column, so `fit-content` would still
    # resolve to the full column width.)
    captioned_full_img = page.locator("img[alt='full-captioned']")
    _await_decoded(page, captioned_full_img)
    captioned_full_fig = captioned_full_img.locator("xpath=..")
    cf_img_rect = _rect(captioned_full_img)
    cf_fig_rect = _rect(captioned_full_fig)
    assert abs(cf_img_rect["left"] - cf_fig_rect["left"]) <= CENTRE_TOL, (
        f"full-captioned image left offset "
        f"{cf_img_rect['left'] - cf_fig_rect['left']:.2f}"
    )


def _open_existing_element_form(page, preview_join):
    """Open row 5's edit form. `button.el-select[data-element-id=...]` matches
    BOTH the icon button and the label button (_element_row.html), so this
    scopes to the label's own class -- the icon button variant would raise a
    Playwright strict-mode violation."""
    page.locator(f"button.el-row__label[data-element-id='{preview_join.pk}']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")


def test_live_preview_updates_without_a_save(page, live_server, geom):
    """Changing a radio updates the preview figure's class with NO save. Both
    this case and test_live_preview_survives_a_save_swap already sit PAST the
    fragment-swap seam: opening an existing element's form is itself a full
    fragment swap (editor.js applyFragments replaces both [data-scope] panes),
    so by the time the radio is clicked one swap has already happened. What
    distinguishes the two cases is the trigger -- a form-open swap here, a save
    swap in the other test -- not before/after the seam."""
    owner, course, _geom_unit, preview_unit, preview_join = geom
    _login(page, live_server, owner.username)  # editor is manage-gated
    page.set_viewport_size(DESKTOP)
    page.goto(_editor_url(live_server, course, preview_unit))

    _open_existing_element_form(page, preview_join)

    fig = page.locator('[data-scope="preview"] figure.el--image')
    assert "el--image--full" in (fig.get_attribute("class") or "")

    saves = []
    page.on(
        "request",
        lambda r: (
            saves.append(r.url)
            if r.method == "POST" and "/build/element/save/" in r.url
            else None
        ),
    )

    page.locator("[data-edit-slot] input[data-size-preset][value='small']").click()
    # Assert the class change first -- a real barrier proving the handler ran --
    # before reading the (asynchronous) request recorder.
    assert "el--image--small" in (fig.get_attribute("class") or "")
    assert "el--image--full" not in (fig.get_attribute("class") or "")
    assert saves == [], f"radio click fired a save: {saves}"

    # Positive control: prove the recorder's filter string actually matches a
    # real save request -- without this, a recorder watching the wrong
    # substring reports zero forever and the assertion above is vacuous.
    _save_open_form(page)
    page.wait_for_selector('[data-scope="preview"] figure.el--image.el--image--small')
    assert len(saves) == 1, f"expected exactly one save POST, got {saves}"


def test_live_preview_survives_a_save_swap(page, live_server, geom):
    """After a real save's fragment swap, opening the form again and changing
    the preset still updates the preview class. Only the preceding trigger
    (save vs form-open) differs from the case above; the assertion is the
    same."""
    owner, course, _geom_unit, preview_unit, preview_join = geom
    _login(page, live_server, owner.username)
    page.set_viewport_size(DESKTOP)
    page.goto(_editor_url(live_server, course, preview_unit))

    _open_existing_element_form(page, preview_join)
    # _save_open_form waits for the save's fragment swap to LAND (by node identity).
    # A `wait_for_selector('figure.el--image')` here would not: the pre-save figure is
    # still in the DOM, so it resolves instantly and the swap arrives mid-test.
    _save_open_form(page)

    _open_existing_element_form(page, preview_join)
    fig = page.locator('[data-scope="preview"] figure.el--image')
    page.locator("[data-edit-slot] input[data-size-preset][value='medium']").click()
    assert "el--image--medium" in (fig.get_attribute("class") or "")
    assert "el--image--full" not in (fig.get_attribute("class") or "")


def test_print_media_uses_mm_caps(page, live_server, geom):
    """Under print media the resolved max-height is the mm value, converted to
    px (getComputedStyle never reports mm), not the dvh one -- a source scan
    cannot prove the print rule wins the specificity tie. Run at 1280x900 only:
    the "not the screen value" guard needs headroom that a phone viewport does
    not give it (medium's screen value would sit only 4.5px from its print
    value there)."""
    owner, course, geom_unit, _preview_unit, _preview_join = geom
    _login(page, live_server, owner.username)
    page.set_viewport_size(DESKTOP)
    page.goto(_lesson_url(live_server, geom_unit))

    alt_for_preset = {
        "small": "centred-small",
        "medium": "centred-medium",
        "large": "centred-large",
        "full": "full-plain",
    }
    mm_for_preset = {"small": 45, "medium": 75, "large": 110, "full": 170}

    page.emulate_media(media="print")

    for preset, alt in alt_for_preset.items():
        img = page.locator(f"img[alt='{alt}']")
        got = img.evaluate("el => parseFloat(getComputedStyle(el).maxHeight)")
        want = mm_for_preset[preset] * 96 / 25.4
        assert abs(got - want) <= 1, (
            f"{preset}: print max-height {got:.1f} != {want:.1f}"
        )
        screen_value = HEIGHT_FRACTIONS[preset] * DESKTOP["height"]
        assert abs(got - screen_value) > 1, (
            f"{preset}: print value {got:.1f} matches screen value {screen_value:.1f}"
        )


def test_zoom_overlay_ignores_the_preset(page, live_server, geom):
    """The zoom overlay is unaffected by the preset -- measured, not asserted as
    a mood. imagezoom.js's build() creates a fresh img.imgzoom__img appended to
    document.body, so the overlay carries no el--image--* class and has no
    .el--image ancestor (the STRUCTURAL reason the presets cannot reach it),
    and its rendered height is strictly greater than the in-page figure's."""
    owner, course, geom_unit, _preview_unit, _preview_join = geom
    _login(page, live_server, owner.username)
    page.set_viewport_size(DESKTOP)
    page.goto(_lesson_url(live_server, geom_unit))

    trigger = page.locator("img[alt='centred-small'][data-zoomable]")
    _await_decoded(page, trigger)
    fig = trigger.locator("xpath=..")
    fig_height = _rect(fig)["height"]

    trigger.click()
    page.wait_for_selector("dialog.imgzoom[open]")
    page.wait_for_function(
        "() => { const i = document.querySelector('.imgzoom__img');"
        " return i && i.complete && i.naturalWidth > 0; }"
    )

    overlay = page.locator(".imgzoom__img")
    classes = overlay.evaluate("el => Array.from(el.classList)")
    assert not any(c.startswith("el--image") for c in classes), classes
    assert overlay.evaluate("el => el.closest('.el--image')") is None

    overlay_height = _rect(overlay)["height"]
    assert overlay_height > fig_height, (
        f"overlay height {overlay_height:.1f} not greater than "
        f"figure height {fig_height:.1f}"
    )


def _check_nested_small(page, alt):
    """Task 8's box formula, generalised to any alt and pinned to `small`:
    `wcap` reads the containing block off fig.parentElement (the per-child
    wrapper, e.g. .spoiler__child) so it IS container-relative; `hcap` stays
    viewport-derived (max-height is authored in dvh) and does not shrink with
    nesting depth. Returns None on a match, else a mismatch description -- a
    non-raising check (mirrors _check_preset) so a mutant's WHOLE footprint
    across all four containers is visible in one run, not just its first
    casualty."""
    img = page.locator(f"img[alt='{alt}']")
    _await_decoded(page, img)
    nw, nh = img.evaluate("el => [el.naturalWidth, el.naturalHeight]")
    fig = img.locator("xpath=..")
    wrapper = fig.locator("xpath=..")
    cw = wrapper.evaluate("el => parseFloat(getComputedStyle(el).width)")
    vh = page.evaluate("window.innerHeight")
    rw, rh = img.evaluate(
        "el => { const r = el.getBoundingClientRect(); return [r.width, r.height]; }"
    )
    ratio = nw / nh
    wcap = cw * WIDTH_FRACTIONS["small"]
    hcap = vh * HEIGHT_FRACTIONS["small"]
    h = min(hcap, wcap / ratio, nh)
    w = h * ratio
    if abs(rh - h) > 1 or abs(rw - w) > 1:
        return f"{alt}: got {rw:.1f}x{rh:.1f}, want {w:.1f}x{h:.1f}"
    return None


def test_nested_images_scale_to_their_container(page, live_server, geom):
    """A nested `small` image scales to its container on the width axis (the
    containing block a nesting wrapper provides) while its height cap stays
    viewport-derived (dvh) at every nesting depth -- one case each for spoiler,
    callout, tabs and two-column."""
    owner, course, geom_unit, _preview_unit, _preview_join = geom
    _login(page, live_server, owner.username)
    page.set_viewport_size(DESKTOP)
    page.goto(_lesson_url(live_server, geom_unit))

    # Callout and two-column render unconditionally. A closed <details> hides
    # via content-visibility (a zeroed box, not merely an invisible one) and an
    # inactive tab panel has no layout box at all -- open the spoiler and
    # activate the (second) tab the nested child lives in before measuring.
    page.locator("details.spoiler > summary").click()
    page.get_by_role("tab", name="Tab 2").click()

    failures = []
    for alt in ("nested-spoiler", "nested-callout", "nested-tabs", "nested-twocolumn"):
        img = page.locator(f"img[alt='{alt}']")
        page.wait_for_function("el => el.checkVisibility()", arg=img.element_handle())
        msg = _check_nested_small(page, alt)
        if msg is not None:
            failures.append(msg)
    assert not failures, "\n".join(failures)
