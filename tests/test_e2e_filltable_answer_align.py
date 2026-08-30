r"""An ANSWER cell's text must honour the cell's horizontal alignment.

`.ta-*` reaches the `<td>` and the answer `<input>` BOX is placed correctly by it
(it is inline-level, so a centred cell centres the box). But `text-align` does
NOT inherit into a form control: Chromium, Gecko and WebKit alike compute
`text-align: start` on `<input>` from their UA stylesheet, and
`.filltable__input` declared none. So the value the student types -- and the
canonical value restored on the `mine.done` path -- sat flush LEFT inside the
box at every alignment. Reported on a real unit: the author centres a whole
fill-in table and every answer stays left.

Same defect class as `.katex-display` and `.cell-img` in courses.css -- a child
of the cell that does not take the cell's text-align -- and the same fix shape:
`text-align: inherit`.

MEASURED (pixel ink inside the input, this test, with the fix reverted):
ta-left 6.0/33.0, ta-center 6.0/33.0, ta-right 6.0/33.0 -- IDENTICAL at all
three alignments, i.e. halign had no effect on the answer text whatever.

The probe is the INK inside the input's own content box, not the box position:
centring the box is the part that already worked, so measuring the box would
pass on the broken build. Background is sampled from the crop's own corner, so
the measurement is free of the theme and of the correct/incorrect state colours.

Marked e2e (excluded from the default run; use -m e2e)."""

import io
import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import add_element

pytestmark = pytest.mark.e2e

# Inset past the 1px border + border-radius corners before looking for ink.
_INSET = 5
# Per-channel distance from the sampled background that counts as a glyph.
_INK = 40


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


def _new_unit(username):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_verified_user

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    EnrollmentFactory(student=student, course=course)
    return student, unit


def _ink_gaps(locator):
    """(gap_left, gap_right) in px between the input's inner edges and its glyphs."""
    from PIL import Image

    img = Image.open(io.BytesIO(locator.screenshot())).convert("RGB")
    box = img.crop((_INSET, _INSET, img.width - _INSET, img.height - _INSET))
    bg = box.getpixel((0, 0))
    cols = [
        x
        for x in range(box.width)
        if any(
            max(abs(p - b) for p, b in zip(box.getpixel((x, y)), bg, strict=True))
            > _INK
            for y in range(box.height)
        )
    ]
    assert cols, "no glyph ink inside the input -- the value did not render"
    return float(cols[0]), float(box.width - 1 - cols[-1])


def _fill(page, row, value):
    inp = page.locator(f".el--filltable tr:nth-child({row}) .filltable__input")
    inp.fill(value)
    return inp


@pytest.mark.django_db(transaction=True)
def test_answer_input_text_honours_cell_halign(page, live_server):
    from courses.models import FillTableElement

    _student, unit = _new_unit("ftbl_ans_align")
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "left"},
                    {"kind": "answer", "answer": "1", "halign": "left"},
                ],
                [
                    {"kind": "static", "html": "center"},
                    {"kind": "answer", "answer": "1", "halign": "center"},
                ],
                [
                    {"kind": "static", "html": "right"},
                    {"kind": "answer", "answer": "1", "halign": "right"},
                ],
            ]
        }
    )
    el.save()
    add_element(unit, el)
    _login(page, live_server, "ftbl_ans_align")
    page.goto(f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".el--filltable .filltable__input")

    for row in (1, 2, 3):
        _fill(page, row, "1")
    # The caret is ink too, and it blinks: measure an UNFOCUSED input.
    page.evaluate("document.activeElement && document.activeElement.blur()")

    left = _ink_gaps(page.locator(".el--filltable tr:nth-child(1) .filltable__input"))
    center = _ink_gaps(page.locator(".el--filltable tr:nth-child(2) .filltable__input"))
    right = _ink_gaps(page.locator(".el--filltable tr:nth-child(3) .filltable__input"))

    assert left[0] < left[1], f"ta-left not honoured: {left}"
    assert right[1] < right[0], f"ta-right not honoured: {right}"
    assert abs(center[0] - center[1]) <= 1.0, f"ta-center not honoured: {center}"
