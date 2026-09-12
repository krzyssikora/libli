"""Demo-kit services. The commands and (later) PR 3's tab both call these, so
every rule lives here rather than in a caller."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def require_vendor():
    """Refuse on a box that is not the vendor instance.

    Guards the CREATING half only: provision_kit and extend_kit. purge_kit,
    revoke_kit and list are deliberately EXEMPT (spec R8) — guarding a cleanup
    path is the one way this guard could leave stranger-known logins alive on
    prod, since the flag is an env var a compose change can lose.
    """
    if not settings.VENDOR_INSTANCE:
        raise ImproperlyConfigured(
            "Demo kits can only be provisioned on the vendor instance. Set "
            "LIBLI_VENDOR_INSTANCE=true in .env.production if this box is it."
        )
