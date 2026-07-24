"""Playwright e2e: over-wide grids/tables scroll in their own box, never the page.

Regression guard for the report against /courses/<slug>/u/<pk>/ — a multi-select
grid with long column labels ("lewostronnie otwarty") pushed the whole document
sideways, so on a phone part of the grid was simply unreachable.

Root cause is NOT a missing wrapper: .multigrid-scroll / .choicegrid-scroll have
carried `overflow-x: auto` since they shipped. The wrapper sits inside the
question's <form><fieldset>, and a fieldset's UA style is
`min-inline-size: min-content` — so the fieldset inflated to the grid's
max-content width and the scroll box, sized by its parent, never had an overflow
to scroll. Table elements (.el--table) sit in no fieldset and were always fine;
they are asserted here so the reset can't regress them.

Measured, not eyeballed: the assertions compare scrollWidth vs clientWidth at a
phone viewport. Marked e2e (excluded by default; run with -m e2e).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

# Phone-width viewport: the reported "part of it is not visible at all" case.
PHONE = {"width": 390, "height": 780}

# Long, unbreakable-ish labels straight from the reported unit (PL interval terms).
COLUMN_LABELS = ["otwarty", "domknięty", "ograniczony", "lewostronnie otwarty"]
STATEMENTS = ["(2,3)", "⟨4, 7⟩", "(4, +∞)", "⟨-∞, 7)"]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_wide_unit(username, slug):
    """A lesson unit holding both over-wide surfaces: a multi-select grid with
    long column labels, and a 10-column table element."""
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import MultiGridColumn
    from courses.models import MultiGridQuestionElement
    from courses.models import MultiGridRow
    from courses.models import TableElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )

    q = MultiGridQuestionElement.objects.create(stem="<p>Classify each interval</p>")
    cols = [MultiGridColumn.objects.create(question=q, label=x) for x in COLUMN_LABELS]
    for s in STATEMENTS:
        row = MultiGridRow.objects.create(question=q, statement=s)
        row.correct_columns.add(cols[0])
    Element.objects.create(unit=unit, content_object=q)

    # 10 columns of non-wrapping-ish text: wider than a 390px column by a mile.
    cells = [
        [
            {"html": f"r{r}c{c} wartość", "halign": "left", "valign": "top"}
            for c in range(10)
        ]
        for r in range(3)
    ]
    t = TableElement.objects.create(data={"cells": cells, "border": "grid"})
    Element.objects.create(unit=unit, content_object=t)

    return course, unit


# Each entry: (human name, wrapper selector, inner table selector).
SURFACES = [
    ("multi-select grid", ".multigrid-scroll", "table.multigrid"),
    ("table element", ".el--table__scroll", "table"),
]

MEASURE = """
([boxSel, innerSel]) => {
  const box = document.querySelector(boxSel);
  if (!box) return null;
  const inner = box.querySelector(innerSel);
  return {
    client: box.clientWidth,
    scroll: box.scrollWidth,
    right: Math.round(box.getBoundingClientRect().right),
    inner: inner ? Math.round(inner.getBoundingClientRect().width) : null,
  };
}
"""


@pytest.mark.django_db(transaction=True)
def test_wide_surfaces_scroll_in_their_own_box_not_the_page(page, live_server):
    """At phone width, each over-wide surface must be an actual scroll container
    (scrollWidth > clientWidth) and the document must not scroll sideways."""
    course, unit = _seed_wide_unit("wide_scroll", "wide-scroll")
    _login(page, live_server, "wide_scroll")
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector("[data-question]")

    failures = []
    for name, wrapper_sel, inner_sel in SURFACES:
        box = page.evaluate(MEASURE, [wrapper_sel, inner_sel])
        assert box is not None, f"{name}: no {wrapper_sel} wrapper rendered"
        assert box["inner"], f"{name}: no {inner_sel} inside {wrapper_sel}"

        # Precondition: this surface really is over-wide at phone width, so a
        # green result means "it scrolls", never "it happened to fit".
        assert box["inner"] > PHONE["width"], (
            f"{name}: seed is not wide enough to exercise the scroll "
            f"(table {box['inner']}px at {PHONE['width']}px viewport)"
        )

        # The wrapper must stay inside the viewport...
        if box["right"] > PHONE["width"]:
            failures.append(
                f"{name}: {wrapper_sel} extends to x={box['right']} "
                f"(past the {PHONE['width']}px viewport)"
            )
        # ...and it must be the thing that scrolls.
        if box["scroll"] <= box["client"]:
            failures.append(
                f"{name}: {wrapper_sel} is not scrolling "
                f"(scrollWidth {box['scroll']} <= clientWidth {box['client']}); "
                "it was inflated to content width instead"
            )

    doc = page.evaluate(
        "() => ({client: document.documentElement.clientWidth,"
        " scroll: document.documentElement.scrollWidth})"
    )
    if doc["scroll"] > doc["client"]:
        failures.append(
            f"document scrolls horizontally: scrollWidth {doc['scroll']} > "
            f"clientWidth {doc['client']} — content is off-screen on mobile"
        )

    assert not failures, "Horizontal overflow escaped its scroll box:\n  " + (
        "\n  ".join(failures)
    )


@pytest.mark.django_db(transaction=True)
def test_wide_grid_scrolls_to_reveal_its_last_column(page, live_server):
    """The scroll must actually reach the far edge: after scrolling the grid box
    fully right, the last column's header is inside the viewport."""
    course, unit = _seed_wide_unit("wide_reach", "wide-reach")
    _login(page, live_server, "wide_reach")
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".multigrid-scroll")

    last_header = page.locator("table.multigrid thead th").last
    assert last_header.inner_text().strip() == COLUMN_LABELS[-1]

    page.evaluate(
        "() => { const b = document.querySelector('.multigrid-scroll');"
        " b.scrollLeft = b.scrollWidth; }"
    )
    page.wait_for_timeout(100)

    right = page.evaluate(
        "() => Math.round(document.querySelector('table.multigrid thead th:last-child')"
        ".getBoundingClientRect().right)"
    )
    assert right <= PHONE["width"], (
        f"last column still off-screen after scrolling right (right={right} > "
        f"{PHONE['width']}) — the grid cannot be read on a phone"
    )
