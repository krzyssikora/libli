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

Task 5 (slice 2) adds the WALK edge-case, fail-safe, and editor-preview coverage on top
of the above (restoreGates/save/cascadeFrom focus-mode from Task 4):
  7. Barrier enumeration, prefix-closure, across-scopes, two-column (and its
     column-nested-fill-gate sibling), boot-restore focus/scroll, and drifted
     data-state -- each asserts on `.reveal-shown` class presence/absence, never
     `to_be_visible()` (inactive tab panels carry the `hidden` attribute, which makes
     visibility a false RED).
  8. Editor-preview: a tab-nested preview gate does not cascade on load (data-state is
     always "{}" there); a preview gate click sends no request at all (save_url is "").

Mirrors the harness in tests/test_e2e_slideshow.py / tests/test_e2e_tabs.py (student
half). Marked e2e (excluded from the default run; run with -m e2e)."""

import os
import re

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


def _fillgate(author_stem):
    """Build a FillGateElement from author `{{answer}}` markup (use | for
    alternatives), as the form's clean_stem/save would: parse to token-stem+answers.
    Mirrors tests/test_e2e_fillgate.py:98-105."""
    from courses.fillblank import parse
    from courses.models import FillGateElement

    token_stem, blanks = parse(author_stem)
    return FillGateElement.objects.create(stem=token_stem, answers=blanks)


def _seed_tabs_element(unit, tabs, children=None):
    """Attach one TabsElement to `unit`, one tab per `tabs` entry.

    `tabs` is [(tab_id, label)]; `children` maps tab_id -> [concrete element obj].
    Returns (obj, join). Mirrors tests/test_e2e_tabs.py:93 (the per-tab seeder, as
    opposed to this file's own `_seed_tab1_gate`, which only ever populates tab 1)."""
    from courses.models import Element
    from courses.models import TabsElement

    obj = TabsElement.objects.create(
        data={"tabs": [{"id": tid, "label": label} for tid, label in tabs]}
    )
    join = Element.objects.create(unit=unit, content_object=obj)
    for tid, objs in (children or {}).items():
        for child_obj in objs:
            Element.objects.create(
                unit=unit, content_object=child_obj, parent=join, tab_id=tid
            )
    return obj, join


def _seed_two_column_gate(unit, col_children):
    """Attach one TwoColumnElement to `unit`; every element in `col_children` is
    placed, in order, into the FIRST column. The column id is minted by `secrets`
    inside `default_data()` -- read it back after `save()`, never hardcode it (a
    hardcoded id would orphan the children and make the two-column tests pass
    vacuously). Returns (parent join row, column id)."""
    from courses.models import Element
    from courses.models import TwoColumnElement

    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    cid = col.data["columns"][0]["id"]  # minted by secrets -- never hardcode
    parent = Element.objects.create(unit=unit, content_object=col)
    for child in col_children:
        Element.objects.create(
            unit=unit, content_object=child, parent=parent, tab_id=cid
        )
    return parent, cid


def _seed_state(student, unit, element_state):
    """Seed UnitProgress.element_state DIRECTLY in the DB -- this is fixture SETUP,
    not a bypassed gesture (the gesture under test is always the reload/click that
    follows). Keys must be the Element JOIN-ROW pk, stringified (JSONField keys are
    always strings on disk)."""
    from courses.models import UnitProgress

    progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
    progress.element_state = element_state
    progress.save()
    return progress


def _make_pa_user(username):
    """A Platform Admin, manage-capable login. Mirrors
    tests/test_e2e_editor_view_toggle.py:23-34."""
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _editor_unit(pa, slug):
    """A course OWNED by `pa` (manage_editor is owner-gated) + a fresh lesson unit.
    Mirrors tests/test_e2e_editor_view_toggle.py:45-53."""
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


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


# ---------------------------------------------------------------------------
# 7. Walk edge cases (Task 5) -- restoreGates's BARRIER enumeration, prefix-closure,
# and per-scope bucketing. Every block assertion below is on `.reveal-shown`, keyed
# by the block's `data-element-id` -- NEVER `to_be_visible()`, which would false-RED
# inside a hidden (non-default) tab panel.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_restore_barrier_enumeration_includes_fillgate(page, live_server):
    """A TOP-LEVEL unanswered fill-gate ABOVE a stored-open plain gate must itself act
    as a walk barrier: restoreGates enumerates BARRIER (all three gate families), not
    just RESTORABLE, so the unanswered fill-gate stops the walk before it ever reaches
    the stored-open plain gate below it -- no block past the plain gate restores."""
    student, unit = _new_unit("rg_barrier")
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    gate_join = add_element(unit, _gate("Reveal"))
    trailing_join = add_element(unit, _text("<p>past the plain gate</p>"))
    _seed_state(student, unit, {str(gate_join.pk): {"open": True}})
    _login(page, live_server, "rg_barrier")
    page.goto(_unit_url(live_server, unit))

    trailing = page.locator(f".lesson-block[data-element-id='{trailing_join.pk}']")
    expect(trailing).not_to_have_class(re.compile(r"\breveal-shown\b"))


@pytest.mark.django_db(transaction=True)
def test_restore_prefix_closure_stops_at_first_closed_gate(page, live_server):
    """gate2 is stored open behind a CLOSED gate1: the walk stops at gate1 (still a
    live, un-consumed button) and never reaches gate2, so no block past gate2
    restores."""
    student, unit = _new_unit("rg_prefix")
    add_element(unit, _gate("Gate One"))
    between_join = add_element(unit, _text("<p>between the gates</p>"))
    gate2_join = add_element(unit, _gate("Gate Two"))
    trailing_join = add_element(unit, _text("<p>past gate two</p>"))
    _seed_state(student, unit, {str(gate2_join.pk): {"open": True}})
    _login(page, live_server, "rg_prefix")
    page.goto(_unit_url(live_server, unit))

    gate1 = page.get_by_role("button", name="Gate One")
    expect(gate1).to_be_visible()  # never consumed: the walk stopped here
    between = page.locator(f".lesson-block[data-element-id='{between_join.pk}']")
    trailing = page.locator(f".lesson-block[data-element-id='{trailing_join.pk}']")
    expect(between).not_to_have_class(re.compile(r"\breveal-shown\b"))
    expect(trailing).not_to_have_class(re.compile(r"\breveal-shown\b"))


@pytest.mark.django_db(transaction=True)
def test_restore_across_scopes_does_not_cross_tab_panels(page, live_server):
    """A closed gate in tab panel 1 must not veto a stored-open gate in tab panel 2:
    restoreGates buckets gates by scope (scopeOf) and walks each bucket
    independently. Panel 2 is not the default-active panel (tabs.js selects panel 0),
    so this also proves restore reaches into a HIDDEN panel."""
    student, unit = _new_unit("rg_scopes")
    gate1 = _gate("Panel One Gate")
    text1 = _text("<p>panel one child</p>")
    gate2 = _gate("Panel Two Gate")
    text2 = _text("<p>panel two secret</p>")
    _seed_tabs_element(
        unit,
        [("t000001", "One"), ("t000002", "Two")],
        {"t000001": [gate1, text1], "t000002": [gate2, text2]},
    )
    gate2_pk = gate2.elements.first().pk
    _seed_state(student, unit, {str(gate2_pk): {"open": True}})
    _login(page, live_server, "rg_scopes")
    page.goto(_unit_url(live_server, unit))

    page.wait_for_selector("[data-tabs].tabs--js")
    panel2_secret = page.locator(
        "[data-tab-panel][data-tab-id='t000002'] .tabs__child",
        has_text="panel two secret",
    )
    expect(panel2_secret).to_have_class(re.compile(r"\breveal-shown\b"))


@pytest.mark.django_db(transaction=True)
def test_restore_two_column_gate_does_not_veto_top_level_gate(page, live_server):
    """A stored-open gate nested inside a two-column column is MIS-SCOPED for the
    slide-level walk (its own-wrapper is the two-column's whole .lesson-block, which
    is not itself a direct gate wrapper) -- restoreGates must `continue` past it,
    never hide the two-column element, and never veto a later top-level stored-open
    gate."""
    student, unit = _new_unit("rg_twocol")
    col_gate = _gate("Column Gate")
    parent, _cid = _seed_two_column_gate(unit, [col_gate])
    col_gate_pk = col_gate.elements.first().pk
    top_gate_join = add_element(unit, _gate("Top Gate"))
    trailing_join = add_element(unit, _text("<p>after top gate</p>"))
    _seed_state(
        student,
        unit,
        {
            str(col_gate_pk): {"open": True},
            str(top_gate_join.pk): {"open": True},
        },
    )
    _login(page, live_server, "rg_twocol")
    page.goto(_unit_url(live_server, unit))

    two_col_block = page.locator(f".lesson-block[data-element-id='{parent.pk}']")
    assert two_col_block.get_attribute("hidden") is None
    trailing = page.locator(f".lesson-block[data-element-id='{trailing_join.pk}']")
    expect(trailing).to_have_class(re.compile(r"\breveal-shown\b"))


@pytest.mark.django_db(transaction=True)
def test_restore_column_nested_fillgate_does_not_veto_top_level_gate(page, live_server):
    """An unanswered fill-gate mis-scoped inside a two-column column must not act as a
    barrier for the SLIDE-level walk: a later top-level stored-open gate still
    restores."""
    student, unit = _new_unit("rg_twocol_fill")
    col_fillgate = _fillgate("Capital of France? {{Paris}}")
    _seed_two_column_gate(unit, [col_fillgate])
    top_gate_join = add_element(unit, _gate("Top Gate"))
    trailing_join = add_element(unit, _text("<p>after top gate</p>"))
    _seed_state(student, unit, {str(top_gate_join.pk): {"open": True}})
    _login(page, live_server, "rg_twocol_fill")
    page.goto(_unit_url(live_server, unit))

    trailing = page.locator(f".lesson-block[data-element-id='{trailing_join.pk}']")
    expect(trailing).to_have_class(re.compile(r"\breveal-shown\b"))


@pytest.mark.django_db(transaction=True)
def test_boot_restore_moves_neither_focus_nor_scroll(page, live_server):
    """A restore-only load (no click) must not steal focus or scroll the viewport --
    the gate is un-hidden and consumed in place, silently. The gate sits BELOW THE
    FOLD (many preceding blocks) so the scroll assertion is not decorative."""
    student, unit = _new_unit("rg_bootfocus")
    for i in range(50):
        add_element(unit, _text(f"<p>filler line {i}</p>"))
    gate_join = add_element(unit, _gate("Reveal"))
    add_element(unit, _text("<p>below the fold secret</p>"))
    _seed_state(student, unit, {str(gate_join.pk): {"open": True}})
    _login(page, live_server, "rg_bootfocus")
    page.goto(_unit_url(live_server, unit))

    expect(page.locator("body")).to_be_focused()
    assert page.evaluate("() => window.scrollY") == 0


# ---------------------------------------------------------------------------
# 8. Fail-safe (Task 5): a drifted stored blob, and the JS-blocked watchdog
# (test_watchdog_unhides_when_reveal_js_blocked above is the pre-existing coverage
# for the latter -- confirmed still green, not rewritten).
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_restore_drifted_state_keeps_gate_live(page, live_server):
    """A hand-drifted blob ({"open": "yes"}) fails storedOpen's strict `=== true`
    check: the walk `break`s, the gate stays live/clickable, and nothing past it
    restores automatically -- but a REAL click still reveals it normally. This is the
    only reachable drift: the endpoint's validator normalizes any truthy `open` to
    `True`, so a hand-written row is the one path in."""
    student, unit = _new_unit("rg_drift")
    gate_join = add_element(unit, _gate("Reveal"))
    trailing_join = add_element(unit, _text("<p>drifted secret</p>"))
    _seed_state(student, unit, {str(gate_join.pk): {"open": "yes"}})
    _login(page, live_server, "rg_drift")
    page.goto(_unit_url(live_server, unit))

    gate = page.get_by_role("button", name="Reveal")
    trailing = page.locator(f".lesson-block[data-element-id='{trailing_join.pk}']")
    expect(gate).to_be_visible()
    expect(trailing).not_to_have_class(re.compile(r"\breveal-shown\b"))

    gate.click()

    expect(trailing).to_have_class(re.compile(r"\breveal-shown\b"))


# ---------------------------------------------------------------------------
# 9. Editor preview (Task 5): the preview loads reveal.js unconditionally, and a
# tab-nested preview gate gets a REAL, non-null scope -- inertness rests on
# data-state="{}" (the editor context carries no element_state), not on scope
# absence.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_editor_preview_tab_nested_gate_does_not_cascade_on_load(page, live_server):
    """A gate nested in a tabs element in the editor preview gets a real, non-null
    [data-tab-panel] scope -- the null-scope discard never fires for it. It does not
    cascade on the initial editor load because data-state is always "{}" there."""
    pa = _make_pa_user("rg_editor_pa")
    course, unit = _editor_unit(pa, "rg-editor-tabnest")
    gate = _gate("Nested Gate")
    text = _text("<p>should stay hidden in preview</p>")
    _seed_tabs_element(
        unit, [("t000001", "One"), ("t000002", "Two")], {"t000001": [gate, text]}
    )
    _login(page, live_server, "rg_editor_pa")
    page.goto(_editor_url(live_server, course, unit))

    preview = page.locator('[data-scope="preview"]')
    preview_gate = preview.locator("[data-tab-panel] button.reveal-gate")
    expect(preview_gate).to_have_attribute("data-state", "{}")
    trailing = preview.locator(".tabs__child", has_text="should stay hidden in preview")
    expect(trailing).not_to_have_class(re.compile(r"\breveal-shown\b"))


@pytest.mark.django_db
def test_editor_preview_gate_click_sends_no_request(page, live_server):
    """Clicking a real gate button in the editor preview must never POST: save_url is
    "" there (the editor context carries no slug/node_pk), and without the
    `if (!url) return;` guard `fetch("")` would hit the editor's OWN url as a POST."""
    pa = _make_pa_user("rg_editor_pa2")
    course, unit = _editor_unit(pa, "rg-editor-click")
    add_element(unit, _gate("Preview Gate"))
    add_element(unit, _text("<p>preview trailer</p>"))
    _login(page, live_server, "rg_editor_pa2")
    editor_url = _editor_url(live_server, course, unit)

    posts = []
    page.on(
        "request",
        lambda req: posts.append(req.url) if req.method == "POST" else None,
    )
    page.goto(editor_url)

    preview_gate = page.locator('[data-scope="preview"] button.reveal-gate')
    expect(preview_gate).to_be_visible()
    preview_gate.click()
    page.wait_for_timeout(300)  # allow any erroneous fetch("") to land

    assert not any("/state/" in u for u in posts)
    assert not any(u.rstrip("/") == editor_url.rstrip("/") for u in posts)
