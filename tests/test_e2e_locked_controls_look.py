"""Playwright: a locked question LOOKS locked (owner follow-up to quiz answer reveal
PR 2): a disabled button is dimmed, a locked grid's pick stands out in dark mode, and
a drag-onto-image badge is not covered by its answer box."""

import os

import pytest

from tests.test_e2e_quiz_reveal_pr2 import _check
from tests.test_e2e_quiz_reveal_pr2 import _login
from tests.test_e2e_quiz_reveal_pr2 import _quiz_url
from tests.test_e2e_quiz_reveal_pr2 import _seed
from tests.test_e2e_quiz_reveal_pr2 import _size_stages
from tests.test_e2e_quiz_reveal_pr2 import _student

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# WCAG relative-luminance contrast of two cells' EFFECTIVE backgrounds (a transparent
# cell shows its nearest painted ancestor). color-mix() computes to `color(srgb …)`
# with 0-1 channels, a plain colour to `rgb(…)` with 0-255 ones.
_CELL_CONTRAST = """(tr) => {
  const eff = (el) => {
    for (; el; el = el.parentElement) {
      const c = getComputedStyle(el).backgroundColor;
      const alpha = c.match(/\\/\\s*([\\d.]+)\\)|rgba\\([^)]*,\\s*([\\d.]+)\\)/);
      const clear = alpha && Number(alpha[1] || alpha[2]) === 0;
      if (c !== "transparent" && !clear) return c;
    }
    return "rgb(255, 255, 255)";
  };
  const lum = (c) => {
    const n = c.match(/[\\d.]+/g).map(Number).slice(0, 3);
    const unit = c.startsWith("color(") ? n : n.map((v) => v / 255);
    const [r, g, b] = unit.map((v) =>
      v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const tds = tr.querySelectorAll("td");  // [statement, picked, not picked]
  const a = lum(eff(tds[1]));
  const b = lum(eff(tds[2]));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}"""


def _lock_grid(page, live_server, username, kind, theme="light"):
    from django.contrib.auth import get_user_model

    _student(username)
    course, unit, _ = _seed(username, f"e2e-look-{username}", [kind], max_attempts=1)
    user = get_user_model().objects.get(username=username)
    user.theme = theme
    user.save(update_fields=["theme"])
    _login(page, live_server, username)
    page.goto(_quiz_url(live_server, course, unit))
    assert page.evaluate("document.documentElement.dataset.theme") == theme
    q = page.locator("[data-question]").first
    rows = q.locator("[data-answer-yours] tbody tr")
    rows.nth(0).locator("input").nth(0).check()
    rows.nth(1).locator("input").nth(0).check()
    return q


@pytest.mark.django_db(transaction=True)
def test_a_locked_check_button_looks_disabled(browser, live_server):
    page = browser.new_context().new_page()
    q = _lock_grid(page, live_server, "look_btn", "choicegrid")
    check = q.locator("button[type='submit']:not([name='reveal'])")
    assert check.evaluate("b => getComputedStyle(b).opacity") == "1"  # live
    _check(q)
    q.locator("[data-answer-switch]").wait_for(timeout=6000)  # 1 attempt: locked
    assert check.is_disabled()
    look = "b => [getComputedStyle(b).opacity, getComputedStyle(b).pointerEvents]"
    assert check.evaluate(look) == ["0.45", "none"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["choicegrid", "multigrid"])
def test_dark_locked_grid_pick_stands_out(browser, live_server, kind):
    # Row 1: the first column is picked, the second is not. A disabled control's dot
    # barely shows in dark mode, so the two cells' tints must differ clearly.
    page = browser.new_context().new_page()
    q = _lock_grid(page, live_server, f"look_{kind}", kind, theme="dark")
    _check(q)
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
    row = q.locator("[data-answer-yours] tbody tr").nth(0)
    # Measured on this fixture: the plain --primary-subtle tint gives 1.25:1 (RED),
    # a 40% mix 1.49:1, the 50% mix that ships clears this bar.
    ratio = row.evaluate(_CELL_CONTRAST)
    assert ratio >= 1.5, ratio


@pytest.mark.django_db(transaction=True)
def test_dragimage_badge_sits_above_its_answer_box(browser, live_server):
    _student("look_img")
    course, unit, _ = _seed("look_img", "e2e-look-img", ["dragimage"])
    page = browser.new_context().new_page()
    _login(page, live_server, "look_img")
    page.goto(_quiz_url(live_server, course, unit))
    _size_stages(page)
    q = page.locator("[data-question]").first
    badge = q.locator("[data-answer-yours] .dragimage__badge").first
    target = q.locator("[data-answer-yours] .dragimage__target").first
    z = "el => Number(getComputedStyle(el).zIndex)"
    assert badge.evaluate(z) > target.evaluate(z)
    # The badge must still let taps through to the box beneath it.
    assert badge.evaluate("el => getComputedStyle(el).pointerEvents") == "none"
