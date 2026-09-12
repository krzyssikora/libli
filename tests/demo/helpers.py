from django.test import override_settings

from demo.constants import DEFAULT_DAYS


def provision_for_test(
    course, *, label="SP 12", pupils=5, days=DEFAULT_DAYS, seed=4242, full=False
):
    """Every provisioning test needs VENDOR_INSTANCE on (test settings pin it
    False) and an EXPLICIT seed (the service draws one from secrets otherwise,
    so content assertions would run against a fresh random class each time).

    `full=True` returns the whole ProvisionResult instead of just `.kit` — the
    warnings and the two passwords are otherwise unreachable, which silently
    defeated the webhook half of T12.
    """
    from demo.services import provision_kit

    with override_settings(VENDOR_INSTANCE=True):
        result = provision_kit(
            label, course=course, days=days, pupils=pupils, seed=seed
        )
    return result if full else result.kit
