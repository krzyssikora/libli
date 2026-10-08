import pytest

from tests.image_float_kit import *

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]
SHAPE = [lambda c: image(c, px=(300, 220)), lambda c: text(), lambda c: text()]


def _block(join):
    return f'.lesson-block[data-element-id="{join.pk}"]'


def _float(page, join):
    return page.locator(_block(join)).evaluate("e => getComputedStyle(e).float")


# Tall image: both two-line paragraphs sit well inside its height, so paragraph 2's
# top-anchored handle is far above the image's bottom-anchored one -- clear of the
# spec's accepted "second paragraph lands at the image's bottom" edge (D8).
RAIL_SHAPE = [lambda c: image(c, px=(300, 600)), lambda c: text(), lambda c: text()]


def test_rail_handles_do_not_intersect_and_pop_opens_at_handle(page, live_server):
    """D8. Short-image case (spec: measured, not asserted): run once with
    image(px=(300, 60)) and record here the two handles' vertical gap in px --
    measured 2026-10-08 at 1300px: the image renders 32px tall, shorter than the 36px
    handle, so its bottom-anchored handle (260.6-296.5) OVERLAPS paragraph 1's
    top-anchored one (264.2-300.1) by 32.4px (gap -32.4); paragraph 2's handle clears
    it by 55.6px. Accepted limit (spec D8: images under ~2 handle heights)."""
    course, unit, joins, st = seed_student_lesson("fn-rail", "fn_rail", RAIL_SHAPE)
    for j in joins:
        note(st, unit, j)
    login(page, live_server, "fn_rail")
    open_page(page, unit_url(live_server, unit), DESKTOP)
    page.wait_for_selector("html.notes-js")
    img_h = rect(page, f"{_block(joins[0])} .block-notes__handle")
    img_box = rect(page, f"{_block(joins[0])} img")
    p2_top = rect(page, f"{_block(joins[2])} .el--text p")["top"]
    assert img_box["bottom"] - p2_top > 80, (
        "fixture, not code: paragraph 2 must start well above the image's bottom "
        f"(gap {img_box['bottom'] - p2_top:.0f}px) -- lengthen the image"
    )
    for j in joins[1:]:
        assert not boxes_intersect(
            img_h, rect(page, f"{_block(j)} .block-notes__handle")
        )
    open_notes(page, joins[0])
    pop = rect(page, f"{_block(joins[0])} .block-notes__pop")
    handle = rect(page, f"{_block(joins[0])} .block-notes__handle")
    assert abs(pop["top"] - handle["top"]) < 2, (pop, handle)
    assert _float(page, joins[0]) == "right"  # rail: open notes never un-float


def test_open_pop_beats_the_sticky_footer(page, live_server):
    lead = [lambda c: text() for _ in range(25)]  # page must scroll
    course, unit, joins, st = seed_student_lesson(
        "fn-foot", "fn_foot", lead + SHAPE + [lambda c: text("Ostatni.")]
    )
    img_join, plain_join = joins[25], joins[12]
    note(st, unit, img_join)
    note(st, unit, plain_join)
    login(page, live_server, "fn_foot")
    open_page(page, unit_url(live_server, unit), DESKTOP)
    page.wait_for_selector("html.notes-js")
    for j in (img_join, plain_join):
        handle = f"{_block(j)} .block-notes__handle"
        # Put the handle near the viewport bottom so the opened pop meets .unit-foot.
        page.evaluate(
            """(sel) => { const h = document.querySelector(sel);
                 const top = h.getBoundingClientRect().top;
                 window.scrollBy(0, top - innerHeight + 140); }""",
            handle,
        )
        open_notes(page, j)
        pop_r = rect(page, f"{_block(j)} .block-notes__pop")
        assert boxes_intersect(pop_r, rect(page, ".unit-foot")), (
            "fixture: the open pop must overlap .unit-foot, or this proves nothing"
        )
        hit = page.evaluate(
            """(sel) => { const p = document.querySelector(sel).getBoundingClientRect();
                 const y = Math.min(p.bottom - 4, innerHeight - 4);
                 const e = document.elementFromPoint(p.left + p.width / 2, y);
                 return !!(e && e.closest(sel)); }""",
            f"{_block(j)} .block-notes__pop",
        )
        assert hit, f"block {j.pk}: its pop is painted under something (.unit-foot?)"
        page.locator(handle).click()  # close before the next block


def test_below_rail_open_notes_unfloat_to_an_unflagged_small(page, live_server):
    course, unit, joins, st = seed_student_lesson("fn-phone", "fn_phone", SHAPE)
    note(st, unit, joins[0])
    _c2, twin, _j2, _s2 = seed_student_lesson(
        "fn-phone-twin",
        "fn_phone_twin",
        [lambda c: image(c, px=(300, 220), float_right=False), lambda c: text()],
    )
    login(page, live_server, "fn_phone")
    open_page(page, unit_url(live_server, unit), PHONE)
    open_notes(page, joins[0])
    assert _float(page, joins[0]) == "none"
    pop = rect(page, f"{_block(joins[0])} .block-notes__pop")
    col = rect(page, f"{_block(joins[1])} .lesson-block__body")
    assert abs(pop["width"] - col["width"]) < 2, (pop, col)
    a = rect(page, f"{_block(joins[0])} img")
    page.context.clear_cookies()
    login(page, live_server, "fn_phone_twin")
    open_page(page, unit_url(live_server, twin), PHONE)
    b = rect(page, ".el--image img")
    assert all(abs(a[k] - b[k]) < 1 for k in ("left", "width")), (a, b)


@pytest.mark.parametrize("medium", ["screen", "print"])
def test_neighbour_note_card_never_runs_under_the_image(page, live_server, medium):
    course, unit, joins, st = seed_student_lesson(
        f"fn-nb-{medium}",
        f"fn_nb_{medium}",
        [lambda c: image(c, px=(300, 600)), lambda c: text("Krótko.")],
    )
    note(st, unit, joins[1], body="notatka obok obrazka " * 5)
    login(page, live_server, f"fn_nb_{medium}")
    open_page(page, unit_url(live_server, unit), PHONE)
    if medium == "print":
        print_mode(page)  # notes.css prints pops that have cards
    else:
        open_notes(page, joins[1])
    card = rect(page, f"{_block(joins[1])} .note-card")
    assert card["width"] > 0 and card["height"] > 0, "card not rendered; vacuous"
    img = rect(page, f"{_block(joins[0])} img")
    assert not boxes_intersect(card, img), (card, img)


def test_spacing_unchanged_for_a_block_far_from_the_float(page, live_server):
    far = [lambda c: text() for _ in range(5)]
    course, unit, joins, st = seed_student_lesson("fn-sp", "fn_sp", SHAPE + far)
    note(st, unit, joins[-1])
    _c2, twin, tj, ts = seed_student_lesson(
        "fn-sp-twin",
        "fn_sp_twin",
        [lambda c: image(c, px=(300, 220), float_right=False)] + SHAPE[1:] + far,
    )
    note(ts, twin, tj[-1])

    def offset(user, u, j):
        page.context.clear_cookies()
        login(page, live_server, user)
        open_page(page, unit_url(live_server, u), PHONE)
        open_notes(page, j)
        return (
            rect(page, f"{_block(j)} .note-card")["top"]
            - rect(page, f"{_block(j)} .block-notes__pop")["top"]
        )

    assert (
        abs(offset("fn_sp", unit, joins[-1]) - offset("fn_sp_twin", twin, tj[-1])) < 0.5
    )


def test_print_keeps_the_float_unless_notes_print(page, live_server):
    course, unit, joins, st = seed_student_lesson(
        "fn-print",
        "fn_print",
        [
            lambda c: image(c, px=(300, 220)),
            lambda c: text(),
            lambda c: image(c, px=(300, 220)),
            lambda c: text(),
        ],
    )
    note(st, unit, joins[2])  # the second image prints notes -> un-floats
    login(page, live_server, "fn_print")
    open_page(page, unit_url(live_server, unit), DESKTOP)
    print_mode(page)
    assert _float(page, joins[0]) == "right"
    cap = page.locator(f"{_block(joins[0])} img").evaluate(
        "e => getComputedStyle(e).maxHeight"
    )
    assert cap.endswith("px") and abs(float(cap[:-2]) - 45 * 96 / 25.4) < 1  # 45mm
    assert _float(page, joins[2]) == "none"
    assert (
        page.locator(f"{_block(joins[1])} .block-notes__pop").evaluate(
            "e => getComputedStyle(e).display"
        )
        == "none"
    )  # an EMPTY pop stays hidden
    assert page.locator(f"{_block(joins[2])} .block-notes__panel[open]").count() == 1
    pop = rect(page, f"{_block(joins[2])} .block-notes__pop")
    col = rect(page, f"{_block(joins[1])} .lesson-block__body")
    assert pop["width"] > 0, "pop not rendered (beforeprint not fired?)"
    assert abs(pop["width"] - col["width"]) < 2, (pop, col)
    a = rect(page, f"{_block(joins[2])} img")
    _c2, twin, _j2, _s2 = seed_student_lesson(
        "fn-print-twin",
        "fn_print_twin",
        [lambda c: image(c, px=(300, 220), float_right=False), lambda c: text()],
    )
    page.context.clear_cookies()
    login(page, live_server, "fn_print_twin")
    open_page(page, unit_url(live_server, twin), DESKTOP)
    print_mode(page)
    b = rect(page, ".el--image img")
    assert all(abs(a[k] - b[k]) < 1 for k in ("left", "width")), (a, b)


def test_clamped_pop_beats_a_following_drag_to_image_target(page, live_server):
    # z-index 50 while open exists to beat positive-z content in the root context;
    # .dragimage__target / __badge (3/4) is one. 1400px clamps the pop over the column's
    # RIGHT end (right: 0, 15rem wide -- tests/test_e2e_notes_rail.py "clamped"), so the
    # drop zone is placed at the stage's right end on a REAL, column-wide image: the
    # reveal kit's MediaAssetFactory file is never served (no geometry) and its zones
    # sit at x 0.1-0.75, left of the pop.
    from courses.models import DragToImageQuestionElement
    from courses.models import DragZone

    def drag_question(course):
        q = DragToImageQuestionElement.objects.create(
            stem="Label it.",
            media=make_image_asset(course, size=(1600, 400), color="blue"),
            distractors="gammadis",
        )
        DragZone.objects.create(
            question=q, order=0, correct_label="alphakey", x=0.8, y=0.05, w=0.18, h=0.9
        )
        return q

    course, unit, joins, st = seed_student_lesson(
        "fn-drag",
        "fn_drag",
        [lambda c: image(c, px=(300, 220)), lambda c: text("Krótko."), drag_question],
    )
    note(st, unit, joins[0], body="notatka " * 60)  # a tall pop reaches the stage
    login(page, live_server, "fn_drag")
    open_page(page, unit_url(live_server, unit), {"width": 1400, "height": 950})
    page.wait_for_selector("html.notes-js")
    open_notes(page, joins[0])
    pop_sel = f"{_block(joins[0])} .block-notes__pop"
    page.wait_for_selector(f"{pop_sel}.block-notes__pop--clamped")
    # The click leaves the pointer on the handle, so notes.js's hover highlight dims the
    # drag question's block (opacity .45): a stacking context that traps the target's
    # z-index 3 below the floated block's 1 and makes this test pass vacuously. Move
    # the pointer away (keyboard users and any mouse that leaves never have the dim).
    page.mouse.move(1, 1)
    assert page.locator(".lesson-block.is-dimmed").count() == 0, "fixture: still dimmed"
    pop = rect(page, pop_sel)
    target = rect(page, ".dragimage__target")
    assert boxes_intersect(pop, target), (
        f"fixture: pop {pop} must overlap target {target}; adjust the zone/note length"
    )
    x = (max(pop["left"], target["left"]) + min(pop["right"], target["right"])) / 2
    y = (max(pop["top"], target["top"]) + min(pop["bottom"], target["bottom"])) / 2
    on_top = page.evaluate(
        "([x, y, sel]) => !!document.elementFromPoint(x, y).closest(sel)",
        [x, y, pop_sel],
    )
    assert on_top, "the floated block's open pop is under the drag-image target"
