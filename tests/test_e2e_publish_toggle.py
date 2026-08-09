import os

import pytest
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    """Every e2e module in this repo defines this (74 of them). Fixtures
    declared in a test module are module-LOCAL, so a new file inherits
    nothing -- and running this file alone would raise SynchronousOnlyOperation
    the moment the ORM is touched under the sync Playwright greenlet."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _make_pa_user(username):
    """Copied from tests/test_e2e_builder.py -- do NOT hand-roll this.

    UserFactory sets the password to "password123", not TEST_PASSWORD, and
    creates no verified email, so allauth's AccountMiddleware bounces the
    session to verify-email and the login silently never takes.
    """
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
    """allauth's field is name="login", not "username", and there is no
    `accounts:login` URL name -- the path is literal. The submit button is
    form-scoped because a bare button[type=submit] hits the shell header's
    language/logout buttons first."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def stamp(page):
    """Mark the current document so a navigation can be detected."""
    page.evaluate("() => { window.__samedoc = 1; }")


def assert_no_navigation(page):
    """Pin a test to the JS fetch path rather than a real navigation -- see
    tests/test_e2e_builder_toggle.py's copy of this helper for the full
    rationale (a plain <a href> toggle would otherwise pass with zero JS)."""
    assert page.evaluate("() => window.__samedoc === 1"), (
        "the page navigated; this test must exercise the JS fetch path"
    )


def _seed(owner, slug):
    """part > chapter > unit (lesson, published). A minimal tree; individual
    tests add their own siblings/children on top of this shape."""
    course = CourseFactory(slug=slug, owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Part"
    )
    chapter = ContentNodeFactory(
        course=course, kind="chapter", parent=part, unit_type=None, title="Chapter"
    )
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        published=True,
        title="Unit",
    )
    return course, part, chapter, unit


def test_e2e1_unit_toggle_applies_strike_through_without_reload(page, live_server):
    owner = _make_pa_user("pa1")
    course, part, chapter, unit = _seed(owner, "e2e1")
    _login(page, live_server, "pa1")
    url = reverse("courses:manage_builder", kwargs={"slug": "e2e1"})
    page.goto(f"{live_server.url}{url}?open={part.pk},{chapter.pk}")

    row = page.locator(f'li.tree__row[data-node="{unit.pk}"]')
    assert "tree__row--draft" not in (row.get_attribute("class") or "")

    stamp(page)  # detect a navigation
    page.click(
        f'li.tree__row[data-node="{unit.pk}"] > .tree__rowhead '
        'button[data-op="flag"][data-flag="published"]'
    )
    page.wait_for_selector(f'li.tree__row.tree__row--draft[data-node="{unit.pk}"]')
    assert_no_navigation(page)  # must be the fetch path, not a navigation

    unit.refresh_from_db()
    assert unit.published is False


def test_e2e2_container_confirm_updates_descendants_and_preserves_state(
    page, live_server
):
    owner = _make_pa_user("pa2")
    course = CourseFactory(slug="e2e2", owner=owner)
    # Filler top-level parts, so the tree has real scroll height -- otherwise
    # a "scroll position survives" assertion is vacuously true on a page that
    # never scrolls in the first place.
    for i in range(40):
        ContentNodeFactory(
            course=course, kind="part", parent=None, unit_type=None, title=f"Filler {i}"
        )
    part_a = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Part A"
    )
    chapter_a = ContentNodeFactory(
        course=course, kind="chapter", parent=part_a, unit_type=None, title="Chapter A"
    )
    u1 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter_a,
        published=False,
        title="U1",
    )
    u2 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter_a,
        published=False,
        title="U2",
    )
    # A second, separately-opened branch: its expansion must survive the
    # `top`-scope swap that confirming chapter_a's write triggers.
    chapter_b = ContentNodeFactory(
        course=course, kind="chapter", parent=part_a, unit_type=None, title="Chapter B"
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter_b,
        published=True,
        title="U3",
    )

    _login(page, live_server, "pa2")
    url = reverse("courses:manage_builder", kwargs={"slug": "e2e2"})
    page.goto(f"{live_server.url}{url}?open={part_a.pk},{chapter_a.pk},{chapter_b.pk}")

    page.locator(
        f'li.tree__row[data-node="{chapter_a.pk}"]'
    ).scroll_into_view_if_needed()
    before_y = page.evaluate("() => window.scrollY")

    stamp(page)  # detect a navigation across the whole open+confirm sequence
    page.click(
        f'li.tree__row[data-node="{chapter_a.pk}"] > .tree__rowhead '
        'a[data-flag-confirm][data-flag="published"]'
    )
    strip = page.locator(f'[data-flag-strip="{chapter_a.pk}"]')
    strip.wait_for(state="visible")
    strip.locator('button[name="value"][value="1"]').click()

    page.wait_for_selector(f'li.tree__row[data-node="{u1.pk}"]:not(.tree__row--draft)')
    page.wait_for_selector(f'li.tree__row[data-node="{u2.pk}"]:not(.tree__row--draft)')
    assert_no_navigation(page)  # both the GET-strip and the POST stayed fetch
    # Every descendant row updated -- not just the container's own glyph.
    u1.refresh_from_db()
    u2.refresh_from_db()
    assert u1.published is True
    assert u2.published is True

    # A sibling branch's expansion state survives the top-scope swap.
    assert page.locator(f'ol[data-scope="{chapter_b.pk}"]').count() == 1

    after_y = page.evaluate("() => window.scrollY")
    assert abs(after_y - before_y) < 2  # scroll position survives


def test_e2e3_draft_unit_outline_visibility_and_author_open(page, live_server, browser):
    """E2E3.

    The "carrying the draft banner when opened" half of the original scope is
    DEFERRED to Task 15: its Step 3 item 2 ("student-facing render, viewed by
    an author -- text-only, no sprite glyph") owns both the banner and the
    `is_author` render-context flag its `{% if %}` needs, neither of which
    exists yet. Building it here would duplicate Task 15's work outside this
    task's file list. This test proves only what Task 14 can: the draft is
    absent from the student's rendered outline, present in the author's
    (asserted as CONTAINMENT, not merely a 200 -- opening the unit directly
    would pass even on a build where the outline itself dropped it, which is
    exactly OUT10's mutant at the view level), and the author's open of it
    succeeds.
    """
    owner = _make_pa_user("pa3")
    course = CourseFactory(slug="e2e3", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Part"
    )
    published = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        published=True,
        title="Published Unit",
    )
    draft = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        published=False,
        title="Draft Unit",
    )
    student = make_verified_user(
        username="student3", email="student3@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)

    outline_url = reverse("courses:course_outline", kwargs={"slug": "e2e3"})

    _login(page, live_server, "student3")
    page.goto(f"{live_server.url}{outline_url}")
    assert page.locator(f'[data-unit="{published.pk}"]').count() == 1
    assert page.locator(f'[data-unit="{draft.pk}"]').count() == 0

    author_ctx = browser.new_context()
    try:
        author_page = author_ctx.new_page()
        _login(author_page, live_server, "pa3")
        author_page.goto(f"{live_server.url}{outline_url}")
        assert author_page.locator(f'[data-unit="{draft.pk}"]').count() == 1

        author_page.click(f'[data-unit="{draft.pk}"] a.outline-unit')
        author_page.wait_for_url(f"**/u/{draft.pk}/")
        assert author_page.title().startswith("Draft Unit")
    finally:
        author_ctx.close()


def test_e2e4_focus_after_write_targets_the_right_control(page, live_server):
    """E2E4. Three cases: a plain unit toggle, a confirmed container write,
    and a confirmed quiz UNPUBLISH -- the third renders a plain button, not
    the confirming anchor a two-case test would look for (a drafted quiz
    needs no confirmation to be re-published)."""
    owner = _make_pa_user("pa4")
    course = CourseFactory(slug="e2e4", owner=owner)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        published=True,
        title="Solo unit",
    )
    container = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Container"
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=container,
        published=False,
        title="C1",
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=container,
        published=False,
        title="C2",
    )
    quiz = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        published=True,
        title="Quiz",
    )
    QuizSubmissionFactory(unit=quiz)

    _login(page, live_server, "pa4")
    url = reverse("courses:manage_builder", kwargs={"slug": "e2e4"})
    page.goto(f"{live_server.url}{url}")
    stamp(page)  # detect a navigation across all three cases below

    # Case 1: a plain unit toggle -> focus lands on the SAME (re-rendered)
    # button.
    page.click(
        f'li.tree__row[data-node="{unit.pk}"] > .tree__rowhead '
        'button[data-op="flag"][data-flag="published"]'
    )
    page.wait_for_selector(f'li.tree__row.tree__row--draft[data-node="{unit.pk}"]')
    assert_no_navigation(page)
    assert page.evaluate(
        f"""() => document.activeElement === document.querySelector(
            'li.tree__row[data-node="{unit.pk}"] > .tree__rowhead '
            + '[data-op="flag"][data-flag="published"]')"""
    )

    # Case 2: a confirmed CONTAINER write -> focus lands on the confirming
    # anchor.
    page.click(
        f'li.tree__row[data-node="{container.pk}"] > .tree__rowhead '
        'a[data-flag-confirm][data-flag="published"]'
    )
    strip = page.locator(f'[data-flag-strip="{container.pk}"]')
    strip.wait_for(state="visible")
    strip.locator('button[name="value"][value="1"]').click()
    page.wait_for_function(
        f"""() => {{
            const a = document.querySelector(
                'li.tree__row[data-node="{container.pk}"] > .tree__rowhead '
                + '[data-flag-confirm][data-flag="published"]');
            return !!a && document.activeElement === a;
        }}"""
    )
    assert_no_navigation(page)

    # Case 3: a confirmed quiz UNPUBLISH -> the row now renders a PLAIN
    # BUTTON, not an anchor. Mutant: focus [data-flag-confirm] unconditionally
    # -> the selector misses here and focus falls to <body>.
    page.click(
        f'li.tree__row[data-node="{quiz.pk}"] > .tree__rowhead '
        'a[data-flag-confirm][data-flag="published"]'
    )
    strip2 = page.locator(f'[data-flag-strip="{quiz.pk}"]')
    strip2.wait_for(state="visible")
    strip2.locator('button[name="value"][value="0"]').click()
    page.wait_for_selector(
        f'li.tree__row[data-node="{quiz.pk}"] > .tree__rowhead a[data-flag-confirm]',
        state="detached",
    )
    assert page.evaluate(
        f"""() => document.activeElement === document.querySelector(
            'li.tree__row[data-node="{quiz.pk}"] > .tree__rowhead '
            + '[data-op="flag"][data-flag="published"]')"""
    )
    assert_no_navigation(page)


def test_e2e5_collapsed_container_toggle_updates_its_own_and_ancestor_glyphs(
    page, live_server
):
    """E2E5. `chapter` stays COLLAPSED throughout -- the case every narrower
    fragment choice (e.g. re-rendering only the acted-on row) silently
    no-ops on, since applying the full `top` scope is what re-derives the
    ancestor's fold too."""
    owner = _make_pa_user("pa5")
    course = CourseFactory(slug="e2e5", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Part"
    )
    chapter = ContentNodeFactory(
        course=course, kind="chapter", parent=part, unit_type=None, title="Chapter"
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        published=False,
        title="U1",
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        published=False,
        title="U2",
    )

    _login(page, live_server, "pa5")
    url = reverse("courses:manage_builder", kwargs={"slug": "e2e5"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")  # chapter itself NOT opened

    assert page.locator(f'ol[data-scope="{chapter.pk}"]').count() == 0  # collapsed

    chapter_icon = page.locator(
        f'li.tree__row[data-node="{chapter.pk}"] > .tree__rowhead '
        'a[data-flag-confirm][data-flag="published"]'
    )
    part_icon = page.locator(
        f'li.tree__row[data-node="{part.pk}"] > .tree__rowhead '
        'a[data-flag-confirm][data-flag="published"]'
    )
    assert "icm--draft" in chapter_icon.get_attribute("class")
    assert "icm--draft" in part_icon.get_attribute("class")  # the ANCESTOR's fold

    stamp(page)  # detect a navigation across the whole open+confirm sequence
    chapter_icon.click()
    strip = page.locator(f'[data-flag-strip="{chapter.pk}"]')
    strip.wait_for(state="visible")
    strip.locator('button[name="value"][value="1"]').click()

    page.wait_for_function(
        f"""() => {{
            const a = document.querySelector(
                'li.tree__row[data-node="{chapter.pk}"] > .tree__rowhead '
                + '[data-flag-confirm][data-flag="published"]');
            return !!a && a.classList.contains('icm--live');
        }}"""
    )
    assert_no_navigation(page)
    assert "icm--live" in part_icon.get_attribute("class")  # ancestor updated too
    # STILL collapsed:
    assert page.locator(f'ol[data-scope="{chapter.pk}"]').count() == 0


def test_e2e6_a_racing_post_returns_a_strip_and_the_button_recovers(page, live_server):
    """E2E6. Full cycle: click -> strip opens -> dismiss -> click again
    succeeds.

    The race: the page renders while the quiz has zero submissions (a plain
    unit-toggle button, per TREE7's "drafted+submissions -> button" /
    "no submissions -> button" cases -- here it's the latter). A submission
    then lands via another session, simulated here with a direct ORM write,
    while this page's DOM still shows the stale plain button. Clicking it
    POSTs with no `confirmed` param; the server now finds needs_confirmation
    True and returns the strip instead of writing.

    Mutant A: route the response straight to applyFragment -> dead click (the
    strip never opens). Mutant B: clear `disabled` inside applyFragment,
    which the strip branch never reaches -> the button stays disabled
    forever, and a test that stops at "strip opens" is green on it -- hence
    the explicit re-click + expect_response below.
    """
    owner = _make_pa_user("pa6")
    course = CourseFactory(slug="e2e6", owner=owner)
    quiz = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        published=True,
        title="Quiz",
    )

    _login(page, live_server, "pa6")
    url = reverse("courses:manage_builder", kwargs={"slug": "e2e6"})
    page.goto(f"{live_server.url}{url}")

    btn = page.locator(
        f'li.tree__row[data-node="{quiz.pk}"] > .tree__rowhead '
        'button[data-op="flag"][data-flag="published"]'
    )
    assert btn.count() == 1  # plain button: no submissions at render time

    QuizSubmissionFactory(unit=quiz)  # the race: a submission lands elsewhere

    stamp(page)  # a full-page form-submit POSTs the same URL, so expect_response
    # alone would not distinguish it from the fetch path
    with page.expect_response(
        lambda r: "/build/node/flag/" in r.url and r.request.method == "POST"
    ):
        btn.click()  # hides a published, now-submitted quiz -- needs confirming
    strip = page.locator(f'[data-flag-strip="{quiz.pk}"]')
    strip.wait_for(state="visible")
    assert_no_navigation(page)
    assert btn.is_disabled() is False  # cleared even though the write never landed

    strip.focus()  # focusInto() already put it here; pin it for the Esc below
    page.keyboard.press("Escape")
    strip.wait_for(state="detached")

    # Click again: must actually fire a fetch, not sit dead behind a stale
    # `disabled` (Mutant B).
    with page.expect_response(
        lambda r: "/build/node/flag/" in r.url and r.request.method == "POST"
    ):
        btn.click()
    strip.wait_for(state="visible")
    assert_no_navigation(page)

    quiz.refresh_from_db()
    assert quiz.published is True  # never actually confirmed, so never written
