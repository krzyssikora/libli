"""Playwright e2e for the reveal-gate "Show more" element (plan Task 10). Drives the
REAL student gesture end-to-end — clicks the actual gate button — never a page.evaluate
shortcut into reveal.js internals (this repo's standing lesson: an e2e that bypasses
the real gesture ships broken UX green). The one route-intercept below (watchdog)
simulates a NETWORK condition, it does not bypass the click.

Covers the six scenarios from the task brief, each its own test:
  1. Cascade: [intro][gateA][B][C][gateB][D]. Only gateA's button shows; B/C/gateB/D
     hidden. Click gateA -> B, C, gateB-button show, gateA gone, D still hidden. Click
     gateB -> D shows.
  2. Nested-in-tab: a gate in tab 1 gates only that tab's following .tabs__child rows;
     a sibling SLIDE-level block placed AFTER the tabs element is NOT hidden by it.
  3. Quiz-inert: the same content in a QUIZ unit shows everything — no gate button, no
     reveal-armed class, no reveal.js.
  4. Watchdog: abort the reveal.js request; the DOMContentLoaded fallback (reveal.js
     never set window.__revealBooted) strips reveal-armed, so all content is visible.
  5. Focus: after clicking gateA, document.activeElement is gateB's button; for a
     TRAILING gate whose run is empty, focus lands on the scope container (.slide),
     not <body>.
  6. Single-slide: a single-slide lesson gate actually collapses its run.

Mirrors the harness in tests/test_e2e_slideshow.py / tests/test_e2e_tabs.py (student
half). Marked e2e (excluded from the default run; run with -m e2e)."""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Login / seed helpers
# ---------------------------------------------------------------------------


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _new_unit(username, unit_type="lesson"):
    """An enrolled student + a fresh unit of `unit_type`. Returns (student, unit)."""
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type=unit_type)
    EnrollmentFactory(student=student, course=course)
    return student, unit


def _unit_url(live_server, unit):
    from django.urls import reverse

    name = "courses:quiz_unit" if unit.unit_type == "quiz" else "courses:lesson_unit"
    path = reverse(name, kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    return f"{live_server.url}{path}"


def _text(body):
    from courses.models import TextElement

    return TextElement.objects.create(body=body)


def _gate(label):
    from courses.models import RevealGateElement

    return RevealGateElement.objects.create(label=label)


def _seed_tab1_gate(unit, tab1_children):
    """One TabsElement on `unit` (tabs 'First'/'Second'); `tab1_children` is a list of
    concrete element objects placed, in order, nested under tab 1. Order is per-unit and
    monotonic, so caller ordering (gate first) is preserved inside the tab."""
    from courses.models import Element
    from courses.models import TabsElement

    obj = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": "t000001", "label": "First"},
                {"id": "t000002", "label": "Second"},
            ]
        }
    )
    join = Element.objects.create(unit=unit, content_object=obj)
    for child in tab1_children:
        Element.objects.create(
            unit=unit, content_object=child, parent=join, tab_id="t000001"
        )
    return join


# ---------------------------------------------------------------------------
# 1. Cascade
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_reveal_cascade(page, live_server):
    """[intro][gateA][B][C][gateB][D]: gateA reveals B/C and the next gate (gateB),
    consumes itself, and stops — D stays hidden until gateB is clicked."""
    _student, unit = _new_unit("rg_cascade")
    add_element(unit, _text("<p>intro block</p>"))
    add_element(unit, _gate("Reveal A"))
    add_element(unit, _text("<p>block B</p>"))
    add_element(unit, _text("<p>block C</p>"))
    add_element(unit, _gate("Reveal B"))
    add_element(unit, _text("<p>block D</p>"))
    _login(page, live_server, "rg_cascade")
    page.goto(_unit_url(live_server, unit))

    gate_a = page.get_by_role("button", name="Reveal A")
    gate_b = page.get_by_role("button", name="Reveal B")
    # Boot: reveal.js un-hides gateA's button. B/C/gateB/D are display:none via the
    # prepaint reveal-armed hide-guard.
    expect(gate_a).to_be_visible()
    expect(page.get_by_text("intro block")).to_be_visible()
    expect(page.get_by_text("block B")).to_be_hidden()
    expect(page.get_by_text("block C")).to_be_hidden()
    expect(gate_b).to_be_hidden()
    expect(page.get_by_text("block D")).to_be_hidden()

    gate_a.click()

    expect(page.get_by_text("block B")).to_be_visible()
    expect(page.get_by_text("block C")).to_be_visible()
    expect(gate_b).to_be_visible()
    expect(gate_a).to_be_hidden()  # consumed
    expect(page.get_by_text("block D")).to_be_hidden()  # stops at the next gate

    gate_b.click()

    expect(page.get_by_text("block D")).to_be_visible()


# ---------------------------------------------------------------------------
# 2. Nested-in-tab
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_reveal_gate_nested_in_tab_scopes_to_that_tab(page, live_server):
    """A gate nested in tab 1 gates only that tab's following .tabs__child rows. A
    SLIDE-level block placed AFTER the whole tabs element is NOT hidden by the nested
    gate (the slide hide-guard only fires for a slide-level gate)."""
    _student, unit = _new_unit("rg_tab")
    _seed_tab1_gate(
        unit,
        [
            _gate("Reveal In Tab"),
            _text("<p>tab child one</p>"),
            _text("<p>tab child two</p>"),
        ],
    )
    add_element(unit, _text("<p>slide level after tabs</p>"))
    _login(page, live_server, "rg_tab")
    page.goto(_unit_url(live_server, unit))

    page.wait_for_selector("[data-tabs].tabs--js")
    gate = page.get_by_role("button", name="Reveal In Tab")
    expect(gate).to_be_visible()  # tab 1 is the active panel; gate un-hidden on boot

    # Nested run hidden; the slide-level sibling after the tabs element is visible.
    expect(page.get_by_text("tab child one")).to_be_hidden()
    expect(page.get_by_text("tab child two")).to_be_hidden()
    expect(page.get_by_text("slide level after tabs")).to_be_visible()

    gate.click()

    expect(page.get_by_text("tab child one")).to_be_visible()
    expect(page.get_by_text("tab child two")).to_be_visible()
    expect(gate).to_be_hidden()  # consumed
    # The slide-level sibling was never gated and stays visible throughout.
    expect(page.get_by_text("slide level after tabs")).to_be_visible()


# ---------------------------------------------------------------------------
# 3. Quiz-inert
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_reveal_gate_inert_in_quiz(page, live_server):
    """The same gate content in a QUIZ unit is inert: build_quiz_context never sets
    has_reveal_gate, so quiz_unit.html emits no reveal-armed class and no reveal.js. The
    gate button keeps its `hidden` attribute (no engine to un-hide it) and every block —
    including the one a lesson gate would have hidden — is visible."""
    _student, unit = _new_unit("rg_quiz", unit_type="quiz")
    add_element(unit, _text("<p>quiz intro</p>"))
    add_element(unit, _gate("Reveal A"))
    add_element(unit, _text("<p>after gate quiz</p>"))
    _login(page, live_server, "rg_quiz")
    page.goto(_unit_url(live_server, unit))

    # Quiz shell rendered.
    expect(page.locator("article.quiz")).to_be_visible()
    # No reveal machinery in the served document.
    html = page.content()
    assert "reveal-armed" not in html
    assert "reveal.js" not in html
    # Everything visible; the gate button stays hidden (never un-hidden).
    expect(page.get_by_text("quiz intro")).to_be_visible()
    expect(page.get_by_text("after gate quiz")).to_be_visible()
    expect(page.get_by_role("button", name="Reveal A")).to_be_hidden()


# ---------------------------------------------------------------------------
# 4. Watchdog
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_watchdog_unhides_when_reveal_js_blocked(page, live_server):
    """Abort the reveal.js request (as an extension/network block would). reveal.js
    never runs, so window.__revealBooted stays undefined and the prepaint
    DOMContentLoaded fallback strips reveal-armed — the hide-guard no longer applies
    and all content is visible (fail-open, never trapping content behind a dead
    button)."""
    _student, unit = _new_unit("rg_watchdog")
    add_element(unit, _text("<p>intro block</p>"))
    add_element(unit, _gate("Reveal A"))
    add_element(unit, _text("<p>block C</p>"))
    _login(page, live_server, "rg_watchdog")

    # Register the route before navigation so the deferred reveal.js load is caught.
    page.route("**/reveal.js*", lambda route: route.abort())
    page.goto(_unit_url(live_server, unit))

    # The watchdog removes reveal-armed on DOMContentLoaded; the gated block becomes
    # visible even though the engine never booted.
    expect(page.get_by_text("block C")).to_be_visible()
    assert page.evaluate("() => window.__revealBooted") in (None, False)
    assert (
        page.evaluate(
            "() => document.documentElement.classList.contains('reveal-armed')"
        )
        is False
    )


# ---------------------------------------------------------------------------
# 5. Focus
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_focus_lands_on_next_gate(page, live_server):
    """After clicking gateA the cascade stops at gateB, and focus moves to gateB's
    button, so keyboard users continue without hunting for it."""
    _student, unit = _new_unit("rg_focus")
    add_element(unit, _text("<p>intro block</p>"))
    add_element(unit, _gate("Reveal A"))
    add_element(unit, _text("<p>block B</p>"))
    add_element(unit, _gate("Reveal B"))
    _login(page, live_server, "rg_focus")
    page.goto(_unit_url(live_server, unit))

    gate_a = page.get_by_role("button", name="Reveal A")
    expect(gate_a).to_be_visible()
    gate_a.click()
    expect(page.get_by_role("button", name="Reveal B")).to_be_visible()
    assert page.evaluate("() => document.activeElement.matches('[data-reveal-gate]')")
    assert (
        page.evaluate("() => document.activeElement.textContent").strip() == "Reveal B"
    )


@pytest.mark.django_db(transaction=True)
def test_focus_lands_on_scope_for_trailing_gate(page, live_server):
    """A TRAILING gate whose run is empty has no next gate and no revealed sibling to
    focus, so focus lands on the scope container (.slide, made programmatically
    focusable) — never falling through to <body>."""
    _student, unit = _new_unit("rg_focus_trail")
    add_element(unit, _text("<p>lead block</p>"))
    add_element(unit, _gate("Reveal Trailing"))
    _login(page, live_server, "rg_focus_trail")
    page.goto(_unit_url(live_server, unit))

    trailing = page.get_by_role("button", name="Reveal Trailing")
    expect(trailing).to_be_visible()
    trailing.click()
    assert page.evaluate("() => document.activeElement !== document.body")
    assert page.evaluate("() => document.activeElement.classList.contains('slide')")


# ---------------------------------------------------------------------------
# 6. Single-slide
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_gate_state_survives_reload(page, live_server):
    """Click the real gate -> state POST -> reload -> content still revealed AND
    the gate button is gone (the only coverage of restore's {hideWrapper: true})."""

    def _is_state_post(r):
        return "/state/" in r.url and r.request.method == "POST"

    student, unit = _new_unit("rg_persist")
    add_element(unit, _text("<p>intro</p>"))
    add_element(unit, _gate("Reveal"))
    add_element(unit, _text("<p>secret block</p>"))
    _login(page, live_server, "rg_persist")
    page.goto(_unit_url(live_server, unit))

    # REAL click; await the /state/ POST before reloading.
    with page.expect_response(_is_state_post):
        page.get_by_role("button", name="Reveal").click()

    page.reload()

    # After reload: the secret block is revealed, and the gate button is consumed.
    assert page.get_by_text("secret block").is_visible()
    assert page.get_by_role("button", name="Reveal").count() == 0


@pytest.mark.django_db(transaction=True)
def test_single_slide_gate_collapses_its_run(page, live_server):
    """A single-slide lesson (no slide breaks) still collapses a gate's run: the block
    after the gate is hidden at rest and revealed on click."""
    _student, unit = _new_unit("rg_single")
    add_element(unit, _gate("Reveal A"))
    add_element(unit, _text("<p>hidden until revealed</p>"))
    _login(page, live_server, "rg_single")
    page.goto(_unit_url(live_server, unit))

    # Genuinely single-slide (not slideshow mode): no data-slideshow, one .slide.
    expect(page.locator("article.lesson")).to_be_visible()
    assert page.locator("article.lesson[data-slideshow]").count() == 0
    assert page.locator("article.lesson .slide").count() == 1
    gate = page.get_by_role("button", name="Reveal A")
    expect(gate).to_be_visible()
    expect(page.get_by_text("hidden until revealed")).to_be_hidden()

    gate.click()

    expect(page.get_by_text("hidden until revealed")).to_be_visible()
    expect(gate).to_be_hidden()
