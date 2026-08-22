import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from courses.validators import validate_fetch_url

OK = ["upload.wikimedia.org"]


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "url,fragment",
    [
        ("", "Enter an image URL"),
        ("   \n ", "Enter an image URL"),
        ("https://upload.wikimedia.org/" + "a" * 500, "too long"),
        ("https://", "valid URL"),
        ("http://upload.wikimedia.org/x.png", "https"),
        ("https://evil.com/x.png", "allow-list"),
        # The host that DISTINGUISHES the mutant: "notupload.wikimedia.org" DOES
        # endswith("upload.wikimedia.org"), so endswith(d) accepts it while the
        # correct endswith("." + d) rejects it. MEASURED.
        ("https://notupload.wikimedia.org/x.png", "allow-list"),
        # A suffix case that both forms reject (endswith(d) is False here) -- kept
        # for coverage, but it does NOT falsify the mutant on its own.
        ("https://notupload.wikimedia.org.evil.com/x.png", "allow-list"),
    ],
)
def test_rejections(url, fragment):
    with pytest.raises(ValidationError) as exc:
        validate_fetch_url(url)
    assert fragment in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "url",
    [
        "https://upload.wikimedia.org/x.png",  # exact host
        "https://sub.upload.wikimedia.org/x.png",  # subdomain
    ],
)
def test_accepts(url):
    assert validate_fetch_url(url) == url


@override_settings(
    ALLOWED_IMAGE_FETCH_DOMAINS=["Upload.Wikimedia.ORG"], ALLOW_HTTP_IMAGE_FETCH=False
)
def test_allow_list_entry_is_case_folded():
    url = "https://upload.wikimedia.org/x.png"
    assert validate_fetch_url(url) == url


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_returns_stripped_value():
    assert validate_fetch_url("  https://upload.wikimedia.org/x.png\n") == (
        "https://upload.wikimedia.org/x.png"
    )


@override_settings(
    ALLOWED_IMAGE_FETCH_DOMAINS=["localhost"], ALLOW_HTTP_IMAGE_FETCH=True
)
def test_http_allowed_when_flag_on():
    url = "http://localhost:8000/x.png"
    assert validate_fetch_url(url) == url


def test_base_settings_default_allow_http_is_false(monkeypatch):
    """The escape hatch's default-off state is a tested property.

    Must be environment-independent, and a naive reload is NOT: base.py calls
    env.read_env() at module scope and django-environ writes with
    os.environ.setdefault, so reloading re-inserts any .env value before env.bool()
    runs -- and monkeypatch.delenv(raising=False) records nothing to undo when the
    var was absent, leaking that insertion into every later test in the process.
    So: suppress the .env read too, and restore os.environ.
    """
    import importlib
    import os

    import environ

    monkeypatch.delenv("LIBLI_ALLOW_HTTP_IMAGE_FETCH", raising=False)
    monkeypatch.setattr(environ.Env, "read_env", staticmethod(lambda *a, **k: None))
    saved = dict(os.environ)
    try:
        base = importlib.import_module("config.settings.base")
        base = importlib.reload(base)
        assert base.ALLOW_HTTP_IMAGE_FETCH is False
    finally:
        os.environ.clear()
        os.environ.update(saved)
        # Deliberately NO second reload here: it would run while read_env is still
        # monkeypatched (undo happens at teardown, after this body), leaving `base`
        # cached WITHOUT its .env values. django.conf.settings is unaffected either
        # way, so restoring os.environ is the whole job.
