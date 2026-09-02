"""Playwright e2e for printing a lesson with the student's own notes.

Assumes PR #267 (lesson print foundations) is in the base: dark-theme printing
and slideshow printing are already correct and are not re-asserted here.

Entry-path rules, which decide several assertions:
  * emulate_media(media="print") re-evaluates CSS media queries AND fires a
    matchMedia("print") change, so it RUNS the enter path.
  * Therefore a row proving the beforeprint listener exists must NOT call
    emulate_media first, or the mutant is rescued by the media route.
  * Never mql.dispatchEvent(new Event("change")) -- it carries no `matches`, so
    the handler takes the LEAVE path and the row goes red on a correct build.

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _lesson_with_note(slug, body="a note the student wrote", elements=1):
    """A published lesson with `elements` blocks, each carrying one note.

    Two blocks are the minimum for several rows, and the reason is not cosmetic:
    applyHighlight (notes.js:434) dims only blocks OTHER than the target, so with
    a single block nothing is ever .is-dimmed and an opacity assertion cannot
    fail. The restore rows likewise need one panel the student opens by hand and
    a DIFFERENT one for the sweep to open.

    Returns (course, unit, student, [notes...]).
    """
    from django.contrib.auth.models import Group as AuthGroup

    from courses.models import ContentNode
    from courses.models import Enrollment
    from courses.models import TextElement
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from notes.models import Note
    from tests.factories import CourseFactory
    from tests.factories import add_element
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug=slug)
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="Printable",
        published=True,
    )
    els = [
        add_element(unit, TextElement.objects.create(body=f"<p>Block {i}.</p>"))
        for i in range(elements)
    ]
    student = make_verified_user(
        username=f"{slug}-student", email=f"{slug}@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")
    notes = [
        Note.objects.create(author=student, unit=unit, element=el, body=body)
        for el in els
    ]
    return course, unit, student, notes


def _open(page, live_server, course, unit, student):
    _login(page, live_server, student.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".block-notes__panel", state="attached")


def _visible(page, selector):
    """checkVisibility() with NO options -- the only correct discriminator for a
    closed <details>. bounding_box() stays non-zero through one (measured
    52.4x22) and querySelectorAll counts it, so both are useless here."""
    return page.evaluate(
        "s => { const el = document.querySelector(s);"
        "       return !!el && el.checkVisibility(); }",
        selector,
    )


@pytest.mark.django_db(transaction=True)
def test_note_body_visible_after_the_event_route(page, live_server):
    """NO emulate_media: with both listeners live it would run the enter path via
    the media route and rescue this row's mutant. An open <details> is visible on
    screen, so this is a valid observation."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-event")
    _open(page, live_server, course, unit, student)

    assert not _visible(page, ".note-card__body"), "panel should start closed"
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    assert _visible(page, ".note-card__body"), (
        "the beforeprint listener did not open the panel"
    )


@pytest.mark.django_db(transaction=True)
def test_note_body_visible_after_the_media_route(page, live_server):
    """emulate_media only -- this IS a real matchMedia('print') change."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-media")
    _open(page, live_server, course, unit, student)

    page.emulate_media(media="print")
    page.wait_for_function(
        "() => { const el = document.querySelector('.note-card__body');"
        "        return el && el.checkVisibility(); }"
    )


@pytest.mark.django_db(transaction=True)
def test_the_real_button_calls_window_print(page, live_server):
    """Drives the actual control, not a page.evaluate shortcut."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-button")
    stub = "window.__printed = 0; window.print = () => { window.__printed++; };"
    page.add_init_script(stub)
    _open(page, live_server, course, unit, student)

    page.locator("[data-print-lesson]").click()
    assert page.evaluate("window.__printed") == 1, (
        "the Print button did not call window.print()"
    )


@pytest.mark.django_db(transaction=True)
def test_the_button_is_visible_on_screen_and_not_in_print(page, live_server):
    """The gate is (0,2,1); a print rule at (0,1,0) loses to it."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-btnvis")
    _open(page, live_server, course, unit, student)

    assert _visible(page, "[data-print-lesson]"), "button must show on screen"
    page.emulate_media(media="print")
    assert not _visible(page, "[data-print-lesson]"), (
        "the Print button printed; its print rule must be html.js-qualified to "
        "beat the (0,2,1) gate"
    )


@pytest.mark.django_db(transaction=True)
def test_long_note_prints_in_full(page, live_server):
    """INJECTS the clamp class rather than waiting for setupClamp: the toggle is
    async, and setupClamp measures AFTER adding the class (notes.js:104), so with
    the un-clamp rule live it detects no overflow and removes the class again --
    leaving this row green on its own mutant."""
    long_body = "\n".join(f"line {i}" for i in range(20))
    course, unit, student, _ = _lesson_with_note("e2e-pn-clamp", body=long_body)
    _open(page, live_server, course, unit, student)

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.evaluate(
        "document.querySelector('.note-card__body')"
        ".classList.add('note-card__body--clamp')"
    )
    page.emulate_media(media="print")
    box = page.locator(".note-card__body").bounding_box()
    # .note-card__body is font-size .9rem (14.4px); -webkit-line-clamp: 6 means a
    # clamped body measures ~121-138px at any plausible line-height. A 100px
    # threshold sits BELOW that, so the un-clamp mutant would still pass. The
    # 20-line body prints at ~400px unclamped, so 300 separates the two regimes.
    assert box["height"] > 300, (
        f"clamped note prints {box['height']}px -- the un-clamp rule is missing "
        "or lost on specificity"
    )


@pytest.mark.django_db(transaction=True)
def test_controls_do_not_print(page, live_server):
    """Only display:none targets, asserted with checkVisibility()."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-controls")
    _open(page, live_server, course, unit, student)

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.emulate_media(media="print")
    for sel in (".note-card__actions", ".block-notes__add-more"):
        assert not _visible(page, sel), f"{sel} printed"


@pytest.mark.django_db(transaction=True)
def test_the_note_handle_has_zero_height_in_print(page, live_server):
    """MUST measure the box, not checkVisibility(): the handle is suppressed with
    visibility:hidden, and checkVisibility()'s default visibilityProperty:false
    means it returns TRUE for such an element -- this row would be RED on a
    correct build."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-handle")
    _open(page, live_server, course, unit, student)

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.emulate_media(media="print")
    box = page.locator(".block-notes__handle").first.bounding_box()
    assert box["height"] == 0, (
        f"the note handle prints {box['height']}px tall; the suppression must "
        "reset padding too, or box-sizing:border-box leaves ~8px"
    )


@pytest.mark.django_db(transaction=True)
def test_label_and_date_print_and_are_absent_on_screen(page, live_server):
    """Both directions, for both print-only elements."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-label")
    _open(page, live_server, course, unit, student)
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")

    assert not _visible(page, ".note-card__print-label"), "label showed on screen"
    assert not _visible(page, ".note-card__print-date"), "date showed on screen"

    page.emulate_media(media="print")
    assert _visible(page, ".note-card__print-label"), "My note label did not print"
    assert _visible(page, ".note-card__print-date"), "absolute date did not print"
    assert not _visible(page, ".note-card__meta-rel"), (
        "the relative 'x ago' text printed alongside the absolute date"
    )
    box = page.locator(".note-card__print-label").bounding_box()
    assert box["height"] > 1, "label is present but clipped"


@pytest.mark.django_db(transaction=True)
def test_blocks_are_not_dimmed_or_ringed_in_print(page, live_server):
    """A dimmed or ringed block must not print that way.

    The state is injected AFTER print media is entered, and both halves of that
    are deliberate.

    Injected rather than gestured: notes.js applies these classes on hover and
    focus and clears them on mouseout (:467) and focusout (:500), and both fire
    easily around the print lifecycle -- opening the panels shifts layout under a
    stationary cursor, and a headless browser does not hold document focus the
    way a real one does. Measured, a focus-driven fixture passed locally and
    failed on CI for exactly that reason.

    AFTER emulate_media rather than before: notes.js's own highlight bookkeeping
    (clearHighlight/applyHighlight, :410-434) can re-run while the enter path
    opens panels and move the classes to a different block -- measured, an
    injection placed before the media switch had is-dimmed relocated onto the
    other block, which silently made every mutant survive. Injecting last leaves
    no window for that.

    Which state notes.js happens to be in at snapshot time is ITS behaviour. What
    these print rules must do is neutralise the classes WHEN PRESENT, and that is
    what is asserted.
    """
    course, unit, student, _ = _lesson_with_note("e2e-pn-dim", elements=2)
    _open(page, live_server, course, unit, student)

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.emulate_media(media="print")

    state = page.evaluate(
        "() => { const bs = document.querySelectorAll('.lesson-block');"
        "        bs[0].classList.add('is-highlighted');"
        "        bs[1].classList.add('is-dimmed');"
        "        const card = bs[0].querySelector('.note-card');"
        "        card.classList.add('is-highlighted');"
        "        return { dimClass: bs[1].className,"
        "                 dimOpacity: getComputedStyle(bs[1]).opacity,"
        "                 hiOutline: getComputedStyle(bs[0]).outlineStyle,"
        "                 cardRail: getComputedStyle(card).borderLeftWidth }; }"
    )
    # Guard the fixture itself: if notes.js has moved the class off this block,
    # the measurements below would be meaningless and every mutant would survive.
    assert "is-dimmed" in state["dimClass"], (
        f"the injected class did not stick: {state}"
    )
    assert float(state["dimOpacity"]) == 1.0, f"other block printed dimmed: {state}"
    assert state["hiOutline"] == "none", f"highlighted block printed ringed: {state}"
    # applyHighlight stamps is-highlighted on the CARD too (notes.js:445-449),
    # and notes.css gives that a 6px rail -- borders survive the
    # strip-backgrounds default, so it would print fatter than every sibling.
    assert state["cardRail"] == "4px", (
        f"highlighted card printed a {state['cardRail']} rail, not 4px: {state}"
    )


@pytest.mark.django_db(transaction=True)
def test_panels_print_opened_are_closed_again_and_hand_opened_ones_are_not(
    page, live_server
):
    """The restore contract, plus the residue cleanup.

    The residue is INJECTED rather than waited for: the toggle is async, so an
    absence assertion would pass vacuously on a build with the cleanup deleted.
    """
    # TWO blocks, and the distinction is the whole point: panel A is opened by
    # the STUDENT (so enter() never sees it -- it queries :not([open]) -- and
    # leave() must not touch it), panel B is opened by the sweep. With one block
    # the sweep opens nothing, `opened` stays empty, and the residue assertion is
    # RED on a correct build.
    course, unit, student, _ = _lesson_with_note("e2e-pn-restore", elements=2)
    _open(page, live_server, course, unit, student)

    page.locator(".block-notes__handle").first.click()
    page.wait_for_function(
        "() => document.querySelectorAll('.block-notes__panel[open]').length === 1"
    )

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.wait_for_function(
        "() => document.querySelectorAll('.block-notes__panel[open]').length === 2"
    )
    # Inject the residue into the panel the SWEEP opened (the second one).
    page.evaluate(
        "() => { const p = document.querySelectorAll('.block-notes__panel')[1];"
        "        p.querySelector('.note-card__body')"
        "         .classList.add('note-card__body--clamp'); }"
    )
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")

    state = page.evaluate(
        "() => { const ps = document.querySelectorAll('.block-notes__panel');"
        "        return { handOpen: ps[0].open, sweptOpen: ps[1].open,"
        "                 residue: !!document.querySelector"
        "                            ('.note-card__body--clamp') }; }"
    )
    assert state["handOpen"], "the leave path closed a panel the STUDENT opened"
    assert not state["sweptOpen"], "the leave path left a swept panel open"
    assert not state["residue"], "clamp residue survived the leave path"


@pytest.mark.django_db(transaction=True)
def test_two_enters_with_no_leave_then_one_leave(page, live_server):
    """The re-close between the enters is what makes this falsifiable: without it
    the first enter has already opened everything and a reintroduced mode flag's
    early return would be invisible."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-idempotent", elements=2)
    _open(page, live_server, course, unit, student)

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.evaluate("document.querySelector('.block-notes__panel').open = false")
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    assert page.evaluate("document.querySelector('.block-notes__panel').open"), (
        "the second enter did not re-open the panel -- a mode flag was reintroduced"
    )

    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    assert not page.evaluate("document.querySelector('.block-notes__panel').open")
