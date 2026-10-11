"""e2e for the unit print layout (spec 2026-10-11-print-layout-for-units, tests 4-10).

Print media is entered with page.emulate_media(media="print"). emulate_media keeps
the browser viewport, NOT the A4 page area, so page-width layout is covered by the
manual page.pdf() check (plan Task 6), not here. Every "hidden in print" assertion
is preceded by an attached (and where possible screen-visible) precondition, so it
cannot pass vacuously. emulate_media never fires `beforeprint`; that is deliberate
here: print.js's beforeprint handler only opens notes panels, and no assertion in
this module depends on notes.
"""

import os

import pytest
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

VIEWPORT = {"width": 1280, "height": 900}


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _student(username, course, theme="light"):
    user = make_verified_user(
        username=username, email=f"{username}@test.example.com", password=TEST_PASSWORD
    )
    user.theme = theme
    user.save(update_fields=["theme"])
    EnrollmentFactory(course=course, student=user)
    return user


def _login(page, live_server, user):
    # Scoped: base.html renders one submit button per language in the header.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(user.username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(lambda u: "/accounts/login/" not in u)


def _url(live_server, name, unit):
    path = reverse(name, kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    return f"{live_server.url}{path}"


def _inject_alerts(page):
    """Inject a flash (hidden in print) and a content alert (printed) into .app-main."""
    page.evaluate(
        """() => {
          const m = document.querySelector('.app-main');
          const p = document.createElement('p');
          p.className = 'alert alert--warning';
          p.id = 'content-alert';
          p.textContent = 'y';
          m.prepend(p);
          const d = document.createElement('div');
          d.className = 'alert alert--flash alert--info'; d.textContent = 'x';
          m.prepend(d);
        }"""
    )


def _shown(page, sel):
    loc = page.locator(sel)
    assert loc.count() >= 1, f"{sel} not attached"
    for i in range(loc.count()):
        assert loc.nth(i).is_visible(), f"{sel}[{i}] not visible"


def _hidden(page, sel):
    loc = page.locator(sel)
    assert loc.count() >= 1, f"{sel} not attached (assertion would be vacuous)"
    for i in range(loc.count()):
        assert not loc.nth(i).is_visible(), f"{sel}[{i}] still visible in print"


def _lesson(username, theme="light"):
    from courses.models import ShortTextQuestionElement
    from courses.models import TextElement

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", title="Printable"
    )
    add_element(unit, TextElement.objects.create(body="<p>Body.</p>"))
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q?"))
    return course, unit, _student(username, course, theme)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_page_frame_header_and_flash(page, live_server, theme):
    course, unit, user = _lesson(f"pf-{theme}", theme)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".lesson-unit__title")
    assert page.evaluate("document.documentElement.dataset.theme") == theme
    _inject_alerts(page)
    _shown(page, ".app-header__cluster")
    _shown(page, ".alert--flash")

    page.emulate_media(media="print")
    _hidden(page, ".app-header__cluster")
    _hidden(page, ".alert--flash")
    _shown(page, "#content-alert")
    _shown(page, ".brand")
    style = page.evaluate(
        """() => {
          const s = getComputedStyle(document.querySelector('.app-header'));
          return [s.backgroundColor, s.backgroundImage, s.borderBottomWidth];
        }"""
    )
    assert style == ["rgba(0, 0, 0, 0)", "none", "0px"], style
