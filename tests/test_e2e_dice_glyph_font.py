"""A die face typed in lesson text renders from the bundled die font, scaled up.

Measured, because only a browser can fail this: tests/test_dice_glyph_font.py stays
green when the @font-face is present but not applied (a family that is not first in
the stack, a url() that 404s, a unicode-range typo).

The probe is the glyph's ADVANCE WIDTH, read off a Range over the one character.
MEASURED (Chromium, 16px text): 12.1px from the system symbol font this replaces,
21.2px from the 170%-scaled bundled face -- 0.76em vs 1.32em. The 1.2em floor sits
between the two with margin on both sides; Linux fallbacks (DejaVu Sans, ~0.8em) are
also well under it.
"""

import os

import pytest

from courses.models import TextElement
from tests.factories import add_element
from tests.test_e2e_table_width_preset import PA_USERNAME
from tests.test_e2e_table_width_preset import _lesson_url
from tests.test_e2e_table_width_preset import _login
from tests.test_e2e_table_width_preset import _make_pa_user
from tests.test_e2e_table_width_preset import _unit

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

DIE = "⚃"  # die face 4
SENTENCE = f"Uwaga, wynik najpierw ⚀ potem {DIE} jest inny."


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def test_a_die_face_in_lesson_text_uses_the_bundled_scaled_font(page, live_server):
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "dice-font")
    add_element(unit, TextElement.objects.create(body=f"<p>{SENTENCE}</p>"))

    _login(page, live_server, PA_USERNAME)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--text p")
    page.evaluate("() => document.fonts.ready")
    m = page.evaluate(
        """(die) => {
             const p = document.querySelector('.el--text p');
             const t = [...p.childNodes].find(n => n.nodeType === 3
                                                   && n.textContent.includes(die));
             const i = t.textContent.indexOf(die);
             const r = document.createRange();
             r.setStart(t, i); r.setEnd(t, i + 1);
             return { width: r.getBoundingClientRect().width,
                      fontSize: parseFloat(getComputedStyle(p).fontSize),
                      faces: [...document.fonts]
                               .filter(f => f.family.replace(/"/g, '') === 'libli-dice')
                               .map(f => f.status) };
           }""",
        DIE,
    )

    assert m["faces"] == ["loaded"], m
    assert m["width"] >= 1.2 * m["fontSize"], (
        f"die face is {m['width']:.1f}px wide at {m['fontSize']:.0f}px text "
        f"({m['width'] / m['fontSize']:.2f}em); the scaled face measures ~1.32em"
    )
