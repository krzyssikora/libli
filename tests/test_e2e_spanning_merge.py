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
