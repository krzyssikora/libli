# PWA C2 Web Push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver libli's three existing notification kinds as web push notifications to opted-in devices, tied to the user's live, remembered login session.

**Architecture:** A new `notifications/push.py` holds every push decision (configuration gate, remembered-login predicate, live-session filter, payload, per-request budget, delivery). `notify()` registers a second on_commit callback beside the email one. Three JSON endpoints (subscribe / unsubscribe / claim) and a GET tap-through view live in `notifications/push_views.py`. The browser side is a new `core/static/core/js/push.js` driving server-rendered, hidden markup in the settings page and the bell panel; the C1 worker (`templates/core/sw.js`) gains `push` and `notificationclick` handlers.

**Tech Stack:** Django 5.2, django-allauth 65.18, `pywebpush` (new), `cryptography` (via pywebpush), Playwright (pytest-playwright) for e2e, plain ES5-style JS (no build step), gettext catalogs in `locale/`.

**Spec:** `docs/superpowers/specs/2026-10-16-pwa-c2-web-push-design.md` — read it beside this plan. Owner decisions D1–D8 in its table are VERBATIM and must not be reversed by any reviewer or implementer.

## Global Constraints

- Settings: `PUSH_VAPID_PUBLIC_KEY` ← `LIBLI_VAPID_PUBLIC_KEY`, `PUSH_VAPID_PRIVATE_KEY` ← `LIBLI_VAPID_PRIVATE_KEY`, `PUSH_VAPID_SUBJECT` ← `LIBLI_VAPID_SUBJECT`, all default `""`. Test settings pin all three to `""`.
- `push_configured()` = all three non-blank AND subject starts `mailto:` or `https:` AND `core.pwa.serve_normal()`. Everything is gated on it EXCEPT `notifications:open` and the logout receiver.
- `PUSH_ENDPOINT_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "push.apple.com", "notify.windows.com")`, exact or dot-suffix match.
- Constants: `MAX_SUBSCRIPTIONS_PER_USER = 5`, `PUSH_TIMEOUT = 5`, `PUSH_TTL = 86400`, `PUSH_BUDGET_SECONDS = 10.0`.
- Keys: `p256dh` decodes to 65 bytes starting `0x04`; `auth` decodes to 16 bytes; base64url, padding optional.
- Payload JSON keys exactly: `title`, `body`, `url`, `tag` (`libli-<pk>`), `icon`.
- Session entry name: `request.session["push_endpoint"]`.
- localStorage flag: `libli:push-invite-dismissed`.
- Endpoint check order (CSRF-valid requests): not configured → 404; anonymous → 403 `{"ok": false}`; subscribe in a non-remembered session → 403 `{"ok": false}`; malformed body → 400.
- `NotificationPushForm` is ALWAYS constructed with `prefix="push"`, and only when `push_configured()`.
- push.js builds no user-facing text; every string is server-rendered with `{% trans %}`.
- Polish quotes the login label exactly: „Zapamiętaj mnie”.
- No FORMAT_VERSION bump. One migration: `notifications/0003_push.py`, depending on `0002_notificationemailpreference` (the graph head — verify with `ls notifications/migrations` before writing it).
- Django `{# #}` comments are single-line ONLY; use `{% comment %}…{% endcomment %}` for anything longer.
- No new password or secret literals anywhere (GitGuardian scans code AND markdown): passwords are `tests.factories.TEST_PASSWORD`; a different secret is DERIVED (e.g. `settings.SECRET_KEY[::-1] + "x"`).
- A test client that must stay logged in uses `push_helpers.logged_in_user(client)` (a verified, persisted user) — NEVER `UserFactory()` + `force_login`, which leaves the client silently anonymous. `UserFactory()` is fine for users never logged in through the client.
- Before EVERY commit: `uv run ruff format <touched .py files>` then `uv run ruff check --no-cache <touched .py files>`. The line limit is 88 (`E501`); `ruff format` cannot shorten comments or long string literals, so wrap comments and split long strings by implicit concatenation (e.g. Task 3's mutant comments, the budget warning text, the e2e `KEYS` literal, Task 11's `NEW` entries). Code blocks in this plan may exceed 88 where a sentence reads better unbroken — the implementer wraps them.
- Never pass `-q` to pytest (addopts already has it). e2e needs `-m e2e`. Run tests with `uv run pytest`.
- Every new guard is falsified against its named mutant (shown RED, then reverted BY HAND — never `git checkout` a file holding uncommitted work).

## Spec deviation recorded here (technical, not an owner decision)

- **Where push.js gets its registration.** Spec §6 says `navigator.serviceWorker.getRegistration()`. On the FIRST page load after login, `pwa.js`'s `register()` may not have resolved yet, so `getRegistration()` returns `undefined` and the page would wrongly read `unsupported` until a reload. So `pwa.js` publishes its `register()` promise as `window.libliSwRegistration`, and push.js awaits THAT, bounded by a 5 s timeout (`.catch` → `undefined` → `unsupported`). Like `getRegistration()` and unlike `ready`, it always settles, so the spec's intent (never hang the switch) is preserved.

## Review Focus

1. **First visit after login, worker not yet registered** — the device switch must reach a real state (`off`), not `unsupported`. Test: Task 10 `test_first_visit_reads_off_not_unsupported`.
2. **A notification row whose `data` lacks `course_slug`** (old rows, bogus kinds) — push must not raise into on_commit and the tap target must fall back to the list. Tests: Task 3 `test_unknown_kind_is_swallowed`, Task 5 `test_unreversible_target_falls_back_to_list`.
3. **Settings POST from a page rendered before push was configured** (the push fields simply absent) while push IS now configured — the push preferences flip to False. That matches how the email form already treats an absent checkbox, and is accepted; the guard is that the EMAIL row is untouched. Test: Task 6 `test_post_without_push_fields_turns_push_off_but_leaves_email`.
4. **A subscribe body with extra / wrong-typed fields** (`keys` a string, `endpoint` a number) — 400, never 500. Test: Task 4 `test_wrong_types_are_400`.
5. **Logout through allauth's own GET confirmation page** — the server receiver still deletes the row. Test: Task 4 `test_logout_via_confirmation_page_still_deletes`.

---

## File map

| File | Responsibility |
|---|---|
| `pyproject.toml`, `uv.lock` | add `pywebpush` |
| `config/settings/base.py`, `config/settings/test.py` | VAPID settings; test pins |
| `.env.production.example` | document the three env vars |
| `notifications/push.py` (new) | gate, predicates, validation, live-session filter, payload, budget, delivery |
| `notifications/models.py` | `PushSubscription`, `NotificationPushPreference` |
| `notifications/migrations/0003_push.py` (new) | the two tables |
| `notifications/services.py` | `notify()` registers the push callback |
| `notifications/signals.py` (new) | `request_started` budget reset; `user_logged_out` cleanup |
| `notifications/apps.py` | `ready()` imports signals |
| `notifications/push_views.py` (new), `notifications/urls.py` | subscribe / unsubscribe / claim / open |
| `notifications/context_processors.py` (new) | `push_available` + meta values |
| `notifications/forms.py` | `NotificationPushForm` |
| `notifications/management/commands/generate_vapid_keys.py` (new) | print a key pair |
| `core/views.py` | settings view binds the push form |
| `templates/base.html` | meta, push.js include, `data-logout-form` |
| `templates/core/user_settings.html` | Notifications section |
| `notifications/templates/notifications/_bell_panel.html` | bell invite row |
| `core/static/core/css/settings.css`, `core/static/core/css/app.css` | column headers, invite row |
| `core/static/core/js/pwa.js` | publish `window.libliSwRegistration` |
| `core/static/core/js/push.js` (new) | device state, claim, subscribe/unsubscribe, UI toggling |
| `templates/core/sw.js` | `push` + `notificationclick` |
| `conftest.py` | autouse `reset_push_budget()` |
| `locale/{pl,en}/LC_MESSAGES/django.{po,mo}` | new msgids |
| `docs/deployment.md` | "Push notifications" runbook + restore line |
| tests (new) | `notifications/tests/test_push_*.py`, `notifications/tests/test_e2e_push.py`, `tests/test_push_runbook.py` |

---

### Task 1: Dependency, settings, and the pure push predicates

**Files:**
- Modify: `pyproject.toml` (dependencies list), `uv.lock`
- Modify: `config/settings/base.py` (after the `PWA_CACHE_UNHASHED_STATIC` block, ~line 301)
- Modify: `config/settings/test.py` (after the `PWA_KILL_SWITCH = False` line)
- Modify: `.env.production.example` (after the `# --- pwa ---` block)
- Create: `notifications/push.py`
- Create: `notifications/management/commands/generate_vapid_keys.py`
- Test: `notifications/tests/test_push_config.py`

**Interfaces:**
- Produces: `notifications.push.push_configured() -> bool`; `remembered_from_data(data: Mapping) -> bool`; `endpoint_host_allowed(endpoint: str) -> bool`; `decode_b64url(value: str) -> bytes | None`; `clean_subscription(body) -> tuple[str, str, str] | None` (endpoint, p256dh, auth); `generate_vapid_pair() -> tuple[str, str]` (public_b64url, private_b64url); constants listed in Global Constraints.

- [ ] **Step 1: Add the dependency**

Run: `uv add "pywebpush>=2.0,<3.0"`
Expected: `pyproject.toml` gains `"pywebpush>=2.0,<3.0",` and `uv.lock` updates. Then `uv run python -c "import pywebpush, cryptography; print(pywebpush.__name__)"` prints `pywebpush`.

- [ ] **Step 2: Add the settings**

In `config/settings/base.py`, after `PWA_CACHE_UNHASHED_STATIC = False`:

```python
# Web push (docs/superpowers/specs/2026-10-16-pwa-c2-web-push-design.md). Per-box
# VAPID keys; with any of the three blank, push is entirely hidden and nothing is
# sent (notifications.push.push_configured). Generate with `manage.py
# generate_vapid_keys`. The subject must start with mailto: or https:.
PUSH_VAPID_PUBLIC_KEY = env("LIBLI_VAPID_PUBLIC_KEY", default="")
PUSH_VAPID_PRIVATE_KEY = env("LIBLI_VAPID_PRIVATE_KEY", default="")
PUSH_VAPID_SUBJECT = env("LIBLI_VAPID_SUBJECT", default="")
```

In `config/settings/test.py`, after `PWA_KILL_SWITCH = False`:

```python
# Pinned for the same reason: a developer's .env may carry real VAPID keys. Tests
# that exercise push opt in with the settings fixture (tests use push_settings()).
PUSH_VAPID_PUBLIC_KEY = ""
PUSH_VAPID_PRIVATE_KEY = ""
PUSH_VAPID_SUBJECT = ""
```

In `.env.production.example`, after the `# LIBLI_PWA_ENABLED=false` line:

```
# --- push ---
# Web push keys, PER BOX (never copy them between schools; never rotate a key in
# use). Generate with: bash manage.sh generate_vapid_keys
# All three blank = push hidden. The subject starts with mailto: (libli's convention)
# or https:; anything else turns push off (runbook §9).
LIBLI_VAPID_PUBLIC_KEY=
LIBLI_VAPID_PRIVATE_KEY=
LIBLI_VAPID_SUBJECT=
```

- [ ] **Step 3: Write the failing tests**

Create `notifications/tests/test_push_config.py`:

```python
"""PWA C2 §1/§4: the configuration gate and the pure push predicates."""

import base64

import pytest
from allauth.account import app_settings as allauth_settings
from django.conf import settings as dj_settings
from django.core.management import call_command

from notifications import push

GOOD_P256DH = base64.urlsafe_b64encode(b"\x04" + b"\x01" * 64).decode().rstrip("=")
GOOD_AUTH = base64.urlsafe_b64encode(b"\x02" * 16).decode().rstrip("=")
FCM = "https://fcm.googleapis.com/fcm/send/abc123"


def configure(settings, **over):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    settings.PUSH_VAPID_PUBLIC_KEY = over.get("public", "pub")
    settings.PUSH_VAPID_PRIVATE_KEY = over.get("private", "priv")
    settings.PUSH_VAPID_SUBJECT = over.get("subject", "mailto:ops@example.com")


def test_configured_when_everything_set(settings):
    configure(settings)
    assert push.push_configured() is True


def test_https_subject_is_accepted(settings):
    configure(settings, subject="https://school.example")
    assert push.push_configured() is True


@pytest.mark.parametrize(
    "over",
    [{"public": ""}, {"private": ""}, {"subject": ""}, {"subject": "ops@example.com"}],
)
def test_not_configured_when_a_value_is_missing_or_bad(settings, over):
    configure(settings, **over)
    assert push.push_configured() is False


def test_not_configured_without_the_worker(settings):
    configure(settings)
    settings.PWA_ENABLED = False
    assert push.push_configured() is False


def test_not_configured_under_the_kill_switch(settings):
    configure(settings)
    settings.PWA_KILL_SWITCH = True
    assert push.push_configured() is False


def test_suite_default_is_not_configured():
    assert push.push_configured() is False


# --- remembered_from_data (D8) -------------------------------------------------


def test_absent_expiry_is_remembered_by_default():
    assert push.remembered_from_data({}) is True


def test_absent_expiry_follows_the_browser_close_setting(settings):
    # mutant "fallback dropped": `return data.get("_session_expiry") != 0`
    settings.SESSION_EXPIRE_AT_BROWSER_CLOSE = True
    assert push.remembered_from_data({}) is False


def test_zero_expiry_is_not_remembered():
    assert push.remembered_from_data({"_session_expiry": 0}) is False


def test_positive_expiry_is_remembered():
    assert push.remembered_from_data({"_session_expiry": 1209600}) is True


def test_pins_the_session_backend_d7_depends_on():
    assert dj_settings.SESSION_ENGINE == "django.contrib.sessions.backends.db"


def test_pins_allauth_remember_me_unset_d8_depends_on():
    assert allauth_settings.SESSION_REMEMBER is None


# --- endpoint host allowlist -----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://fcm.googleapis.com/fcm/send/x",
        "https://updates.push.services.mozilla.com/wpush/v2/x",
        "https://web.push.apple.com/x",
        "https://wns2-par02p.notify.windows.com/w/?token=x",
    ],
)
def test_known_push_hosts_are_allowed(url):
    assert push.endpoint_host_allowed(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/x",
        "https://localhost/x",
        "https://fcm.googleapis.com.evil.example/x",
        "https://evilfcm.googleapis.com/x",
        "http://fcm.googleapis.com/x",
        "https:///x",
        "not a url",
    ],
)
def test_other_hosts_are_refused(url):
    assert push.endpoint_host_allowed(url) is False


# --- subscription body validation ------------------------------------------------


def _body(**over):
    body = {"endpoint": FCM, "keys": {"p256dh": GOOD_P256DH, "auth": GOOD_AUTH}}
    body.update(over)
    return body


def test_clean_subscription_accepts_a_good_body():
    assert push.clean_subscription(_body()) == (FCM, GOOD_P256DH, GOOD_AUTH)


def test_padded_base64_is_accepted():
    padded = base64.urlsafe_b64encode(b"\x02" * 16).decode()
    assert push.clean_subscription(_body(keys={"p256dh": GOOD_P256DH, "auth": padded}))


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "x",
        {"endpoint": FCM},
        {"endpoint": 5, "keys": {"p256dh": GOOD_P256DH, "auth": GOOD_AUTH}},
        {"endpoint": FCM, "keys": "nope"},
        {"endpoint": "https://evil.example/x", "keys": {"p256dh": GOOD_P256DH, "auth": GOOD_AUTH}},
        {"endpoint": FCM + "x" * 1024, "keys": {"p256dh": GOOD_P256DH, "auth": GOOD_AUTH}},
        # p256dh of the wrong decoded length
        {"endpoint": FCM, "keys": {"p256dh": GOOD_AUTH, "auth": GOOD_AUTH}},
        # p256dh not starting 0x04
        {
            "endpoint": FCM,
            "keys": {
                "p256dh": base64.urlsafe_b64encode(b"\x05" + b"\x01" * 64).decode(),
                "auth": GOOD_AUTH,
            },
        },
        # auth not 16 bytes
        {"endpoint": FCM, "keys": {"p256dh": GOOD_P256DH, "auth": GOOD_P256DH}},
        # not base64url
        {"endpoint": FCM, "keys": {"p256dh": "!!!", "auth": GOOD_AUTH}},
    ],
)
def test_clean_subscription_refuses_bad_bodies(body):
    assert push.clean_subscription(body) is None


# --- key generation --------------------------------------------------------------


def test_generated_pair_has_protocol_sizes():
    public, private = push.generate_vapid_pair()
    assert len(push.decode_b64url(public)) == 65
    assert push.decode_b64url(public)[0] == 4
    assert len(push.decode_b64url(private)) == 32


def test_command_prints_env_lines(capsys):
    call_command("generate_vapid_keys")
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("LIBLI_VAPID_PUBLIC_KEY=")
    assert out[1].startswith("LIBLI_VAPID_PRIVATE_KEY=")
    assert len(push.decode_b64url(out[0].split("=", 1)[1])) == 65
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest notifications/tests/test_push_config.py`
Expected: FAIL — `ImportError: cannot import name 'push' from 'notifications'`.

- [ ] **Step 5: Write `notifications/push.py` (predicates only; later tasks extend it)**

```python
"""Web push (PWA C2): every push decision lives here.

Spec: docs/superpowers/specs/2026-10-16-pwa-c2-web-push-design.md. This module
top-level-imports only Django and the notifications models; email_content is
imported function-locally (emails.py top-level-imports services.py, and
services.notify imports THIS module function-locally).
"""

import base64
import binascii
import logging
import re
from urllib.parse import urlsplit

from django.conf import settings

logger = logging.getLogger(__name__)

# Real push services only (spec §4). Matched exactly or as a dot-suffix, so
# "evilfcm.googleapis.com" and "fcm.googleapis.com.evil.example" are refused.
PUSH_ENDPOINT_HOSTS = (
    "fcm.googleapis.com",  # Chrome, Edge on Android, Samsung Internet
    "push.services.mozilla.com",  # Firefox
    "push.apple.com",  # Safari, iOS home-screen apps
    "notify.windows.com",  # Edge on Windows
)
MAX_ENDPOINT_LENGTH = 1024
MAX_SUBSCRIPTIONS_PER_USER = 5
PUSH_TIMEOUT = 5
PUSH_TTL = 86400
PUSH_BUDGET_SECONDS = 10.0

_B64URL = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def push_configured():
    """True only when this box can actually deliver a push (spec §1)."""
    from core.pwa import serve_normal

    subject = settings.PUSH_VAPID_SUBJECT or ""
    return bool(
        settings.PUSH_VAPID_PUBLIC_KEY
        and settings.PUSH_VAPID_PRIVATE_KEY
        and subject.startswith(("mailto:", "https:"))
        and serve_normal()
    )


def remembered_from_data(data):
    """D8: is this login meant to outlive the browser? `data` is any mapping with
    .get(): request.session itself, or Session.get_decoded(). Same fallback as
    SessionBase.get_expire_at_browser_close()."""
    expiry = data.get("_session_expiry")
    if expiry is None:
        return not settings.SESSION_EXPIRE_AT_BROWSER_CLOSE
    return expiry != 0


def endpoint_host_allowed(endpoint):
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in PUSH_ENDPOINT_HOSTS)


def decode_b64url(value):
    if not isinstance(value, str) or not _B64URL.match(value):
        return None
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        return None


def clean_subscription(body):
    """(endpoint, p256dh, auth) from a PushSubscription.toJSON() body, or None."""
    if not isinstance(body, dict):
        return None
    endpoint = body.get("endpoint")
    keys = body.get("keys")
    if not isinstance(endpoint, str) or not isinstance(keys, dict):
        return None
    if len(endpoint) > MAX_ENDPOINT_LENGTH or not endpoint_host_allowed(endpoint):
        return None
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    raw_p, raw_a = decode_b64url(p256dh), decode_b64url(auth)
    if raw_p is None or raw_a is None:
        return None
    if len(raw_p) != 65 or raw_p[0] != 4 or len(raw_a) != 16:
        return None
    if len(p256dh) > 128 or len(auth) > 64:
        return None
    return endpoint, p256dh, auth


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def generate_vapid_pair():
    """(public, private): the uncompressed P-256 point PushManager.subscribe takes,
    and the raw 32-byte scalar pywebpush accepts, both base64url without padding."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(public), _b64url(private)
```

Create `notifications/management/commands/generate_vapid_keys.py` (the `management/commands/` package already exists — it holds the purge command; check with `ls notifications/management/commands`):

```python
from django.core.management.base import BaseCommand

from notifications.push import generate_vapid_pair


class Command(BaseCommand):
    help = "Print a fresh VAPID key pair as .env.production lines. Writes nothing."

    def handle(self, *args, **options):
        public, private = generate_vapid_pair()
        self.stdout.write(f"LIBLI_VAPID_PUBLIC_KEY={public}")
        self.stdout.write(f"LIBLI_VAPID_PRIVATE_KEY={private}")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest notifications/tests/test_push_config.py`
Expected: PASS (all).

- [ ] **Step 7: Falsify**

Replace `remembered_from_data`'s body with `return data.get("_session_expiry") != 0` → `test_absent_expiry_follows_the_browser_close_setting` FAILS. Change `host.endswith("." + h)` to `host.endswith(h)` → `test_other_hosts_are_refused[https://evilfcm.googleapis.com/x]` FAILS. Revert both by hand; re-run green.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock config/settings/base.py config/settings/test.py .env.production.example notifications/push.py notifications/management/commands/generate_vapid_keys.py notifications/tests/test_push_config.py
git commit -m "feat(push): VAPID settings, push predicates and generate_vapid_keys"
```

---

### Task 2: Models and migration

**Files:**
- Modify: `notifications/models.py` (append)
- Create: `notifications/migrations/0003_push.py` (via makemigrations)
- Modify: `notifications/push.py` (add `push_kind_enabled`)
- Test: `notifications/tests/test_push_models.py`

**Interfaces:**
- Produces: `PushSubscription` (fields per spec §2), `NotificationPushPreference` (OneToOne `user`, booleans `quiz_needs_review`, `quiz_graded`, `enrolled`, default True); `notifications.push.push_kind_enabled(user, kind) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `notifications/tests/test_push_models.py`:

```python
import pytest
from django.db import IntegrityError
from django.utils import timezone

from notifications.models import NotificationPushPreference
from notifications.models import PushSubscription
from notifications.push import push_kind_enabled
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def make_sub(user, endpoint="https://fcm.googleapis.com/fcm/send/a", **kw):
    kw.setdefault("p256dh", "p")
    kw.setdefault("auth", "a")
    kw.setdefault("subscribed_at", timezone.now())
    kw.setdefault("session_key", "k" * 32)
    return PushSubscription.objects.create(user=user, endpoint=endpoint, **kw)


def test_endpoint_is_unique_across_users():
    make_sub(UserFactory())
    with pytest.raises(IntegrityError):
        make_sub(UserFactory())


def test_deleting_the_user_deletes_subscriptions():
    user = UserFactory()
    make_sub(user)
    user.delete()
    assert PushSubscription.objects.count() == 0


def test_no_preference_row_means_every_kind_on():
    user = UserFactory()
    for kind in ("quiz_needs_review", "quiz_graded", "enrolled"):
        assert push_kind_enabled(user, kind) is True


def test_preference_row_turns_one_kind_off():
    user = UserFactory()
    NotificationPushPreference.objects.create(user=user, quiz_graded=False)
    assert push_kind_enabled(user, "quiz_graded") is False
    assert push_kind_enabled(user, "enrolled") is True


def test_str_methods():
    user = UserFactory()
    assert str(user.pk) in str(make_sub(user))
    assert str(user.pk) in str(NotificationPushPreference.objects.create(user=user))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest notifications/tests/test_push_models.py`
Expected: FAIL — `ImportError: cannot import name 'NotificationPushPreference'`.

- [ ] **Step 3: Add the models**

Append to `notifications/models.py`:

```python
class PushSubscription(models.Model):
    """One subscribed browser (PWA C2 spec §2). Delivers only while the login session
    named by session_key is live, authenticated as `user` and remembered (D7, D8)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    endpoint = models.URLField(max_length=1024, unique=True)
    p256dh = models.CharField(max_length=128)
    auth = models.CharField(max_length=64)
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set on every subscribe upsert; orders the 5-device cap (created_at would keep
    # a re-subscribed endpoint looking old).
    subscribed_at = models.DateTimeField()
    last_success_at = models.DateTimeField(null=True, blank=True)
    session_key = models.CharField(max_length=40, db_index=True)

    def __str__(self):
        return f"push subscription {self.pk} for {self.user_id}"


class NotificationPushPreference(models.Model):
    """Per-user, per-kind opt-out for PUSH (mirrors NotificationEmailPreference).
    Absence of a row = all-on. Field names equal the Notification.Kind values."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_push_pref",
    )
    quiz_needs_review = models.BooleanField(default=True)
    quiz_graded = models.BooleanField(default=True)
    enrolled = models.BooleanField(default=True)

    def __str__(self):
        return f"push prefs for {self.user_id}"
```

Append to `notifications/push.py`:

```python
def push_kind_enabled(user, kind):
    """True when the user has no push preference row (default-on), else the per-kind
    boolean. An unknown kind raises later -- AttributeError here when a row exists, else
    ValueError in email_content -- and delivery swallows both."""
    from notifications.models import NotificationPushPreference

    pref = NotificationPushPreference.objects.filter(user=user).first()
    if pref is None:
        return True
    return getattr(pref, kind)
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations notifications --name push`
Expected: creates `notifications/migrations/0003_push.py`. Open it and confirm `dependencies` lists `("notifications", "0002_notificationemailpreference")` and the user model swappable dependency. Then `uv run python manage.py makemigrations --check --dry-run` prints `No changes detected`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest notifications/tests/test_push_models.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add notifications/models.py notifications/migrations/0003_push.py notifications/push.py notifications/tests/test_push_models.py
git commit -m "feat(push): PushSubscription and NotificationPushPreference models"
```

---

### Task 3: Sending — live-session filter, payload, budget, delivery, wiring

**Files:**
- Modify: `notifications/push.py` (append)
- Modify: `notifications/services.py:38-63` (`notify`)
- Create: `notifications/signals.py`
- Modify: `notifications/apps.py`
- Create: `notifications/push_views.py` (the open view only; Task 4 adds the endpoints)
- Modify: `notifications/urls.py` (the `open` route)
- Modify: `conftest.py` (root; add an autouse fixture after `_reset_active_language`)
- Test: `notifications/tests/test_push_delivery.py`, `notifications/tests/test_push_sessions.py`, `notifications/tests/test_push_budget.py`, `notifications/tests/push_helpers.py` (new helper module)

**Interfaces:**
- Consumes: Task 1 predicates, Task 2 models.
- Produces: `live_subscriptions(user) -> list[PushSubscription]`; `build_payload(notification) -> str`; `deliver_notification_push(notification) -> None`; `reset_push_budget() -> None`; `notifications/tests/push_helpers.py` with `push_settings(settings)`, `logged_in_user(client, **attrs) -> User`, `live_session_for(user, *, remembered=True) -> str` (session key), `make_sub(user, session_key, endpoint=...)`, `FCM`, `MOZ` endpoint constants.

- [ ] **Step 1: Write the shared test helpers**

Create `notifications/tests/push_helpers.py`:

```python
"""Shared fixtures-as-functions for the push tests."""

import itertools

from django.contrib.auth import BACKEND_SESSION_KEY
from django.contrib.auth import HASH_SESSION_KEY
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.utils import timezone

from notifications.models import PushSubscription
from notifications.push import generate_vapid_pair

FCM = "https://fcm.googleapis.com/fcm/send/"
MOZ = "https://updates.push.services.mozilla.com/wpush/v2/"

_PAIR = generate_vapid_pair()
_SEQ = itertools.count()


def push_settings(settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    settings.PUSH_VAPID_PUBLIC_KEY, settings.PUSH_VAPID_PRIVATE_KEY = _PAIR
    settings.PUSH_VAPID_SUBJECT = "mailto:ops@example.com"


def logged_in_user(client, **attrs):
    """A user the test client STAYS logged in as. Never UserFactory()+force_login:
    UserFactory skips the post-generation save, so the persisted password differs
    from the in-memory one, the session hash mismatches on the next request and the
    client is silently anonymous (see tests/test_notes_views.py:_stranger)."""
    from tests.factories import make_verified_user

    n = next(_SEQ)
    user = make_verified_user(username=f"pushuser{n}", email=f"pushuser{n}@example.com")
    for key, value in attrs.items():
        setattr(user, key, value)
    if attrs:
        user.save()
    client.force_login(user)
    return user


def live_session_for(user, *, remembered=True):
    """A real DB session authenticated as `user`, like a login would leave.

    Saves the user's password FIRST: UserFactory skips the post-generation save, so
    its in-memory password (which Notification.recipient and live_subscriptions see --
    nothing reloads it) differs from the persisted one. Persisting it makes both agree,
    so a later user.save() (is_active, language) no longer changes the hash on its own
    and each session test fails only through the check it targets."""
    user.save(update_fields=["password"])
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    store[HASH_SESSION_KEY] = user.get_session_auth_hash()
    if not remembered:
        store.set_expiry(0)
    store.create()
    return store.session_key


def make_sub(user, session_key, endpoint=None, **kw):
    kw.setdefault("p256dh", "BPp")
    kw.setdefault("auth", "aa")
    kw.setdefault("subscribed_at", timezone.now())
    return PushSubscription.objects.create(
        user=user,
        endpoint=endpoint or f"{FCM}{PushSubscription.objects.count()}-{user.pk}",
        session_key=session_key,
        **kw,
    )
```

- [ ] **Step 2: Write the failing session-filter tests**

Create `notifications/tests/test_push_sessions.py`:

```python
"""D7 + D8: a subscription delivers only while its session is live, authenticated
as its user, with a current auth hash, an active user and a remembered login."""

from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.sessions.models import Session
from django.utils import timezone

from notifications.models import PushSubscription
from notifications.push import live_subscriptions
from notifications.tests.push_helpers import live_session_for
from notifications.tests.push_helpers import make_sub
from tests.factories import TEST_PASSWORD
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_live_remembered_session_is_kept():
    user = UserFactory()
    sub = make_sub(user, live_session_for(user))
    assert live_subscriptions(user) == [sub]


def test_missing_session_is_dropped_and_deleted():
    # mutant "filter removed": return every row
    user = UserFactory()
    make_sub(user, "nosuchsession0000000000000000000")
    assert live_subscriptions(user) == []
    assert PushSubscription.objects.count() == 0


def test_expired_session_row_still_present_is_dropped():
    # mutant "existence only": Session.objects.filter(session_key__in=keys) without expire_date
    user = UserFactory()
    key = live_session_for(user)
    Session.objects.filter(session_key=key).update(
        expire_date=timezone.now() - timedelta(seconds=1)
    )
    make_sub(user, key)
    assert live_subscriptions(user) == []
    assert PushSubscription.objects.count() == 0


def test_session_of_another_user_is_dropped():
    # mutant: drop the _auth_user_id check. ONLY the id is wrong -- the stored hash is
    # still user's own, so the hash check cannot drop the row on this test's behalf.
    from django.contrib.auth import SESSION_KEY
    from django.contrib.sessions.backends.db import SessionStore

    user, other = UserFactory(), UserFactory()
    key = live_session_for(user)
    store = SessionStore(session_key=key)
    store[SESSION_KEY] = str(other.pk)
    store.save()
    make_sub(user, key)
    assert live_subscriptions(user) == []


def test_password_changed_elsewhere_is_dropped():
    # mutant: drop the auth-hash check
    user = UserFactory()
    make_sub(user, live_session_for(user))
    user.set_password(TEST_PASSWORD)  # differs from UserFactory's password
    user.save()
    assert live_subscriptions(user) == []


def test_fallback_secret_hash_is_still_live(settings):
    user = UserFactory()
    settings.SECRET_KEY_FALLBACKS = [settings.SECRET_KEY]
    key = live_session_for(user)  # hash made with the (now fallback) key
    settings.SECRET_KEY = settings.SECRET_KEY[::-1] + "x"  # derived: no secret literal
    make_sub(user, key)
    assert len(live_subscriptions(user)) == 1


def test_inactive_user_is_dropped():
    # mutant: drop the is_active check
    user = UserFactory()
    make_sub(user, live_session_for(user))
    user.is_active = False
    user.save()
    assert live_subscriptions(user) == []


def test_not_remembered_session_is_dropped():
    # mutant: drop the remembered_from_data check
    user = UserFactory()
    make_sub(user, live_session_for(user, remembered=False))
    assert live_subscriptions(user) == []
    assert PushSubscription.objects.count() == 0


def test_delete_spares_a_row_rekeyed_meanwhile():
    # mutant "delete by pk alone": PushSubscription.objects.filter(pk__in=...).delete()
    user = UserFactory()
    sub = make_sub(user, "deadsession00000000000000000000x")
    fresh = live_session_for(user)
    real_filter = Session.objects.filter

    def rekey_then_filter(*args, **kwargs):
        PushSubscription.objects.filter(pk=sub.pk).update(session_key=fresh)
        return real_filter(*args, **kwargs)

    with mock.patch.object(Session.objects, "filter", side_effect=rekey_then_filter):
        live_subscriptions(user)
    assert PushSubscription.objects.filter(pk=sub.pk, session_key=fresh).exists()


def test_other_users_rows_are_never_touched():
    user, other = UserFactory(), UserFactory()
    make_sub(other, "deadsession00000000000000000000y")
    live_subscriptions(user)
    assert PushSubscription.objects.filter(user=other).count() == 1
```

- [ ] **Step 3: Write the failing delivery tests**

Create `notifications/tests/test_push_delivery.py`:

```python
"""§3: deliver_notification_push decisions, payload, error handling, independence."""

import json
from unittest import mock

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import translation
from pywebpush import WebPushException

from notifications import services
from notifications.emails import email_content
from notifications.models import Notification
from notifications.models import NotificationEmailPreference
from notifications.models import NotificationPushPreference
from notifications.models import PushSubscription
from notifications.push import deliver_notification_push
from notifications.push import push_kind_enabled as real_push_kind_enabled
from notifications.tests.push_helpers import FCM
from notifications.tests.push_helpers import MOZ
from notifications.tests.push_helpers import live_session_for
from notifications.tests.push_helpers import make_sub
from notifications.tests.push_helpers import push_settings
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _graded(recipient, course=None):
    course = course or CourseFactory()
    return Notification.objects.create(
        recipient=recipient,
        kind=Notification.Kind.QUIZ_GRADED,
        target_type=Notification.TargetType.COURSE,
        target_id=course.pk,
        data={
            "course_title": course.title,
            "course_slug": course.slug,
            "unit_title": "Quiz 1",
            "node_pk": 999,
        },
    )


@pytest.fixture
def webpush():
    with mock.patch("pywebpush.webpush") as m:
        yield m


@pytest.fixture
def subscribed(settings):
    push_settings(settings)
    user = UserFactory(email="stu@example.com")
    sub = make_sub(user, live_session_for(user))
    return user, sub


def _payload(call):
    return json.loads(call.kwargs["data"])


def test_not_configured_sends_nothing(webpush):
    user = UserFactory()
    make_sub(user, live_session_for(user))
    deliver_notification_push(_graded(user))
    webpush.assert_not_called()


def test_kind_off_sends_nothing(webpush, subscribed):
    user, _ = subscribed
    NotificationPushPreference.objects.create(user=user, quiz_graded=False)
    deliver_notification_push(_graded(user))
    webpush.assert_not_called()


def test_no_subscriptions_sends_nothing(webpush, settings):
    push_settings(settings)
    deliver_notification_push(_graded(UserFactory()))
    webpush.assert_not_called()


def test_sends_with_the_documented_call_shape(webpush, subscribed, settings):
    user, sub = subscribed
    n = _graded(user)
    deliver_notification_push(n)
    call = webpush.call_args
    assert call.kwargs["subscription_info"] == {
        "endpoint": sub.endpoint,
        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
    }
    assert call.kwargs["vapid_private_key"] == settings.PUSH_VAPID_PRIVATE_KEY
    assert call.kwargs["vapid_claims"] == {"sub": "mailto:ops@example.com"}
    assert call.kwargs["ttl"] == 86400
    assert call.kwargs["timeout"] == 5
    payload = _payload(call)
    assert payload["url"] == reverse("notifications:open", args=[n.pk])
    assert payload["tag"] == f"libli-{n.pk}"
    sub.refresh_from_db()
    assert sub.last_success_at is not None


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_payload_text_is_the_email_wording_in_the_recipient_language(
    webpush, subscribed, lang
):
    user, _ = subscribed
    user.language = lang
    user.save()
    n = _graded(user)
    deliver_notification_push(n)
    with translation.override(lang):
        _s, headline, body_line = email_content(n)
    payload = _payload(webpush.call_args)
    assert (payload["title"], payload["body"]) == (headline, body_line)


def test_real_pywebpush_encrypts_and_signs_with_our_keys(settings):
    """The ONE test that runs the real library (every other test mocks webpush): our
    key format, the stored p256dh/auth and our kwargs must produce a real request.
    Only the HTTP call is patched. pywebpush 2.x posts via requests.post when no
    session is passed -- confirm in .venv/Lib/site-packages/pywebpush/__init__.py
    (WebPusher.send) and patch whatever it calls if that differs."""
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from notifications.push import _b64url

    push_settings(settings)
    receiver = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    user = UserFactory()
    sub = make_sub(user, live_session_for(user), endpoint=FCM + "real",
                   p256dh=_b64url(receiver), auth=_b64url(os.urandom(16)))
    response = mock.Mock(status_code=201, text="", headers={})
    with mock.patch("requests.post", return_value=response) as http:
        deliver_notification_push(_graded(user))
    http.assert_called_once()
    args, kwargs = http.call_args
    assert (args[0] if args else kwargs["url"]) == FCM + "real"
    headers = {k.lower(): v for k, v in kwargs["headers"].items()}
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["ttl"] == "86400"
    assert headers["authorization"].startswith("vapid t=")
    assert f"k={settings.PUSH_VAPID_PUBLIC_KEY}" in headers["authorization"]
    assert kwargs["timeout"] == 5
    sub.refresh_from_db()
    assert sub.last_success_at is not None


def test_icon_is_the_static_default_without_an_override(webpush, subscribed):
    user, _ = subscribed
    deliver_notification_push(_graded(user))
    assert _payload(webpush.call_args)["icon"].endswith("core/img/favicon/icon-192.png")


def test_icon_is_the_favicon_override_when_set(webpush, subscribed):
    user, _ = subscribed
    with mock.patch(
        "core.services.get_site_config",
        return_value={"favicon_url": "/media/branding/fav.png"},
    ):
        deliver_notification_push(_graded(user))
    assert _payload(webpush.call_args)["icon"] == "/media/branding/fav.png"


def test_push_ignores_the_email_gates(webpush, settings):
    push_settings(settings)
    user = UserFactory(email="")  # blank email still pushes
    NotificationEmailPreference.objects.create(user=user, quiz_graded=False)
    make_sub(user, live_session_for(user))
    deliver_notification_push(_graded(user))
    webpush.assert_called_once()


def test_each_call_gets_its_own_claims_dict(webpush, settings):
    # mutant: one vapid_claims dict hoisted out of the loop
    push_settings(settings)
    user = UserFactory()
    key = live_session_for(user)
    make_sub(user, key, endpoint=FCM + "a")
    make_sub(user, key, endpoint=MOZ + "b")
    deliver_notification_push(_graded(user))
    first, second = webpush.call_args_list
    assert first.kwargs["vapid_claims"] is not second.kwargs["vapid_claims"]


@pytest.mark.parametrize("status", [404, 410])
def test_gone_subscription_is_deleted(webpush, subscribed, status):
    user, sub = subscribed
    webpush.side_effect = WebPushException("gone", response=mock.Mock(status_code=status))
    deliver_notification_push(_graded(user))
    assert not PushSubscription.objects.filter(pk=sub.pk).exists()


def test_other_error_logs_and_the_next_subscription_still_goes(webpush, settings, caplog):
    push_settings(settings)
    user = UserFactory()
    key = live_session_for(user)
    first = make_sub(user, key, endpoint=FCM + "a")
    make_sub(user, key, endpoint=FCM + "b")
    webpush.side_effect = [
        WebPushException("boom", response=mock.Mock(status_code=500)),
        None,
    ]
    deliver_notification_push(_graded(user))
    assert webpush.call_count == 2
    assert PushSubscription.objects.filter(pk=first.pk).exists()
    assert "push" in caplog.text.lower()


def test_unknown_kind_is_swallowed(webpush, subscribed):
    user, _ = subscribed
    n = Notification.objects.create(
        recipient=user, kind="bogus_kind", target_type="course", target_id=1, data={}
    )
    deliver_notification_push(n)  # must not raise
    webpush.assert_not_called()


def test_muted_notify_creates_nothing(webpush, subscribed):
    user, _ = subscribed
    with services.muted():
        services.notify_enrolled(user, CourseFactory())
    assert Notification.objects.count() == 0
    webpush.assert_not_called()


# --- independence (spec §10) -------------------------------------------------------


def test_email_failure_still_pushes(webpush, subscribed, django_capture_on_commit_callbacks):
    # mutant: email's log-and-swallow removed (deliver_notification_email lets send() raise)
    user, _ = subscribed
    with mock.patch(
        "django.core.mail.EmailMultiAlternatives.send", side_effect=RuntimeError("smtp")
    ):
        with django_capture_on_commit_callbacks(execute=True):
            services.notify_enrolled(user, CourseFactory())
    webpush.assert_called_once()


def test_first_teachers_push_failure_does_not_stop_the_second_teacher(
    settings, django_capture_on_commit_callbacks
):
    # mutant: the try in deliver_notification_push narrowed so push_kind_enabled sits outside it
    push_settings(settings)
    first, second = UserFactory(email="t1@example.com"), UserFactory(email="t2@example.com")
    make_sub(first, live_session_for(first), endpoint=FCM + "t1")
    make_sub(second, live_session_for(second), endpoint=FCM + "t2")
    def boom_for_first(user, kind):
        if user.pk == first.pk:
            raise RuntimeError("pref lookup failed")
        return real_push_kind_enabled(user, kind)

    course = CourseFactory()
    with (
        mock.patch("notifications.push.push_kind_enabled", side_effect=boom_for_first),
        mock.patch("pywebpush.webpush") as webpush,
        django_capture_on_commit_callbacks(execute=True),
    ):
        services.notify_enrolled(first, course)
        services.notify_enrolled(second, course)
    assert [c.kwargs["subscription_info"]["endpoint"] for c in webpush.call_args_list] == [
        FCM + "t2"
    ]
    assert {m.to[0] for m in mail.outbox} == {"t1@example.com", "t2@example.com"}
```

Note on the second independence test: it uses two `notify_enrolled` calls (two separate on_commit pairs, same shape as `notify_needs_review`'s per-teacher fan-out) because `notify_needs_review` needs [R] questions to emit at all; the guarded property — a raising push callback for recipient 1 does not stop recipient 2's callbacks — is identical.

- [ ] **Step 4: Write the failing budget tests**

Create `notifications/tests/test_push_budget.py`:

```python
"""§3 latency bound 3: the per-request push budget."""

import logging
from unittest import mock

import pytest
from django.core.signals import request_started
from django.db import close_old_connections

from notifications.models import Notification
from notifications.push import deliver_notification_push
from notifications.push import reset_push_budget
from notifications.tests.push_helpers import FCM
from notifications.tests.push_helpers import live_session_for
from notifications.tests.push_helpers import make_sub
from notifications.tests.push_helpers import push_settings
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    c = Clock()
    with mock.patch("notifications.push.monotonic", c):
        yield c


def _n(user):
    return Notification.objects.create(
        recipient=user, kind="enrolled", target_type="course", target_id=1,
        data={"course_title": "C", "course_slug": "c"},
    )


@pytest.fixture
def three_subs(settings):
    push_settings(settings)
    user = UserFactory()
    key = live_session_for(user)
    for i in range(3):
        make_sub(user, key, endpoint=f"{FCM}{i}")
    return user


def test_pushes_after_the_deadline_are_skipped_with_one_warning(three_subs, clock, caplog):
    calls = []

    def slow(**kwargs):
        calls.append(kwargs)
        clock.now += 6  # each call "takes" 6 s; the 10 s budget allows two

    with mock.patch("pywebpush.webpush", side_effect=slow), caplog.at_level(logging.WARNING):
        deliver_notification_push(_n(three_subs))
        deliver_notification_push(_n(three_subs))
    assert len(calls) == 2
    warnings = [r for r in caplog.records if "push budget exhausted" in r.getMessage()]
    assert len(warnings) == 1


def test_request_started_resets_the_budget(three_subs, clock):
    # mutant: no request_started receiver
    with mock.patch("pywebpush.webpush") as webpush:
        deliver_notification_push(_n(three_subs))
        clock.now += 60
        # Django's test client does the same: close_old_connections (also on
        # request_started) would close the test transaction's connection.
        request_started.disconnect(close_old_connections)
        try:
            request_started.send(sender=None)
        finally:
            request_started.connect(close_old_connections)
        deliver_notification_push(_n(three_subs))
    assert webpush.call_count == 6


def test_reset_push_budget_lets_a_later_direct_call_push(three_subs, clock):
    with mock.patch("pywebpush.webpush") as webpush:
        deliver_notification_push(_n(three_subs))
        clock.now += 60
        reset_push_budget()
        deliver_notification_push(_n(three_subs))
    assert webpush.call_count == 6


def test_without_a_reset_a_stale_deadline_skips(three_subs, clock):
    # the property the autouse conftest fixture exists for
    with mock.patch("pywebpush.webpush") as webpush:
        deliver_notification_push(_n(three_subs))
        clock.now += 60
        deliver_notification_push(_n(three_subs))
    assert webpush.call_count == 3
```

- [ ] **Step 5: Run to verify failure**

Run: `uv run pytest notifications/tests/test_push_sessions.py notifications/tests/test_push_delivery.py notifications/tests/test_push_budget.py`
Expected: FAIL — `ImportError: cannot import name 'live_subscriptions'` (and `notifications:open` NoReverseMatch once imports pass; that route arrives in Task 5 — so in THIS task add the URL name now, see Step 6c).

- [ ] **Step 6a: Append delivery to `notifications/push.py`**

Add `import contextvars`, `import json` and `from time import monotonic` to the imports (a bare name, so the budget tests patch `notifications.push.monotonic` without freezing the shared `time` module for the whole process), then append:

```python
# --- per-request budget (spec §3, latency bound 3) ---------------------------------

_BUDGET = contextvars.ContextVar("libli_push_budget", default=None)


def reset_push_budget():
    _BUDGET.set(None)


def _budget_allows():
    state = _BUDGET.get()
    now = monotonic()
    if state is None:
        _BUDGET.set({"deadline": now + PUSH_BUDGET_SECONDS, "warned": False})
        return True
    if now < state["deadline"]:
        return True
    if not state["warned"]:
        logger.warning("push budget exhausted; skipping remaining pushes in this request")
        state["warned"] = True
    return False


# --- live sessions (D7, D8) ------------------------------------------------------


def _session_is_live_for(data, user):
    from django.contrib.auth import HASH_SESSION_KEY
    from django.contrib.auth import SESSION_KEY
    from django.utils.crypto import constant_time_compare

    if not user.is_active or data.get(SESSION_KEY) != str(user.pk):
        return False
    stored = data.get(HASH_SESSION_KEY) or ""
    hashes = [user.get_session_auth_hash(), *user.get_session_auth_fallback_hash()]
    if not any(constant_time_compare(stored, h) for h in hashes):
        return False
    return remembered_from_data(data)


def live_subscriptions(user):
    """The user's subscriptions whose session is live, authenticated as this user with
    a current auth hash, active and remembered. The rest are deleted -- conditionally
    on the stale key, so a row a concurrent claim re-keyed survives."""
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    from notifications.models import PushSubscription

    subs = list(PushSubscription.objects.filter(user=user))
    if not subs:
        return []
    keys = {s.session_key for s in subs}
    sessions = Session.objects.filter(session_key__in=keys, expire_date__gt=timezone.now())
    live = {s.session_key for s in sessions if _session_is_live_for(s.get_decoded(), user)}
    dead = keys - live
    if dead:
        PushSubscription.objects.filter(
            pk__in=[s.pk for s in subs if s.session_key in dead],
            session_key__in=dead,
        ).delete()
    return [s for s in subs if s.session_key in live]


# --- payload + delivery (spec §3) --------------------------------------------------


def _icon_url():
    from django.templatetags.static import static

    from core.services import get_site_config

    return get_site_config().get("favicon_url") or static("core/img/favicon/icon-192.png")


def build_payload(notification):
    from django.urls import reverse
    from django.utils import translation

    from notifications.emails import email_content

    lang = notification.recipient.language or settings.LANGUAGE_CODE
    with translation.override(lang):
        _subject, headline, body_line = email_content(notification)
    return json.dumps(
        {
            "title": headline,
            "body": body_line,
            "url": reverse("notifications:open", args=[notification.pk]),
            "tag": f"libli-{notification.pk}",
            "icon": _icon_url(),
        }
    )


def _send_one(sub, data, notification):
    from django.utils import timezone
    from pywebpush import WebPushException
    from pywebpush import webpush

    from notifications.models import PushSubscription

    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=data,
            vapid_private_key=settings.PUSH_VAPID_PRIVATE_KEY,
            # FRESH per call: webpush writes aud/exp into the dict it is given.
            vapid_claims={"sub": settings.PUSH_VAPID_SUBJECT},
            ttl=PUSH_TTL,
            timeout=PUSH_TIMEOUT,
        )
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            PushSubscription.objects.filter(pk=sub.pk).delete()
            return
        logger.warning(
            "push delivery failed (subscription %s, notification %s, status %s)",
            sub.pk, notification.pk, status,
        )
        return
    except Exception:  # noqa: BLE001 -- one device never stops the next
        logger.exception(
            "push delivery failed (subscription %s, notification %s)", sub.pk, notification.pk
        )
        return
    PushSubscription.objects.filter(pk=sub.pk).update(last_success_at=timezone.now())


def deliver_notification_push(notification):
    """Push one notification to the recipient's live devices. Runs in a post-commit
    callback; the WHOLE body is log-and-swallow (Django stops the on_commit chain at
    the first callback that raises -- see deliver_notification_email)."""
    try:
        if not push_configured():
            return
        user = notification.recipient
        if not push_kind_enabled(user, notification.kind):
            return
        subs = live_subscriptions(user)
        if not subs:
            return
        data = build_payload(notification)
        for sub in subs:
            if not _budget_allows():
                return
            _send_one(sub, data, notification)
    except Exception:  # noqa: BLE001 -- never break the request / fan-out
        logger.exception("push delivery failed (notification %s)", notification.pk)
```

- [ ] **Step 6b: Wire `notify()`**

In `notifications/services.py` replace the two lines

```python
    from notifications.emails import deliver_notification_email

    transaction.on_commit(lambda: deliver_notification_email(n))
```

with

```python
    from notifications.emails import deliver_notification_email
    from notifications.push import deliver_notification_push

    transaction.on_commit(lambda: deliver_notification_email(n))
    transaction.on_commit(lambda: deliver_notification_push(n))
```

and extend the comment above them to read "…a top-level import here would cycle at load (push.py imports emails.py function-locally for the same reason). Deferring to call time breaks the cycle."

- [ ] **Step 6c: Add the tap-target route now (its tests come in Task 5)**

The payload reverses `notifications:open`. Create `notifications/push_views.py` with only the view from Task 5 Step 3 (copy it from there now; Task 5 adds its tests) and add to `notifications/urls.py`:

```python
from notifications import push_views
...
    path("notifications/<int:pk>/open/", push_views.open_notification, name="open"),
```

- [ ] **Step 6d: Signals, app ready, conftest**

Create `notifications/signals.py`:

```python
"""Push housekeeping receivers (PWA C2 spec §3, §4). Connected by
NotificationsConfig.ready()."""

from django.contrib.auth.signals import user_logged_out
from django.core.signals import request_started
from django.dispatch import receiver

from notifications.push import reset_push_budget


@receiver(request_started)
def reset_push_budget_on_request(sender, **kwargs):
    reset_push_budget()


@receiver(user_logged_out)
def delete_push_subscription_on_logout(sender, request, user, **kwargs):
    """NOT gated on push_configured(): a row must not outlive a logout made while
    push was off. Django sends this before flushing the session."""
    if user is None or request is None or not hasattr(request, "session"):
        return
    endpoint = request.session.get("push_endpoint")
    if not endpoint:
        return
    from notifications.models import PushSubscription

    PushSubscription.objects.filter(endpoint=endpoint, user=user).delete()
```

Replace `notifications/apps.py` with:

```python
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        from notifications import signals  # noqa: F401  (registers push receivers)
```

In the root `conftest.py`, after `_reset_active_language`:

```python
@pytest.fixture(autouse=True)
def _reset_push_budget():
    """The per-request push budget (notifications.push) is a ContextVar reset by
    request_started. Direct notify()/deliver calls in tests never fire that signal,
    so a deadline left by one test would skip pushes in a later one on the same
    worker. Reset it before every test."""
    from notifications.push import reset_push_budget

    reset_push_budget()
    yield
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest notifications/tests/test_push_sessions.py notifications/tests/test_push_delivery.py notifications/tests/test_push_budget.py notifications/tests/test_push_models.py notifications/tests/test_push_config.py`
Expected: PASS. Then the existing suite for the touched module: `uv run pytest notifications/tests/` — PASS (email tests unaffected).

- [ ] **Step 8: Falsify (each RED, then revert by hand)**

1. `live_subscriptions`: drop `expire_date__gt=...` → `test_expired_session_row_still_present_is_dropped` FAILS.
2. drop `data.get(SESSION_KEY) != str(user.pk)` → `test_session_of_another_user_is_dropped` FAILS.
3. replace the hash check with `pass` → `test_password_changed_elsewhere_is_dropped` FAILS.
4. drop `not user.is_active` → `test_inactive_user_is_dropped` FAILS.
5. replace `return remembered_from_data(data)` with `return True` → `test_not_remembered_session_is_dropped` FAILS.
6. delete without `session_key__in=dead` → `test_delete_spares_a_row_rekeyed_meanwhile` FAILS.
7. hoist `claims = {"sub": ...}` above the loop in `deliver_notification_push` and pass it into `_send_one` → `test_each_call_gets_its_own_claims_dict` FAILS.
8. move `if not push_kind_enabled(...)` above the `try:` → `test_first_teachers_push_failure_does_not_stop_the_second_teacher` FAILS.
9. comment out the `@receiver(request_started)` decorator → `test_request_started_resets_the_budget` FAILS.
10. make `live_subscriptions` `return subs` right after loading them (no filtering) → `test_missing_session_is_dropped_and_deleted` FAILS.
11. in `_send_one`, pass `vapid_private_key=decode_b64url(settings.PUSH_VAPID_PRIVATE_KEY).hex()` → `test_real_pywebpush_encrypts_and_signs_with_our_keys` FAILS (no POST; the error is swallowed and logged). If the real-library test cannot pass on a CORRECT build, the key format in `generate_vapid_pair` is wrong for this pywebpush version — fix the format (e.g. PEM via `py_vapid`), never the test.

Mutant 4 (`is_active`) must go RED on its own: `live_session_for` persists the password first, so `user.save()` in that test changes only `is_active`. If it stays green, the hash is still dropping the row — fix the helper, not the test.

- [ ] **Step 9: Commit**

```bash
git add notifications/push.py notifications/services.py notifications/signals.py notifications/apps.py notifications/push_views.py notifications/urls.py conftest.py notifications/tests/push_helpers.py notifications/tests/test_push_sessions.py notifications/tests/test_push_delivery.py notifications/tests/test_push_budget.py
git commit -m "feat(push): deliver notifications to live remembered sessions"
```

---

### Task 4: Subscribe / unsubscribe / claim endpoints and the logout receiver

**Files:**
- Modify: `notifications/push_views.py` (add three views)
- Modify: `notifications/urls.py`
- Test: `notifications/tests/test_push_endpoints.py`, `notifications/tests/test_push_logout.py`

**Interfaces:**
- Consumes: `clean_subscription`, `push_configured`, `remembered_from_data`, `MAX_SUBSCRIPTIONS_PER_USER`, `MAX_ENDPOINT_LENGTH`, `PushSubscription`; `notifications/signals.py` logout receiver (Task 3).
- Produces: URL names `notifications:push_subscribe`, `notifications:push_unsubscribe`, `notifications:push_claim` at `notifications/push/subscribe/`, `/unsubscribe/`, `/claim/`. Responses: subscribe/unsubscribe `{"ok": true}`; claim `{"mine": bool}`; errors per Global Constraints.

- [ ] **Step 1: Write the failing endpoint tests**

Create `notifications/tests/test_push_endpoints.py`:

```python
"""§4: the three JSON endpoints."""

import base64
import json
from datetime import timedelta
from unittest import mock

import pytest
from django.db import IntegrityError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from notifications.models import PushSubscription
from notifications.tests.push_helpers import FCM
from notifications.tests.push_helpers import logged_in_user
from notifications.tests.push_helpers import make_sub
from notifications.tests.push_helpers import push_settings
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

P256DH = base64.urlsafe_b64encode(b"\x04" + b"\x01" * 64).decode().rstrip("=")
AUTH = base64.urlsafe_b64encode(b"\x02" * 16).decode().rstrip("=")


def body(endpoint=FCM + "dev1"):
    return {"endpoint": endpoint, "keys": {"p256dh": P256DH, "auth": AUTH}}


def post(client, name, payload):
    return client.post(
        reverse(f"notifications:{name}"),
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.fixture
def on(settings):
    push_settings(settings)


@pytest.fixture
def user_client(client):
    user = logged_in_user(client)  # force_login sets no _session_expiry: remembered
    return user, client


def forget_me(client):
    session = client.session
    session.set_expiry(0)
    session.save()


# --- gates and order --------------------------------------------------------------


@pytest.mark.parametrize("name", ["push_subscribe", "push_unsubscribe", "push_claim"])
def test_404_when_not_configured_even_for_anonymous(client, name):
    assert post(client, name, body()).status_code == 404


@pytest.mark.parametrize("name", ["push_subscribe", "push_unsubscribe", "push_claim"])
def test_anonymous_gets_403_json_not_a_redirect(client, on, name):
    r = post(client, name, body())
    assert r.status_code == 403
    assert r.json() == {"ok": False}


def test_csrf_is_required(on):
    strict = Client(enforce_csrf_checks=True)
    logged_in_user(strict)
    assert post(strict, "push_subscribe", body()).status_code == 403
    assert PushSubscription.objects.count() == 0


def test_get_is_refused(user_client, on):
    _, client = user_client
    assert client.get(reverse("notifications:push_subscribe")).status_code == 405


def test_not_remembered_subscribe_is_403_even_with_a_bad_body(user_client, on):
    # mutant: remembered check moved after body validation
    _, client = user_client
    forget_me(client)
    assert post(client, "push_subscribe", {"nope": 1}).status_code == 403
    assert post(client, "push_subscribe", body()).status_code == 403
    assert PushSubscription.objects.count() == 0


def test_bad_json_is_400(user_client, on):
    _, client = user_client
    r = client.post(
        reverse("notifications:push_subscribe"), data="{not json", content_type="application/json"
    )
    assert r.status_code == 400


def test_wrong_types_are_400(user_client, on):
    _, client = user_client
    for payload in ({"endpoint": 5, "keys": {}}, {"endpoint": FCM + "x", "keys": "k"}, [1]):
        assert post(client, "push_subscribe", payload).status_code == 400


def test_disallowed_host_is_400(user_client, on):
    _, client = user_client
    assert post(client, "push_subscribe", body("https://evil.example/x")).status_code == 400


# --- subscribe --------------------------------------------------------------------


def test_subscribe_creates_a_keyed_row_and_remembers_the_endpoint(user_client, on):
    user, client = user_client
    r = post(client, "push_subscribe", body())
    assert r.status_code == 200 and r.json() == {"ok": True}
    row = PushSubscription.objects.get()
    assert row.user == user
    assert row.session_key == client.session.session_key
    assert client.session["push_endpoint"] == FCM + "dev1"


def test_subscribe_moves_an_endpoint_from_another_user(user_client, on):
    user, client = user_client
    make_sub(UserFactory(), "x" * 32, endpoint=FCM + "dev1")
    post(client, "push_subscribe", body())
    assert PushSubscription.objects.get().user == user


def test_sixth_subscribe_evicts_only_this_users_oldest(user_client, on):
    user, client = user_client
    other = UserFactory()
    other_row = make_sub(other, "o" * 32, endpoint=FCM + "other",
                         subscribed_at=timezone.now() - timedelta(days=30))
    base = timezone.now() - timedelta(days=10)
    rows = [make_sub(user, "k" * 32, endpoint=f"{FCM}old{i}",
                     subscribed_at=base + timedelta(days=i)) for i in range(5)]
    post(client, "push_subscribe", body(FCM + "new"))
    remaining = set(PushSubscription.objects.filter(user=user).values_list("endpoint", flat=True))
    assert rows[0].endpoint not in remaining
    assert len(remaining) == 5 and FCM + "new" in remaining
    assert PushSubscription.objects.filter(pk=other_row.pk).exists()


def test_resubscribing_an_old_endpoint_keeps_it(user_client, on):
    # mutant: not excluding the current endpoint from the cap
    user, client = user_client
    long_ago = timezone.now() - timedelta(days=100)
    old = make_sub(user, "k" * 32, endpoint=FCM + "dev1", subscribed_at=long_ago)
    PushSubscription.objects.filter(pk=old.pk).update(created_at=long_ago)
    for i in range(5):
        make_sub(user, "k" * 32, endpoint=f"{FCM}new{i}")
    post(client, "push_subscribe", body(FCM + "dev1"))
    assert PushSubscription.objects.filter(endpoint=FCM + "dev1").exists()
    assert PushSubscription.objects.filter(user=user).count() == 5


def test_cap_evicts_by_subscribed_at_not_created_at(user_client, on):
    # mutant: cap ordered by created_at. A was CREATED first but RE-SUBSCRIBED last;
    # B is the oldest by subscribed_at. Only B may go.
    user, client = user_client
    now = timezone.now()
    a = make_sub(user, "k" * 32, endpoint=FCM + "A", subscribed_at=now - timedelta(hours=1))
    PushSubscription.objects.filter(pk=a.pk).update(created_at=now - timedelta(days=99))
    make_sub(user, "k" * 32, endpoint=FCM + "B", subscribed_at=now - timedelta(days=50))
    for i in range(3):
        make_sub(user, "k" * 32, endpoint=f"{FCM}mid{i}",
                 subscribed_at=now - timedelta(days=10 - i))
    post(client, "push_subscribe", body(FCM + "sixth"))
    left = set(PushSubscription.objects.filter(user=user).values_list("endpoint", flat=True))
    assert FCM + "A" in left and FCM + "B" not in left and len(left) == 5


def test_concurrent_insert_integrity_error_retries_as_update(user_client, on):
    user, client = user_client
    make_sub(UserFactory(), "x" * 32, endpoint=FCM + "dev1")
    with mock.patch(
        "notifications.models.PushSubscription.objects.update_or_create",
        side_effect=IntegrityError("dup"),
    ):
        r = post(client, "push_subscribe", body())
    assert r.status_code == 200
    assert PushSubscription.objects.get(endpoint=FCM + "dev1").user == user


# --- unsubscribe ------------------------------------------------------------------


def test_unsubscribe_deletes_own_row_and_clears_the_entry(user_client, on):
    _, client = user_client
    post(client, "push_subscribe", body())
    r = post(client, "push_unsubscribe", {"endpoint": FCM + "dev1"})
    assert r.json() == {"ok": True}
    assert PushSubscription.objects.count() == 0
    assert "push_endpoint" not in client.session


def test_unsubscribe_of_another_users_endpoint_deletes_nothing(user_client, on):
    _, client = user_client
    make_sub(UserFactory(), "x" * 32, endpoint=FCM + "theirs")
    r = post(client, "push_unsubscribe", {"endpoint": FCM + "theirs"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert PushSubscription.objects.count() == 1


# --- claim ------------------------------------------------------------------------


def test_claim_own_row_rekeys_and_sets_the_entry(user_client, on):
    user, client = user_client
    row = make_sub(user, "stale" * 8, endpoint=FCM + "dev1")
    r = post(client, "push_claim", {"endpoint": FCM + "dev1"})
    assert r.json() == {"mine": True}
    row.refresh_from_db()
    assert row.session_key == client.session.session_key
    assert client.session["push_endpoint"] == FCM + "dev1"


def test_claim_other_users_row_deletes_it(user_client, on):
    _, client = user_client
    make_sub(UserFactory(), "x" * 32, endpoint=FCM + "dev1")
    assert post(client, "push_claim", {"endpoint": FCM + "dev1"}).json() == {"mine": False}
    assert PushSubscription.objects.count() == 0


def test_claim_with_no_row_creates_nothing(user_client, on):
    _, client = user_client
    assert post(client, "push_claim", {"endpoint": FCM + "dev1"}).json() == {"mine": False}
    assert PushSubscription.objects.count() == 0


def test_claim_in_a_not_remembered_session_deletes_own_row(user_client, on):
    user, client = user_client
    make_sub(user, "x" * 32, endpoint=FCM + "dev1")
    forget_me(client)
    assert post(client, "push_claim", {"endpoint": FCM + "dev1"}).json() == {"mine": False}
    assert PushSubscription.objects.count() == 0


def test_claim_after_rotation_rekeys_and_delivers_again(user_client, on):
    from notifications.models import Notification
    from notifications.push import deliver_notification_push

    user, client = user_client
    post(client, "push_subscribe", body())
    session = client.session
    session.cycle_key()  # as login / password change do; the row's key goes stale
    session.save()
    client.cookies["sessionid"] = session.session_key
    assert post(client, "push_claim", {"endpoint": FCM + "dev1"}).json() == {"mine": True}
    assert PushSubscription.objects.get().session_key == client.session.session_key
    n = Notification.objects.create(recipient=user, kind="enrolled", target_type="course",
                                    target_id=1, data={"course_title": "C", "course_slug": "c"})
    with mock.patch("pywebpush.webpush") as webpush:
        deliver_notification_push(n)
    webpush.assert_called_once()


def test_claim_with_a_non_string_endpoint_is_400(user_client, on):
    _, client = user_client
    assert post(client, "push_claim", {"endpoint": 7}).status_code == 400
```

- [ ] **Step 2: Write the failing logout tests**

Create `notifications/tests/test_push_logout.py`:

```python
"""§4 Logout: driven through the real account_logout view (a receiver that is never
connected fails these)."""

import json

import pytest
from django.urls import reverse

from notifications.models import PushSubscription
from notifications.tests.push_helpers import FCM
from notifications.tests.push_helpers import logged_in_user
from notifications.tests.push_helpers import make_sub
from notifications.tests.push_helpers import push_settings
from notifications.tests.test_push_endpoints import body
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _subscribe(client):
    client.post(
        reverse("notifications:push_subscribe"),
        data=json.dumps(body()),
        content_type="application/json",
    )


def test_logout_deletes_the_sessions_row_only(client, settings):
    push_settings(settings)
    user = logged_in_user(client)
    _subscribe(client)
    other_device = make_sub(user, "y" * 32, endpoint=FCM + "phone")
    client.post(reverse("account_logout"))
    assert list(PushSubscription.objects.all()) == [other_device]


def test_logout_without_an_entry_is_a_noop(client, settings):
    push_settings(settings)
    user = logged_in_user(client)
    row = make_sub(user, "y" * 32)
    client.post(reverse("account_logout"))
    assert PushSubscription.objects.filter(pk=row.pk).exists()


def test_logout_deletes_even_when_push_is_off_now(client, settings):
    push_settings(settings)
    logged_in_user(client)
    _subscribe(client)
    settings.PUSH_VAPID_PUBLIC_KEY = ""  # keys blanked after subscribing
    client.post(reverse("account_logout"))
    assert PushSubscription.objects.count() == 0


def test_subscription_from_an_earlier_session_is_deleted_after_a_claim(client, settings):
    push_settings(settings)
    user = logged_in_user(client)  # a new session that has never seen the endpoint
    make_sub(user, "earlier" * 5, endpoint=FCM + "dev1")
    client.post(
        reverse("notifications:push_claim"),
        data=json.dumps({"endpoint": FCM + "dev1"}),
        content_type="application/json",
    )
    client.post(reverse("account_logout"))
    assert PushSubscription.objects.count() == 0


def test_logout_via_confirmation_page_still_deletes(client, settings):
    push_settings(settings)
    logged_in_user(client)
    _subscribe(client)
    assert client.get(reverse("account_logout")).status_code == 200  # the confirm page
    client.post(reverse("account_logout"))
    assert PushSubscription.objects.count() == 0


def test_receiver_ignores_a_none_user_and_a_missing_request():
    # Through the signal, not a direct import, so this test cannot connect the
    # receivers for later tests and mask the "ready() import removed" mutant. NOTE:
    # every send also reaches core/signals.py:clear_theme_cookie_on_logout, which sets
    # an attribute on any non-None request -- so pass a real request object (a bare
    # object() would raise there), one with NO .session to exercise our guard.
    from django.contrib.auth.signals import user_logged_out
    from django.test import RequestFactory

    user_logged_out.send(sender=None, request=None, user=UserFactory())
    user_logged_out.send(sender=None, request=RequestFactory().get("/"), user=UserFactory())
    user_logged_out.send(sender=None, request=RequestFactory().get("/"), user=None)
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest notifications/tests/test_push_endpoints.py notifications/tests/test_push_logout.py`
Expected: FAIL — `NoReverseMatch: 'push_subscribe' is not a valid view function or pattern name`.

- [ ] **Step 4: Implement the views**

Add to `notifications/push_views.py` (keep `open_notification` from Task 3; MERGE the imports below into the file's top import block — ruff E402 forbids imports after a def — and keep one import per line, isort order):

```python
import json

from django.db import IntegrityError
from django.db import transaction
from django.http import Http404
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from notifications.models import PushSubscription
from notifications.push import MAX_ENDPOINT_LENGTH
from notifications.push import MAX_SUBSCRIPTIONS_PER_USER
from notifications.push import clean_subscription
from notifications.push import push_configured
from notifications.push import remembered_from_data

FORBIDDEN = {"ok": False}


def _gate(request, *, subscribe=False):
    """Spec §4 order (after CSRF): 404 → anonymous 403 → (subscribe) non-remembered 403."""
    if not push_configured():
        raise Http404
    if not request.user.is_authenticated:
        return JsonResponse(FORBIDDEN, status=403)
    if subscribe and not remembered_from_data(request.session):
        return JsonResponse(FORBIDDEN, status=403)
    return None


def _json(request):
    try:
        return json.loads(request.body or b"null")
    except (ValueError, UnicodeDecodeError):
        return None


def _endpoint_only(body):
    endpoint = body.get("endpoint") if isinstance(body, dict) else None
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > MAX_ENDPOINT_LENGTH:
        return None
    return endpoint


def _session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


@require_POST
def push_subscribe(request):
    refused = _gate(request, subscribe=True)
    if refused:
        return refused
    cleaned = clean_subscription(_json(request))
    if cleaned is None:
        return JsonResponse(FORBIDDEN, status=400)
    endpoint, p256dh, auth = cleaned
    values = {
        "user": request.user,
        "p256dh": p256dh,
        "auth": auth,
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
        "subscribed_at": timezone.now(),
        "session_key": _session_key(request),
    }
    try:
        with transaction.atomic():
            PushSubscription.objects.update_or_create(endpoint=endpoint, defaults=values)
    except IntegrityError:  # a concurrent insert of the same endpoint won the race
        PushSubscription.objects.filter(endpoint=endpoint).update(**values)
    keep = list(
        PushSubscription.objects.filter(user=request.user)
        .exclude(endpoint=endpoint)
        .order_by("-subscribed_at", "-pk")
        .values_list("pk", flat=True)[: MAX_SUBSCRIPTIONS_PER_USER - 1]
    )
    PushSubscription.objects.filter(user=request.user).exclude(endpoint=endpoint).exclude(
        pk__in=keep
    ).delete()
    request.session["push_endpoint"] = endpoint
    return JsonResponse({"ok": True})


@require_POST
def push_unsubscribe(request):
    refused = _gate(request)
    if refused:
        return refused
    endpoint = _endpoint_only(_json(request))
    if endpoint is None:
        return JsonResponse(FORBIDDEN, status=400)
    PushSubscription.objects.filter(endpoint=endpoint, user=request.user).delete()
    if request.session.get("push_endpoint") == endpoint:
        del request.session["push_endpoint"]
    return JsonResponse({"ok": True})


@require_POST
def push_claim(request):
    refused = _gate(request)
    if refused:
        return refused
    endpoint = _endpoint_only(_json(request))
    if endpoint is None:
        return JsonResponse(FORBIDDEN, status=400)
    row = PushSubscription.objects.filter(endpoint=endpoint).first()
    if row and row.user_id == request.user.pk and remembered_from_data(request.session):
        row.session_key = _session_key(request)
        row.save(update_fields=["session_key"])
        request.session["push_endpoint"] = endpoint
        return JsonResponse({"mine": True})
    # Not this user's, or a not-remembered login (D8): the browser is about to
    # unsubscribe it, so the row can never deliver again -- for anyone.
    PushSubscription.objects.filter(endpoint=endpoint).delete()
    if request.session.get("push_endpoint") == endpoint:
        del request.session["push_endpoint"]
    return JsonResponse({"mine": False})
```

Add to `notifications/urls.py` `urlpatterns`:

```python
    path("notifications/push/subscribe/", push_views.push_subscribe, name="push_subscribe"),
    path("notifications/push/unsubscribe/", push_views.push_unsubscribe, name="push_unsubscribe"),
    path("notifications/push/claim/", push_views.push_claim, name="push_claim"),
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest notifications/tests/test_push_endpoints.py notifications/tests/test_push_logout.py`
Expected: PASS.

- [ ] **Step 6: Falsify**

1. Move the remembered check in `_gate` after body parsing (check `cleaned` first in `push_subscribe`) → `test_not_remembered_subscribe_is_403_even_with_a_bad_body` FAILS.
2. In the cap, `order_by("-created_at", "-pk")` → `test_cap_evicts_by_subscribed_at_not_created_at` FAILS. Separately, drop `.exclude(endpoint=endpoint)` from both cap queries → `test_resubscribing_an_old_endpoint_keeps_it` FAILS.
3. Remove `from notifications import signals` from `NotificationsConfig.ready` → `test_logout_deletes_the_sessions_row_only` FAILS. Run this mutant with `uv run pytest notifications/tests/test_push_logout.py::test_logout_deletes_the_sessions_row_only -p no:xdist` ALONE: any earlier test in the same process that imports `notifications.signals` directly would connect the receivers and hide the mutant (no test does — the receiver test goes through `user_logged_out.send` — and `push.py` does not import it).
4. In `push_claim`, drop `and remembered_from_data(...)` → `test_claim_in_a_not_remembered_session_deletes_own_row` FAILS.
Revert each by hand.

- [ ] **Step 7: Commit**

```bash
git add notifications/push_views.py notifications/urls.py notifications/tests/test_push_endpoints.py notifications/tests/test_push_logout.py
git commit -m "feat(push): subscribe, unsubscribe and claim endpoints; logout cleanup"
```

---

### Task 5: The tap target `notifications/<pk>/open/`

**Files:**
- Modify: `notifications/push_views.py` (the view was created in Task 3 Step 6c — this task adds its tests and finalises it)
- Test: `notifications/tests/test_push_open.py`

**Interfaces:**
- Produces: `notifications:open` (GET, login required) → 302.

- [ ] **Step 1: Write the failing tests**

Create `notifications/tests/test_push_open.py`:

```python
"""§3 the tap target: marks the viewer's own notification read, never an oracle."""

import pytest
from django.urls import reverse

from notifications.models import Notification
from notifications.services import notification_url
from notifications.tests.push_helpers import logged_in_user
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _enrolled(user, course=None, **data):
    course = course or CourseFactory()
    base = {"course_title": course.title, "course_slug": course.slug}
    base.update(data)
    return Notification.objects.create(
        recipient=user, kind="enrolled", target_type="course", target_id=course.pk, data=base
    )


def _open(client, pk):
    return client.get(reverse("notifications:open", args=[pk]))


def test_marks_read_and_redirects_to_the_target(client):
    user = logged_in_user(client)
    n = _enrolled(user)
    r = _open(client, n.pk)
    assert r.status_code == 302 and r["Location"] == notification_url(n)
    n.refresh_from_db()
    assert n.read_at is not None


def test_idempotent_on_a_read_notification(client):
    user = logged_in_user(client)
    n = _enrolled(user)
    _open(client, n.pk)
    n.refresh_from_db()
    first = n.read_at
    _open(client, n.pk)
    n.refresh_from_db()
    assert n.read_at == first


def test_unreversible_target_falls_back_to_list(client):
    user = logged_in_user(client)
    n = _enrolled(user, course_slug="")
    assert _open(client, n.pk)["Location"] == reverse("notifications:list")


def test_foreign_and_missing_pk_look_identical_and_mark_nothing(client):
    user, other = logged_in_user(client), UserFactory()
    theirs = _enrolled(other)
    a, b = _open(client, theirs.pk), _open(client, 999999)
    assert (a.status_code, a["Location"]) == (b.status_code, b["Location"])
    assert a["Location"] == reverse("notifications:list")
    theirs.refresh_from_db()
    assert theirs.read_at is None


def test_anonymous_goes_to_login_with_next_and_marks_nothing(client):
    # mutant: login_required dropped
    n = _enrolled(UserFactory())
    r = _open(client, n.pk)
    assert r.status_code == 302
    assert reverse("account_login") in r["Location"]
    assert "next=" in r["Location"]
    n.refresh_from_db()
    assert n.read_at is None


def test_works_with_push_not_configured(client):
    user = logged_in_user(client)
    n = _enrolled(user)
    assert _open(client, n.pk).status_code == 302  # suite default: push not configured
    n.refresh_from_db()
    assert n.read_at is not None
```

- [ ] **Step 2: Run** — `uv run pytest notifications/tests/test_push_open.py`. If Task 3's view already matches Step 3 below, these PASS; run the mutant in Step 4 to prove they bite.

- [ ] **Step 3: The view (must be exactly this; it lives at the top of `notifications/push_views.py`)**

```python
"""PWA C2 push endpoints and the push tap target (spec §3, §4)."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.services import notification_url


@login_required
def open_notification(request, pk):
    """GET with a side effect, deliberately: the worker cannot send a CSRF token, and
    the only effect is marking the viewer's OWN notification read. Not gated on
    push_configured(): a notification outlives blanked keys in the tray. A missing
    and a foreign pk get the same redirect, so there is no oracle."""
    n = Notification.objects.filter(pk=pk, recipient=request.user).first()
    if n is None:
        return redirect("notifications:list")
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return redirect(notification_url(n) or reverse("notifications:list"))
```

- [ ] **Step 4: Falsify** — remove `@login_required` → `test_anonymous_goes_to_login_with_next_and_marks_nothing` FAILS (AttributeError/`TypeError` on anonymous filter or a 302 to the list). Revert.

- [ ] **Step 5: Commit**

```bash
git add notifications/push_views.py notifications/tests/test_push_open.py
git commit -m "feat(push): tap-through view marks the notification read"
```

---

### Task 6: Settings page — push preferences, device switch markup, page context

**Files:**
- Modify: `notifications/forms.py`
- Create: `notifications/context_processors.py`
- Modify: `config/settings/base.py` (`TEMPLATES[0]["OPTIONS"]["context_processors"]`, append `"notifications.context_processors.push_client"`)
- Modify: `core/views.py` (`user_settings`, the block at ~lines 129-166)
- Modify: `templates/core/user_settings.html` (the "Email notifications" section, ~lines 113-160)
- Modify: `templates/base.html` (head meta, script include, logout form)
- Modify: `core/static/core/css/settings.css` (append)
- Test: `notifications/tests/test_push_settings.py`

**Interfaces:**
- Consumes: `push_configured`, `remembered_from_data`, `PushSubscription`, `NotificationPushPreference`.
- Produces: context keys `push_available` (bool), `push_vapid_key`, `push_session_endpoint`, `push_remembered` (bool) — present only for authenticated users when configured; DOM hooks used by push.js (Task 8): `meta[name=libli-push]` with `data-vapid-key`, `data-session-endpoint`, `data-remembered`, `data-msg-error`, `data-subscribe-url`, `data-unsubscribe-url`, `data-claim-url`; `[data-push-device]` containing `[data-push-switch-wrap]`, `input[data-push-switch]`, `[data-push-state="unsupported|not-remembered|ios-not-installed|blocked"]`, `[data-push-help]`, `[data-push-error]`; `form[data-logout-form]`.

- [ ] **Step 1: Write the failing tests**

Create `notifications/tests/test_push_settings.py`:

```python
"""§6/§7: page context, settings form independence, dark-box behaviour."""

import pytest
from django.urls import reverse

from notifications.models import NotificationEmailPreference
from notifications.models import NotificationPushPreference
from notifications.tests.push_helpers import logged_in_user
from notifications.tests.push_helpers import make_sub
from notifications.tests.push_helpers import push_settings

pytestmark = pytest.mark.django_db

KINDS = ("quiz_needs_review", "quiz_graded", "enrolled")


def _settings_post(client, user, *, email=(), push=()):
    data = {"display_name": "X", "email": user.email, "language": "en", "theme": "auto"}
    for k in email:
        data[k] = "on"
    for k in push:
        data[f"push-{k}"] = "on"
    r = client.post(reverse("core:user_settings"), data)
    assert r.status_code == 302, "settings POST was invalid -- the test would prove nothing"
    return r


@pytest.fixture
def logged_in(client):
    return logged_in_user(client), client


def test_dark_box_page_has_no_push_markup(logged_in):
    _, client = logged_in
    html = client.get(reverse("core:user_settings")).content.decode()
    for hook in ("libli-push", "data-push-device", "push.js", "push-quiz_graded"):
        assert hook not in html
    assert "Email notifications" in html


def test_configured_page_carries_meta_switch_and_columns(logged_in, settings):
    push_settings(settings)
    _, client = logged_in
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'name="libli-push"' in html
    assert f'data-vapid-key="{settings.PUSH_VAPID_PUBLIC_KEY}"' in html
    assert 'data-remembered="1"' in html
    assert "data-push-device" in html
    assert 'name="push-quiz_graded"' in html and 'name="quiz_graded"' in html
    assert "core/js/push.js" in html
    assert "data-logout-form" in html


def test_not_remembered_session_renders_remembered_0(logged_in, settings):
    push_settings(settings)
    _, client = logged_in
    session = client.session
    session.set_expiry(0)
    session.save()
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'data-remembered="0"' in html


def test_session_endpoint_rendered_only_for_this_sessions_row(logged_in, settings):
    push_settings(settings)
    user, client = logged_in
    session = client.session
    session["push_endpoint"] = "https://fcm.googleapis.com/fcm/send/me"
    session.save()
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'data-session-endpoint=""' in html  # no row yet
    make_sub(user, client.session.session_key, endpoint="https://fcm.googleapis.com/fcm/send/me")
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'data-session-endpoint="https://fcm.googleapis.com/fcm/send/me"' in html


def test_session_endpoint_empty_after_a_key_rotation(logged_in, settings):
    push_settings(settings)
    user, client = logged_in
    old_key = client.session.session_key
    make_sub(user, old_key, endpoint="https://fcm.googleapis.com/fcm/send/me")
    session = client.session
    session["push_endpoint"] = "https://fcm.googleapis.com/fcm/send/me"
    session.cycle_key()
    session.save()
    client.cookies["sessionid"] = session.session_key
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'data-session-endpoint=""' in html


def test_columns_save_independently(logged_in, settings):
    # mutant: prefix="push" removed from NotificationPushForm
    push_settings(settings)
    user, client = logged_in
    _settings_post(client, user, email=("quiz_graded",), push=("enrolled",))
    e = NotificationEmailPreference.objects.get(user=user)
    p = NotificationPushPreference.objects.get(user=user)
    assert (e.quiz_graded, e.enrolled) == (True, False)
    assert (p.quiz_graded, p.enrolled) == (False, True)


def test_get_does_not_create_a_push_row(logged_in, settings):
    push_settings(settings)
    user, client = logged_in
    client.get(reverse("core:user_settings"))
    assert not NotificationPushPreference.objects.filter(user=user).exists()


def test_dark_box_post_leaves_the_push_row_alone(logged_in):
    user, client = logged_in
    NotificationPushPreference.objects.create(user=user, quiz_graded=False, enrolled=False)
    _settings_post(client, user, email=KINDS)
    p = NotificationPushPreference.objects.get(user=user)
    assert (p.quiz_graded, p.enrolled, p.quiz_needs_review) == (False, False, True)


def test_dark_box_post_creates_no_push_row(logged_in):
    user, client = logged_in
    _settings_post(client, user, email=KINDS)
    assert not NotificationPushPreference.objects.filter(user=user).exists()


def test_post_without_push_fields_turns_push_off_but_leaves_email(logged_in, settings):
    push_settings(settings)
    user, client = logged_in
    _settings_post(client, user, email=KINDS)  # a page rendered before push existed
    p = NotificationPushPreference.objects.get(user=user)
    e = NotificationEmailPreference.objects.get(user=user)
    assert not any(getattr(p, k) for k in KINDS)
    assert all(getattr(e, k) for k in KINDS)


def test_real_unticked_login_is_not_remembered_and_cannot_subscribe(client, settings):
    """D8 through allauth's REAL login form: an unticked 'Remember me' must yield
    data-remembered="0" and a 403 from subscribe."""
    import json

    from notifications.tests.test_push_endpoints import body
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_verified_user

    push_settings(settings)
    make_verified_user(username="unticked", email="unticked@example.com")
    r = client.post(reverse("account_login"), {"login": "unticked", "password": TEST_PASSWORD})
    assert r.status_code == 302
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'data-remembered="0"' in html
    r = client.post(reverse("notifications:push_subscribe"), data=json.dumps(body()),
                    content_type="application/json")
    assert r.status_code == 403


def test_anonymous_pages_carry_no_push_meta(client, settings):
    push_settings(settings)
    html = client.get(reverse("account_login")).content.decode()
    assert "libli-push" not in html
```

`UserSettingsForm.Meta.fields` is `["theme", "language", "display_name", "email"]` (`core/forms.py`); `_settings_post` supplies all four with valid values and asserts the 302, so an invalid POST can never pass silently.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest notifications/tests/test_push_settings.py`
Expected: FAIL — e.g. `assert 'name="libli-push"' in html`.

- [ ] **Step 3: The form**

Add `from notifications.models import NotificationPushPreference` to the TOP import block of `notifications/forms.py` (after the `NotificationEmailPreference` import, one name per line — ruff E402/isort), then append the class:

```python
class NotificationPushForm(forms.ModelForm):
    """Per-kind PUSH opt-outs. ALWAYS built with prefix="push": the booleans share
    their names with NotificationEmailForm's (which has no prefix), so without it
    both rows would post name="quiz_graded" and ticking either box would set both."""

    class Meta:
        model = NotificationPushPreference
        fields = ["quiz_needs_review", "quiz_graded", "enrolled"]
```

- [ ] **Step 4: The context processor**

Create `notifications/context_processors.py`:

```python
"""Push client context (PWA C2 spec §6): push_available plus the meta values."""


def push_client(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from django.conf import settings

    from notifications.models import PushSubscription
    from notifications.push import push_configured
    from notifications.push import remembered_from_data

    if not push_configured():
        return {}
    session = request.session
    endpoint = session.get("push_endpoint", "")
    # Rendered only when THIS session's current key owns the row: after a key
    # rotation (login, password change) it is empty, so push.js claims and re-keys.
    if endpoint and not PushSubscription.objects.filter(
        endpoint=endpoint, user=user, session_key=session.session_key
    ).exists():
        endpoint = ""
    return {
        "push_available": True,
        "push_vapid_key": settings.PUSH_VAPID_PUBLIC_KEY,
        "push_session_endpoint": endpoint,
        "push_remembered": remembered_from_data(session),
    }
```

Register it in `config/settings/base.py` after `"core.context_processors.notifications_badge",`:

```python
                "notifications.context_processors.push_client",
```

- [ ] **Step 5: The view**

In `core/views.py:user_settings`, replace the block from `from notifications.forms import NotificationEmailForm` through the `else:` branch's `notif_form = NotificationEmailForm(instance=pref)` with:

```python
    from notifications.forms import NotificationEmailForm
    from notifications.forms import NotificationPushForm
    from notifications.models import NotificationEmailPreference
    from notifications.models import NotificationPushPreference
    from notifications.push import push_configured

    pref = (
        NotificationEmailPreference.objects.filter(user=request.user).first()
        or NotificationEmailPreference(
            user=request.user
        )  # unsaved → GET stays read-only
    )
    # Push prefs only when push can work: on a dark box the form is never bound, so
    # absent checkboxes can never switch every push kind off (spec §7).
    with_push = push_configured()
    push_pref = (
        NotificationPushPreference.objects.filter(user=request.user).first()
        or NotificationPushPreference(user=request.user)
    ) if with_push else None

    if request.method == "POST":
        form = UserSettingsForm(request.POST, instance=request.user)
        notif_form = NotificationEmailForm(request.POST, instance=pref)
        push_form = (
            NotificationPushForm(request.POST, instance=push_pref, prefix="push")
            if with_push
            else None
        )
        forms_valid = form.is_valid() and notif_form.is_valid()
        if push_form is not None:
            forms_valid = push_form.is_valid() and forms_valid
        if forms_valid:
            from django.db import transaction

            from accounts.emails import reconcile_primary_email

            with transaction.atomic():
                user = form.save()
                notif_form.save()
                if push_form is not None:
                    push_form.save()
                if "email" in form.changed_data:
                    reconcile_primary_email(user)
```

keep the rest of the POST branch (session language, message, redirect, cookie) unchanged, then:

```python
    else:
        form = UserSettingsForm(instance=request.user)
        notif_form = NotificationEmailForm(instance=pref)
        push_form = (
            NotificationPushForm(instance=push_pref, prefix="push") if with_push else None
        )
```

and add `"push_form": push_form,` to the render context dict.

- [ ] **Step 6: base.html**

In `templates/base.html` `<head>`, after the viewport meta:

```html
  {% if push_available %}<meta name="libli-push" data-vapid-key="{{ push_vapid_key }}" data-session-endpoint="{{ push_session_endpoint }}" data-remembered="{{ push_remembered|yesno:'1,0' }}" data-subscribe-url="{% url 'notifications:push_subscribe' %}" data-unsubscribe-url="{% url 'notifications:push_unsubscribe' %}" data-claim-url="{% url 'notifications:push_claim' %}" data-msg-error="{% trans "Couldn't change push notifications. Try again." %}">{% endif %}
```

Change the logout form tag to `<form method="post" action="{% url 'account_logout' %}" data-logout-form>`.

After the `pwa.js` script line:

```html
  {% if push_available %}<script src="{% static 'core/js/push.js' %}" defer></script>{% endif %}
```

(`push.js` arrives in Task 8; until then the 404 for the script is harmless in tests, which only assert the tag.)

- [ ] **Step 7: The settings template**

Replace the whole `<section class="settings-section">` that starts with `<h2 class="settings-sec-title">{% trans "Email notifications" %}</h2>` in `templates/core/user_settings.html` with:

```html
    <section class="settings-section">
      {% if push_form %}
      <h2 class="settings-sec-title">{% trans "Notifications" %}</h2>
      <p class="settings-sec-lede">{% trans "Choose which events email you and which send a push notification. The bell always shows everything." %}</p>

      <div class="settings-field" data-push-device>
        <div>
          <div class="settings-field-label">{% trans "Push notifications on this device" %}</div>
          <p class="settings-field-help" data-push-help hidden>{% trans "On a shared computer, log out when you finish." %}</p>
        </div>
        <div class="settings-field-control">
          <label class="switch" data-push-switch-wrap>
            <input type="checkbox" data-push-switch disabled aria-label="{% trans 'Push notifications on this device' %}">
            <span class="switch__track" aria-hidden="true"></span>
          </label>
          <p class="settings-field-help" data-push-state="unsupported" hidden>{% trans "This browser can't show push notifications." %}</p>
          <p class="settings-field-help" data-push-state="not-remembered" hidden>{% trans "To get push notifications on this device, tick 'Remember me' when you log in." %}</p>
          <p class="settings-field-help" data-push-state="ios-not-installed" hidden>{% trans "On iPhone and iPad, add libli to your Home Screen first." %} <a href="{% url 'core:install_app' %}">{% trans "How to install" %}</a></p>
          <p class="settings-field-help" data-push-state="blocked" hidden>{% trans "Notifications are blocked for libli in this browser's settings." %}</p>
          <p class="settings-field-help settings-field-error" data-push-error hidden></p>
        </div>
      </div>

      <div class="settings-field settings-field--cols" aria-hidden="true">
        <div></div>
        <div class="settings-field-control settings-cols">
          <span>{% trans "Email" %}</span><span>{% trans "Push" %}</span>
        </div>
      </div>
      {% else %}
      <h2 class="settings-sec-title">{% trans "Email notifications" %}</h2>
      <p class="settings-sec-lede">{% trans "Choose which events email you. In-app notifications are always shown." %}</p>
      {% endif %}

      {% for key, label, help_email, help_neutral in notif_rows %}
      <div class="settings-field">
        <div>
          <div class="settings-field-label">{{ label }}</div>
          <p class="settings-field-help">{% if push_form %}{{ help_neutral }}{% else %}{{ help_email }}{% endif %}</p>
        </div>
        <div class="settings-field-control{% if push_form %} settings-cols{% endif %}">
          <label class="switch">
            <input type="checkbox" name="{{ key }}" {% if key in notif_on %}checked{% endif %} aria-label="{% if push_form %}{% blocktrans %}Email: {{ label }}{% endblocktrans %}{% else %}{{ help_email }}{% endif %}">
            <span class="switch__track" aria-hidden="true"></span>
          </label>
          {% if push_form %}
          <label class="switch">
            <input type="checkbox" name="push-{{ key }}" {% if key in push_on %}checked{% endif %} aria-label="{% blocktrans %}Push: {{ label }}{% endblocktrans %}">
            <span class="switch__track" aria-hidden="true"></span>
          </label>
          {% endif %}
        </div>
      </div>
      {% endfor %}
    </section>
```

To feed it, add in `core/views.py` (module level, above `user_settings`):

```python
def _notif_rows():
    """(field, label, email-era help, neutral help) for the Notifications section, in
    the order the page has always shown them."""
    return [
        ("quiz_graded", _("Quiz graded"),
         _("Email me when a quiz I submitted is graded."),
         _("When a quiz I submitted is graded.")),
        ("enrolled", _("Course enrollment"),
         _("Email me when I'm enrolled in a course."),
         _("When I'm enrolled in a course.")),
        ("quiz_needs_review", _("Quiz needs review"),
         _("Email me when a student's quiz needs my review."),
         _("When a student's quiz needs my review.")),
    ]
```

and in the render context:

```python
            "notif_rows": _notif_rows(),
            "notif_on": {k for k in ("quiz_graded", "enrolled", "quiz_needs_review")
                         if notif_form[k].value()},
            "push_on": ({k for k in ("quiz_graded", "enrolled", "quiz_needs_review")
                         if push_form[k].value()} if push_form else set()),
```

(`_` in `core/views.py` is already `gettext` — confirm the import at the top of the file; if it is `gettext_lazy`, keep it, the template renders it.) The three English email-era strings are unchanged msgids, so the dark-box page is byte-identical in wording to today's.

Append to `core/static/core/css/settings.css`:

```css
/* PWA C2: the device switch is hidden in the four can't-work states; .switch's
   display:inline-flex would otherwise beat the UA [hidden] style. */
.switch[hidden] { display: none; }
/* PWA C2: Email | Push columns. row overrides .settings-field-control's column. */
.settings-cols { flex-direction: row; gap: var(--space-4); align-items: center; }
.settings-cols > span { width: 40px; text-align: center; font-size: .8rem; color: var(--text-secondary); }
.settings-field--cols { padding-bottom: 0; }
.settings-field-error { color: var(--danger); }
```

(`.8rem` matches `.settings-field-help`; tokens.css has no font-size tokens. Check `--danger` and `--text-secondary` exist with `grep -n "\-\-danger\|\-\-text-secondary" core/static/core/css/tokens.css` and use the existing names if they differ.)

- [ ] **Step 8: Run the tests**

Run: `uv run pytest notifications/tests/test_push_settings.py notifications/tests/test_email_settings.py` and `uv run pytest tests -k css` (marker-based CSS tests can be broken by any new rule), then `uv run pytest -m e2e notifications/tests/test_e2e_email_prefs.py`
Expected: PASS (the email e2e still finds `input[name='quiz_graded']`).

- [ ] **Step 9: Falsify** — drop `prefix="push"` from the POST construction → `test_columns_save_independently` FAILS. Compute `push_pref` and bind `push_form` regardless of `with_push` (i.e. replace `with_push` by `True` in both conditionals) → `test_dark_box_post_leaves_the_push_row_alone` FAILS because the row turns all-False. Revert.

- [ ] **Step 10: Screenshots** — run the dev server with push configured (export the TWO lines `generate_vapid_keys` prints, plus `LIBLI_VAPID_SUBJECT=mailto:dev@example.com` and `LIBLI_PWA_ENABLED=true`; first confirm `/settings/` shows the "Notifications" heading — if it shows "Email notifications", push is not configured and the screenshots would show the dark page), open `/settings/` in light AND dark themes at 390 px and 1280 px; check the Email|Push headers sit over their switches and the state lines wrap. Judge dark separately.

- [ ] **Step 11: Commit**

```bash
git add notifications/forms.py notifications/context_processors.py config/settings/base.py core/views.py templates/core/user_settings.html templates/base.html core/static/core/css/settings.css notifications/tests/test_push_settings.py
git commit -m "feat(push): settings page push column, device switch markup, page meta"
```

---

### Task 7: Bell invite markup

**Files:**
- Modify: `notifications/templates/notifications/_bell_panel.html` (top of file, before `{% if notifications_recent %}`)
- Modify: `core/static/core/css/app.css` (after `.notif-menu__empty`, ~line 1389)
- Test: `notifications/tests/test_push_bell.py`

**Interfaces:**
- Produces: `[data-push-invite]` (hidden) containing `[data-push-invite-on]` button, `[data-push-invite-dismiss]` button, `[data-push-error]`.

- [ ] **Step 1: Failing tests**

Create `notifications/tests/test_push_bell.py`:

```python
import pytest
from django.urls import reverse

from notifications.tests.push_helpers import logged_in_user
from notifications.tests.push_helpers import push_settings

pytestmark = pytest.mark.django_db


def _html(client):
    logged_in_user(client)
    return client.get(reverse("core:user_settings")).content.decode()


def test_invite_absent_on_a_dark_box(client):
    assert "data-push-invite" not in _html(client)


def test_invite_rendered_hidden_when_configured(client, settings):
    push_settings(settings)
    html = _html(client)
    start = html.index("data-push-invite")
    tag = html[html.rindex("<", 0, start): html.index(">", start)]
    assert " hidden" in tag
    assert "data-push-invite-on" in html and "data-push-invite-dismiss" in html


def test_invite_present_with_an_empty_panel(client, settings):
    push_settings(settings)
    html = _html(client)
    assert "You have no notifications yet." in html
    assert "data-push-invite" in html
```

- [ ] **Step 2: Run** — `uv run pytest notifications/tests/test_push_bell.py` → FAIL on the configured cases.

- [ ] **Step 3: Markup** — insert at the top of `_bell_panel.html`, right after `{% load i18n %}`:

```html
{% if push_available %}
<div class="notif-menu__push" data-push-invite hidden>
  <span class="notif-menu__push-text">{% trans "Get notifications on this device" %}</span>
  <button type="button" class="btn btn--small" data-push-invite-on>{% trans "Turn on" %}</button>
  <button type="button" class="btn--icon notif-menu__push-dismiss" data-push-invite-dismiss aria-label="{% trans 'Dismiss' %}">
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false"><path d="M3.5 3.5l9 9m0-9l-9 9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none"/></svg>
  </button>
  <p class="notif-menu__push-error" data-push-error hidden></p>
</div>
{% endif %}
```

Append to `core/static/core/css/app.css` after the `.notif-menu__empty` rule:

```css
/* PWA C2 bell invite: one row above the list; push.js unhides it. */
.notif-menu__push { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2);
  padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border-subtle); }
.notif-menu__push[hidden] { display: none; }
.notif-menu__push-text { flex: 1 1 0; min-width: 0; }
.notif-menu__push-error { flex-basis: 100%; margin: 0; color: var(--danger); }
.notif-menu__push-error[hidden] { display: none; }
```

(The `[hidden]` rules are needed because `display:flex` beats the UA `hidden` style. Confirm every custom property used exists: `grep -n "\-\-border-subtle\|\-\-danger\|\-\-space-2\|\-\-space-3" core/static/core/css/tokens.css` — an undefined one silently drops the declaration. Run EVERY `tests/test_*css*.py` after this edit: `uv run pytest tests -k css`.)

- [ ] **Step 4: Run** — `uv run pytest notifications/tests/test_push_bell.py notifications/tests/test_bell_render.py` and `uv run pytest tests -k css` → PASS.

- [ ] **Step 5: Commit**

```bash
git add notifications/templates/notifications/_bell_panel.html core/static/core/css/app.css notifications/tests/test_push_bell.py
git commit -m "feat(push): bell invite row markup"
```

---

### Task 8: push.js — device state, claim, subscribe/unsubscribe, UI

**Files:**
- Modify: `core/static/core/js/pwa.js` (the `register()` call)
- Create: `core/static/core/js/push.js`
- Test: `notifications/tests/test_push_js_source.py` (source guards; behaviour is Task 10's e2e)

**Interfaces:**
- Consumes: DOM hooks from Tasks 6–7; endpoints from Task 4; `window.libliSwRegistration` (this task).
- Produces: `window.libliPush = { state: <string>, refresh(): Promise }` (used by e2e to wait for a reported state); `document.documentElement.dataset.pushReported` set to the reported state (e2e waits on `html[data-push-reported=...]`; a DIFFERENT attribute name from the state lines' `data-push-state`, so state-line locators never also match `<html>`).

- [ ] **Step 1: Publish the registration promise in `pwa.js`**

Replace the registration block in `core/static/core/js/pwa.js`:

```js
  if ("serviceWorker" in navigator) {
    // Published for push.js: unlike navigator.serviceWorker.ready this promise
    // always settles (it rejects when registration is refused).
    window.libliSwRegistration = navigator.serviceWorker
      .register("/sw.js", { scope: "/", updateViaCache: "none" });
    window.libliSwRegistration.catch(function (err) {
      console.warn("libli: service worker registration failed", err);
    });
  }
```

- [ ] **Step 2: Write source-guard tests**

Create `notifications/tests/test_push_js_source.py`:

```python
"""Source guards for push.js where the e2e cannot see the property."""

from pathlib import Path

from django.conf import settings

JS = (Path(settings.BASE_DIR) / "core/static/core/js/push.js").read_text(encoding="utf-8")
PWA = (Path(settings.BASE_DIR) / "core/static/core/js/pwa.js").read_text(encoding="utf-8")


def test_never_waits_on_ready_for_the_page_state():
    # ready is allowed ONLY inside subscribe(), bounded by a timeout
    assert JS.count("serviceWorker.ready") == 1
    assert "withTimeout(navigator.serviceWorker.ready" in JS


def test_pwa_publishes_its_registration_promise():
    assert "window.libliSwRegistration = navigator.serviceWorker" in PWA


def test_builds_no_user_facing_text():
    assert "textContent = msg" in JS  # the one dynamic string comes from data-msg-error
    for english in ("Turn on", "Notifications are blocked", "can't show", "Home Screen",
                    "Try again", "Remember me"):
        assert english not in JS


def test_dismiss_flag_name():
    assert '"libli:push-invite-dismissed"' in JS
```

- [ ] **Step 3: Run** — FAIL (`push.js` missing).

- [ ] **Step 4: Write `core/static/core/js/push.js`**

```js
/* PWA C2 push client (spec docs/superpowers/specs/2026-10-16-pwa-c2-web-push-design.md §6-§8).
   Loaded only when push is configured. Builds NO user-facing text: every line is
   server-rendered and hidden; this file toggles `hidden` and fills the one error line
   from data-msg-error. */
(function () {
  "use strict";

  var meta = document.querySelector('meta[name="libli-push"]');
  if (!meta) return;

  var DISMISS_KEY = "libli:push-invite-dismissed";
  var CANNOT = ["unsupported", "not-remembered", "ios-not-installed", "blocked"];
  var sessionEndpoint = meta.getAttribute("data-session-endpoint") || "";
  var busy = false;
  var api = { state: "pending", refresh: refresh };
  window.libliPush = api;

  function getCookie(name) {
    var m = document.cookie.match("(?:^|; )" + name + "=([^;]+)");
    return m ? decodeURIComponent(m[1]) : null;
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) throw new Error("push request failed: " + r.status);
      return r.json();
    });
  }

  function withTimeout(promise, ms) {
    return new Promise(function (resolve, reject) {
      var t = setTimeout(function () { reject(new Error("timeout")); }, ms);
      promise.then(function (v) { clearTimeout(t); resolve(v); },
                   function (e) { clearTimeout(t); reject(e); });
    });
  }

  function isIos() {
    return /iPhone|iPad|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  function standalone() {
    return window.matchMedia("(display-mode: standalone)").matches ||
      navigator.standalone === true;
  }

  function supported() {
    return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  }

  function registration() {
    var p = window.libliSwRegistration;
    if (!p) return Promise.resolve(undefined);
    return withTimeout(p, 5000).catch(function () { return undefined; });
  }

  function keyBytes(b64) {
    var s = (b64 + "===".slice((b64.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function storageGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function storageSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* storage off: fine */ }
  }

  // The claim step (spec §6): acts, never reports a state.
  function claim(sub) {
    if (!sub || sub.endpoint === sessionEndpoint) return Promise.resolve();
    return post(meta.getAttribute("data-claim-url"), { endpoint: sub.endpoint })
      .then(function (res) {
        if (res.mine) { sessionEndpoint = sub.endpoint; return; }
        return sub.unsubscribe().catch(function () {});
      })
      .catch(function () { /* retried on the next page load */ });
  }

  function evaluate() {
    if (isIos() && !standalone()) return Promise.resolve({ state: "ios-not-installed" });
    if (!supported()) return Promise.resolve({ state: "unsupported" });
    return registration().then(function (reg) {
      if (!reg) return { state: "unsupported" };
      return reg.pushManager.getSubscription().catch(function () { return null; })
        .then(function (sub) { return claim(sub).then(function () { return reg; }); })
        .then(function (reg2) {
          if (meta.getAttribute("data-remembered") === "0") return { state: "not-remembered", reg: reg2 };
          if (Notification.permission === "denied") return { state: "blocked", reg: reg2 };
          return reg2.pushManager.getSubscription().catch(function () { return null; })
            .then(function (sub) { return { state: sub ? "on" : "off", reg: reg2, sub: sub }; });
        });
    });
  }

  // --- rendering ------------------------------------------------------------------

  function each(selector, fn) {
    [].forEach.call(document.querySelectorAll(selector), fn);
  }

  function showError(scope, on) {
    each(scope + " [data-push-error]", function (el) {
      var msg = on ? meta.getAttribute("data-msg-error") : "";
      el.textContent = msg;
      el.hidden = !on;
    });
  }

  function render(state) {
    api.state = state;
    document.documentElement.setAttribute("data-push-reported", state);
    var cannot = CANNOT.indexOf(state) !== -1;
    each("[data-push-device] [data-push-state]", function (el) {
      el.hidden = el.getAttribute("data-push-state") !== state;
    });
    each("[data-push-switch-wrap]", function (el) { el.hidden = cannot; });
    each("[data-push-help]", function (el) { el.hidden = cannot; });
    each("input[data-push-switch]", function (el) {
      // While a request is in flight keep the user's click visible (Playwright's
      // check() also requires the box to stay as clicked); refresh() settles it.
      if (!busy) el.checked = state === "on";
      el.disabled = cannot || busy;
    });
    each("[data-push-invite]", function (el) {
      el.hidden = !(state === "off" && storageGet(DISMISS_KEY) !== "1");
    });
  }

  function refresh() {
    // Terminal fallback: any rejection in the evaluation (e.g. a registration with no
    // usable pushManager) must still report a state -- never a disabled switch with
    // no line (spec §10, registration refused).
    return evaluate()
      .catch(function () { return { state: "unsupported" }; })
      .then(function (r) { render(r.state); return r; });
  }

  // --- actions --------------------------------------------------------------------

  function subscribe() {
    return Notification.requestPermission().then(function (perm) {
      if (perm !== "granted") return;
      return withTimeout(navigator.serviceWorker.ready, 10000).then(function (reg) {
        return reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: keyBytes(meta.getAttribute("data-vapid-key"))
        });
      }).then(function (sub) {
        return post(meta.getAttribute("data-subscribe-url"), sub.toJSON())
          .then(function () { sessionEndpoint = sub.endpoint; })
          .catch(function (err) {
            // Never leave the browser holding a subscription the server does not know.
            return sub.unsubscribe().catch(function () {}).then(function () { throw err; });
          });
      });
    });
  }

  function unsubscribe(sub) {
    return post(meta.getAttribute("data-unsubscribe-url"), { endpoint: sub.endpoint })
      .then(function () {
        sessionEndpoint = "";
        return sub.unsubscribe().catch(function () { /* the claim step tidies it */ });
      });
  }

  function act(scope, action) {
    if (busy) return Promise.resolve();
    busy = true;
    render(api.state);
    showError(scope, false);
    // Promise.resolve().then(action): a synchronous throw (e.g. an old Safari whose
    // requestPermission returns undefined) becomes a rejection, so busy always resets.
    return Promise.resolve().then(action)
      .then(function () { return false; }, function () { return true; })
      .then(function (failed) {
        busy = false;
        return refresh()
          .catch(function () { failed = true; })
          .then(function () { showError(scope, failed); });
      });
  }

  document.addEventListener("change", function (e) {
    var box = e.target.closest && e.target.closest("input[data-push-switch]");
    if (!box) return;
    var wantOn = box.checked;
    act("[data-push-device]", function () {
      if (wantOn) return subscribe();
      return registration().then(function (reg) {
        return reg ? reg.pushManager.getSubscription() : null;
      }).then(function (sub) { return sub ? unsubscribe(sub) : null; });
    });
  });

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-push-invite-on]")) {
      act("[data-push-invite]", subscribe);
    } else if (e.target.closest("[data-push-invite-dismiss]")) {
      storageSet(DISMISS_KEY, "1");
      each("[data-push-invite]", function (el) { el.hidden = true; });
    }
  });

  // Logout: tidy the browser best-effort; the server receiver is the guarantee.
  document.addEventListener("submit", function (e) {
    if (!e.target.matches || !e.target.matches("form[data-logout-form]")) return;
    registration().then(function (reg) {
      return reg && reg.pushManager.getSubscription();
    }).then(function (sub) { if (sub) sub.unsubscribe(); }).catch(function () {});
  });

  refresh();
})();
```

- [ ] **Step 5: Run** — `uv run pytest notifications/tests/test_push_js_source.py tests/test_pwa_shell.py` → PASS, then `uv run pytest -m e2e tests/test_e2e_pwa.py -n 2` (the `pwa.js` registration block changed; C1's e2e must stay green). Also `node --check core/static/core/js/push.js` if Node is on PATH (syntax only).

- [ ] **Step 6: Commit**

```bash
git add core/static/core/js/pwa.js core/static/core/js/push.js notifications/tests/test_push_js_source.py
git commit -m "feat(push): push.js device state, claim and subscribe flow"
```

---

### Task 9: Service worker `push` and `notificationclick`

**Files:**
- Modify: `templates/core/sw.js` (inside `{% verbatim %}`, after the `fetch` listener)
- Test: `tests/test_pwa_worker.py` (append)

**Interfaces:**
- Produces: worker functions `showPush(payload)` and `targetUrl(raw)` (named, so the e2e fallback can call them in the worker context).

- [ ] **Step 1: Failing tests** — append to `tests/test_pwa_worker.py`:

```python
def test_worker_has_push_handlers_and_no_new_value_slot(client, settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    body = client.get("/sw.js").content.decode()
    assert 'addEventListener("push"' in body
    assert 'addEventListener("notificationclick"' in body
    assert "function targetUrl(" in body and "function showPush(" in body
    assert "includeUncontrolled" not in body  # navigate() rejects for uncontrolled clients
    assert "badge" not in body


def test_sw_bytes_do_not_depend_on_a_favicon_override(client, settings):
    from unittest import mock

    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    from core.services import get_site_config

    plain = client.get("/sw.js").content
    cfg = {**get_site_config(), "favicon_url": "/media/x.png"}
    # core.views imports get_site_config BY NAME, so patch it there too.
    with mock.patch("core.views.get_site_config", return_value=cfg), \
            mock.patch("core.services.get_site_config", return_value=cfg):
        overridden = client.get("/sw.js").content
    assert plain == overridden


def test_kill_worker_has_no_push_handlers(client, settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = True
    body = client.get("/sw.js").content.decode()
    assert '"push"' not in body
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_pwa_worker.py` → the new handler test FAILS.

- [ ] **Step 3: Add to `templates/core/sw.js`** before `{% endverbatim %}`:

```js
// --- push (PWA C2 spec §5). Every value comes from the payload; this file gains no
// value slot, so /sw.js bytes and VERSION are unaffected by branding.
function targetUrl(raw) {
  try {
    const url = new URL(raw, self.location.origin);
    return url.origin === self.location.origin ? url.href : null;
  } catch (e) {
    return null;
  }
}

function showPush(payload) {
  return self.registration.showNotification(payload.title, {
    body: payload.body,
    tag: payload.tag,
    icon: payload.icon,
    data: { url: payload.url },
  });
}

self.addEventListener("push", (event) => {
  let payload;
  try {
    payload = event.data.json();
  } catch (e) {
    return; // the browser may show its own generic notice; our payloads always parse
  }
  event.waitUntil(showPush(payload));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = targetUrl((event.notification.data || {}).url || "/");
  if (!url) return;
  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then((list) => {
      const client = list[0];
      if (!client) return self.clients.openWindow(url);
      return client.focus()
        .then(() => client.navigate(url))
        .then((navigated) => navigated || self.clients.openWindow(url))
        .catch(() => self.clients.openWindow(url));
    })
  );
});
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_pwa_worker.py tests/test_pwa_core.py` → PASS.

- [ ] **Step 4b: Falsify** — add `"icon_json": json.dumps(get_site_config()["favicon_url"]),` to `service_worker`'s render context in `core/views.py` and `const ICON = {{ icon_json|safe }};` above `{% verbatim %}` in `sw.js` → `test_sw_bytes_do_not_depend_on_a_favicon_override` FAILS. Revert both by hand. Then paste `self.addEventListener("push", () => {});` inside `templates/core/sw_kill.js`'s verbatim block → `test_kill_worker_has_no_push_handlers` FAILS (it was green before any change); revert by hand.

- [ ] **Step 5: Commit**

```bash
git add templates/core/sw.js tests/test_pwa_worker.py
git commit -m "feat(push): worker shows pushes and opens their target"
```

---

### Task 10: End-to-end tests

**Files:**
- Create: `notifications/tests/test_e2e_push.py`

**Interfaces:**
- Consumes: everything above. Waits on `html[data-push-reported="…"]` (Task 8).

- [ ] **Step 1: Write the e2e module**

```python
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
      : "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15" });
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
    subscribe: () => { S.sub = cfg.endpoint; S.keys = cfg.keys; save(); return Promise.resolve(fakeSub()); }
  };
  Object.defineProperty(ServiceWorkerRegistration.prototype, "pushManager", { get: () => pm });
  let perm = cfg.permission || "default";
  Object.defineProperty(Notification, "permission", { get: () => perm });
  Notification.requestPermission = () => { perm = cfg.grant || "granted"; return Promise.resolve(perm); };
})();
"""

KEYS = {"p256dh": "BAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE",
        "auth": "AgICAgICAgICAgICAgICAg"}


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
    page.wait_for_selector(".bell__trigger")  # logged in, on the LOGIN_REDIRECT_URL page


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
    context.add_cookies([{
        "name": dj_settings.SESSION_COOKIE_NAME,
        "value": client.cookies[dj_settings.SESSION_COOKIE_NAME].value,
        "url": live_server.url,
    }])
    return user


def test_first_visit_reads_off_not_unsupported(page, context, live_server):
    # Review Focus 1. Must go RED with push.js's registration() reading
    # navigator.serviceWorker.getRegistration() instead of window.libliSwRegistration.
    _configure(context, live_server)
    _cookie_login(context, live_server)
    page.goto(f"{live_server.url}/settings/")  # the origin's first page: nothing registered
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
    page.route("**/notifications/push/subscribe/", lambda r: r.fulfill(status=500, body="{}"))
    page.route("**/notifications/push/claim/", lambda r: r.fulfill(
        status=200, content_type="application/json", body='{"mine": true}'))
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
    page.evaluate("() => { const s = JSON.parse(localStorage.__pushStub || '{}');"
                  f" s.sub = '{ENDPOINT}'; localStorage.__pushStub = JSON.stringify(s); }}")
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


@pytest.mark.parametrize("permission,mine,state", [
    ("denied", "false", "blocked"), ("denied", "true", "blocked"),
    ("default", "false", "off"), ("default", "true", "on"),
])
def test_claim_on_load(page, context, live_server, permission, mine, state):
    _configure(context, live_server, permission=permission)
    _login(page, live_server)
    page.evaluate("() => { const s = JSON.parse(localStorage.__pushStub || '{}');"
                  f" s.sub = '{ENDPOINT}'; localStorage.__pushStub = JSON.stringify(s); }}")
    page.route("**/notifications/push/claim/", lambda r: r.fulfill(
        status=200, content_type="application/json", body=f'{{"mine": {mine}}}'))
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
    context.add_init_script("Object.defineProperty(window, 'libliSwRegistration', "
                            "{ get: () => Promise.reject(new Error('refused')), set: () => {} });")
    _configure(context, live_server)
    _login(page, live_server)
    _settings(page, live_server, "unsupported")
    expect(page.locator('[data-push-state="unsupported"]')).to_be_visible()
    page.locator(".bell__trigger").click()
    expect(page.locator("[data-push-invite]")).to_be_hidden()


def test_a_registration_without_push_manager_reads_unsupported(page, context, live_server):
    # mutant: refresh() without its terminal .catch -> the page stays "pending" forever
    context.add_init_script(
        "Object.defineProperty(ServiceWorkerRegistration.prototype, 'pushManager', "
        "{ get: () => undefined });"
    )
    _login(page, live_server)
    _settings(page, live_server, "unsupported")
    expect(page.locator('[data-push-device] [data-push-state="unsupported"]')).to_be_visible()


def test_bell_invite_turn_on_dismiss_and_errors(page, context, live_server):
    _configure(context, live_server)
    _login(page, live_server)
    page.wait_for_selector('html[data-push-reported="off"]')
    page.locator(".bell__trigger").click()
    invite = page.locator("[data-push-invite]")
    expect(invite).to_be_visible()
    page.route("**/notifications/push/subscribe/", lambda r: r.fulfill(status=500, body="{}"))
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
        context.add_init_script("Object.defineProperty(window, 'libliSwRegistration', "
                                "{ get: () => Promise.reject(new Error('refused')), set: () => {} });")
    _configure(context, live_server,
               **({"ios": "iphone"} if case == "ios" else {}),
               **({"permission": "denied"} if case == "blocked" else {}))
    _login(page, live_server, remember=case != "not-remembered")
    state = {"ios": "ios-not-installed"}.get(case, case)
    _settings(page, live_server, state)
    expect(page.locator("[data-push-help]")).to_be_hidden()


def test_blocked_with_a_foreign_leftover_deletes_the_server_row(page, context, live_server):
    # The REAL claim endpoint (no page.route): another user's row for this browser's
    # endpoint is deleted, the browser unsubscribes, and the state still reads blocked.
    from notifications.tests.push_helpers import make_sub
    from tests.factories import UserFactory

    _configure(context, live_server, permission="denied")
    _login(page, live_server)
    make_sub(UserFactory(), "x" * 32, endpoint=ENDPOINT)
    page.evaluate("() => { const s = JSON.parse(localStorage.__pushStub || '{}');"
                  f" s.sub = '{ENDPOINT}'; localStorage.__pushStub = JSON.stringify(s); }}")
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
    worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
    assert worker.evaluate("targetUrl('https://evil.example/x')") is None
    assert worker.evaluate("targetUrl('/notifications/5/open/')") == f"{live_server.url}/notifications/5/open/"


def test_worker_shows_a_delivered_push(page, context, live_server):
    context.grant_permissions(["notifications"], origin=live_server.url)
    _login(page, live_server)
    page.evaluate("async () => { await navigator.serviceWorker.ready; }")
    cdp = context.new_cdp_session(page)
    regs = []
    cdp.on("ServiceWorker.workerRegistrationUpdated", lambda e: regs.extend(e["registrations"]))
    cdp.send("ServiceWorker.enable")
    for _ in range(50):
        if any(not r.get("isDeleted") for r in regs):
            break
        page.wait_for_timeout(100)
    reg_id = next(r["registrationId"] for r in regs if not r.get("isDeleted"))
    payload = {"title": "T", "body": "B", "url": "/notifications/", "tag": "libli-1", "icon": ""}
    cdp.send("ServiceWorker.deliverPushMessage",
             {"origin": live_server.url, "registrationId": reg_id, "data": json.dumps(payload)})
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
```

Two notes for the implementer, recorded here so they are not rediscovered:
- `page.wait_for_function` with an ASYNC predicate is vacuous (a Promise is truthy) — the worker test polls `page.evaluate` instead; do the same for any other async check you add.
- If CDP `deliverPushMessage` proves unworkable (no `workerRegistrationUpdated` event, or it needs a real subscription), switch `test_worker_shows_a_delivered_push` to the fallback named in the spec: evaluate `showPush({...})` inside the worker via `context.service_workers[0].evaluate(...)` and assert `getNotifications()`. Record which route was used in the PR body. `test_worker_refuses_off_origin_targets` runs either way.
- Polish rendering of EVERY state line and the bell row is pinned server-side in Task 11 (`test_settings_and_bell_render_polish`), since push.js only toggles server-rendered text; the e2e Polish test here covers the quoted login label end to end.

- [ ] **Step 2: Run** — `uv run pytest -m e2e notifications/tests/test_e2e_push.py -n 2`
Expected: PASS, EXCEPT `test_polish_lines_and_the_quoted_login_label`, which FAILS until Task 11 writes the Polish catalog (the not-remembered line still renders in English). That failure is expected here — do not touch the test, template or push.js for it; Task 11 Step 4 re-runs it. Any test passing on the FIRST run must still be falsified (Step 3).

- [ ] **Step 3: Falsify** — (a) in `push.js` make `registration()` call `navigator.serviceWorker.getRegistration()` instead of the published promise → `test_first_visit_reads_off_not_unsupported` MUST FAIL. The test logs in by cookie so `/settings/` is the origin's first page and no worker exists yet; if it still stays green, the race is not being reached — STOP and fix the test (e.g. clear registrations with a fresh context, or assert the state before `navigator.serviceWorker.controller` exists) rather than keeping an unfalsified guard. (b) remove the rollback `sub.unsubscribe()` in `subscribe()` → `test_subscribe_500_rolls_back_and_shows_the_error` FAILS. (c) swap the `isIos()` and `supported()` checks in `evaluate()` → `test_ios_outside_the_app_shows_the_install_line` FAILS. (d) make `targetUrl` return `url.href` unconditionally → `test_worker_refuses_off_origin_targets` FAILS. (e) change the `[data-push-help]` toggle in `render()` to `el.hidden = false` (help shown in every state) → all four `test_help_line_hidden_in_every_cannot_state` cases FAIL. (Removing the toggle instead leaves the server-rendered `hidden` in place — that mutant is caught only by `test_off_to_on_to_off_posts_and_persists`'s `to_be_visible`, run it there.) (f) in `push_claim`, re-key instead of deleting a foreign row → `test_blocked_with_a_foreign_leftover_deletes_the_server_row` FAILS. (g) drop `disabled` from the server-rendered `input[data-push-switch]` in `user_settings.html` → `test_switch_disabled_until_a_state_is_reported` FAILS. (h) in `claim()`, skip `sub.unsubscribe()` on `mine: false` → the `("default", "false", "off")` case of `test_claim_on_load` FAILS. (i) make the dismiss handler skip `storageSet(DISMISS_KEY, "1")` → the after-reload half of `test_bell_invite_turn_on_dismiss_and_errors` FAILS. (j) in `render()`, set the invite's `el.hidden = storageGet(DISMISS_KEY) === "1"` (ignoring the state) → `test_denied_prompt_hides_the_invite` and the invite assertion in `test_not_remembered_login_shows_the_d8_line` FAIL. (k) make `registration()`'s `.catch` return `{}` instead of `undefined` AND remove `refresh()`'s terminal `.catch` (applied TOGETHER: with the fallback present, (k) alone is an equivalent mutant — the TypeError on `{}.pushManager` is caught and still reads `unsupported`) → `test_registration_refused_reads_unsupported` FAILS (times out in `pending`). (l) remove ONLY `refresh()`'s terminal `.catch` → `test_a_registration_without_push_manager_reads_unsupported` FAILS (times out in `pending`). (m) in `render()`, set the help line's `el.hidden = state !== "on"` → `test_off_to_on_to_off_posts_and_persists` FAILS at its first help assertion. Revert each by hand.

- [ ] **Step 4: Commit**

```bash
git add notifications/tests/test_e2e_push.py
git commit -m "test(push): e2e for the push client and worker"
```

---

### Task 11: Polish and English catalogs

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po`, both `.mo`
- Test: `notifications/tests/test_push_i18n.py`

- [ ] **Step 1: Failing test**

```python
"""Every new push msgid has a real Polish translation (no fuzzy, no empty)."""

import pytest
from django.utils import translation

NEW = {
    "Notifications": "Powiadomienia",
    "Choose which events email you and which send a push notification. The bell always shows everything.":
        "Wybierz, o których zdarzeniach chcesz dostawać e-mail, a o których powiadomienie push. Dzwonek zawsze pokazuje wszystko.",
    "Push notifications on this device": "Powiadomienia push na tym urządzeniu",
    "On a shared computer, log out when you finish.": "Na wspólnym komputerze wyloguj się, gdy skończysz.",
    "This browser can't show push notifications.": "Ta przeglądarka nie obsługuje powiadomień push.",
    "To get push notifications on this device, tick 'Remember me' when you log in.":
        "Aby dostawać powiadomienia push na tym urządzeniu, zaznacz „Zapamiętaj mnie” przy logowaniu.",
    "On iPhone and iPad, add libli to your Home Screen first.":
        "Na iPhonie i iPadzie najpierw dodaj libli do ekranu początkowego.",
    "How to install": "Jak zainstalować",
    "Notifications are blocked for libli in this browser's settings.":
        "Powiadomienia z libli są zablokowane w ustawieniach tej przeglądarki.",
    "Email": "E-mail",
    "Push": "Push",
    "When a quiz I submitted is graded.": "Gdy mój przesłany quiz zostanie oceniony.",
    "When I'm enrolled in a course.": "Gdy zostanę zapisany(-a) na kurs.",
    "When a student's quiz needs my review.": "Gdy quiz ucznia wymaga mojego sprawdzenia.",
    "Couldn't change push notifications. Try again.":
        "Nie udało się zmienić powiadomień push. Spróbuj ponownie.",
    "Get notifications on this device": "Otrzymuj powiadomienia na tym urządzeniu",
    "Turn on": "Włącz",
    "Dismiss": "Zamknij",
    "Email: %(label)s": "E-mail: %(label)s",
    "Push: %(label)s": "Push: %(label)s",
}


@pytest.mark.parametrize("msgid", sorted(NEW))
def test_polish_translation(msgid):
    with translation.override("pl"):
        assert translation.gettext(msgid) == NEW[msgid]


@pytest.mark.parametrize("msgid", sorted(k for k, v in NEW.items() if k == v))
def test_identical_translations_are_really_filled(msgid):
    """gettext returns the msgid for an EMPTY msgstr, so for entries whose Polish
    equals the English the comparison above cannot fail; read the .po instead."""
    from pathlib import Path

    from django.conf import settings as dj_settings

    po = (Path(dj_settings.BASE_DIR) / "locale/pl/LC_MESSAGES/django.po").read_text(encoding="utf-8")
    entry = po.split(f'msgid "{msgid}"\n', 1)[1].split("\n\n", 1)[0]
    assert f'msgstr "{NEW[msgid]}"' in entry


@pytest.mark.django_db
def test_settings_and_bell_render_polish(client, settings):
    """Every server-rendered push line (state lines, help, bell row, error string)
    renders in Polish -- push.js only toggles them, so this is where pl is proven."""
    from django.urls import reverse

    from notifications.tests.push_helpers import logged_in_user
    from notifications.tests.push_helpers import push_settings

    push_settings(settings)
    logged_in_user(client, language="pl")
    html = client.get(reverse("core:user_settings"), HTTP_ACCEPT_LANGUAGE="pl").content.decode()
    for msgid in (
        "This browser can't show push notifications.",
        "To get push notifications on this device, tick 'Remember me' when you log in.",
        "On iPhone and iPad, add libli to your Home Screen first.",
        "Notifications are blocked for libli in this browser's settings.",
        "On a shared computer, log out when you finish.",
        "Get notifications on this device",
        "Push notifications on this device",
    ):
        assert NEW[msgid] in html, msgid
    # the error string travels in an attribute, HTML-escaped
    assert "Nie udało się zmienić powiadomień push" in html
```

Before writing the Polish, check the existing catalog for msgids that already exist (`Email`, `Notifications`, `Dismiss`, `Turn on` may already be translated — `grep -n 'msgid "Email"' locale/pl/LC_MESSAGES/django.po`). Where one exists, keep ITS translation and change the test's expected value to match it (never retranslate an existing msgid). The two `blocktrans` strings (`"Email: %(label)s"`, `"Push: %(label)s"`) are in `NEW` too. (If `makemessages` wraps a long msgid across lines, the `.po`-reading test's `split` will not find it — none of the identical-translation msgids is long enough to wrap.)

- [ ] **Step 2: Run** — FAIL (untranslated).

- [ ] **Step 3: Extract and translate**

Run: `uv run python manage.py makemessages -l pl -l en --no-obsolete`. In `locale/pl/LC_MESSAGES/django.po` fill each new `msgstr` from the table; for any entry marked `#, fuzzy`, delete the `#, fuzzy` line, any `#| msgid "…"` previous-msgid line beside it, AND replace the pre-filled msgstr (fuzzy matches are wrong translations). Then `uv run python manage.py compilemessages`.

- [ ] **Step 4: Run** — `uv run pytest notifications/tests/test_push_i18n.py notifications/tests/test_i18n.py tests -k "i18n"` → PASS (the existing no-fuzzy / no-obsolete guards included), then `uv run pytest -m e2e notifications/tests/test_e2e_push.py::test_polish_lines_and_the_quoted_login_label` → PASS now (it was expected RED at Task 10).

- [ ] **Step 5: Commit**

```bash
git add locale/ notifications/tests/test_push_i18n.py
git commit -m "i18n(push): Polish catalog for the push strings"
```

---

### Task 12: Runbook

**Files:**
- Modify: `docs/deployment.md` (new `### Push notifications` subsection in §9, directly before `### PWA kill switch`; one line in `### Rolling back across a migration: restore in place`)
- Create: `tests/test_push_runbook.py`

- [ ] **Step 1: Failing test**

```python
"""PWA C2 §9: the push runbook carries the commands and rules that matter."""

from pathlib import Path

from django.conf import settings

TEXT = (Path(settings.BASE_DIR) / "docs/deployment.md").read_text(encoding="utf-8")


def _section():
    start = TEXT.index("### Push notifications")
    return TEXT[start : TEXT.index("\n### ", start + 1)]


def test_runbook_steps():
    s = _section()
    assert "bash manage.sh generate_vapid_keys" in s
    assert "LIBLI_VAPID_SUBJECT=mailto:" in s
    assert "up -d --force-recreate app" in s
    assert "never copy them between schools" in s.lower() or "never copy" in s
    assert "rotate" in s
    assert "slows" in s
    # replace-if-present, append-if-not (a blind append would duplicate keys)
    assert 'grep -q "^$1=" .env.production' in s
    assert 'sed -i "s|^$1=.*|$1=$2|" .env.production' in s
    assert "set_env LIBLI_VAPID_PUBLIC_KEY" in s
    # turning it off
    assert "sed -i 's/^LIBLI_VAPID_" in s
    assert "docker compose restart" in s  # named, as the thing NOT to do


def test_restore_section_mentions_vapid_keys():
    start = TEXT.index("### Rolling back across a migration: restore in place")
    block = TEXT[start : TEXT.index("\n### ", start + 1)]
    assert "VAPID" in block


def test_env_example_lists_the_three_vars():
    text = (Path(settings.BASE_DIR) / ".env.production.example").read_text(encoding="utf-8")
    for var in ("LIBLI_VAPID_PUBLIC_KEY=", "LIBLI_VAPID_PRIVATE_KEY=", "LIBLI_VAPID_SUBJECT="):
        assert f"\n{var}\n" in text
```

- [ ] **Step 2: Run** — the two runbook tests FAIL; `test_env_example_lists_the_three_vars` already PASSES (Task 1 added the lines). Falsify it now: delete the `LIBLI_VAPID_SUBJECT=` line from `.env.production.example`, see it RED, restore the line by hand.

- [ ] **Step 3: Write the runbook** — insert before `### PWA kill switch`:

````markdown
### Push notifications

Push ships dark: a box without the three `LIBLI_VAPID_*` values shows no push UI and sends
nothing. To turn it on for one box:

```bash
# on the box, in /opt/libli
bash manage.sh generate_vapid_keys
# prints two lines: LIBLI_VAPID_PUBLIC_KEY=... and LIBLI_VAPID_PRIVATE_KEY=...
```

Put both values, plus `LIBLI_VAPID_SUBJECT=mailto:<contact address>` (libli's convention; an
`https:` URL also works, any other value turns push off), into `.env.production`. A box
provisioned after this release already has the three lines, blank; an older box has none — so
each line is REPLACED if present and appended if not (never a blind append, which would leave
duplicate keys):

```bash
# on the box, in /opt/libli -- paste the two values the command printed
set_env() {
  if grep -q "^$1=" .env.production; then
    sed -i "s|^$1=.*|$1=$2|" .env.production
  else
    [ -n "$(tail -c1 .env.production)" ] && echo >> .env.production   # end the last line first
    echo "$1=$2" >> .env.production
  fi
}
set_env LIBLI_VAPID_PUBLIC_KEY '<public key>'
set_env LIBLI_VAPID_PRIVATE_KEY '<private key>'
set_env LIBLI_VAPID_SUBJECT 'mailto:<contact address>'
grep -c '^LIBLI_VAPID_' .env.production   # must print 3
grep -x "LIBLI_VAPID_SUBJECT=mailto:<contact address>" .env.production \
  && docker compose -f docker-compose.prod.yml --env-file .env.production up -d --force-recreate app
```

Never `docker compose restart` (it keeps the old environment); recreating shows the usual ~24 s
maintenance page.

Smoke test: on a phone, log in with "Remember me" ticked, turn on Settings → Notifications →
"Push notifications on this device"; have a teacher account grade one of that account's quiz
submissions. The push arrives; tapping it opens the results page; the bell shows it read.

Rules:
- Keys are **per box** — never copy them between schools.
- Never rotate a key in use: every existing subscription silently stops working and users must
  turn push on again.
- A hung push service slows the requests that send notifications (quiz submit, grading,
  enrolment) by up to ~15–20 s per request.

To turn push off, blank the three values and recreate the same way:

```bash
sed -i 's/^LIBLI_VAPID_\(PUBLIC_KEY\|PRIVATE_KEY\|SUBJECT\)=.*/LIBLI_VAPID_\1=/' .env.production
grep '^LIBLI_VAPID_' .env.production   # three lines, all ending in =
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --force-recreate app
```
````

In `### Rolling back across a migration: restore in place`, append the line:

```markdown
The VAPID push keys come back with `.env.production`, not with the database: restore that file
too, or every device's push subscription stops working.
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_push_runbook.py tests/test_pwa_runbook.py` → PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/deployment.md tests/test_push_runbook.py
git commit -m "docs(push): runbook for turning push on per box"
```

---

## Branch gate (after Task 12)

- `uv run ruff check --no-cache .` and `uv run ruff format --check .` — clean (the untracked `find_filltable_units.py` is not branch work; exclude it).
- `uv run python manage.py makemigrations --check --dry-run` — `No changes detected`.
- Full non-e2e suite in ~4 chunks (a single full run is OOM-killed); start the test-DB container first. GREP each chunk's summary line — the exit code can lie.
- e2e: `uv run pytest -m e2e notifications/tests/ tests/test_e2e_pwa.py -n 2`.
- PR body: the device checklist from spec §9 as unchecked boxes (Android Chrome, iPhone/iPad home-screen app, desktop Chrome/Edge: subscribe from settings, subscribe from the bell invite, receive each kind, tap-through marks read, per-kind push off suppresses, logout stops delivery, kill switch silences, a "Remember me"-unticked login shows the D8 line), plus which route Task 10's worker test used (CDP or the named-function fallback), and the note that this is a migration release (B2 rehearsal step 7 candidate).
````
