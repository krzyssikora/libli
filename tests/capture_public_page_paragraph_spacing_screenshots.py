"""Produce the images the design pass judges for public-page paragraph/heading
spacing (`/privacy/` and `/getting-started/`).

Not an assertion test -- run it on its own; the source-level assertions live in
tests/test_public_page_paragraph_spacing_css.py.

    uv run pytest tests/capture_public_page_paragraph_spacing_screenshots.py -m e2e

reset.css sets `* { margin: 0 }` and app.css never restored a margin for
`.public-page p`, so consecutive paragraphs run together with nothing but
line-height between them, and `.public-page h2` (margin-top only) butts
straight against its first paragraph. A screenshot taken WITH the new rules
shows only that something was drawn, never that it fixed the defect it was
added for -- so each page gets an A/B pair from the SAME build: the "off" shot
suppresses exactly the new declarations via add_style_tag, the "on" shot does
not touch the page at all.

Desktop width (1280px, this app's usual e2e viewport) is used throughout: the
defect is about vertical rhythm within the fixed 46rem `.public-page` column,
which does not reflow with viewport width, so a narrower shot would not show
the spacing any differently -- it would just crop the same column shorter.
Full-page screenshots so multi-paragraph sections and the getting-started
bullet list are both visible in one image.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

pytestmark = pytest.mark.e2e

OUT_DIR = Path(
    os.environ.get(
        "SHOT_DIR", Path(settings.BASE_DIR) / "docs" / "superpowers" / "screenshots"
    )
)

# The exact declarations under test, zeroed back to the reset.css baseline.
# Must stay in step with the rules added to app.css -- if a selector there is
# edited and this is not, the "off" shot silently becomes a duplicate of the
# "on" shot and the A/B proves nothing.
RULES_OFF = """
.public-page p { margin-bottom: 0; }
.public-page h2 { margin-bottom: 0; }
.public-page ul, .public-page ol { margin-bottom: 0; padding-left: 0; }
.public-page li + li { margin-top: 0; }
"""

# Suppresses only the list rules, leaving the paragraph/heading fix in place --
# isolates what the list treatment specifically contributes.
LIST_RULES_OFF = """
.public-page ul, .public-page ol { margin-bottom: 0; padding-left: 0; }
.public-page li + li { margin-top: 0; }
"""

PAGES = ["privacy", "getting_started"]


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("slug", PAGES)
def test_capture_public_page_paragraph_spacing(page, live_server, slug):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1280, "height": 1000})

    url = live_server.url + reverse(f"core:{slug}")
    page.goto(url)
    page.wait_for_selector(".public-page")

    # A half: current build, rules present.
    page.screenshot(
        path=str(OUT_DIR / f"public-page-spacing-{slug}-on.png"), full_page=True
    )

    # getting-started also carries a bulleted list (privacy's lists sit lower
    # on the page); capture the list-rules-off variant there to show what the
    # ul/ol/li treatment specifically contributes, isolated from the
    # paragraph/heading fix.
    if slug == "getting_started":
        page.add_style_tag(content=LIST_RULES_OFF)
        page.screenshot(
            path=str(OUT_DIR / f"public-page-spacing-{slug}-list-rules-off.png"),
            full_page=True,
        )
        page.reload()
        page.wait_for_selector(".public-page")

    # B half of the A/B: same page, same build, all new rules suppressed --
    # the pre-fix state.
    page.add_style_tag(content=RULES_OFF)
    page.screenshot(
        path=str(OUT_DIR / f"public-page-spacing-{slug}-off.png"), full_page=True
    )
