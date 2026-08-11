"""e2e for the seams a render test is byte-identical across.

MANDATORY, not preferred: the server emits no computed style, and a CSS-cascade defect
leaves the rendered HTML unchanged. These four tests are the ONLY pin for the combined
spoiler rule (Task 11), the one-width rule for both callout shapes, the heading katex
reset, and the reveal cascade inside a callout.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD  # noqa: F401 -- used by the copied _login
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_verified_user  # noqa: F401 -- used by _make_pa_user

pytestmark = pytest.mark.e2e

MARKER = "CALLOUT-E2E-9f3a"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# Copied VERBATIM from tests/test_e2e_depth3.py (same PA-user helper, same login form
# drive). They close over TEST_PASSWORD and make_verified_user, which is why both are
# imported above. `_editor_url` is NOT needed here -- every test in this file reads the
# lesson as a student.


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _seed_unit(username):
    user = _make_pa_user(username)
    course = CourseFactory(owner=user)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return user, course, unit


def test_spoiler_body_and_children_show_one_continuous_rule(page, live_server):
    """MUST open the <details> first: a closed one is not rendered, so the rect comes
    back all-zeros and `zero gap` (0-0) holds WITH and WITHOUT the fix -- green under
    the named mutant. On the BROKEN build the gap is non-zero; check that before
    trusting green.

    No left-offset assertion: `.el { margin: 1rem 0 }` already zeroes
    `.spoiler__body`'s margin-left independently of the combined-shape rule, so both
    boxes sit at x=0 with or without the fix -- that comparison cannot fail and would
    read as a second pin while proving nothing.
    """
    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TextElement

    user, _course, unit = _seed_unit("pa_rule")
    sp = SpoilerElement.objects.create(label="Reveal", body="<p>BODY</p>")
    join = add_element(unit, sp)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=f"<p>{MARKER}</p>"),
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    _login(page, live_server, user.username)
    page.goto(_lesson_url(live_server, unit))
    page.eval_on_selector("details.spoiler", "d => { d.open = true; }")
    page.wait_for_selector(".spoiler__body", state="visible")
    page.wait_for_selector(".spoiler__children", state="visible")
    body = page.locator(".spoiler__body").bounding_box()
    kids = page.locator(".spoiler__children").bounding_box()
    gap = kids["y"] - (body["y"] + body["height"])
    assert abs(gap) < 1, f"vertical gap between the two rules: {gap}px"


def test_both_callout_shapes_render_at_one_width(page, live_server):
    """The cap is `html.unit-tree-collapsed [data-unit-shell] ...` under
    `@media screen and (min-width: 641px)`, and that class is set by the TOC-pin JS
    from localStorage -- NEVER by the server. Without seeding it the page renders
    expanded, both arms measure 648px, and the `> 736` half REDDENS -- so the seed
    is what makes this test meaningful, not merely non-vacuous.

    641px is NOT enough either. The collapsed content box is .app-main's 960px cap
    less its 2x20px padding = 920; the -2.4rem shell shift at courses.css:1051
    exactly OFFSETS the 2.4rem pin lane, so .unit-shell__main stays 920; less the
    3rem .lesson padding = 872px at any viewport >= 1040px. At 641px it is far
    smaller, which would put both arms under the 736px cap and make the comparison
    vacuous. Use 1280x900. (.unit-shell's max-width: 72rem never binds: .app-main
    caps the containing block first.)
    """
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import TableElement

    user, _course, unit = _seed_unit("pa_cap")
    prose = CalloutElement.objects.create(kind="note", body="<p>prose only</p>")
    add_element(unit, prose)
    wide = CalloutElement.objects.create(kind="example")
    wide_join = add_element(unit, wide)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "A"}, {"html": "B"}]]}
        ),
        parent=wide_join,
        tab_id=CalloutElement.SLOT_ID,
    )
    page.set_viewport_size({"width": 1280, "height": 900})
    _login(page, live_server, user.username)
    # Seed the collapsed state BEFORE first paint. Grep `unit-tree-collapsed` under
    # courses/static/courses/js/ for the exact localStorage key the TOC pin reads and
    # use it verbatim -- a wrong key silently leaves the page uncollapsed.
    page.add_init_script("localStorage.setItem('libli_unit_tree_collapsed', '1');")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("html.unit-tree-collapsed")
    prose_w = page.locator(".callout:not(:has(> .callout__children))").bounding_box()[
        "width"
    ]
    wide_w = page.locator(".callout:has(> .callout__children)").bounding_box()["width"]
    # BOTH halves are required. Equality alone passes when both callouts are capped
    # at 736 -- the squeezed-table regression this test exists to prevent -- and
    # `> 736` alone passes when they are both uncapped but unequal.
    assert abs(prose_w - wide_w) < 2, (
        f"the two callout shapes must render at one width: prose {prose_w}, "
        f"with-children {wide_w}"
    )
    assert prose_w > 736 and wide_w > 736, (
        f"both callouts must exceed the old 46rem cap: {prose_w}, {wide_w}"
    )


def test_callout_heading_math_is_not_uppercased_or_letter_spaced(page, live_server):
    """Assert what actually CHANGES under the defect. `text-transform` is paint-time
    and never alters textContent, so a textContent assertion is green either way. The
    sample is superscript-free so `.mord` selection is unambiguous (KaTeX emits
    `.mord.mtight` at ~0.7em for a superscript).
    """
    from courses.models import CalloutElement

    user, _course, unit = _seed_unit("pa_head")
    co = CalloutElement.objects.create(
        kind="tip", heading=r"Wzor \(a\cdot b\)", body="<p>x</p>"
    )
    add_element(unit, co)
    _login(page, live_server, user.username)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".callout__heading .katex")
    mord = page.locator(".callout__heading .katex-html .mord").first
    style = mord.evaluate(
        "e => { const c = getComputedStyle(e);"
        " return {t: c.textTransform, l: c.letterSpacing, f: parseFloat(c.fontSize)}; }"
    )
    assert style["t"] == "none", f"heading math is being uppercased: {style['t']}"
    assert style["l"] in ("normal", "0px"), (
        f"heading math is letter-spaced: {style['l']}"
    )
    head_size = page.locator(".callout__heading").evaluate(
        "e => parseFloat(getComputedStyle(e).fontSize)"
    )
    assert abs(style["f"] - head_size) < 1, (
        f"math {style['f']}px vs label {head_size}px -- KaTeX's 1.21em default leaked"
    )


def test_a_gate_in_a_callout_cascades_without_hiding_the_callout(page, live_server):
    """Pre-fix, scopeOf resolved to `.slide` (emitted in EVERY lesson, not just a
    slideshow), so `gateWrap.hidden = true` hid the WHOLE callout and the cascade,
    finding no stopping point, marked every following top-level .lesson-block
    .reveal-shown. Do NOT assert "the button did nothing" -- that is green under the
    defect and RED under the fix.
    """
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import RevealGateElement
    from courses.models import TextElement

    user, _course, unit = _seed_unit("pa_gate")
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=RevealGateElement.objects.create(label="Show more"),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
        order=0,
    )
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=f"<p>{MARKER}</p>"),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
        order=1,
    )
    # A sibling OUTSIDE the callout: the cascade must not sweep it.
    add_element(unit, TextElement.objects.create(body="<p>OUTSIDE-SIBLING</p>"))

    _login(page, live_server, user.username)
    page.goto(_lesson_url(live_server, unit))
    # (a) gated content hidden BEFORE the click -- what the 4th pre-hide selector buys
    assert not page.locator(f"text={MARKER}").is_visible(), (
        "gated content leaked pre-click"
    )
    page.click(".callout__children [data-reveal-gate]")
    page.wait_for_selector(f"text={MARKER}", state="visible")
    # (b) the callout itself survives the cascade
    assert page.locator(".callout").is_visible(), "the callout itself vanished"
    # (c) the cascade did not escape to a top-level sibling
    outside = page.locator(".lesson-block:has-text('OUTSIDE-SIBLING')")
    assert "reveal-shown" not in (outside.get_attribute("class") or ""), (
        "the cascade escaped the callout and swept a top-level sibling"
    )
