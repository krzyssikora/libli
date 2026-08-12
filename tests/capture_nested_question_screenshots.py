"""Light + dark capture of a `choice` question nested in each of the five
containers (plan Task 10 Step 2, spec section 9.9).

Regeneration/verification tool, not CI. Run explicitly:

    uv run pytest tests/capture_nested_question_screenshots.py -m e2e

Not `test_`-prefixed as a FILENAME, so `python_files=["test_*.py"]` never
auto-collects it; the `test_`-named function inside is collected only when this
path is passed explicitly. Mirrors tests/capture_title_math_screenshots.py.

Why it exists: the widening lets a question render inside five container
templates that were only ever styled around prose and layout children. Nothing
in the unit-test suite can see whether the controls, the verdict block and the
per-option markers actually LOOK right in there -- and dark mode has to be judged
on its own, not inferred from light.

Each question is answered WRONG through the real browser gesture before the shot,
so every image carries the three things worth judging at once: live controls, a
verdict block, and per-option markers + feedback.

Dark is set through User.theme, NOT the libli_theme cookie: for an authenticated
user _resolve_theme_pref lets User.theme win outright, so a cookie is silently
ignored and the "dark" shot would come back light.

Alongside the images the run prints three families of MEASUREMENTS, because two
of the three judgements are not reliably eyeballed:

  * overflow -- the question wrapper, the options list, the Check button and the
    verdict block, each against the container's own content box, per side, in
    px, signed so that ANY POSITIVE NUMBER is the defect;
  * rhythm -- an A/B: the gaps above and below the nested question, against the
    gaps a nested TEXT element gets in the SAME container in the SAME slot with
    the SAME neighbours (every container is seeded twice for this), plus the
    top-level twin of the pair;
  * contrast -- the verdict, the per-option marker, the per-option feedback and
    the option text against the background composited from the whole ancestor
    chain, as a WCAG ratio, with the top-level question probed identically so a
    failing ratio can be told apart from one this feature never touched.

Output goes to SHOT_DIR (env) or docs/superpowers/screenshots/.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get(
        "SHOT_DIR", Path(settings.BASE_DIR) / "docs" / "superpowers" / "screenshots"
    )
)

# 1200 tall, not the usual 900: an answered question inside a callout is ~520px
# and the sticky `.unit-foot` nav is painted over the bottom of any element
# screenshot taller than the viewport -- at 900 it covered the callout's trailing
# prose, i.e. exactly the rhythm the shot exists to show.
DESKTOP_VIEWPORT = {"width": 1440, "height": 1200}

# (key, container selector, child-wrapper selector inside the VISIBLE slot).
#
# Every container is seeded TWICE, in this order: the shot instance, whose slot
# holds [text, QUESTION, text], then a control twin whose slot holds
# [text, text, text]. `document.querySelectorAll(sel)[0]` is therefore always
# the shot and `[1]` always the control -- which is what turns the rhythm claim
# into an A/B (the same container, the same slot, the same neighbours, with and
# without the question) instead of a number with nothing to sit beside.
CONTAINERS = [
    ("callout", ".callout", ".callout__children > .callout__child"),
    ("spoiler", "details.spoiler", ".spoiler__children > .spoiler__child"),
    ("beforeafter", ".el--beforeafter", ".ba__panel:not([hidden]) > .ba__child"),
    ("tabs", ".el--tabs", "[data-tab-panel]:not([hidden]) > .tabs__child"),
    (
        "twocolumn",
        ".el--twocolumn",
        ".twocolumn__column:first-child > .twocolumn__child",
    ),
]

# Geometry + contrast probe, run once per container (and once for the top-level
# reference, whose "container" is the .lesson-block__body wrapper).
#
# Two design points worth stating, because both change the verdict:
#
#   * Backgrounds are COMPOSITED up the ancestor chain by PAINTING each fill
#     into a 1x1 canvas, not by parsing `rgba(...)` out of the computed value.
#     `.callout`'s fill is `color-mix(in srgb, var(--callout-accent) 6%,
#     var(--surface-raised))`, which Chrome computes to `color(srgb ...)` -- an
#     rgb()-only regex silently skips it and reports the PAGE ground, i.e. it
#     scores the callout's contrast as if the callout had no tint. Painting also
#     gets alpha compositing right for free.
#   * Overflow is measured for the CONTROLS and the VERDICT individually, not
#     only for the [data-question] wrapper. A wrapper can sit inside its
#     container while a wide control inside it sticks out.
#
# Sign convention: every `overflow` number is POSITIVE when the part sticks out
# past the container's content box on that side, so any positive value is the
# defect and everything <= 0 is clean.
PROBE_JS = """
(sel) => {
  const lum = (c) => {
    const f = c.map(v => {
      v = v / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
  };
  const unparsed = [];
  // Both syntaxes Chrome actually produces here: `rgb()/rgba()` for a plain
  // token, and `color(srgb r g b / a)` (0..1 components) for anything that went
  // through color-mix(), which is how every .callout tint is authored. Anything
  // else is RECORDED in `unparsed` rather than dropped -- a silently skipped
  // fill is exactly how a contrast number ends up scored against the page
  // ground instead of the container's own tint.
  const norm = (s) => {
    s = String(s || "").trim();
    let m = s.match(/^rgba?\\(([^)]+)\\)$/);
    if (m) {
      const p = m[1].split(/[,\\s/]+/).filter(Boolean).map(Number);
      return { rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 };
    }
    m = s.match(/^color\\(srgb\\s+([^)]+)\\)$/);
    if (m) {
      const p = m[1].split(/[\\s/]+/).filter(Boolean).map(Number);
      return {
        rgb: p.slice(0, 3).map(v => Math.round(v * 255)),
        a: p.length > 3 ? p[3] : 1,
      };
    }
    if (s && s !== "transparent") unparsed.push(s);
    return null;
  };
  const over = (top, under) =>
    top.rgb.map((v, i) => Math.round(v * top.a + under[i] * (1 - top.a)));
  // Composite the page ground, then every ancestor fill on top of it, outermost
  // first, so a translucent container tint is part of the answer.
  const bgOf = (el) => {
    const stack = [];
    let n = el;
    while (n) { stack.push(n); n = n.parentElement; }
    let acc = [255, 255, 255];
    for (let i = stack.length - 1; i >= 0; i--) {
      const c = norm(getComputedStyle(stack[i]).backgroundColor);
      if (c && c.a > 0) acc = over(c, acc);
    }
    return acc;
  };
  // The text colour AS PAINTED over that background (a translucent text colour
  // is a real thing in this palette, and comparing its raw value against the
  // background would flatter it).
  const fgOn = (el, bg) => {
    const c = norm(getComputedStyle(el).color);
    return c ? over(c, bg) : bg;
  };
  const ratio = (fg, bg) => {
    const [x, y] = [lum(fg), lum(bg)].sort((p, q) => q - p);
    return +((x + 0.05) / (y + 0.05)).toFixed(2);
  };
  const contentBox = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const px = (v) => parseFloat(v) || 0;
    return {
      top: r.top + px(s.paddingTop) + px(s.borderTopWidth),
      bottom: r.bottom - px(s.paddingBottom) - px(s.borderBottomWidth),
      left: r.left + px(s.paddingLeft) + px(s.borderLeftWidth),
      right: r.right - px(s.paddingRight) - px(s.borderRightWidth),
    };
  };
  const outside = (cb, el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      left: +(cb.left - r.left).toFixed(1),
      right: +(r.right - cb.right).toFixed(1),
      top: +(cb.top - r.top).toFixed(1),
      bottom: +(r.bottom - cb.bottom).toFixed(1),
    };
  };
  // Which ancestor actually paints the ground behind this text. Reported
  // because "the ratio is fine" is only meaningful once you know WHAT the text
  // is sitting on -- a nested question turning out to paint its own surface is
  // a different (and much stronger) result than it inheriting the container's.
  const bgSource = (el) => {
    let n = el;
    while (n) {
      const c = norm(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) {
        return n.tagName.toLowerCase() + "." + (n.className || "(none)");
      }
      n = n.parentElement;
    }
    return "(page ground)";
  };
  const swatch = (el) => {
    if (!el) return null;
    const bg = bgOf(el);
    const fg = fgOn(el, bg);
    const r = el.getBoundingClientRect();
    return {
      fg: "rgb(" + fg.join(",") + ")",
      bg: "rgb(" + bg.join(",") + ")",
      bg_from: bgSource(el),
      ratio: ratio(fg, bg),
      px: +getComputedStyle(el).fontSize.replace("px", ""),
      box: [+r.width.toFixed(1), +r.height.toFixed(1)],
    };
  };
  const container = document.querySelector(sel);
  if (!container) return { error: "no container for " + sel };
  const q = container.querySelector("[data-question]");
  if (!q) return { error: "no [data-question] in " + sel };
  const cb = contentBox(container);
  return {
    overflow: {
      question: outside(cb, q),
      choices: outside(cb, q.querySelector(".question__choices")),
      check: outside(cb, q.querySelector("button[type='submit']")),
      verdict: outside(cb, q.querySelector(".question__verdict")),
    },
    verdict: swatch(q.querySelector(".question__verdict")),
    marker: swatch(q.querySelector(".question__choice-marker")),
    feedback: swatch(q.querySelector(".question__choice-feedback")),
    choice_text: swatch(q.querySelector(".question__choice-text")),
    container_bg: "rgb(" + bgOf(container).join(",") + ")",
    unparsed: [...new Set(unparsed)],
  };
}
"""

# Vertical rhythm A/B: the gap ABOVE and BELOW the MIDDLE child of a container's
# visible slot, measured on the shot instance (middle child = the question) and
# on the control twin (middle child = a text element). Same container, same
# slot, same neighbours -- the only difference is what the middle child IS, so
# any divergence is the question's and nothing else's.
GAP_JS = """
([containerSel, childSel, index]) => {
  const container = document.querySelectorAll(containerSel)[index];
  if (!container) return null;
  const kids = [...container.querySelectorAll(childSel)];
  if (kids.length < 3) return { error: "only " + kids.length + " children" };
  const r = (el) => el.getBoundingClientRect();
  return {
    before: +(r(kids[1]).top - r(kids[0]).bottom).toFixed(1),
    after: +(r(kids[2]).top - r(kids[1]).bottom).toFixed(1),
  };
}
"""


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _choice(stem):
    """A/C single choice, BOTH options carrying feedback.

    The feedback is what makes per-option markers render at all: choice_marks'
    lesson branch marks only mark_result.annotated options, and mark() annotates
    only options that HAVE feedback. Without it these shots would show a verdict
    and nothing else, and judgement (c) would have no marker to judge.
    """
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem=stem, multiple=False)
    Choice.objects.create(
        question=q, text="A", is_correct=True, feedback="A was the one to pick."
    )
    Choice.objects.create(
        question=q, text="C", is_correct=False, feedback="C is the classic trap."
    )
    return q


def _text(body):
    from courses.models import TextElement

    return TextElement.objects.create(body=f"<p>{body}</p>")


def _build_lesson():
    """One enrolled student + one lesson unit carrying, in order:

      0-2. text, a choice question, text -- the TOP-LEVEL reference triple
      3+.  each of the five containers TWICE: the shot instance, whose visible
           slot holds [text, QUESTION, text], immediately followed by a control
           twin whose slot holds [text, TEXT, text].

    The pairing is the point. "The nested question sits in the container's
    rhythm" is a comparison, and the only honest comparison is the same
    container with the same neighbours and a different middle child.

    Every container's nested question sits in the slot that is VISIBLE at rest
    (before/after's BEFORE panel, tab 1, column 1) so a single pass can answer
    all of them without a container-specific reveal gesture -- except the
    spoiler, which is opened by clicking its summary.
    """
    from courses.models import BeforeAfterElement
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from courses.models import TwoColumnElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = make_verified_user(
        username="nqshots",
        email="nqshots@t.example.com",
        password=TEST_PASSWORD,
    )
    course = CourseFactory(slug="nested-question-shots", title="Nested question shots")
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Nested questions in containers",
    )
    EnrollmentFactory(student=student, course=course)

    add_element(unit, _text("Top-level prose, for the rhythm reference below."))
    add_element(unit, _choice("Top-level question (the reference)."))
    add_element(unit, _text("Top-level prose after the reference question."))

    def nest(join, tab_id, children):
        for child in children:
            Element.objects.create(
                unit=unit, content_object=child, parent=join, tab_id=tab_id
            )

    def slot_children(middle, label):
        """[leading text, MIDDLE, trailing text] -- the A/B's only variable is
        `middle`, so the shot instance and its control twin differ in exactly one
        child and every rhythm number is directly comparable."""
        return [
            _text(f"{label}: prose before."),
            middle,
            _text(f"{label}: prose after."),
        ]

    def make_callout(middle, label):
        obj = CalloutElement.objects.create(
            kind="example", body=f"<p>{label}: the callout's own body text.</p>"
        )
        nest(
            add_element(unit, obj),
            CalloutElement.SLOT_ID,
            slot_children(middle, label),
        )

    def make_spoiler(middle, label):
        obj = SpoilerElement.objects.create(
            label="Show the task", body=f"<p>{label}: the spoiler's own body text.</p>"
        )
        nest(
            add_element(unit, obj),
            SpoilerElement.SLOT_ID,
            slot_children(middle, label),
        )

    def make_beforeafter(middle, label):
        obj = BeforeAfterElement.objects.create(button_label="Swap")
        nest(
            add_element(unit, obj),
            BeforeAfterElement.BEFORE_SLOT_ID,
            slot_children(middle, label),
        )

    def make_tabs(middle, label):
        obj = TabsElement.objects.create(
            data={
                "tabs": [
                    {"id": "t000001", "label": "First"},
                    {"id": "t000002", "label": "Second"},
                ]
            }
        )
        nest(add_element(unit, obj), "t000001", slot_children(middle, label))

    def make_twocolumn(middle, label):
        obj = TwoColumnElement.objects.create(
            data={"columns": [{"id": "c000001"}, {"id": "c000002"}]}
        )
        join = add_element(unit, obj)
        nest(join, "c000001", slot_children(middle, label))
        nest(join, "c000002", [_text("The right column, for contrast.")])

    # Shot instance FIRST, control twin SECOND, for every family -- CONTAINERS'
    # querySelectorAll index depends on exactly this order.
    for stem, make in (
        ("callout", make_callout),
        ("spoiler", make_spoiler),
        ("before/after", make_beforeafter),
        ("tab", make_tabs),
        ("two column", make_twocolumn),
    ):
        make(_choice(f"Nested in a {stem}."), "shot")
        make(_text(f"Control: a text element where the {stem} question sits."), "ctrl")

    return student, unit


def _answer_wrong(scope):
    """Tick the distractor "C" and press Check, inside `scope`.

    The REAL gesture, not a fetch into check_answer: the shot has to show what a
    student's browser actually paints, and question.js's inline swap is the thing
    that puts the verdict and the per-option feedback where they end up.
    """
    li = (
        scope.locator(".question__choice")
        .filter(has=scope.page.locator(".question__choice-text", has_text="C"))
        .first
    )
    li.locator("input[type='radio']").check()
    scope.locator("button[type='submit']").first.click()
    scope.locator(".question__verdict").first.wait_for(state="visible")


def test_capture(browser, live_server):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shots = []
    measurements = []

    _student, unit = _build_lesson()
    path = reverse(
        "courses:lesson_unit",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk},
    )
    url = f"{live_server.url}{path}"

    ctx = browser.new_context(viewport=DESKTOP_VIEWPORT)
    page = ctx.new_page()
    try:
        _login(page, live_server, "nqshots")
        for theme in ("light", "dark"):
            _student.theme = theme
            _student.save(update_fields=["theme"])
            page.goto(url)
            assert page.locator("html").get_attribute("data-theme") == theme
            page.wait_for_selector("[data-tabs].tabs--js")
            # Both spoilers (shot + control) need the reveal gesture; the control
            # one only so its rhythm is measurable at all.
            for i in range(page.locator("details.spoiler").count()):
                page.locator("details.spoiler summary.spoiler__toggle").nth(i).click()

            # Answer the top-level reference first, then each nested one. `.first`
            # for the containers is the SHOT instance -- the control twin has no
            # question in it at all.
            _answer_wrong(page.locator(".lesson-block__body > [data-question]").first)
            for _key, sel, _child_sel in CONTAINERS:
                _answer_wrong(page.locator(sel).first)

            # `theme=theme` is a DEFAULT ARGUMENT, not a closure read: this
            # helper is redefined inside the theme loop, and a late-bound
            # `theme` would write both passes to the same filenames (ruff B023).
            def shoot(locator, name, theme=theme):
                # Centre the subject before shooting. An element screenshot
                # captures the VIEWPORT region the element occupies, so the
                # sticky `.unit-foot` nav parked at the bottom of the viewport
                # gets painted over the bottom of any subject that reaches it --
                # which is where a question's verdict and the container's
                # trailing prose live. Centring moves the subject clear of it.
                locator.evaluate("el => el.scrollIntoView({block: 'center'})")
                out = OUT_DIR / f"{name}-{theme}.png"
                locator.screenshot(path=str(out))
                shots.append(out)

            shoot(
                page.locator(".lesson-block__body > [data-question]").first,
                "nested-question-toplevel",
            )

            # The top-level reference goes through the SAME probe, so every
            # contrast number below has a not-nested twin. Without it a failing
            # ratio inside a container cannot be told apart from a failing ratio
            # the feature never touched.
            top = page.evaluate(PROBE_JS, ".lesson-block__body:has(> [data-question])")
            # `.slide` is the wrapper _lesson_article.html puts every
            # .lesson-block in, so its .lesson-block children are the top-level
            # twin of a container's slot children: [text, question, text].
            top_gap = page.evaluate(GAP_JS, [".slide", ":scope > .lesson-block", 0])
            measurements.append(
                f"[{theme}] TOP LEVEL reference: gaps={top_gap} "
                f"verdict={top.get('verdict')} marker={top.get('marker')} "
                f"feedback={top.get('feedback')} "
                f"choice_text={top.get('choice_text')}"
            )

            for key, sel, child_sel in CONTAINERS:
                shoot(page.locator(sel).first, f"nested-question-{key}")
                probe = page.evaluate(PROBE_JS, sel)
                gap = page.evaluate(GAP_JS, [sel, child_sel, 0])
                control = page.evaluate(GAP_JS, [sel, child_sel, 1])
                measurements.append(
                    f"[{theme}] {key}: overflow={probe.get('overflow')} "
                    f"gaps(question)={gap} gaps(control text)={control} "
                    f"container_bg={probe.get('container_bg')} "
                    f"verdict={probe.get('verdict')} marker={probe.get('marker')} "
                    f"feedback={probe.get('feedback')} "
                    f"choice_text={probe.get('choice_text')} "
                    f"unparsed={probe.get('unparsed')}"
                )

            full = OUT_DIR / f"nested-question-page-{theme}.png"
            page.screenshot(path=str(full), full_page=True)
            shots.append(full)
    finally:
        ctx.close()

    print(f"SCREENSHOTS ({len(shots)}): {OUT_DIR}")
    for line in measurements:
        print(f"[measure] {line}")
    assert len(shots) == 14
