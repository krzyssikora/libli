"""After saving, the element the author just worked on has to still be on screen.

editor.js anchors its post-save scroll on ``form.closest(".el-row[data-element]")``.
A CREATE has no such row of its own -- there is no pk until the save lands -- so that
lookup answers with the enclosing CONTAINER's row, or with nothing at all for a
top-level add. Neither is the element the author just wrote:

* a container that already holds a run of children puts the new one far below the
  container's own row, which is what gets aligned;
* a top-level create finds no ``.el-row[data-element]`` ancestor whatsoever, so
  nothing scrolls in either pane.

Both shapes are MEASURED below rather than asserted loosely, because a container with
ONE child is in view either way -- a test built on that shape passes against a build
that scrolls to the wrong place entirely.
"""

import os

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _seed(username, *, children):
    """A callout in the MIDDLE of a long unit, holding `children` elements already.

    Mid-unit and a POPULATED callout are both load-bearing. A container at the top of
    a short unit leaves everything near scroll-top, where it is in view whether or not
    anything scrolled to it; a callout holding one child leaves the new sibling within
    a row of the container's own row, which is what the unfixed build aligns to. With
    a run of children the two answers are ~950px apart in a 339px pane.
    """
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import TextElement
    from tests.conftest import _pa_user
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    pa = _pa_user(username)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )

    def text(order, body, **kw):
        return Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=body),
            order=order,
            **kw,
        )

    for i in range(8):
        text(i, f"<p>before {i}</p>")
    callout = CalloutElement.objects.create(body="<p>callout body</p>")
    callout_join = Element.objects.create(unit=unit, content_object=callout, order=8)
    for i in range(children):
        text(i, f"<p>child {i}</p>", parent=callout_join, tab_id=CalloutElement.SLOT_ID)
    for i in range(9, 17):
        text(i, f"<p>after {i}</p>")
    return unit, callout_join


_IN_VIEW = """
  (sel) => {
    const el = document.querySelector(sel);
    if (!el) return false;
    const body = el.closest('.pane-body');
    const b = body.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return r.top < b.bottom && r.bottom > b.top;
  }
"""


def _add_and_save(page, menu):
    """Open a blank text element from `menu`, fill it, save it."""
    menu.locator("button[data-add-toggle]").click()
    menu.locator('button[data-add-type="text"]').click()
    page.wait_for_selector(
        '[data-edit-slot] form[data-op="element-save"]', state="attached"
    )
    # Type into the RTE surface, not the textarea: the editor hides the source field
    # and mirrors the contenteditable back into it on input.
    page.locator("form[data-op='element-save'] .rte-surface").fill("brand new child")
    # Clicking Save scrolls the pane down to reach the button -- exactly what the
    # author does by hand, and what strands them once the form collapses.
    page.locator("form[data-op='element-save'] button[type='submit']").click()
    page.wait_for_selector('form[data-op="element-save"]', state="detached")


def _assert_in_view(page, pk):
    # wait_for_function, not a sleep: scrollPreviewTo animates and re-aligns as the
    # preview's async content settles, so the pass condition is "arrives", not
    # "has arrived by millisecond N".
    page.wait_for_function(
        _IN_VIEW, arg=f'li.el-row[data-element="{pk}"]', timeout=5000
    )
    page.wait_for_function(
        _IN_VIEW, arg=f'.prev-el[data-element-id="{pk}"]', timeout=5000
    )


@pytest.mark.django_db(transaction=True)
def test_a_new_element_saved_inside_a_busy_callout_stays_in_view(page, live_server):
    from courses.models import Element
    from tests.conftest import _editor_login
    from tests.conftest import _editor_url

    unit, callout_join = _seed("pa_busy_callout", children=10)
    _editor_login(page, live_server, "pa_busy_callout")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector("[data-add-menu]", state="attached")

    _add_and_save(
        page, page.locator(f'[data-add-menu][data-parent="{callout_join.pk}"]')
    )

    _assert_in_view(page, Element.objects.filter(parent=callout_join).latest("pk").pk)


@pytest.mark.django_db(transaction=True)
def test_a_new_top_level_element_stays_in_view_after_saving(page, live_server):
    """The un-nested add has no container row to fall back on at all."""
    from courses.models import Element
    from tests.conftest import _editor_login
    from tests.conftest import _editor_url

    unit, _callout_join = _seed("pa_top_level", children=0)
    _editor_login(page, live_server, "pa_top_level")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector("[data-add-menu]", state="attached")

    _add_and_save(page, page.locator("[data-add-menu]:not([data-parent])").first)

    saved = Element.objects.filter(unit=unit, parent__isnull=True).latest("pk")
    _assert_in_view(page, saved.pk)
