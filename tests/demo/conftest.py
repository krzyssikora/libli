import pytest


@pytest.fixture
def vendor(settings):
    """The demo tab exists only on the vendor instance, and config/settings/test.py
    pins VENDOR_INSTANCE False. pytest-django's `settings` restores it afterwards."""
    settings.VENDOR_INSTANCE = True
    return settings
