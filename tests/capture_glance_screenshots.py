"""Light + dark + forced-colors capture of the course glance bars, plus measured
contrast. Verification tool, not CI:

    uv run pytest tests/capture_glance_screenshots.py -m e2e

Dark for a logged-in user is set through User.theme (a cookie is ignored for an
authenticated user); the anonymous landing uses the libli_theme cookie.
Output: SHOT_DIR or ./.superpowers/shots/ (gitignored).
"""

import os
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings

from courses.models import Element
from courses.models import ShortTextQuestionElement
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get("SHOT_DIR", Path(settings.BASE_DIR) / ".superpowers" / "shots")
)

# Colours are normalised through a 1x1 canvas: dark --accent is a color-mix(), which
# Chromium reports as `color(srgb 0.87 0.69 0.51)` (0..1 channels), so a regex over
# the computed string would read it as near-black. The raw strings are returned too,
# so a normalisation failure is visible in the notes.
CONTRAST_JS = """
() => {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  const toRgb = css => {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = '#000';
    ctx.fillStyle = css;
    ctx.fillRect(0, 0, 1, 1);
    return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3);
  };
  const lum = ([r, g, b]) => {
    const f = c => {
      c /= 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(toRgb(a)), lum(toRgb(b))].sort((p, q) => q - p);
    return ((x + 0.05) / (y + 0.05)).toFixed(2);
  };
  const bg = el => getComputedStyle(el).backgroundColor;
  const fill = document.querySelector('.glance__fill, .glance__dot');
  const track = fill.closest('.glance__track');
  // The surface is the nearest ANCESTOR of the track with a painted background
  // (.dash-card / .dash-panel / .glance-card / body) -- never the track itself.
  let surface = track.parentElement;
  while (surface && bg(surface) === 'rgba(0, 0, 0, 0)') surface = surface.parentElement;
  return {
    raw: {fill: bg(fill), track: bg(track), surface: bg(surface)},
    measured: fill.className,
    course: (fill.closest('li, .glance-card')?.querySelector('a, .glance-card__title')
             ?.textContent || '').trim(),
    surface_el: surface.className || surface.tagName,
    fill_vs_track: ratio(bg(fill), bg(track)),
    fill_vs_surface: ratio(bg(fill), bg(surface)),
    track_vs_surface: ratio(bg(track), bg(surface)),
  };
}
"""


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(f"{live_server.url}/home/")


def _seed(student):
    """Four courses covering partial fill, zero-dot, track-only and full."""
    full = CourseFactory(title="Biology Basics")
    EnrollmentFactory(student=student, course=full)
    lesson = ContentNodeFactory(
        course=full, kind="unit", unit_type="lesson", parent=None, obligatory=True
    )
    UnitProgressFactory(student=student, unit=lesson, completed=True)
    quiz = ContentNodeFactory(course=full, kind="unit", unit_type="quiz", parent=None)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=Decimal("4")
    )
    Element.objects.create(unit=quiz, content_object=q)
    QuizSubmissionFactory(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("4"),
        max_score=Decimal("4"),
    )

    started = CourseFactory(title="Algebra Basics")
    EnrollmentFactory(student=student, course=started)
    lessons = [
        ContentNodeFactory(
            course=started,
            kind="unit",
            unit_type="lesson",
            parent=None,
            obligatory=True,
        )
        for _ in range(3)
    ]
    UnitProgressFactory(student=student, unit=lessons[0], completed=True)
    quiz = ContentNodeFactory(
        course=started, kind="unit", unit_type="quiz", parent=None
    )
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=Decimal("10")
    )
    Element.objects.create(unit=quiz, content_object=q)
    QuizSubmissionFactory(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("7"),
        max_score=Decimal("10"),
    )

    zero = CourseFactory(title="Chemistry Intro")
    EnrollmentFactory(student=student, course=zero)
    quiz = ContentNodeFactory(course=zero, kind="unit", unit_type="quiz", parent=None)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=Decimal("5")
    )
    Element.objects.create(unit=quiz, content_object=q)
    QuizSubmissionFactory(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("5"),
    )

    untouched = CourseFactory(title="History Survey")
    EnrollmentFactory(student=student, course=untouched)
    ContentNodeFactory(
        course=untouched, kind="unit", unit_type="lesson", parent=None, obligatory=True
    )


def test_capture(page, live_server):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    notes = ["# Course glance verification", ""]
    student = make_verified_user(
        username="glanceshots",
        email="glanceshots@t.example.com",
        password=TEST_PASSWORD,
    )
    _seed(student)

    for theme in ("light", "dark"):
        student.theme = theme
        student.save(update_fields=["theme"])
        _login(page, live_server, "glanceshots")
        for name, path in (("dashboard", "/home/"), ("mycourses", "/courses/")):
            page.goto(f"{live_server.url}{path}")
            # Mislabelled "dark" numbers would gate the --glance-fill decision.
            assert page.locator("html").get_attribute("data-theme") == theme
            page.screenshot(
                path=str(OUT_DIR / f"glance-{name}-{theme}.png"), full_page=True
            )
            notes.append(f"- {name} {theme}: {page.evaluate(CONTRAST_JS)}")
        page.context.clear_cookies()

    for theme in ("light", "dark"):
        page.context.add_cookies(
            [{"name": "libli_theme", "value": theme, "url": live_server.url}]
        )
        page.goto(f"{live_server.url}/")
        assert page.locator("html").get_attribute("data-theme") == theme
        page.screenshot(
            path=str(OUT_DIR / f"glance-landing-{theme}.png"), full_page=True
        )
        notes.append(f"- landing {theme}: {page.evaluate(CONTRAST_JS)}")

    # Polish dashboard: labels must neither wrap nor clip.
    student.theme = "light"
    student.language = "pl"
    student.save(update_fields=["theme", "language"])
    page.context.clear_cookies()
    _login(page, live_server, "glanceshots")
    page.goto(f"{live_server.url}/home/")
    assert (
        page.locator("html").get_attribute("lang") == "pl"
    )  # else an English page is mislabelled
    page.screenshot(path=str(OUT_DIR / "glance-dashboard-pl.png"), full_page=True)
    page.context.clear_cookies()

    page.emulate_media(forced_colors="active")
    page.goto(f"{live_server.url}/")
    page.screenshot(
        path=str(OUT_DIR / "glance-landing-forced-colors.png"), full_page=True
    )
    # The dashboard has the zero-dot and empty tracks the landing lacks.
    _login(page, live_server, "glanceshots")
    page.screenshot(
        path=str(OUT_DIR / "glance-dashboard-forced-colors.png"), full_page=True
    )
    notes.append(
        "- Measured palette: the DEFAULT brand accent only; an install with a custom "
        "--brand-accent (core/templatetags/branding.py) is not covered."
    )

    (OUT_DIR / "glance-verification.md").write_text(
        "\n".join(notes) + "\n", encoding="utf-8"
    )
