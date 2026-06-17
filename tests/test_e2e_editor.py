"""Playwright e2e for the 1b-ii editor｜preview flow: a PA opens a unit's editor,
adds a text element and a math element (KaTeX renders in the swapped-in preview —
this validates the Task 8/9 root-render fix), reorders + deletes elements, hits a
stale-token 409 (the 'this changed' notice + a refresh that preserves the out-of-band
element, i.e. no clobber), and the no-JS full-page POST save path.

Marked e2e (excluded from the default run; run with `-m e2e`)."""

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
    # Mirror the proven helper in test_e2e_builder/test_e2e_smoke (allauth's login
    # field is name="login"); scope to the login form so the shell header's submit
    # buttons (language switch, Log out) aren't clicked instead.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_course_and_unit(username, slug="editor-test", unit_title="Lesson One"):
    """Seed a PA-owned course + one lesson unit via the ORM, returning the unit."""
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    User = get_user_model()
    owner = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title=unit_title,
    )
    return unit


def _editor_url(live_server, unit):
    return (
        f"{live_server.url}/manage/courses/{unit.course.slug}"
        f"/build/unit/{unit.pk}/edit/"
    )


def _add_element(page, add_type):
    """Click a '+ Type' add button and wait for the host form to swap in (the per-type
    editor partial mounts inside .editor-form-host)."""
    page.locator(f"[data-add-type='{add_type}']").click()
    page.wait_for_selector(".editor-form-host form[data-op='element-save']")


@pytest.mark.django_db(transaction=True)
def test_add_text_element(page, live_server):
    """+ Text -> type into the RTE source -> Save -> the preview shows the text."""
    _make_pa_user("ed_text")
    _login(page, live_server, "ed_text")
    unit = _seed_course_and_unit("ed_text", slug="ed-text")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')

    _add_element(page, "text")
    # JS-on: text_toolbar mounts a contenteditable .rte-surface and hides the textarea;
    # type into the surface (input event syncs it back to [data-rte-source] on submit).
    surface = page.locator(".editor-form-host .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("Hello from the editor")

    page.locator(".editor-form-host button[type='submit']").click()

    preview = page.locator('[data-scope="preview"]')
    preview.get_by_text("Hello from the editor").wait_for()
    assert "Hello from the editor" in preview.inner_text()


@pytest.mark.django_db(transaction=True)
def test_add_math_element_renders_katex(page, live_server):
    """+ Math -> enter LaTeX -> Save -> the swapped-in preview contains a .katex node
    (proves KaTeX ran on the freshly swapped preview — the Task 8/9 root-render fix)."""
    _make_pa_user("ed_math")
    _login(page, live_server, "ed_math")
    unit = _seed_course_and_unit("ed_math", slug="ed-math")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')

    _add_element(page, "math")
    page.locator(".editor-form-host [data-math-input]").fill("a^2+b^2=c^2")
    page.locator(".editor-form-host button[type='submit']").click()

    # The preview is swapped wholesale; editor.js calls window.libliRenderMath on it,
    # which must produce a KaTeX-rendered node.
    page.wait_for_selector('[data-scope="preview"] .katex')
    assert page.locator('[data-scope="preview"] .katex').count() >= 1


@pytest.mark.django_db(transaction=True)
def test_reorder_elements(page, live_server):
    """With two elements present, moving one changes the preview order."""
    from courses.models import TextElement
    from tests.factories import add_element

    _make_pa_user("ed_order")
    _login(page, live_server, "ed_order")
    unit = _seed_course_and_unit("ed_order", slug="ed-order")
    add_element(unit, TextElement.objects.create(body="<p>First</p>"))
    add_element(unit, TextElement.objects.create(body="<p>Second</p>"))

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="preview"]')

    def preview_order():
        text = page.locator('[data-scope="preview"]').inner_text()
        return text.index("First"), text.index("Second")

    first_pos, second_pos = preview_order()
    assert first_pos < second_pos  # initial order: First before Second

    # Move the FIRST row down (its ↓ button). After the fragment swap the order flips.
    page.locator(".el-row").first.locator(
        "button[name='direction'][value='down']"
    ).click()

    # Wait for the preview to reflect the new order (Second now before First).
    page.wait_for_function(
        """() => {
            const t = document.querySelector('[data-scope=\"preview\"]').innerText;
            return t.indexOf('Second') < t.indexOf('First');
        }"""
    )
    first_pos, second_pos = preview_order()
    assert second_pos < first_pos


@pytest.mark.django_db(transaction=True)
def test_delete_element(page, live_server):
    """Deleting an element removes it from the preview."""
    from courses.models import TextElement
    from tests.factories import add_element

    _make_pa_user("ed_del")
    _login(page, live_server, "ed_del")
    unit = _seed_course_and_unit("ed_del", slug="ed-del")
    add_element(unit, TextElement.objects.create(body="<p>Keep me</p>"))
    add_element(unit, TextElement.objects.create(body="<p>Delete me</p>"))

    page.goto(_editor_url(live_server, unit))
    preview = page.locator('[data-scope="preview"]')
    preview.get_by_text("Delete me").wait_for()

    # Delete the second row (the one carrying "Delete me").
    rows = page.locator(".el-row")
    rows.nth(1).locator("form[data-op='element-delete'] button[type='submit']").click()

    # After the swap, "Delete me" is gone but "Keep me" remains.
    page.wait_for_function(
        """() => {
            const t = document.querySelector('[data-scope=\"preview\"]').innerText;
            return !t.includes('Delete me') && t.includes('Keep me');
        }"""
    )
    assert "Delete me" not in preview.inner_text()
    assert "Keep me" in preview.inner_text()


@pytest.mark.django_db(transaction=True)
def test_stale_token_409_no_clobber(page, live_server):
    """An out-of-band mutation bumps unit.updated, so the in-page op's token is stale.
    The op returns 409: editor.js flashes the 'this changed' notice AND swaps in the
    latest fragments — the out-of-band element is preserved (no data loss / clobber)."""
    from courses.models import TextElement
    from tests.factories import add_element

    _make_pa_user("ed_stale")
    _login(page, live_server, "ed_stale")
    unit = _seed_course_and_unit("ed_stale", slug="ed-stale")
    add_element(unit, TextElement.objects.create(body="<p>Original</p>"))

    page.goto(_editor_url(live_server, unit))
    preview = page.locator('[data-scope="preview"]')
    preview.get_by_text("Original").wait_for()

    # Out-of-band change AFTER page load: append a new element and bump unit.updated so
    # the DOM's token (embedded in the row's forms) is now stale. This simulates another
    # editor having saved concurrently.
    add_element(unit, TextElement.objects.create(body="<p>Concurrent</p>"))
    from django.utils import timezone

    unit.updated = timezone.now()
    unit.save(update_fields=["updated"])

    # Trigger an in-page op carrying the now-stale token: delete "Original".
    page.locator(".el-row").first.locator(
        "form[data-op='element-delete'] button[type='submit']"
    ).click()

    # editor.js flashes the .op-error notice on a 409.
    page.wait_for_selector(".op-error")
    notice = page.locator(".op-error").first.text_content()
    assert "changed" in notice.lower() or "elsewhere" in notice.lower(), (
        f"unexpected op-error text: {notice!r}"
    )

    # And the swapped-in fragments reflect the latest DB state WITHOUT clobbering: the
    # out-of-band "Concurrent" element is present, and "Original" survived (the stale
    # delete did NOT go through).
    page.wait_for_function(
        """() => {
            const t = document.querySelector('[data-scope=\"preview\"]').innerText;
            return t.includes('Concurrent') && t.includes('Original');
        }"""
    )
    body = preview.inner_text()
    assert "Concurrent" in body
    assert "Original" in body


@pytest.mark.django_db(transaction=True)
def test_no_js_fallback_save(browser, live_server):
    """With JS disabled, the '+ Type' button is inert (it needs JS), so a no-JS user
    saves via a full-page POST to element_save (no X-Requested-With header -> the view
    redirects back to the editor page). The reloaded editor must show the new element,
    proving the no-JS full-page POST path works."""
    from courses.models import ContentNode

    _make_pa_user("ed_nojs")
    unit = _seed_course_and_unit("ed_nojs", slug="ed-nojs")
    save_url = (
        f"{live_server.url}/manage/courses/{unit.course.slug}/build/element/save/"
    )
    editor_url = _editor_url(live_server, unit)

    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "ed_nojs")

    # Read the live token from the rendered editor page (the data-updated attribute) so
    # the POST carries a valid, current unit_token — exactly what a no-JS form submit
    # would carry from the page.
    page.goto(editor_url)
    page.wait_for_selector('[data-scope="editor"]')
    token = page.locator('[data-scope="editor"]').get_attribute("data-updated")

    # Pull the CSRF cookie/token the same way a no-JS form would (the hidden field
    # mirrors the cookie). Use the page's request context so cookies are shared.
    csrf = ctx.cookies()
    csrf_token = next((c["value"] for c in csrf if c["name"] == "csrftoken"), "")

    resp = page.request.post(
        save_url,
        form={
            "ctx": "editor",
            "type": "text",
            "element": "new",
            "unit": str(unit.pk),
            "unit_token": token,
            "body": "<p>No JS saved this</p>",
            "csrfmiddlewaretoken": csrf_token,
        },
        headers={"Referer": editor_url},
    )
    # Full-page POST path: 200 after following the 302 redirect to the editor page.
    assert resp.ok, f"no-JS save failed: {resp.status}"
    assert ContentNode.objects.get(pk=unit.pk).elements.count() == 1

    # Reload the editor page and confirm the new element renders in the preview.
    page.goto(editor_url)
    preview = page.locator('[data-scope="preview"]')
    preview.get_by_text("No JS saved this").wait_for()
    assert "No JS saved this" in preview.inner_text()
    ctx.close()
