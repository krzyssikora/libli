"""Guards for the factual claims the shipped privacy notice makes.

Each asserts that a value the notice STATES still matches the code. Changing
any of them must fail here rather than quietly turn the notice into a lie.
"""

import re

import pytest
from django.conf import settings

from core.help import DOCS_ROOT

PRIVACY = (DOCS_ROOT / "public/privacy.md").read_text(encoding="utf-8")
PRIVACY_PL = (DOCS_ROOT / "public/privacy.pl.md").read_text(encoding="utf-8")


def test_session_cookie_age_matches_the_stated_two_weeks():
    assert settings.SESSION_COOKIE_AGE == 1209600
    assert "two weeks" in PRIVACY.lower()
    # The Polish notice states the same lifetimes and is equally falsifiable.
    assert "dwa tygodnie" in PRIVACY_PL.lower()


def test_session_cookie_is_still_persistent():
    # Setting this True makes sessionid a browser-session cookie while
    # SESSION_COOKIE_AGE stays 1209600 -- every other guard would stay green
    # while "persistent, not a session cookie" became false.
    assert not settings.SESSION_EXPIRE_AT_BROWSER_CLOSE


def test_csrf_cookie_age_matches_the_stated_year():
    assert settings.CSRF_COOKIE_AGE == 31449600


def test_theme_cookie_max_age_matches_the_stated_year():
    source = (settings.BASE_DIR / "core" / "views.py").read_text(encoding="utf-8")
    assert "31_536_000" in source


@pytest.mark.django_db
def test_no_undocumented_cookie_is_set_on_the_public_or_entrance_pages(client):
    """The notice names exactly four cookies. Anything else set on a surface a
    visitor can reach before logging in makes that list false."""
    from django.urls import reverse

    documented = {"sessionid", "csrftoken", "messages", "libli_theme"}
    for name in ("core:privacy", "core:getting_started", "account_login"):
        response = client.get(reverse(name))
        assert set(response.cookies) <= documented, (
            f"{name} set an undocumented cookie: {set(response.cookies) - documented}"
        )


def test_every_first_party_storage_key_uses_a_documented_prefix():
    """The notice claims all browser storage uses libli_, libli: or libli-.

    Scan roots are the project's own app static dirs only: a bare
    **/static/**/*.js glob sweeps .venv and Django's bundled admin JS (which
    writes "theme" and "django.admin.*") and would be red for unrelated reasons.
    """
    prefixes = ("libli_", "libli:", "libli-")
    call_re = re.compile(
        r"(?:local|session)Storage\.(?:set|get|remove)Item\(\s*([^,)]+)"
    )
    lit_re = re.compile(r'^["\']([^"\']*)')
    unresolved = []
    bad = []

    for path in settings.BASE_DIR.glob("*/static/**/*.js"):
        skip = {".venv", "site-packages", "staticfiles"}
        if any(part in skip for part in path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        for raw in call_re.findall(source):
            arg = raw.strip()
            key = None
            # Rule 1: leading string literal of a (possibly concatenated) expr.
            match = lit_re.match(arg)
            if match:
                key = match.group(1)
            else:
                # Rule 2: bare identifier -> its initialiser, then rule 1. The
                # initialiser may itself be a concatenation (outline_tree.js:7).
                init = re.search(rf"\b{re.escape(arg)}\s*=\s*(.+)", source)
                # Rule 3: same-file function call -> its return expression.
                call = re.match(r"(\w+)\s*\(", arg)
                if init and lit_re.match(init.group(1).strip()):
                    key = lit_re.match(init.group(1).strip()).group(1)
                elif call:
                    ret = re.search(
                        rf"function\s+{re.escape(call.group(1))}"
                        rf"\s*\([^)]*\)\s*\{{[^}}]*?return\s+(.+)",
                        source,
                        re.S,
                    )
                    if ret and lit_re.match(ret.group(1).strip()):
                        key = lit_re.match(ret.group(1).strip()).group(1)
            if key is None:
                unresolved.append(f"{path.name}: {arg}")  # rule 4: fail loudly
            elif not key.startswith(prefixes):
                bad.append(f"{path.name}: {key}")

    assert not unresolved, f"unresolved storage key expressions: {unresolved}"
    assert not bad, f"storage keys outside the documented prefixes: {bad}"
