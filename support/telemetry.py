"""Allow-listed, bounded telemetry plus the two shared render helpers.

Everything the client sends is untrusted: the view never stores the payload, it
rebuilds the dict from TELEMETRY_LABELS' keys. No IP address is collected — this
is a platform with student accounts and the diagnostic value does not justify the
personal-data question.
"""

from urllib.parse import urlparse

from django.contrib.sites.models import Site
from django.utils.translation import gettext_lazy as _

# Declared ORDER is the render order, shared by triage and both email templates.
TELEMETRY_LABELS = {
    "viewport_w": _("Viewport width"),
    "viewport_h": _("Viewport height"),
    "screen_w": _("Screen width"),
    "screen_h": _("Screen height"),
    "dpr": _("Device pixel ratio"),
    "theme": _("Theme"),
    "ui_language": _("Interface language"),
    "timezone": _("Time zone"),
    "user_agent": _("Browser"),
    "accept_language": _("Language header"),
}

TELEMETRY_CAPS = {
    "timezone": 64,
    "ui_language": 16,
    "user_agent": 512,
    "accept_language": 256,
}

# (low, high) inclusive; out-of-range values are DROPPED, never clamped.
TELEMETRY_BOUNDS = {
    "viewport_w": (1, 20000),
    "viewport_h": (1, 20000),
    "screen_w": (1, 20000),
    "screen_h": (1, 20000),
}

_CLIENT_STRINGS = ("timezone", "ui_language")
_THEMES = {"light", "dark"}
_DPR_MAX = 10


def sanitise(request):
    """Build the stored telemetry dict from request.POST and request.META.

    Read directly from POST, never through IssueReportForm: these keys are neither
    model fields nor declared form fields, and routing them through the form would
    let a malformed telemetry value REJECT a bug report. Bad telemetry is dropped.
    """
    post = request.POST
    data = {}

    for key in _CLIENT_STRINGS:
        value = (post.get(key) or "").strip()
        if value:
            data[key] = value[: TELEMETRY_CAPS[key]]

    for key, (low, high) in TELEMETRY_BOUNDS.items():
        try:
            number = int(post.get(key, ""))
        except (TypeError, ValueError):
            continue
        if low <= number <= high:
            data[key] = number

    try:
        dpr = round(float(post.get("dpr", "")), 2)
    except (TypeError, ValueError):
        dpr = None
    if dpr is not None and 0 < dpr <= _DPR_MAX:
        data["dpr"] = dpr

    theme = (post.get("theme") or "").strip()
    if theme in _THEMES:
        data["theme"] = theme

    # Server facts win: taken from the request, never from the payload, so a
    # reporter cannot forge the browser identification a PA debugs against.
    for key, header in (
        ("user_agent", "HTTP_USER_AGENT"),
        ("accept_language", "HTTP_ACCEPT_LANGUAGE"),
    ):
        value = (request.META.get(header) or "").strip()
        if value:
            data[key] = value[: TELEMETRY_CAPS[key]]

    return data


def telemetry_rows(telemetry):
    """[(key, label, value)] in TELEMETRY_LABELS order, omitting absent keys.

    A shared dict alone would prevent label drift but not row-order drift between
    triage and email. Dropped keys are omitted rather than rendered as "unknown":
    the sanitiser drops out-of-range values instead of clamping precisely because
    an absent viewport is an honest fact and a clamped one is a plausible lie.
    """
    telemetry = telemetry or {}
    return [
        (key, label, telemetry[key])
        for key, label in TELEMETRY_LABELS.items()
        if key in telemetry
    ]


def safe_page_link(url):
    """The URL when it is safe to render as an href, else None.

    One home, used by the triage template AND both email templates — the email is
    the one output that travels outside the login wall, so a rule living only in
    the triage view could leak a javascript: or foreign-host href into it.

    Keys on the current Site (never request.get_host()), matching
    notifications/emails._absolute_url, so a link cannot be host-spoofed. Compares
    urlparse().hostname (port-stripped, lower-cased) against a port-stripped
    Site.domain: comparing netloc directly would fail on every port-bearing
    deployment and throughout local development. Django's default Site.domain is
    example.com, so an install that never edited the Site row renders every
    page_url as inert text — intended, not a defect.
    """
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    site_host = Site.objects.get_current().domain.split(":")[0].lower()
    return url if host and host == site_host else None
