"""Drive a visually hidden choice input the way a student does.

Playwright refuses `.check()` on a clipped 1x1 input, so a test clicks what the
student clicks: the input's parent `label`. Never `force=True`, which would also
pass on a card that a real click cannot reach.
"""


def pick(input_locator) -> None:
    """Click the parent label of `input_locator` (toggles a checkbox)."""
    input_locator.locator("xpath=..").click()
