"""Playwright e2e: an EDITABLE fill-in blank grows with what the student types.

The blank was pinned to `width: 8ch`, and app.css's `input[type=text]` rule (0,1,1)
outranked the blank's own padding (0,1,0) with 12px a side -- MEASURED: an 81px box
with ~55px for text, so `tg alpha` already scrolled out of view while typing. Now
the blank keeps 8ch as its MINIMUM and grows to fit its value (CSS `field-sizing:
content`, or blank_autosize.js where that is unsupported), capped at the line.

The fallback test simulates a browser without field-sizing inside Chromium: it
stubs CSS.supports and forces `field-sizing: fixed`, so only the JS can grow the box.

Marked e2e (excluded from the default run; run with -m e2e).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

LONG = "sin alfa razy cos alfa"  # 22 chars -- far past the 8ch minimum


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


def _seed(username, unit_type, concrete):
    """An enrolled student and a unit of `unit_type` holding `concrete`. Returns
    the unit's URL path."""
    from django.urls import reverse

    from courses.models import Element
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type=unit_type)
    EnrollmentFactory(student=student, course=course)
    Element.objects.create(unit=unit, content_object=concrete())
    name = "courses:quiz_unit" if unit_type == "quiz" else "courses:lesson_unit"
    return reverse(name, kwargs={"slug": course.slug, "node_pk": unit.pk})


def _fillgate():
    from courses.fillblank import parse
    from courses.models import FillGateElement

    token_stem, blanks = parse("Wiemy, że sin a = {{tg a}} · cos a")
    return FillGateElement.objects.create(stem=token_stem, answers=blanks)


def _fillblank_question():
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    fb = FillBlankQuestionElement.objects.create(stem="sin a = ￿0￿ · cos a")
    Blank.objects.create(question=fb, order=0, accepted="tg a")
    return fb


def _metrics(blank):
    return blank.evaluate(
        """el => {
          const s = getComputedStyle(el);
          const probe = document.createElement('span');
          probe.style.cssText = 'position:absolute;visibility:hidden;font:' + s.font +
            ';padding:0 var(--space-2);width:8ch;box-sizing:border-box';
          document.body.appendChild(probe);
          const eightCh = probe.getBoundingClientRect().width;
          probe.style.width = 'auto';
          probe.textContent = '';
          const space2 = parseFloat(getComputedStyle(probe).paddingLeft);
          probe.remove();
          return { scroll: el.scrollWidth, client: el.clientWidth,
                   width: el.getBoundingClientRect().width,
                   parent: el.parentElement.getBoundingClientRect().width,
                   padLeft: parseFloat(s.paddingLeft), space2, eightCh };
        }"""
    )


def _open(browser, live_server, username, path, *, no_field_sizing=False):
    ctx = browser.new_context()
    page = ctx.new_page()
    if no_field_sizing:
        # A browser without field-sizing: CSS.supports says no BEFORE any script
        # runs, and the property is forced off so only the JS fallback can grow.
        page.add_init_script(
            """(() => { const orig = CSS.supports.bind(CSS);
              CSS.supports = function (a, b) {
                if (String(a).indexOf('field-sizing') !== -1) return false;
                return orig.apply(null, arguments); }; })();"""
        )
    _login(page, live_server, username)
    page.goto(f"{live_server.url}{path}")
    if no_field_sizing:
        # Undo the @supports block as an unsupporting browser would never apply it:
        # (0,2,2) outranks it, while an inline width (the JS) still outranks this.
        page.add_style_tag(
            content='html input.question__blank-input[type="text"] '
            "{ field-sizing: fixed; width: 8ch; }"
        )
    return ctx, page


def _assert_grows(page):
    blank = page.locator('input[name="blank"]').first
    empty = _metrics(blank)
    # Empty: the 8ch minimum, drawn with the blank's OWN padding -- not app.css's.
    assert empty["padLeft"] == pytest.approx(empty["space2"], abs=0.5), empty
    assert empty["width"] >= empty["eightCh"] - 1, empty

    blank.click()
    blank.press_sequentially(LONG)
    typed = _metrics(blank)
    assert typed["scroll"] <= typed["client"] + 1, f"typed text is clipped: {typed}"
    assert typed["width"] > empty["width"], typed

    # A runaway answer stops at the line instead of widening the page.
    blank.press_sequentially(" " + "x" * 200)
    huge = _metrics(blank)
    assert huge["width"] <= huge["parent"] + 1, huge


@pytest.mark.django_db(transaction=True)
def test_fillgate_blank_grows_with_the_answer(browser, live_server):
    path = _seed("bw_gate", "lesson", _fillgate)
    ctx, page = _open(browser, live_server, "bw_gate", path)
    _assert_grows(page)
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_quiz_fillblank_blank_grows_with_the_answer(browser, live_server):
    # The quiz page loads no question.js, so it proves the fix is not tied to it.
    path = _seed("bw_quiz", "quiz", _fillblank_question)
    ctx, page = _open(browser, live_server, "bw_quiz", path)
    _assert_grows(page)
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_blank_grows_without_field_sizing(browser, live_server):
    path = _seed("bw_fallback", "lesson", _fillgate)
    ctx, page = _open(browser, live_server, "bw_fallback", path, no_field_sizing=True)
    _assert_grows(page)
    ctx.close()
