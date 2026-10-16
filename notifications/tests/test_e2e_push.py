"""PWA C2 e2e: push client states, actions and the worker's push handling.

PushManager / Notification are stubbed by an init script (no real push service is
reachable from CI); pywebpush.webpush is patched in the live-server process, so no
test ever reaches a real push service even if it triggers notify(). Logins TICK
"Remember me" -- an unticked login is not-remembered by design (D8).
"""

import json
import os
from unittest import mock

import pytest
from playwright.sync_api import expect

from notifications.models import PushSubscription
from notifications.tests.push_helpers import push_settings
from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user
from tests.pwa_e2e import enable_pwa

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

ENDPOINT = "https://fcm.googleapis.com/fcm/send/e2e-token"

STUB = """
(() => {
  const S = window.__pushStub = JSON.parse(localStorage.getItem("__pushStub") || "{}");
  const save = () => localStorage.setItem("__pushStub", JSON.stringify(S));
  const cfg = JSON.parse(localStorage.getItem("__pushCfg") || "{}");
  if (cfg.ios) {
    Object.defineProperty(navigator, "userAgent", { get: () => cfg.ios === "ipad"
      ? "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
      : "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        + "AppleWebKit/605.1.15" });
    if (cfg.ios === "ipad") {
      Object.defineProperty(navigator, "platform", { get: () => "MacIntel" });
      Object.defineProperty(navigator, "maxTouchPoints", { get: () => 5 });
    }
    delete window.PushManager;
    delete window.Notification;
    return;
  }
  const fakeSub = () => S.sub ? {
    endpoint: S.sub, toJSON: () => ({ endpoint: S.sub, keys: S.keys }),
    unsubscribe: () => { delete S.sub; save(); return Promise.resolve(true); }
  } : null;
  const pm = {
    getSubscription: () => Promise.resolve(fakeSub()),
    subscribe: () => {
      S.sub = cfg.endpoint; S.keys = cfg.keys; save();
      return Promise.resolve(fakeSub());
    }
  };
  Object.defineProperty(ServiceWorkerRegistration.prototype, "pushManager",
    { get: () => pm });
  let perm = cfg.permission || "default";
  Object.defineProperty(Notification, "permission", { get: () => perm });
  Notification.requestPermission = () => {
    perm = cfg.grant || "granted"; return Promise.resolve(perm);
  };
})();
"""

KEYS = {
    "p256dh": "BAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
    "auth": "AgICAgICAgICAgICAgICAg",
}


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(autouse=True)
def _push(settings):
    enable_pwa(settings)
    push_settings(settings)
    with mock.patch("pywebpush.webpush") as webpush:
        yield webpush


def _configure(context, live_server, **cfg):
    cfg.setdefault("endpoint", ENDPOINT)
    cfg.setdefault("keys", KEYS)
    context.add_init_script(
        f"localStorage.setItem('__pushCfg', {json.dumps(json.dumps(cfg))});" + STUB
    )


def _login(page, live_server, username="pushy", remember=True, language="en"):
    user = make_verified_user(username=username, email=f"{username}@example.com")
    user.language = language  # login seeds the session language from the user
    user.save(update_fields=["language"])
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    if remember:
        form.locator("input[name='remember']").check()
    form.locator("button[type='submit']").click()
    # logged in, on the LOGIN_REDIRECT_URL page
    page.wait_for_selector(".bell__trigger")


def _settings(page, live_server, state):
    page.goto(f"{live_server.url}/settings/")
    page.wait_for_selector(f'html[data-push-reported="{state}"]')
    return page.locator("input[data-push-switch]")


def _cookie_login(context, live_server, username="pushy"):
    """Log in WITHOUT visiting any page of the origin first: a force_login session
    cookie (no _session_expiry, i.e. remembered). The next page load is then the
    origin's very first, with no worker registered yet -- the race push.js must win."""
    from django.conf import settings as dj_settings
    from django.test import Client

    user = make_verified_user(username=username, email=f"{username}@example.com")
    client = Client()
    client.force_login(user)
    context.add_cookies(
        [
            {
                "name": dj_settings.SESSION_COOKIE_NAME,
                "value": client.cookies[dj_settings.SESSION_COOKIE_NAME].value,
                "url": live_server.url,
            }
        ]
    )
    return user


def test_first_visit_reads_off_not_unsupported(page, context, live_server):
    # Review Focus 1. Must go RED with push.js's registration() reading
    # navigator.serviceWorker.getRegistration() instead of window.libliSwRegistration.
    _configure(context, live_server)
    _cookie_login(context, live_server)
    # A slow registration, so the race is REACHED: Chromium's getRegistration() finds
    # an INSTALLING registration the moment register() has been called, and pwa.js
    # (deferred, before push.js) calls it first -- measured, the mutant stayed green
    # on a plain first visit. Deferring the real register() call by 500 ms keeps the
    # origin registration-less while push.js evaluates; the published promise still
    # settles well inside push.js's 5 s bound.
    context.add_init_script(
        "(() => { const reg = ServiceWorkerContainer.prototype.register;"
        " ServiceWorkerContainer.prototype.register = function (...args) {"
        " return new Promise((r) => setTimeout(r, 500))"
        ".then(() => reg.apply(this, args)); }; })();"
    )
    # the origin's first page: nothing registered
    page.goto(f"{live_server.url}/settings/")
    page.wait_for_selector("html[data-push-reported]")
    assert page.evaluate("() => document.documentElement.dataset.pushReported") == "off"
    box = page.locator("input[data-push-switch]")
    expect(box).to_be_enabled()
    expect(box).not_to_be_checked()


def test_off_to_on_to_off_posts_and_persists(page, context, live_server):
    _configure(context, live_server)
    _login(page, live_server)
    box = _settings(page, live_server, "off")
    expect(page.locator("[data-push-help]")).to_be_visible()  # visible in off too
    with page.expect_request("**/notifications/push/subscribe/"):
        box.check(force=True)
    page.wait_for_selector('html[data-push-reported="on"]')
    assert PushSubscription.objects.filter(endpoint=ENDPOINT).exists()
    expect(page.locator("[data-push-help]")).to_be_visible()
    with page.expect_request("**/notifications/push/unsubscribe/"):
        page.locator("input[data-push-switch]").uncheck(force=True)
    page.wait_for_selector('html[data-push-reported="off"]')
    assert not PushSubscription.objects.exists()


def test_subscribe_500_rolls_back_and_shows_the_error(page, context, live_server):
    # mutant: the rollback sub.unsubscribe() removed. The claim endpoint answers
    # mine:true here, so the post-action claim step cannot tidy a leftover on the
    # rollback's behalf -- only the rollback itself can leave the stub empty.
    _configure(context, live_server)
    _login(page, live_server)
    page.route(
        "**/notifications/push/subscribe/", lambda r: r.fulfill(status=500, body="{}")
    )
    page.route(
        "**/notifications/push/claim/",
        lambda r: r.fulfill(
            status=200, content_type="application/json", body='{"mine": true}'
        ),
    )
    box = _settings(page, live_server, "off")
    # click(), not check(): the page itself reverts the box on this path, and check()
    # would race that revert ("did not change its state").
    box.click(force=True)
    # The state is already "off" before the POST, so waiting on it would be vacuous;
    # the error line is the synchronisation point, the state the final assertion.
    expect(page.locator("[data-push-device] [data-push-error]")).to_be_visible()
    expect(page.locator("html")).to_have_attribute("data-push-reported", "off")
    assert page.evaluate("() => !window.__pushStub.sub")


def test_switch_disabled_until_a_state_is_reported(page, context, live_server):
    _configure(context, live_server)
    _login(page, live_server)
    page.evaluate(
        "() => { const s = JSON.parse(localStorage.__pushStub || '{}');"
        f" s.sub = '{ENDPOINT}'; localStorage.__pushStub = JSON.stringify(s); }}"
    )
    held = []
    page.route("**/notifications/push/claim/", lambda r: held.append(r))
    page.goto(f"{live_server.url}/settings/")
    for _ in range(100):  # wait for push.js to reach the held claim
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "claim request never sent"
    assert page.evaluate("() => window.libliPush.state") == "pending"
    expect(page.locator("input[data-push-switch]")).to_be_disabled()
    held[0].fulfill(status=200, content_type="application/json", body='{"mine": false}')
    page.wait_for_selector('html[data-push-reported="off"]')
    expect(page.locator("input[data-push-switch]")).to_be_enabled()


@pytest.mark.parametrize(
    "permission,mine,state",
    [
        ("denied", "false", "blocked"),
        ("denied", "true", "blocked"),
        ("default", "false", "off"),
        ("default", "true", "on"),
    ],
)
def test_claim_on_load(page, context, live_server, permission, mine, state):
    _configure(context, live_server, permission=permission)
    _login(page, live_server)
    page.evaluate(
        "() => { const s = JSON.parse(localStorage.__pushStub || '{}');"
        f" s.sub = '{ENDPOINT}'; localStorage.__pushStub = JSON.stringify(s); }}"
    )
    page.route(
        "**/notifications/push/claim/",
        lambda r: r.fulfill(
            status=200, content_type="application/json", body=f'{{"mine": {mine}}}'
        ),
    )
    _settings(page, live_server, state)
    assert page.evaluate("() => !!window.__pushStub.sub") == (mine == "true")


@pytest.mark.parametrize("ios", ["iphone", "ipad"])
def test_ios_outside_the_app_shows_the_install_line(page, context, live_server, ios):
    _configure(context, live_server, ios=ios)
    _login(page, live_server)
    _settings(page, live_server, "ios-not-installed")
    expect(page.locator('[data-push-state="ios-not-installed"]')).to_be_visible()
    expect(page.locator('[data-push-state="unsupported"]')).to_be_hidden()
    expect(page.locator("[data-push-switch-wrap]")).to_be_hidden()


def test_blocked_shows_its_line(page, context, live_server):
    _configure(context, live_server, permission="denied")
    _login(page, live_server)
    _settings(page, live_server, "blocked")
    expect(page.locator('[data-push-state="blocked"]')).to_be_visible()
    expect(page.locator("[data-push-help]")).to_be_hidden()


def test_not_remembered_login_shows_the_d8_line(page, context, live_server):
    _configure(context, live_server)
    _login(page, live_server, remember=False)
    _settings(page, live_server, "not-remembered")
    expect(page.locator('[data-push-state="not-remembered"]')).to_be_visible()
    expect(page.locator("[data-push-switch-wrap]")).to_be_hidden()
    page.locator(".bell__trigger").click()
    expect(page.locator("[data-push-invite]")).to_be_hidden()


def test_registration_refused_reads_unsupported(page, context, live_server):
    context.add_init_script(
        "Object.defineProperty(window, 'libliSwRegistration', "
        "{ get: () => Promise.reject(new Error('refused')), set: () => {} });"
    )
    _configure(context, live_server)
    _login(page, live_server)
    _settings(page, live_server, "unsupported")
    expect(page.locator('[data-push-state="unsupported"]')).to_be_visible()
    page.locator(".bell__trigger").click()
    expect(page.locator("[data-push-invite]")).to_be_hidden()


def test_a_registration_without_push_manager_reads_unsupported(
    page, context, live_server
):
    # mutant: refresh() without its terminal .catch -> the page stays "pending" forever
    context.add_init_script(
        "Object.defineProperty(ServiceWorkerRegistration.prototype, 'pushManager', "
        "{ get: () => undefined });"
    )
    _login(page, live_server)
    _settings(page, live_server, "unsupported")
    expect(
        page.locator('[data-push-device] [data-push-state="unsupported"]')
    ).to_be_visible()


def test_bell_invite_turn_on_dismiss_and_errors(page, context, live_server):
    _configure(context, live_server)
    _login(page, live_server)
    page.wait_for_selector('html[data-push-reported="off"]')
    page.locator(".bell__trigger").click()
    invite = page.locator("[data-push-invite]")
    expect(invite).to_be_visible()
    page.route(
        "**/notifications/push/subscribe/", lambda r: r.fulfill(status=500, body="{}")
    )
    invite.locator("[data-push-invite-on]").click()
    expect(invite.locator("[data-push-error]")).to_be_visible()
    expect(invite).to_be_visible()
    invite.locator("[data-push-invite-dismiss]").click()
    expect(invite).to_be_hidden()
    page.reload()
    page.wait_for_selector('html[data-push-reported="off"]')
    page.locator(".bell__trigger").click()
    expect(page.locator("[data-push-invite]")).to_be_hidden()


def test_denied_prompt_hides_the_invite(page, context, live_server):
    _configure(context, live_server, grant="denied")
    _login(page, live_server)
    page.wait_for_selector('html[data-push-reported="off"]')
    page.locator(".bell__trigger").click()
    page.locator("[data-push-invite-on]").click()
    page.wait_for_selector('html[data-push-reported="blocked"]')
    expect(page.locator("[data-push-invite]")).to_be_hidden()


def test_polish_lines_and_the_quoted_login_label(page, context, live_server):
    _configure(context, live_server)
    page.set_extra_http_headers({"Accept-Language": "pl"})
    page.goto(f"{live_server.url}/accounts/login/")
    assert "Zapamiętaj mnie" in page.content()  # the label the D8 line quotes
    _login(page, live_server, remember=False, language="pl")
    _settings(page, live_server, "not-remembered")
    line = page.locator('[data-push-state="not-remembered"]').inner_text()
    assert "Zapamiętaj mnie" in line


@pytest.mark.parametrize("case", ["ios", "unsupported", "not-remembered", "blocked"])
def test_help_line_hidden_in_every_cannot_state(page, context, live_server, case):
    if case == "unsupported":
        context.add_init_script(
            "Object.defineProperty(window, 'libliSwRegistration', "
            "{ get: () => Promise.reject(new Error('refused')), set: () => {} });"
        )
    _configure(
        context,
        live_server,
        **({"ios": "iphone"} if case == "ios" else {}),
        **({"permission": "denied"} if case == "blocked" else {}),
    )
    _login(page, live_server, remember=case != "not-remembered")
    state = {"ios": "ios-not-installed"}.get(case, case)
    _settings(page, live_server, state)
    expect(page.locator("[data-push-help]")).to_be_hidden()


def test_blocked_with_a_foreign_leftover_deletes_the_server_row(
    page, context, live_server
):
    # The REAL claim endpoint (no page.route): another user's row for this browser's
    # endpoint is deleted, the browser unsubscribes, and the state still reads blocked.
    from notifications.tests.push_helpers import make_sub
    from tests.factories import UserFactory

    _configure(context, live_server, permission="denied")
    _login(page, live_server)
    make_sub(UserFactory(), "x" * 32, endpoint=ENDPOINT)
    page.evaluate(
        "() => { const s = JSON.parse(localStorage.__pushStub || '{}');"
        f" s.sub = '{ENDPOINT}'; localStorage.__pushStub = JSON.stringify(s); }}"
    )
    _settings(page, live_server, "blocked")
    assert not PushSubscription.objects.filter(endpoint=ENDPOINT).exists()
    assert page.evaluate("() => !window.__pushStub.sub")


def test_worker_refuses_off_origin_targets(page, context, live_server):
    # notificationclick itself cannot be driven: Playwright cannot click an OS
    # notification, and dispatching a synthetic NotificationEvent needs a real
    # Notification object. So its two decisions are tested through the named
    # helper, and the openWindow fallback is on the device checklist (PR body).
    _login(page, live_server)
    page.evaluate("async () => { await navigator.serviceWorker.ready; }")
    worker = (
        context.service_workers[0]
        if context.service_workers
        else context.wait_for_event("serviceworker")
    )
    assert worker.evaluate("targetUrl('https://evil.example/x')") is None
    assert (
        worker.evaluate("targetUrl('/notifications/5/open/')")
        == f"{live_server.url}/notifications/5/open/"
    )


def test_worker_shows_a_delivered_push(
    browser_type, browser_type_launch_args, live_server
):
    # Its own browser, the FULL Chromium build (channel "chromium", new headless):
    # the default chromium-headless-shell keeps Notification.permission "denied"
    # whatever grant_permissions says (navigator.permissions reads "granted"), so
    # showNotification() rejects there and no notification could ever be listed.
    browser = browser_type.launch(**{**browser_type_launch_args, "channel": "chromium"})
    try:
        context = browser.new_context()
        context.grant_permissions(["notifications"], origin=live_server.url)
        page = context.new_page()
        _login(page, live_server)
        page.evaluate("async () => { await navigator.serviceWorker.ready; }")
        assert page.evaluate("() => Notification.permission") == "granted"
        cdp = context.new_cdp_session(page)
        regs = []
        cdp.on(
            "ServiceWorker.workerRegistrationUpdated",
            lambda e: regs.extend(e["registrations"]),
        )
        cdp.send("ServiceWorker.enable")
        for _ in range(50):
            if any(not r.get("isDeleted") for r in regs):
                break
            page.wait_for_timeout(100)
        reg_id = next(r["registrationId"] for r in regs if not r.get("isDeleted"))
        payload = {
            "title": "T",
            "body": "B",
            "url": "/notifications/",
            "tag": "libli-1",
            "icon": "",
        }
        cdp.send(
            "ServiceWorker.deliverPushMessage",
            {
                "origin": live_server.url,
                "registrationId": reg_id,
                "data": json.dumps(payload),
            },
        )
        check = """async () => {
          const reg = await navigator.serviceWorker.ready;
          const list = await reg.getNotifications({ tag: 'libli-1' });
          return list.length === 1 && list[0].title === 'T' && list[0].body === 'B';
        }"""
        # NOT wait_for_function: an async predicate returns a Promise, which is truthy.
        shown = False
        for _ in range(50):
            shown = page.evaluate(check)
            if shown:
                break
            page.wait_for_timeout(100)
        assert shown
    finally:
        browser.close()
