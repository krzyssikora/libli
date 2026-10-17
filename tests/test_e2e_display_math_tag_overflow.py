"""A numbered display's equation numbers must not cover an overflowing formula.

THE DEFECT. The vendored `katex.min.css` positions `.katex-html > .tag` with
`position: absolute; right: 0` against `.katex-html`, a block as wide as the
COLUMN, not the formula. Since #292 a too-wide display scrolls -- prose
`.katex-display` is its own scroller, a math element scrolls on `.el--math` --
and the tag scrolls with the content, but its x was fixed by the column width.
At scroll 0 it sits on the formula's middle; scrolled to the end it has moved
left onto the formula again. Nowhere in the scroll range is it clear of ink.

THE FIX (courses.css) lays a tagged `.katex-html` out as a flex row with two
equal-weight spacers -- a `::before` and the now in-flow `.tag` -- so a fitting
formula stays exactly centred with its number flush right, while an
overflowing one is followed by its number, 1em clear, at the end of the scroll
range.

Every behavioural assertion is an A/B against the SAME page with the new rules
deleted through CSSOM (`_vendor_leg`), never a hand-written override that would
have to restore each property at the right specificity.

"Ink" is the union of the tag's leaf elements, never `.tag`'s own box (under
the fix that box is a flex-grow spacer). `.strut`/`.pstrut`/`.vlist-s` are
excluded: a `\\tag{}`'s first child is a zero-width full-height strut, and the
`.vlist-t` box overshoots the number by 2px. Auto-numbers are CSS-counter
`::before` content with no text node, so a leaf-element union -- `.eqn-num` is
the leaf -- is the only measure that sees them.

FIXTURE SIZES, MEASURED on master (C = `.katex-html` width, F = base union
width, n = tag ink width, em = font-size of the tag's first child):
identical on both surfaces (a 326px column at 390, 648px at 1280; em 19.36px).
  wide        F 544.0, n 24.8: overflows the 390 column by 218px.
  fit_mixed   F 58.9,  n 34.4: (C-F)/2 = 133.6 at 390, 294.6 at 1280,
              against n + em + 20 = 73.8.
  multi_base  F 85.6,  n 24.8: (C-F)/2 = 120.2 at 390, 281.2 at 1280,
              against 64.2.
  near        F 236.0, n 54.9: C-F = 90.0 inside the window
              [n + em + 4, 2n - 8) = [78.3, 101.8). Only an \\hspace of 80px
              (in 10px steps) lands in it -- the window is narrow by nature.

Marked e2e (excluded from the default run; use -m e2e)."""

import os

import pytest
from django.urls import reverse

from courses.models import FillTableElement
from courses.models import MathElement
from courses.models import TableElement
from courses.models import TextElement
from tests.factories import add_element
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

# The owner's case: a stepwise derivation whose rows are far wider than a phone.
WIDE = (
    r"\begin{align}|P(A)P(B)| &= \sqrt{((2-y_A)-(2-y_B))^2+((x_A+1)-(x_B+1))^2}"
    r"\\ &= \sqrt{(-y_A+y_B)^2+(x_A-x_B)^2}\\ &= |AB|\end{align}"
)
# Eleven rows, so (9) sits above (10): mixed-width numbers whose alignment
# AGAINST EACH OTHER the `.tag > *` rule exists to keep.
FIT_MIXED = (
    r"\begin{align}"
    + r"\\".join(r"a_{" + str(i) + "}&=b" for i in range(1, 12))
    + r"\end{align}"
)
# Several `.base` runs of clearly different height (the fraction), so dropping
# `align-items: baseline` has something to move.
MULTI_BASE = r"x = \frac{a}{b} + y \tag{3}"
# A LONG tag: vendor overlap needs (C - F)/2 < n while the fix needs
# C - F >= n + 1em, which no short number can satisfy. Padded into the measured
# window; both surfaces share the column today, so the
# two constants are equal -- re-tune them apart if the columns ever diverge.
NEAR_FIT_PROSE = r"\hspace{80px} x = y + z \tag{1.2.3}"
NEAR_FIT_MATH = r"\hspace{80px} x = y + z \tag{1.2.3}"

FIXTURES = {"wide": WIDE, "fit_mixed": FIT_MIXED, "multi_base": MULTI_BASE}

DISP = {"prose": ".el--text .katex-display", "math": ".el--math .katex-display"}
SCROLLER = {"prose": ".el--text .katex-display", "math": ".el--math"}

TOL = 0.5


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """live_server + the ORM in the test body, under pytest-playwright's session
    loop. Same shape and name as the fixture in test_e2e_math_reflow.py."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _latex(fixture, surface):
    if fixture == "near":
        return NEAR_FIT_PROSE if surface == "prose" else NEAR_FIT_MATH
    return FIXTURES[fixture]


def _element(fixture, surface):
    latex = _latex(fixture, surface)
    if surface == "prose":
        return TextElement.objects.create(body=r"<p>\[" + latex + r"\]</p>")
    return MathElement.objects.create(latex=latex)


def _open(page, live_server, username, slug, element, *, tagged=True):
    _make_pa_user(username)
    _login(page, live_server, username)
    unit = _seed_course_and_unit(username, slug=slug)
    add_element(unit, element)
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{path}")
    page.wait_for_selector(".katex-html > .base")
    if tagged:
        page.wait_for_selector(".katex-html > .tag")
    page.evaluate("document.fonts.ready.then(() => true)")
    assert page.evaluate("document.fonts.check('1em KaTeX_Main')")


_MEASURE_JS = """([dispSel, scrSel]) => {
  const disp = document.querySelector(dispSel);
  const html = disp.querySelector(':scope > .katex > .katex-html');
  const tag = html.querySelector(':scope > .tag');
  const scr = document.querySelector(scrSel);
  const R = (r) => ({left: r.left, right: r.right, top: r.top, bottom: r.bottom});
  const union = (rs) => ({
    left: Math.min(...rs.map((r) => r.left)),
    right: Math.max(...rs.map((r) => r.right)),
    top: Math.min(...rs.map((r) => r.top)),
    bottom: Math.max(...rs.map((r) => r.bottom)),
  });
  const bases = [...html.querySelectorAll(':scope > .base')]
    .map((b) => R(b.getBoundingClientRect()));
  const leaves = [...tag.querySelectorAll('*')]
    .filter((e) => !e.firstElementChild && !e.matches('.strut, .pstrut, .vlist-s')
                   && e.getBoundingClientRect().width > 0)
    .map((e) => R(e.getBoundingClientRect()));
  const sr = scr.getBoundingClientRect();
  const left = sr.left + scr.clientLeft, top = sr.top + scr.clientTop;
  return {
    bases, base_union: union(bases), leaves, ink: union(leaves),
    html: R(html.getBoundingClientRect()),
    scroller: {
      left, right: left + scr.clientWidth, top, bottom: top + scr.clientHeight,
    },
    em: parseFloat(getComputedStyle(tag.firstElementChild).fontSize),
    scroll_max: scr.scrollWidth - scr.clientWidth,
    scroll_width: scr.scrollWidth, client_width: scr.clientWidth,
  };
}"""


def _measure(page, surface):
    return page.evaluate(_MEASURE_JS, [DISP[surface], SCROLLER[surface]])


def _scroll_to(page, surface, x):
    page.evaluate(
        "([sel, x]) => { document.querySelector(sel).scrollLeft = x; }",
        [SCROLLER[surface], x],
    )


def _scroll_to_end(page, surface):
    page.evaluate(
        "(sel) => { const s = document.querySelector(sel);"
        " s.scrollLeft = s.scrollWidth; }",
        SCROLLER[surface],
    )


def _strip_new_rules(page):
    """Delete every rule of the fix -- the five main rules and both opt-outs,
    all of which carry `:has(> .tag)` -- leaving exactly the vendor cascade."""
    return page.evaluate(
        """() => {
             let n = 0;
             const walk = (list, owner) => {
               for (let i = list.length - 1; i >= 0; i--) {
                 const r = list[i];
                 if (r.cssRules && !r.selectorText) { walk(r.cssRules, r); continue; }
                 if (r.selectorText && r.selectorText.includes(':has(> .tag)')) {
                   owner.deleteRule(i); n++;
                 }
               }
             };
             for (const sheet of document.styleSheets) {
               let rules;
               try { rules = sheet.cssRules; } catch (e) { continue; }
               walk(rules, sheet);
             }
             return n;
           }"""
    )


def _vendor_leg(page, surface):
    assert _strip_new_rules(page) == 13
    tag = f"{DISP[surface]} > .katex > .katex-html > .tag"
    assert (
        page.evaluate(
            "(s) => getComputedStyle(document.querySelector(s)).position", tag
        )
        == "absolute"
    )
    assert (
        page.evaluate(
            "(s) => getComputedStyle(document.querySelector(s).firstElementChild)"
            ".marginInlineStart",
            tag,
        )
        == "0px"
    )


def _clear(m):
    """The fix's claim: the number starts at least 1em right of the formula."""
    return m["ink"]["left"] >= m["base_union"]["right"] + m["em"] - TOL


def _same(a, b):
    return all(abs(a[k] - b[k]) <= TOL for k in ("left", "right", "top", "bottom"))


def _phone(page):
    page.set_viewport_size({"width": 390, "height": 900})


@pytest.mark.parametrize("surface", ["prose", "math"])
@pytest.mark.parametrize("fixture", ["wide", "near"])
def test_tag_clears_formula_at_scroll_start(page, live_server, surface, fixture):
    """Assertion 1. On vendor the tag sits on the formula (RED leg)."""
    _phone(page)
    _open(
        page,
        live_server,
        f"tagovf1_{surface}_{fixture}",
        f"tagovf1-{surface}-{fixture}",
        _element(fixture, surface),
    )
    new = _measure(page, surface)
    assert _clear(new), new
    _vendor_leg(page, surface)
    old = _measure(page, surface)
    assert not _clear(old), "fixture does not reproduce the defect on vendor"


@pytest.mark.parametrize("surface", ["prose", "math"])
def test_tag_reachable_and_clear_at_scroll_end(page, live_server, surface):
    """Assertion 2. Scrolled to the end, the number is on screen and clear."""
    _phone(page)
    _open(
        page,
        live_server,
        f"tagovf2_{surface}",
        f"tagovf2-{surface}",
        _element("wide", surface),
    )
    _scroll_to_end(page, surface)
    new = _measure(page, surface)
    assert new["ink"]["left"] >= new["scroller"]["left"] - TOL, new
    assert new["ink"]["right"] <= new["scroller"]["right"] + TOL, new
    assert _clear(new), new
    _vendor_leg(page, surface)
    _scroll_to_end(page, surface)  # stripping changed scrollWidth
    old = _measure(page, surface)
    assert not _clear(old), "vendor tag should have scrolled back onto the formula"


@pytest.mark.parametrize("surface", ["prose", "math"])
@pytest.mark.parametrize("fixture", ["fit_mixed", "multi_base"])
def test_fitting_display_matches_vendor(page, live_server, surface, fixture):
    """Assertion 3, a regression guard: a display that fits keeps the vendor
    geometry -- every base run, the ink, and every ink leaf, at both widths."""
    _phone(page)
    _open(
        page,
        live_server,
        f"tagovf3_{surface}_{fixture}",
        f"tagovf3-{surface}-{fixture}",
        _element(fixture, surface),
    )
    if fixture == "fit_mixed":
        assert page.locator(".katex-html > .tag .eqn-num").count() == 11
    widths = (390, 1280)
    new = {}
    for w in widths:
        page.set_viewport_size({"width": w, "height": 900})
        new[w] = _measure(page, surface)
    _vendor_leg(page, surface)
    for w in reversed(widths):
        page.set_viewport_size({"width": w, "height": 900})
        old = _measure(page, surface)
        assert len(new[w]["bases"]) == len(old["bases"])
        for a, b in zip(new[w]["bases"], old["bases"], strict=True):
            assert _same(a, b), (w, a, b)
        assert _same(new[w]["ink"], old["ink"]), (w, new[w]["ink"], old["ink"])
        assert len(new[w]["leaves"]) == len(old["leaves"])
        for a, b in zip(new[w]["leaves"], old["leaves"], strict=True):
            assert _same(a, b), (w, a, b)


@pytest.mark.parametrize("surface", ["prose", "math"])
@pytest.mark.parametrize("fixture", ["fit_mixed", "multi_base", "wide", "near"])
def test_numbers_level_with_rows(page, live_server, surface, fixture):
    """Assertion 4, a regression guard: the number keeps its vertical place
    against the display, as vendor laid it out."""
    _phone(page)
    _open(
        page,
        live_server,
        f"tagovf4_{surface}_{fixture}",
        f"tagovf4-{surface}-{fixture}",
        _element(fixture, surface),
    )
    new = _measure(page, surface)
    _vendor_leg(page, surface)
    old = _measure(page, surface)
    for m in (new, old):
        m["dt"] = m["ink"]["top"] - m["html"]["top"]
        m["db"] = m["ink"]["bottom"] - m["html"]["bottom"]
    assert abs(new["dt"] - old["dt"]) <= TOL, (new["dt"], old["dt"])
    assert abs(new["db"] - old["db"]) <= TOL, (new["db"], old["db"])


@pytest.mark.parametrize("surface", ["prose", "math"])
def test_near_fit_does_not_overflow(page, live_server, surface):
    """Assertion 5, a regression guard: near-fit moves left rather than spill."""
    _phone(page)
    _open(
        page,
        live_server,
        f"tagovf5_{surface}",
        f"tagovf5-{surface}",
        _element("near", surface),
    )
    m = _measure(page, surface)
    assert m["scroll_width"] <= m["client_width"] + 1, m


@pytest.mark.parametrize("widget", ["table", "filltable"])
def test_table_widgets_keep_vendor_tag(page, live_server, widget):
    """Assertion 6, drift guards for the opt-outs: a table cell's display maths
    inherits the cell's alignment, which a centring spacer would override."""
    html = r"\[" + FIT_MIXED + r"\]"
    if widget == "table":
        el = TableElement(data={"cells": [[{"html": html, "halign": "left"}]]})
    else:
        el = FillTableElement(
            data={
                "cells": [
                    [
                        {"kind": "static", "html": html, "halign": "left"},
                        {"kind": "answer", "answer": "1"},
                    ]
                ]
            }
        )
    el.save()
    _open(page, live_server, f"tagovf6_{widget}", f"tagovf6-{widget}", el)
    got = page.evaluate(
        """() => {
             const html = document.querySelector('.katex-html:has(> .tag)');
             const tag = html.querySelector(':scope > .tag');
             const first = tag.firstElementChild;
             const cs = (e) => getComputedStyle(e);
             return {
               display: cs(html).display, position: cs(tag).position,
               tagAlign: cs(tag).textAlign,
               parentAlign: cs(tag.parentElement).textAlign,
               firstMargin: cs(first).marginInlineStart,
               firstAlign: cs(first).textAlign,
               htmlAlign: cs(html).textAlign,
             };
           }"""
    )
    assert got["display"] == "block", got
    assert got["position"] == "absolute", got
    assert got["tagAlign"] == got["parentAlign"], got
    assert got["firstMargin"] == "0px", got
    assert got["firstAlign"] == got["htmlAlign"], got
    assert got["htmlAlign"] != "center", "cell is ta-left; the fixture proves nothing"


def test_untagged_display_untouched(page, live_server):
    body = r"<p>\[\begin{align*} a&=b\\ c&=d \end{align*}\]</p>"
    _open(
        page,
        live_server,
        "tagovf_untagged",
        "tagovf-untagged",
        TextElement.objects.create(body=body),
        tagged=False,
    )
    display = page.evaluate(
        "() => getComputedStyle("
        "document.querySelector('.el--text .katex-html')).display"
    )
    assert display == "block"


@pytest.mark.parametrize("surface", ["prose", "math"])
def test_page_does_not_widen(page, live_server, surface):
    """Assertion 7, the #292 invariant re-pinned for the flex overflow."""
    _phone(page)
    _open(
        page,
        live_server,
        f"tagovf7_{surface}",
        f"tagovf7-{surface}",
        _element("wide", surface),
    )
    sw, cw = page.evaluate(
        "() => [document.documentElement.scrollWidth,"
        " document.documentElement.clientWidth]"
    )
    assert sw == cw
