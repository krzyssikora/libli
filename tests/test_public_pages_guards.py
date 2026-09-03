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
    # Both notices state the lifetime, so both must be falsifiable here. Without
    # these, an edit to the Polish "Około roku" is unguarded while the same edit
    # to "two weeks" is caught by the session guard above.
    assert "about a year" in PRIVACY.lower()
    assert "około roku" in PRIVACY_PL.lower()


def test_theme_cookie_max_age_matches_the_stated_year():
    """The libli_theme lifetime is hardcoded in TWO places that must agree with
    the notice's "One year": the server-side cookie set in core/views.py (the
    logged-in settings toggle) and the client-side cookie write in
    core/static/core/js/ui.js (the pre-login theme toggle, loaded by
    templates/base.html and templates/allauth/layouts/entrance.html -- it runs
    on /privacy/, /getting-started/ and /accounts/login/). Either one drifting
    from 31536000 makes "One year" false on some surface, so both are checked.
    """
    views_source = (settings.BASE_DIR / "core" / "views.py").read_text(encoding="utf-8")
    assert "31_536_000" in views_source

    ui_js_source = (
        settings.BASE_DIR / "core" / "static" / "core" / "js" / "ui.js"
    ).read_text(encoding="utf-8")
    assert "Max-Age=31536000" in ui_js_source

    # The notice text, in both languages. Matched as whole table cells: a bare
    # "rok" substring is already inside the csrftoken row's "Około roku", so it
    # would stay green after the libli_theme cell was edited.
    assert "| One year |" in PRIVACY
    assert "| Rok |" in PRIVACY_PL


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
    The single leading "*/static/**/*.js" segment is what excludes those
    vendor roots today (measured: 0 matches from `skip` below). `skip` is
    belt-and-braces for a future looser glob, not the thing doing the
    exclusion now -- keep it, but do not credit it with today's result.
    """
    prefixes = ("libli_", "libli:", "libli-")
    call_re = re.compile(
        r"(?:local|session)Storage\.(?:set|get|remove)Item\(\s*([^,)]+)"
    )
    lit_re = re.compile(r'^["\']([^"\']*)')
    unresolved = []
    bad = []

    for path in settings.BASE_DIR.glob("*/static/**/*.js"):
        # Belt-and-braces only: the glob shape above already excludes .venv,
        # site-packages and staticfiles today (measured: this never matches).
        # Keep it in case the glob is ever loosened to sweep vendor trees.
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


BACKUP_SH = (DOCS_ROOT.parent / "backup.sh").read_text(encoding="utf-8")


def _backup_constant(name):
    match = re.search(rf"^{name}=(\d+)$", BACKUP_SH, re.MULTILINE)
    assert match, f"backup.sh no longer defines {name}"
    return int(match.group(1))


def test_backup_retention_matches_the_stated_periods():
    """Publishing a retention claim whose real value lives in a shell script is
    exactly the drift this file exists to prevent -- and this one is a legal
    statement in two languages, not a UI string.

    Mutant: change a constant in backup.sh without updating both notices.
    """
    daily = _backup_constant("RETAIN_DAILY_DAYS")
    monthly = _backup_constant("RETAIN_MONTHLY_MONTHS")
    prune = _backup_constant("MIRROR_PRUNE_DAYS")
    # Pinned so a deliberate policy change stays visible in the diff instead
    # of silently propagating from backup.sh.
    assert daily == 30
    assert monthly == 12
    assert prune == 90

    # Derived from the constants, not from literals: this is what couples the
    # shell script to the notice. A bare `"30" in notice` is satisfied by any
    # stray 30 in the document and would not move when the constant moves.
    assert f"**{daily} days**" in PRIVACY
    assert f"**{monthly} months**" in PRIVACY
    assert f"**{prune} days**" in PRIVACY
    assert f"**{daily} dni**" in PRIVACY_PL
    assert f"**{monthly} miesięcy**" in PRIVACY_PL
    assert f"**{prune} dni**" in PRIVACY_PL

    # The 13-month total is a human-readable consequence, not a constant.
    assert "13 months" in PRIVACY
    assert "13 miesięcy" in PRIVACY_PL
