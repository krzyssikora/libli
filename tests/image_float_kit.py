"""Shared seeding/measuring for the image Float-right e2e suites."""

import os

import pytest

from courses.models import ImageElement
from courses.models import TextElement
from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

PHONE = {"width": 367, "height": 800}
DESKTOP = {"width": 1300, "height": 900}
PARA = (
    "Flaga jest uszyta z czterech trójkątów w dwóch różnych kolorach oraz naszytego "
    "na nie koła w trzecim kolorze, jak na rysunku obok."
)

# Image <img> tags carry no width/height: EVERY geometry read must wait for decode.
WAIT_IMAGES = """async () => {
  for (let i = 0; i < 200; i++) {
    const imgs = [...document.images];
    const done = im => im.complete && im.naturalWidth > 0;
    if (imgs.length && imgs.every(done)) return true;
    await new Promise(r => setTimeout(r, 25));
  }
  return false;
}"""


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)  # live_server serves /media/ from here
    return tmp_path


def make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_load_state("load")


def seed_unit(owner, slug, unit_type="lesson"):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="U"
    )
    return course, unit


def image(
    course, *, size="small", float_right=True, px=(300, 200), alt="img", caption=""
):
    asset = make_image_asset(course, size=px, color="red")
    return ImageElement.objects.create(
        media=asset, alt=alt, size=size, float_right=float_right, figcaption=caption
    )


def text(body=PARA):
    return TextElement.objects.create(body=f"<p>{body}</p>")


def unit_url(live_server, unit):
    base = f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/"
    return base + ("quiz/" if unit.unit_type == "quiz" else "")


def editor_url(live_server, unit):
    slug = unit.course.slug
    return f"{live_server.url}/manage/courses/{slug}/build/unit/{unit.pk}/edit/"


def open_page(page, url, viewport):
    page.set_viewport_size(viewport)
    page.goto(url)
    page.wait_for_load_state("load")
    assert page.evaluate(WAIT_IMAGES), "fixture images never decoded"
    page.evaluate("() => document.fonts.ready")


def rect(page, selector):
    return page.locator(selector).first.evaluate(
        "e => e.getBoundingClientRect().toJSON()"
    )


def print_mode(page):
    """Print emulation AS A PRINT: emulate_media alone never fires `beforeprint`, and
    print.js's enter() (which opens every closed notes panel, spoiler and tab for
    paper) runs only on that event -- without it a closed panel's cards stay 0x0 and
    a print notes assertion passes or fails vacuously (precedent:
    tests/test_e2e_print_lesson_notes.py)."""
    page.emulate_media(media="print")
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")


def first_line(page, selector):
    """Box of the first rendered line of the text in `selector`."""
    return page.evaluate(
        """(sel) => { const el = document.querySelector(sel);
             const r = document.createRange(); r.selectNodeContents(el);
             return r.getClientRects()[0].toJSON(); }""",
        selector,
    )


def seed_student_lesson(slug, username, builders):
    """Published lesson + enrolled STUDENT (notes need a student; PA users suffice for
    layout only). `builders` are callables taking the course and returning a saved
    concrete element, added top-level in order.
    Returns (course, unit, joins, student)."""
    from django.contrib.auth.models import Group

    from courses.models import ContentNode
    from courses.models import Enrollment
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import CourseFactory

    seed_roles()
    course = CourseFactory(slug=slug)
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="F",
        published=True,
    )
    joins = [add_element(unit, b(course)) for b in builders]
    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    student.groups.add(Group.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")
    return course, unit, joins, student


def note(student, unit, join, body="notatka"):
    from notes.models import Note

    return Note.objects.create(author=student, unit=unit, element=join, body=body)


def open_notes(page, join):
    """Open `join`'s notes and wait until the pop is where it will stay.

    <details> fires `toggle` ASYNCHRONOUSLY: at the rail (>=1200px + notes.js) the pop
    paints at its unanchored top:0 until notes.js's positionPop stamps an inline top --
    measuring in that window passed locally and failed on CI
    (tests/test_e2e_notes_rail.py). Below the rail: wait for [open] only."""
    sel = f'.lesson-block[data-element-id="{join.pk}"]'
    page.locator(f"{sel} .block-notes__handle").click()
    page.wait_for_function(
        """(s) => { const pop = document.querySelector(s + ' .block-notes__pop');
             const rail = matchMedia('screen and (min-width: 1200px)').matches
                          && document.documentElement.classList.contains('notes-js');
             const open = document.querySelector(s + ' .block-notes__panel[open]');
             return !!pop && !!open && (!rail || pop.style.top !== ''); }""",
        arg=sel,
    )


def boxes_intersect(a, b):
    return not (
        a["right"] <= b["left"]
        or b["right"] <= a["left"]
        or a["bottom"] <= b["top"]
        or b["bottom"] <= a["top"]
    )


# KEEP THIS LAST: helpers added by later tasks go ABOVE it, or the star import
# in the e2e files silently drops them.
__all__ = [n for n in dir() if not n.startswith("__")]
