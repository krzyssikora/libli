"""Guards for the maintenance page Caddy serves while the app container restarts.

Same rationale and shape as test_deploy_wiring.py: the Caddyfile and the page it
serves are consumed by a reverse proxy on a production host, never by this suite,
so a mistake in them surfaces only as a user staring at Chrome's "This page isn't
working" -- the exact failure this page exists to remove. Worse, the page is only
ever rendered while the app is DOWN, which is precisely when nothing else can
check it: a broken maintenance page looks perfect in every environment where you
would think to look at it.

MEASURED, 2026-09-08, deploy of #312 (run 34226974153): `libli-app-1 Recreate`
12:36:57.9 -> `Healthy` 12:37:22.3 = 24 s during which Caddy answered 502 with no
upstream. Caddy itself stays up throughout -- that is what makes serving a page
from here possible at all.

Each assertion names the mutant that makes it fail. An assertion that cannot go
red is not a guard.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CADDYFILE = ROOT / "Caddyfile"
COMPOSE = ROOT / "docker-compose.prod.yml"
PAGE = ROOT / "maintenance.html"

COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _handle_errors_block():
    """The body of the Caddyfile's `handle_errors` directive, comments stripped.

    A window, not the whole file: several assertions below would pass vacuously
    against a match anywhere in the Caddyfile. `status 503`, for instance, means
    something entirely different sitting in the media handler.
    """
    lines = CADDYFILE.read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, ln in enumerate(lines) if ln.lstrip().startswith("handle_errors")
    )
    depth = 0
    body = []
    for i, line in enumerate(lines[start:], start=start):
        depth += line.count("{") - line.count("}")
        if i > start:
            body.append(line)
        if depth <= 0 and i > start:
            break
    return [ln for ln in body if not ln.lstrip().startswith("#")]


def _handle_errors_codes():
    """The status codes the `handle_errors` directive is scoped to."""
    text = CADDYFILE.read_text(encoding="utf-8")
    line = next(
        ln for ln in text.splitlines() if ln.lstrip().startswith("handle_errors")
    )
    return set(re.findall(r"[0-9]{3}", line))


def test_caddy_answers_every_dead_upstream_status():
    """A dead upstream is a 502 today, but Caddy emits 503 when a configured
    upstream is unavailable and 504 when one accepts and then stalls -- a slow
    migration in the entrypoint reaches the second. Scoping the handler to 502
    alone leaves two doors open onto Chrome's error page, and both appear only
    under load or under a slow deploy, never in a test.

    Mutant: narrow `handle_errors` to `502` -> a stalled app during deploy still
    shows the browser error.
    """
    assert {"502", "503", "504"} <= _handle_errors_codes(), _handle_errors_codes()


def test_a_real_500_is_not_dressed_up_as_maintenance():
    """VERIFIED behaviourally against caddy:2-alpine v2.11.4 before this landed:
    `handle_errors` fires only on errors CADDY generates, so a 500 returned by a
    healthy Django passes straight through, body intact. The guard is against
    someone later "improving" the handler to cover 500 as well.

    That would be the worst possible bug in this feature: every unhandled
    exception in production would render as "we're updating, back in a moment",
    the site would look healthy while it was broken, and nothing anywhere would
    go red. The 24-second window this page exists for cannot produce a 500 --
    there is no app running to produce one.

    Mutant: add `500` to the handle_errors line -> real bugs become invisible.
    """
    assert "500" not in _handle_errors_codes(), _handle_errors_codes()


def test_the_outage_keeps_a_failing_status_code():
    """`file_server` answers 200 by default, and 200 is a lie that outlives the
    outage: a 200 is cacheable and indexable, so a CDN, a browser cache or a
    crawler can keep serving "the platform is updating" as the site's real
    content long after it recovered. 503 is the only status that says
    "temporary" to all three.

    Mutant: drop the `status 503` subdirective -> the outage answers 200 OK.
    """
    body = " ".join(_handle_errors_block())
    assert re.search(r"status\s+503", body), body


def test_the_page_is_not_cached():
    """Without no-store the browser may keep the maintenance page for the URL the
    user was on, so the reload that should return them to the app re-renders the
    outage from cache instead -- the page then outlasts the deploy that caused
    it, which reads to the user as a site that never came back.

    Mutant: drop the Cache-Control header -> the retry loop can never escape.
    """
    body = " ".join(_handle_errors_block())
    assert "no-store" in body, body


def test_compose_mounts_the_file_the_caddyfile_serves():
    """Two halves that must agree across two files, with no runtime error when
    they disagree: Caddy finds no file, falls back to its OWN blank 503, and the
    deploy stays green. The site simply shows an empty page during every future
    deploy and nobody learns until a user says so.

    So this derives the path from the Caddyfile rather than restating it, and
    checks compose mounts exactly that.

    Mutant: rename the page, or edit `root`/`rewrite` on one side only.
    """
    body = _handle_errors_block()
    root = next(
        ln.split("*", 1)[1].strip() for ln in body if ln.lstrip().startswith("root")
    )
    target = next(
        ln.split("*", 1)[1].strip() for ln in body if ln.lstrip().startswith("rewrite")
    )
    served = root.rstrip("/") + "/" + target.lstrip("/")

    assert PAGE.exists(), PAGE
    mount = f"./{PAGE.name}:{served}:ro"
    compose = COMPOSE.read_text(encoding="utf-8")
    assert mount in compose, (mount, [ln for ln in compose.splitlines() if "srv" in ln])


def test_the_page_reaches_for_nothing_it_cannot_have():
    """The page renders only while the app is down, and /static/ is served by
    Whitenoise INSIDE that app -- so every stylesheet, script, font or image the
    page references is guaranteed to fail at exactly the moment it is needed.
    A page that looks right in a browser during development is not evidence:
    there the app is up and the asset resolves.

    Everything must be inline. An external font or a CDN reset is the same bug
    with a slower failure -- it hangs the render until the request times out.

    Mutant: add a stylesheet link to the app's own CSS -> the page arrives
    unstyled during every deploy, and looks perfect in every test.

    HTML comments are stripped first. The page has to be able to EXPLAIN this
    constraint to whoever edits it next, and it cannot do that without naming
    the paths it must not reach for. A guard that forbids a file from
    documenting its own rule teaches the next author to delete the rationale.
    """
    html = COMMENT.sub("", PAGE.read_text(encoding="utf-8"))
    for forbidden in ("/static/", "http://", "https://", "//fonts."):
        assert forbidden not in html, forbidden
    assert not re.search(r"<(link|script|img)\b", html, re.IGNORECASE), html


def test_the_page_retries_by_itself():
    """The whole promise of the page -- "you'll be back in a moment" -- is a lie
    unless something reloads. `handle_errors` does not redirect, so the page is
    served AT the URL the user asked for; a plain reload therefore returns them
    to the exact unit they were reading, not to the site root.

    A meta refresh rather than JS: it is the one mechanism that still works with
    scripting disabled, and it needs no asset the page cannot load.

    Mutant: drop the meta refresh -> the user sits on the page until they think
    to reload, well past the 24 s the outage actually lasts.
    """
    html = PAGE.read_text(encoding="utf-8")
    refresh = re.search(
        r'http-equiv=["\']refresh["\'][^>]*content=["\']([0-9]+)', html, re.IGNORECASE
    )
    assert refresh, html
    # Long enough not to hammer a box mid-deploy, short enough that the 24 s
    # window costs the user at most a couple of retries.
    assert 3 <= int(refresh.group(1)) <= 15, refresh.group(1)


def test_the_page_speaks_both_languages():
    """LANGUAGE_CODE is "en" but the users are Polish schools, and Caddy cannot
    read the language: SessionLocaleMiddleware keeps it in the Django session,
    which is exactly what is unreachable while the app is down. Showing both is
    the only option that is never wrong for the reader in front of it.

    Mutant: drop one language -> half the audience reads an outage notice in a
    language they did not choose.

    Scoped to the BODY, and comments stripped. The first version of this guard
    searched the whole file and was INERT: `<title>` carries the Polish too, so
    deleting every Polish word the reader actually sees left it green. Found by
    running the mutant, not by reading the assertion.
    """
    html = COMMENT.sub("", PAGE.read_text(encoding="utf-8"))
    body = html.split("<body", 1)[1]
    assert "Trwa aktualizacj" in body, body
    assert "updating" in body.lower(), body
