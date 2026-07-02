"""Email delivery for notifications (slice 2).

Imports are one-way: this module top-level-imports notifications.services and
core.services; notifications.services imports THIS module function-locally inside
notify() to avoid a load-time cycle. Uses eager gettext (not gettext_lazy) so
interpolation resolves inside the translation.override() block.
"""

import logging

from allauth.account import app_settings as account_settings
from django.contrib.sites.models import Site

from notifications.models import NotificationEmailPreference

logger = logging.getLogger(__name__)


def email_enabled(user, kind):
    """True when the user has no preference row (default-on), else the per-kind
    boolean. `kind` is always a valid Notification.Kind value (from a Notification
    row), so getattr is safe."""
    pref = NotificationEmailPreference.objects.filter(user=user).first()
    if pref is None:
        return True
    return getattr(pref, kind)


def _absolute_url(path):
    """Absolute URL from the current Site domain (never a request Host header, so the
    emailed link cannot be host-spoofed) + allauth's default scheme."""
    domain = Site.objects.get_current().domain
    scheme = account_settings.DEFAULT_HTTP_PROTOCOL
    return f"{scheme}://{domain}{path}"
