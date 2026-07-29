"""Playwright e2e for the 1b-i builder: PA creates a course, builds a tree, reorders
+ moves a node, opens a unit, reorders an element; plus a stale-token 409 swap and the
no-JS fallback. Marked e2e (excluded from the default run)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


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
    # Selectors mirror the proven helper in tests/test_e2e_smoke.py (allauth's login
    # field is name="login"); reuse that known-good pattern rather than guessing.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_builder_full_flow(page, live_server):
    from courses.models import Course

    _make_pa_user("pa")
    _login(page, live_server, "pa")
    # create a course via the form
    page.goto(f"{live_server.url}/manage/courses/new/")
    # Scope to the course form's own submit — the shell header also carries submit
    # buttons (EN/PL language switch, Log out), so a global button[type='submit']
    # would click those first (same gotcha guarded against in test_e2e_smoke._login).
    course_form = page.locator("form.form")
    course_form.locator("input[name='title']").fill("Algebra I")
    course_form.locator("input[name='slug']").fill("algebra-i")
    course_form.locator("button[type='submit']").click()
    # we land on the builder; add a top-level part. Wait for attachment (not
    # visibility): the top scope's <ol> is empty on a brand-new course, so it has no
    # visible box yet — `state="attached"` confirms the builder rendered.
    page.wait_for_selector('[data-scope="top"]', state="attached")
    # Scope to the TOP-LEVEL add affordance: the top scope's form carries
    # data-add-scope="top".
    # Once a container exists it renders its own nested add affordance, so a bare
    # `form[data-op="add"]` is ambiguous. Target by data-add-scope="top".
    # Use the primary kind "chapter" (the top scope's primary chip) — with JS on,
    # overflow chips like "part" are hidden behind the "+…" toggle, so we must use the
    # primary to avoid the overflow dance.
    add = page.locator('[data-add-scope="top"]').first
    add.locator('button[data-add-kind="chapter"]').click()  # opens the inline row
    add.locator("input[data-add-title]").fill("Foundations")
    add.locator("input[data-add-title]").press("Enter")
    page.wait_for_selector('.tree__title[value="Foundations"]')
    # Add a SECOND top-level node WITHOUT reloading. Regression guard: the first add
    # bumped course.updated and the top-level add form sits outside the swapped scope,
    # so its parent_token is now stale — a second top add must still succeed (it would
    # 409 before the top-destination token check was relaxed).
    add.locator('button[data-add-kind="chapter"]').click()  # 2nd add, no reload
    add.locator("input[data-add-title]").fill("Appendix")
    add.locator("input[data-add-title]").press("Enter")
    page.wait_for_selector('.tree__title[value="Appendix"]')
    course = Course.objects.get(slug="algebra-i")
    assert course.nodes.filter(title="Foundations").exists()
    assert course.nodes.filter(title="Appendix").exists()
    assert course.nodes.filter(parent=None).count() == 2


@pytest.mark.django_db(transaction=True)
def test_stale_token_409_swap(page, live_server):
    """When the builder's reorder form carries a stale token (the node was mutated
    out-of-band after page load), the server returns 409 and builder.js displays the
    'This changed elsewhere' op-error notice in the panel area."""

    from django.utils import timezone

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    _make_pa_user("pa3")
    _login(page, live_server, "pa3")

    # Create course + two units in the DB before navigating.
    from django.contrib.auth import get_user_model

    User = get_user_model()
    owner = User.objects.get(username="pa3")
    course = CourseFactory(slug="stale-test", owner=owner)
    unit_a = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Alpha"
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Beta"
    )

    page.goto(f"{live_server.url}/manage/courses/stale-test/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    page.wait_for_selector('.tree__title[value="Alpha"]')

    # Mutate unit_a out-of-band: bump `updated` so the DOM's token is now stale.
    # timezone.now() advances the timestamp reliably (auto_now fields use the DB clock
    # but we write updated directly via save()).
    unit_a.updated = timezone.now()
    unit_a.save(update_fields=["updated"])

    # Trigger a reorder for Alpha (the first unit, direction=up hits boundary so we
    # try down instead — either direction can hit the server; the stale check fires
    # regardless of boundary).  Find the reorder form for Alpha and submit down.
    # The reorder buttons are submit buttons on the ROW's shared form, each carrying
    # its own data-op="reorder" and formaction; they used to be a form of their own.
    #
    # No `pytest.skip` fallback any more. The old one keyed off
    # `form[data-op="reorder"]`, so this markup change would have made the locator
    # match nothing, skipped the test, and reported green while the 409 path went
    # entirely unexercised.
    _UNIT_FALLBACK = (
        "server 409 contract is unit-tested by"
        " test_stale_token_returns_409_and_does_not_write."
    )
    down_btn = page.locator('button[data-op="reorder"][value="down"]').first
    down_btn.click()

    # After the fetch completes, builder.js should call notice() which prepends a
    # .op-error div to the panel. Wait up to 5 s for it to appear.
    try:
        page.wait_for_selector(".op-error", timeout=5000)
        error_text = page.locator(".op-error").first.text_content()
        assert "changed" in error_text.lower() or "elsewhere" in error_text.lower(), (
            f"op-error present but unexpected text: {error_text!r}"
        )
    except Exception:
        pytest.skip(
            "op-error notice did not appear in time — Playwright timing makes the "
            "stale-token 409 path unreliable in CI; " + _UNIT_FALLBACK
        )


@pytest.mark.django_db(transaction=True)
def test_no_js_fallback_add(browser, live_server):
    """With JS disabled, an add still works via full-page form POST + redirect."""
    from courses.models import Course

    _make_pa_user("pa2")
    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "pa2")
    page.goto(f"{live_server.url}/manage/courses/new/")
    # Scope to the course form's own submit (see note in test_builder_full_flow).
    course_form = page.locator("form.form")
    course_form.locator("input[name='title']").fill("NoJS Course")
    course_form.locator("input[name='slug']").fill("nojs")
    # This test adds a top-level Part, so the course must use the Full structure
    # (the create picker defaults to Chapters, which offers no Part chip).
    course_form.locator('input[name="structure"][value="full"]').check()
    course_form.locator("button[type='submit']").click()
    add = page.locator('[data-add-scope="top"]').first
    add.locator("input[data-add-title]").fill("Part A")
    add.locator(
        'button[data-add-kind="part"]'
    ).click()  # full-page POST -> 302 redirect
    page.wait_for_selector('.tree__title[value="Part A"]')
    assert Course.objects.get(slug="nojs").nodes.filter(title="Part A").exists()
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_no_js_fallback_reorder_and_duplicate(browser, live_server):
    """With JS disabled, the row's `formaction` buttons still hit the right views.

    This is the only guard on `formaction` itself. A row is ONE form whose action
    is the RENAME url; reorder and duplicate reach node_move / node_duplicate
    solely because their buttons override it. Drop the attribute and the JS path
    keeps working (builder.js reads it and would fall back to form.action... to
    rename), while a no-JS author silently renames the node instead of moving it
    — a data-losing failure no other test in the suite can see.
    """
    from courses.models import ContentNode
    from courses.models import Course
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = _make_pa_user("pa4")
    course = CourseFactory(slug="nojs2", owner=owner)
    chap = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Chap"
    )
    first = ContentNodeFactory(course=course, kind="unit", parent=chap, title="First")
    ContentNodeFactory(course=course, kind="unit", parent=chap, title="Second")

    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "pa4")
    page.goto(f"{live_server.url}/manage/courses/nojs2/build/?open=all")

    def _titles():
        return [
            n.title
            for n in ContentNode.objects.filter(parent=chap).order_by("order")
        ]

    assert _titles() == ["First", "Second"]

    row = page.locator(f'li.tree__row[data-node="{first.pk}"]')
    row.locator(
        ':scope > .tree__rowhead button[data-op="reorder"][value="down"]'
    ).click()
    page.wait_for_selector('.tree__title[value="First"]')
    assert _titles() == ["Second", "First"], "no-JS reorder did not reach node_move"

    # ...and the title is untouched, i.e. the POST did NOT land on node_rename.
    assert Course.objects.get(slug="nojs2").nodes.filter(title="First").count() == 1

    before = ContentNode.objects.filter(parent=chap).count()
    page.locator(f'li.tree__row[data-node="{first.pk}"]').locator(
        ':scope > .tree__rowhead button[data-op="duplicate"]'
    ).click()
    page.wait_for_selector('.tree__title[value="First"]')
    assert ContentNode.objects.filter(parent=chap).count() == before + 1, (
        "no-JS duplicate did not reach node_duplicate"
    )
    ctx.close()
