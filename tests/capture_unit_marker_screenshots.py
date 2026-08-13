"""Light + dark capture of every surface the unit-kind markers touch
(spec 2026-08-12, Task 8 Step 1).

Regeneration/verification tool, not CI. Run explicitly:

    uv run pytest tests/capture_unit_marker_screenshots.py -m e2e

Not `test_`-prefixed as a FILENAME, so `python_files=["test_*.py"]` never
auto-collects it; the `test_`-named function inside is collected only when
this path is passed explicitly. Mirrors tests/capture_title_math_screenshots.py.

Why it exists: two of the spec's acceptance decisions cannot be settled by a
geometry assertion, only by looking at a real render.

  1. GLYPH LEGIBILITY. Both glyphs are compound stroke paths inside a 9-radius
     circle on a 24-unit viewBox, painted at ~13px in the rail. A circled `?`
     drawn naively at that size reads as a blob. The e2e suite pins where the
     glyph SITS, never what it LOOKS like.
  2. THE `--surface-sunken` COLLISION. `.unit-kind-chip` is a `.badge`, whose
     fill is `var(--surface-sunken)` (app.css:119) — the SAME token
     `.outline-unit:hover` (app.css:533) and `.outline-node:target`
     (app.css:554-556) paint the row with. Under either state the chip's fill
     equals its background and only its 1px `--border-default` rim separates
     it. The spec accepts this; the outline rest/hover/target triple below is
     what that acceptance is judged from.

Dark is set through User.theme, NOT the libli_theme cookie: for an
authenticated user _resolve_theme_pref lets User.theme win outright, so a
cookie is silently ignored and the "dark" shot would come back light.

SEED CONSTRAINT: `ContentNode.obligatory` defaults to True and
ContentNodeFactory does not set it, so every unit here passes `obligatory`
explicitly. An omitted kwarg renders NO marker and the shot is of nothing --
except `req_unit`, which is left obligatory on purpose as the unmarked control.

Output goes to SHOT_DIR (env) or ./.superpowers/shots/, both gitignored.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get("SHOT_DIR", Path(settings.BASE_DIR) / ".superpowers" / "shots")
)

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
# Same viewport the drawer arms of test_e2e_unit_nav.py use.
MOBILE_VIEWPORT = {"width": 390, "height": 780}

# A single wide \frac{...}{...}: the tallest, widest UNBREAKABLE KaTeX atom a
# title can carry, and the one the spec names as its documented-but-untested
# residual on the outline row (an atom that cannot wrap painting across the
# 8px gap into the chip). A short \(x^2\) would not reach the chip at any width.
#
# The numerator's LENGTH is load-bearing and MEASURED, not guessed: at 390px the
# outline title column renders 232px wide, and a \frac narrower than that simply
# wraps onto its own line with room to spare -- two earlier drafts of this
# fixture measured 137px of clearance (a 3-term numerator) and then a 128.8px
# atom (a 7-term one), i.e. both shot the residual NOT happening. A \frac's box
# is max(numerator, denominator), NOT their sum, so terms buy width slowly:
# ~18px each. Fourteen terms measure past the column. The guard in shot 4b
# re-measures this every run rather than trusting the constant.
MATHS_TITLE = (
    r"Oblicz \(\frac{a^{2}+b^{2}+c^{2}+d^{2}+e^{2}+f^{2}+g^{2}"
    r"+h^{2}+i^{2}+j^{2}+k^{2}+l^{2}+m^{2}+n^{2}}"
    r"{a-b-c-d-e-f-g-h-i-j-k-l-m-n}\) dla podanych liczb"
)

# Measure a marker's own glyph + word boxes on whichever row it is on.
KIND_BOXES_JS = """
(root) => {
  const out = [];
  for (const k of root.querySelectorAll('.unit-kind')) {
    const svg = k.querySelector('svg.icon');
    const lab = k.querySelector('.unit-kind__label');
    out.push({
      cls: k.className,
      kind: k.getBoundingClientRect().toJSON(),
      svg: svg ? svg.getBoundingClientRect().toJSON() : null,
      label: lab ? lab.getBoundingClientRect().toJSON() : null,
    });
  }
  return out;
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


def _build_course():
    """One chapter carrying both marked kinds, an unmarked control and a maths row.

    Shape (pre-order):
        Chapter  "Rozdzial 1"
          add_unit    lesson, obligatory=False  -> the `additional` marker
          quiz_unit   quiz                      -> the `quiz` marker
          req_unit    lesson, obligatory=True   -> the UNMARKED control
          maths_unit  lesson, obligatory=False  -> marked AND \\frac-titled

    req_unit is also the page every rail/drawer shot is taken FROM: its own row
    is the unmarked one, so a single rail shot shows both glyphs and the absence
    of a third in the same column, which is what makes the column read as a
    column rather than as decoration.
    """
    owner = make_verified_user(
        username="unitkindowner",
        email="unitkindowner@t.example.com",
        password=TEST_PASSWORD,
    )
    course = CourseFactory(
        slug="unit-kind-shots", owner=owner, title="Unit kind marker shots"
    )
    chapter = ContentNodeFactory(
        course=course,
        kind="chapter",
        parent=None,
        unit_type=None,
        order=0,
        title="Rozdzial 1",
    )
    add_unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        order=0,
        obligatory=False,
        title="Zadania dodatkowe",
    )
    quiz_unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=chapter,
        order=1,
        obligatory=True,
        title="Sprawdzian z ulamkow",
    )
    req_unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        order=2,
        obligatory=True,  # explicit: the deliberate UNMARKED control
        title="Lekcja obowiazkowa",
    )
    maths_unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        order=3,
        obligatory=False,
        title=MATHS_TITLE,
    )

    student = make_verified_user(
        username="unitkindstudent",
        email="unitkindstudent@t.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(student=student, course=course)

    return {
        "owner": owner,
        "student": student,
        "course": course,
        "chapter": chapter,
        "add_unit": add_unit,
        "quiz_unit": quiz_unit,
        "req_unit": req_unit,
        "maths_unit": maths_unit,
    }


def test_capture(browser, live_server):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shots = []
    measurements = []

    def shoot(name, locator=None, *, page=None):
        path = OUT_DIR / f"{name}.png"
        if locator is not None:
            locator.screenshot(path=str(path))
        else:
            page.screenshot(path=str(path), full_page=True)
        shots.append(path)

    nodes = _build_course()
    course = nodes["course"]
    slug = course.slug
    student = nodes["student"]

    def _url(name, **kwargs):
        return f"{live_server.url}{reverse(name, kwargs=kwargs)}"

    def unit_url(node):
        is_quiz = node.unit_type == "quiz"
        name = "courses:quiz_unit" if is_quiz else "courses:lesson_unit"
        return _url(name, slug=slug, node_pk=node.pk)

    def set_theme(user, theme):
        user.theme = theme
        user.save(update_fields=["theme"])

    outline_url = _url("courses:course_outline", slug=slug)

    # ------------------------------------------------------------------
    # DESKTOP: shot 1 (rail), shot 3 (outline rest/hover/target), shot 4
    # (maths outline row), shot 5 (unit-page head, lesson AND quiz).
    # ------------------------------------------------------------------
    ctx = browser.new_context(viewport=DESKTOP_VIEWPORT)
    page = ctx.new_page()
    try:
        _login(page, live_server, student.username)
        for theme in ("light", "dark"):
            set_theme(student, theme)

            # --- Shot 1: the contents rail, both glyphs at ~13px -------
            # Taken from req_unit's page: req_unit is the UNMARKED control, so
            # its own row shows the column's gap in the same frame.
            page.goto(unit_url(nodes["req_unit"]))
            assert page.locator("html").get_attribute("data-theme") == theme
            page.wait_for_selector(".unit-tree .unit-kind")
            shoot(f"unit-kind-1-rail-{theme}", page.locator(".unit-tree"))
            rail_kinds = page.eval_on_selector(".unit-tree", KIND_BOXES_JS)
            measurements.append(
                f"shot1 [{theme}] rail markers: "
                + "; ".join(
                    f"{k['cls']} glyph {k['svg']['width']:.1f}x{k['svg']['height']:.1f}"
                    for k in rail_kinds
                )
            )
            # THREE, not two: maths_unit is obligatory=False as well, so the
            # rail carries add_unit + maths_unit (additional) and quiz_unit
            # (quiz). req_unit, the control, carries none.
            kinds_seen = sorted(k["cls"].split("--")[-1] for k in rail_kinds)
            assert kinds_seen == ["additional", "additional", "quiz"], (
                f"expected the rail's markers to be 2x additional + 1x quiz, got "
                f"{kinds_seen} -- either a seed lost its obligatory=False or the "
                f"unmarked control started emitting one"
            )

            # --- Shot 5: the unit-page head, BOTH article templates -----
            # _lesson_article.html and _quiz_article.html carry their own copy
            # of the .lesson-unit__heading group; a shot of one says nothing
            # about the other.
            page.goto(unit_url(nodes["add_unit"]))
            page.wait_for_selector(".lesson-unit__heading .unit-kind-chip")
            shoot(
                f"unit-kind-5-head-lesson-{theme}",
                page.locator(".lesson-unit__head"),
            )
            page.goto(unit_url(nodes["quiz_unit"]))
            page.wait_for_selector(".lesson-unit__heading .unit-kind-chip")
            shoot(f"unit-kind-5-head-quiz-{theme}", page.locator(".lesson-unit__head"))

            # --- Shot 3: the outline row at rest, :hover and :target ----
            page.goto(outline_url)
            page.wait_for_selector(".outline-unit .unit-kind-chip")
            add_li = page.locator(f"#node-{nodes['add_unit'].pk}")
            quiz_li = page.locator(f"#node-{nodes['quiz_unit'].pk}")
            req_li = page.locator(f"#node-{nodes['req_unit'].pk}")
            # Rest: all three rows in one frame (marked, marked, unmarked), so
            # the chips are judged against the row that carries none.
            shoot(f"unit-kind-3a-outline-rest-{theme}", page.locator(".outline-tree"))

            # Hover: the ACCEPTED collision. `.outline-unit:hover` paints
            # --surface-sunken, which is the chip's own fill.
            add_li.locator(".outline-unit").hover()
            # A paint settle, NOT a synchronisation: `.outline-unit:hover` has no
            # transition, so there is no condition to wait ON -- hover() has
            # already dispatched and the style is applied. This only lets the
            # compositor land the repaint before the screenshot. Nothing below
            # asserts on it; the collision numbers come from getComputedStyle,
            # which does not need the paint at all.
            page.wait_for_timeout(120)
            shoot(f"unit-kind-3b-outline-hover-{theme}", add_li)
            collision = page.evaluate(
                """(pk) => {
                    const li = document.getElementById('node-' + pk);
                    const row = li.querySelector('.outline-unit');
                    const chip = li.querySelector('.unit-kind-chip');
                    const cs = getComputedStyle(chip);
                    return {
                        row: getComputedStyle(row).backgroundColor,
                        chip: cs.backgroundColor,
                        rim: cs.borderTopColor,
                        rimWidth: cs.borderTopWidth,
                    };
                }""",
                nodes["add_unit"].pk,
            )
            measurements.append(
                f"shot3 [{theme}] HOVER collision: row bg {collision['row']}, "
                f"chip bg {collision['chip']}, rim {collision['rim']} "
                f"@ {collision['rimWidth']}"
            )

            # Target: same token again, plus a 2px --primary ring on the row.
            # Move the pointer off first, or :hover and :target stack and the
            # shot no longer isolates :target.
            page.mouse.move(0, 0)
            page.goto(f"{outline_url}#node-{nodes['quiz_unit'].pk}")
            page.wait_for_selector(".outline-unit .unit-kind-chip")
            shoot(f"unit-kind-3c-outline-target-{theme}", quiz_li)
            target_collision = page.evaluate(
                """(pk) => {
                    const li = document.getElementById('node-' + pk);
                    const row = li.querySelector('.outline-unit');
                    const chip = li.querySelector('.unit-kind-chip');
                    return {
                        row: getComputedStyle(row).backgroundColor,
                        chip: getComputedStyle(chip).backgroundColor,
                    };
                }""",
                nodes["quiz_unit"].pk,
            )
            measurements.append(
                f"shot3 [{theme}] TARGET collision: row bg "
                f"{target_collision['row']}, chip bg {target_collision['chip']}"
            )
            # The unmarked control, at rest, for the same frame's baseline.
            shoot(f"unit-kind-3d-outline-unmarked-{theme}", req_li)

            # --- Shot 4: the MATHS outline row -------------------------
            # The spec's documented-but-untested residual: an unbreakable KaTeX
            # atom (a wide \frac) painting across the 8px gap into the chip.
            page.goto(outline_url)
            page.wait_for_selector(".outline-unit__title .katex")
            maths_li = page.locator(f"#node-{nodes['maths_unit'].pk}")
            shoot(f"unit-kind-4-outline-maths-{theme}", maths_li)
            gap = page.evaluate(
                """(pk) => {
                    const li = document.getElementById('node-' + pk);
                    const chip = li.querySelector('.unit-kind-chip');
                    const cb = chip.getBoundingClientRect();
                    let worst = null;
                    for (const k of li.querySelectorAll(
                        '.outline-unit__title .katex')) {
                        const kb = k.getBoundingClientRect();
                        const d = cb.left - kb.right;
                        if (worst === null || d < worst) worst = d;
                    }
                    return {gap: worst,
                        katex: li.querySelectorAll(
                            '.outline-unit__title .katex').length};
                }""",
                nodes["maths_unit"].pk,
            )
            assert gap["katex"] > 0, (
                "the maths outline row typeset no KaTeX -- shot 4 shows nothing "
                "the residual is about"
            )
            measurements.append(
                f"shot4 [{theme}] narrowest .katex-right -> chip-left gap: "
                f"{gap['gap']:.1f}px across {gap['katex']} katex box(es) "
                f"(negative = the atom paints INTO the chip)"
            )
    finally:
        ctx.close()

    # ------------------------------------------------------------------
    # Shot 1 detail: the SAME rail at device_scale_factor=4.
    #
    # Judged SECOND and only for geometry. A 4x raster is sharper than the 1x
    # the student actually sees, so it can make a blob look like a glyph; the
    # legibility verdict comes from the 1x shot above, and this one only
    # answers "is the shape the intended one".
    # ------------------------------------------------------------------
    ctx = browser.new_context(viewport=DESKTOP_VIEWPORT, device_scale_factor=4)
    page = ctx.new_page()
    try:
        _login(page, live_server, student.username)
        for theme in ("light", "dark"):
            set_theme(student, theme)
            page.goto(unit_url(nodes["req_unit"]))
            # Asserted in EVERY context, not just the first: set_theme writes to
            # the DB, and each context has its own cookie jar and session. A
            # context whose login silently landed anonymous would render the
            # light default and the "dark" shot would come back light -- which
            # looks like a correct light shot, not like a failure.
            assert page.locator("html").get_attribute("data-theme") == theme
            page.wait_for_selector(".unit-tree .unit-kind")
            shoot(f"unit-kind-1-rail-detail4x-{theme}", page.locator(".unit-tree"))
    finally:
        ctx.close()

    # ------------------------------------------------------------------
    # Shot 2 (drawer) + shot 4b (the maths outline row at phone width) -- one
    # 390x780 context, own viewport.
    #
    # The word is VISIBLE in the drawer (it un-hides .unit-kind__label) and the
    # glyph is larger, because `font-size: .82rem` sits on .unit-tree alone and
    # the drawer list is its SIBLING, not its descendant.
    # ------------------------------------------------------------------
    ctx = browser.new_context(viewport=MOBILE_VIEWPORT)
    page = ctx.new_page()
    try:
        _login(page, live_server, student.username)
        for theme in ("light", "dark"):
            set_theme(student, theme)
            # --- Shot 4b: the maths outline row at PHONE width ---------
            # MEASURED first, and the desktop shot is not the acceptance on its
            # own: at 1440 the outline title column is ~872px wide and the
            # \frac lands ~580px clear of the chip, so the desktop frame shows
            # the residual NOT happening rather than showing it survived. The
            # residual is a squeeze, so it has to be judged where the column is
            # squeezed.
            page.goto(f"{outline_url}")
            assert page.locator("html").get_attribute("data-theme") == theme
            page.wait_for_selector(".outline-unit__title .katex")
            shoot(
                f"unit-kind-4b-outline-maths-phone-{theme}",
                page.locator(f"#node-{nodes['maths_unit'].pk}"),
            )
            phone_gap = page.evaluate(
                """(pk) => {
                    const li = document.getElementById('node-' + pk);
                    const chip = li.querySelector('.unit-kind-chip');
                    const cb = chip.getBoundingClientRect();
                    const title = li.querySelector('.outline-unit__title');
                    const tb = title.getBoundingClientRect();
                    let worst = null;
                    for (const k of li.querySelectorAll(
                        '.outline-unit__title .katex')) {
                        const kb = k.getBoundingClientRect();
                        // Only a katex box that SHARES the chip's line can
                        // reach it; a box on an earlier line is vertically
                        // clear no matter how far right it runs.
                        const sameLine = kb.bottom > cb.top && kb.top < cb.bottom;
                        const d = cb.left - kb.right;
                        if (sameLine && (worst === null || d < worst)) worst = d;
                    }
                    let atom = 0;
                    for (const k of li.querySelectorAll(
                        '.outline-unit__title .katex')) {
                        atom = Math.max(atom, k.getBoundingClientRect().width);
                    }
                    return {gap: worst, column: tb.width, atom: atom,
                        overflow: title.scrollWidth - title.clientWidth};
                }""",
                nodes["maths_unit"].pk,
            )
            measurements.append(
                f"shot4b [{theme}] PHONE outline maths row: title column "
                f"{phone_gap['column']:.1f}px, widest katex atom "
                f"{phone_gap['atom']:.1f}px, title self-overflow "
                f"{phone_gap['overflow']:.1f}px, narrowest same-line katex->chip "
                f"gap {phone_gap['gap']} (None = no katex shares the chip's line)"
            )
            # Fixture-validity guard. The residual is an atom that CANNOT fit;
            # a \frac narrower than the column wraps to its own line and this
            # shot would show the residual not happening rather than showing
            # what it looks like when it does. Lengthen MATHS_TITLE's numerator
            # if this ever goes red -- do not relax the bound.
            assert phone_gap["atom"] > phone_gap["column"], (
                f"the \\frac measures {phone_gap['atom']:.1f}px against a "
                f"{phone_gap['column']:.1f}px title column -- it fits, so shot 4b "
                f"does not exercise the unbreakable-atom residual at all"
            )

            page.goto(unit_url(nodes["req_unit"]))
            fab = page.locator("[data-unit-drawer-open]")
            fab.wait_for(state="visible")
            fab.click()
            drawer = page.locator("[data-unit-drawer]")
            drawer.wait_for(state="visible")
            page.wait_for_selector("[data-unit-drawer] .unit-kind__label")
            shoot(f"unit-kind-2-drawer-{theme}", drawer)
            drawer_kinds = page.eval_on_selector(
                "[data-unit-drawer] .unit-drawer__list", KIND_BOXES_JS
            )
            drawer_seen = sorted(k["cls"].split("--")[-1] for k in drawer_kinds)
            assert drawer_seen == ["additional", "additional", "quiz"], (
                f"expected the drawer's markers to be 2x additional + 1x quiz, "
                f"got {drawer_seen}"
            )
            measurements.append(
                f"shot2 [{theme}] drawer markers: "
                + "; ".join(
                    f"{k['cls']} glyph "
                    f"{k['svg']['width']:.1f}x{k['svg']['height']:.1f}, word "
                    f"{k['label']['width']:.1f}x{k['label']['height']:.1f}"
                    for k in drawer_kinds
                )
            )
    finally:
        ctx.close()

    print(f"SCREENSHOTS ({len(shots)}): {OUT_DIR}")
    for line in measurements:
        print(f"[measure] {line}")
    # An EXACT count, not `> 0`: every shot below the first one is taken inside a
    # loop or a later context, so `> 0` stays green if a whole context raises
    # nothing but silently stops shooting -- and this script's whole output is the
    # shots. 22 = 2 themes x (8 desktop + 1 detail-4x + 2 mobile).
    assert len(shots) == 22, (
        f"expected 22 shots (2 themes x 11), got {len(shots)}: "
        f"{sorted(p.name for p in shots)}"
    )
