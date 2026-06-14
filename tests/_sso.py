"""Builders for SSO adapter tests: an openid_connect SocialApp, a SocialLogin for
a given IdP email, and a session/messages-enabled request. Kept out of the test
module so multiple test files can share it."""


def make_oidc_app():
    from allauth.socialaccount.models import SocialApp
    from django.contrib.sites.models import Site

    app = SocialApp.objects.create(
        provider="openid_connect",
        provider_id="testidp",
        name="Test IdP",
        client_id="client-id",
        secret="secret",
        settings={"server_url": "https://idp.example.test"},
    )
    app.sites.add(Site.objects.get_current())
    return app


def make_sociallogin(app, request, email, username="ssouser", uid=None, verified=True):
    """An unsaved, not-yet-existing SocialLogin for `email`, wired to `app`'s provider.

    Verified against allauth 65.18: SocialAccount stores `app.provider_id` (here
    "testidp") for app-based providers like openid_connect, and SocialLogin carries
    the provider *instance* (`app.get_provider(request)`) so connect()'s notification
    mail and any serialization can resolve the provider. `uid` defaults to a
    per-username value so two sociallogins in one test never collide on the
    (provider, uid) unique constraint (pass a distinct `uid` only to force a clash)."""
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount
    from allauth.socialaccount.models import SocialLogin

    from accounts.models import User

    provider = app.get_provider(request)
    account = SocialAccount(provider=app.provider_id, uid=uid or f"sub-{username}")
    user = User(username=username, email=email)
    addresses = [EmailAddress(email=email, verified=verified, primary=True)]
    sociallogin = SocialLogin(
        user=user, account=account, email_addresses=addresses, provider=provider
    )
    sociallogin.state = {}
    return sociallogin


def make_request(path="/accounts/oidc/testidp/login/callback/"):
    from django.contrib.auth.models import AnonymousUser
    from django.contrib.messages.middleware import MessageMiddleware
    from django.contrib.sessions.middleware import SessionMiddleware
    from django.test import RequestFactory

    request = RequestFactory().get(path)
    SessionMiddleware(lambda r: None).process_request(request)
    MessageMiddleware(lambda r: None).process_request(request)
    request.user = AnonymousUser()
    request.session.save()
    return request
