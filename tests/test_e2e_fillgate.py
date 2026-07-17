"""Playwright e2e for the "Fill in & confirm" gate element (plan Task 12). Drives the
REAL student gesture end-to-end — types into the blank input and clicks the actual
Confirm button — never a page.evaluate shortcut into the grading endpoint or reveal.js
internals (this repo's standing lesson: an e2e that bypasses the real gesture ships
broken UX green). page.evaluate is used ONLY to read state (document.activeElement),
never to trigger a reveal.

Covers the seven behaviors from the task brief:
  1. Correct answer -> following sibling reveals (.reveal-shown/visible), inputs become
     readonly + .is-correct, the Confirm button is gone, container is fillgate--done.
  2. Wrong answer -> following block stays hidden, try-again message visible, the wrong
     input has .is-wrong, inputs still editable, Confirm still present.
  3. Multi-attempt reset -> wrong then correct: no stale .is-wrong, message gone, block
     revealed.
  4. No grading bypass -> clicking inside the fill-gate WITHOUT a correct submit reveals
     nothing.
  5. Focus -> a preceding PLAIN gate's cascade that stops at a fill-gate lands focus on
     the fill-gate's first input[name="blank"].
  6. Stop boundary -> a plain gate before a fill-gate reveals up to and including the
     fill-gate, then stops (block after the fill-gate stays hidden).
  7. Nested-in-tab -> a fill-gate inside a tab panel cascades within that panel only.

Mirrors the harness in tests/test_e2e_reveal_gate.py (login/seed/unit helpers, tab
seeding). Marked e2e (excluded from the default run; run with -m e2e)."""

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
# Login / seed helpers (mirrored from tests/test_e2e_reveal_gate.py)
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


def _fillgate(author_stem):
    """Build a FillGateElement from author `{{answer}}` markup (use | for
    alternatives), as the form's clean_stem/save would: parse to token-stem+answers."""
    from courses.fillblank import parse
    from courses.models import FillGateElement

    token_stem, blanks = parse(author_stem)
    return FillGateElement.objects.create(stem=token_stem, answers=blanks)


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
def _blank(page):
    return page.locator('[data-fillgate] input[name="blank"]').first


def _confirm(page):
    return page.get_by_role("button", name="Confirm")


# ---------------------------------------------------------------------------
# 1. Correct answer reveals + locks
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_correct_answer_reveals_and_locks(page, live_server):
    """Behavior 1: a correct, server-checked answer reveals the following block, locks
    the inputs (readonly + .is-correct), removes Confirm, marks the container done."""
    _student, unit = _new_unit("fg_correct")
    add_element(unit, _text("<p>intro block</p>"))
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_correct")
    page.goto(_unit_url(live_server, unit))

    # Boot: fillgate.js arms Confirm; the following block is pre-hidden by the gate.
    expect(_confirm(page)).to_be_visible()
    expect(_blank(page)).to_be_visible()
    expect(page.get_by_text("reward block")).to_be_hidden()

    _blank(page).fill("Paris")
    _confirm(page).click()

    expect(page.get_by_text("reward block")).to_be_visible()
    expect(_blank(page)).to_have_class(re.compile(r"\bis-correct\b"))
    expect(_blank(page)).to_have_js_property("readOnly", True)
    expect(_confirm(page)).to_have_count(0)  # Confirm removed once answered
    expect(page.locator("[data-fillgate]")).to_have_class(
        re.compile(r"\bfillgate--done\b")
    )


# ---------------------------------------------------------------------------
# 1b. A long correct answer stays fully visible once locked (regression: the
#     blank input's fixed 8ch width clipped answers longer than ~8 chars, so a
#     locked long word showed only its beginning).
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_long_correct_answer_not_clipped_when_locked(page, live_server):
    _student, unit = _new_unit("fg_long")
    add_element(unit, _fillgate("Largest city on the Bosphorus? {{Constantinople}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_long")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    _blank(page).fill("Constantinople")
    _confirm(page).click()

    # Locked read-only correct input: the full answer must fit — no horizontal
    # overflow (content wider than the box would clip it to the leading chars).
    expect(_blank(page)).to_have_js_property("readOnly", True)
    assert page.evaluate(
        "() => { const i = document.querySelector("
        "'[data-fillgate] input[name=\"blank\"]');"
        " return i.scrollWidth <= i.clientWidth + 1; }"
    )


# ---------------------------------------------------------------------------
# 2. Wrong answer stays gated
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_wrong_answer_stays_gated(page, live_server):
    """Behavior 2: a wrong answer keeps the following block hidden, shows the try-again
    message, marks the wrong input .is-wrong, leaves inputs editable + Confirm live."""
    _student, unit = _new_unit("fg_wrong")
    add_element(unit, _text("<p>intro block</p>"))
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_wrong")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    _blank(page).fill("London")
    _confirm(page).click()

    # Still gated.
    expect(page.get_by_text("reward block")).to_be_hidden()
    # Try-again message shown.
    expect(page.locator("[data-fillgate-feedback]")).to_be_visible()
    expect(page.locator("[data-fillgate-feedback]")).to_contain_text("try again")
    # Wrong input marked, still editable, Confirm still present.
    expect(_blank(page)).to_have_class(re.compile(r"\bis-wrong\b"))
    expect(_blank(page)).to_have_js_property("readOnly", False)
    expect(_confirm(page)).to_be_visible()


# ---------------------------------------------------------------------------
# 3. Multi-attempt reset (wrong -> correct)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_wrong_then_correct_resets_and_reveals(page, live_server):
    """Behavior 3: after a wrong attempt, a correct one clears the .is-wrong marker,
    hides the try-again message, and reveals the following block."""
    _student, unit = _new_unit("fg_reset")
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_reset")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    _blank(page).fill("London")
    _confirm(page).click()
    expect(_blank(page)).to_have_class(re.compile(r"\bis-wrong\b"))
    expect(page.locator("[data-fillgate-feedback]")).to_be_visible()

    # Correct on the second attempt.
    _blank(page).fill("Paris")
    _confirm(page).click()

    expect(page.get_by_text("reward block")).to_be_visible()
    expect(_blank(page)).not_to_have_class(re.compile(r"\bis-wrong\b"))
    expect(page.locator("[data-fillgate-feedback]")).to_be_hidden()


# ---------------------------------------------------------------------------
# 4. No grading bypass
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_clicking_container_does_not_reveal(page, live_server):
    """Behavior 4: interacting with the fill-gate (focusing/clicking the blank) without
    a correct submit reveals nothing — only a server-confirmed answer opens the gate."""
    _student, unit = _new_unit("fg_bypass")
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_bypass")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    # Click into the container / blank; type without confirming.
    page.locator("[data-fillgate]").click()
    _blank(page).click()
    _blank(page).fill("Paris")

    expect(page.get_by_text("reward block")).to_be_hidden()
    expect(page.locator("[data-fillgate]")).not_to_have_class(
        re.compile(r"\bfillgate--done\b")
    )
    expect(_confirm(page)).to_be_visible()  # nothing consumed


# ---------------------------------------------------------------------------
# 5 + 6. Focus lands on the blank & stop boundary
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_plain_gate_stops_at_fillgate_and_focuses_blank(page, live_server):
    """Behaviors 5 & 6: a plain gate before a fill-gate reveals up to and INCLUDING the
    fill-gate, then stops (the block after the fill-gate stays hidden), and focus lands
    on the fill-gate's first input[name="blank"]."""
    _student, unit = _new_unit("fg_focus")
    add_element(unit, _text("<p>intro block</p>"))
    add_element(unit, _gate("Reveal A"))
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>after fillgate</p>"))
    _login(page, live_server, "fg_focus")
    page.goto(_unit_url(live_server, unit))

    gate_a = page.get_by_role("button", name="Reveal A")
    expect(gate_a).to_be_visible()
    # At rest: the fill-gate and the block after it are both hidden.
    expect(_blank(page)).to_be_hidden()
    expect(page.get_by_text("after fillgate")).to_be_hidden()

    gate_a.click()

    # Stop boundary: fill-gate revealed, but the block after it is NOT.
    expect(_blank(page)).to_be_visible()
    expect(_confirm(page)).to_be_visible()
    expect(page.get_by_text("after fillgate")).to_be_hidden()
    expect(gate_a).to_be_hidden()  # plain gate consumed

    # Focus landed on the fill-gate's first blank input.
    assert page.evaluate(
        "() => document.activeElement.matches('[data-fillgate] input[name=\"blank\"]')"
    )


# ---------------------------------------------------------------------------
# 7. Nested inside a tab panel
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_fillgate_nested_in_tab_scopes_to_that_panel(page, live_server):
    """Behavior 7: a fill-gate nested in tab 1 gates only that tab's following children;
    a correct answer cascades within the panel only, and a SLIDE-level block placed
    AFTER the tabs element is never touched by the nested gate."""
    _student, unit = _new_unit("fg_tab")
    _seed_tab1_gate(
        unit,
        [
            _fillgate("Capital of France? {{Paris}}"),
            _text("<p>tab child one</p>"),
            _text("<p>tab child two</p>"),
        ],
    )
    add_element(unit, _text("<p>slide level after tabs</p>"))
    _login(page, live_server, "fg_tab")
    page.goto(_unit_url(live_server, unit))

    page.wait_for_selector("[data-tabs].tabs--js")
    # Tab 1 is active on boot: the fill-gate is live; its nested run is pre-hidden; the
    # slide-level sibling after the tabs element is NOT hidden by the nested gate.
    expect(_confirm(page)).to_be_visible()
    expect(page.get_by_text("tab child one")).to_be_hidden()
    expect(page.get_by_text("tab child two")).to_be_hidden()
    expect(page.get_by_text("slide level after tabs")).to_be_visible()

    _blank(page).fill("Paris")
    _confirm(page).click()

    # Cascade stays within the panel: the tab children reveal; the slide-level sibling
    # remains visible throughout (was never part of this gate's run).
    expect(page.get_by_text("tab child one")).to_be_visible()
    expect(page.get_by_text("tab child two")).to_be_visible()
    expect(page.get_by_text("slide level after tabs")).to_be_visible()
    expect(page.locator("[data-fillgate]")).to_have_class(
        re.compile(r"\bfillgate--done\b")
    )


# ---------------------------------------------------------------------------
# 8. Inline \(...\) math in the stem is typeset on the STUDENT page (not only
#    the editor preview). Regression for: the lesson inline-math pass only
#    covered .el--text/.el--table/.el--gallery/.el--tabs and [data-question],
#    so a fill-gate stem's math stayed raw for students.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_stem_math_renders_in_student_view(page, live_server):
    from courses.models import Element

    _student, unit = _new_unit("fg_math")
    fg = _fillgate(r"The square \(x^2\) grows fast, so 2 + 2 = {{4}}.")
    Element.objects.create(unit=unit, content_object=fg)
    _login(page, live_server, "fg_math")
    page.goto(_unit_url(live_server, unit))

    page.wait_for_selector("[data-fillgate] .fillgate__confirm:not([hidden])")
    body = page.locator("[data-fillgate] .fillgate__body")
    # KaTeX replaced the \(x^2\) delimiters with a rendered .katex node.
    expect(body.locator(".katex")).to_have_count(1)
    # And the raw delimiter is gone from the visible text.
    expect(body).not_to_contain_text("\\(")


# ---------------------------------------------------------------------------
# 9. Restore walk (plan Task 6): a stored-open fill gate cascades on load, the
#    walk continues past it to later gates, and an unanswered fill gate still
#    stops the walk (prefix-closure).
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_stored_open_fillgate_restores_content_on_load(page, live_server):
    """A previously-answered fill gate: seed {"open": true}, load, the following
    block is revealed (content restored) and the widget stays (locked, done)."""
    student, unit = _new_unit("fg_restore")
    add_element(unit, _text("<p>intro block</p>"))
    fg = add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _seed_state(student, unit, {str(fg.pk): {"open": True}})
    _login(page, live_server, "fg_restore")
    page.goto(_unit_url(live_server, unit))

    expect(page.get_by_text("reward block")).to_be_visible()
    expect(page.locator("[data-fillgate]")).to_have_class(
        re.compile(r"\bfillgate--done\b")
    )
    expect(_confirm(page)).to_have_count(0)  # server omitted Confirm when open


@pytest.mark.django_db(transaction=True)
def test_answered_fillgate_lets_a_later_plain_gate_restore(page, live_server):
    """The walk must CONTINUE past a restored fill gate: a stored-open fill gate
    followed by a stored-open plain gate -> BOTH restore. This is what falsifies
    keeping the old `!matches(RESTORABLE) break` (which stops the walk at the fill
    gate, so the later plain gate never restores)."""
    student, unit = _new_unit("fg_chain")
    fg = add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>between gates</p>"))
    plain = add_element(unit, _gate("Show more"))
    add_element(unit, _text("<p>past the plain gate</p>"))
    _seed_state(
        student, unit, {str(fg.pk): {"open": True}, str(plain.pk): {"open": True}}
    )
    _login(page, live_server, "fg_chain")
    page.goto(_unit_url(live_server, unit))

    expect(page.get_by_text("between gates")).to_be_visible()  # fill gate cascaded
    expect(page.get_by_text("past the plain gate")).to_be_visible()  # walk continued


@pytest.mark.django_db(transaction=True)
def test_unanswered_fillgate_stops_the_walk(page, live_server):
    """Prefix-closure across the new family: a stored-open PLAIN gate placed AFTER
    an unanswered fill gate must NOT restore -- the fill gate is a barrier."""
    student, unit = _new_unit("fg_prefix")
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))  # unanswered
    plain = add_element(unit, _gate("Show more"))
    add_element(unit, _text("<p>past the plain gate</p>"))
    _seed_state(student, unit, {str(plain.pk): {"open": True}})
    _login(page, live_server, "fg_prefix")
    page.goto(_unit_url(live_server, unit))

    # The block past the (stored-open) plain gate stays hidden, because the
    # unanswered fill gate stops the walk before the plain gate is reached.
    expect(page.get_by_text("past the plain gate")).to_be_hidden()


# ---------------------------------------------------------------------------
# 10. Client-side persistence on correct (plan Task 7): save on correct,
#     skip-arm + preventDefault-only submit on a restored (stored-open) gate.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_correct_answer_persists_across_reload(page, live_server):
    """Real gesture: answer correctly, await the state POST, reload -> content still
    revealed AND the blank shows the canonical answer locked, no Confirm."""
    _student, unit = _new_unit("fg_persist")
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_persist")
    page.goto(_unit_url(live_server, unit))

    expect(_confirm(page)).to_be_visible()
    _blank(page).fill("Paris")
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        _confirm(page).click()
    assert resp_info.value.ok

    page.reload()
    expect(page.get_by_text("reward block")).to_be_visible()
    expect(_blank(page)).to_have_js_property("readOnly", True)
    expect(_blank(page)).to_have_value("Paris")
    expect(_confirm(page)).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_long_answer_not_clipped_after_reload(page, live_server):
    """Round-2 C1: the server must emit `size`, or width:auto clips a long answer
    to ~20ch on the restore path (the JS lock() that sets size never runs on boot)."""
    _student, unit = _new_unit("fg_persist_long")
    add_element(unit, _fillgate("Largest city on the Bosphorus? {{Constantinople}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_persist_long")
    page.goto(_unit_url(live_server, unit))

    _blank(page).fill("Constantinople")
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ):
        _confirm(page).click()

    page.reload()
    expect(_blank(page)).to_have_js_property("readOnly", True)
    assert page.evaluate(
        "() => { const i = document.querySelector("
        "'[data-fillgate] input[name=\"blank\"]');"
        " return i.scrollWidth <= i.clientWidth + 1; }"
    )


@pytest.mark.django_db(transaction=True)
def test_wrong_answer_persists_nothing(page, live_server):
    """A wrong answer makes NO state POST; reload -> fresh editable widget, hidden."""
    _student, unit = _new_unit("fg_wrong_nosave")
    add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _login(page, live_server, "fg_wrong_nosave")
    page.goto(_unit_url(live_server, unit))

    saw_state_post = {"hit": False}
    page.on(
        "request",
        lambda r: saw_state_post.__setitem__(
            "hit", saw_state_post["hit"] or "/state/" in r.url
        ),
    )
    _blank(page).fill("London")
    _confirm(page).click()
    expect(page.locator("[data-fillgate-feedback]")).to_be_visible()
    assert saw_state_post["hit"] is False

    page.reload()
    expect(_blank(page)).to_have_js_property("readOnly", False)
    expect(page.get_by_text("reward block")).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_restored_fillgate_does_not_navigate_on_enter(page, live_server):
    """Round-3 I2: a restored single-blank form must not implicitly submit (Enter)
    and navigate away. The boot preventDefault-only handler blocks it."""
    student, unit = _new_unit("fg_enter")
    fg = add_element(unit, _fillgate("Capital of France? {{Paris}}"))
    add_element(unit, _text("<p>reward block</p>"))
    _seed_state(student, unit, {str(fg.pk): {"open": True}})
    _login(page, live_server, "fg_enter")
    url = _unit_url(live_server, unit)
    page.goto(url)

    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    _blank(page).focus()
    _blank(page).press("Enter")
    page.wait_for_timeout(150)  # allow any (wrongly) queued navigation / POST to start
    assert page.url == url  # no navigation / reload
    # The distinguishing assertion (spec §e2e): skip-arm binds a preventDefault-ONLY
    # handler, so NO check POST fires. The normal handler also preventDefaults (so
    # page.url alone can't tell them apart) but additionally POSTs to fillgate_check.
    assert posts == []
