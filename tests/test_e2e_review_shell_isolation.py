"""The teacher quiz-review page must be unaffected by the student tree's collapse.

review_submission.html reuses the .unit-shell wrapper AND inherits
html.unit-tree-collapsed (base.html sets it on every page from one global key), so
an unscoped rule would deform it for any teacher who had ever collapsed the tree on
a student page.

This test guards exactly ONE rule family — the margin. It deliberately does not
attempt an inner-node assertion for the prose cap: this page renders none of the
twelve capped selectors (it never calls render_element), so such an assertion
could never go red. That the prose-cap selectors are correctly SCOPED is guarded by
the source assertion in tests/test_consumption_css.py instead; that they cap at the
right width is guarded behaviourally in test_e2e_uniform_block_width.py (the prose
containers and both callout shapes) and test_e2e_unit_nav.py (.lesson-unit__title,
plus the quiz chrome that now fills the column).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _shell_box(page, url):
    page.goto(url)
    assert page.evaluate("() => matchMedia('(min-width: 1040px)').matches") is True, (
        "the rule under test lives inside @media (min-width: 1040px); below it the "
        "falsification would shift nothing and this test would pass vacuously"
    )
    return page.evaluate(
        "() => { const r = document.querySelector('.unit-shell')"
        ".getBoundingClientRect();"
        "return {l: r.left, w: r.width}; }"
    )


@pytest.mark.django_db(transaction=True)
def test_review_shell_is_unmoved_by_the_student_tree_collapse(browser, live_server):
    from tests.factories import EnrollmentFactory
    from tests.factories import make_review_submission

    result = make_review_submission()
    submission = result["submission"]
    course = submission.unit.course

    # The fixture's own `reviewer` is built with UserFactory (password
    # "password123", no verified email), so it cannot log in through the allauth
    # form -- discard it. The gate is reviewable_students(), not can_review_course:
    # the submission page resolves through _resolve_submission. Its owner path
    # filters through Enrollment, which the fixture never creates, so making the
    # actor the owner WITHOUT the enrolment below 404s.
    actor = make_verified_user(
        username="e2e_review_iso",
        email="e2e_review_iso@t.example.com",
        password=TEST_PASSWORD,
    )
    course.owner = actor
    course.save(update_fields=["owner"])
    EnrollmentFactory(course=course, student=submission.student)

    url = f"{live_server.url}/manage/courses/{course.slug}/review/{submission.pk}/"

    # Baseline context: no collapse state at all.
    plain = browser.new_context(viewport={"width": 1440, "height": 900})
    page = plain.new_page()
    _login(page, live_server, "e2e_review_iso")
    baseline = _shell_box(page, url)
    plain.close()

    # Collapsed context. The class MUST be installed before first paint: base.html
    # reads localStorage pre-paint, so a page.evaluate after goto would measure a
    # page that already painted uncollapsed and pass for the wrong reason.
    # add_init_script is registered on the CONTEXT and cannot be removed, which is
    # why the baseline above needs its own context -- sized identically.
    collapsed_ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    collapsed_ctx.add_init_script(
        "localStorage.setItem('libli_unit_tree_collapsed','1')"
    )
    page = collapsed_ctx.new_page()
    _login(page, live_server, "e2e_review_iso")
    collapsed = _shell_box(page, url)
    assert page.evaluate(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    ), "the pre-paint restore did not run; this test would be vacuous"
    collapsed_ctx.close()

    assert abs(collapsed["l"] - baseline["l"]) <= 1, (
        f"the review shell moved {collapsed['l'] - baseline['l']:.1f}px when the "
        f"student tree was collapsed — a new rule is scoped to .unit-shell instead "
        f"of [data-unit-shell]"
    )
    assert abs(collapsed["w"] - baseline["w"]) <= 1, (
        f"the review shell changed width by {collapsed['w'] - baseline['w']:.1f}px"
    )
