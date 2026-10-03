"""Produce the images the design pass judges for the "W skrócie" summary card.

Not an assertion suite -- run it on its own:

    TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_summary \
        uv run pytest tests/capture_summary_callout_screenshots.py -m e2e

Writes summary-callout-*.png under docs/superpowers/screenshots/ (or SHOT_DIR); a
re-run OVERWRITES those committed files. The few asserts are sanity checks that
the page is the one being judged (KaTeX ran in the title; the Example after the
cards reads 2, not 3+; print restates the light bar), not the feature's tests.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings

from courses.models import CalloutElement
from courses.models import Element
from courses.models import ImageElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import make_image_asset
from tests.test_e2e_tabs import _lesson_url
from tests.test_e2e_tabs import _login
from tests.test_e2e_tabs import _make_pa_user
from tests.test_e2e_tabs import _seed_unit

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get(
        "SHOT_DIR", Path(settings.BASE_DIR) / "docs" / "superpowers" / "screenshots"
    )
)

TOPICS = [
    (
        "Funkcja liniowa",
        "<ul><li>Wzór: \\(y = ax + b\\).</li><li>\\(a\\) to współczynnik "
        "kierunkowy, \\(b\\) to wyraz wolny.</li><li>Dla \\(a &gt; 0\\) funkcja "
        "rośnie, dla \\(a &lt; 0\\) maleje.</li></ul>",
    ),
    (
        "Układy równań",
        "<ul><li>Metoda podstawiania.</li><li>Metoda przeciwnych "
        "współczynników.</li><li>Interpretacja: punkt przecięcia "
        "prostych.</li></ul>",
    ),
    (
        "Procenty",
        "<ul><li>\\(p\\%\\) liczby \\(x\\) to \\(\\frac{p}{100}x\\).</li>"
        "<li>Punkt procentowy to różnica procentów.</li></ul>",
    ),
]
WIDE = (
    "<p>Wzór skróconego mnożenia:</p><p>\\[(a+b)^5 = a^5 + 5a^4b + 10a^3b^2 + "
    "10a^2b^3 + 5ab^4 + b^5 \\quad\\text{oraz}\\quad (a-b)^5 = a^5 - 5a^4b + "
    "10a^3b^2 - 10a^2b^3 + 5ab^4 - b^5\\]</p>"
)
HEADINGS_BODY = (
    "<h3>Typed H3 inside the card</h3><p>Compare this with the card title.</p>"
    "<h4>An H4 sub-point</h4><p>It must read as subordinate to the title.</p>"
)


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _card(unit, heading, body="", parent=None, tab_id="", order=0):
    co = CalloutElement.objects.create(kind="summary", heading=heading, body=body)
    return Element.objects.create(
        unit=unit, content_object=co, parent=parent, tab_id=tab_id, order=order
    )


def _seed(course, unit):
    order = 0

    def nxt():
        nonlocal order
        order += 1
        return order

    first = CalloutElement.objects.create(
        kind="example", numbered=True, body="<p>A</p>"
    )
    Element.objects.create(unit=unit, content_object=first, order=nxt())
    for heading, body in TOPICS:  # three cards stacked
        _card(unit, heading, body, order=nxt())
    cols = TwoColumnElement.objects.create(
        data={"columns": [{"id": "c000001"}, {"id": "c000002"}]}
    )
    cols_join = Element.objects.create(unit=unit, content_object=cols, order=nxt())
    powers = "<p>\\(a^m \\cdot a^n = a^{m+n}\\)</p>"
    roots = "<p>\\(\\sqrt{ab} = \\sqrt a \\sqrt b\\)</p>"
    _card(unit, "Potęgi", powers, cols_join, "c000001")
    _card(unit, "Pierwiastki", roots, cols_join, "c000002")
    fig = _card(unit, "Wykres i wzór", WIDE, order=nxt())
    img = ImageElement.objects.create(
        media=make_image_asset(course, "wykres.png", size=(480, 240), color="#88aacc"),
        alt="Wykres funkcji",
    )
    Element.objects.create(
        unit=unit, content_object=img, parent=fig, tab_id=CalloutElement.SLOT_ID
    )
    _card(unit, "Twierdzenie \\(a^2 + b^2 = c^2\\)", "<p>Pitagoras.</p>", order=nxt())
    _card(unit, "Sam nagłówek", "", order=nxt())  # heading-only card
    _card(unit, "Nagłówki w karcie", HEADINGS_BODY, order=nxt())
    after = CalloutElement.objects.create(
        kind="example", numbered=True, body="<p>B</p>"
    )
    Element.objects.create(unit=unit, content_object=after, order=nxt())
    # add_element would use order=0 and sort this FIRST; it must render last.
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>Koniec podsumowania.</p>"),
        order=nxt(),
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_capture_summary_cards(page, browser, live_server, theme):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": 1280, "height": 1000})
    username = f"summary-shot-{theme}"
    user = _make_pa_user(username)
    user.theme = theme  # the user row, NOT the cookie
    user.save()
    course, unit = _seed_unit(user, f"summary-shot-{theme}")
    _seed(course, unit)

    _login(page, live_server, username)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("h3.callout__title .katex")  # math.js typeset the title

    numbers = page.locator(".callout--example .callout__number").all_inner_texts()
    assert numbers == ["1", "2"], f"cards shifted the Example numbers: {numbers}"

    page.screenshot(
        path=str(OUT_DIR / f"summary-callout-{theme}-page.png"), full_page=True
    )
    cards = page.locator(".callout--summary")
    for i, name in enumerate(
        [
            "stack-1",
            "stack-2",
            "stack-3",
            "col-left",
            "col-right",
            "figure-wide",
            "math-heading",
            "heading-only",
            "h3-h4",
        ]
    ):
        # Centre the card first: the sticky Previous/Next bar covers a card that
        # Playwright only scrolls to the viewport's bottom edge.
        cards.nth(i).evaluate("el => el.scrollIntoView({block: 'center'})")
        cards.nth(i).screenshot(
            path=str(OUT_DIR / f"summary-callout-{theme}-{name}.png")
        )
    # The wide formula must scroll INSIDE the card, not clip or widen it.
    widths = cards.nth(5).evaluate(
        "el => { const d = el.querySelector('.katex-display');"
        " return [d.scrollWidth, d.clientWidth, el.scrollWidth, el.clientWidth]; }"
    )
    print(f"{theme} figure-wide [formula sw, cw, card sw, cw]: {widths}")
    page.locator(".el--twocolumn").first.evaluate(
        "el => el.scrollIntoView({block: 'center'})"
    )
    page.locator(".el--twocolumn").first.screenshot(
        path=str(OUT_DIR / f"summary-callout-{theme}-columns.png")
    )

    # Bar corners at zoom: the 3px top border meets the 1px sides on the radius.
    zoom = browser.new_page(
        device_scale_factor=4, viewport={"width": 1280, "height": 1000}
    )
    _login(zoom, live_server, username)
    zoom.goto(_lesson_url(live_server, unit))
    zoom.wait_for_selector(".callout--summary")
    box = zoom.locator(".callout--summary").first.bounding_box()
    for side, x in (("left", box["x"] - 4), ("right", box["x"] + box["width"] - 36)):
        zoom.screenshot(
            path=str(OUT_DIR / f"summary-callout-{theme}-corner-{side}.png"),
            clip={"x": x, "y": box["y"] - 4, "width": 40, "height": 24},
        )
    zoom.close()

    if theme == "dark":
        # Print in the dark theme restates the LIGHT bar colour (#4b6b8a).
        page.emulate_media(media="print")
        colour = page.locator(".callout--summary").first.evaluate(
            "el => getComputedStyle(el).borderTopColor"
        )
        assert colour == "rgb(75, 107, 138)", f"print bar is {colour}"
        cards.first.screenshot(path=str(OUT_DIR / "summary-callout-dark-print.png"))
