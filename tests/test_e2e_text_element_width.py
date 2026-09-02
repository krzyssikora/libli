"""A text element fills its column, like the tinted blocks beside it.

THE REPORT: on a collapsed lesson a top-level paragraph stopped 136px short of
the callout above it (measured on unit 487: `.el--text` 736 @204, `.callout`
872 @204). Every block shares a left edge, so the step showed as a ragged RIGHT
edge with nothing to explain it.

WHY NOT "widen only the maths", which was the first idea. Two measured reasons:
  * display maths typesets INSIDE a <p>, so the only mechanism that widens it
    from where it sits is a negative inline margin -- and that escapes the
    CONTAINER too. Screenshotted inside a callout: the box cleared the panel's
    left border and the accent rail. 795 of the 1,192 prose-maths elements in
    mat-pp are nested in a callout, spoiler or tabs.
  * it breaks the left edge. The formula started at x=136 against x=204 for the
    paragraph directly above it, in the same element.

AND THE MATHS ARGUMENT IS A RED HERRING ANYWAY. Ink measured over all 1,551
stored display blocks: 2 overflow at 872px, 6 at 736, 7 at 688. The whole width
question moves FIVE formulas out of 1,551, and #292's scroller reaches every one
of them at every width. So this is a layout decision, not a legibility one.

WHAT CHANGED: `.el--text` came off the prose-cap allow-list. Everything else on
it stays -- question stems, choices, feedback, the short-input, the gates, the
title and crumbs. `.callout__body` and `.spoiler__body` carry `.el--text`, so
prose inside a tinted block widens with it; that is intended and is what the
approved screenshot showed.

Marked e2e (excluded from the default run; use -m e2e)."""

import os

import pytest

from tests.factories import add_element
from tests.test_e2e_uniform_block_width import COLUMN_JS
from tests.test_e2e_uniform_block_width import _collapsed
from tests.test_e2e_uniform_block_width import _login
from tests.test_e2e_uniform_block_width import _seed_unit
from tests.test_e2e_uniform_block_width import _width

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """Declared HERE, not inherited: the helpers above are imported, but an
    autouse fixture is module-scoped and does not travel with them. Without it
    every test in this file errors with SynchronousOnlyOperation."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_a_top_level_text_element_is_as_wide_as_the_callout_beside_it(
    page, live_server
):
    """The headline pin, written as an EQUALITY against the callout rather than
    against the 736/872 literals: the report was about two blocks disagreeing,
    so the assertion should fail when they disagree, whatever the column becomes.

    The column assertion beside it is what stops the equality being vacuous --
    expanded, both are 648 and equal, which is why `_collapsed` proves its state.
    """
    from courses.models import CalloutElement
    from courses.models import TextElement

    user, _course, unit = _seed_unit("pa_textwidth")
    add_element(unit, TextElement.objects.create(body="<p>A top-level paragraph.</p>"))
    add_element(unit, CalloutElement.objects.create(kind="note", body="<p>Tinted.</p>"))

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    column = page.evaluate(COLUMN_JS)
    text = _width(page, ".el--text")
    callout = _width(page, ".callout")

    assert abs(text - callout) < 2, (
        f"a text element ({text}) must be as wide as the callout ({callout})"
    )
    # Not vacuous: both really do fill the column, rather than agreeing at some
    # narrower width they happen to share.
    assert abs(text - column) < 2, f"text {text} does not fill the column {column}"


@pytest.mark.django_db(transaction=True)
def test_prose_inside_a_tinted_block_widens_with_the_block(page, live_server):
    """The deliberate consequence, pinned so nobody 'fixes' it back.

    `.callout__body` carries `.el--text`, so it comes off the cap with it and now
    fills the callout's inner width. Asserted as "wider than the old 736 cap AND
    within the callout", not as a literal, because the inner width depends on the
    callout's padding and border rather than on any token.
    """
    from courses.models import CalloutElement

    user, _course, unit = _seed_unit("pa_tintedprose")
    add_element(
        unit,
        CalloutElement.objects.create(
            kind="note", body="<p>Body prose inside a tinted block.</p>"
        ),
    )

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    body = _width(page, ".callout__body")
    callout = _width(page, ".callout")

    assert body > 736 + 2, f".callout__body is still capped at {body}"
    assert body < callout, (
        f".callout__body ({body}) must stay inside its callout ({callout})"
    )


@pytest.mark.django_db(transaction=True)
def test_display_maths_in_prose_stays_inside_its_container(page, live_server):
    """The failure mode of the REJECTED approach, kept as a guard.

    A negative-margin breakout on `.katex-display` would widen nested maths past
    the callout's border. Nothing ships that today, so this asserts the property
    directly: the maths box never starts left of its container's content box.
    Delete this only with a screenshot showing the nested case is still contained.
    """
    from courses.models import CalloutElement

    user, _course, unit = _seed_unit("pa_nestedmath")
    add_element(
        unit,
        CalloutElement.objects.create(
            kind="note",
            body=r"<p>Rate:</p><p>\[\frac{k}{m}=\frac{4\pi^2}{T^2}\]</p>",
        ),
    )

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)
    page.wait_for_selector(".callout .katex-display .katex")

    edges = page.evaluate(
        """() => {
             const c = document.querySelector('.callout');
             const d = document.querySelector('.callout .katex-display');
             const cs = getComputedStyle(c);
             const cr = c.getBoundingClientRect();
             const dr = d.getBoundingClientRect();
             return {
               inner_left: cr.left + parseFloat(cs.paddingLeft)
                                   + parseFloat(cs.borderLeftWidth),
               inner_right: cr.right - parseFloat(cs.paddingRight)
                                     - parseFloat(cs.borderRightWidth),
               math_left: dr.left,
               math_right: dr.right,
             };
           }"""
    )
    assert edges["math_left"] >= edges["inner_left"] - 1, edges
    assert edges["math_right"] <= edges["inner_right"] + 1, edges
