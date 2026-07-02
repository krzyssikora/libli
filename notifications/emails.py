"""Email delivery for notifications (slice 2).

Imports are one-way: this module top-level-imports notifications.services and
core.services; notifications.services imports THIS module function-locally inside
notify() to avoid a load-time cycle. Uses eager gettext (not gettext_lazy) so
interpolation resolves inside the translation.override() block.
"""

import logging

from allauth.account import app_settings as account_settings
from django.contrib.sites.models import Site
from django.utils.translation import gettext as _

from notifications.models import Notification
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


def email_content(notification):
    """Return (subject, headline, body_line) for the notification's kind, localized
    under the caller's active language. Reads only notification.data (no DB loads).
    Call inside a translation.override() block."""
    d = notification.data or {}
    if notification.kind == Notification.Kind.QUIZ_NEEDS_REVIEW:
        subject = _("A quiz needs your review")
        body_line = _(
            "%(student)s submitted %(unit)s in %(course)s and it needs review."
        ) % {
            "student": d.get("student_name", ""),
            "unit": d.get("unit_title", ""),
            "course": d.get("course_title", ""),
        }
    elif notification.kind == Notification.Kind.QUIZ_GRADED:
        subject = _("Your quiz was graded")
        body_line = _(
            "Your submission for %(unit)s in %(course)s has been reviewed."
        ) % {
            "unit": d.get("unit_title", ""),
            "course": d.get("course_title", ""),
        }
    elif notification.kind == Notification.Kind.ENROLLED:
        # course_title lands in the Subject header → collapse any newline; reuse the
        # collapsed value for the body so headline and body agree.
        course = " ".join((d.get("course_title") or "").split())
        subject = _("You've been enrolled in %(course)s") % {"course": course}
        body_line = _("You now have access to %(course)s.") % {"course": course}
    else:
        raise ValueError(f"email_content: no copy for kind {notification.kind!r}")
    headline = subject  # kept separate for future divergence
    return subject, headline, body_line
