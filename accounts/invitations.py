"""Invite token URL building and email sending.

Host is always taken from the django.contrib.sites Site (never a request Host
header) so the emailed security link cannot be host-spoofed; the scheme reuses
allauth's ACCOUNT_DEFAULT_HTTP_PROTOCOL.
"""

from allauth.account import app_settings as account_settings
from django.contrib.sites.models import Site
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

INVITE_SUBJECT = "You're invited to libli"


def build_accept_url(invitation):
    path = reverse("accounts:accept_invite", args=[invitation.token])
    domain = Site.objects.get_current().domain
    scheme = account_settings.DEFAULT_HTTP_PROTOCOL
    return f"{scheme}://{domain}{path}"


def send_invitation_email(invitation):
    body = render_to_string(
        "accounts/invite_email.txt",
        {"invitation": invitation, "accept_url": build_accept_url(invitation)},
    )
    # from_email=None -> DEFAULT_FROM_EMAIL; plaintext only in 0c-1.
    send_mail(INVITE_SUBJECT, body, None, [invitation.email])
