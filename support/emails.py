"""Report notification email.

Built like notifications/emails.py (EmailMultiAlternatives + render_to_string +
translation.override with EAGER gettext so interpolation resolves inside the
block), with two deliberate divergences, noted here so a later reviewer does not
"restore consistency" and undo them:

  * ONE bcc'd message rather than one message per recipient — the audience is a
    fixed admin list, not a per-user fan-out.
  * The language is the institution default, not the recipient's: a single
    message can only have one language.
"""

import logging

from allauth.account import app_settings as account_settings
from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils import translation
from django.utils.translation import gettext as _

from core.services import get_site_config
from institution.roles import PLATFORM_ADMIN
from support.models import SupportSettings
from support.policy import role_labels
from support.telemetry import safe_page_link
from support.telemetry import telemetry_rows

logger = logging.getLogger(__name__)
User = get_user_model()


def _absolute_url(path):
    """Absolute URL from the current Site (never a request Host header, so an
    emailed link cannot be host-spoofed). Local rather than importing
    notifications.emails._absolute_url, which is a private name in another app."""
    domain = Site.objects.get_current().domain
    scheme = account_settings.DEFAULT_HTTP_PROTOCOL
    return f"{scheme}://{domain}{path}"


def resolve_recipients():
    """Active PA-Group members with an email, unioned with extra_emails,
    de-duplicated case-insensitively. Superusers outside the Group are NOT
    included, matching accounts.services.is_last_active_platform_admin."""
    addresses = list(
        User.objects.filter(is_active=True, groups__name=PLATFORM_ADMIN)
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    row = SupportSettings.objects.filter(pk=1).first()
    if row is not None:
        addresses += [a for a in (row.extra_emails or []) if a]
    seen, unique = set(), []
    for address in addresses:
        key = address.lower()
        if key not in seen:
            seen.add(key)
            unique.append(address)
    return unique


def send_issue_report_email(report):
    """Never raises. See the module note in Task 4's stub: an exception escaping
    here would reach report_create's rollback `except` — which cannot tell a
    rollback from a post-commit failure — and delete a COMMITTED report's
    screenshot while 500ing a reporter whose report was in fact saved."""
    try:
        recipients = resolve_recipients()
        if not recipients:
            logger.warning(
                "issue report %s has no resolvable recipients; not sending",
                report.pk,
            )
            return
        cfg = get_site_config()
        with translation.override(cfg["default_language"]):
            reporter = " ".join((report.reporter_label or "").split())
            institution = " ".join((cfg["name"] or "").split())
            subject = _("[%(institution)s] Issue report #%(pk)s from %(who)s") % {
                "institution": institution,
                "pk": report.pk,
                "who": reporter,
            }
            ctx = {
                "report": report,
                "detail_url": _absolute_url(
                    reverse("support:report_detail", args=[report.pk])
                ),
                "roles": role_labels(report.reporter_roles),
                "telemetry": telemetry_rows(report.telemetry),
                "page_link": safe_page_link(report.page_url),
                "site": cfg,
            }
            text = render_to_string("support/email/issue_report.txt", ctx)
            html = render_to_string("support/email/issue_report.html", ctx)
        reply_to = (
            [report.reporter.email]
            if (report.reporter and report.reporter.email)
            else None
        )
        message = EmailMultiAlternatives(
            subject,
            text,
            None,
            # Recipients go in bcc: putting them in `to` would disclose each PA's
            # personal address to a helpdesk alias and to every other recipient.
            to=[dj_settings.DEFAULT_FROM_EMAIL],
            bcc=recipients,
            reply_to=reply_to,
        )
        message.attach_alternative(html, "text/html")
        if report.screenshot:
            report.screenshot.open("rb")
            try:
                message.attach(
                    report.screenshot.name.rsplit("/", 1)[-1],
                    report.screenshot.read(),
                )
            finally:
                report.screenshot.close()
        message.send()
        report.emailed_at = timezone.now()
        # update_fields: a bare save() from a post-commit callback would rewrite
        # every field of a row a PA may have resolved in the meantime.
        report.save(update_fields=["emailed_at"])
    except Exception:  # noqa: BLE001 — must never escape the on_commit hook
        logger.exception("issue report email delivery failed (report %s)", report.pk)
