"""Playwright e2e for the "Choose & confirm" gate element (plan Task 11). Drives the
REAL student gesture end-to-end — clicks the inline cycler to select an option and
clicks the actual Confirm button — never a page.evaluate shortcut into the grading
endpoint or reveal.js internals (this repo's standing lesson: an e2e that bypasses the
real gesture ships broken UX green). page.evaluate is used ONLY to read state
(document.activeElement), never to trigger a reveal.

Covers the behaviour matrix from the task brief:
  1. Cycle wraps placeholder -> opt0 -> ... -> optN-1 -> placeholder.
  2. Wrong Confirm -> "Try again" visible + following content still hidden + cycler
     still enabled.
  3. Wrong then cycle (Try again hides) then correct -> Confirm -> following content
     revealed + cycler disabled + Confirm gone.
  4. A preceding plain gate's cascade stops at the switchgate and focuses the cycler.
  5. An option containing \\(+\\) renders KaTeX (a .katex node), not raw TeX.
  6. A switchgate nested in a tab reveals only within that panel.
  7. No-JS (JS disabled): following content visible (fail-open) + cycler shows only the
     inert placeholder (options + Confirm stay hidden).

Mirrors the harness in tests/test_e2e_fillgate.py (login/seed/unit helpers, tab
seeding) and the JS-disabled context pattern from tests/test_e2e_builder.py. Marked e2e
(excluded from the default run; run with -m e2e)."""

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
# Login / seed helpers (mirrored from tests/test_e2e_fillgate.py)
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


def _switchgate(author_stem, options, answer):
    """Build a SwitchGateElement from author `{{choice}}` markup, as the form's
    clean()/save() would: parse the stem to its ￿0￿ token-stem. The raw sentinel is
    NEVER pasted here (file tools corrupt it) — parse_stem builds it from fillblank's
    SENTINEL. Options are sanitised in the model's save()."""
    from courses import switchgate
    from courses.models import SwitchGateElement

    return SwitchGateElement.objects.create(
        stem=switchgate.parse_stem(author_stem),
        options=list(options),
        answer=answer,
    )


def _seed_tab1_gate(unit, tab1_children):
    """One TabsElement on `unit` (tabs 'First'/'Second'); `tab1_children` is a list of
    concrete element objects placed, in order, nested under tab 1."""
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


def _seed_state(student, unit, element_state):
    """Seed UnitProgress.element_state DIRECTLY in the DB -- fixture SETUP (a
    precondition of the reload gesture under test), not a bypassed gesture."""
    from courses.models import UnitProgress

    progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
    progress.element_state = element_state
    progress.save(update_fields=["element_state"])


# Shared locators.
def _cycler(page):
    return page.locator("[data-switchgate-cycler]").first


def _confirm(page):
    return page.get_by_role("button", name="Confirm")


def _placeholder(page):
    return page.locator(".switchgate__placeholder").first


def _option(page, i):
    return page.locator(".switchgate__option").nth(i)


def _feedback(page):
    return page.locator("[data-switchgate-feedback]")


# ---------------------------------------------------------------------------
# 1. Cycle wraps placeholder -> options -> placeholder
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_cycle_wraps_through_placeholder(page, live_server):
    """Behaviour 1: clicking the cycler rings placeholder -> opt0 -> opt1 ->
    placeholder (N+1 clicks for N options return to the placeholder)."""
    _student, unit = _new_unit("sg_cycle")
    add_element(unit, _switchgate("Pick: {{choice}}", ["Alpha", "Bravo"], answer=1))
    _login(page, live_server, "sg_cycle")
    page.goto(_unit_url(live_server, unit))

    # At rest: placeholder visible, both options hidden.
    expect(_placeholder(page)).to_be_visible()
    expect(_placeholder(page)).to_contain_text("Choose")
    expect(_option(page, 0)).to_be_hidden()
    expect(_option(page, 1)).to_be_hidden()

    _cycler(page).click()
    expect(_option(page, 0)).to_be_visible()
    expect(_placeholder(page)).to_be_hidden()

    _cycler(page).click()
    expect(_option(page, 1)).to_be_visible()
    expect(_option(page, 0)).to_be_hidden()

    _cycler(page).click()  # wraps back to the placeholder
    expect(_placeholder(page)).to_be_visible()
    expect(_option(page, 1)).to_be_hidden()


# ---------------------------------------------------------------------------
# 2. Wrong choice -> Try again, stays gated, cycler still live
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_wrong_choice_shows_try_again_and_stays_gated(page, live_server):
    """Behaviour 2: a wrong, server-checked choice keeps the following block hidden,
    shows the "Try again" message, and leaves the cycler enabled + Confirm live."""
    _student, unit = _new_unit("sg_wrong")
    add_element(unit, _switchgate("Pick: {{choice}}", ["Alpha", "Bravo"], answer=1))
    add_element(unit, _text("<p>SECRET block</p>"))
    _login(page, live_server, "sg_wrong")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    expect(page.get_by_text("SECRET block")).to_be_hidden()

    _cycler(page).click()  # -> opt0 "Alpha" (wrong; answer is index 1)
    expect(_option(page, 0)).to_be_visible()
    _confirm(page).click()

    expect(_feedback(page)).to_be_visible()
    expect(_feedback(page)).to_contain_text("Try again")
    expect(page.get_by_text("SECRET block")).to_be_hidden()
    expect(_cycler(page)).to_have_js_property("disabled", False)
    expect(_confirm(page)).to_be_visible()


# ---------------------------------------------------------------------------
# 3. Wrong then correct -> reveals + locks
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_wrong_then_correct_reveals_and_locks(page, live_server):
    """Behaviour 3: after a wrong attempt, cycling hides "Try again"; a correct choice
    then reveals the following block, disables the cycler and removes Confirm."""
    _student, unit = _new_unit("sg_reset")
    add_element(unit, _switchgate("Pick: {{choice}}", ["Alpha", "Bravo"], answer=1))
    add_element(unit, _text("<p>SECRET block</p>"))
    _login(page, live_server, "sg_reset")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    _cycler(page).click()  # -> opt0 "Alpha" (wrong)
    _confirm(page).click()
    expect(_feedback(page)).to_be_visible()

    _cycler(page).click()  # -> opt1 "Bravo" (correct); Try again re-hides on cycle
    expect(_feedback(page)).to_be_hidden()
    expect(_option(page, 1)).to_be_visible()
    _confirm(page).click()

    expect(page.get_by_text("SECRET block")).to_be_visible()
    expect(_cycler(page)).to_have_js_property("disabled", True)
    expect(_confirm(page)).to_have_count(0)  # Confirm removed once solved
    expect(page.locator("[data-switchgate]")).to_have_class(
        re.compile(r"\bswitchgate--done\b")
    )


# ---------------------------------------------------------------------------
# 4. Preceding gate's cascade stops at the switchgate + focuses the cycler
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_chains_to_next_gate_and_focuses_cycler(page, live_server):
    """Behaviour 4: a plain gate before the switchgate reveals up to and INCLUDING the
    switchgate, then stops (the block after it stays hidden), and focus lands on the
    switchgate's cycler."""
    _student, unit = _new_unit("sg_focus")
    add_element(unit, _text("<p>intro block</p>"))
    add_element(unit, _gate("Reveal A"))
    add_element(unit, _switchgate("Pick: {{choice}}", ["Alpha", "Bravo"], answer=1))
    add_element(unit, _text("<p>after switchgate</p>"))
    _login(page, live_server, "sg_focus")
    page.goto(_unit_url(live_server, unit))

    gate_a = page.get_by_role("button", name="Reveal A")
    expect(gate_a).to_be_visible()
    expect(_cycler(page)).to_be_hidden()
    expect(page.get_by_text("after switchgate")).to_be_hidden()

    gate_a.click()

    # Stop boundary: the switchgate is revealed, the block after it is NOT.
    expect(_cycler(page)).to_be_visible()
    expect(_confirm(page)).to_be_visible()
    expect(page.get_by_text("after switchgate")).to_be_hidden()
    expect(gate_a).to_be_hidden()  # plain gate consumed

    # Focus landed on the switchgate's cycler.
    assert page.evaluate(
        "() => document.activeElement.matches('[data-switchgate-cycler]')"
    )


# ---------------------------------------------------------------------------
# 5. Inline \(...\) math in an option is typeset (KaTeX)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_option_math_typeset(page, live_server):
    """Behaviour 5: an option carrying \\(+\\) is rendered by KaTeX (a .katex node),
    not shown as raw TeX. Drive the cycler to reveal the math option, then assert the
    typeset node is present and visible."""
    _student, unit = _new_unit("sg_math")
    add_element(
        unit, _switchgate("Operator: {{choice}}", [r"\(+\)", "minus"], answer=0)
    )
    _login(page, live_server, "sg_math")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    _cycler(page).click()  # -> opt0 (the \(+\) option)
    expect(_option(page, 0)).to_be_visible()

    math_node = page.locator(".switchgate__option .katex")
    expect(math_node).to_have_count(1)
    expect(math_node.first).to_be_visible()
    # The raw delimiter is gone from the visible option text.
    expect(_option(page, 0)).not_to_contain_text("\\(")


# ---------------------------------------------------------------------------
# 6. Nested inside a tab panel
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_switchgate_nested_in_tab_scopes_to_panel(page, live_server):
    """Behaviour 6: a switchgate nested in tab 1 gates only that tab's following
    children; a correct choice cascades within the panel only, and a SLIDE-level block
    placed AFTER the tabs element is never touched by the nested gate."""
    _student, unit = _new_unit("sg_tab")
    _seed_tab1_gate(
        unit,
        [
            _switchgate("Pick: {{choice}}", ["Alpha", "Bravo"], answer=0),
            _text("<p>tab child one</p>"),
            _text("<p>tab child two</p>"),
        ],
    )
    add_element(unit, _text("<p>slide level after tabs</p>"))
    _login(page, live_server, "sg_tab")
    page.goto(_unit_url(live_server, unit))

    page.wait_for_selector("[data-tabs].tabs--js")
    # Tab 1 active on boot: the switchgate is live; its nested run is pre-hidden; the
    # slide-level sibling after the tabs element is NOT hidden by the nested gate.
    expect(_confirm(page)).to_be_visible()
    expect(page.get_by_text("tab child one")).to_be_hidden()
    expect(page.get_by_text("tab child two")).to_be_hidden()
    expect(page.get_by_text("slide level after tabs")).to_be_visible()

    _cycler(page).click()  # -> opt0 "Alpha" (correct)
    _confirm(page).click()

    expect(page.get_by_text("tab child one")).to_be_visible()
    expect(page.get_by_text("tab child two")).to_be_visible()
    expect(page.get_by_text("slide level after tabs")).to_be_visible()
    expect(page.locator("[data-switchgate]")).to_have_class(
        re.compile(r"\bswitchgate--done\b")
    )


# ---------------------------------------------------------------------------
# 7. No-JS fail-open: content visible, cycler shows only the inert placeholder
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_no_js_shows_content_and_inert_placeholder(browser, live_server):
    """Behaviour 7: with JS disabled the prepaint watchdog never hides anything, so the
    following block stays visible (fail-open), and the cycler shows only the inert
    "Choose ▾" placeholder — the options and Confirm remain hidden (server-rendered
    ``hidden`` attributes), never trapping content behind a dead widget."""
    _student, unit = _new_unit("sg_nojs")
    add_element(unit, _switchgate("Pick: {{choice}}", ["Alpha", "Bravo"], answer=1))
    add_element(unit, _text("<p>SECRET block</p>"))

    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "sg_nojs")
    page.goto(_unit_url(live_server, unit))

    # Fail-open: the following content is visible even though no JS ran.
    expect(page.get_by_text("SECRET block")).to_be_visible()
    # The cycler shows only the inert placeholder.
    expect(_placeholder(page)).to_be_visible()
    expect(_placeholder(page)).to_contain_text("Choose")
    expect(_option(page, 0)).to_be_hidden()
    expect(_option(page, 1)).to_be_hidden()
    # Confirm stays hidden until JS arms it.
    expect(page.locator(".switchgate__confirm")).to_be_hidden()

    ctx.close()


# ---------------------------------------------------------------------------
# 8. Persist {"open": true} on correct choice; restore typesets on boot
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_choice_persists_across_reload(page, live_server):
    """Real gesture: cycle to the correct option, Confirm, await the state POST,
    reload -> content revealed, the correct option shown disabled, done, no Confirm."""
    _student, unit = _new_unit("sg_persist")
    add_element(unit, _switchgate("Pick: {{choice}}", ["Alpha", "Bravo"], answer=1))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "sg_persist")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    _cycler(page).click()  # -> opt0 "Alpha"
    _cycler(page).click()  # -> opt1 "Bravo" (correct; answer index 1)
    expect(_option(page, 1)).to_be_visible()
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        _confirm(page).click()
    assert resp_info.value.ok

    page.reload()
    expect(page.get_by_text("reward block")).to_be_visible()
    expect(page.locator("[data-switchgate]")).to_have_class(
        re.compile(r"\bswitchgate--done\b")
    )
    expect(_confirm(page)).to_have_count(0)
    expect(_cycler(page)).to_have_js_property("disabled", True)
    expect(_option(page, 1)).to_be_visible()  # the correct option, server-shown


@pytest.mark.django_db(transaction=True)
def test_stored_open_switchgate_typesets_math_on_load(page, live_server):
    """Round-1 C1: switchgate math is typeset ONLY by its own initOne (math.js's
    global renderInlineText list excludes .switchgate). Seed {"open": true} for a
    gate whose correct option contains inline \\(...\\); on load the shown option is
    typeset (a .katex node), with no raw \\( left in the switchgate text."""
    student, unit = _new_unit("sg_math_restore")
    sg = add_element(
        unit, _switchgate("Operator: {{choice}}", [r"\(+\)", "minus"], answer=0)
    )
    _seed_state(student, unit, {str(sg.pk): {"open": True}})
    _login(page, live_server, "sg_math_restore")
    page.goto(_unit_url(live_server, unit))

    # The correct option (index 0, the math one) is server-shown; its LaTeX is
    # typeset by switchgate.js's boot short-circuit.
    math_node = page.locator(".switchgate__option .katex")
    expect(math_node).to_have_count(1)
    expect(math_node.first).to_be_visible()
    assert "\\(" not in page.locator(".switchgate").inner_text()
    expect(page.locator("[data-switchgate]")).to_have_class(
        re.compile(r"\bswitchgate--done\b")
    )
