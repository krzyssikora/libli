"""Playwright e2e for the collapsible course outline (spec T6-T19).

Real browser gestures only. Marked `e2e` (run with -m e2e).

FOLD ASSERTIONS USE checkVisibility(), NEVER to_be_hidden(): Playwright's
visibility contract is "non-empty bounding box and not visibility:hidden", and a
closed <details> keeps a STALE non-zero rect — this repo measured exactly that in
tests/test_e2e_unit_nav.py. Worse, it is state-dependent: content never laid out
may report 0x0 and pass, while the same assertion after a real fold gesture
fails. to_be_hidden() IS correct for the tag filter's [hidden] rows, which are
display:none, and is used for exactly those.
"""

import json
import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _course_with_two_chapters(username="outliner"):
    """part > (chapter A > unit A1) + (chapter B > unit B1), plus a depth-0 unit.

    Every container holds a visible unit, or build_outline's pruning drops it
    before the template ever sees it. The depth-0 unit pins the mixed shape:
    units and containers coexist at the same depth, so "top level open" cannot
    mean "show only containers".
    """
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username=username,
        email=f"{username}@test.example.com",
        password=TEST_PASSWORD,
    )
    course = CourseFactory(title="Algebra")
    Enrollment.objects.create(student=user, course=course)
    part = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    chap_a = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Chapter A"
    )
    chap_b = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Chapter B"
    )
    unit_a = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_a, title="Unit A1"
    )
    unit_b = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_b, title="Unit B1"
    )
    root_unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Root Unit"
    )
    return {
        "user": user,
        "course": course,
        "part": part,
        "chap_a": chap_a,
        "chap_b": chap_b,
        "unit_a": unit_a,
        "unit_b": unit_b,
        "root_unit": root_unit,
    }


def _title_sel(node_pk):
    """The clickable title span of ONE group.

    `[data-node='N'] .outline-node__title` is a descendant selector, and a
    container's <details> contains every descendant group's title too — on a part
    it resolves to three spans and .click() raises a strict-mode violation.
    Scoping through `> summary` keeps it to exactly one, at any depth.
    """
    return f"[data-node='{node_pk}'] > summary .outline-node__title"


def _visible(page, selector):
    """checkVisibility() — see the module docstring for why not to_be_hidden()."""
    return page.evaluate(
        "sel => { const el = document.querySelector(sel);"
        "         return !!el && el.checkVisibility(); }",
        selector,
    )


def _is_open(page, node_pk):
    return page.evaluate(
        "pk => document.querySelector(`[data-node='${pk}']`).open", str(node_pk)
    )


def _has_open_attr(page, node_pk):
    """Attribute read, for contexts where page.evaluate is unavailable (JS off)."""
    return page.locator(f"[data-node='{node_pk}']").get_attribute("open") is not None


def _stored(page):
    return page.evaluate(
        "() => { const k = Object.keys(localStorage)"
        ".find(x => x.startsWith('libli_outline_open:'));"
        "        return k ? localStorage.getItem(k) : null; }"
    )


def _wait_for_write(page):
    """Persistence runs inside setTimeout(write, 0) because <summary> activation
    is post-dispatch. Any reload that races it fails intermittently on a CORRECT
    build — the worst thing to debug a mutant against."""
    page.wait_for_function(
        "() => Object.keys(localStorage).some("
        "  k => k.startsWith('libli_outline_open:'))"
    )


@pytest.mark.django_db(transaction=True)
def test_first_visit_opens_depth0_only(page, live_server):
    """T6 + T7. Mutant: render every <details> open."""
    f = _course_with_two_chapters("t7")
    _login(page, live_server, "t7")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    # The attribute half is what actually pins D1; a visibility-only assertion
    # also passes under a stray display:none.
    assert _is_open(page, f["part"].pk) is True
    assert _is_open(page, f["chap_a"].pk) is False

    assert _visible(page, f"[data-node='{f['chap_a'].pk}'] > summary")
    assert not _visible(page, f"#node-{f['unit_a'].pk}")
    # Mixed shape: a depth-0 unit row is an ordinary row, always visible.
    assert _visible(page, f"#node-{f['root_unit'].pk}")

    # T6: the computed ACCESSIBLE NAME, not DOM text — a text assertion would
    # merely duplicate the render-tier T3. Do NOT use get_by_role("button", ...):
    # <summary> has no entry in Playwright's implicit-role table, so that locator
    # resolves to ZERO elements and fails on a correct build. Nor
    # page.accessibility.snapshot(), which no longer exists in this version.
    # Only the negative assertion discriminates: under the T6 mutant the name
    # becomes "Chapter A 0/1 required Start fresh", which still matches
    # ^Chapter A. The positive one is a liveness check that the locator resolves
    # and the name is computed at all.
    summary = page.locator(f"[data-node='{f['chap_a'].pk}'] > summary")
    expect(summary).to_have_accessible_name(re.compile(r"^Chapter A"))
    expect(summary).not_to_have_accessible_name(re.compile("Start fresh"))


@pytest.mark.django_db(transaction=True)
def test_fold_state_survives_a_round_trip(page, live_server):
    """T8. Mutant: take the snapshot SYNCHRONOUSLY inside the click handler
    instead of inside setTimeout(..., 0) — it reads the pre-click state, so the
    newly-opened chapter is absent from the stored `open` array."""
    f = _course_with_two_chapters("t8")
    _login(page, live_server, "t8")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    # Click the TITLE SPAN, not the summary's padding: that click target is what
    # falsifies an e.target.matches() implementation.
    page.locator(_title_sel(f["chap_a"].pk)).click()
    expect(page.locator(f"#node-{f['unit_a'].pk}")).to_be_visible()
    _wait_for_write(page)

    # Assert on the "open" ARRAY, not on the raw JSON string: under the mutant
    # chap_a's pk lands in "closed", so its digits are still in the blob and a
    # substring test passes. (It is pk-fragile too — "4" is in '["14"]'.)
    # The round
    # trip below can be served from Chromium's back/forward cache — nothing in
    # this project sends Cache-Control: no-store — which restores the live DOM
    # WITHOUT re-running outline_tree.js, leaving the chapter open regardless of
    # what was persisted and turning the mutant green.
    assert str(f["chap_a"].pk) in json.loads(_stored(page))["open"]

    page.locator(f"#node-{f['unit_a'].pk} a.outline-unit").click()
    page.wait_for_url(f"**/u/{f['unit_a'].pk}/")
    page.go_back()
    page.reload()  # defeats bfcache: forces a real re-run of the restore path

    assert _is_open(page, f["chap_a"].pk) is True
    assert _is_open(page, f["chap_b"].pk) is False


@pytest.mark.django_db(transaction=True)
def test_expand_all_then_collapse_all(page, live_server):
    """T9. Mutant: make write() a no-op in the toggle-all click handler — the
    reload assertion below goes red. (The separate "label set inline in the click
    handler instead of via syncLabel" mutant belongs to T14, not here.)"""
    f = _course_with_two_chapters("t9")
    _login(page, live_server, "t9")
    page.goto(f"{live_server.url}/courses/{f['course'].slug}/")

    button = page.locator("[data-outline-toggle-all]")
    expect(button).to_be_visible()
    expect(button).to_have_text("Expand all")

    button.click()
    expect(page.locator(f"#node-{f['unit_a'].pk}")).to_be_visible()
    expect(page.locator(f"#node-{f['unit_b'].pk}")).to_be_visible()
    expect(button).to_have_text("Collapse all")

    _wait_for_write(page)
    page.reload()
    assert _is_open(page, f["chap_a"].pk) is True

    page.locator("[data-outline-toggle-all]").click()
    # Collapse all folds depth 0 too.
    assert _is_open(page, f["part"].pk) is False
