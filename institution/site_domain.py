"""Validation and persistence for the django.contrib.sites Site domain.

Security-sensitive links -- invitation acceptance, password reset -- are built
from the Site record rather than the request Host header
(accounts/invitations.py:build_accept_url), so they cannot be host-spoofed.
The cost of that choice is that the Site record must be set per environment;
Django ships Site #1 as the placeholder "example.com".

Shared by the `set_site_domain` management command (called from the container
entrypoint) and BrandingForm's public_hostname field (the non-technical
surface in the first-run wizard).

NOTE: institution/forms.py defines `_DOMAIN_RE` (search for the symbol, not a
line number -- Task 3 inserts ~25 lines above it). That is a DIFFERENT regex for
a different job: it validates email domains for AccessForm's allow-list and is
deliberately stricter (requires a dot, lowercase only). Do not merge them: a
public hostname may legitimately be a single label ("localhost") and carry a
port, neither of which is ever valid in an email domain.
"""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# A bare host with an optional :port. No scheme, no path, no userinfo, no
# trailing slash -- Site.domain is a host, and Django concatenates it directly.
# The length lookahead is 100, not DNS's 253: Site.domain is max_length=100, and
# a longer value would pass validation only to fail at save() with a database
# error instead of a form error.
_HOST_RE = re.compile(
    r"^(?=.{1,100}$)"
    r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*"
    r"(?::\d{1,5})?$"
)

INVALID_MESSAGE = _(
    "Enter a hostname such as libli.example.org — no http://, no path, "
    "no trailing slash."
)

# Django ships Site #1 with this domain. It is a VALID hostname, so it passes
# validate_site_domain -- it has to be recognised by identity, never by
# rejection. Consumed by the command's --only-if-placeholder branch and by
# BrandingForm, which leaves the field blank rather than pre-filling it.
PLACEHOLDER_DOMAIN = "example.com"

# django.contrib.sites.models.Site.name is CharField(max_length=50), which is
# SHORTER than Institution.name. Anything longer must be truncated, not passed
# through -- see set_site_domain.
SITE_NAME_MAX_LENGTH = 50


def validate_site_domain(value):
    """Return `value` unchanged if it is a bare host (optionally :port).

    Raises ValidationError otherwise. Used as a form field validator and as the
    command's argument check.
    """
    if not value or not _HOST_RE.match(value):
        raise ValidationError(INVALID_MESSAGE)
    return value


def set_site_domain(domain, name=None):
    """Validate `domain` and write it onto the current Site. Returns the Site.

    Clears the sites framework's per-SITE_ID cache: get_current() memoizes, so
    without this a long-lived process keeps serving the old domain in links.

    LIMITATION: SITE_CACHE is a per-PROCESS dict. With GUNICORN_WORKERS > 1 this
    clears only the worker that served the request; siblings keep building links
    from the old domain until they are recycled. After changing the hostname
    through the settings UI, restart the app service -- Task 6 says so.
    """
    from django.contrib.sites.models import Site

    validate_site_domain(domain)
    site = Site.objects.get_current()
    site.domain = domain
    fields = ["domain"]
    if name:
        # TRUNCATE: Site.name is max_length=50 while Institution.name allows far
        # more, and a realistic school name ("Zespół Szkół Ogólnokształcących
        # im. Marii Skłodowskiej-Curie w Warszawie" is 72 characters) would raise
        # DataError. In the form that happens inside transaction.atomic(), so it
        # would 500 the Identity step AND roll back the brand colours; in the
        # entrypoint, under `set -eu`, it would crash-loop the container.
        site.name = name[:SITE_NAME_MAX_LENGTH]
        fields.append("name")
    site.save(update_fields=fields)
    Site.objects.clear_cache()
    return site
