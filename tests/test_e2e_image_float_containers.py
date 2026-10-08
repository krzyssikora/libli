import pytest

from courses.models import BeforeAfterElement
from courses.models import CalloutElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TwoColumnElement
from tests.factories import add_element
from tests.image_float_kit import *

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _container(kind):
    """(saved container, [slot ids in order]). Tabs/two-column ids are read off the
    SAVED instance -- normalize_data() would mint fresh ids at render time."""
    if kind == "callout":
        return CalloutElement.objects.create(kind="note"), [CalloutElement.SLOT_ID]
    if kind == "spoiler":
        return SpoilerElement.objects.create(label="s"), [SpoilerElement.SLOT_ID]
    if kind == "beforeafter":
        return BeforeAfterElement.objects.create(), list(BeforeAfterElement.SLOT_IDS)
    if kind in ("tabs", "carousel"):
        data = TabsElement.default_data()
        data["display"] = (
            "carousel" if kind == "carousel" else TabsElement.DEFAULT_DISPLAY
        )
        obj = TabsElement.objects.create(data=data)
        return obj, [t["id"] for t in obj.data["tabs"]]
    obj = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    return obj, [c["id"] for c in obj.data["columns"]]


def _fill(unit, join, slot, children):
    for child in children:
        Element.objects.create(
            unit=unit, content_object=child, parent=join, tab_id=slot
        )


def seed_container(kind, slug):
    """A container whose FIRST list holds [tall floated image, short text], then a
    top-level text block. Returns (owner, unit, selector of the container's block)."""
    owner = make_pa_user(f"pa-{slug}")
    course, unit = seed_unit(owner, slug)
    obj, slots = _container(kind)
    join = add_element(unit, obj)
    _fill(unit, join, slots[0], [image(course, px=(300, 600)), text("Krótko.")])
    add_element(unit, text())
    return owner, unit, f'[data-element-id="{join.pk}"]'


def seed_stacked(kind, slug):
    """List 1 ENDS with the floated image; list 2 holds one text child -- so a leak
    from list 1 would pull list 2's label/first child up beside the image."""
    owner = make_pa_user(f"pa-{slug}")
    course, unit = seed_unit(owner, slug)
    obj, slots = _container(kind)
    join = add_element(unit, obj)
    _fill(unit, join, slots[0], [text("Krótko."), image(course, px=(300, 600))])
    _fill(unit, join, slots[1], [text("Druga lista.")])
    return owner, unit, f'[data-element-id="{join.pk}"]'


CONTAINERS = [
    "callout",
    "tabs",
    "carousel",
    "twocolumn",
    "spoiler",
    "beforeafter",
]  # carousel = tabs, display="carousel"


@pytest.mark.parametrize("kind", CONTAINERS)
def test_float_is_contained_by_its_container(page, live_server, kind):
    owner, unit, container_sel = seed_container(
        kind, "fl-c-" + kind
    )  # helper in this file
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), DESKTOP)
    if kind == "spoiler":
        page.locator(".spoiler__toggle").click()
    img = rect(page, f"{container_sel} .el--image--float img")
    assert rect(page, container_sel)["bottom"] >= img["bottom"] - 1.5
    nxt = rect(page, "[data-element-id] + [data-element-id] .el--text p")
    assert nxt["top"] >= img["bottom"] - 1.5


# .ba--dead shares html:not(.ba-js)'s declarations by grouped selector
# (beforeafter.js), so the no-JS case covers it. "carousel" = tabs with
# data display="carousel" (idiom: tests/test_e2e_tabs.py's tabs fixture).
@pytest.mark.parametrize("state", ["nojs", "print"])
@pytest.mark.parametrize("kind", ["tabs", "carousel", "beforeafter"])
def test_float_at_end_of_a_non_last_list_stays_in_it(browser, live_server, kind, state):
    # Tabs without JS and in print stack every section; before/after shows both sides.
    owner, unit, sel = seed_stacked(
        kind, f"fl-s-{kind}-{state}"
    )  # image is LAST child of list 1
    ctx = browser.new_context(java_script_enabled=(state != "nojs"))
    try:
        page = ctx.new_page()
        login(page, live_server, owner.username)
        open_page(page, unit_url(live_server, unit), DESKTOP)
        if state == "print":
            print_mode(page)
        _assert_next_list_below(page, kind, sel)
    finally:
        ctx.close()


def _assert_next_list_below(page, kind, sel):
    img = rect(page, f"{sel} .el--image--float img")
    second_list = (
        ".tabs__section:nth-child(2)"
        if kind in ("tabs", "carousel")
        else '.ba__panel[data-ba-side="after"]'
    )
    assert rect(page, second_list)["top"] >= img["bottom"] - 1.5
    first_child = f"{second_list} :is(.tabs__child, .ba__child)"
    assert rect(page, first_child)["top"] >= img["bottom"] - 1.5


@pytest.mark.parametrize(
    "vp,medium",
    [(PHONE, "screen"), (DESKTOP, "screen"), (DESKTOP, "print")],
    ids=["phone-screen", "desktop-screen", "desktop-print"],
)
def test_top_alignment_and_no_trailing_space_in_a_callout(
    page, live_server, vp, medium
):
    owner = make_pa_user("pa-fl-callout")
    course, unit = seed_unit(owner, "fl-callout")

    def callout(children):
        join = add_element(unit, CalloutElement.objects.create(kind="note"))
        for c in children:
            Element.objects.create(
                unit=unit, content_object=c, parent=join, tab_id=CalloutElement.SLOT_ID
            )
        return join

    a = callout([image(course, px=(300, 200)), text()])  # image first: top alignment
    b = callout([text("Krótko."), image(course, px=(300, 200))])  # float is LAST child
    c = callout(
        [text("Krótko."), image(course, px=(300, 200), float_right=False)]
    )  # twin
    # Two-column, floated image NOT first in its column: the (0,4,0) `+` rule must lose.
    tc = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    tc_join = add_element(unit, tc)
    col_id = tc.data["columns"][0]["id"]
    for child in (text("Pierwszy."), image(course, px=(300, 200)), text()):
        Element.objects.create(
            unit=unit, content_object=child, parent=tc_join, tab_id=col_id
        )
    login(page, live_server, owner.username)
    open_page(page, unit_url(live_server, unit), vp)
    if medium == "print":
        print_mode(page)

    img_a = rect(page, f'[data-element-id="{a.pk}"] .el--image img')
    para_a = rect(page, f'[data-element-id="{a.pk}"] .callout__child .el--text p')
    assert abs(img_a["top"] - para_a["top"]) <= 2 + 1.5, (img_a, para_a)

    def trailing(join):
        box = rect(page, f'[data-element-id="{join.pk}"] .callout')
        img = rect(page, f'[data-element-id="{join.pk}"] .el--image img')
        return box["bottom"] - img["bottom"]

    assert trailing(b) <= trailing(c) + 1.5, (trailing(b), trailing(c))

    tc_img = rect(page, f'[data-element-id="{tc_join.pk}"] .el--image img')
    tc_next = rect(
        page,
        f'[data-element-id="{tc_join.pk}"] .twocolumn__child:last-child .el--text p',
    )
    assert abs(tc_img["top"] - tc_next["top"]) <= 2 + 1.5, (tc_img, tc_next)
