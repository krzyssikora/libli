"""Playwright e2e for click-to-enlarge images.

Media IS served under live_server, regardless of DEBUG: django.test.testcases.
LiveServerThread.run() (django/test/testcases.py:1755) unconditionally builds
`self.static_handler(_MediaFilesHandler(WSGIHandler()))` -- no DEBUG check anywhere in
that chain. `_MediaFilesHandler.get_base_dir()`/`get_base_url()`
(django/test/testcases.py:1716-1726) return `settings.MEDIA_ROOT`/`settings.MEDIA_URL`
at request time, so `/media/<path>` is served straight from `MEDIA_ROOT` via
django.views.static.serve, entirely bypassing this project's own config/urls.py (whose
DEBUG-gated route only matters for a real dev/prod server). This means `_isolated_media`
is not just about not polluting the developer's real media/ tree: it is *also* what
makes the fixture images resolve at all, because `_MediaFilesHandler` reads
`settings.MEDIA_ROOT` per request -- point it at tmp_path and that is what gets served.
No Playwright-level route interception is needed or present; every `naturalWidth`
assertion below is a live guard against a MEDIA_ROOT misconfiguration or a
wrongly-sized fixture, not a workaround for a serving gap that does not exist.

Focus placement via locator.focus()/blur() is sanctioned SETUP here: several cases need
a trigger focused but not activated, and a real click on an armed image opens the
overlay. The interaction under test -- the click, the keypress, the wheel -- is always
real. The one exception is the Tab-traversal cases, which must use real Tab presses
because the tab order IS what they test.

Marked e2e (excluded from the default run). Run focused and in the FOREGROUND -- a
background `-m e2e` sweep spawns runaway browsers.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_quiz_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

VIEWPORT = {"width": 1280, "height": 800}
BIG = (1400, 900)
MAGENTA = "#FF00FF"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists. Two independent reasons, both real:

    1. make_image_asset writes its bytes through the FileField at create() time, so an
       override applied later would drop a 1400x900 PNG into the developer's real
       media/ tree.
    2. live_server's `_MediaFilesHandler` (see the module docstring) reads
       `settings.MEDIA_ROOT` per request to decide what `/media/<path>` serves -- this
       fixture pointing it at tmp_path is what makes a freshly created fixture image
       resolve at all, not an optional convenience.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


# _student / _lesson_url / _login are defined here rather than imported from
# tests/test_e2e_gallery.py: this module needs a user OBJECT (for EnrollmentFactory),
# not a username, and every e2e module in this repo is deliberately self-contained.
# The login helper is the same scoped-form version that module uses.
def _student(username="zoomstudent"):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _quiz_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _login(page, live_server, user):
    # Scope to the login form. base.html renders one <button type="submit"
    # name="language"> per enabled language in the header (templates/base.html:60-67),
    # and page.click is non-strict -- an unscoped click POSTs the language switcher and
    # reloads the login page with nobody authenticated. Mirrors the proven helper at
    # tests/test_e2e_editor.py:38-47.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(user.username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _image_unit(
    course, size=BIG, color=MAGENTA, alt="A labelled diagram", name="z.png"
):
    from courses.models import ImageElement

    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename=name, size=size, color=color)
    add_element(unit, ImageElement.objects.create(media=asset, alt=alt))
    return unit


@pytest.fixture
def zoom_lesson(db, _isolated_media):
    """One lesson unit, one ImageElement, 1400x900 magenta, non-empty alt.

    _isolated_media is listed explicitly, not relied on as autouse-ordering: the asset
    is written through the FileField at create() time, and a silent mis-ordering would
    drop a 1400x900 PNG into the developer's real media/ tree.
    """
    course = CourseFactory()
    unit = _image_unit(course)
    user = _student()
    EnrollmentFactory(course=course, student=user)
    return unit, user


def _goto(page, live_server, unit, user):
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_lesson_url(live_server, unit))


def _trigger(page):
    return page.locator("[data-zoomable]").first


def _open(page, trigger):
    trigger.click()
    page.wait_for_selector("dialog.imgzoom[open]")
    # The [open] attribute is set synchronously, but the overlay <img> still has to
    # request and decode its bytes, so measuring immediately can read naturalWidth == 0
    # and a zero-area box regardless of who serves the file. Wait for the decode before
    # any geometry is taken.
    page.wait_for_function(
        "() => { const i = document.querySelector('.imgzoom__img');"
        " return i && i.complete && i.naturalWidth > 0; }"
    )
    return page.locator("dialog.imgzoom")


def _await_decoded(page, locator):
    """Wait for an <img> to actually have pixels before measuring it.

    locator.wait_for() defaults to state="visible", which only needs a non-empty box --
    and an <img> whose bytes have not arrived still gets one from its alt text, so
    naturalWidth can legitimately read 0. This race is real independent of who serves
    the bytes (see the module docstring): a fresh request always needs a round trip and
    a decode, and it applies to the inline trigger exactly as it does to the overlay
    image.
    """
    locator.wait_for()
    page.wait_for_function(
        "el => el.complete && el.naturalWidth > 0", arg=locator.element_handle()
    )


def _await_closed(page):
    """Wait until the dialog's `close` HANDLER has finished, not merely until it shut.

    `dialog.close()` removes the `open` attribute SYNCHRONOUSLY but only QUEUES the
    `close` event as a task, so `wait_for_selector("dialog.imgzoom[open]",
    state="detached")` returns while the handler may not have run yet. Anything the
    handler produces — the `src` removal, the focus restore, dropping the
    `imgzoom-open` class — is therefore racy to assert right after that wait.

    CI caught this that the serial local runs did not: under `-n 2` on a loaded runner,
    `test_close_removes_the_src_attribute` read the still-present src.

    `imgzoom-open` is removed LAST in the handler, so its absence proves every earlier
    step already ran. Wait on that.
    """
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('imgzoom-open')"
    )


def _box(locator):
    box = locator.bounding_box()
    assert box is not None, "expected a laid-out box"
    return box


def _natural_width(locator):
    return locator.evaluate("el => el.naturalWidth")


def test_harness_serves_the_real_fixture_image(page, live_server, zoom_lesson):
    """The precondition every geometry case depends on.

    Django's live_server serves /media/ from MEDIA_ROOT on its own (see the module
    docstring), so this assertion is not a workaround for a serving gap -- it is a live
    guard against a MEDIA_ROOT misconfiguration (e.g. _isolated_media mis-ordered
    relative to asset creation) or a fixture built at the wrong size: either would
    surface here as naturalWidth != 1400 instead of silently measuring the wrong image.
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    _await_decoded(page, trigger)
    assert _natural_width(trigger) == 1400


def test_closed_dialog_is_not_rendered(page, live_server, zoom_lesson):
    """Open, close, THEN assert -- the dialog is created lazily.

    Asserting "absent or invisible" before the first open would be vacuous: it passes
    even with `display: grid` unscoped, which is the very bug this case exists to catch.
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    dialog = _open(page, _trigger(page))
    dialog.click()
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")

    assert dialog.evaluate("el => el.checkVisibility()") is False
    assert dialog.bounding_box() is None  # display:none -> None, not a zero-area box


def test_overlay_enlarges_without_upscaling_and_fits_the_viewport(
    page, live_server, zoom_lesson
):
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    _await_decoded(page, trigger)  # or inline_width is measured pre-load and the
    assert _natural_width(trigger) == 1400, "media route must serve the real image"
    # "overlay is wider" would pass for the wrong reason if measured before decode.
    inline_width = _box(trigger)["width"]

    dialog = _open(page, trigger)
    img = page.locator(".imgzoom__img")
    box = _box(img)

    assert box["width"] > inline_width, "the overlay must actually enlarge"
    assert box["width"] <= _natural_width(img) + 0.5, "never upscaled past natural size"

    # Half-pixel tolerance is not decoration: for this fixture the vertical axis sits
    # EXACTLY at the 800px cap and the 0.888... scale factor rounds at device-pixel
    # resolution. Only the horizontal axis has real slack.
    assert box["x"] >= -0.5 and box["y"] >= -0.5
    assert box["x"] + box["width"] <= VIEWPORT["width"] + 0.5
    assert box["y"] + box["height"] <= VIEWPORT["height"] + 0.5

    # The dialog itself must fill the scrollbar-EXCLUDED ICB. This, not the image box,
    # is what a `100vw` regression violates: with width:100vw the dialog spans 1280
    # while the ICB is ~1265, yet the height-capped image still centres inside it and
    # every image-box assertion above stays green.
    client_width = page.evaluate("() => document.documentElement.clientWidth")
    assert abs(_box(dialog)["width"] - client_width) <= 0.5

    # Centred in the VIEWPORT, not merely inside the dialog: an in-dialog check is
    # invariant to a fit-content dialog (both of its internal bands are 0) sitting
    # flush left.
    right_band = client_width - box["x"] - box["width"]
    assert abs(box["x"] - right_band) <= 1

    # Aspect ratio survives, so a stretched image is caught however an engine treats
    # grid stretching of a replaced element.
    assert abs(box["width"] / box["height"] - 1400 / 900) < 0.01


def test_nothing_but_the_image_is_visible(page, live_server, zoom_lesson, tmp_path):
    """checkVisibility() cannot express this -- a modal <dialog> makes the rest of the
    document inert, not unrendered, so the lesson article still reports visible. Assert
    occlusion two independent ways instead.
    """
    from PIL import Image

    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    dialog = _open(page, _trigger(page))
    img = page.locator(".imgzoom__img")
    box = _box(img)

    # (a) the resolved scrim colour, read from the token rather than hardcoded so a
    # design-pass retune cannot turn this red.
    token = page.evaluate(
        "() => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--scrim-solid').trim()"
    )
    expected = [int(n) for n in token.split("(")[1].split(")")[0].split(",")[:3]]
    alpha = float(token.split(",")[-1].strip(") "))
    assert alpha >= 0.95, f"scrim must be near-opaque, got {token}"

    resolved = dialog.evaluate("el => getComputedStyle(el).backgroundColor")
    got = [int(n) for n in resolved.split("(")[1].split(")")[0].split(",")[:3]]
    assert all(abs(a - b) <= 12 for a, b in zip(got, expected, strict=True)), (
        resolved,
        token,
    )
    # Relative luminance, the third spec invariant: it is what catches a retune to a
    # LIGHT scrim that still matches its own token.
    lum = (0.2126 * got[0] + 0.7152 * got[1] + 0.0722 * got[2]) / 255
    assert lum < 0.05, f"scrim must be dark, luminance {lum:.3f}"
    # Asserting alpha alone would be untestable: the UA gives dialog an OPAQUE
    # `background-color: Canvas`, so deleting the author background leaves alpha at 1.0
    # and renders an opaque WHITE panel. Hence the channel check.

    # (b) pixel sampling in the letterbox bands beside the measured image box -- NOT
    # where the article text sits, which at this viewport is entirely behind the image.
    # Pin the assumption the coordinate mapping rests on rather than trusting a default.
    assert page.evaluate("() => devicePixelRatio") == 1
    assert box["x"] >= 6, f"letterbox band too narrow to sample: x={box['x']}"
    client_width = page.evaluate("() => document.documentElement.clientWidth")
    right_start = box["x"] + box["width"] + 2
    assert right_start <= client_width - 2, (
        f"right letterbox band too narrow to sample: {right_start} vs {client_width}"
    )
    shot = tmp_path / "imgzoom-occlusion.png"  # never the repo root
    dialog.screenshot(path=str(shot))
    frame = Image.open(shot).convert("RGB")
    left_xs = [2, int(box["x"] / 2), int(box["x"]) - 3]
    right_xs = [
        int(right_start),
        int((right_start + client_width - 2) / 2),
        int(client_width) - 3,
    ]
    ys = [2, int(box["height"] / 2), int(box["height"]) - 3]
    for x in left_xs + right_xs:
        for y in ys:
            px = frame.getpixel((x, y))
            assert all(abs(a - b) <= 12 for a, b in zip(px, expected, strict=True)), (
                x,
                y,
                px,
            )


@pytest.fixture
def tall_lesson(db, _isolated_media):
    """zoom_lesson plus enough text that the page scrolls at 1280x800."""
    from courses.models import TextElement

    course = CourseFactory()
    unit = _image_unit(course)
    for i in range(12):
        text = TextElement.objects.create(body=f"<p>Filler paragraph {i}.</p>")
        add_element(unit, text)
    user = _student("tallstudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user


def test_second_click_closes_and_restores_focus(page, live_server, zoom_lesson):
    """Smoke test of the close path.

    This case CANNOT falsify the explicit `trigger.focus()`, and no Chromium e2e can:
    Chromium focuses the trigger on mousedown -- after any blur, before the delegated
    handler runs showModal() -- so the recorded pre-open focus is the trigger and the
    native restore satisfies this even with our line deleted. The source-level assertion
    in tests/test_imagezoom_render.py is the sole guard on it.
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    dialog = _open(page, trigger)
    dialog.click()
    _await_closed(page)
    assert trigger.evaluate("el => el === document.activeElement")


def test_escape_closes_the_overlay(page, live_server, zoom_lesson):
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    _open(page, _trigger(page))
    page.keyboard.press("Escape")
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")


def test_escape_does_not_also_close_the_unit_drawer(page, live_server, zoom_lesson):
    """The only guard on the stopImmediatePropagation decision.

    The gesture is spelled out because the obvious one is impossible: an open drawer is
    position:fixed; inset:0; z-index:50 with a full-viewport scrim carrying
    data-unit-drawer-close, so a real click on the image lands on the scrim and closes
    the drawer instead. Opening the overlay first is impossible too -- a modal <dialog>
    makes the document inert. So: focus the trigger (sanctioned setup) and press Enter.
    """
    unit, user = zoom_lesson
    page.set_viewport_size({"width": 390, "height": 844})  # drawer only exists <=640px
    _login(page, live_server, user)
    page.goto(_lesson_url(live_server, unit))

    page.click("[data-unit-drawer-open]")
    drawer = page.locator(".unit-drawer")
    assert drawer.evaluate("el => !el.hidden")

    _trigger(page).focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("dialog.imgzoom[open]")

    page.keyboard.press("Escape")
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")
    assert drawer.evaluate("el => !el.hidden"), "one Escape closed the drawer too"


def test_double_click_opens_then_closes(page, live_server, zoom_lesson):
    """The accepted behaviour: the second click lands on the now-covering dialog."""
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)

    # Positive control first, or this test cannot tell "opened then closed" from "never
    # opened at all": a 404'd script, a bailed feature detect or a deleted click handler
    # would all leave the count at 0 and read as GREEN.
    box = _box(trigger)
    point = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    trigger.click()
    page.wait_for_selector("dialog.imgzoom[open]")  # proves the open really happens
    page.keyboard.press("Escape")
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")

    page.mouse.dblclick(*point)
    assert page.locator("dialog.imgzoom[open]").count() == 0


def test_enter_opens_from_the_keyboard(page, live_server, zoom_lesson):
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    _trigger(page).focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("dialog.imgzoom[open]")


def test_accessible_names(page, live_server, zoom_lesson):
    """Non-empty-alt branch here; the empty-alt branch is on the gallery fixture."""
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    page.get_by_role("button", name="A labelled diagram").wait_for()
    _open(page, _trigger(page))
    # The dialog is named for the CONTROL, never with the image's alt -- naming both
    # would make a screen reader read the description twice on entry.
    dialog = page.locator("dialog.imgzoom")
    assert dialog.get_attribute("aria-label") == "Enlarged image"


def test_focus_cannot_reach_the_page_behind_the_overlay(page, live_server, zoom_lesson):
    """Replaces an earlier assertion that claimed a focus TRAP -- i.e. that
    document.activeElement stays inside dialog.imgzoom under Tab. Measured: it does not.
    The overlay's only content is a non-focusable <img>, so showModal() has zero
    focusable descendants to place focus on, and in this Chromium the first Tab moves
    document.activeElement to <body> and leaves it there. That is harmless, not a bug:
    the rest of the document is inert while the dialog is modal, so <body> and the
    dialog itself are the only two places activeElement can land -- nothing on the page
    BEHIND the overlay (the lesson article) ever becomes reachable. Escape still closes
    the overlay, and its `close` handler explicitly restores focus to the trigger. What
    actually matters for the user is inertness, not which inert-adjacent node currently
    holds activeElement, so that is what this asserts.
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)

    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    moved = page.evaluate("() => document.activeElement !== document.body")
    assert moved, "positive control: Tab must move focus on the closed page"

    _open(page, _trigger(page))
    for _ in range(2):
        page.keyboard.press("Tab")
        outside_page_content = page.evaluate(
            "() => { const e = document.activeElement; "
            "const lesson = document.querySelector('article.lesson'); "
            "return !lesson || !lesson.contains(e); }"
        )
        assert outside_page_content, (
            "focus reached content on the page behind the overlay"
        )


def test_close_removes_the_src_attribute(page, live_server, zoom_lesson):
    """`img.src = ""` would resolve against the document URL and refetch the HTML page
    as an image on every close."""
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    dialog = _open(page, _trigger(page))
    dialog.click()
    _await_closed(page)
    assert page.locator(".imgzoom__img").get_attribute("src") is None


def test_the_page_behind_does_not_scroll(page, live_server, tall_lesson):
    """Tests the platform claim rather than trusting it. The positive control IS the
    falsification: there is no line of ours to delete."""
    unit, user = tall_lesson
    _goto(page, live_server, unit, user)
    assert page.evaluate(
        "() => document.documentElement.scrollHeight > window.innerHeight"
    ), "fixture must be taller than the viewport or scrollY is 0 either way"

    _open(page, _trigger(page))
    before = page.evaluate("() => window.scrollY")
    page.mouse.move(VIEWPORT["width"] / 2, VIEWPORT["height"] / 2)
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(150)
    assert page.evaluate("() => window.scrollY") == before

    page.keyboard.press("Escape")
    _await_closed(
        page
    )  # the lock is dropped in the close handler; settle before scrolling
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(150)
    assert page.evaluate("() => window.scrollY") > before, "positive control failed"


@pytest.fixture
def gallery_lesson(db, _isolated_media):
    """Anchor link, then a 3-figure gallery.

    Figure 1 is active on load and carries an EMPTY description -> empty alt: that is
    the decorative branch, and it must be the ACTIVE figure because inactive figures are
    aria-hidden and Playwright's role engine cannot see them at all.

    Gallery alt is NOT authorable: GalleryElement stores {media, desc} and render()
    derives alt = desc_to_alt(desc), substituting a generic "Image n of m" when a
    non-empty desc strips to nothing. So an empty alt requires an EMPTY desc, and a
    math-only desc must be avoided.

    No <a href> in any description: GalleryElement.save() sanitises each desc through
    sanitize_cell, whose allowlist is CELL_TAGS = {strong, b, em, i, u, br, span} with
    attributes={} (courses/sanitize.py:98) -- a link would be silently stripped to bare
    text, so a fixture "carrying a link" would document a case it does not have.
    """
    from courses.models import GalleryElement
    from courses.models import TextElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    add_element(
        unit, TextElement.objects.create(body='<p><a href="#">Anchor link</a></p>')
    )
    descs = ["", "Second figure", "Third figure"]
    colors = ["#FF00FF", "#00FF00", "#0000FF"]
    images = [
        {
            "media": make_image_asset(
                course, filename=f"gal{i}.png", size=(800, 600), color=colors[i]
            ).pk,
            "desc": desc,
        }
        for i, desc in enumerate(descs)
    ]
    add_element(
        unit,
        GalleryElement.objects.create(data={"images": images, "desc_pos": "below"}),
    )
    user = _student("gallerystudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user


@pytest.fixture
def hidden_lesson(db, _isolated_media):
    """DOM order is LOAD-BEARING and fixed: anchor, tabs, spoiler, then the reveal gate
    with the gated image LAST.

    The gate's rule is
    `.slide > .lesson-block:has(...) ~ .lesson-block:not(.reveal-shown)
    { display: none }` -- a GENERAL SIBLING combinator over blocks that
    _lesson_article.html wraps in `.slide > .lesson-block`. So the gate hides
    EVERY later block in the unit, not just its own answer: anything placed
    after it would be display:none and its positive control would fail for a
    reason unrelated to this feature, while its negative half passed vacuously.

    NO STEPPER IMAGE, deliberately. StepperStep.content is a CharField of
    plain text + KaTeX (courses/models.py:503-508) -- a stepper step cannot
    contain an element at all, so no image can ever be hidden by the stepper
    mechanism and there is nothing for this feature to test there. The
    stepper row of the spec's hiding table stays true (it does hide steps)
    but is unreachable by an image, which is why no stepper case follows.
    """
    from courses.models import Element
    from courses.models import ImageElement
    from courses.models import RevealGateElement
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from courses.models import TextElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")

    def img(name):
        asset = make_image_asset(
            course, filename=name, size=(400, 300), color="#00FFFF"
        )
        return ImageElement.objects.create(media=asset, alt=f"Hidden {name}")

    add_element(
        unit, TextElement.objects.create(body='<p><a href="#">Anchor link</a></p>')
    )

    # Tabs: default_data() MINTS its own tab ids (new_tab_id -> "t" + 6 hex), so
    # read them back rather than assuming literals, and key the child to the
    # SECOND tab so it lands in the panel that ships [hidden]. Nesting pattern:
    # tests/test_e2e_tabs.py:110.
    tabs_obj = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = add_element(unit, tabs_obj)
    second_tab_id = tabs_obj.data["tabs"][1]["id"]
    Element.objects.create(
        unit=unit,
        content_object=img("tabbed.png"),
        parent=tabs_join,
        tab_id=second_tab_id,
    )

    # Spoiler: `label`, not `summary` (courses/models.py:397-408), and its single child
    # slot id is SpoilerElement.SLOT_ID == "only".
    spoiler_join = add_element(unit, SpoilerElement.objects.create(label="Show"))
    Element.objects.create(
        unit=unit,
        content_object=img("spoilered.png"),
        parent=spoiler_join,
        tab_id=SpoilerElement.SLOT_ID,
    )

    # The gate hides every FOLLOWING sibling, so it goes second-to-last and its answer
    # image last.
    add_element(unit, RevealGateElement.objects.create(label="Show answer"))
    add_element(unit, img("gated.png"))

    # Ordering comes from creation sequence: Element.order is
    # OrderField(for_fields=["unit"]) with Meta.ordering = ["order", "pk"], and
    # nested child rows consume numbers from the same per-unit counter -- which
    # is why each container's child is created immediately after the container
    # above, keeping the top-level sequence monotonic.
    user = _student("hiddenstudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user


def _tab_walk(page, n=24):
    """Press Tab up to n times from the current focus, recording each activeElement.

    A single <body>/null observation is a WRAP, not an exit (Chromium passes
    through it), so continue; only two consecutive such observations terminate.

    `cls` reads getAttribute('class') rather than a.className, because on an
    SVG element className is an SVGAnimatedString and would not serialise as
    a string. It is only used for debugging output, but a silently-empty
    field is worse than none.
    """
    seen = []
    blanks = 0
    for _ in range(n):
        page.keyboard.press("Tab")
        info = page.evaluate(
            "() => { const a = document.activeElement;"
            " if (!a || a === document.body) return null;"
            " const item = a.closest('.gallery__item');"
            " return { tag: a.tagName, cls: a.getAttribute('class') || '',"
            "   alt: a.getAttribute('alt') || '',"
            "   inInactiveFigure: !!(item && !item.classList.contains('is-active')),"
            "   isTrigger: a.classList.contains('imgzoom-trigger'),"
            "   inHiddenPanel: !!a.closest('[hidden]') }; }"
        )
        if info is None:
            blanks += 1
            if blanks >= 2:
                break
            continue
        blanks = 0
        seen.append(info)
    return seen


def test_only_the_active_gallery_figure_is_a_tab_stop(
    page, live_server, gallery_lesson
):
    """A get_by_role("button") COUNT is not a valid test here: inactive figures already
    carry aria-hidden today and Playwright's role engine excludes ARIA-hidden elements,
    so that assertion is already green with `inert` removed. Real Tab traversal, with a
    positive control.

    The anchor precedes the gallery deliberately: the "Previous image" button
    is disabled at rest (idx 0), so it can be neither clicked nor focused, and
    gallery.js appends the bar AFTER the stage, so forward Tab from a bar
    control would only reach the figures after wrapping past the end of the
    document.
    """
    unit, user = gallery_lesson
    _goto(page, live_server, unit, user)
    page.wait_for_selector(".gallery__item.is-active")
    page.get_by_role("link", name="Anchor link").click()

    seen = _tab_walk(page)
    assert any(s["isTrigger"] for s in seen), "traversal never reached a zoom trigger"
    assert not any(s["inInactiveFigure"] for s in seen), (
        "focus entered an inactive figure"
    )


def test_arrow_key_navigation_survives_inerting(page, live_server, gallery_lesson):
    """Focus a zoom trigger, ArrowRight twice, assert the carousel advanced twice.

    Without the focus rescue, inerting the outgoing figure blurs focus to <body>, the
    arrow handler's `container.contains(t)` guard then fails, and navigation dies after
    exactly one step.
    """
    unit, user = gallery_lesson
    _goto(page, live_server, unit, user)
    page.wait_for_selector(".gallery__item.is-active")
    page.locator(".gallery__item.is-active .imgzoom-trigger").focus()

    def active_index():
        return page.evaluate(
            "() => Array.from(document.querySelectorAll('.gallery__item'))"
            ".findIndex(el => el.classList.contains('is-active'))"
        )

    assert active_index() == 0
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(400)  # 320ms fade + slack
    assert active_index() == 1
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(400)
    assert active_index() == 2, "second ArrowRight ignored -- focus was lost to <body>"
    assert page.evaluate(
        "() => document.querySelector('[data-gallery]')"
        ".contains(document.activeElement)"
    )


def test_clicking_the_active_gallery_figure_opens_the_overlay(
    page, live_server, gallery_lesson
):
    """The gallery is the surface with all the pointer complications and the only one
    whose click-to-open path nothing else exercises."""
    unit, user = gallery_lesson
    _goto(page, live_server, unit, user)
    page.wait_for_selector(".gallery__item.is-active")
    trigger = page.locator(".gallery__item.is-active .imgzoom-trigger")
    _open(page, trigger)


def test_decorative_gallery_figure_is_named_for_the_control(
    page, live_server, gallery_lesson
):
    """The empty-alt branch: figure 1 has an empty description, so its alt is empty and
    arming must give it an aria-label instead of leaving a nameless button."""
    unit, user = gallery_lesson
    _goto(page, live_server, unit, user)
    page.wait_for_selector(".gallery__item.is-active")
    page.get_by_role("button", name="Enlarge image").first.wait_for()


def test_inactive_tab_panel_keeps_its_image_out_of_the_tab_order(
    page, live_server, hidden_lesson
):
    unit, user = hidden_lesson
    _goto(page, live_server, unit, user)
    page.get_by_role("link", name="Anchor link").click()
    seen = _tab_walk(page, n=30)
    assert not any(s["inHiddenPanel"] for s in seen)

    # Positive control, and it must be able to fail: activate the second tab, walk
    # again, and require a trigger inside the now-visible panel to be REACHED.
    # `.tabs__tab`, NOT `[data-tab-btn]` -- that attribute exists nowhere in the repo.
    # tabselement.html emits only [data-tab-label] headings and [data-tab-panel] panels;
    # tabs.js:66-73 builds the strip buttons itself as button.tabs__tab[role=tab].
    # Walk order to expect: active tab button -> active panel (tabs.js:77 sets
    # panel.tabIndex = 0) -> the trigger inside it, with a roving tabindex on the
    # inactive tab buttons (tabs.js:94).
    # Selected by accessible NAME, not position: TabsElement.default_data() labels its
    # second tab "Tab 2" (courses/models.py), but `nth(1)` would silently target
    # whatever tab happens to be second if that default ever changed, rather than
    # failing loudly.
    page.get_by_role("tab", name="Tab 2").click()
    page.wait_for_selector("[data-tab-panel]:not([hidden]) .imgzoom-trigger")
    page.get_by_role("link", name="Anchor link").click()
    seen_after = _tab_walk(page, n=30)
    assert any(s["isTrigger"] for s in seen_after), (
        "tab image unreachable once revealed"
    )

    # Falsify with `[data-tab-panel][hidden] { display: block }` in
    # courses.css -- that keeps the attribute while making the image
    # focusable. REMOVING the hidden attribute is not a valid break: this
    # assertion keys on closest('[hidden]'), which would then return null
    # and leave inHiddenPanel false, and tabs.js:96-99 re-applies it anyway.


def test_closed_spoiler_keeps_its_image_out_of_the_tab_order(
    page, live_server, hidden_lesson
):
    """UNFALSIFIABLE SMOKE CHECK, stated as such: a closed <details> skips its contents
    via content-visibility and skipped contents are not focusable, so an author
    `display: block` on a child cannot restore focusability -- there is no break
    available. Its value is the positive control below.
    """
    unit, user = hidden_lesson
    _goto(page, live_server, unit, user)
    # `details.spoiler`, scoped: the lesson page also renders other native
    # <details> disclosures unrelated to this feature (a per-unit Tags panel
    # and a per-block Notes panel), so an unscoped "details > summary" would
    # toggle one of those instead of the spoiler under test.
    spoiler_img = page.locator("details .imgzoom-trigger")
    assert spoiler_img.evaluate_all("els => els.every(el => !el.checkVisibility())")
    page.locator("details.spoiler > summary").first.click()
    assert spoiler_img.first.evaluate("el => el.checkVisibility()")


def test_gated_image_stays_out_of_the_tab_order(page, live_server, hidden_lesson):
    """The highest-stakes row of the hiding table: a leaked tab stop would let
    a keyboard user open a gated ANSWER image before passing the gate.

    Gate only, no stepper half: StepperStep.content is a CharField of plain
    text + KaTeX (courses/models.py:503-508), so a stepper step cannot
    contain an element and no image can ever be hidden by that mechanism.
    The stepper row of the spec's hiding table stays true but is unreachable
    by this feature -- so there is deliberately no stepper assertion here,
    and no stepper falsification either.
    """
    unit, user = hidden_lesson
    _goto(page, live_server, unit, user)
    page.get_by_role("link", name="Anchor link").click()
    seen = _tab_walk(page, n=30)
    gated_reachable = page.evaluate(
        "() => Array.from(document.querySelectorAll('.imgzoom-trigger'))"
        ".some(el => el.checkVisibility() && el.alt.includes('gated'))"
    )
    assert not gated_reachable, (
        "gated answer image is rendered before the gate is passed"
    )
    # No inInactiveFigure assertion here: hidden_lesson has no gallery, so that
    # flag is False for every observation by construction and the check could
    # never fail. What the walk is for is this -- the gated trigger must never
    # be reached before the gate:
    assert not any(s["isTrigger"] and "gated" in (s.get("alt") or "") for s in seen)
    # Positive control: pass the gate, the image becomes reachable.
    page.locator("[data-reveal-gate]").click()
    page.wait_for_timeout(200)
    assert page.evaluate(
        "() => Array.from(document.querySelectorAll('.imgzoom-trigger'))"
        ".some(el => el.checkVisibility() && el.alt.includes('gated'))"
    )


@pytest.fixture
def filltable_lesson(db, _isolated_media):
    """A fill-in table whose one cell is an image cell."""
    from courses.models import FillTableElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(
        course, filename="cell.png", size=(800, 600), color="#FFAA00"
    )
    # Verified schema (courses/models.py:1007-1017): an image cell is
    # {"kind": "image", "media": <int pk>, "alt": str, "halign": ..., "valign": ...}.
    # `media` MUST be a real int -- normalize_data silently downgrades a non-int (or a
    # bool) to an empty STATIC cell, which renders no <img> at all and would make this
    # test fail for a reason unrelated to the feature.
    add_element(
        unit,
        FillTableElement.objects.create(
            data={
                "cells": [[{"kind": "image", "media": asset.pk, "alt": "Table image"}]],
                "header_row": False,
                "header_col": False,
                "border": "all",
            }
        ),
    )
    user = _student("filltablestudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user


@pytest.fixture
def tiny_lesson(db, _isolated_media):
    course = CourseFactory()
    unit = _image_unit(course, size=(1, 1), color="black", alt="Tiny", name="tiny.png")
    user = _student("tinystudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user


def test_filltable_image_cell_opens_the_overlay(page, live_server, filltable_lesson):
    unit, user = filltable_lesson
    _goto(page, live_server, unit, user)
    _open(page, page.locator(".filltable__img"))


def test_tiny_image_opens_and_is_not_upscaled(page, live_server, tiny_lesson):
    unit, user = tiny_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    _await_decoded(page, trigger)
    # Precondition: a mis-mapped media route must not hand this the 1400px fixture.
    assert _natural_width(trigger) == 1
    _open(page, trigger)
    box = _box(page.locator(".imgzoom__img"))
    assert box["width"] <= 1.5, f"1x1 image was upscaled to {box['width']}"


@pytest.fixture
def quiz_zoom_lesson(db, _isolated_media):
    """A QUIZ unit (unit_type="quiz", make_quiz_unit), not a lesson -- every other
    fixture in this module runs on a lesson page or the editor. quiz_unit.html
    renders elements through build_quiz_context rather than build_lesson_context, and
    this repo has a recorded lesson that a shared element template can render
    differently -- and has actually broken -- between the two consumption paths. This
    is a surface-level smoke check, not a re-test of geometry (that is covered
    exhaustively on lesson pages above)."""
    from courses.models import ImageElement

    course = CourseFactory()
    unit = make_quiz_unit(course=course)
    asset = make_image_asset(course, filename="quiz.png", size=BIG, color=MAGENTA)
    add_element(unit, ImageElement.objects.create(media=asset, alt="Quiz diagram"))
    user = _student("quizstudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user


def test_quiz_page_opens_and_closes_the_overlay(page, live_server, quiz_zoom_lesson):
    unit, user = quiz_zoom_lesson
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_quiz_url(live_server, unit))
    trigger = _trigger(page)
    _await_decoded(page, trigger)
    dialog = _open(page, trigger)
    assert dialog.evaluate("el => el.open") is True
    page.keyboard.press("Escape")
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")


def _make_pa_user(username):
    """A Platform Admin, which is what actually opens the editor.

    NOT an is_staff user. `can_manage_course` is "the course owner, OR anyone
    holding the courses.change_course model perm (the Platform Admin group)" and
    its own docstring says it "Deliberately does NOT key on is_staff"
    (courses/access.py:36-42). is_staff widens accessible_courses -- STUDENT
    access -- which is a different gate entirely. And make_verified_user takes
    only (username, email, password): there is no is_staff parameter to pass it.
    Mirrors tests/test_e2e_editor.py:24-36.
    """
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def test_editor_preview_rearms_after_a_real_save(
    page, live_server, db, _isolated_media
):
    """A source grep proves the string exists in editor.js; it cannot prove the name
    matches what imagezoom.js exports or that arming survives a real fragment swap
    (applyFragments replaces the whole [data-scope="preview"] node).

    There is no per-element edit PAGE in this app -- `courses:element_edit` does not
    exist and `reverse` would raise NoReverseMatch. Element editing happens inside the
    unit editor (`courses:manage_editor`, manage/courses/<slug>/build/unit/<pk>/edit/)
    via fetched fragments that mount in [data-edit-slot]; the save gesture is that
    fragment's own submit button, exactly as tests/test_e2e_editor.py:99-107 drives it.
    """
    from django.urls import reverse

    from courses.models import ImageElement

    owner = _make_pa_user("zoompa")
    course = CourseFactory(owner=owner)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename="ed.png", size=BIG, color=MAGENTA)
    add_element(unit, ImageElement.objects.create(media=asset, alt="Editor image"))

    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, owner)
    editor_url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    page.goto(f"{live_server.url}{editor_url}")

    # Open the existing element's edit fragment, change its alt, submit. The contract is
    # "a real save swaps [data-scope=preview] and the swapped-in image is armed".
    # [data-edit-slot] renders EMPTY on load: _element_row.html:42 only injects
    # open_form when open_form_pk == el.pk. So the fragment must be opened first,
    # via the row's edit button (_element_row.html:33 --
    # `button.iconbtn.el-select.el-act-edit` carrying data-element-id and
    # data-form-url). Note that tests/test_e2e_editor.py never does this: every
    # case there ADDS a new element via [data-add-toggle], so it is not a usable
    # reference for editing an existing one.
    page.locator(".el-act-edit").first.click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    page.locator("[data-edit-slot] input[name='alt']").fill("Editor image v2")
    page.locator("[data-edit-slot] button[type='submit']").click()
    page.wait_for_selector('[data-scope="preview"] [data-zoomable]')

    # Assert ARMING, not just that a click opens something. The click path is
    # delegated on document and matches e.target.closest("[data-zoomable]") by
    # design, so an UNARMED swapped-in image opens the overlay just the same --
    # meaning _open() alone stays green with the editor.js re-arm line deleted,
    # and would prove only that delegation survives a fragment swap. These four
    # attributes are what the re-arm line actually produces, so removing it
    # breaks this and nothing else does.
    swapped = page.locator('[data-scope="preview"] [data-zoomable]').first
    page.wait_for_function(
        "el => el.dataset.imgzoomReady === '1'", arg=swapped.element_handle()
    )
    assert swapped.get_attribute("role") == "button"
    assert swapped.get_attribute("tabindex") == "0"
    assert "imgzoom-trigger" in (swapped.get_attribute("class") or "")

    _open(page, swapped)  # smoke check on top of the arming assertions
