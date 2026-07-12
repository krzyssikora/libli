"""Project-wide pytest fixtures.

Kept minimal: this root conftest exists so an autouse fixture can cover EVERY
test directory (tests/, courses/tests/, notifications/tests/, ...). Directory
conftests (e.g. tests/conftest.py) only apply to their own subtree, which is
too narrow for cross-cutting test-isolation concerns like the one below.
"""

import pytest
from django.conf import settings
from django.utils import translation


@pytest.fixture(autouse=True)
def _reset_active_language():
    """Pin the active translation to the default language around every test.

    Some tests issue ``client.get(..., HTTP_ACCEPT_LANGUAGE="pl")``. Django's
    LocaleMiddleware activates ``pl`` for that request but does NOT deactivate it
    afterwards, so ``pl`` stays active in the worker's thread and leaks into
    whatever test runs next on that worker. Victims are any test that asserts
    against gettext output in the default language (e.g. the transfer-validation
    tests, which check English error text). This was latent until CI moved to
    xdist (``-n auto`` / ``-n 2``), which makes "which test runs before which on a
    worker" nondeterministic — turning the leak into a flaky failure.

    Activating the default before each test guarantees a clean starting locale
    regardless of order or parallelism; deactivating after keeps a leaking test
    from polluting the next one. Tests that need another language still use
    ``translation.override(...)`` or ``HTTP_ACCEPT_LANGUAGE`` locally — those are
    unaffected because they set the language *within* the test.
    """
    translation.activate(settings.LANGUAGE_CODE)
    yield
    translation.deactivate_all()
