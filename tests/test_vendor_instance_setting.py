"""VENDOR_INSTANCE is a DEPLOY fact, not a school-editable preference.

It gates /for-schools/, its footer links and the Pricing settings tab, so a
hosted school never publishes our price list. It is a setting rather than an
Institution field precisely so a school admin cannot toggle it.
"""

from django.conf import settings
from django.test import override_settings


def test_defaults_to_false_under_test_settings():
    """PINNED in config/settings/test.py, not merely defaulted.

    base.py does env.read_env(BASE_DIR/".env"), which copies a developer's local
    .env into os.environ, and test.py does `from base import *`. Whoever builds
    this page will set LIBLI_VENDOR_INSTANCE=true in their own .env to see the
    page on runserver -- and without the pin that flips the flag for the ENTIRE
    test run, reddening every gate-off assertion for a reason unrelated to the
    code. tests/test_transfer_caps_env.py records this exact leak happening
    before.
    """
    assert settings.VENDOR_INSTANCE is False


def test_the_pin_is_in_the_test_settings_module_not_just_the_env():
    """Falsification: reading the source proves the pin exists, where asserting
    the value alone would pass on a machine that simply has no .env."""
    from pathlib import Path

    source = Path(settings.BASE_DIR, "config", "settings", "test.py").read_text(
        encoding="utf-8"
    )
    assert "VENDOR_INSTANCE = False" in source


@override_settings(VENDOR_INSTANCE=True)
def test_tests_opt_back_in_with_override_settings():
    assert settings.VENDOR_INSTANCE is True
