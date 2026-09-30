"""e2e: the PWA worker.

Spec: docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md

Marked e2e (excluded by default). Run focused and in the FOREGROUND:
    uv run python -m pytest tests/test_e2e_pwa.py -m e2e
Every wait is on a condition, never a sleep. Mechanisms for going offline and for
observing the export download come from tests/pwa_e2e.py -- read its Findings.

The same-origin half of rule 0 is deliberately unguarded: no controlled page loads
a cross-origin subresource in the e2e fixtures.
"""

import os
import uuid

import pytest
from django.urls import reverse
from playwright.sync_api import Error as PlaywrightError

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset
from tests.factories import make_verified_user
from tests.pwa_e2e import enable_pwa
from tests.pwa_e2e import export_observer
from tests.pwa_e2e import outage
from tests.pwa_e2e import wait_controlled

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OFFLINE_TEXT = "You're offline"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _pwa(settings, tmp_path):
    enable_pwa(settings)
    settings.MEDIA_ROOT = str(tmp_path)  # live_server serves /media/ from here


def _login(page, live_server, user):
    # Scoped to the login form: the header's language switcher is also a submit.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(user.username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_selector("form[action*='login']", state="detached")


def _wait_until(page, predicate, arg=None, timeout=5000):
    """Poll an ASYNC predicate in the page until it is truthy; fail on timeout.

    Not page.wait_for_function: it does not await a returned Promise, and a
    Promise is truthy, so an async predicate there passes at once whatever it
    would have resolved to (measured: `async () => false` returns immediately).
    """
    ok = page.evaluate(
        f"""async ([arg, timeout]) => {{
            const predicate = {predicate};
            const deadline = Date.now() + timeout;
            for (;;) {{
                if (await predicate(arg)) return true;
                if (Date.now() > deadline) return false;
                await new Promise((resolve) => setTimeout(resolve, 50));
            }}
        }}""",
        [arg, timeout],
    )
    assert ok is True, f"timed out after {timeout} ms waiting for: {predicate}"


def _poll_cache_has(page, cache_name, url, timeout=5000):
    # caches.match with cacheName, never caches.open: open() CREATES a missing
    # cache, and the probe itself would then leave the cache it is looking for.
    _wait_until(
        page,
        """async ([name, url]) =>
            !!(await caches.match(url, { cacheName: name }))""",
        [cache_name, url],
        timeout,
    )


def _warm_static(page, version):
    """Wait until every /static/ resource the current page loaded is in the
    static cache -- including tokens.css's @font-face woff2 files and any
    CSS-referenced image, which no element selector finds. Without it, a miss on
    the NEXT navigation puts after a new (or kill) worker's activate deleted the
    old cache and recreates it, and a poll on caches.keys() times out."""
    urls = page.evaluate(
        "() => performance.getEntriesByType('resource').map(e => e.name)"
        ".filter(u => new URL(u).pathname.startsWith('/static/'))"
    )
    assert urls, "non-vacuity: the page loaded no /static/ file"
    # The browser fetches icons ITSELF (<link rel=icon>, apple-touch-icon, the
    # manifest's icons for the installability check): those requests go through
    # the worker but never appear in the page's Resource Timing. Fetch each once
    # through the controlled page so it is cached, then wait for it like the rest.
    icons = page.evaluate(
        """async () => {
            const links = [...document.querySelectorAll(
                'link[rel~="icon"], link[rel="apple-touch-icon"]')].map(l => l.href);
            const manifest = document.querySelector('link[rel="manifest"]');
            const data = manifest ? await (await fetch(manifest.href)).json() : {};
            const fromManifest = (data.icons || [])
                .map(i => new URL(i.src, location.href).href);
            const all = [...links, ...fromManifest]
                .filter(u => new URL(u).pathname.startsWith('/static/'));
            await Promise.all(all.map(u => fetch(u)));
            return all;
        }"""
    )
    for url in [*urls, *icons]:
        _poll_cache_has(page, f"libli-static-{version}", url)


def test_static_is_really_cached(page, live_server):
    from core.pwa import worker_version

    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    page.reload()
    ui_js = page.evaluate(
        "() => document.querySelector('script[src*=\"core/js/ui.js\"]').src"
    )
    _poll_cache_has(page, f"libli-static-{worker_version()}", ui_js)


def test_offline_then_back_online_without_a_click(page, live_server, context):
    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    with outage(context, page, fires_online=True):
        page.goto(f"{live_server.url}/getting-started/")
        page.get_by_text(OFFLINE_TEXT).wait_for()
    # the page's own `online` listener reloads it -- no click. Wait for the REAL
    # page's content: the URL is /getting-started/ even while the offline page shows.
    page.get_by_role("heading", name="Getting started", level=1).wait_for()


def test_offline_then_try_again(page, live_server, context):
    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    with outage(context, page, fires_online=False):
        page.goto(f"{live_server.url}/getting-started/")
        page.get_by_text(OFFLINE_TEXT).wait_for()
    page.get_by_role("button", name="Try again").click()
    page.get_by_role("heading", name="Getting started", level=1).wait_for()


def test_real_errors_and_posts_pass_through(page, live_server):
    from core.pwa import worker_version

    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    # A real 404 is shown as itself, not as the offline page.
    resp = page.goto(f"{live_server.url}/no-such-page-{uuid.uuid4().hex}/")
    assert resp.status == 404
    assert OFFLINE_TEXT not in page.content()
    # A failed static fetch is not stored.
    missing = f"{live_server.url}/static/core/nonexistent-{uuid.uuid4().hex}.css"
    status = page.evaluate("async (u) => (await fetch(u)).status", missing)
    assert status == 404
    # Positive control, fetched AFTER the missing file: once IT is cached, the
    # worker has had the same chance to (wrongly) store the 404. It must be a file
    # neither /privacy/ nor the web manifest requests (pwa.js, ui.js or a manifest
    # icon could already be cached, and the poll would return before the 404's put
    # could land): doc-page.css is loaded only by the staff help pages.
    control = f"{live_server.url}/static/core/css/doc-page.css"
    page.evaluate("async (u) => { await fetch(u); }", control)
    _poll_cache_has(page, f"libli-static-{worker_version()}", control)
    has = page.evaluate(
        """async ([name, url]) => !!(await caches.match(url, { cacheName: name }))""",
        [f"libli-static-{worker_version()}", missing],
    )
    assert has is False
    # A POST (the header language switcher) is not served by the worker.
    page.goto(f"{live_server.url}/privacy/")
    with page.expect_response(lambda r: r.request.method == "POST") as posted:
        page.locator("button[name='language']").first.click()
    assert posted.value.from_service_worker is False


def test_anonymous_login_page_is_quiet_and_suppresses_the_banner(page, live_server):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(f"{live_server.url}/accounts/login/")
    wait_controlled(page)
    prevented = page.evaluate(
        """() => {
            const e = new Event("beforeinstallprompt", { cancelable: true });
            e.prompt = () => Promise.resolve({ outcome: "accepted" });
            e.userChoice = Promise.resolve({ outcome: "accepted" });
            window.dispatchEvent(e);
            return e.defaultPrevented;
        }"""
    )
    assert prevented is True
    assert errors == []


@pytest.fixture
def image_lesson(transactional_db):
    from courses.models import ImageElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename="pwa-probe.png")
    add_element(
        unit, ImageElement.objects.create(media=asset, alt="probe", size="full")
    )
    user = make_verified_user(
        username="pwa-student", email="pwa-student@probe.example.com"
    )
    EnrollmentFactory(course=course, student=user)
    return unit, user, asset


def test_media_is_never_intercepted(page, live_server, context, image_lesson):
    unit, user, asset = image_lesson
    _login(page, live_server, user)
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    seen = []
    page.on("response", lambda r: seen.append(r) if "/media/" in r.url else None)
    page.goto(f"{live_server.url}{url}")
    wait_controlled(page)
    seen.clear()  # only CONTROLLED loads count toward the non-emptiness checks
    page.reload()
    page.wait_for_function(
        "() => [...document.images].some(i => i.src.includes('/media/') && i.complete)"
    )
    sub = [r for r in seen if r.request.resource_type == "image"]
    page.goto(f"{live_server.url}{asset.file.url}")
    nav = [r for r in seen if r.request.resource_type == "document"]
    assert sub, "no /media/ subresource observed"
    assert nav, "no /media/ navigation observed"
    assert all(r.from_service_worker is False for r in sub + nav)
    # Export half: the archive download (a pathname ending /export/, carrying
    # ?confirm=1) must reach the network untouched. A fresh cookie jar and the
    # same page: context.new_page() would share the student's session, and allauth
    # would redirect away from the login form.
    course = make_course_with_unit(
        owner=make_verified_user(
            username="pwa-owner", email="pwa-owner@probe.example.com"
        )
    )[0]
    exports = export_observer(context)
    context.clear_cookies()
    _login(page, live_server, course.owner)
    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    export_url = reverse("courses:manage_course_export", kwargs={"slug": course.slug})
    with page.expect_download() as download:
        try:
            page.goto(f"{live_server.url}{export_url}?confirm=1")
        except PlaywrightError as exc:  # a download navigation never commits
            if "Download is starting" not in str(exc):
                raise
    download.value.path()  # let the stream finish before teardown truncates
    assert len(exports) == 1, exports
    assert exports[0].served_by_worker is False


def test_rename_reaches_the_next_navigation(page, live_server):
    from core.pwa import worker_version
    from institution.models import Institution

    inst = Institution.load()
    inst.name = "Before School"
    inst.save()
    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    page.goto(f"{live_server.url}/privacy/")  # visited while controlled, pre-rename
    # Every /static/ file this page loads must be cached BEFORE the rename, or the
    # old worker's late puts on the next navigation can recreate the old static
    # cache after the new worker's activate deleted it (the poll below then times
    # out). Same warm-up as the kill-switch test.
    _warm_static(page, worker_version())
    inst.name = "After School"
    inst.save()  # post_save clears the in-process site-config cache
    new = worker_version()
    page.goto(f"{live_server.url}/privacy/")  # the FIRST post-rename navigation
    assert "After School" in page.title()  # read from THIS document, no reload
    _wait_until(
        page,
        """async (v) => {
            const keys = await caches.keys();
            const ours = keys.filter(k => k.startsWith("libli-"));
            return ours.includes("libli-offline-" + v)
                && ours.every(k => k.endsWith(v));
        }""",
        new,
    )


def test_kill_switch_recalls_the_worker(page, live_server, settings):
    from core.pwa import worker_version

    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    # Warm the static cache for THIS page first, and navigate back to the same page
    # after flipping the switch: its static files are then cache hits, which touch
    # no cache, so the old worker has no miss-path put that could land after the
    # kill worker's delete and recreate an orphan (the poll below would time out).
    page.reload()
    _warm_static(page, worker_version())
    settings.PWA_KILL_SWITCH = True
    page.goto(f"{live_server.url}/privacy/")
    _wait_until(
        page,
        """async () => {
            const regs = await navigator.serviceWorker.getRegistrations();
            const keys = (await caches.keys()).filter(k => k.startsWith("libli-"));
            return regs.length === 0 && keys.length === 0;
        }""",
    )


def _open_account_menu(page):
    page.locator("[data-account-menu] [data-menu-trigger]").click()
    page.get_by_role("link", name="Settings").wait_for(state="visible")


# Chromium may fire a REAL beforeinstallprompt (the page is installable); it
# would replace the fake as the kept event. This init script, registered before
# pwa.js, swallows every such event not flagged as the test's own.
SWALLOW_REAL_PROMPTS = """window.addEventListener("beforeinstallprompt", (e) => {
    if (!e.__fake) e.stopImmediatePropagation();
}, true);"""

FAKE_PROMPT = """() => {
    window.__promptCalls = 0;
    const e = new Event("beforeinstallprompt", { cancelable: true });
    e.__fake = true;
    e.prompt = () => {
        window.__promptCalls += 1;
        return Promise.resolve({ outcome: "accepted" });
    };
    e.userChoice = Promise.resolve({ outcome: "accepted" });
    window.dispatchEvent(e);
}"""


@pytest.fixture
def member(transactional_db):
    return make_verified_user(
        username="pwa-member", email="pwa-member@probe.example.com"
    )


def test_install_item_prompt_is_single_use(page, live_server, member):
    page.add_init_script(SWALLOW_REAL_PROMPTS)
    _login(page, live_server, member)
    page.goto(f"{live_server.url}/home/")
    item = page.locator("[data-install-app]")
    page.evaluate(FAKE_PROMPT)
    assert item.get_attribute("data-install-mode") == "prompt"
    _open_account_menu(page)
    item.click()
    assert page.evaluate("() => window.__promptCalls") == 1
    assert "/home/" in page.url
    if not item.is_visible():  # re-opening an open menu would toggle it shut
        _open_account_menu(page)
    with page.expect_navigation():
        item.click()
    assert page.url.endswith("/install-app/")


def test_appinstalled_hides_the_item(page, live_server, member):
    _login(page, live_server, member)
    page.goto(f"{live_server.url}/home/")
    _open_account_menu(page)
    page.evaluate("() => window.dispatchEvent(new Event('appinstalled'))")
    assert page.locator("[data-install-app]").is_hidden()


def test_standalone_hides_the_item_on_load(page, live_server, member):
    page.add_init_script(
        """(() => {
            const real = window.matchMedia.bind(window);
            const standalone = {
                matches: true,
                media: "(display-mode: standalone)",
                addEventListener() {},
                removeEventListener() {},
            };
            window.matchMedia = (q) =>
                q.includes("display-mode: standalone") ? standalone : real(q);
        })();"""
    )
    _login(page, live_server, member)
    page.goto(f"{live_server.url}/home/")
    _open_account_menu(page)
    assert page.locator("[data-install-app]").is_hidden()
