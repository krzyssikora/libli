import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings


@override_settings(VENDOR_INSTANCE=False)
def test_require_vendor_refuses_on_a_school_box():
    from demo.services import require_vendor

    with pytest.raises(ImproperlyConfigured) as exc:
        require_vendor()
    assert "LIBLI_VENDOR_INSTANCE" in str(exc.value)


@override_settings(VENDOR_INSTANCE=True)
def test_require_vendor_passes_on_the_vendor_box():
    from demo.services import require_vendor

    require_vendor()  # must not raise
