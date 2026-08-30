"""Produce the images the design pass judges for the tabs panel's left rule.

Not an assertion test -- run it on its own; the assertions live in
tests/test_tabs_css.py.

    uv run pytest tests/capture_tabs_panel_rule_screenshots.py -m e2e

Each theme yields an A/B PAIR plus a short-tab shot. The A/B is what makes the
pair worth looking at: a screenshot taken WITH the rule shows only that something
was drawn, never that it fixed the thing it was added for. The `-off` shot
suppresses the rule in the page, so the two images differ in exactly one
declaration pair and the reviewer can see the boundary appear.

The suppression is done with add_style_tag rather than by reverting the file so
that both halves of the pair come from the SAME build and the same seeded page.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings

from courses.models import TextElement
from tests.factories import add_element
from tests.test_e2e_tabs import _lesson_url
from tests.test_e2e_tabs import _login
from tests.test_e2e_tabs import _make_pa_user
from tests.test_e2e_tabs import _seed_tabs_element
from tests.test_e2e_tabs import _seed_unit

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get(
        "SHOT_DIR", Path(settings.BASE_DIR) / "docs" / "superpowers" / "screenshots"
    )
)

# The exact declarations under test, zeroed. Must stay in step with the rule in
# courses.css -- if the selector there is edited and this is not, the `-off` shot
# silently becomes a duplicate of the `-on` shot and the A/B proves nothing.
RULE_OFF = """
.el--tabs[data-display="tabs"] > .tabs__stage > .tabs__section > .tabs__panel {
  padding-left: 0;
  border-left: 0;
}
"""

TALL = "".join(
    f"<p>{p}</p>"
    for p in (
        "A right triangle has one angle of exactly 90 degrees.",
        "The two sides that meet at the right angle are the legs; the third and "
        "longest side, opposite the right angle, is the hypotenuse.",
        "Pythagoras' theorem relates the three: the square on the hypotenuse "
        "equals the sum of the squares on the two legs.",
        "This holds for every right triangle, and only for right triangles, "
        "which is what makes its converse a usable test.",
    )
)
SHORT = "<p>A triangle with all three sides equal.</p>"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_capture_tabs_panel_rule(page, live_server, theme):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1280, "height": 1000})
    username = f"tabs-rule-shot-{theme}"
    user = _make_pa_user(username)
    user.theme = theme  # the user row, NOT the cookie
    user.save()
    course, unit = _seed_unit(user, f"tabs-rule-shot-{theme}")

    # A paragraph on each side of the tabs: the whole complaint is that a student
    # cannot tell where the tab's content stops and the NEXT element starts, so a
    # shot without a following element cannot show the fix.
    add_element(
        unit,
        TextElement.objects.create(
            body="<p>Read the definitions in each tab before continuing.</p>"
        ),
    )
    _seed_tabs_element(
        unit,
        [("t000001", "Right triangle"), ("t000002", "Equilateral")],
        children={
            "t000001": [TextElement.objects.create(body=TALL)],
            "t000002": [TextElement.objects.create(body=SHORT)],
        },
    )
    add_element(
        unit,
        TextElement.objects.create(
            body="<p>Now apply the theorem to the worked example below.</p>"
        ),
    )

    _login(page, live_server, username)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("[role=tablist]")  # the enhancer ran; not the fallback

    tabs = page.locator(".el--tabs").first
    tabs.screenshot(path=str(OUT_DIR / f"tabs-panel-rule-{theme}-on-tall.png"))

    # Short tab, rule still on: the terminus should move WITH the content, which is
    # the property that turns the reflow into something the student can read.
    page.get_by_role("tab", name="Equilateral").click()
    page.wait_for_selector("[role=tabpanel]:not([hidden])")
    tabs.screenshot(path=str(OUT_DIR / f"tabs-panel-rule-{theme}-on-short.png"))

    # B half of the A/B: same page, same build, rule suppressed.
    page.get_by_role("tab", name="Right triangle").click()
    page.add_style_tag(content=RULE_OFF)
    tabs.screenshot(path=str(OUT_DIR / f"tabs-panel-rule-{theme}-off-tall.png"))
