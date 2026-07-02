"""Email delivery for notifications (slice 2).

Imports are one-way: this module top-level-imports notifications.services and
core.services; notifications.services imports THIS module function-locally inside
notify() to avoid a load-time cycle. Uses eager gettext (not gettext_lazy) so
interpolation resolves inside the translation.override() block.
"""

import logging

from allauth.account import app_settings as account_settings
from django.conf import settings as dj_settings
from django.contrib.sites.models import Site
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

from core.services import get_site_config
from notifications.models import Notification
from notifications.models import NotificationEmailPreference
from notifications.services import notification_url

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


def deliver_notification_email(notification):
    """Send one multipart (text + HTML) email for a notification, localized to the
    recipient's language. No-op on a blank email address. The whole body is wrapped
    in log-and-swallow: this runs in a post-on_commit callback AFTER the row has
    committed, and notify_needs_review queues one callback per teacher — Django runs
    them in order and STOPS at the first that raises, so any unguarded failure (render,
    content ValueError, send) would silently skip the remaining recipients."""
    recipient = notification.recipient
    if not recipient.email:
        return
    try:
        if not email_enabled(recipient, notification.kind):
            return
        lang = recipient.language or dj_settings.LANGUAGE_CODE
        with translation.override(lang):
            subject, headline, body_line = email_content(notification)
            ctx = {
                "headline": headline,
                "body_line": body_line,
                "cta_url": _absolute_url(
                    notification_url(notification) or reverse("notifications:list")
                ),
                "manage_url": _absolute_url(reverse("core:user_settings")),
                "site": get_site_config(),
            }
            html = render_to_string("notifications/email/notification.html", ctx)
            text = render_to_string("notifications/email/notification.txt", ctx)
        msg = EmailMultiAlternatives(subject, text, None, [recipient.email])
        msg.attach_alternative(html, "text/html")
        msg.send()
    except Exception:  # noqa: BLE001 — never break the request / fan-out
        logger.exception(
            "notification email delivery failed (notification %s)", notification.pk
        )
