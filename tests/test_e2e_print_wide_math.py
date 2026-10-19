"""Printing a lesson shrinks a display formula wider than the printed column.

THE DEFECT. KaTeX cannot line-break a display and paper cannot scroll, so a
display wider than the printed column was clipped at the column edge -- the
equation numbers first, since #390 lays them out after the formula.

THE FIX. print.js (beforeprint) flags every display in block flow with its
natural width in em and its containers' horizontal inset; the print CSS sets
its `.katex-html` to `min(1em, (100vw - inset - 2px) / width-in-em)`.
In print `vw` is the printed content width. A display that fits keeps 1em and
prints exactly as before. NOT a container query: style containment scoped
KaTeX's equation counter per display, and (4)(5)(6) printed as (1)(1)(1).

HOW IT IS MEASURED. A real `page.pdf()` straight from the screen layout -- the
only route that showed #380's clip (`emulate_media` + resize hid it).

Geometry: Chromium writes a link annotation (`/Rect`, `/URI`) for every
`<a href>` it paints and DROPS the annotation of one clipped out of view, so
tiny probe links mark:
  L / R  the formula's first and last 4px (inside the first / last `.base`,
         with a negative margin so they add no width),
  T      the last 4px of the equation numbers (inside `.tag`),
  W      the column itself (a full-width block at the top of the element).
A probe missing from the PDF was clipped (Windows Chromium drops it; Linux
Chromium trims its rect to the clip, so every probe must also keep its full
width); a present one is checked against W.
The PDF is A4 at scale 1, so 1 CSS px = 0.75pt.

Numbering: `_pdf_text` reads the PDF's text back through each font's
ToUnicode CMap (Chromium embeds one per font; no PDF library is installed).
Clipped glyphs are not written, so the number sequence also fails on master.

Marked e2e (excluded from the default run; use -m e2e)."""

import os
import re
import zlib

import pytest
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import Element
from courses.models import MathElement
from courses.models import SlideBreakElement
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import add_element
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

# #390's owner case, widened past the printed column (~980px at 1em): the
# auto-numbered rows put their numbers after the widest line.
WIDE_TAGGED = (
    r"\begin{align}|P(A)P(B)| &= \sqrt{((2-y_A)-(2-y_B))^2+((x_A+1)-(x_B+1))^2}"
    r" = \sqrt{((2-y_A)-(2-y_B))^2+((x_A+1)-(x_B+1))^2}"
    r"\\ &= \sqrt{(-y_A+y_B)^2+(x_A-x_B)^2}\\ &= |AB|\end{align}"
)
# No number at all, just over the printed column (A4 at 10pt: 680px, ~42em).
WIDE_PLAIN = (
    r"\sum_{k=1}^{n} \left(a_k + b_k\right)^2 = \sum_{k=1}^{n} a_k^2"
    r" + 2\sum_{k=1}^{n} a_k b_k + \sum_{k=1}^{n} b_k^2"
    r" = \sum_{k=1}^{n} a_k^2 + 2\sum_{k=1}^{n} a_k b_k + \sum_{k=1}^{n} b_k^2"
    r" + 2\sum_{k=1}^{n} a_k b_k + \sum_{k=1}^{n} b_k^2"
)
# A letter tag, so it never joins the (n) auto-number sequence.
FIT_TAGGED = r"x = \frac{a}{b} + y \tag{A}"
FIT_PLAIN = r"a^2 + b^2 = c^2"

# (name, surface, latex, wide?, tagged?) in page order. The auto-numbered
# displays run (1)-(3), (4)-(6), (7)-(9), (10)-(12). A slide break after the
# first seven makes the lesson a slideshow deck, so slide 1 carries the deck
# slide's padding; the last display sits in the CLOSED second tab of a tabs
# element on the HIDDEN second slide -- unrendered on screen, printed on paper.
DISPLAYS = [
    ("wide_tagged_prose", "prose", WIDE_TAGGED, True, True),
    ("wide_tagged_math", "math", WIDE_TAGGED, True, True),
    ("wide_plain_prose", "prose", WIDE_PLAIN, True, False),
    ("wide_plain_math", "math", WIDE_PLAIN, True, False),
    ("wide_tagged_callout", "callout", WIDE_TAGGED, True, True),
    ("fit_tagged_math", "math", FIT_TAGGED, False, True),
    ("fit_plain_prose", "prose", FIT_PLAIN, False, False),
    ("wide_tagged_hidden_tab", "hidden_tab", WIDE_TAGGED, True, True),
]
NUMBERS = [str(n) for n in range(1, 13)]

PT = 0.75  # pt per CSS px at scale 1
# Paper prints at 10pt against the screen's 16px (app.css), so a display that
# fits prints at 10/12 of its screen size, not 1.
PRINT_SCALE = 10 / 12
TOL = 0.75  # pt


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


_PROBE_JS = """() => {
  const out = [];
  document.querySelectorAll('[data-element-id] .katex-display').forEach((disp, i) => {
    const html = disp.querySelector(':scope > .katex > .katex-html');
    const bases = html.querySelectorAll(':scope > .base');
    const mk = (kind, css) => {
      const a = document.createElement('a');
      a.href = `https://probe.invalid/d${i}-${kind}`;
      a.style.cssText = css;
      return a;
    };
    const box = 'display:inline-block;width:4px;height:4px;vertical-align:top;';
    const l = mk('L', box + 'margin-right:-4px');
    bases[0].prepend(l);
    const r = mk('R', box + 'margin-left:-4px');
    bases[bases.length - 1].append(r);
    const tag = html.querySelector(':scope > .tag');
    if (tag) tag.append(mk('T', box + 'margin-left:-4px'));
    disp.closest('.el').prepend(mk('W', 'display:block;height:2px'));
    out.push({
      L: l.getBoundingClientRect().left, R: r.getBoundingClientRect().left,
      font: getComputedStyle(html).fontSize,
    });
  });
  return out;
}"""


def _objects(pdf):
    """obj number -> (dictionary bytes, decoded stream bytes or None)."""
    objs = {}
    for m in re.finditer(rb"(\d+) 0 obj(.*?)endobj", pdf, re.S):
        body = m.group(2)
        sm = re.search(rb"stream\r?\n(.*?)\r?\nendstream", body, re.S)
        if not sm:
            objs[int(m.group(1))] = (body, None)
            continue
        data = sm.group(1)
        if b"/FlateDecode" in body[: sm.start()]:
            data = zlib.decompress(data)
        objs[int(m.group(1))] = (body[: sm.start()], data)
    return objs


def _annotations(objs):
    """URI -> (x0, x1) of every probe link."""
    found = {}
    for d, _ in objs.values():
        uri = re.search(rb"https://probe\.invalid/(d\d+-[LRTW])", d)
        rect = re.search(rb"/Rect\s*\[\s*([-\d. ]+)\]", d)
        if uri and rect:
            x0, _, x1, _ = (float(v) for v in rect.group(1).split())
            found[uri.group(1).decode()] = (x0, x1)
    return found


def _cmap(data):
    txt = data.decode("latin-1")
    out = {}
    for blk in re.findall(r"beginbfchar(.*?)endbfchar", txt, re.S):
        for a, b in re.findall(r"<(\w+)>\s*<(\w+)>", blk):
            out[int(a, 16)] = bytes.fromhex(b).decode("utf-16-be")
    for blk in re.findall(r"beginbfrange(.*?)endbfrange", txt, re.S):
        for a, b, c in re.findall(r"<(\w+)>\s*<(\w+)>\s*<(\w+)>", blk):
            for i, code in enumerate(range(int(a, 16), int(b, 16) + 1)):
                out[code] = chr(int(c, 16) + i)
    return out


def _pdf_text(objs):
    """The text Chromium drew, in content-stream order: its glyph strings are
    2-byte hex codes, mapped through the current font's ToUnicode CMap."""
    fonts = {}
    for d, _ in objs.values():
        res = re.search(rb"/Font\s*<<(.*?)>>", d, re.S)
        refs = re.findall(rb"/(\w+)\s+(\d+) 0 R", res.group(1)) if res else []
        for name, ref in refs:
            tu = re.search(rb"/ToUnicode (\d+) 0 R", objs[int(ref)][0])
            if tu:
                fonts[name.decode()] = _cmap(objs[int(tu.group(1))][1])
    text = []
    for _, data in objs.values():
        if not data or b" Tf" not in data:
            continue
        cmap = {}
        for m in re.finditer(rb"/(\w+)\s+[\d.]+\s+Tf|<([0-9A-Fa-f]*)>", data):
            if m.group(1):
                cmap = fonts.get(m.group(1).decode(), {})
                continue
            h = m.group(2).decode()
            text += [cmap.get(int(h[i : i + 4], 16), "?") for i in range(0, len(h), 4)]
    return "".join(text)


def _add_in_closed_tab(unit, child):
    """A slide break, then a tabs element holding `child` in its second tab."""
    add_element(unit, SlideBreakElement.objects.create())
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = add_element(unit, tabs)
    Element.objects.create(
        unit=unit,
        content_object=child,
        parent=join,
        tab_id=tabs.data["tabs"][1]["id"],
        order=0,
    )


# print.js also re-runs on the `print` media-query change (for Safari). In
# page.pdf() that second pass runs under the PRINT cascade, where a closed tab
# is already revealed -- and would mask a beforeprint pass that skipped it.
# Chrome's Ctrl+P is only guaranteed the beforeprint pass, so the geometry test
# deafens print.js to the media query and measures that pass alone.
_BEFOREPRINT_ONLY_JS = """(() => {
  const mm = window.matchMedia.bind(window);
  window.matchMedia = (q) => {
    const m = mm(q);
    if (q === 'print') { m.addEventListener = () => {}; m.addListener = () => {}; }
    return m;
  };
})();"""


def _print_pdf(page, live_server, slug, width, *, beforeprint_only=False):
    if beforeprint_only:
        page.add_init_script(_BEFOREPRINT_ONLY_JS)
    _make_pa_user(slug)
    _login(page, live_server, slug)
    unit = _seed_course_and_unit(slug, slug=slug)
    for _, surface, latex, _, _ in DISPLAYS:
        body = r"<p>\[" + latex + r"\]</p>"
        if surface == "prose":
            el = TextElement.objects.create(body=body)
        elif surface == "callout":
            el = CalloutElement.objects.create(kind="tip", body=body)
        elif surface == "hidden_tab":
            _add_in_closed_tab(unit, MathElement.objects.create(latex=latex))
            continue
        else:
            el = MathElement.objects.create(latex=latex)
        add_element(unit, el)
    page.set_viewport_size({"width": width, "height": 900})
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{path}")
    page.wait_for_selector(".el--math .katex-html > .tag")
    page.evaluate("document.fonts.ready.then(() => true)")
    assert page.evaluate("document.fonts.check('1em KaTeX_Main')")
    screen = page.evaluate(_PROBE_JS)
    assert len(screen) == len(DISPLAYS), screen
    pdf = page.pdf(format="A4")
    out = os.environ.get("PRINT_WIDE_MATH_PDF_DIR")
    if out:
        with open(os.path.join(out, f"print_wide_math_{width}.pdf"), "wb") as f:
            f.write(pdf)
    return screen, _objects(pdf)


@pytest.mark.parametrize("width", [1280, 390])
def test_wide_displays_print_inside_the_column(page, live_server, width):
    screen, objs = _print_pdf(
        page, live_server, f"pwm{width}", width, beforeprint_only=True
    )
    ann = _annotations(objs)
    scales = {}
    for i, (name, _, _, wide, tagged) in enumerate(DISPLAYS):
        col = ann[f"d{i}-W"]
        for kind in ("L", "R") + (("T",) if tagged else ()):
            key = f"d{i}-{kind}"
            assert key in ann, f"{name}: {kind} probe clipped out of the PDF"
            x0, x1 = ann[key]
            # Linux Chromium does not drop a partly clipped link: it trims the
            # rect to the clip. A 4px probe must keep its full 3pt.
            assert x1 - x0 >= 4 * PT - TOL, (name, kind, ann[key], "trimmed")
            assert x0 >= col[0] - TOL, (name, kind, ann[key], col)
            assert x1 <= col[1] + TOL, (name, kind, ann[key], col)
        if tagged:
            # The number still FOLLOWS the formula (#390), not laid over it.
            assert ann[f"d{i}-T"][0] >= ann[f"d{i}-R"][1] - TOL, (name, ann)
        # Formula span, start of L to start of R, PDF against screen. The
        # display unrendered on screen has no span there; it shares the first
        # display's formula, so that span stands in.
        printed = ann[f"d{i}-R"][0] - ann[f"d{i}-L"][0]
        span = (screen[i]["R"] - screen[i]["L"]) or (screen[0]["R"] - screen[0]["L"])
        scales[name] = printed / (span * PT)
        if not wide:
            # 0.03, not tighter: glyph advances round at the printed ~16px
            # (measured 2.3% short), as print.js's small-size note describes.
            # A shrink or a dropped min() moves it far more than that.
            assert abs(scales[name] - PRINT_SCALE) <= 0.03, (name, scales[name])
    wide_scales = [scales[d[0]] for d in DISPLAYS if d[3]]
    assert all(s < 0.99 * PRINT_SCALE for s in wide_scales), scales
    print(width, {n: round(s, 3) for n, s in scales.items()})


@pytest.mark.parametrize("width", [1280, 390])
def test_equation_numbers_survive_printing(page, live_server, width):
    """Auto-numbers keep counting ACROSS displays on paper: (1)-(9) in order,
    once each. A container query on the display printed (1)(1)(1) three times."""
    _, objs = _print_pdf(page, live_server, f"pwmnum{width}", width)
    text = _pdf_text(objs)
    assert "(A)" in text, "the reader found no tag text at all"
    numbers = re.findall(r"\((\d+)\)", text)
    assert numbers == NUMBERS, numbers


def test_screen_layout_untouched_by_printing(page, live_server):
    """Screen rendering is unchanged: the flag lives only between beforeprint and
    afterprint, and nothing in the screen cascade reads it."""
    screen, _ = _print_pdf(page, live_server, "pwmscreen", 1280)
    assert {s["font"] for s in screen} == {"19.36px"}, screen
    assert page.locator(".katex-display[data-print-fit]").count() == 0
    page.evaluate("dispatchEvent(new Event('beforeprint'))")
    assert page.locator(".katex-display[data-print-fit]").count() == len(DISPLAYS)
    fonts = page.evaluate(
        "() => [...document.querySelectorAll('.katex-display > .katex > .katex-html')]"
        ".map((h) => getComputedStyle(h).fontSize)"
    )
    assert set(fonts) == {"19.36px"}, fonts
    page.evaluate("dispatchEvent(new Event('afterprint'))")
    assert page.locator(".katex-display[data-print-fit]").count() == 0


def test_printed_display_draws_no_scrollbar(page, live_server):
    """Paper cannot scroll. A shrunk display still overflows its box by a pixel
    or two (KaTeX's fixed-width struts do not scale), and the screen scroller's
    `overflow-x: auto` printed a scrollbar under it (owner report, Chrome)."""
    _print_pdf(page, live_server, "pwmbar", 1280)
    page.emulate_media(media="print")
    overflow = page.evaluate(
        "() => [...document.querySelectorAll('.el--text .katex-display')]"
        ".map((d) => getComputedStyle(d).overflowX)"
    )
    assert overflow and set(overflow) == {"hidden"}, overflow
