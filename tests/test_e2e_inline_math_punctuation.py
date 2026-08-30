"""Inline maths must not shed the punctuation the author typed against it.

REPORTED on a real unit: the sentence "...w jednej kolumnie to \\(18\\)." put the
full stop alone on the next line. The stored body carries NO space before it --
the text node reaching the browser is `... to \\(18\\).` in one piece.

ROOT CAUSE. KaTeX types the formula into `.katex .base`, which the vendored
stylesheet makes `display: inline-block` -- an ATOMIC INLINE, which the line
breaker may break after regardless of whether a space is there. REPRODUCED with
a bare `<span style="display:inline-block">18</span>.` and NOT reproduced with a
bare `<b>18</b>.`, so the inline-block is the whole mechanism, and no amount of
whitespace hygiene in the authored body can reach it.

THE FIX is `white-space: nowrap` on `.katex` -- Chromium resolves that boundary
against the atomic inline's parent inline, which a U+2060 WORD JOINER and an
outer nowrap wrapper both fail to be (both MEASURED, both still break). It is
GUARDED by `:not(:has(.base ~ .base))` because KaTeX deliberately emits several
`.base` runs for a long inline formula so it can wrap inside the prose column;
a blanket nowrap costs 684px of overflow on the real lesson page. Both halves
are pinned below, each falsified by hand against the matching mutant.

MEASUREMENT DEVICE, stated because it is not a user gesture: the probe sweeps
the paragraph's width and asks, at each width, whether the stop still shares a
line with the last `.base` run. A single viewport width cannot pin this -- the
break only appears in the narrow band where the stop is the character that no
longer fits, and that band moves with the font. The sweep finds the band instead
of guessing it: with the rule rolled back the stop separates at 367px on this
page, and with the rule in place it separates at NO width down to 70px.

Marked e2e (excluded from the default run; use -m e2e)."""

import os

import pytest
from django.urls import reverse

from courses.models import TextElement
from tests.factories import add_element
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

# The reported sentence, verbatim in shape: no space before the stop.
REPORTED = (
    "<p>Wpisz w tabelę poniżej brakujące dzielniki w taki sposób, "
    "że iloczyn liczb w jednej kolumnie to \\(18\\).</p>"
)

# 23 `.base` runs -- KaTeX breaks inline maths at binary operators, so this one
# CAN wrap inside the column and the guard must leave it alone.
LONG = (
    "<p>iloczyn liczb w jednej kolumnie to "
    "\\(" + "+".join("abcdefghijklmnopqrstuvw") + "\\).</p>"
)

# Finds the first width at which the trailing stop leaves the formula's line.
# Rects are compared by VERTICAL OVERLAP, never by equality of `top`: `.base` is
# an inline-block that stands taller than the surrounding text, so the two tops
# differ by a few px on the SAME line.
SWEEP = """() => {
  const p = document.querySelector('.el--text p');
  let split = null, maxOverflow = 0;
  for (let w = 420; w >= 70; w -= 1) {
    p.style.width = w + 'px';
    maxOverflow = Math.max(maxOverflow, p.scrollWidth - p.clientWidth);
    if (split !== null) continue;
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    let stop = null;
    while (walker.nextNode()) {
      if (walker.currentNode.data.trim() === '.') stop = walker.currentNode;
    }
    if (!stop) throw new Error('no trailing stop text node -- maths did not typeset');
    const r = document.createRange();
    r.setStart(stop, 0); r.setEnd(stop, 1);
    const d = r.getBoundingClientRect();
    const runs = p.querySelectorAll('.katex .base');
    const last = runs[runs.length - 1].getBoundingClientRect();
    if (!(d.top < last.bottom && d.bottom > last.top)) split = w;
  }
  p.style.width = '';
  return {split, maxOverflow, runs: p.querySelectorAll('.katex .base').length,
          whiteSpace: getComputedStyle(p.querySelector('.katex')).whiteSpace};
}"""


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """live_server + the ORM in the test body, under pytest-playwright's session
    loop. Same shape and name as the fixture in test_e2e_math_reflow.py."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _open_lesson(page, live_server, username, slug, body):
    _make_pa_user(username)
    _login(page, live_server, username)
    unit = _seed_course_and_unit(username, slug=slug)
    add_element(unit, TextElement.objects.create(body=body))
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{path}")
    page.wait_for_selector(".el--text .katex")
    return unit


def test_inline_maths_keeps_the_full_stop_typed_against_it(page, live_server):
    """The reported sentence: at no width does the stop leave the formula's line."""
    _open_lesson(page, live_server, "imp_dot", "imp-dot", REPORTED)

    result = page.evaluate(SWEEP)

    assert result["runs"] == 1, result
    assert result["whiteSpace"] == "nowrap", result
    assert result["split"] is None, result


def test_a_long_inline_formula_still_wraps_inside_the_prose_column(page, live_server):
    """The guard. A multi-run formula must keep `white-space: normal` and must
    keep wrapping: without `:not(:has(.base ~ .base))` this paragraph overflows
    its own width by hundreds of pixels instead."""
    _open_lesson(page, live_server, "imp_long", "imp-long", LONG)

    result = page.evaluate(SWEEP)

    assert result["runs"] > 1, result
    assert result["whiteSpace"] == "normal", result
    assert result["maxOverflow"] == 0, result
