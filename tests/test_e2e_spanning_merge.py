"""Real-gesture e2e for span-aware structural editing and the merge/split UI.

Drives actual clicks and keystrokes throughout -- no page.evaluate shortcuts.
Helpers come from test_e2e_spanning_roundtrip (NOT test_e2e_table_editor, whose
_reopen/_save hard-code the plain-table root and assume the editor detaches on
save, which is false for a rejected one).

⚠️ DIALOGS: Playwright AUTO-DISMISSES window.confirm when no `dialog` listener
is attached, so an un-handled merge confirm returns false and the merge is
silently cancelled -- the test then fails on a later assertion with no hint
why. Any merge whose absorbed cells are non-empty must either register
`page.on("dialog", lambda d: d.accept())` first, or seed blank cells so the
confirm never fires. Note the fill-table's rule is stricter: cellIsNonEmpty
returns true for ANY answer or image cell regardless of displayed text, so a
fill-table merge that absorbs one ALWAYS needs the handler."""

import os

import pytest

from tests.test_e2e_spanning_roundtrip import (
    FILL_ROOT,  # noqa: F401 -- used by later cases in this file
)
from tests.test_e2e_spanning_roundtrip import TABLE_ROOT
from tests.test_e2e_spanning_roundtrip import _reopen
from tests.test_e2e_spanning_roundtrip import _save_and_report
from tests.test_e2e_spanning_roundtrip import _seed

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _cells(model, element):
    return model.objects.get(pk=element.object_id).normalized_data["cells"]


@pytest.mark.django_db(transaction=True)
def test_column_insert_through_a_colspan_widens_it(page, live_server):
    """Press the real column-insert handle on a spanning table: the straddled
    colspan must GROW rather than the row gaining a stray cell. Also proves
    slice 1's blanket handle-lock has been lifted."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("span_ins")
    _login(page, live_server, "span_ins")
    unit = _unit("span_ins", "span-ins")
    element = _seed(
        unit,
        TableElement,
        [
            [{"colspan": 3, "html": "top"}],
            [{"html": "a"}, {"html": "b"}, {"html": "c"}],
        ],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    # "Insert column right" of layout column 0 -> insertColumn(desc, 1), which
    # is strictly inside the colspan=3 and must widen it to 4.
    page.locator(f"{TABLE_ROOT} [data-col-insert][data-col-index='0']").click()
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"

    cells = _cells(TableElement, element)
    assert cells[0][0]["colspan"] == 4
    assert len(cells[0]) == 1  # the merged cell grew; no stray cell
    assert len(cells[1]) == 4  # the plain row gained one


@pytest.mark.django_db(transaction=True)
def test_column_delete_inside_a_colspan_shrinks_it(page, live_server):
    """The covering predicate: deleting a column the span covers decrements it."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("span_del")
    _login(page, live_server, "span_del")
    unit = _unit("span_del", "span-del")
    element = _seed(
        unit,
        TableElement,
        [
            [{"colspan": 3, "html": "top"}],
            [{"html": "a"}, {"html": "b"}, {"html": "c"}],
        ],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    page.locator(f"{TABLE_ROOT} [data-col-delete][data-col-index='1']").click()
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"

    cells = _cells(TableElement, element)
    assert cells[0][0]["colspan"] == 2
    assert len(cells[1]) == 2


def _cell(page, root, row, col):
    """The (row, col)-th DATA cell of the editor grid, by sibling position."""
    return (
        page.locator(f"{root} [data-table-grid] tr")
        .nth(row)
        .locator("td:not([data-control]), th:not([data-control])")
        .nth(col)
    )


@pytest.mark.django_db(transaction=True)
def test_shift_click_range_then_merge_persists_the_span(page, live_server):
    """Real gestures only: click a cell, Shift+click another, press Merge,
    Save -- the span must reach the database."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("merge_ok")
    _login(page, live_server, "merge_ok")
    unit = _unit("merge_ok", "merge-ok")
    element = _seed(
        unit,
        TableElement,
        [[{"html": ""} for _ in range(3)] for _ in range(3)],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    _cell(page, TABLE_ROOT, 1, 1).click(modifiers=["Shift"])
    page.locator(f"{TABLE_ROOT} [data-merge]").click()
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"

    cells = _cells(TableElement, element)
    assert cells[0][0]["colspan"] == 2
    assert cells[0][0]["rowspan"] == 2
    assert len(cells[0]) == 2  # 3 cells -> merged one + the survivor
    assert len(cells[1]) == 1  # row 1 lost the absorbed cell
    assert len(cells[2]) == 3  # untouched


@pytest.mark.django_db(transaction=True)
def test_split_returns_the_freed_cells(page, live_server):
    """A merged cell, split, must free the covered slots back as plain cells."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("split_ok")
    _login(page, live_server, "split_ok")
    unit = _unit("split_ok", "split-ok")
    element = _seed(
        unit,
        TableElement,
        [[{"colspan": 2, "rowspan": 2, "html": "m"}], []],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    page.locator(f"{TABLE_ROOT} [data-split]").click()
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"

    cells = _cells(TableElement, element)
    assert [len(r) for r in cells] == [2, 2]
    for row in cells:
        for c in row:
            assert "colspan" not in c
            assert "rowspan" not in c


@pytest.mark.django_db(transaction=True)
def test_merge_then_split_all_returns_the_original_rectangle(page, live_server):
    """The normalize_data BRANCH FLIP, pinned end to end.

    normalize_data picks its branch from "does any cell carry a span", so
    splitting the last merge flips a grid from keep-ragged-verbatim to
    rectangularising (pad-to-max-width, plus the 2x2 collapse guard). That is
    only safe because the editor never posts a layout-inconsistent grid.
    """
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("flip")
    _login(page, live_server, "flip")
    unit = _unit("flip", "flip")
    # Only the ANCHOR carries content: the absorbed cells must be blank, or
    # absorbedNonEmpty fires the confirm and Playwright auto-dismisses it (see
    # the dialog note in this file's header), silently cancelling the merge.
    element = _seed(
        unit,
        TableElement,
        [
            [{"html": "keep"}, {"html": ""}, {"html": ""}],
            [{"html": ""}, {"html": ""}, {"html": ""}],
            [{"html": ""}, {"html": ""}, {"html": ""}],
        ],
    )
    before = _cells(TableElement, element)

    # merge (0,0)..(1,1)
    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    _cell(page, TABLE_ROOT, 1, 1).click(modifiers=["Shift"])
    page.locator(f"{TABLE_ROOT} [data-merge]").click()
    assert _save_and_report(page, TABLE_ROOT), "merge save was rejected"
    assert _cells(TableElement, element)[0][0]["colspan"] == 2

    # split it again -- the grid flips back to the rectangularising branch
    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    page.locator(f"{TABLE_ROOT} [data-split]").click()
    assert _save_and_report(page, TABLE_ROOT), "split save was rejected"

    after = _cells(TableElement, element)
    assert [len(r) for r in after] == [3, 3, 3]
    for row in after:
        for c in row:
            assert "colspan" not in c
            assert "rowspan" not in c
            assert "header" not in c
    # The surviving anchor keeps its content; the re-created cells are empty.
    assert after[0][0]["html"] == before[0][0]["html"]


@pytest.mark.django_db(transaction=True)
def test_merge_over_content_asks_before_discarding(page, live_server):
    """A non-empty absorbed cell triggers window.confirm; dismissing it must
    leave the grid unchanged, accepting it must merge."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("confirm_ok")
    _login(page, live_server, "confirm_ok")
    unit = _unit("confirm_ok", "confirm-ok")
    element = _seed(
        unit,
        TableElement,
        [
            [{"html": "keep"}, {"html": "lose"}],
            [{"html": "a"}, {"html": "b"}],
        ],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    page.once("dialog", lambda d: d.dismiss())
    _cell(page, TABLE_ROOT, 0, 0).click()
    _cell(page, TABLE_ROOT, 0, 1).click(modifiers=["Shift"])
    page.locator(f"{TABLE_ROOT} [data-merge]").click()
    # Dismissed confirm -> no merge happened, so [data-merge] should still be
    # sitting there enabled (range untouched) and the grid unchanged on save.
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"
    cells = _cells(TableElement, element)
    assert "colspan" not in cells[0][0]
    assert len(cells[0]) == 2

    # Now accept: re-open, redo the gesture, accept the dialog.
    _reopen(page, live_server, unit, element, TABLE_ROOT)
    page.once("dialog", lambda d: d.accept())
    _cell(page, TABLE_ROOT, 0, 0).click()
    _cell(page, TABLE_ROOT, 0, 1).click(modifiers=["Shift"])
    page.locator(f"{TABLE_ROOT} [data-merge]").click()
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"
    cells = _cells(TableElement, element)
    assert cells[0][0]["colspan"] == 2


@pytest.mark.django_db(transaction=True)
def test_header_toggle_round_trips_a_header_cell(page, live_server):
    """Press the real Header-cell toggle on a focused td: save must store
    header: True. Toggle it again and save: the KEY must be gone entirely --
    not header: False -- so a plain table stays byte-identical to one that
    never touched the toggle."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("hdr_ok")
    _login(page, live_server, "hdr_ok")
    unit = _unit("hdr_ok", "hdr-ok")
    element = _seed(
        unit,
        TableElement,
        [[{"html": "a"}, {"html": "b"}], [{"html": "c"}, {"html": "d"}]],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    page.locator(f"{TABLE_ROOT} [data-header-toggle]").click()
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"
    cells = _cells(TableElement, element)
    assert cells[0][0]["header"] is True

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    page.locator(f"{TABLE_ROOT} [data-header-toggle]").click()
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"
    cells = _cells(TableElement, element)
    assert "header" not in cells[0][0]


@pytest.mark.django_db(transaction=True)
def test_header_toggle_is_disabled_for_a_cell_the_header_row_option_covers(
    page, live_server
):
    """Focus a row-0 cell, then tick [data-th-row] WITHOUT re-clicking the
    cell: the Header button must go disabled live -- enablement is computed
    off the checkbox's `change` event, not off focus movement."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("hdr_lock")
    _login(page, live_server, "hdr_lock")
    unit = _unit("hdr_lock", "hdr-lock")
    element = _seed(
        unit,
        TableElement,
        [[{"html": "a"}, {"html": "b"}], [{"html": "c"}, {"html": "d"}]],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    hdr_btn = page.locator(f"{TABLE_ROOT} [data-header-toggle]")
    assert not hdr_btn.is_disabled()

    page.locator(f"{TABLE_ROOT} [data-th-row]").click()
    assert hdr_btn.is_disabled()


@pytest.mark.django_db(transaction=True)
def test_merge_while_focus_sits_on_an_absorbed_cell_refocuses_the_survivor(
    page, live_server
):
    """Click cell B, shift-click A so the range covers both but focusCell is B
    (an absorbed cell). Merge. The kept cell must hold DOM focus -- otherwise
    the toolbar's mousedown preventDefault leaves focus on <body> after the
    absorbed node is detached."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("refocus")
    _login(page, live_server, "refocus")
    unit = _unit("refocus", "refocus")
    element = _seed(
        unit,
        TableElement,
        [[{"html": ""} for _ in range(2)] for _ in range(2)],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    # Click B (0,1) first -- becomes focusCell and rangeAnchor.
    _cell(page, TABLE_ROOT, 0, 1).click()
    # Shift+click A (0,0) -- range now covers both, anchor stays B, so B (the
    # click-anchor) is the ABSORBED cell after merge: rangeCells sorts by
    # layout position, and the top-left slot (0,0) becomes the survivor.
    _cell(page, TABLE_ROOT, 0, 0).click(modifiers=["Shift"])
    page.locator(f"{TABLE_ROOT} [data-merge]").click()

    focused = page.locator(f"{TABLE_ROOT} td:focus, {TABLE_ROOT} th:focus")
    assert focused.count() == 1
    assert focused.get_attribute("colspan") == "2"


@pytest.mark.django_db(transaction=True)
def test_alt_shift_arrow_extends_and_then_shrinks_the_range(page, live_server):
    """Click (0,0); the FIRST Alt+Shift+ArrowRight already selects TWO slots
    (seed from the anchor AND move in the same keystroke -- seeding alone
    would be a keystroke with no visible effect). A following ArrowLeft
    shrinks the range back to one, proving paintRange re-normalises every
    keystroke instead of only ever growing."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("kbd_range")
    _login(page, live_server, "kbd_range")
    unit = _unit("kbd_range", "kbd-range")
    element = _seed(
        unit,
        TableElement,
        [[{"html": ""} for _ in range(3)] for _ in range(3)],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    page.keyboard.press("Alt+Shift+ArrowRight")
    assert page.locator(f"{TABLE_ROOT} .is-range").count() == 2

    page.keyboard.press("Alt+Shift+ArrowLeft")
    assert page.locator(f"{TABLE_ROOT} .is-range").count() == 1


@pytest.mark.django_db(transaction=True)
def test_alt_shift_arrow_is_a_no_op_with_nothing_focused(page, live_server):
    """No click first: the keystroke must not throw and must not select --
    focusCell is null, so the handler must bail out before touching rangeEnd."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("kbd_noop")
    _login(page, live_server, "kbd_noop")
    unit = _unit("kbd_noop", "kbd-noop")
    element = _seed(
        unit,
        TableElement,
        [[{"html": ""} for _ in range(3)] for _ in range(3)],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    page.keyboard.press("Alt+Shift+ArrowRight")
    assert page.locator(f"{TABLE_ROOT} .is-range").count() == 0
