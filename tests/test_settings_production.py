"""Production settings wire env-driven email / HTTPS / CSRF / proxy hooks.

These load `config.settings.production` fresh under a patched environment and
assert the resolved settings, without letting the reload leak into other tests
(pytest-django runs under `config.settings.test`).
"""

import importlib
import sys


def _load_production(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # Drop any cached module so each load gets a fresh namespace — a plain
    # importlib.reload() re-runs the body in the *existing* dict, leaking
    # conditionally-set attributes (e.g. SECURE_PROXY_SSL_HEADER) between tests.
    sys.modules.pop("config.settings.production", None)
    return importlib.import_module("config.settings.production")


def test_smtp_backend_activates_when_email_host_set(monkeypatch):
    prod = _load_production(
        monkeypatch,
        {
            "DJANGO_EMAIL_HOST": "smtp.example.org",
            "DJANGO_EMAIL_PORT": "2525",
            "DJANGO_EMAIL_HOST_USER": "mailer",
            "DJANGO_EMAIL_HOST_PASSWORD": "secret",  # noqa: S106
            "DJANGO_EMAIL_USE_TLS": "false",
            "DJANGO_DEFAULT_FROM_EMAIL": "libli <hi@example.org>",
        },
    )
    assert prod.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
    assert prod.EMAIL_HOST == "smtp.example.org"
    assert prod.EMAIL_PORT == 2525
    assert prod.EMAIL_HOST_USER == "mailer"
    assert prod.EMAIL_USE_TLS is False
    assert prod.DEFAULT_FROM_EMAIL == "libli <hi@example.org>"
    assert prod.SERVER_EMAIL == "libli <hi@example.org>"


def test_console_backend_when_email_host_absent(monkeypatch):
    monkeypatch.delenv("DJANGO_EMAIL_HOST", raising=False)
    prod = _load_production(monkeypatch, {})
    # Safe default: an unconfigured deploy logs mail to the console rather than
    # silently trying SMTP-to-localhost (Django's own default) and black-holing it.
    assert prod.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"


def test_https_protocol_and_secure_cookies(monkeypatch):
    prod = _load_production(monkeypatch, {})
    assert prod.ACCOUNT_DEFAULT_HTTP_PROTOCOL == "https"
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True


def test_csrf_trusted_origins_from_env(monkeypatch):
    prod = _load_production(
        monkeypatch,
        {
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://libli.example.org,https://www.libli.example.org"
        },
    )
    assert prod.CSRF_TRUSTED_ORIGINS == [
        "https://libli.example.org",
        "https://www.libli.example.org",
    ]


def test_csrf_trusted_origins_default_empty(monkeypatch):
    monkeypatch.delenv("DJANGO_CSRF_TRUSTED_ORIGINS", raising=False)
    prod = _load_production(monkeypatch, {})
    assert prod.CSRF_TRUSTED_ORIGINS == []


def test_proxy_ssl_header_gated_on_behind_proxy(monkeypatch):
    prod = _load_production(monkeypatch, {"DJANGO_BEHIND_PROXY": "true"})
    assert prod.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_proxy_ssl_header_absent_by_default(monkeypatch):
    monkeypatch.delenv("DJANGO_BEHIND_PROXY", raising=False)
    prod = _load_production(monkeypatch, {})
    assert getattr(prod, "SECURE_PROXY_SSL_HEADER", None) is None
