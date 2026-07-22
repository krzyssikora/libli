"""The headline slice-1 gate: opening a SPANNING table and saving it with zero
edits must not change its structure.

Before this slice, saving a spanning table -- even untouched -- stripped every
span and header flag, because the editor templates never emitted them and
neither serialize() read them back. The two fixtures go RED for DIFFERENT
reasons, which is expected rather than a harness fault:

  * `table`      -> fails the SUCCESS assertion (TableElementForm rejected the
                    ragged grid with "All table rows must have the same number
                    of cells")
  * `fill_table` -> passes SUCCESS, fails the STRUCTURE assertion (saved
                    "successfully" having silently dropped the spans)
"""

import os

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _structure(cells):
    """The signal this test guards: geometry and kind, never cell html."""
    return [
        [
            (
                c.get("colspan", 1),
                c.get("rowspan", 1),
                bool(c.get("header")),
                c.get("kind"),
            )
            for c in row
        ]
        for row in cells
    ]


# Plain-text cells only: html round-trips through contenteditable and the
# sanitiser, so markup would make this flap for a reason unrelated to spans.
TABLE_CELLS = [
    [{"html": "top", "colspan": 3, "header": True}],
    [{"html": "a", "rowspan": 2}, {"html": "b"}, {"html": "c"}],
    [{"html": "d"}, {"html": "e"}],
]

# TWO non-blank answer cells deliberately: FillTableElementForm rejects a grid
# with no answer cells or any blank one, so a static-only fixture would fail
# the SUCCESS assertion for a third, misleading reason.
FILL_CELLS = [
    [{"kind": "static", "html": "top", "colspan": 3, "header": True}],
    [
        {"kind": "static", "html": "a", "rowspan": 2},
        {"kind": "static", "html": "b"},
        {"kind": "answer", "answer": "42"},
    ],
    [{"kind": "static", "html": "d"}, {"kind": "answer", "answer": "7"}],
]


def _seed(unit, model, cells, **extra):
    from django.contrib.contenttypes.models import ContentType

    from courses.models import Element

    concrete = model.objects.create(
        data=model.normalize_data({"cells": cells, **extra})
    )
    return Element.objects.create(
        unit=unit,
        order=0,
        content_type=ContentType.objects.get_for_model(model),
        object_id=concrete.pk,
    )


# ---- editor helpers -------------------------------------------------------
#
# test_e2e_table_editor.py's _reopen/_save CANNOT be reused here, for two
# reasons, and both would show up as a bare 30s Playwright timeout:
#
#  1. They wait on "[data-edit-slot] [data-table-editor]". The fill-table
#     editor's root is [data-filltable-editor] -- data-table-editor never
#     appears in a fill-table edit slot -- so every fill-table case would hang.
#  2. _save waits for the editor to DETACH. On a REJECTED save the form
#     re-renders inside the slot and never detaches, so the helper times out
#     before the test can assert anything. This suite's whole point is to
#     distinguish "saved" from "rejected", so it needs a save that survives
#     both outcomes.

TABLE_ROOT = "[data-edit-slot] [data-table-editor]"
FILL_ROOT = "[data-edit-slot] [data-filltable-editor]"


def _reopen(page, live_server, unit, element, root):
    from tests.test_e2e_table_editor import _editor_url

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(f"[data-element='{element.pk}'] .el-act-edit").click()
    page.wait_for_selector(root)


def _save_and_report(page, root):
    """Click Save and return True iff the POST was accepted.

    Reads the HTTP STATUS, because that is the only reliable signal here:
    `element_save` answers a rejected save with 422 and editor.js swaps the
    re-rendered form back into the slot, and NEITHER editor partial renders
    any error markup (there is no `.field-error` node anywhere in
    _edit_table.html / _edit_filltable.html / _host_form.html). Waiting on
    error markup -- or on the editor detaching -- would hang for the full
    Playwright timeout on exactly the rejected path this helper exists to
    detect."""
    with page.expect_response(
        lambda r: "/build/element/save/" in r.url and r.request.method == "POST"
    ) as info:
        page.locator(
            "[data-edit-slot] .editor-form__actions button[type='submit']"
        ).click()
    if info.value.status != 200:
        return False
    page.wait_for_selector(root, state="detached")
    return True


@pytest.mark.django_db(transaction=True)
def test_spanning_table_survives_a_zero_edit_save(page, live_server):
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("span_tbl")
    _login(page, live_server, "span_tbl")
    unit = _unit("span_tbl", "span-tbl")
    element = _seed(unit, TableElement, TABLE_CELLS, header_row=True)
    before = _structure(
        TableElement.objects.get(pk=element.object_id).normalized_data["cells"]
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    saved = _save_and_report(page, TABLE_ROOT)

    # (1) the save actually succeeded -- without this, the comparison below is
    # satisfied vacuously by a rejected POST that wrote nothing.
    assert saved, "save was rejected"

    after = _structure(
        TableElement.objects.get(pk=element.object_id).normalized_data["cells"]
    )
    assert after == before


@pytest.mark.django_db(transaction=True)
def test_spanning_fill_table_survives_a_zero_edit_save(page, live_server):
    from courses.models import FillTableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("span_fill")
    _login(page, live_server, "span_fill")
    unit = _unit("span_fill", "span-fill")
    element = _seed(unit, FillTableElement, FILL_CELLS, header_row=True)
    before = _structure(
        FillTableElement.objects.get(pk=element.object_id).normalized_data["cells"]
    )

    _reopen(page, live_server, unit, element, FILL_ROOT)
    saved = _save_and_report(page, FILL_ROOT)

    assert saved, "save was rejected"

    after = _structure(
        FillTableElement.objects.get(pk=element.object_id).normalized_data["cells"]
    )
    assert after == before


@pytest.mark.django_db(transaction=True)
def test_spanning_grid_gets_a_layout_width_control_strip(page, live_server):
    """Row 0 is one colspan=3 cell, so the OLD colCount() (row 0's CELL count)
    would emit ONE handle pair for a 3-column layout, leaving every handle
    under the wrong column."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("strip")
    _login(page, live_server, "strip")
    unit = _unit("strip", "strip")
    element = _seed(unit, TableElement, [[{"colspan": 3, "html": "t"}], [{}, {}, {}]])

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    assert page.locator(f"{TABLE_ROOT} [data-col-insert]").count() == 3


@pytest.mark.django_db(transaction=True)
def test_plain_table_stores_no_span_or_header_keys(page, live_server):
    """A table with no merges must serialize exactly as it did before this
    feature existed -- no colspan, no rowspan, no header key, anywhere."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("plainkeys")
    _login(page, live_server, "plainkeys")
    unit = _unit("plainkeys", "plainkeys")
    element = _seed(
        unit,
        TableElement,
        [[{"html": "a"}, {"html": "b"}], [{"html": "c"}, {"html": "d"}]],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"

    cells = TableElement.objects.get(pk=element.object_id).normalized_data["cells"]
    for row in cells:
        for c in row:
            assert "colspan" not in c
            assert "rowspan" not in c
            assert "header" not in c
