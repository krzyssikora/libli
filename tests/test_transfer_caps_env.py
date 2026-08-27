"""The four transfer caps are deployment guardrails. A school's default install
must keep the shipped values; only an operator's env raises them. Both halves of
that contract are asserted here.

Both tests reload config.settings.base rather than reading django.conf.settings.
That is deliberate: base.py reads BASE_DIR/.env at import time and django-environ's
read_env copies those values into os.environ, so a developer who set the overrides
in their own .env -- exactly what docs/deployment.md tells them to do -- would
otherwise turn the defaults test red for reasons unrelated to the code.

Reloading config.settings.base does NOT disturb django.conf.settings, which is
already configured; this exercises the module's read logic in isolation.
"""

import importlib
import os
from unittest import mock

import pytest

# Every env name the reload must control. DJANGO_FILE_UPLOAD_TEMP_DIR is not a
# cap, but it is cleared alongside them so the defaults test sees a pristine
# environment rather than the developer's own .env.
CAP_ENV_NAMES = (
    "LIBLI_TRANSFER_MAX_COMPRESSED_BYTES",
    "LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES",
    "LIBLI_TRANSFER_MAX_MEDIA_ENTRIES",
    "LIBLI_TRANSFER_MAX_ELEMENTS",
    "DJANGO_FILE_UPLOAD_TEMP_DIR",
)


@pytest.fixture
def reload_base():
    """Reload config.settings.base under a controlled environment.

    Neutralises read_env so the dict passed in is the ONLY input, and restores the
    real module afterwards so later tests in the session see normal settings.
    """
    import environ

    import config.settings.base as base

    def _reload(env_overrides):
        with (
            mock.patch.object(environ.Env, "read_env", lambda *a, **k: None),
            mock.patch.dict(os.environ, env_overrides),
        ):
            for name in CAP_ENV_NAMES:
                if name not in env_overrides:
                    os.environ.pop(name, None)
            return importlib.reload(base)

    yield _reload
    importlib.reload(base)


def test_transfer_caps_default_to_the_shipped_guardrails(reload_base):
    base = reload_base({})
    assert base.TRANSFER_MAX_COMPRESSED_BYTES == 1 * 1024**3
    assert base.TRANSFER_MAX_UNCOMPRESSED_BYTES == 1536 * 1024**2
    assert base.TRANSFER_MAX_MEDIA_ENTRIES == 1000
    assert base.TRANSFER_MAX_ELEMENTS == 20000


def test_transfer_caps_are_env_overridable(reload_base):
    base = reload_base(
        {
            # 5 GiB, 6 GiB
            "LIBLI_TRANSFER_MAX_COMPRESSED_BYTES": "5368709120",
            "LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES": "6442450944",
            "LIBLI_TRANSFER_MAX_MEDIA_ENTRIES": "2000",
            "LIBLI_TRANSFER_MAX_ELEMENTS": "25000",
        }
    )
    assert base.TRANSFER_MAX_COMPRESSED_BYTES == 5368709120
    assert base.TRANSFER_MAX_UNCOMPRESSED_BYTES == 6442450944
    assert base.TRANSFER_MAX_MEDIA_ENTRIES == 2000
    assert base.TRANSFER_MAX_ELEMENTS == 25000


def test_file_upload_temp_dir_defaults_to_none(reload_base):
    """Unset, Django falls back to the system temp dir -- correct for local dev."""
    base = reload_base({})
    assert base.FILE_UPLOAD_TEMP_DIR is None


def test_file_upload_temp_dir_is_env_overridable(reload_base):
    """Setting it in compose alone would do nothing: Django reads settings from
    the settings module, never from arbitrary environment variables."""
    base = reload_base({"DJANGO_FILE_UPLOAD_TEMP_DIR": "/app/upload_tmp"})
    assert base.FILE_UPLOAD_TEMP_DIR == "/app/upload_tmp"
