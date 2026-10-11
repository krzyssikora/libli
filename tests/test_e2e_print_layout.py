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
    body_bg = "getComputedStyle(document.body).backgroundColor"
    # Precondition: the screen body is painted (beige / dark), so white is not default.
    assert page.evaluate(body_bg) != "rgb(255, 255, 255)"

    page.emulate_media(media="print")
    assert page.evaluate(body_bg) == "rgb(255, 255, 255)"
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


@pytest.mark.django_db(transaction=True)
def test_lesson_unit_chrome_hidden(page, live_server):
    """Spec test 4 (courses.css half)."""
    course, unit, user = _lesson("chrome-stu")
    # A required lesson has no kind chip (unit_marker -> MARKER_NONE); mark it
    # additional so the chip exists and the "kept in print" check is not vacuous.
    unit.obligatory = False
    unit.save(update_fields=["obligatory"])
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".lesson-unit__title")
    for sel in (
        ".unit-foot",
        ".unit-strip",
        ".unit-done",
        '.el--question .question__form button[type="submit"]',
    ):
        _shown(page, sel)
    assert page.locator(".unit-tree").count() >= 1

    page.emulate_media(media="print")
    for sel in (
        ".unit-foot",
        ".unit-strip",
        ".unit-done",
        '.el--question .question__form button[type="submit"]',
    ):
        _hidden(page, sel)
    tree_display = page.evaluate(
        "getComputedStyle(document.querySelector('.unit-tree')).display"
    )
    assert tree_display == "none"
    _shown(page, ".unit-crumbs")
    _shown(page, ".unit-kind-chip")
    shell_x, main_x, shell_display = page.evaluate(
        """() => {
          const shell = document.querySelector('[data-unit-shell]');
          const main = shell.querySelector(':scope > .unit-shell__main');
          return [shell.getBoundingClientRect().left,
                  main.getBoundingClientRect().left,
                  getComputedStyle(shell).display];
        }"""
    )
    assert abs(shell_x - main_x) <= 1, (shell_x, main_x)  # no tree column reserved
    assert shell_display == "block"  # covers the block-flow rule itself


@pytest.mark.django_db(transaction=True)
def test_toc_pin_hidden_in_print_when_collapsed(page, live_server):
    """Pre-existing coverage, kept for completeness (spec §3); not new-rule evidence."""
    course, unit, user = _lesson("pin-stu")
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".lesson-unit__title")
    page.evaluate("document.documentElement.classList.add('unit-tree-collapsed')")
    _shown(page, ".unit-toc-pin")
    page.emulate_media(media="print")
    _hidden(page, ".unit-toc-pin")


@pytest.mark.django_db(transaction=True)
def test_draft_banner_hidden_for_author(page, live_server):
    from courses.models import TextElement

    owner = make_verified_user(
        username="owner-pr", email="owner-pr@test.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", title="Draft", published=False
    )
    add_element(unit, TextElement.objects.create(body="<p>x</p>"))
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, owner)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".lesson-unit__title")
    _shown(page, ".draft-banner")
    page.emulate_media(media="print")
    _hidden(page, ".draft-banner")


@pytest.mark.django_db(transaction=True)
def test_open_mobile_drawer_not_printed(page, live_server):
    """Review Focus 4. The leaking rule is `.unit-drawer:not([hidden])` inside
    max-width: 640px, so the drawer must be OPENED (real Contents trigger) at a
    narrow viewport first; a freshly loaded page would pass vacuously."""
    course, unit, user = _lesson("drawer-stu")
    page.set_viewport_size({"width": 500, "height": 900})
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".lesson-unit__title")
    page.locator("[data-unit-drawer-open]").click()
    _shown(page, ".unit-drawer")
    page.emulate_media(media="print")
    _hidden(page, ".unit-drawer")


@pytest.mark.django_db(transaction=True)
def test_quiz_multi_slide_prints_every_question(page, live_server):
    """Spec test 5."""
    from tests.factories import seed_slideshow_unit

    course = CourseFactory()
    unit = seed_slideshow_unit(course, "quiz", layout=["q", "brk", "q", "brk", "q"])
    user = _student("quiz-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:quiz_unit", unit))
    page.wait_for_selector(".slideshow-bar")
    _inject_alerts(page)
    for sel in (".app-header__cluster", ".unit-foot", ".unit-strip", ".slideshow-bar"):
        _shown(page, sel)
    assert page.locator(".quiz-finish").count() >= 1

    page.emulate_media(media="print")
    for sel in (
        ".app-header__cluster",
        ".unit-foot",
        ".unit-strip",
        ".alert--flash",
        ".slideshow-bar",
        ".quiz-finish",
    ):
        _hidden(page, sel)
    for sel in (".brand", ".unit-crumbs", ".unit-kind-chip"):
        _shown(page, sel)
    tree_display = page.evaluate(
        "getComputedStyle(document.querySelector('.unit-tree')).display"
    )
    assert tree_display == "none"
    assert page.locator(".el--question").count() == 3
    _shown(page, ".el--question")


@pytest.mark.django_db(transaction=True)
def test_single_slide_quiz_finish_hidden(page, live_server):
    from tests.factories import seed_slideshow_unit

    course = CourseFactory()
    unit = seed_slideshow_unit(course, "quiz", layout=["q"])
    user = _student("quiz1-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:quiz_unit", unit))
    page.wait_for_selector(".quiz-finish")
    _shown(page, ".quiz-finish")
    page.emulate_media(media="print")
    _hidden(page, ".quiz-finish")


@pytest.mark.django_db(transaction=True)
def test_action_buttons_hidden_and_stepper_prints_all(page, live_server):
    """Spec test 10."""
    from courses.models import FillTableElement
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import StepperElement
    from courses.models import StepperStep

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", title="Stateful"
    )
    ft = FillTableElement.objects.create(
        data=FillTableElement.normalize_data(
            {
                "header_row": False,
                "header_col": False,
                "border": "grid",
                "prompt": "",
                "case_sensitive": False,
                "cells": [
                    [
                        {
                            "kind": "answer",
                            "answer": "4",
                            "halign": "left",
                            "valign": "top",
                        }
                    ]
                ],
            }
        )
    )
    add_element(unit, ft)
    md = MarkDoneElement.objects.create(prompt="Do it")
    MarkDoneItem.objects.create(element=md, content="a")
    add_element(unit, md)
    st = StepperElement.objects.create(prompt="")
    for c in ("one", "two", "three"):
        StepperStep.objects.create(stepper=st, content=c)
    add_element(unit, st)
    user = _student("act-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".stepper.is-stepping")  # proves stepper.js booted
    _shown(page, ".stepper__next")
    _shown(page, ".filltable__confirm")
    _shown(page, ".lesson-unit__reset")
    # .markdone__save is NOT asserted here: markdone.js sets it [hidden] on boot,
    # so a print check would pass vacuously. It is the no-JS fallback; only the
    # Task 4 source test covers it.
    steps = page.locator("[data-stepper-step]")
    assert steps.count() == 3
    assert [steps.nth(i).is_visible() for i in range(3)] == [True, False, False]

    page.emulate_media(media="print")
    for sel in (".filltable__confirm", ".stepper__next", ".lesson-unit__reset"):
        _hidden(page, sel)
    _shown(page, "[data-stepper-step]")


def _png(size, rgb=(90, 120, 200)):
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", size, rgb).save(buf, "PNG")
    return buf.getvalue()


MM170_PX = 170 / 25.4 * 96  # 642.5


@pytest.mark.django_db(transaction=True)
def test_break_inside_cascade(page, live_server):
    """Spec test 6: CASCADE check only; actual pagination is the Task 6 PDF check."""
    from courses.models import ImageElement
    from courses.models import ShortTextQuestionElement
    from tests.factories import make_image_asset

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename="b.png", raw=_png((400, 300)))
    add_element(unit, ImageElement.objects.create(media=asset, alt="b", size="medium"))
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q?"))
    user = _student("brk-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".el--image img")
    page.emulate_media(media="print")
    for sel in (".el--image", ".el--question"):
        value = page.evaluate(
            "s => getComputedStyle(document.querySelector(s)).breakInside", sel
        )
        assert value == "avoid", (sel, value)


@pytest.mark.django_db(transaction=True)
def test_tall_dragimage_capped_and_badges_aligned(page, live_server):
    """Spec test 8."""
    from courses.models import DragToImageQuestionElement
    from courses.models import DragZone
    from tests.factories import make_image_asset

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename="tall.png", raw=_png((600, 1600)))
    q = DragToImageQuestionElement.objects.create(media=asset, alt="Tall")
    for n, (x, y) in enumerate([(0.2, 0.2), (0.5, 0.5), (0.8, 0.8)]):
        DragZone.objects.create(
            question=q, correct_label=f"L{n}", x=x, y=y, w=0.1, h=0.1, order=n
        )
    add_element(unit, q)
    user = _student("drag-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    img = page.locator(".dragimage__img").first
    img.wait_for()
    page.wait_for_function(
        "el => el.complete && el.naturalWidth > 0", arg=img.element_handle()
    )
    assert img.bounding_box()["height"] > MM170_PX + 1, (
        "fixture too short: cap would not engage"
    )

    page.emulate_media(media="print")
    geo = page.evaluate(
        """() => {
          const stage = document.querySelector('.dragimage__stage');
          const img = stage.querySelector('.dragimage__img').getBoundingClientRect();
          const st = stage.getBoundingClientRect();
          const badges = [...stage.querySelectorAll('.dragimage__badge')].map(b => {
            const r = b.getBoundingClientRect();
            return {cx: r.left + r.width / 2, cy: r.top + r.height / 2,
                    x: parseFloat(b.dataset.x), y: parseFloat(b.dataset.y)};
          });
          return {
            img: [img.left, img.top, img.width, img.height],
            stageW: st.width,
            badges,
          };
        }"""
    )
    left, top, w, h = geo["img"]
    assert h <= MM170_PX + 0.5, h
    assert abs(geo["stageW"] - w) <= 1, (geo["stageW"], w)
    assert len(geo["badges"]) == 3
    for b in geo["badges"]:
        assert abs(b["cx"] - (left + b["x"] * w)) <= 2, b
        assert abs(b["cy"] - (top + b["y"] * h)) <= 2, b


@pytest.mark.django_db(transaction=True)
def test_js_gallery_prints_every_image(page, live_server):
    """Spec test 9."""
    from courses.models import GalleryElement
    from tests.factories import make_image_asset

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    assets = [
        make_image_asset(
            course, filename=f"g{n}.png", raw=_png((400, 300), (40 * n, 120, 200))
        )
        for n in range(3)
    ]
    add_element(
        unit,
        GalleryElement.objects.create(
            data={
                "images": [{"media": a.pk, "desc": ""} for a in assets],
                "desc_pos": "below",
            }
        ),
    )
    user = _student("gal-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".el--gallery.gallery--js")
    _shown(page, ".el--gallery .gallery__bar")

    page.emulate_media(media="print")
    _hidden(page, ".el--gallery .gallery__bar")
    boxes = page.evaluate(
        """() => [...document.querySelectorAll('.gallery__item')].map(it => {
          const r = it.getBoundingClientRect(); const img = it.querySelector('img');
          const ir = img.getBoundingClientRect();
          return {top: r.top, bottom: r.bottom, imgW: ir.width, imgH: ir.height,
                  opacity: getComputedStyle(it).opacity};
        })"""
    )
    assert len(boxes) == 3
    for b in boxes:
        assert b["imgW"] > 0 and b["imgH"] > 0 and b["opacity"] == "1", b
    for a, b in zip(boxes, boxes[1:], strict=False):
        assert a["bottom"] <= b["top"] + 0.5, (a, b)  # stacked, not overlapping


@pytest.mark.django_db(transaction=True)
def test_quiz_results_chrome_and_row_break(page, live_server):
    """Spec test 5, results half.

    Every QuestionElement subclass sets SUPPORTS_REVEAL = True, so today every
    results row wraps a rendered .el--question; the "non-reveal row" branch of
    quiz_results.html is unreachable (the spec's drag-to-image claim was wrong and
    is corrected in Step 0). The rule is on .quiz-results__item itself, so the
    row's own computed break-inside is what is asserted."""
    from courses.models import QuizSubmission
    from courses.models import ShortTextQuestionElement

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", title="Done"
    )
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q?"))
    user = _student("res-stu", course)
    QuizSubmission.objects.create(
        student=user, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:quiz_results", unit))
    page.wait_for_selector(".quiz-results")
    _shown(page, ".unit-strip")
    _shown(page, ".quiz-results > .btn")
    assert page.locator(".quiz-results__item").count() >= 1

    page.emulate_media(media="print")
    _hidden(page, ".unit-strip")
    _hidden(page, ".quiz-results > .btn")
    row_break = page.evaluate(
        "getComputedStyle(document.querySelector('.quiz-results__item')).breakInside"
    )
    assert row_break == "avoid"


@pytest.mark.django_db(transaction=True)
def test_focus_ring_and_deck_fill_do_not_print(page, live_server):
    """slideshow.js focuses the active .slide on load; its ring must not print.
    The quiz's .slideshow-deck card is painted on screen and must be unpainted."""
    from tests.factories import seed_slideshow_unit

    course = CourseFactory()
    unit = seed_slideshow_unit(course, "quiz", layout=["q", "brk", "q"])
    user = _student("focus-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:quiz_unit", unit))
    page.wait_for_selector(".slideshow-bar")
    ring = (
        "() => { const s = document.querySelector('.slide.is-active');"
        " return [document.activeElement === s, getComputedStyle(s).outlineStyle]; }"
    )
    deck_bg = (
        "getComputedStyle(document.querySelector('.slideshow-deck')).backgroundColor"
    )
    focused, outline = page.evaluate(ring)
    assert focused, "slideshow.js did not focus the active slide"
    assert outline != "none", outline
    assert page.evaluate(deck_bg) != "rgba(0, 0, 0, 0)"

    page.emulate_media(media="print")
    focused, outline = page.evaluate(ring)
    assert focused
    assert outline == "none", outline
    assert page.evaluate(deck_bg) == "rgba(0, 0, 0, 0)"
