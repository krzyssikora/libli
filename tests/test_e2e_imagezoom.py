"""Playwright e2e for click-to-enlarge images.

Media IS served under live_server, regardless of DEBUG: django.test.testcases.
LiveServerThread.run() (django/test/testcases.py:1755) unconditionally builds
`self.static_handler(_MediaFilesHandler(WSGIHandler()))` -- no DEBUG check anywhere in
that chain. `_MediaFilesHandler.get_base_dir()`/`get_base_url()`
(django/test/testcases.py:1716-1726) return `settings.MEDIA_ROOT`/`settings.MEDIA_URL`
at request time, so `/media/<path>` is served straight from `MEDIA_ROOT` via
django.views.static.serve, entirely bypassing this project's own config/urls.py (whose
DEBUG-gated route only matters for a real dev/prod server). This means `_isolated_media`
is not just about not polluting the developer's real media/ tree: it is *also* what
makes the fixture images resolve at all, because `_MediaFilesHandler` reads
`settings.MEDIA_ROOT` per request -- point it at tmp_path and that is what gets served.
No Playwright-level route interception is needed or present; every `naturalWidth`
assertion below is a live guard against a MEDIA_ROOT misconfiguration or a
wrongly-sized fixture, not a workaround for a serving gap that does not exist.

Focus placement via locator.focus()/blur() is sanctioned SETUP here: several cases need
a trigger focused but not activated, and a real click on an armed image opens the
overlay. The interaction under test -- the click, the keypress, the wheel -- is always
real. The one exception is the Tab-traversal cases, which must use real Tab presses
because the tab order IS what they test.

Marked e2e (excluded from the default run). Run focused and in the FOREGROUND -- a
background `-m e2e` sweep spawns runaway browsers.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

VIEWPORT = {"width": 1280, "height": 800}
BIG = (1400, 900)
MAGENTA = "#FF00FF"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists. Two independent reasons, both real:

    1. make_image_asset writes its bytes through the FileField at create() time, so an
       override applied later would drop a 1400x900 PNG into the developer's real
       media/ tree.
    2. live_server's `_MediaFilesHandler` (see the module docstring) reads
       `settings.MEDIA_ROOT` per request to decide what `/media/<path>` serves -- this
       fixture pointing it at tmp_path is what makes a freshly created fixture image
       resolve at all, not an optional convenience.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


# _student / _lesson_url / _login are defined here rather than imported from
# tests/test_e2e_gallery.py: this module needs a user OBJECT (for EnrollmentFactory),
# not a username, and every e2e module in this repo is deliberately self-contained.
# The login helper is the same scoped-form version that module uses.
def _student(username="zoomstudent"):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _login(page, live_server, user):
    # Scope to the login form. base.html renders one <button type="submit"
    # name="language"> per enabled language in the header (templates/base.html:60-67),
    # and page.click is non-strict -- an unscoped click POSTs the language switcher and
    # reloads the login page with nobody authenticated. Mirrors the proven helper at
    # tests/test_e2e_editor.py:38-47.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(user.username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _image_unit(
    course, size=BIG, color=MAGENTA, alt="A labelled diagram", name="z.png"
):
    from courses.models import ImageElement

    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename=name, size=size, color=color)
    add_element(unit, ImageElement.objects.create(media=asset, alt=alt))
    return unit


@pytest.fixture
def zoom_lesson(db, _isolated_media):
    """One lesson unit, one ImageElement, 1400x900 magenta, non-empty alt.

    _isolated_media is listed explicitly, not relied on as autouse-ordering: the asset
    is written through the FileField at create() time, and a silent mis-ordering would
    drop a 1400x900 PNG into the developer's real media/ tree.
    """
    course = CourseFactory()
    unit = _image_unit(course)
    user = _student()
    EnrollmentFactory(course=course, student=user)
    return unit, user


def _goto(page, live_server, unit, user):
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_lesson_url(live_server, unit))


def _trigger(page):
    return page.locator("[data-zoomable]").first


def _open(page, trigger):
    trigger.click()
    page.wait_for_selector("dialog.imgzoom[open]")
    # The [open] attribute is set synchronously, but the overlay <img> still has to
    # request and decode its bytes, so measuring immediately can read naturalWidth == 0
    # and a zero-area box regardless of who serves the file. Wait for the decode before
    # any geometry is taken.
    page.wait_for_function(
        "() => { const i = document.querySelector('.imgzoom__img');"
        " return i && i.complete && i.naturalWidth > 0; }"
    )
    return page.locator("dialog.imgzoom")


def _await_decoded(page, locator):
    """Wait for an <img> to actually have pixels before measuring it.

    locator.wait_for() defaults to state="visible", which only needs a non-empty box --
    and an <img> whose bytes have not arrived still gets one from its alt text, so
    naturalWidth can legitimately read 0. This race is real independent of who serves
    the bytes (see the module docstring): a fresh request always needs a round trip and
    a decode, and it applies to the inline trigger exactly as it does to the overlay
    image.
    """
    locator.wait_for()
    page.wait_for_function(
        "el => el.complete && el.naturalWidth > 0", arg=locator.element_handle()
    )


def _box(locator):
    box = locator.bounding_box()
    assert box is not None, "expected a laid-out box"
    return box


def _natural_width(locator):
    return locator.evaluate("el => el.naturalWidth")


def test_harness_serves_the_real_fixture_image(page, live_server, zoom_lesson):
    """The precondition every geometry case depends on.

    Django's live_server serves /media/ from MEDIA_ROOT on its own (see the module
    docstring), so this assertion is not a workaround for a serving gap -- it is a live
    guard against a MEDIA_ROOT misconfiguration (e.g. _isolated_media mis-ordered
    relative to asset creation) or a fixture built at the wrong size: either would
    surface here as naturalWidth != 1400 instead of silently measuring the wrong image.
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    _await_decoded(page, trigger)
    assert _natural_width(trigger) == 1400
