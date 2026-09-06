"""Every institution settings ACTION view is a POST target; a non-POST must not
reach its body.

These views shipped guarding on `request.method == "GET"`, so HEAD, OPTIONS, PUT
and DELETE fell THROUGH to the action carrying an empty `request.POST`. Two of
them have real side effects on that path: `settings_notifications_purge` deletes
rows, and `settings_integrations_test` fires an outbound signed webhook. The rest
re-bind their form against an empty QueryDict.

⚠️ HEAD and OPTIONS need no CSRF token at all -- `CsrfViewMiddleware.process_view`
skips the safe methods -- so those two reach the body unauthenticated by any
token. (Django's default SESSION_COOKIE_SAMESITE="Lax" blocks the cross-site
`fetch(..., {method: "HEAD"})` route, so this is not a practical CSRF hole; the
live risk is an uptime monitor, link prefetcher or scanner issuing HEAD inside an
admin session.)

PR #279 fixed exactly this shape in `settings_page_overrides` with `!= "POST"`
and left the others behind, so `settings_page_overrides` is parametrised in here
too as a regression lock on the fix that already exists.
"""

import pytest
from django.urls import reverse
from django.utils import timezone

from integrations.models import WebhookEndpoint
from notifications.models import Notification
from tests.factories import make_pa

# Every settings action view. The first five share the `_action` helper, so they
# stand or fall together; the rest carry their own copy of the guard.
ACTION_URL_NAMES = [
    "institution:settings_branding",
    "institution:settings_access",
    "institution:settings_uploads",
    "institution:settings_notifications",
    "institution:settings_public_pages",
    "institution:settings_notifications_purge",
    "institution:settings_sso",
    "institution:settings_integrations",
    "institution:settings_integrations_test",
    "institution:settings_page_overrides",  # already correct since #279
    "institution:settings_support",
]

# The four that fell through. GET is excluded deliberately: it was always
# handled, so including it would let the test pass on the broken build.
NON_POST_METHODS = ["head", "options", "put", "delete"]


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", ACTION_URL_NAMES)
@pytest.mark.parametrize("method", NON_POST_METHODS)
def test_settings_action_redirects_instead_of_running_on_non_post(
    client, url_name, method
):
    """A non-POST is turned away at the door, exactly as a GET is.

    302 rather than 405 follows the contract these views already state ("actions
    are POST targets") and matches #279's fix, so the whole family behaves one
    way. A 200 here means the body rendered -- i.e. the request reached the
    action.
    """
    make_pa(client)

    response = getattr(client, method)(reverse(url_name))

    assert response.status_code == 302, (
        f"{url_name} answered {method.upper()} with {response.status_code}; "
        "a non-POST must be redirected, not executed"
    )


@pytest.mark.django_db
def test_purge_does_not_delete_notifications_on_head(client):
    """The destructive one: HEAD must not run the retention purge.

    An ORPHANED notification (its target row does not exist) is deleted by
    `purge_notifications` regardless of the retention window, so this asserts on
    the purge's own effect and needs no clock control.
    """
    user = make_pa(client)
    orphan = Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type=Notification.TargetType.COURSE,
        target_id=987654321,  # no such Course -> orphaned -> in the purge set
        read_at=timezone.now(),
    )

    client.head(reverse("institution:settings_notifications_purge"))

    assert Notification.objects.filter(pk=orphan.pk).exists(), (
        "HEAD ran purge_notifications() and deleted the row"
    )


@pytest.mark.django_db
def test_integrations_test_does_not_send_event_on_head(client, monkeypatch):
    """The side-effecting one: HEAD must not fire the outbound webhook.

    Patched at the name `views_manage` resolves, not at its definition site, and
    asserting on a real recorded call rather than on a mock's internals. Without
    a configured endpoint the view returns early anyway, so the endpoint is
    filled in first -- otherwise this test would pass on the broken build.
    """
    make_pa(client)
    endpoint = WebhookEndpoint.load()
    endpoint.url = "https://example.invalid/hook"
    endpoint.secret = "s3cret-not-a-real-key"  # noqa: S105
    endpoint.save()

    calls = []
    monkeypatch.setattr(
        "institution.views_manage.send_test_event",
        lambda ep: calls.append(ep) or (True, 200, ""),
    )

    client.head(reverse("institution:settings_integrations_test"))

    assert calls == [], "HEAD fired the outbound test event"


@pytest.mark.django_db
def test_integrations_head_does_not_blank_the_endpoint(client):
    """#279's note called the form views "less dangerous -- they only re-bind a
    form". Not for this one.

    An empty QueryDict makes IntegrationsForm VALID (`enabled` falls to False, so
    clean()'s url/secret requirements never fire), so the fall-through reaches
    `form.save()` and writes the blanks over the stored row. The 302 assertion
    above cannot see this: the save path is the one that redirects.
    """
    make_pa(client)
    endpoint = WebhookEndpoint.load()
    endpoint.enabled = True
    endpoint.url = "https://sis.example.edu/libli-hook"
    endpoint.secret = "s3cret-not-a-real-key"  # noqa: S105
    endpoint.save()

    client.head(reverse("institution:settings_integrations"))

    endpoint.refresh_from_db()
    assert endpoint.url == "https://sis.example.edu/libli-hook", (
        "HEAD blanked the webhook URL"
    )
    assert endpoint.enabled, "HEAD disabled result sync"


@pytest.mark.django_db
def test_sso_head_does_not_disable_a_configured_idp(client):
    """The worst of the form views, for a school actually using SSO.

    save_sso_config's blank no-op only fires when NO row exists. With a row it
    writes name/client_id/server_url as blanks and calls `sites.remove(site)` --
    so one HEAD turns SSO off for the whole school. Most Polish schools are
    Microsoft tenants, so this is the realistic configuration.
    """
    from django.contrib.sites.models import Site

    from accounts.sso_config import is_enabled
    from accounts.sso_config import load_sso_app
    from tests._sso import make_oidc_app

    make_pa(client)
    app = make_oidc_app()
    site = Site.objects.get_current()
    app.sites.add(site)
    assert is_enabled(app, site)  # precondition, not the assertion under test

    client.head(reverse("institution:settings_sso"))

    assert is_enabled(load_sso_app(), site), "HEAD detached the IdP from the site"
    assert load_sso_app().client_id == app.client_id, "HEAD blanked the client id"
