"""Produce the images the design pass judges for a link inside an image caption.

Not an assertion test -- run it on its own; the assertions live in
courses/tests/test_caption_render.py and tests/test_e2e_caption_link.py.

    uv run pytest tests/capture_caption_link_screenshots.py -m e2e

Both themes, captured from the same seeded page. The claim under review is that
this feature needs NO new CSS: the dark image plate is painted by courses.css's
`[data-theme="dark"] .el--image img` -- on the <img>, not the <figure>, and
deliberately so, since a figure sized to a long caption would drop themed
caption text onto a light slab. The caption therefore sits on the ordinary page
background, where reset.css's global `a { color: var(--accent) }` already themes
it.

That claim is exactly the kind a single screenshot cannot settle, so each theme
also yields an `-plain` shot with the link's colour forced back to the caption's
own text colour. The pair differs in one declaration, which is what makes the
link visibly distinguishable-or-not rather than merely present.

The theme is set on the User, not through the header toggle or the cookie: an
authed User.theme is what bakes data-theme into the server-rendered <html>.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings

from tests.test_e2e_caption_link import _login
from tests.test_e2e_caption_link import _make_pa_user
from tests.test_e2e_caption_link import _seed

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get(
        "SHOT_DIR", Path(settings.BASE_DIR) / "docs" / "superpowers" / "screenshots"
    )
)

CAPTION = (
    'Pillars of Creation. Photo: <a href="https://example.org/photo">NASA/ESA/CSA</a>, '
    "processed by the Webb ERO team."
)

# The link's own colour, zeroed back to the surrounding caption text. Must stay in
# step with reset.css's bare `a` rule -- if that stops keying on --accent and this
# is not updated, the `-plain` shot silently becomes a duplicate of `-on` and the
# pair proves nothing.
LINK_OFF = "figcaption a { color: inherit; }"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # The autouse fixture in test_e2e_caption_link.py is module-scoped to that
    # file; importing its helpers does not bring it along.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def test_capture(page, live_server):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    from courses.models import Enrollment

    owner = _make_pa_user("shot")
    course, unit, _image, _row = _seed(owner, CAPTION)
    Enrollment.objects.create(student=owner, course=course)
    _login(page, live_server, "shot")

    for theme in ("light", "dark"):
        owner.theme = theme
        owner.save(update_fields=["theme"])
        for leg, css in (("on", None), ("plain", LINK_OFF)):
            page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
            figure = page.locator("figure.el--image")
            figure.wait_for()
            if css:
                page.add_style_tag(content=css)
            figure.screenshot(path=str(OUT_DIR / f"caption-link-{theme}-{leg}.png"))
    print(f"\nwrote 4 shots to {OUT_DIR}")
