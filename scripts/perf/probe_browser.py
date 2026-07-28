"""Measure the real builder page in Chromium.

PREREQUISITES -- none of these are automatic:
  1. A dev database containing the course (default slug: mat-pp).
  2. `uv run python manage.py runserver` on 127.0.0.1:8000.
  3. A session cookie for a user who can manage that course. Mint one with:

       MINT=1 uv run python manage.py shell -c \
         "exec(open('scripts/perf/probe_browser.py').read())"

Usage:
    SESSION=<key> uv run python scripts/perf/probe_browser.py
"""

import json
import os
import sys
import time

BASE = os.environ.get("BASE", "http://127.0.0.1:8000")
SLUG = os.environ.get("SLUG", "mat-pp")
SESSION = os.environ.get("SESSION", "")


def mint_session():
    """Run INSIDE `manage.py shell`. Prints a session key for the first
    superuser."""
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.contrib.sessions.backends.db import SessionStore

    user = get_user_model().objects.filter(is_superuser=True).order_by("pk").first()
    store = SessionStore()
    store["_auth_user_id"] = str(user.pk)
    store["_auth_user_backend"] = settings.AUTHENTICATION_BACKENDS[0]
    store["_auth_user_hash"] = user.get_session_auth_hash()
    store.create()
    print("SESSION", store.session_key)


def measure():
    from playwright.sync_api import sync_playwright

    if not SESSION:
        sys.exit("set SESSION=<key> (mint one with MINT=1, see the docstring)")
    url = f"{BASE}/manage/courses/{SLUG}/build/"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        ctx.add_cookies(
            [
                {
                    "name": "sessionid",
                    "value": SESSION,
                    "domain": "127.0.0.1",
                    "path": "/",
                }
            ]
        )
        page = ctx.new_page()
        t0 = time.perf_counter()
        resp = page.goto(url, wait_until="load", timeout=180000)
        wall = time.perf_counter() - t0
        stats = page.evaluate(
            """() => {
              const nav = performance.getEntriesByType('navigation')[0] || {};
              const els = document.getElementsByTagName('*').length;
              const rows = document.querySelectorAll('.tree__row').length;
              return {elements: els, rows: rows,
                      per_row: rows ? +(els / rows).toFixed(1) : null,
                      ttfb_ms: Math.round(nav.responseStart - nav.requestStart),
                      domInteractive_ms: Math.round(nav.domInteractive),
                      transferKB: Math.round((nav.transferSize || 0) / 1024)};
            }"""
        )
        stats["http"] = resp.status
        stats["wall_s"] = round(wall, 2)
        print(json.dumps(stats, indent=2))
        browser.close()


# `manage.py shell -c "..." -- --flag` is REJECTED: BaseCommand.run_from_argv
# uses parse_args (not parse_known_args) and shell declares no positionals, so
# argparse errors with "unrecognized arguments". Use an env var, matching the
# SLUG=/OPEN= convention of the sibling probe.
if os.environ.get("MINT"):
    mint_session()
elif __name__ == "__main__":
    measure()
