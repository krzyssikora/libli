"""Shared helpers for the builder phone-layout tests (render + e2e).

Fixtures are NOT defined here: pytest does not discover a fixture inside a helpers
module, so every e2e module copies `_allow_sync_orm_under_playwright` itself."""

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

PHONE_MQ = "(pointer: coarse) and (max-width: 959.98px)"
_MQ_JS = f"() => matchMedia('{PHONE_MQ}').matches"

# 60 characters, no spaces: the overflow probe for the title clamp.
LONG_WORD = "Przekształceniaizometrycznepłaszczyznyiwłasnościichzłożeńxyz"
assert len(LONG_WORD) == 60


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


def _pad(text, length):
    """`text` followed by repeated filler words, cut to exactly `length` chars."""
    filler = " oraz kolejne słowa tytułu"
    while len(text) < length:
        text += filler
    text = text[: length - 1]
    return text + ("." if text.endswith(" ") else "u")


def seed_course(slug="phone-demo", long_title=False, extra_lessons=0):
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import Element
    from courses.models import TextElement

    title = "Geometria na płaszczyźnie"
    if long_title:
        title = _pad("Geometria na płaszczyźnie", 120)
    course = Course.objects.create(slug=slug, title=title)

    def node(parent, kind, title, unit_type=None):
        return ContentNode.objects.create(
            course=course, parent=parent, kind=kind, title=title, unit_type=unit_type
        )

    part = node(None, "part", "Geometria analityczna i przekształcenia")
    chapter = node(part, "chapter", "Izometrie")
    section = node(chapter, "section", "Przekształcenia")
    lesson_titles = [
        "Wprowadzenie do przekształceń płaszczyzny",
        "Izometria",
        "Czy przekształcenie jest izometrią?",
    ]
    if long_title:
        lesson_titles[0] = _pad(f"Wprowadzenie {LONG_WORD} do przekształceń", 180)
    lessons = []
    for lesson_title in lesson_titles:
        lesson = node(section, "unit", lesson_title, unit_type="lesson")
        Element.objects.create(
            unit=lesson,
            content_object=TextElement.objects.create(
                body=f"<p>Treść lekcji: {lesson_title}.</p>"
            ),
        )
        lessons.append(lesson)
    quiz = node(section, "unit", "Sprawdzian: izometrie", unit_type="quiz")
    chapter2 = node(part, "chapter", "Okręgi i proste w układzie współrzędnych")
    lesson2 = node(chapter2, "unit", "Równanie okręgu", unit_type="lesson")
    Element.objects.create(
        unit=lesson2,
        content_object=TextElement.objects.create(body="<p>Równanie okręgu.</p>"),
    )
    extra = [
        node(chapter2, "unit", f"Lekcja dodatkowa {i}", unit_type="lesson")
        for i in range(1, extra_lessons + 1)
    ]
    return {
        "course": course,
        "part": part,
        "chapter": chapter,
        "section": section,
        "lessons": lessons,
        "quiz": quiz,
        "chapter2": chapter2,
        "extra": extra,
    }


def phone_context(browser, orientation="portrait", viewport=None, **extra):
    if viewport is None:
        viewport = (
            {"width": 390, "height": 844}
            if orientation == "portrait"
            else {"width": 890, "height": 410}
        )
    return browser.new_context(
        viewport=viewport,
        has_touch=True,
        is_mobile=True,
        device_scale_factor=2,
        **extra,
    )


def assert_phone(page):
    assert page.evaluate(_MQ_JS) is True, "phone media query does not match"


def assert_desktop(page):
    assert page.evaluate(_MQ_JS) is False, "phone media query matches on desktop"


def builder_url(live_server, course):
    return f"{live_server.url}/manage/courses/{course.slug}/build/?open=all"


def cdp_swipe(page, x, y_from, y_to, steps=8):
    cdp = page.context.new_cdp_session(page)
    cdp.send(
        "Input.dispatchTouchEvent",
        {"type": "touchStart", "touchPoints": [{"x": x, "y": y_from}]},
    )
    for i in range(1, steps + 1):
        y = y_from + (y_to - y_from) * i / steps
        cdp.send(
            "Input.dispatchTouchEvent",
            {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]},
        )
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


def cdp_touch_scroll(page, x, y_from, y_to):
    cdp_swipe(page, x, y_from, y_to)
