"""Fill-in table reveal gate, end to end.

Fixtures are TOP-LEVEL (slide-scope) throughout.
"""

import os

import pytest
from playwright.sync_api import expect

from courses.models import FillTableElement
from tests.factories import add_element

# `tests/` has an __init__.py, so these are importable rather than copy-pasted.
# (`_allow_async_unsafe` is NOT -- it is a local autouse fixture in each file.)
from tests.test_e2e_filltable import _INCORRECT
from tests.test_e2e_filltable import _SUCCESS
from tests.test_e2e_filltable import _confirm
from tests.test_e2e_filltable import _summary
from tests.test_e2e_reveal_gate import _gate
from tests.test_e2e_reveal_gate import _login
from tests.test_e2e_reveal_gate import _new_unit
from tests.test_e2e_reveal_gate import _seed_state
from tests.test_e2e_reveal_gate import _text
from tests.test_e2e_reveal_gate import _unit_url

pytestmark = pytest.mark.e2e

# NOTE: `_confirm` and `_summary` are scoped to the FIRST .filltable on the page
# (both are `_table(page).locator(...)`, and `_table` is
# `page.locator(".filltable").first`). Use them ONLY in single-table fixtures --
# tests 21, 22, 24 and 25. Tests 23 and 26 have TWO tables, so the shared
# locators would silently drive the wrong one; that is what _block(...)-scoped
# locators are for. Test 27 has only ONE table and could use them, but stays
# _block-scoped for symmetry with 23 and 26 -- not out of necessity.


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread. Copied from
    # tests/test_e2e_filltable.py:40-45 -- a local fixture, not importable.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


_ANSWER = "4"
# Module-level and mutable. _seed() calls obj.save(), which runs
# FillTableElement._sanitized_data and rewrites cell dicts IN PLACE
# (cell["html"] = sanitize_cell(...), cell["answer"] = a.strip()). Every
# element seeded from _CELLS shares these same dicts, so this is safe only
# because the values above are sanitiser fixed points (idempotent under that
# rewrite). If a test ever needs unsanitised HTML or a padded/pipe-delimited
# answer, make this a zero-arg factory (def _cells(): return [[...]]) instead
# -- otherwise the first save() silently rewrites the fixture for every
# later test in the file.
_CELLS = [[{"kind": "static", "html": "x"}, {"kind": "answer", "answer": _ANSWER}]]


def _filltable(gate=False):
    """An unsaved gated/ungated fill-table with exactly one answer cell."""
    return FillTableElement(data={"cells": _CELLS, "gate": gate})


def _seed(unit, *objs):
    """Attach each concrete element to `unit` as a TOP-LEVEL row, in order.

    Accepts BOTH saved and unsaved concrete elements: _text() and _gate() use
    .objects.create() and arrive saved (the save() below is then a harmless
    no-op UPDATE), while _filltable() returns an unsaved instance that needs
    it. Do not "tidy" the save() away.

    Returns (join_row, concrete_obj) pairs -- test 25 needs the concrete object
    to flip its `gate` mid-test, which a join row alone cannot reach.
    """
    out = []
    for obj in objs:
        obj.save()
        out.append((add_element(unit, obj), obj))  # tests.factories.add_element
    return out


def _block(join_pk):
    return f".lesson-block[data-element-id='{join_pk}']"


def _visible(page, join_pk):
    # Explicit miss-check: a bare querySelector(...).checkVisibility() throws a
    # raw JS TypeError inside Playwright when the block is absent (wrong pk, a
    # callout-nested fixture with no data-element-id, an element that never
    # rendered) -- the least legible form of exactly the fixture mistake the
    # trap list warns about. Fail with a message that names the pk instead.
    sel = _block(join_pk)
    return page.evaluate(
        f'(() => {{ const n = document.querySelector("{sel}");'
        f' if (!n) throw new Error("no .lesson-block for pk {join_pk}");'
        f" return n.checkVisibility(); }})()"
    )


# ---------------------------------------------------------------------------
# 21. A wrong answer keeps the following content hidden
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_wrong_answer_keeps_content_hidden(page, live_server):
    _student, unit = _new_unit("ftg_wrong")  # returns a (student, unit) PAIR
    (table_row, _t), (trailing_row, _tr) = _seed(
        unit, _filltable(gate=True), _text("trailing")
    )
    _login(page, live_server, "ftg_wrong")
    page.goto(_unit_url(live_server, unit))

    inp = page.locator(".filltable__input").first
    inp.fill("nope")
    _confirm(page).click()
    expect(inp).to_have_class(_INCORRECT)  # <- synchronise BEFORE reading the DOM
    assert _visible(page, trailing_row.pk) is False


# ---------------------------------------------------------------------------
# 22. A correct answer reveals -- and the solved table stays on screen
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_correct_answer_reveals(page, live_server):
    _student, unit = _new_unit("ftg_correct")
    (table_row, _t), (trailing_row, _tr) = _seed(
        unit, _filltable(gate=True), _text("trailing")
    )
    _login(page, live_server, "ftg_correct")
    page.goto(_unit_url(live_server, unit))

    inp = page.locator(".filltable__input").first
    inp.fill(_ANSWER)
    _confirm(page).click()
    expect(_summary(page)).to_have_class(_SUCCESS)  # <- synchronise first
    expect(inp).to_be_disabled()
    assert _visible(page, trailing_row.pk) is True
    # The solved table must STAY on screen -- hideWrapper:false. Without it
    # cascadeFrom sets gateWrap.hidden, and app.css:1010 removes the table and its
    # notes entirely. Both Playwright assertions above are visibility-agnostic, so
    # this line is the only behavioural guard on that option.
    assert _visible(page, table_row.pk) is True


# ---------------------------------------------------------------------------
# 23. A chain of two ADJACENT gating tables
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_chained_gates_reveal_in_sequence(page, live_server):
    _student, unit = _new_unit("ftg_chain")
    (table1_row, _t1), (table2_row, _t2), (trailing_row, _tr) = _seed(
        unit, _filltable(gate=True), _filltable(gate=True), _text("trailing")
    )  # ADJACENT: nothing between the two tables
    _login(page, live_server, "ftg_chain")
    page.goto(_unit_url(live_server, unit))

    # solve table 1 (its inputs are the only enabled ones while table 2 is hidden)
    inp1 = page.locator(f"{_block(table1_row.pk)} .filltable__input").first
    inp1.fill(_ANSWER)
    page.locator(f"{_block(table1_row.pk)} .filltable__confirm").click()
    expect(page.locator(f"{_block(table1_row.pk)} .filltable__summary")).to_have_class(
        _SUCCESS
    )

    assert _visible(page, table2_row.pk) is True
    assert _visible(page, trailing_row.pk) is False
    # focus landed IN table 2's first enabled input, not on its wrapper div
    assert (
        page.evaluate("document.activeElement.classList.contains('filltable__input')")
        is True
    )

    inp2 = page.locator(f"{_block(table2_row.pk)} .filltable__input").first
    inp2.fill(_ANSWER)
    page.locator(f"{_block(table2_row.pk)} .filltable__confirm").click()
    expect(page.locator(f"{_block(table2_row.pk)} .filltable__summary")).to_have_class(
        _SUCCESS
    )
    assert _visible(page, trailing_row.pk) is True


# ---------------------------------------------------------------------------
# 24. Reload restores the revealed state
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_reload_restores_the_revealed_state(page, live_server):
    _student, unit = _new_unit("ftg_reload")
    (table_row, _t), (trailing_row, _tr) = _seed(
        unit, _filltable(gate=True), _text("trailing")
    )
    _login(page, live_server, "ftg_reload")
    page.goto(_unit_url(live_server, unit))

    inp = page.locator(".filltable__input").first
    inp.fill(_ANSWER)
    with page.expect_response(  # AWAIT the state POST -- see trap 1
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        _confirm(page).click()
    assert resp_info.value.ok

    page.reload()
    # The restored input is `readonly` (server-rendered), not `disabled` --
    # _filltable_cell.html renders the mine.done branch with readonly, while the
    # live lock() path uses disabled.
    expect(page.locator(".filltable__input").first).to_have_js_property(
        "readOnly", True
    )
    assert _visible(page, trailing_row.pk) is True


# ---------------------------------------------------------------------------
# 25. Pre-tick, single gate: solve UNGATED, then tick `gate`, then reload
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_gate_ticked_after_solving_reveals_on_reload(page, live_server):
    _student, unit = _new_unit("ftg_pretick")
    # seeded UNGATED -- see the fixture note
    (table_row, table_obj), (trailing_row, _tr) = _seed(
        unit, _filltable(gate=False), _text("trailing")
    )
    _login(page, live_server, "ftg_pretick")
    page.goto(_unit_url(live_server, unit))
    inp = page.locator(".filltable__input").first
    inp.fill(_ANSWER)
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        _confirm(page).click()
    assert resp_info.value.ok  # the blob is now stored, table still UNGATED

    # Flip the flag. A JSONField cannot be .update()d key-wise, so rebuild the whole
    # dict -- dropping `cells` here would empty the grid and silently invalidate
    # the test.
    FillTableElement.objects.filter(pk=table_obj.pk).update(
        data={**table_obj.data, "gate": True}
    )

    page.reload()
    assert _visible(page, trailing_row.pk) is True


# ---------------------------------------------------------------------------
# 26. Pre-tick, chained -- the DOCUMENTED limitation (accepted, reload-healed)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_chained_pretick_heals_only_on_reload(page, live_server):
    # NOTE: `student`, not `_student` -- _seed_state needs it.
    student, unit = _new_unit("ftg_prechain")
    (table1_row, _t1), (table2_row, _t2), (trailing_row, _tr) = _seed(
        unit, _filltable(gate=True), _filltable(gate=True), _text("trailing")
    )
    # Table 2 was solved back when both were ungated: seed its blob directly.
    _seed_state(student, unit, {str(table2_row.pk): {"done": True}})
    _login(page, live_server, "ftg_prechain")
    page.goto(_unit_url(live_server, unit))

    # Solve table 1, AWAITING the state POST (trap 1) -- this test reloads, so the
    # expect(summary) pattern used by test 23 is not sufficient here:
    inp1 = page.locator(f"{_block(table1_row.pk)} .filltable__input").first
    inp1.fill(_ANSWER)
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        page.locator(f"{_block(table1_row.pk)} .filltable__confirm").click()
    assert resp_info.value.ok

    # restoreGates broke at table 1, so table 2's cascade never replayed; and
    # table 2 is server-rendered done, so it has no Check button to fire it.
    assert _visible(page, table2_row.pk) is True
    assert _visible(page, trailing_row.pk) is False
    page.reload()
    assert _visible(page, trailing_row.pk) is True


# ---------------------------------------------------------------------------
# 27. An UNGATED table does not cascade
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_ungated_table_does_not_cascade(page, live_server):
    _student, unit = _new_unit("ftg_ungated")
    # the trailing _gate is what makes has_reveal_gate true so reveal.js LOADS.
    # Unpacked in two statements: a single four-pair target list is 99 columns
    # with the def-line indent, and ruff format does NOT parenthesise an
    # assignment target list, so E501 would stand.
    rows = _seed(
        unit,
        _filltable(gate=False),
        _text("ungated-trailing"),
        _gate("Show more"),
        _text("gated-trailing"),
    )
    # Only the first two rows are asserted on -- the _gate and its trailing text
    # exist solely to make has_reveal_gate true. Do not bind them.
    (table_row, _t), (ungated_trailing_row, _ut) = rows[0], rows[1]
    _login(page, live_server, "ftg_ungated")
    page.goto(_unit_url(live_server, unit))

    inp = page.locator(f"{_block(table_row.pk)} .filltable__input").first
    inp.fill(_ANSWER)
    page.locator(f"{_block(table_row.pk)} .filltable__confirm").click()
    expect(page.locator(f"{_block(table_row.pk)} .filltable__summary")).to_have_class(
        _SUCCESS
    )

    # Bind the selector once: inlining _block(...) into the f-string pushes both
    # calls to ~105 columns, and ruff format cannot split a string literal.
    sel = _block(ungated_trailing_row.pk)

    # THIS is the assertion that discriminates the mutant.
    assert (
        page.evaluate(
            f'document.querySelector("{sel}").classList.contains("reveal-shown")'
        )
        is False
    )
    # activeElement is <body> here -- lock() hid the Check button. Assert the
    # negative that actually distinguishes the mutant:
    assert (
        page.evaluate(
            f'!document.querySelector("{sel}").contains(document.activeElement)'
        )
        is True
    )


# ---------------------------------------------------------------------------
# 28. Nested in a CALLOUT: the run stops at the callout's edge
# ---------------------------------------------------------------------------

# The `.callout__children > .callout__child` pair the pre-hide CSS keys on
# (lesson_unit.html:42) and that reveal.js `scopeOf`/`ownWrapper` resolve to.
# Callout children carry NO .lesson-block wrapper (calloutelement.html:24 emits a
# bare .callout__child), so they have no data-element-id and _block()/_visible()
# cannot reach them -- index into this instead.
_CALLOUT_CHILD = ".callout__children > .callout__child"


def _seed_callout(unit, *children):
    """Attach one CalloutElement to `unit`, with `children` nested under it in order.

    `resolved_children()` groups by `parent` alone, so no tab_id is needed (unlike
    the tabs/two-column seeders in tests/test_e2e_reveal_gate.py) -- mirrors
    tests/test_filltable_render.py::_render_callout_with_filltable_child. Each child
    is save()d here for the same reason _seed() does it: _filltable() returns an
    UNSAVED instance while _text() arrives saved.
    """
    from courses.models import CalloutElement
    from courses.models import Element

    callout = CalloutElement.objects.create()
    join = Element.objects.create(unit=unit, content_object=callout)
    for child in children:
        child.save()
        Element.objects.create(unit=unit, content_object=child, parent=join)
    return join


@pytest.mark.django_db(transaction=True)
def test_gate_nested_in_a_callout_scopes_to_that_callout(page, live_server):
    """The motivating real-world shape: a gated table inside a callout.

    The view query, the rendered DOM and the (scope-agnostic) cascade engine each
    have unit coverage; what only a live browser can show is that the cascade walks
    the callout's `.callout__child` run and stops at the callout's edge.
    """
    _student, unit = _new_unit("ftg_callout")
    # No trailing _gate() here, in deliberate contrast to test 27: that fixture's
    # table is UNGATED, so it needed one to make has_reveal_gate true. A GATED
    # table sets has_filltable_gate -- and therefore has_reveal_gate -- from
    # anywhere in the unit, nested included (pinned by tests/test_filltable_
    # context.py::test_has_filltable_gate_flag_when_nested_in_a_callout). The
    # `expect(inside_after).to_be_hidden()` below is what proves it took effect:
    # without the flag neither the pre-hide <style> nor reveal.js ships and the
    # sibling is visible from the start.
    _seed_callout(unit, _filltable(gate=True), _text("<p>inside after</p>"))
    ((outside_row, _o),) = _seed(unit, _text("<p>outside after</p>"))
    _login(page, live_server, "ftg_callout")
    page.goto(_unit_url(live_server, unit))

    inside_after = page.locator(_CALLOUT_CHILD).nth(1)  # [0] is the gated table
    outside_sel = _block(outside_row.pk)  # bound once: inlined it runs past 88 cols

    expect(inside_after).to_be_hidden()
    assert _visible(page, outside_row.pk) is True

    inp = page.locator(f"{_CALLOUT_CHILD} .filltable__input").first
    inp.fill(_ANSWER)
    page.locator(f"{_CALLOUT_CHILD} .filltable__confirm").click()
    expect(page.locator(f"{_CALLOUT_CHILD} .filltable__summary")).to_have_class(
        _SUCCESS
    )

    expect(inside_after).to_be_visible()

    # --- the callout's edge -------------------------------------------------
    # The slide-level block AFTER the whole callout is not behind this gate, so it
    # is visible throughout. Asserted before AND after so the pair cannot pass by
    # the block merely never appearing; it is a real tripwire on the pre-hide CSS
    # (widening lesson_unit.html:42 to slide-level siblings would redden it), but
    # it is NOT the scope discriminator -- a cascade that escaped the callout would
    # only re-reveal an already-visible block. There is no visibility-based
    # discriminator available at all: a leaked run starts at the callout's own
    # .lesson-block and stops at the first slide-level gate wrapper, and the only
    # slide-level blocks the pre-hide CSS hides are the ones AFTER such a wrapper.
    assert _visible(page, outside_row.pk) is True
    # THESE two are what discriminate. A leak leaves its fingerprints in the class
    # the cascade stamps on every node it walks, and in where focus landed.
    assert (
        page.evaluate(
            f'document.querySelector("{outside_sel}")'
            '.classList.contains("reveal-shown")'
        )
        is False
    )
    assert (
        page.evaluate(
            'document.querySelector(".callout__children")'
            ".contains(document.activeElement)"
        )
        is True
    )
