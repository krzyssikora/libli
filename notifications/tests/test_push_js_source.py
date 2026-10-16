"""Source guards for push.js where the e2e cannot see the property."""

from pathlib import Path

from django.conf import settings

JS = (Path(settings.BASE_DIR) / "core/static/core/js/push.js").read_text(
    encoding="utf-8"
)
PWA = (Path(settings.BASE_DIR) / "core/static/core/js/pwa.js").read_text(
    encoding="utf-8"
)


def test_never_waits_on_ready_for_the_page_state():
    # ready is allowed ONLY inside subscribe(), bounded by a timeout
    assert JS.count("serviceWorker.ready") == 1
    assert "withTimeout(navigator.serviceWorker.ready" in JS


def test_pwa_publishes_its_registration_promise():
    assert "window.libliSwRegistration = navigator.serviceWorker" in PWA


def test_builds_no_user_facing_text():
    # the one dynamic string comes from data-msg-error
    assert "textContent = msg" in JS
    for english in (
        "Turn on",
        "Notifications are blocked",
        "can't show",
        "Home Screen",
        "Try again",
        "Remember me",
    ):
        assert english not in JS


def test_dismiss_flag_name():
    assert '"libli:push-invite-dismissed"' in JS
