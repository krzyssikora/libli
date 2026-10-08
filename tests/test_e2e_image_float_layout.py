import pytest

from tests.factories import add_element
from tests.image_float_kit import *

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]
EPS = 1.5


def _seed(slug, *els, unit_type="lesson"):
    owner = make_pa_user(f"pa-{slug}")
    course, unit = seed_unit(owner, slug, unit_type)
    built = [e(course) if callable(e) else e for e in els]
    for el in built:
        add_element(unit, el)
    return owner, unit, built


@pytest.mark.parametrize("vp", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_small_floats_right_and_text_wraps(page, live_server, vp):
    owner, unit, _ = _seed("fl-basic", lambda c: image(c), text(), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), vp)
    # Reference: a TEXT block's body (full column width), never the float's own body.
    col = rect(page, ".lesson-block:not(:has(.el--image--float)) .lesson-block__body")
    img = rect(page, ".el--image--float img")
    line = first_line(page, ".el--text p")
    assert abs(img["right"] - col["right"]) < EPS, (img, col)
    assert line["right"] <= img["left"] + EPS, (line, img)  # wraps beside, not under
    para = rect(page, ".lesson-block:not(:has(.el--image--float)) .el--text p")
    assert abs(img["top"] - para["top"]) < 2 + EPS, (
        img,
        para,
    )  # top-aligned (box, not glyphs)
    second = page.locator(".lesson-block:not(:has(.el--image--float)) .el--text p").nth(
        1
    )
    s2 = second.evaluate(
        "p => { const r = document.createRange(); r.selectNodeContents(p);"
        " return r.getClientRects()[0].toJSON(); }"
    )
    if s2["top"] < img["bottom"]:  # starts beside the image -> must wrap too (D3)
        assert s2["right"] <= img["left"] + EPS, (s2, img)


def test_two_text_elements_both_wrap_in_a_quiz(page, live_server):
    owner, unit, _ = _seed(
        "fl-quiz", lambda c: image(c, px=(300, 600)), text(), text(), unit_type="quiz"
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    img = rect(page, ".el--image--float img")
    lines = page.evaluate(
        """() => [...document.querySelectorAll('.quiz .el--text p')].map(p => {
             const r = document.createRange(); r.selectNodeContents(p);
             return r.getClientRects()[0].toJSON(); })"""
    )
    assert all(
        ln["right"] <= img["left"] + EPS for ln in lines if ln["top"] < img["bottom"]
    )
    assert lines[1]["top"] < img["bottom"], (
        "2nd paragraph should start beside the image"
    )


def test_non_text_after_float_starts_below(page, live_server):
    from courses.models import SpoilerElement

    owner, unit, _ = _seed(
        "fl-clear",
        lambda c: image(c, px=(300, 600)),
        text("Krótko."),
        SpoilerElement.objects.create(label="rozwiązanie"),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    img = rect(page, ".el--image--float img")
    assert rect(page, ".spoiler")["top"] >= img["bottom"] - EPS


def test_mid_body_heading_drops_but_its_paragraph_wraps(page, live_server):
    from courses.models import TextElement

    owner, unit, _ = _seed(
        "fl-h3",
        lambda c: image(c, px=(300, 600)),
        TextElement.objects.create(body=f"<p>{PARA}</p><h3>Nagłówek</h3>"),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    img = rect(page, ".el--image--float img")
    assert first_line(page, ".el--text p")["right"] <= img["left"] + EPS
    assert rect(page, ".el--text h3")["top"] >= img["bottom"] - EPS


def test_two_floats_stack(page, live_server):
    owner, unit, _ = _seed("fl-two", lambda c: image(c), lambda c: image(c), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    a, b = page.locator(".el--image--float img").evaluate_all(
        "els => els.map(e => e.getBoundingClientRect().toJSON())"
    )
    assert b["top"] >= a["bottom"] - EPS


def test_float_as_first_element(page, live_server):
    owner, unit, _ = _seed("fl-first", lambda c: image(c), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), PHONE)
    img = rect(page, ".el--image--float img")
    assert first_line(page, ".el--text p")["right"] <= img["left"] + EPS


def test_float_ending_a_slide_stays_in_it_without_js(browser, live_server):
    # .unit-shell__main is a flex column, so article.lesson (a flex item) already
    # contains floats before .unit-foot -- a footer test cannot fail. What the
    # .slide::after guards is a float ending slide 1 when slides STACK: no JS.
    from courses.models import SlideBreakElement

    owner, unit, _ = _seed(
        "fl-slides",
        text("Krótko."),
        lambda c: image(c, px=(300, 900)),
        SlideBreakElement.objects.create(),
        text("Druga strona."),
    )
    ctx = browser.new_context(java_script_enabled=False)
    try:
        page = ctx.new_page()
        login(page, live_server, owner.username)
        open_page(page, unit_url(live_server, unit), DESKTOP)
        img = rect(page, ".el--image--float img")
        # NOT .slide:nth-of-type(2): div.lesson-unit__head precedes the slides and
        # :nth-of-type counts every div, so that would be slide ONE.
        nxt = rect(page, ".slide ~ .slide .el--text p")
        assert nxt["top"] >= img["bottom"] - EPS, (nxt, img)
    finally:
        ctx.close()


def test_float_ending_a_deck_slide_stays_in_it_in_print(page, live_server):
    # Print makes deck slides position:static; overflow:visible -- no longer BFCs.
    from courses.models import SlideBreakElement

    owner, unit, _ = _seed(
        "fl-deck-print",
        text("Krótko."),
        lambda c: image(c, px=(300, 900)),
        SlideBreakElement.objects.create(),
        text("Druga strona."),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    page.wait_for_selector(".slideshow-deck")
    print_mode(page)
    img = rect(page, ".el--image--float img")
    nxt = rect(page, ".slide ~ .slide .el--text p")
    assert nxt["top"] >= img["bottom"] - EPS, (nxt, img)


def test_preview_contains_a_float_and_a_slide_break_clears_it(page, live_server):
    from courses.models import SlideBreakElement

    owner, unit, _ = _seed(
        "fl-prev",
        lambda c: image(c, px=(300, 900)),
        SlideBreakElement.objects.create(),
        text("Po przerwie."),
        text("Krótko."),
        lambda c: image(c, px=(300, 900)),  # LAST preview element
    )
    login(page, live_server, owner.username)
    page.set_viewport_size(DESKTOP)
    page.goto(editor_url(live_server, unit))
    page.wait_for_selector(".prev-inner .el--image--float img")
    assert page.evaluate(WAIT_IMAGES)
    imgs = page.locator(".prev-inner .el--image--float img").evaluate_all(
        "els => els.map(e => e.getBoundingClientRect().toJSON())"
    )
    brk = rect(page, ".prev-inner section.prev-el:nth-of-type(2)")
    assert brk["top"] >= imgs[0]["bottom"] - EPS, (brk, imgs[0])
    inner = rect(page, ".prev-inner")
    assert inner["bottom"] >= imgs[-1]["bottom"] - EPS, (inner, imgs[-1])


def test_maths_beside_float_does_not_scroll_the_page(page, live_server):
    from courses.models import MathElement

    owner, unit, _ = _seed(
        "fl-math",
        lambda c: image(c, px=(300, 600)),
        MathElement.objects.create(latex="x^2+y^2=r^2"),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), PHONE)
    page.wait_for_selector(".el--math .katex")
    img = rect(page, ".el--image--float img")
    assert rect(page, ".el--math .katex-html")["right"] <= img["left"] + EPS
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_float_before_reveal_gate(page, live_server):
    from courses.models import RevealGateElement

    owner, unit, _ = _seed(
        "fl-gate",
        lambda c: image(c, px=(300, 600)),
        text("Krótko."),
        RevealGateElement.objects.create(),
        text(),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    page.locator("[data-reveal-gate]").wait_for(
        state="visible"
    )  # reveal.js un-hides it
    img = rect(page, ".el--image--float img")
    gate = rect(page, "[data-reveal-gate]")
    assert gate["width"] > 0 and gate["height"] > 0, "gate never rendered; vacuous"
    # D3: a non-text block starts BELOW the float. (Not "or beside it": .reveal-gate is
    # display:flex, a BFC, so without the clear it would sit beside the image and an
    # either-or assertion could never fail.)
    assert gate["top"] >= img["bottom"] - EPS, (gate, img)


@pytest.mark.parametrize("vp", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_clicking_the_floated_image_opens_zoom(page, live_server, vp):
    owner, unit, _ = _seed("fl-zoom", lambda c: image(c), text(), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), vp)
    img = rect(page, ".el--image--float img")
    # Click a point a LATER block's box covers -- else the click lands in a margin gap
    # no positioned block covers, and removing the rail z-index cannot turn this RED.
    x = img["left"] + img["width"] / 2
    y = rect(page, ".lesson-block:not(:has(.el--image--float)) .el--text p")["top"] + 4
    assert img["top"] < y < img["bottom"], (
        "fixture: the paragraph must start beside the image"
    )
    covered = page.evaluate(
        """([x, y]) => [...document.querySelectorAll('.lesson-block')]
             .filter(b => !b.querySelector('.el--image--float'))
             .some(b => { const r = b.getBoundingClientRect();
                          return x >= r.left && x <= r.right
                              && y >= r.top && y <= r.bottom; })""",
        [x, y],
    )
    assert covered, "fixture: a later block must cover the click point"
    page.mouse.click(x, y)
    page.wait_for_selector("dialog.imgzoom[open]", timeout=3000)


def test_narrow_and_captioned_images_hug_the_right_edge(page, live_server):
    owner, unit, _ = _seed(
        "fl-narrow",
        # >= 80px: the in-flow notes handle is ~25-50px
        lambda c: image(c, px=(90, 90)),
        text(),
        lambda c: image(
            c, px=(90, 90), caption="Bardzo długi podpis pod małym obrazkiem"
        ),
        text(),
    )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    col = rect(page, ".lesson-block:not(:has(.el--image--float)) .lesson-block__body")
    for img in page.locator(".el--image--float img").evaluate_all(
        "els => els.map(e => e.getBoundingClientRect().toJSON())"
    ):
        assert abs(img["right"] - col["right"]) < EPS, (img, col)


def test_height_capped_portrait_leaves_no_gap(page, live_server):
    owner, unit, _ = _seed("fl-tall", lambda c: image(c, px=(400, 800)), text())
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), {"width": 1300, "height": 700})
    im = page.locator(".el--image--float img")
    h, cap = im.evaluate(
        "e => [e.getBoundingClientRect().height,"
        " parseFloat(getComputedStyle(e).maxHeight)]"
    )
    assert abs(h - cap) < EPS, "fixture must be height-capped or the test is vacuous"
    img = rect(page, ".el--image--float img")
    # The float box must shrink-wrap the height-capped image: its left edge IS the
    # image's. (Not the text's line end: lesson text is ragged-right, so a Range rect
    # ends at the last glyph, up to a word short of the line box.)
    wrapper = rect(page, ".lesson-block:has(.el--image--float)")
    assert abs(wrapper["left"] - img["left"]) < EPS, (wrapper, img)
    assert first_line(page, ".el--text p")["right"] <= img["left"] + EPS
