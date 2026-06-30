"""Platform-admin SSO (OIDC) configuration service. The single place that reads and
writes the institution's one allauth openid_connect SocialApp and its Site link, so
the form, the settings view, and the landing page all resolve the same row + slug."""

from allauth.socialaccount.models import SocialApp
from django.urls import reverse

OIDC_PROVIDER = "openid_connect"  # allauth provider key — single-provider invariant
OIDC_PROVIDER_ID = "sso"  # default slug for a NEW row -> stable redirect URI


def effective_provider_id(app):
    """The provider_id to build callback/login URLs from. None-tolerant: a fresh
    install (app is None) and a legacy blank-slug row both fall back to "sso" (NOT
    app.provider) — which is what save_sso_config canonicalizes a blank slug to."""
    return (app.provider_id if app else "") or OIDC_PROVIDER_ID


def load_sso_app():
    """The one openid_connect SocialApp, or None. order_by("pk") matches the existing
    core/views login-button query so every surface resolves the same row."""
    return SocialApp.objects.filter(provider=OIDC_PROVIDER).order_by("pk").first()


def is_enabled(app, site):
    """SSO is 'live' iff the row exists and the current Site is attached."""
    return app is not None and app.sites.filter(pk=site.pk).exists()


def redirect_uri(request, app):
    """Absolute OIDC callback URL for the PA to register with their IdP. Built from
    the request (correct scheme/host behind a proxy) and the row's effective slug."""
    return request.build_absolute_uri(
        reverse(
            "openid_connect_callback",
            kwargs={"provider_id": effective_provider_id(app)},
        )
    )
