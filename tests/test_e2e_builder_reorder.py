"""Playwright e2e reproducing the #9 reorder/move symptoms (spec WS1 #9a/#9b).

The backend is already correct + unit-tested, so DB state passes regardless; the #9
bugs are in the frontend swap / panel lifecycle, which only the rendered DOM reveals.
Each symptom is its own assertion so a failure pinpoints which one is real:

  (a) arrow-up does nothing  /  (d) arrow-down on a section does nothing
        -> reorder a unit (down then up) and a section (down); assert the DOM order.
  (c) can't move a lesson back / spurious 409
        -> reparent via the in-panel Move picker; assert the panel no longer holds a
           picker bearing the node's now-stale token (reusing it is what 409s today).

Marked e2e (excluded from the default run; run with -m e2e).
"""

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
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_tree(owner):
    """Chapter 1 -> [Intro lesson (unit), Section A (section) -> Core lesson, Section B
    (section)]. Two sibling sections so arrow-down on a section has somewhere to go."""
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug="reorder-test", owner=owner)
    ch1 = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Chapter 1"
    )
    intro = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch1, title="Intro lesson"
    )
    sec_a = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=ch1, title="Section A"
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=sec_a, title="Core lesson"
    )
    sec_b = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=ch1, title="Section B"
    )
    return course, ch1, intro, sec_a, sec_b


def _wait_order(page, scope_id, expected, timeout_ms=5000):
    """Poll the DOM order of direct <li> rows under [data-scope] until it equals
    `expected` (a list of pks). Raises on timeout -> the swap didn't reflect the move."""
    page.wait_for_function(
        "([sel, want]) => {"
        "  const ol = document.querySelector(sel);"
        "  if (!ol) return false;"
        "  const got = Array.from(ol.children)"
        "    .filter(li => li.classList.contains('tree__row'))"
        "    .map(li => li.getAttribute('data-node'));"
        "  return got.length === want.length && got.every((v,i) => v === want[i]);"
        "}",
        arg=[f'[data-scope="{scope_id}"]', [str(x) for x in expected]],
        timeout=timeout_ms,
    )


def _goto_builder(page, live_server):
    page.goto(f"{live_server.url}/manage/courses/reorder-test/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    page.wait_for_selector("text=Chapter 1")


@pytest.mark.django_db(transaction=True)
def test_reorder_unit_and_section(page, live_server):
    """Symptoms (a) arrow-up and (d) arrow-down-on-section: the rendered tree must
    reflect reorders of both a unit and a section."""
    pa = _make_pa_user("pa9a")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    _login(page, live_server, "pa9a")
    _goto_builder(page, live_server)

    _wait_order(page, ch1.pk, [intro.pk, sec_a.pk, sec_b.pk])  # seed order
    intro_row = page.locator(f'li.tree__row[data-node="{intro.pk}"]')
    sec_a_row = page.locator(f'li.tree__row[data-node="{sec_a.pk}"]')

    # Unit down, then up.
    intro_row.locator('form[data-op="reorder"] button[value="down"]').first.click()
    _wait_order(page, ch1.pk, [sec_a.pk, intro.pk, sec_b.pk])
    intro_row.locator('form[data-op="reorder"] button[value="up"]').first.click()
    _wait_order(page, ch1.pk, [intro.pk, sec_a.pk, sec_b.pk])

    # Section A down (swaps with sibling Section B).
    sec_a_row.locator('form[data-op="reorder"] button[value="down"]').first.click()
    _wait_order(page, ch1.pk, [intro.pk, sec_b.pk, sec_a.pk])


@pytest.mark.django_db(transaction=True)
def test_move_picker_not_left_stale_after_reparent(page, live_server):
    """Symptom (c): after a successful reparent via the in-panel Move picker, the panel
    must NOT still hold a picker bearing the moved node's now-stale token. Reusing such a
    stale picker (e.g. to move the lesson back) is exactly what 409s today."""
    pa = _make_pa_user("pa9c")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    stale_token = intro.updated.isoformat()  # the token the picker is born with
    _login(page, live_server, "pa9c")
    _goto_builder(page, live_server)

    # Open the Move picker for Intro and move it under Section A.
    page.locator(f'a[data-move="{intro.pk}"]').click()
    sel = page.locator('[data-panel] form[data-op="reparent"] select[name="new_parent"]')
    sel.wait_for(state="visible", timeout=5000)
    sel.select_option(label="Section: Section A")
    page.locator('[data-panel] form[data-op="reparent"] button[type="submit"]').click()

    # The move landed (Intro is now under Section A's scope).
    page.wait_for_function(
        "([sel, pk]) => {const ol=document.querySelector(sel); return ol && "
        "Array.from(ol.children).some(li => li.classList.contains('tree__row') "
        "&& li.getAttribute('data-node')===pk);}",
        arg=[f'[data-scope="{sec_a.pk}"]', str(intro.pk)],
        timeout=5000,
    )

    # The fix re-fetches the moved node's fresh detail panel; wait for it to settle.
    page.wait_for_selector(f'[data-panel] [data-panel-for="{intro.pk}"]', timeout=5000)

    # The panel must not retain a reparent picker carrying Intro's now-stale token.
    stale_picker = page.locator(
        f'[data-panel] form[data-op="reparent"] '
        f'input[name="node_token"][value="{stale_token}"]'
    )
    assert stale_picker.count() == 0, (
        "stale Move picker left in the panel after reparent -> reusing it 409s "
        "('can't move the lesson back')"
    )

    # User-level outcome: move Intro back to the top via a fresh picker — no spurious 409.
    page.locator(f'a[data-move="{intro.pk}"]').click()
    back = page.locator('[data-panel] form[data-op="reparent"] select[name="new_parent"]')
    back.wait_for(state="visible", timeout=5000)
    back.select_option(label="Top level")
    page.locator('[data-panel] form[data-op="reparent"] button[type="submit"]').click()
    page.wait_for_function(
        "([sel, pk]) => {const ol=document.querySelector(sel); return ol && "
        "Array.from(ol.children).some(li => li.classList.contains('tree__row') "
        "&& li.getAttribute('data-node')===pk);}",
        arg=['[data-scope="top"]', str(intro.pk)],
        timeout=5000,
    )
    from courses.models import ContentNode

    assert ContentNode.objects.get(pk=intro.pk).parent_id is None, "move-back rejected"
    notices = page.locator(".op-error")
    texts = [notices.nth(i).text_content() or "" for i in range(notices.count())]
    assert not any("changed" in t.lower() or "elsewhere" in t.lower() for t in texts), (
        f"spurious 409 notice on move-back: {texts!r}"
    )
