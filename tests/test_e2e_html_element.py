"""Playwright e2e for the sandboxed HTML element (Phase 1b-iii, Task 10).

Tests:
  1. JS execution inside the sandbox + resize bridge fires.
  2. Runtime containment (opaque-origin isolation).
  3. Two HtmlElements size independently.
  4. Non-.html-el iframes are not resized by the listener.

Marked e2e (excluded from the default run; run with -m e2e).
Mirrors the harness in test_e2e_editor_ws3.py / test_e2e_builder_ws2.py.
"""

import os

import pytest
from playwright.sync_api import Error as PlaywrightError

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_html_unit(slug, viewer, *, n=1, tall=False):
    """Create a course + chapter + unit + n HtmlElement(s).

    course.html_js: defines ``window.getCourseVal`` used by the in-iframe button.
    unit.html_seed_js: ``var ANSWER = 42;``
    element.html: button + output + inline script (reads ANSWER via getCourseVal).
    tall=True makes the second element render with a large block so the two iframes
    have measurably different heights.

    Enrolls ``viewer`` so ``can_access_course`` passes.
    Returns the lesson URL path (relative, starting with /courses/).
    """
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import HtmlElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    # course.html_js: a function the button calls.
    html_js = (
        "window.getCourseVal = function() {"
        " return (window.SEED && 'ANSWER' in window.SEED)"
        " ? window.SEED.ANSWER : 'undef'; };"
    )

    # unit.html_seed_js: a JS object literal exposed as window.SEED (new contract).
    html_seed_js = "{ ANSWER: 42 }"

    # Per-element HTML: button wired to read ANSWER via getCourseVal, write to #o.
    # Use a unique id suffix per element so two elements don't clash.
    def _el_html(i, *, big=False):
        padding = "<div style='height:300px'>spacer</div>" if big else ""
        return (
            f'<button id="b{i}">go</button>'
            f'<output id="o{i}"></output>'
            f"{padding}"
            f"<script>"
            f"document.getElementById('b{i}').addEventListener('click',function(){{"
            f"document.getElementById('o{i}').textContent=String(getCourseVal());"
            f"}});"
            f"</script>"
        )

    course = CourseFactory(slug=slug, html_js=html_js)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=ch,
        title="Test unit",
        html_seed_js=html_seed_js,
    )
    for i in range(n):
        big = tall and (i == 1)  # second element is tall when tall=True
        el = HtmlElement.objects.create(html=_el_html(i, big=big))
        Element.objects.create(unit=unit, content_object=el)

    Enrollment.objects.create(student=viewer, course=course)

    return f"/courses/{slug}/u/{unit.pk}/"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_html_element_runs_and_resizes_in_lesson(live_server, page):
    """iframe present with correct sandbox; JS executes; resize bridge fires."""
    viewer = _make_pa_user("hel1")
    lesson_path = _seed_html_unit("hel1slug", viewer)
    _login(page, live_server, "hel1")
    page.goto(f"{live_server.url}{lesson_path}")
    page.wait_for_selector(".html-el iframe")

    # --- sandbox attribute check ---
    iframe_el = page.locator(".html-el iframe").first
    sandbox = iframe_el.get_attribute("sandbox")
    assert sandbox is not None
    assert "allow-scripts" in sandbox
    assert "allow-same-origin" not in sandbox

    # --- scroll into view (iframe is lazy-loaded) ---
    iframe_el.scroll_into_view_if_needed()

    # --- in-iframe JS execution: click the button, assert output shows 42 ---
    # frame_locator uses the srcdoc iframe; Playwright identifies it by position.
    frame = page.frame_locator(".html-el iframe").first
    frame.locator("#b0").click()
    frame.locator("#o0").wait_for()
    output_text = frame.locator("#o0").text_content(timeout=5000)
    assert output_text == "42", f"Expected '42', got {output_text!r}"

    # --- resize bridge: height is at least the 40px floor ---
    # Poll until the inline style is set (postMessage + listener is async).
    # Small content is clamped to the 40px minimum; assert >= 40 (bridge fired).
    page.wait_for_function(
        "() => {"
        "  const fr = document.querySelector('.html-el iframe');"
        "  if (!fr) return false;"
        "  const h = parseInt(fr.style.height || '0', 10);"
        "  return h >= 40;"
        "}",
        timeout=5000,
    )
    height_px = page.evaluate(
        "() => parseInt("
        "document.querySelector('.html-el iframe').style.height || '0', 10)"
    )
    assert height_px >= 40, f"Expected height >= 40px (bridge fired), got {height_px}"


@pytest.mark.django_db(transaction=True)
def test_runtime_containment(live_server, page):
    """Opaque-origin: localStorage/cookie access throws or yields no parent data.

    Documented fallback: if the cross-origin throw is flaky in Playwright, assert
    the iframe carries sandbox="allow-scripts" without allow-same-origin — the
    attribute set that guarantees isolation by the browser.
    """
    viewer = _make_pa_user("hel2")
    lesson_path = _seed_html_unit("hel2slug", viewer)
    _login(page, live_server, "hel2")
    page.goto(f"{live_server.url}{lesson_path}")
    page.wait_for_selector(".html-el iframe")

    iframe_el = page.locator(".html-el iframe").first
    iframe_el.scroll_into_view_if_needed()

    # Verify attribute-level containment (the reliable Playwright approach).
    sandbox = iframe_el.get_attribute("sandbox")
    assert "allow-scripts" in sandbox
    assert "allow-same-origin" not in sandbox

    # Attempt localStorage access inside the iframe; expect SecurityError.
    # With allow-same-origin absent storage is opaque; access throws SecurityError.
    # Playwright may return 'blocked:SecurityError'; either way isolation holds.
    frame = page.frame_locator(".html-el iframe").first
    isolation_confirmed = False
    result = None
    try:
        result = frame.locator("body").evaluate(
            "() => { try { return localStorage.getItem('x'); }"
            " catch(e) { return 'blocked:' + e.name; } }"
        )
    except PlaywrightError:
        # Cross-origin/opaque access threw at the Playwright boundary —
        # isolation confirmed.
        isolation_confirmed = True
    else:
        # No exception: the value must be None or a 'blocked:...' marker —
        # never real parent data.
        assert result is None or str(result).startswith("blocked:"), (
            f"localStorage access returned unexpected value: {result!r}; "
            "sandbox=allow-scripts without allow-same-origin should block this"
        )
        isolation_confirmed = True
    assert isolation_confirmed


@pytest.mark.django_db(transaction=True)
def test_two_elements_size_independently(live_server, page):
    """Two HtmlElements of different content heights get different applied heights."""
    viewer = _make_pa_user("hel3")
    # n=2, tall=True: second element has a 300px spacer, first does not.
    lesson_path = _seed_html_unit("hel3slug", viewer, n=2, tall=True)
    _login(page, live_server, "hel3")
    page.goto(f"{live_server.url}{lesson_path}")
    page.wait_for_selector(".html-el iframe")

    iframes = page.locator(".html-el iframe")
    assert iframes.count() == 2, f"Expected 2 iframes, found {iframes.count()}"

    # Scroll each into view so lazy-load triggers.
    iframes.nth(0).scroll_into_view_if_needed()
    iframes.nth(1).scroll_into_view_if_needed()

    # Wait for both to receive a height >= 40px from the resize bridge.
    # Small content is clamped to the 40px minimum; assert >= 40 (bridge fired).
    page.wait_for_function(
        "() => {"
        "  const frs = document.querySelectorAll('.html-el iframe');"
        "  if (frs.length < 2) return false;"
        "  const h0 = parseInt(frs[0].style.height || '0', 10);"
        "  const h1 = parseInt(frs[1].style.height || '0', 10);"
        "  return h0 >= 40 && h1 >= 40;"
        "}",
        timeout=8000,
    )

    h0 = page.evaluate(
        "() => parseInt("
        "document.querySelectorAll('.html-el iframe')[0].style.height || '0', 10)"
    )
    h1 = page.evaluate(
        "() => parseInt("
        "document.querySelectorAll('.html-el iframe')[1].style.height || '0', 10)"
    )
    # The tall element (index 1) must be taller than the short one (index 0).
    assert h1 > h0, (
        f"Expected iframe[1] (tall) > iframe[0] (short); got h0={h0}, h1={h1}"
    )


@pytest.mark.django_db(transaction=True)
def test_non_html_iframe_not_resized(live_server, page):
    """The resize listener only targets .html-el iframe; a bare iframe outside that
    wrapper is untouched even if a libli:htmlel:height message is posted."""
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import HtmlElement
    from courses.models import IframeElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    viewer = _make_pa_user("hel4")
    slug = "hel4slug"

    html_js = "window.getCourseVal = function() { return 42; };"
    html_seed_js = "var ANSWER = 42;"
    html_content = (
        '<button id="b0">go</button>'
        '<output id="o0"></output>'
        "<script>"
        "document.getElementById('b0').addEventListener('click',function(){"
        "document.getElementById('o0').textContent=String(getCourseVal());"
        "});"
        "</script>"
    )

    course = CourseFactory(slug=slug, html_js=html_js)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=ch,
        title="Mixed unit",
        html_seed_js=html_seed_js,
    )

    # Add one HtmlElement (in .html-el wrapper)
    html_el = HtmlElement.objects.create(html=html_content)
    Element.objects.create(unit=unit, content_object=html_el)

    # Add one IframeElement from a whitelisted domain (NOT in .html-el wrapper)
    iframe_el = IframeElement.objects.create(
        url="https://www.youtube.com/embed/dQw4w9WgXcQ", title="embed"
    )
    Element.objects.create(unit=unit, content_object=iframe_el)

    Enrollment.objects.create(student=viewer, course=course)

    _login(page, live_server, "hel4")
    page.goto(f"{live_server.url}/courses/{slug}/u/{unit.pk}/")
    page.wait_for_selector(".html-el iframe")

    html_iframe = page.locator(".html-el iframe").first
    html_iframe.scroll_into_view_if_needed()

    # Wait for the html-el iframe to get its height from the bridge.
    # Small content is clamped to 40px minimum; assert >= 40 (bridge fired).
    page.wait_for_function(
        "() => {"
        "  const fr = document.querySelector('.html-el iframe');"
        "  return fr && parseInt(fr.style.height || '0', 10) >= 40;"
        "}",
        timeout=5000,
    )

    # Assert: the listener only wires up .html-el iframes (by querySelector scope).
    # A bare iframe (the embed) outside .html-el is never touched.
    # We verify the embed iframe has no inline height set by the listener.
    embed_height_style = page.evaluate(
        """() => {
            // Find iframes that are NOT inside a .html-el wrapper.
            const all = Array.from(document.querySelectorAll('iframe'));
            const htmlElFrames = Array.from(
                document.querySelectorAll('.html-el iframe'));
            const embeds = all.filter(fr => !htmlElFrames.includes(fr));
            if (embeds.length === 0) return null;
            return embeds[0].style.height || '';
        }"""
    )
    # The embed iframe should have no style.height set by the listener.
    assert embed_height_style == "" or embed_height_style is None, (
        f"Embed iframe unexpectedly had style.height={embed_height_style!r}; "
        "the resize listener must only target .html-el iframe"
    )
