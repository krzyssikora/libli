"""Helpers for tests written before the builder became lazy.

Most seeded fixtures are under SIZE_THRESHOLD and so still arrive fully
expanded -- which is a TRAP, not a relief: such a test no longer exercises
the lazy path at all. At least one test per behaviour must seed above the
threshold or pass open= explicitly.
"""


def open_all_param():
    """Append to a builder GET to force every scope open."""
    return "?open=all"


def expand_to(page, *nodes):
    """Click the real toggles down a chain and wait for each scope.

    Drives the actual control -- never page.evaluate, which would ship broken
    UX green.
    """
    for node in nodes:
        toggle = page.locator(f'[data-toggle="{node.pk}"]')
        # Units render a <span class="tree__toggle--leaf"> with NO data-toggle,
        # so reading an attribute would block until the locator times out
        # instead of failing fast.
        assert toggle.count() == 1, f"node {node.pk} ({node.kind}) has no toggle"
        if toggle.get_attribute("aria-expanded") == "true":
            continue
        toggle.click()
        page.wait_for_selector(f'ol[data-scope="{node.pk}"]')
