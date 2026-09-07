"""Produce the images the design pass judges for the Divider element.

Not an assertion test -- run it on its own; the assertions live in
tests/test_e2e_divider.py and courses/tests/test_divider_element.py.

    uv run pytest tests/capture_divider_screenshots.py -m e2e

Two surfaces, because they use different rules: the EDITOR row (a labelled
"— DIVIDER —" strip sharing .element-row--slidebreak's chrome) and the STUDENT
page (a bare <hr class="el-divider">). Dark is judged on its own, not as "light
but inverted" -- the rule is a --border-default hairline, and a hairline is
exactly where a token that reads fine on white can vanish on near-black.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import DividerElement
from courses.models import Element
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


def _text(body):
    return TextElement.objects.create(body=f"<p>{body}</p>")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_capture_divider(page, live_server, theme):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    username = f"pa-div-{theme}"
    user = _make_pa_user(username)
    user.theme = theme  # NOT the cookie: the editor reads the user row
    user.save()
    unit = _seed_course_and_unit(
        username, slug=f"shot-div-{theme}", unit_title="Divider"
    )
    _login(page, live_server, username)

    # 1. top level: a rule between two blocks of prose.
    add_element(unit, _text("The first idea, stated on its own."))
    add_element(unit, DividerElement.objects.create())
    add_element(unit, _text("The second idea, which the rule sets apart."))

    # 2. the case the element was added for: a rule between a callout's children,
    #    where the container's own padding and left rule are already competing for
    #    the reader's eye.
    callout = CalloutElement.objects.create(
        kind="example",
        heading="Two worked cases",
        body="<p>Both use the same identity.</p>",
    )
    join = add_element(unit, callout)
    for child in (
        _text("Case one: the discriminant is positive."),
        DividerElement.objects.create(),
        _text("Case two: the discriminant is zero."),
    ):
        Element.objects.create(
            unit=unit,
            content_object=child,
            parent=join,
            tab_id=CalloutElement.SLOT_ID,
        )

    page.goto(_editor_url(live_server, unit))
    page.locator(".element-row--divider").first.wait_for(state="visible")
    page.screenshot(path=str(OUT_DIR / f"divider-editor-{theme}.png"), full_page=True)

    lesson = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{lesson}")
    page.locator("hr.el-divider").first.wait_for(state="visible")
    page.screenshot(path=str(OUT_DIR / f"divider-lesson-{theme}.png"), full_page=True)
