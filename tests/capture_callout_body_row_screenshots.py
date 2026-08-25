"""Produce the images the design pass judges for the callout/spoiler body row.

Not an assertion test -- run it on its own; the assertions live in
tests/test_e2e_callout_body_row.py and courses/tests/test_container_body_row.py.

    uv run pytest tests/capture_callout_body_row_screenshots.py -m e2e
"""

import os
from pathlib import Path

import pytest
from django.conf import settings

from courses.models import CalloutElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TextElement
from tests.factories import add_element
from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get(
        "SHOT_DIR", Path(settings.BASE_DIR) / "docs" / "superpowers" / "screenshots"
    )
)


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_capture_body_row(page, live_server, theme):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    username = f"pa-shot-{theme}"
    user = _make_pa_user(username)
    user.theme = theme  # NOT the cookie: <dialog> and the editor read the user row
    user.save()
    unit = _seed_course_and_unit(
        username, slug=f"shot-body-{theme}", unit_title="Body row"
    )
    _login(page, live_server, username)

    # 1. body + children -- the case the editor used to say nothing about.
    callout = CalloutElement.objects.create(
        kind="example",
        heading="Pythagorean theorem",
        body="<p>Consider a right triangle with legs a and b and hypotenuse c.</p>",
    )
    join = add_element(unit, callout)
    for label in ("Diagram of the triangle", "The algebraic statement"):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=f"<p>{label}</p>"),
            parent=join,
            tab_id=CalloutElement.SLOT_ID,
        )

    # 2. body, no children -- the body row plus the pre-existing empty-state hint.
    solo = CalloutElement.objects.create(
        kind="note", body="<p>A note that carries text but nothing nested yet.</p>"
    )
    add_element(unit, solo)

    # 3. the same shape on a spoiler, which shares the template partial.
    spoiler = SpoilerElement.objects.create(
        label="Show the proof", body="<p>Drop a perpendicular from the right angle.</p>"
    )
    sp_join = add_element(unit, spoiler)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>Then compare areas.</p>"),
        parent=sp_join,
        tab_id=SpoilerElement.SLOT_ID,
    )

    # 4. the control: a callout with NO text, which must show no body row at all.
    add_element(unit, CalloutElement.objects.create(kind="tip"))

    page.goto(_editor_url(live_server, unit))
    page.locator(".el-bodyrow").first.wait_for(state="visible")
    page.screenshot(path=str(OUT_DIR / f"callout-body-row-{theme}.png"), full_page=True)

    # The editor pane is its OWN scroller (see the scroll-containment work), so
    # full_page above stops at the pane fold and never reaches the spoiler. Scroll
    # the pane, not the window.
    page.locator(f"[data-element='{sp_join.pk}']").scroll_into_view_if_needed()
    page.screenshot(path=str(OUT_DIR / f"spoiler-body-row-{theme}.png"))
