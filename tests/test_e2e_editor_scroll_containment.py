"""The unit editor's viewport must never acquire a scroll range the author
cannot scroll back.

At >=70rem `body.editor-page` is `height:100vh; overflow:hidden` (editor.css).
Because `html`'s overflow is `visible`, that `hidden` PROPAGATES to the viewport:
the page is not merely un-scrolled, it is un-scroll-ABLE by wheel, scrollbar or
keyboard -- while still being scrollable by script and by the UA. So any scroll
range the viewport acquires is a one-way trip: whatever moves it strands the page
header off-screen for good, and only a reload brings it back.

Two independent defects conspired to do exactly that, and each is pinned here:

1. KaTeX renders an accessibility twin `<span class="katex-mathml">` at
   `position:absolute`. A `.pane-body` is `overflow-y:auto` but was
   `position:static`, so for DISPLAY math -- which has no positioned ancestor
   inside the pane -- the twin's containing block was the initial containing
   block. An absolutely positioned box whose containing block sits OUTSIDE an
   overflow ancestor is not clipped by it, so those twins extended the
   VIEWPORT's scroll box (measured: 2056px against a 900px viewport).

2. `filltable_editor.js` brought its "add an answer cell" validation message
   into view with `scrollIntoView({block:"center"})`. `center` re-centres in
   EVERY scrollport, the viewport included -- so saving a freshly added fill-in
   table scrolled the page down and nothing could scroll it back.

Marked e2e (run with `-m e2e`).
"""

import os

import pytest

from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _seed_display_math(unit, count=8):
    """Callouts carrying DISPLAY math -- the shape whose KaTeX a11y twin has no
    positioned ancestor inside the preview pane."""
    from courses.models import CalloutElement
    from tests.factories import add_element

    for i in range(count):
        add_element(
            unit,
            CalloutElement.objects.create(
                kind="warning",
                heading="",
                body=rf"\[a^{{{i}}}\cdot a^k=a^{{{i}+k}}\]",
            ),
        )


def _open_editor(page, live_server, unit, width=1600, height=900):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    # KaTeX renders on a deferred script; the twins only exist afterwards.
    page.wait_for_function(
        "() => document.querySelectorAll('.preview-pane .katex-mathml').length > 0"
    )


@pytest.mark.django_db(transaction=True)
def test_preview_display_math_does_not_extend_the_viewport_scroll_box(
    page, live_server
):
    """A preview taller than the pane must scroll INSIDE the pane and leave the
    viewport with no scroll range at all."""
    _make_pa_user("sc_box")
    _login(page, live_server, "sc_box")
    unit = _seed_course_and_unit("sc_box", slug="sc-box")
    _seed_display_math(unit)

    _open_editor(page, live_server, unit)

    m = page.evaluate(
        """() => {
             const de = document.documentElement;
             const pane = document.querySelector('.preview-pane .pane-body');
             return {scrollH: de.scrollHeight, clientH: de.clientHeight,
                     bodyOverflow: getComputedStyle(document.body).overflow,
                     paneScrollH: pane.scrollHeight,
                     paneClientH: pane.clientHeight};
           }"""
    )
    # Guard the premise: this only matters while the viewport is un-scrollable
    # and the preview genuinely overflows its pane.
    assert m["bodyOverflow"] == "hidden", m
    assert m["paneScrollH"] > m["paneClientH"] + 50, m

    assert m["scrollH"] <= m["clientH"] + 1, (
        f"viewport has {m['scrollH'] - m['clientH']}px of scroll range the "
        f"author cannot scroll back: {m}"
    )


@pytest.mark.django_db(transaction=True)
def test_filltable_answer_error_does_not_strand_the_page(page, live_server):
    """Add a fill-in table, save it with no answer cell: the validation message
    must be brought into view WITHOUT moving the page viewport."""
    _make_pa_user("sc_ft")
    _login(page, live_server, "sc_ft")
    unit = _seed_course_and_unit("sc_ft", slug="sc-ft")
    _seed_display_math(unit)

    _open_editor(page, live_server, unit)
    assert page.evaluate("() => document.documentElement.scrollTop") == 0

    # The 8 seeded top-level callouts each carry their own add-menu (a callout
    # is now a single-slot container), so an unscoped [data-add-toggle] hits
    # strict mode. Scope to the single non-nested menu, mirroring
    # tests/test_e2e_depth3.py's _top_menu/_open_card pattern: _editor_scope.html
    # includes the top-level menu with no `nested`, so its wrapper carries no
    # .addwrap--nested.
    top_menu = page.locator("[data-add-menu]:not(.addwrap--nested)")
    top_menu.locator("[data-add-toggle]").click()
    top_menu.locator("[data-add-type='filltable']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")

    page.locator("[data-edit-slot] button[type='submit']").first.click()
    page.locator("[data-answer-error]").wait_for()

    assert page.evaluate("() => document.documentElement.scrollTop") == 0, (
        "saving a blank fill-in table scrolled the page; the author cannot "
        "scroll back because the viewport's overflow is hidden"
    )
    # The message still has to be visible -- a fix that simply drops the scroll
    # would pass the assertion above while hiding the error below the fold.
    assert page.locator("[data-answer-error]").is_visible()
    assert page.evaluate(
        """() => {
             const p = document.querySelector('[data-answer-error]');
             const pane = p.closest('.pane-body').getBoundingClientRect();
             const r = p.getBoundingClientRect();
             return r.top >= pane.top - 1 && r.top <= pane.bottom + 1;
           }"""
    ), "the validation message was left outside the editor pane's viewport"
