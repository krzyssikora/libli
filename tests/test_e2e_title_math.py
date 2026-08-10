"""Playwright e2e for LaTeX-in-titles: the asset gate, measured in a real browser.

Marked e2e (excluded from the default run; run with -m e2e). Follows
tests/test_e2e_unit_nav.py's harness: _allow_async_unsafe, _login, and the
explicit `@pytest.mark.django_db(transaction=True)` + `browser.new_context()`
idiom rather than the bare `page` fixture -- the marker is what that file uses,
and owning the context is what makes the viewport controllable (this file does
not need a custom viewport today, but diverging from the house idiom for two
tests buys nothing and costs the next reader a double-take).
"""

import os
import time

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import EnrollmentFactory
from tests.factories import make_verified_user
from tests.helpers_title_math import make_large_title_course
from tests.helpers_title_math import make_title_course

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    """Log in via the allauth HTML form. Copied verbatim from
    tests/test_e2e_unit_nav.py:40-46 -- no `.first`, no networkidle wait; the
    subsequent page.goto is the synchronisation point."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_next_unit_title_typesets_in_the_nav_button(browser, live_server):
    """The ONLY maths in the entire course is in the NEXT unit's title. The
    template is correct either way; what fails without the widened gate is that
    the page ships no KaTeX at all -- which is exactly why this cannot be a
    template-level assertion."""
    course, unit_a, _nodes = make_title_course(maths_on="unitB")
    student = make_verified_user(
        username="e2estudent",
        email="e2estudent@t.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(student=student, course=course)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2estudent")
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit_a.pk}/")
        katex = page.locator(".unit-foot__navtitle .katex")
        katex.first.wait_for(state="attached", timeout=5000)
        assert katex.count() >= 1
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_math_js_pre_filter_runs_end_to_end(browser, live_server, capsys):
    """Coverage for the pre-filter branch itself
    (courses/static/courses/js/math.js:33-34): both perf tests below
    deliberately ABORT math.js and reimplement its loop inside page.evaluate
    WITHOUT the pre-filter, to get a controlled, interference-free timing of
    the raw per-call cost -- which means the pre-filter's early return is
    never executed by either of them. This test lets math.js run UNMODIFIED
    (no route interception) and times typesetting end-to-end, so the new
    branch actually runs under test. Deliberately the SMALL fixture, not the
    large one -- this is a coverage check, not a perf measurement, and needs
    to stay fast."""
    course, unit_a, _nodes = make_title_course(maths_on="far")
    student = make_verified_user(
        username="e2eprefilter",
        email="e2eprefilter@t.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(student=student, course=course)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2eprefilter")
        t0 = time.perf_counter()
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit_a.pk}/")
        katex = page.locator("[data-math-title] .katex")
        katex.first.wait_for(state="attached", timeout=5000)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        katex_count = katex.count()
    finally:
        ctx.close()
    with capsys.disabled():
        print(
            f"\n[pre-filter e2e] math.js (unmodified) typeset "
            f"{katex_count} .katex node(s) in {elapsed_ms:.1f} ms "
            f"(page load + asset fetch + typesetting, wall clock)"
        )
    assert katex_count >= 1, "math.js never typeset the far-off maths title"


@pytest.mark.django_db(transaction=True)
def test_render_inline_text_main_thread_cost_is_recorded(browser, live_server, capsys):
    """RENDER COST, MEASURED not predicted. renderInlineText calls
    renderMathInElement ONCE PER MATCHED ELEMENT, and a unit page holds the whole
    course outline TWICE (the rail plus the drawer copy at _unit_shell.html:40),
    with every group title marked as well as every unit row.

    MEASURE THE FIRST PASS, NOT A SECOND ONE. math.js is deferred but runs before
    this test's evaluate(), and it replaces the delimiters with KaTeX markup whose
    <annotation> text carries none -- so timing a re-run over the live DOM times a
    walk of a DELIMITER-FREE tree and reports a near-zero number on a fast AND on
    a pathologically slow build. The route below aborts math.js so KaTeX and
    auto-render still load (window.renderMathInElement exists) while the document
    pass never happens, leaving the markup pristine for one real, timed pass.

    Take the element count FROM THE PAGE, never derive it. If the measured time
    exceeds ~50 ms, switch renderInlineText to a single renderMathInElement over a
    common ancestor -- and note that the single-root alternative over document.body
    is NOT the default, because it would typeset every delimiter on the page
    including the edit buffers Path C must keep untouched."""
    course, unit_a, _nodes = make_title_course(maths_on="far")
    student = make_verified_user(
        username="e2eperf", email="e2eperf@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2eperf")
        page.route("**/courses/js/math.js", lambda route: route.abort())
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit_a.pk}/")
        page.wait_for_function("() => typeof window.renderMathInElement === 'function'")
        stats = page.evaluate(
            """() => {
                const els = document.querySelectorAll('[data-math-title]');
                let withMaths = 0;
                els.forEach(el => {
                    if (/\\\\[([]/.test(el.textContent)) withMaths++;
                });
                const t0 = performance.now();
                els.forEach(el => window.renderMathInElement(el, {
                    delimiters: [
                        { left: '\\\\(', right: '\\\\)', display: false },
                        { left: '\\\\[', right: '\\\\]', display: true },
                    ],
                    throwOnError: false,
                }));
                const ms = performance.now() - t0;
                return { count: els.length, withMaths: withMaths, ms: ms,
                         rendered: document.querySelectorAll('.katex').length };
            }"""
        )
    finally:
        ctx.close()
    with capsys.disabled():
        print(
            f"\n[render cost] {stats['count']} marked elements "
            f"({stats['withMaths']} carrying delimiters), first renderInlineText "
            f"pass: {stats['ms']:.1f} ms, produced {stats['rendered']} .katex nodes"
        )
    assert stats["count"] > 0, "no [data-math-title] elements on the page"
    # The pass must have done REAL work -- otherwise the number above is a walk of
    # an already-typeset tree and the whole measurement is vacuous.
    assert stats["withMaths"] > 0, "math.js not blocked; DOM already typeset"
    assert stats["rendered"] > 0, "the timed pass produced no KaTeX output"


@pytest.mark.django_db(transaction=True)
def test_render_inline_text_main_thread_cost_is_recorded_at_scale(
    browser, live_server, capsys
):
    """Same measurement as test_render_inline_text_main_thread_cost_is_recorded,
    but at the scale of this repo's real matematyka course (21 parts / 793
    units, rendered twice per page -- rail plus drawer). The small-course
    reading is only ever a screening number; this is the one judged against the
    50 ms threshold."""
    course, unit_a = make_large_title_course()
    student = make_verified_user(
        username="e2eperfscale",
        email="e2eperfscale@t.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(student=student, course=course)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        _login(page, live_server, "e2eperfscale")
        page.route("**/courses/js/math.js", lambda route: route.abort())
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit_a.pk}/")
        page.wait_for_function("() => typeof window.renderMathInElement === 'function'")
        stats = page.evaluate(
            """() => {
                const els = document.querySelectorAll('[data-math-title]');
                let withMaths = 0;
                els.forEach(el => {
                    if (/\\\\[([]/.test(el.textContent)) withMaths++;
                });
                const t0 = performance.now();
                els.forEach(el => window.renderMathInElement(el, {
                    delimiters: [
                        { left: '\\\\(', right: '\\\\)', display: false },
                        { left: '\\\\[', right: '\\\\]', display: true },
                    ],
                    throwOnError: false,
                }));
                const ms = performance.now() - t0;
                return { count: els.length, withMaths: withMaths, ms: ms,
                         rendered: document.querySelectorAll('.katex').length };
            }"""
        )
    finally:
        ctx.close()
    with capsys.disabled():
        print(
            f"\n[render cost, at scale] {stats['count']} marked elements "
            f"({stats['withMaths']} carrying delimiters), first renderInlineText "
            f"pass: {stats['ms']:.1f} ms, produced {stats['rendered']} .katex nodes"
        )
    assert stats["count"] > 0, "no [data-math-title] elements on the page"
    # The pass must have done REAL work -- otherwise the number above is a walk of
    # an already-typeset tree and the whole measurement is vacuous.
    assert stats["withMaths"] > 0, "math.js not blocked; DOM already typeset"
    assert stats["rendered"] > 0, "the timed pass produced no KaTeX output"
