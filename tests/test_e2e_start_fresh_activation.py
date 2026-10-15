"""e2e: the unit page's "Start fresh" control is INACTIVE until a save stores
something, then activates live (spec 2026-10-15). Drives real UI; syncs on responses
and DOM signals, never sleeps."""

import os
import re

import pytest
from django.urls import reverse
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

CONTROL = ".lesson-unit__head .lesson-unit__reset"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _unit(username):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    EnrollmentFactory(student=student, course=course)
    return student, unit


def _url(live_server, unit):
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _expected_href(unit):
    return (
        reverse("courses:progress_reset", args=[unit.course.slug, unit.pk])
        + "?next="
        + reverse("courses:lesson_unit", args=[unit.course.slug, unit.pk])
    )


def _is_state_save(r):
    return "/state/" in r.url and r.request.method == "POST"


def _assert_inactive(page):
    c = page.locator(CONTROL)
    expect(c).to_have_attribute("aria-disabled", "true")
    expect(c).not_to_have_attribute("href", re.compile(".*"))


def _wait_active(page):
    page.wait_for_selector(f"{CONTROL}[href]")


def _settle_completion(page):
    """progress.js POSTs /seen/ ~500 ms after load and, when every element is
    visible, auto-completes the unit and swaps the "Mark as done" pill for
    "Completed" (unit_done.js adds .is-complete). That pill sits BEFORE the control
    in the head row, so any geometry/hover measurement must wait for it first.

    If .is-complete never appears for a unit (auto-complete did not fire), replace
    this body with page.expect_response on the /seen/ POST plus a wait for the pill
    text to settle. NEVER delete the settling step itself."""
    page.wait_for_selector(".unit-done.is-complete")


def test_reveal_gate_activates_live_with_full_contract(page, live_server):
    from courses.models import RevealGateElement
    from courses.models import TextElement

    _s, unit = _unit("sf_reveal")
    add_element(unit, TextElement.objects.create(body="<p>before</p>"))
    add_element(unit, RevealGateElement.objects.create(label="Show more"))
    add_element(unit, TextElement.objects.create(body="<p>after</p>"))
    _login(page, live_server, "sf_reveal")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)
    inactive_opacity = page.locator(CONTROL).evaluate(
        "el => getComputedStyle(el).opacity"
    )
    assert (
        page.locator(CONTROL).evaluate("el => getComputedStyle(el).cursor") == "default"
    )

    page.get_by_role("button", name="Show more").click()
    _wait_active(page)

    c = page.locator(CONTROL)
    for attr in ("aria-disabled", "role", "title"):
        assert c.get_attribute(attr) is None, attr
    assert c.get_attribute("href") == _expected_href(unit)
    active_opacity = c.evaluate("el => getComputedStyle(el).opacity")
    assert active_opacity == "1"
    assert inactive_opacity != active_opacity  # anti-vacuity: the styling exists

    c.click()
    reset_path = reverse("courses:progress_reset", args=[unit.course.slug, unit.pk])
    page.wait_for_url(re.compile(re.escape(reset_path)))
    # Positive anchor: the POPULATED branch of progress_reset_confirm.html. The
    # count-0 check alone also passes on a 403/500 page.
    expect(page.locator(".reset-confirm__blast")).to_contain_text("1 lesson")
    expect(page.locator(".reset-confirm button[type='submit']")).to_be_visible()
    expect(page.get_by_text("Nothing to clear here.")).to_have_count(0)


def test_fill_gate_answered_correctly_activates(page, live_server):
    from courses.fillblank import parse
    from courses.models import FillGateElement
    from courses.models import TextElement

    _s, unit = _unit("sf_fillgate")
    token_stem, blanks = parse("Capital of France? {{Paris}}")
    add_element(unit, FillGateElement.objects.create(stem=token_stem, answers=blanks))
    add_element(unit, TextElement.objects.create(body="<p>reward</p>"))
    _login(page, live_server, "sf_fillgate")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)

    blank = page.locator('[data-fillgate] input[name="blank"]').first
    blank.fill("Paris")
    with page.expect_response(_is_state_save) as resp:
        page.get_by_role("button", name="Confirm").click()
    assert resp.value.ok
    _wait_active(page)


def _choice_unit(username):
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    _s, unit = _unit(username)
    q = ChoiceQuestionElement.objects.create(stem="Pick one", multiple=False)
    Choice.objects.create(question=q, text="Alpha", is_correct=True, order=0)
    Choice.objects.create(question=q, text="Beta", is_correct=False, order=1)
    add_element(unit, q)
    return unit


def _arm_swap_probe(page):
    """Test setup, not a gesture: a child the inline swap (form.innerHTML = …) will
    destroy, so its detachment proves the SECOND .then ran -- after the first-.then
    dispatch line."""
    page.locator("[data-question] form").evaluate(
        "f => { const i = document.createElement('i'); "
        "i.setAttribute('data-e2e-probe', ''); f.appendChild(i); }"
    )


def test_inline_choice_nonempty_answer_activates(page, live_server):
    # ONLY guard for the mutant "question.js dispatch moved to the end of the second
    # .then" (the inline branch returns early there). Do not trim.
    unit = _choice_unit("sf_choice")
    _login(page, live_server, "sf_choice")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)
    page.get_by_label("Alpha").check()
    page.get_by_role("button", name="Check").click()
    _wait_active(page)


def test_inline_choice_empty_answer_stays_inactive(page, live_server):
    unit = _choice_unit("sf_choice_empty")
    _login(page, live_server, "sf_choice_empty")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)
    _arm_swap_probe(page)
    page.get_by_role("button", name="Check").click()
    page.wait_for_selector("[data-e2e-probe]", state="detached")
    _assert_inactive(page)


def test_markdone_stays_active_after_untick_then_inactive_after_reload(
    page, live_server
):
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem

    _s, unit = _unit("sf_markdone")
    md = MarkDoneElement.objects.create(prompt="Prep")
    MarkDoneItem.objects.create(element=md, content="one")
    add_element(unit, md)
    _login(page, live_server, "sf_markdone")
    page.goto(_url(live_server, unit))
    _assert_inactive(page)

    box = page.locator(".markdone__item input[type='checkbox']").first
    with page.expect_response(_is_state_save) as r1:
        box.check()
    assert r1.value.ok
    _wait_active(page)

    with page.expect_response(_is_state_save) as r2:
        box.uncheck()
    assert r2.value.ok
    assert r2.value.json()["state"] == {}  # the final save stored nothing
    # D6: the control stays active although nothing is stored any more
    expect(page.locator(CONTROL)).to_have_attribute("href", _expected_href(unit))

    page.reload()
    _assert_inactive(page)


def test_pressed_inactive_control_paints_no_fill(page, live_server):
    from courses.models import MarkDoneElement

    _s, unit = _unit("sf_pressed")
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    _login(page, live_server, "sf_pressed")
    page.goto(_url(live_server, unit))
    _settle_completion(page)
    _assert_inactive(page)
    box = page.locator(CONTROL).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    hover_bg = page.locator(CONTROL).evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    page.mouse.down()
    # Move OFF the control with the button held: Chrome keeps :active but drops
    # :hover, so this reading isolates the :active override. Read while hovered,
    # the :hover rule (0,3,0) would mask a missing :active rule.
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] + 40)
    pressed_bg = page.locator(CONTROL).evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    still_active = page.locator(CONTROL).evaluate("el => el.matches(':active')")
    page.mouse.up()
    assert still_active, "anti-vacuity: the control must still be :active"
    assert hover_bg == "rgba(0, 0, 0, 0)", hover_bg
    assert pressed_bg == "rgba(0, 0, 0, 0)", pressed_bg
