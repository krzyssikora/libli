"""Playwright e2e: a nested `choice` question checks and shows inline feedback
with JS ON, in the two containers that HIDE their children (plan Task 10, spec
section 9.8).

`question.js` binds to `[data-question]` document-wide with no depth assumption,
so no JS change is expected for the widening -- these tests exist to PROVE that
rather than assume it. The two containers chosen are the ones whose children are
not simply laid out but actively hidden, i.e. the two places where a
depth-assuming or measurement-based enhancer would break:

  * a CLOSED `<details>` spoiler -- content hidden by the disclosure itself;
  * an INACTIVE tabs panel -- tabs.js sets the `hidden` ATTRIBUTE on it.

Both are driven with the REAL student gesture: open the disclosure / click the
tab, tick an option, click the actual Check button. Never a page.evaluate
shortcut into check_answer or into question.js's internals.

Two traps this file is written around (both are repo lessons, not theory):

  * Playwright reports a screen-reader-only node as VISIBLE. `.sr-only`
    (reset.css) is `position:absolute; width:1px; height:1px; clip:rect(0 0 0
    0)` -- a 1x1 box is a NON-EMPTY box, so `is_visible()` is True and asserting
    on it proves nothing about what a sighted student sees. The marker
    assertions therefore read `bounding_box()` and compare the glyph's real box
    against the sr-only label's 1x1 one.
  * A closed `<details>` hides its content through `content-visibility`, which
    Playwright's `is_visible()` does not model -- an element inside a closed
    disclosure still reports a box. `checkVisibility()` (the DOM method, called
    through `evaluate`) does model it, so the "hidden while closed" precondition
    is asserted with that.

Marked e2e (excluded from the default run; run with `-m e2e`).
Login/seed harness mirrored from tests/test_e2e_switchgrid.py, which already
drives a NESTABLE_TYPE_KEYS member nested inside a Tabs panel.
"""

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
# Login / seed helpers (mirrored from tests/test_e2e_switchgrid.py)
# ---------------------------------------------------------------------------


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _new_lesson(username):
    """An enrolled student + a fresh LESSON unit. Returns (student, unit).

    Lesson, not quiz, on purpose: the widening is lesson-only (spec section 6.3),
    and the quiz render path deliberately withholds per-option marks anyway.
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Lesson"
    )
    EnrollmentFactory(student=student, course=course)
    return student, unit


def _unit_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _choice_question():
    """Single-choice A (correct) / C (distractor), BOTH carrying feedback.

    The feedback strings are load-bearing. choice_marks' LESSON branch marks only
    options in mark_result.annotated, and mark() annotates only options that HAVE
    feedback -- with feedback="" the marker assertions below would be vacuous.
    """
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="Pick the right one.", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True, feedback="need A")
    Choice.objects.create(question=q, text="C", is_correct=False, feedback="trap C")
    return q


def _nest_in_spoiler(unit, obj):
    """One SpoilerElement on `unit` with `obj` nested inside it."""
    from courses.models import Element
    from courses.models import SpoilerElement

    spoiler = SpoilerElement.objects.create(label="Show the task")
    join = add_element(unit, spoiler)
    return Element.objects.create(
        unit=unit, content_object=obj, parent=join, tab_id=SpoilerElement.SLOT_ID
    )


def _nest_in_tab2(unit, obj):
    """One TabsElement ('First'/'Second') with `obj` nested under the SECOND tab.

    The second tab is what makes the panel INACTIVE at load: tabs.js activates
    index 0 and sets the `hidden` attribute on every other panel.
    """
    from courses.models import Element
    from courses.models import TabsElement

    tabs = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": "t000001", "label": "First"},
                {"id": "t000002", "label": "Second"},
            ]
        }
    )
    join = add_element(unit, tabs)
    return Element.objects.create(
        unit=unit, content_object=obj, parent=join, tab_id="t000002"
    )


def _question(page):
    return page.locator("[data-question]").first


def _option_li(question_el, text):
    """The `.question__choice` <li> whose option TEXT is exactly `text`.

    Anchoring on the leaf `.question__choice-text` span and walking up, rather
    than `.question__choice` + has_text: has_text is a SUBSTRING match, so "A"
    would also select the "trap C" row once its feedback text lands in the <li>.
    Same helper shape as tests/test_e2e_choice_inline_feedback.py:32.
    """
    pattern = re.compile(rf"^{re.escape(text)}$")
    span = question_el.locator(".question__choice-text").filter(has_text=pattern)
    return span.locator("xpath=ancestor::li[1]")


def _rendered(locator):
    """DOM checkVisibility() for this node.

    NOT Playwright's is_visible(): a closed <details> hides its subtree through
    `content-visibility`, which is a rendering suppression Playwright's own
    visibility model does not implement -- a node inside a closed disclosure
    still reports a box and still reads as "visible".
    """
    return locator.evaluate("el => el.checkVisibility()")


def _mark_boxes(li):
    """(glyph box, sr-only label box) for one option row.

    Returned as raw boxes rather than booleans so the caller can state the real
    claim: the glyph occupies a genuine box, the sr-only label is the 1x1
    clipped one Playwright would happily call `visible`.
    """
    glyph = li.locator(".question__choice-marker").bounding_box()
    label = li.locator(".sr-only").bounding_box()
    return glyph, label


# ---------------------------------------------------------------------------
# 1. Closed <details> spoiler
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_nested_question_in_a_closed_spoiler_checks_inline(page, live_server):
    """A choice question nested in a CLOSED spoiler: hidden at rest, and once the
    student opens the disclosure it checks and feeds back INLINE, with no page
    navigation -- i.e. question.js bound to it at depth 2 exactly as at depth 1."""
    _student, unit = _new_lesson("nq_spoiler")
    _nest_in_spoiler(unit, _choice_question())
    _login(page, live_server, "nq_spoiler")
    page.goto(_unit_url(live_server, unit))
    # state="attached": the default "visible" is exactly the model this file's
    # docstring says is wrong for a closed <details>, so waiting on it would make
    # the precondition below depend on the bug it is guarding.
    page.wait_for_selector("[data-question]", state="attached")

    details = page.locator("details.spoiler")
    expect(details).not_to_have_attribute("open", "")
    q = _question(page)
    # Precondition: the nested question really is inside a CLOSED disclosure.
    # checkVisibility(), not is_visible() -- see _rendered's docstring.
    assert _rendered(q) is False

    # Real gesture: open the disclosure.
    details.locator("summary.spoiler__toggle").click()
    assert _rendered(q) is True

    # A marker that survives a full page navigation would prove nothing about the
    # JS path, so stamp the window and assert the stamp is still there afterwards.
    page.evaluate("() => { window.__nqNoReload = true; }")

    c_li = _option_li(q, "C")
    c_li.locator("input[type='radio']").check()
    q.locator("button[type='submit']").click()

    # Inline verdict, inside the spoiler's own child wrapper.
    verdict = page.locator(".spoiler__child .question__verdict.is-incorrect")
    expect(verdict).to_be_visible()
    # Per-option feedback for BOTH the picked distractor and the missed correct
    # option (mark() annotates the symmetric difference).
    expect(c_li.locator(".question__choice-feedback")).to_have_text("trap C")
    a_li = _option_li(q, "A")
    expect(a_li.locator(".question__choice-feedback")).to_have_text("need A")

    # No navigation happened: this was the fetch path, not the no-JS re-render.
    assert page.evaluate("() => window.__nqNoReload === true")
    # And the disclosure is still open -- nothing re-collapsed it.
    expect(details).to_have_attribute("open", "")

    # The per-option marker: a REAL box for the glyph, a 1x1 clipped box for the
    # screen-reader label Playwright would call "visible".
    glyph_box, label_box = _mark_boxes(c_li)
    assert glyph_box["width"] > 1 and glyph_box["height"] > 1
    assert label_box["width"] <= 1 and label_box["height"] <= 1


# ---------------------------------------------------------------------------
# 2. Inactive tabs panel
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_nested_question_in_an_inactive_tab_panel_checks_inline(page, live_server):
    """A choice question nested under the SECOND tab: hidden while that panel is
    inactive, and fully live once the student selects the tab. Correct answer ->
    inline success verdict + question.js's finishSolved hiding the Check button,
    which is the depth-independent behaviour the widening must not have broken."""
    _student, unit = _new_lesson("nq_tabs")
    _nest_in_tab2(unit, _choice_question())
    _login(page, live_server, "nq_tabs")
    page.goto(_unit_url(live_server, unit))
    page.wait_for_selector("[data-tabs].tabs--js")

    panel2 = page.locator("[data-tab-panel][data-tab-id='t000002']")
    # tabs.js hides an inactive panel with the `hidden` ATTRIBUTE.
    expect(panel2).to_have_attribute("hidden", "")
    q = _question(page)
    assert _rendered(q) is False

    page.evaluate("() => { window.__nqNoReload = true; }")

    # Real gesture: select the second tab from the generated tablist.
    page.locator(".tabs__tab").nth(1).click()
    expect(panel2).not_to_have_attribute("hidden", "")
    assert _rendered(q) is True

    a_li = _option_li(q, "A")
    a_li.locator("input[type='radio']").check()
    q.locator("button[type='submit']").click()

    verdict = page.locator(".tabs__child .question__verdict.is-correct")
    expect(verdict).to_be_visible()
    # A fully correct answer annotates nothing, so no per-option feedback.
    expect(q.locator(".question__choice-feedback")).to_have_count(0)
    # finishSolved hid the Check button on the LIVE form.
    expect(q.locator("button[type='submit']")).to_be_hidden()
    assert page.evaluate("() => window.__nqNoReload === true")
