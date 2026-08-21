"""Playwright e2e for the two pre-existing print defects.

Print media is entered with page.emulate_media(media="print"), which re-evaluates
CSS media queries. No JS lifecycle is involved -- this PR ships no JS.

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os
import re

import pytest

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _contrast_on_white(css_colour):
    """WCAG contrast ratio of a computed CSS colour against #FFFFFF.

    Asserting a RATIO is the point: on every mutant build below the wrong value
    is still non-white and non-transparent, so "the colour changed" or "is not
    white" would pass on the broken build.
    """
    nums = re.findall(r"[\d.]+", css_colour)
    r, g, b = (int(float(n)) for n in nums[:3])

    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    return 1.05 / (lum + 0.05)


def _dark_lesson(slug, body_html=None):
    """A published lesson unit owned by a student whose STORED THEME is dark.

    The user's stored theme is what matters, never the libli_theme cookie:
    base.html:17-26 consults the cookie only when data-theme-pref is absent, so a
    cookie-based fixture silently does nothing and every assertion below would
    measure a LIGHT page -- passing on a build with the override deleted.
    """
    from django.contrib.auth.models import Group as AuthGroup

    from courses.models import ContentNode
    from courses.models import Enrollment
    from courses.models import TextElement
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import CourseFactory
    from tests.factories import add_element
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug=slug)
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="Printable",
        published=True,
    )
    if body_html:
        add_element(unit, TextElement.objects.create(body=body_html))
    # Explicit per-slug email: User.email is unique=True and the factory default
    # is shared, so two fixtures using the default would collide.
    student = make_verified_user(
        username=f"{slug}-student", email=f"{slug}@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    student.theme = "dark"
    student.save(update_fields=["theme"])
    Enrollment.objects.create(student=student, course=course, source="manual")
    return course, unit, student


def _open_lesson(page, live_server, course, unit, student, wait_for):
    _login(page, live_server, student.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(wait_for, state="attached")
    # A mis-wired fixture must fail loudly rather than measure a light page.
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"


@pytest.mark.django_db(transaction=True)
def test_dark_theme_body_text_prints_dark(page, live_server):
    """Row 1. Correct: --text-primary #1E1C18, 17.0:1. Mutant: #F2EFE9, 1.06:1."""
    course, unit, student = _dark_lesson("e2e-print-dark", "<p>Body text on paper.</p>")
    _open_lesson(page, live_server, course, unit, student, ".el--text p")

    page.emulate_media(media="print")
    colour = page.evaluate(
        "getComputedStyle(document.querySelector('.el--text p')).color"
    )
    ratio = _contrast_on_white(colour)
    assert ratio >= 4.5, (
        f"printed body text is {colour} = {ratio:.2f}:1 on white; the tokens.css "
        "@media print override is missing or sits above the dark block"
    )


@pytest.mark.django_db(transaction=True)
def test_dark_theme_author_text_colour_prints_dark(page, live_server):
    """Row 2. Correct: --tc-red #B2372A, 6.05:1. Mutant: #EA8A82, 2.48:1.

    Measures the REAL painted element. `.tc-red { color: var(--tc-red) }`
    (courses.css:1290) is the rule that paints author-coloured text, and
    sanitize_html preserves the class (courses/tests/test_sanitize_colour.py).
    Reading the token off <html> with a synthetic probe would leave that render
    path untested.
    """
    course, unit, student = _dark_lesson(
        "e2e-print-tc", '<p>Warning: <span class="tc-red">do not divide</span>.</p>'
    )
    _open_lesson(page, live_server, course, unit, student, ".tc-red")

    page.emulate_media(media="print")
    colour = page.evaluate("getComputedStyle(document.querySelector('.tc-red')).color")
    ratio = _contrast_on_white(colour)
    assert ratio >= 4.5, (
        f"author-coloured text prints {colour} = {ratio:.2f}:1 on white; the "
        "--tc-* group is missing from the print override"
    )


@pytest.mark.django_db(transaction=True)
def test_dark_theme_callout_heading_prints_dark(page, live_server):
    """Row 3. Correct: #2563c9, 5.67:1. Mutant: #7db0f7, 2.23:1.

    `.callout__heading` carries `color: var(--callout-accent)` (courses.css:1966),
    so this reads the painted heading directly.
    """
    from courses.models import CalloutElement
    from tests.factories import add_element

    course, unit, student = _dark_lesson("e2e-print-callout")
    add_element(
        unit,
        CalloutElement.objects.create(
            kind="example", heading="Worked", body="<p>x</p>"
        ),
    )
    _open_lesson(page, live_server, course, unit, student, ".callout__heading")

    page.emulate_media(media="print")
    colour = page.evaluate(
        "getComputedStyle(document.querySelector('.callout__heading')).color"
    )
    ratio = _contrast_on_white(colour)
    assert ratio >= 4.5, (
        f"callout heading prints {colour} = {ratio:.2f}:1 on white; the courses.css "
        "--callout-accent print block is missing"
    )


def _slideshow_lesson(slug):
    """A unit with two slides: text, slide break, text.

    Uses tests.factories.seed_slideshow_unit, which already builds a unit from a
    "t"/"brk"/"q" layout -- do not hand-roll the element creation.

    The explicit publish below is belt-and-braces, not a fix: ContentNodeFactory
    already sets published=True (factories.py:104). It is the MODEL default that
    is False. Kept so the fixture states what it depends on rather than inheriting
    it silently.
    """
    from django.contrib.auth.models import Group as AuthGroup

    from courses.models import Enrollment
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import CourseFactory
    from tests.factories import make_verified_user
    from tests.factories import seed_slideshow_unit

    seed_roles()
    course = CourseFactory(slug=slug)
    unit = seed_slideshow_unit(course, layout=["t", "brk", "t"])
    unit.published = True
    unit.save(update_fields=["published"])
    student = make_verified_user(
        username=f"{slug}-student", email=f"{slug}@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")
    return course, unit, student


@pytest.mark.django_db(transaction=True)
def test_every_slide_prints_stacked_in_flow(page, live_server):
    """Row 4.

    The discriminator is GEOMETRIC, not visibility. Under the "keep only
    display:block" mutant every slide is display:block, opacity 1, visible, with a
    non-zero box -- they all occupy the IDENTICAL rect inside the stage's fixed
    height. checkVisibility() and bounding_box() presence both pass on that
    mutant; only strictly increasing y separates them.
    """
    course, unit, student = _slideshow_lesson("e2e-print-deck")

    _login(page, live_server, student.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    # The print rules target the post-enhancement DOM; entering print before the
    # deck exists leaves courses.css:355's FOUC pre-hide in charge and the test
    # would be RED on a correct build.
    page.wait_for_selector(".slideshow-deck", state="attached")

    page.emulate_media(media="print")
    ys = page.evaluate(
        """[...document.querySelectorAll('.slideshow-deck .slide')]
             .map(s => s.getBoundingClientRect().top)"""
    )
    assert len(ys) == 2, f"fixture should render 2 slides, got {len(ys)}"
    assert ys[1] > ys[0], (
        f"slides print stacked at identical y ({ys}); the deck/stage geometry reset "
        "is missing, so display:block alone leaves them absolutely positioned"
    )
    bar_visible = page.evaluate(
        """(() => { const b = document.querySelector('.slideshow-bar');
                    return b ? b.checkVisibility() : false; })()"""
    )
    assert not bar_visible, (
        "Prev/Next navigation printed; the .slideshow-bar hide is missing"
    )


@pytest.mark.django_db(transaction=True)
def test_mid_fade_slide_prints_opaque(page, live_server):
    """Row 5.

    ORDER IS LOAD-BEARING. The mid-fade state is injected on the SCREEN cascade
    and a style flush is forced, THEN print media is entered. Injecting after
    entering print means the inline 0 loses to opacity:1 !important immediately,
    the computed value never changes, no transition ever starts, and the
    `transition: none` mutant reads a solid 1 and stays GREEN.
    slideshow.js:184 (`void inn.offsetWidth; // force reflow so opacity
    transitions`) is the in-repo proof that the flush is required.
    """
    course, unit, student = _slideshow_lesson("e2e-print-fade")

    _login(page, live_server, student.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".slideshow-deck", state="attached")

    page.evaluate(
        """(() => {
             const slide = document.querySelector('.slideshow-deck .slide[hidden]');
             slide.removeAttribute('hidden');
             slide.style.opacity = '0';
             // Tag the exact node, so the read below cannot drift to a different
             // slide if the fixture ever grows one -- a non-mutated slide carries
             // no inline opacity and would read a solid 1 on BOTH mutants.
             slide.setAttribute('data-probe', '1');
             void slide.offsetWidth;          // establish 0 as the before-change style
           })()"""
    )
    page.emulate_media(media="print")
    # A transition triggered by the media switch starts at the NEXT style/animation
    # frame. Reading before that frame can legitimately return the after-change
    # value 1, which would leave the `transition: none` mutant GREEN for a timing
    # reason. Wait two frames so a started transition is observably mid-flight.
    page.evaluate(
        "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )

    opacity = page.evaluate(
        "getComputedStyle(document.querySelector('[data-probe]')).opacity"
    )
    assert float(opacity) == 1.0, (
        f"a mid-fade slide prints at opacity {opacity}; either opacity:1 !important "
        "is missing (inline style wins) or transition:none is missing (the reveal "
        "only starts a 320ms animation the snapshot samples mid-way)"
    )
