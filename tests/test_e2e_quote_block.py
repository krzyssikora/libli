"""Playwright e2e for the RTE's Quote button: the stored <blockquote> must READ
as a quote in the student render, and the editor surface must show the same
prose spacing the lesson does. Marked e2e (run with `-m e2e`).

The visual guards are computed-style/geometry assertions rather than markup
checks on purpose: the bug they cover shipped a perfectly correct <blockquote>
that was pixel-identical to a <p>, so asserting on the tag alone stayed green.
"""

import os

import pytest

from tests.test_e2e_editor import _add_element
from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _latest_text_body():
    from courses.models import TextElement

    el = TextElement.objects.order_by("-id").first()
    return el.body if el else ""


def _seed_text(unit, body):
    from courses.models import TextElement
    from tests.factories import add_element

    el = TextElement.objects.create(body=body)
    add_element(unit, el)
    return el


# The properties that can make a quote legible as a quote. reset.css zeroes every
# margin, so a <blockquote> that sets none of these is indistinguishable from the
# paragraph above it -- which is exactly the shipped bug.
_QUOTE_STYLE = (
    "el => { const s = getComputedStyle(el); return {"
    " bl: parseFloat(s.borderLeftWidth), pl: parseFloat(s.paddingLeft),"
    " ml: parseFloat(s.marginLeft), fs: s.fontStyle, col: s.color }; }"
)

_GAP = "([a, b]) => b.getBoundingClientRect().top - a.getBoundingClientRect().bottom"


@pytest.mark.django_db(transaction=True)
def test_quote_button_stores_a_blockquote(page, live_server):
    """Drive the real toolbar button (not execCommand directly): the block the
    caret sits in must survive save as a <blockquote>."""
    _make_pa_user("bq_save")
    _login(page, live_server, "bq_save")
    unit = _seed_course_and_unit("bq_save", slug="bq-save")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")

    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("Cytowane zdanie")
    page.locator('[data-edit-slot] [data-cmd="blockquote"]').click()
    page.locator("[data-edit-slot] button[type='submit']").click()

    preview = page.locator('[data-scope="preview"]')
    preview.get_by_text("Cytowane zdanie").wait_for()

    body = _latest_text_body()
    assert "<blockquote" in body, f"Quote button stored no blockquote: {body!r}"
    assert preview.locator("blockquote").count() == 1, (
        "the sanitizer or the render dropped the blockquote on the way to the student"
    )


@pytest.mark.django_db(transaction=True)
def test_quote_renders_visually_distinct_from_a_paragraph(page, live_server):
    """A stored quote must render as something a reader can tell apart from the
    plain paragraph beside it."""
    _make_pa_user("bq_look")
    _login(page, live_server, "bq_look")
    unit = _seed_course_and_unit("bq_look", slug="bq-look")
    _seed_text(unit, "<p>Zwykly akapit</p><blockquote>Cytowane zdanie</blockquote>")

    page.goto(_editor_url(live_server, unit))
    preview = page.locator('[data-scope="preview"]')
    preview.locator("blockquote").wait_for()

    qs = preview.locator("blockquote").evaluate(_QUOTE_STYLE)
    ps = preview.locator(".el--text > p").first.evaluate(_QUOTE_STYLE)

    # A quote must carry SOMETHING a paragraph does not. Any one of these would
    # do; asserting the disjunction keeps the test from dictating the styling.
    distinct = (
        qs["bl"] > 0
        or qs["pl"] > 0
        or qs["ml"] > 0
        or qs["fs"] != ps["fs"]
        or qs["col"] != ps["col"]
    )
    assert distinct, (
        f"blockquote renders identically to a paragraph (quote={qs}, para={ps}) — "
        "reset.css zeroes the UA `margin: 1em 40px`, so the quote needs its own rule"
    )


@pytest.mark.django_db(transaction=True)
def test_editor_and_preview_agree_on_paragraph_spacing(page, live_server):
    """WYSIWYG: the gap the author sees between two blocks in the contenteditable
    must be the gap the student gets. `form p` in app.css used to leak 16px into
    the surface (it lives inside <form class="editor-form">) while the lesson had
    none, so the editor over-reported spacing on every text element."""
    _make_pa_user("bq_gap")
    _login(page, live_server, "bq_gap")
    unit = _seed_course_and_unit("bq_gap", slug="bq-gap")
    _seed_text(unit, "<p>Pierwszy akapit</p><p>Drugi akapit</p>")

    page.goto(_editor_url(live_server, unit))
    preview = page.locator('[data-scope="preview"]')
    preview.get_by_text("Drugi akapit").wait_for()
    preview_gap = page.evaluate(
        _GAP,
        [
            preview.locator(".el--text > p").nth(0).element_handle(),
            preview.locator(".el--text > p").nth(1).element_handle(),
        ],
    )

    # Load the same body into the editor's contenteditable and measure there.
    page.locator(".el-row").first.locator(".el-act-edit").first.click()
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    editor_gap = page.evaluate(
        _GAP,
        [
            surface.locator("> p").nth(0).element_handle(),
            surface.locator("> p").nth(1).element_handle(),
        ],
    )

    assert abs(editor_gap - preview_gap) <= 1, (
        f"editor shows a {editor_gap}px gap between blocks, the student sees "
        f"{preview_gap}px — the two surfaces must render authored prose alike"
    )
