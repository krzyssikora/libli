"""Playwright: a locked question LOOKS locked (owner follow-up to quiz answer reveal
PR 2): a disabled button is dimmed, a locked grid's pick stands out in dark mode, and
a drag-onto-image badge is not covered by its answer box."""

import os

import pytest

from tests.e2e_pick import pick
from tests.test_e2e_choice_cards import _css
from tests.test_e2e_choice_cards import _token
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


# WCAG contrast of a colour against the surface behind the button (the nearest
# painted ancestor). color-mix() computes to `color(srgb ...)` with 0-1 channels, a
# plain colour to `rgb(...)` with 0-255 ones.
_BORDER_CONTRAST = """([btn, colour]) => {
  let surface = "rgb(255, 255, 255)";
  for (let el = btn.parentElement; el; el = el.parentElement) {
    const c = getComputedStyle(el).backgroundColor;
    const alpha = c.match(/\\/\\s*([\\d.]+)\\)|rgba\\([^)]*,\\s*([\\d.]+)\\)/);
    const clear = alpha && Number(alpha[1] || alpha[2]) === 0;
    if (c !== "transparent" && !clear) { surface = c; break; }
  }
  const lum = (c) => {
    const n = c.match(/[\\d.]+/g).map(Number).slice(0, 3);
    const unit = c.startsWith("color(") ? n : n.map((v) => v / 255);
    const [r, g, b] = unit.map((v) =>
      v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const a = lum(colour);
  const b = lum(surface);
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
    pick(rows.nth(0).locator("input").nth(0))
    pick(rows.nth(1).locator("input").nth(0))
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
    # Row 0 is answered correctly through its first column; the outline carries
    # the pick now that the native dot is gone (the fill alone is too faint).
    page = browser.new_context().new_page()
    q = _lock_grid(page, live_server, f"look_{kind}", kind, theme="dark")
    _check(q)
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
    row = q.locator("[data-answer-yours] tbody tr").nth(0)
    picked = row.locator(".gridbtn").nth(0)
    unpicked = row.locator(".gridbtn").nth(1)
    assert row.locator("input").nth(0).is_disabled()
    success = _token(page, "--success")
    assert _css(picked, "borderTopColor") == success
    shadow = _css(picked, "boxShadow")
    assert "inset" in shadow and success in shadow, shadow
    assert _css(unpicked, "borderTopColor") == _token(page, "--border-strong")
    assert _css(unpicked, "boxShadow") == "none"
    ratio = picked.evaluate(
        "(el, args) => (" + _BORDER_CONTRAST + ")([el, args])", success
    )
    assert ratio >= 3, ratio


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
