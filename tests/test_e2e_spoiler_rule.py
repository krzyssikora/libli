"""The revealed region of an element-based spoiler must show ONE continuous left
rule, the same affordance the legacy body-only spoiler has always had.

This is a painted-pixels question, so it is asserted on live geometry rather than on
markup: exactly one box inside the <details> carries a left border, and that box spans
the whole revealed region. Both halves matter --

  * drop the CSS rule and the count goes to 0 (the reported bug);
  * move the border onto each `.spoiler__child` instead and the count goes to 3 with
    boxes that do NOT span the gaps between children (measured: the children's inner
    element margins collapse through, leaving 16px holes in the rule).
"""

import os
import types

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

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


@pytest.fixture
def lesson_with_spoilers(page, live_server):
    """A lesson holding both spoiler shapes: the legacy body-only one (which already
    had the rule) and a three-child element-based one (which did not)."""
    from django.urls import reverse

    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = make_verified_user(
        username="sp_rule", email="sp_rule@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="U")

    body_sp = SpoilerElement.objects.create(label="Body", body="<p>hidden prose</p>")
    Element.objects.create(unit=unit, content_object=body_sp)

    multi = SpoilerElement.objects.create(label="Multi", body="")
    join = Element.objects.create(unit=unit, content_object=multi)
    for i in range(3):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=f"<p>child {i}</p>"),
            parent=join,
            tab_id=SpoilerElement.SLOT_ID,
        )

    EnrollmentFactory(student=student, course=course)
    _login(page, live_server, "sp_rule")
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    return types.SimpleNamespace(url=f"{live_server.url}{path}")


BORDERED = """() => {
    const sp = document.querySelectorAll('details.spoiler')[1];
    // The toggle pill carries its own 1px border -- that is the affordance, not the
    // rule under test, so anything inside <summary> is excluded.
    const all = Array.from(sp.querySelectorAll('*')).filter(n => {
        if (n.closest('summary')) return false;
        const c = getComputedStyle(n);
        return parseFloat(c.borderLeftWidth) > 0 &&
               c.borderLeftStyle !== 'none' &&
               !/transparent|rgba\\(0, 0, 0, 0\\)/.test(c.borderLeftColor);
    });
    const kids = Array.from(sp.querySelectorAll('.spoiler__child'));
    const r = n => n.getBoundingClientRect();
    return {
        count: all.length,
        box: all.length ? {top: Math.round(r(all[0]).top),
                           bottom: Math.round(r(all[0]).bottom),
                           left: Math.round(r(all[0]).left)} : null,
        first: Math.round(r(kids[0]).top),
        last: Math.round(r(kids[kids.length - 1]).bottom),
        childLeft: Math.round(r(kids[0]).left),
    };
}"""


@pytest.mark.django_db(transaction=True)
def test_element_spoiler_shows_one_continuous_rule(
    live_server, page, lesson_with_spoilers
):
    page.goto(lesson_with_spoilers.url)
    page.set_viewport_size({"width": 900, "height": 900})
    page.wait_for_selector("details.spoiler")
    # Real gesture: open the element-based spoiler via its <summary>.
    page.locator("details.spoiler > summary").nth(1).click()

    g = page.evaluate(BORDERED)

    assert g["count"] == 1, (
        f"expected ONE bordered box spanning the revealed region, found {g['count']} "
        "(0 = no rule at all; 3 = a per-child border, which leaves gaps)"
    )
    # It spans the whole region: top of the first child to the bottom of the last.
    assert abs(g["box"]["top"] - g["first"]) <= 1
    assert abs(g["box"]["bottom"] - g["last"]) <= 1
    # And it indents the content, like the legacy body spoiler does.
    assert g["childLeft"] > g["box"]["left"], "children are not indented past the rule"


@pytest.mark.django_db(transaction=True)
def test_legacy_body_spoiler_keeps_its_single_rule(
    live_server, page, lesson_with_spoilers
):
    """The body path must not gain a second border from the new wrapper."""
    page.goto(lesson_with_spoilers.url)
    page.wait_for_selector("details.spoiler")
    page.locator("details.spoiler > summary").nth(0).click()

    count = page.evaluate(
        """() => {
            const sp = document.querySelectorAll('details.spoiler')[0];
            return Array.from(sp.querySelectorAll('*')).filter(n => {
                if (n.closest('summary')) return false;
                const c = getComputedStyle(n);
                return parseFloat(c.borderLeftWidth) > 0 &&
                       c.borderLeftStyle !== 'none' &&
                       !/transparent|rgba\\(0, 0, 0, 0\\)/.test(c.borderLeftColor);
            }).length;
        }"""
    )
    assert count == 1
