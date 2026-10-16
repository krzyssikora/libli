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
        {
            "endpoint": "https://evil.example/x",
            "keys": {"p256dh": GOOD_P256DH, "auth": GOOD_AUTH},
        },
        {
            "endpoint": FCM + "x" * 1024,
            "keys": {"p256dh": GOOD_P256DH, "auth": GOOD_AUTH},
        },
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
        # trailing newline must not slip past a $-anchored match
        {
            "endpoint": FCM,
            "keys": {"p256dh": GOOD_P256DH, "auth": GOOD_AUTH + "==" + chr(10)},
        },
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
