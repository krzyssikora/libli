"""Playwright e2e for Phase 3c-ii: the teacher analytics-matrix journey.

The owner opens the matrix (Progress), sees a student's 100% cell, toggles to
Results, then edits a colour-band threshold and saves — all via real gestures.
"""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_pa

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_teacher_views_matrix_toggles_mode_and_edits_a_band(page, live_server, client):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UnitProgressFactory
    from tests.factories import UserFactory

    owner = make_pa(client, "e2eanalytics")  # PA: passes can_review + can_manage
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    les = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, obligatory=True
    )
    # A quiz too: Results shows only quiz-bearing columns, and the band save
    # lands back on Results, which must still draw a table.
    ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch)
    student = UserFactory(display_name="Ada L.")
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)

    _login(page, live_server, "e2eanalytics")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/")
    expect(page.locator("table.analytics__matrix")).to_contain_text("100%")
    expect(page.get_by_text("Ada L.")).to_be_visible()

    # Toggle to Results (real click on the toggle link)
    page.get_by_role("link", name="Results").click()
    expect(page).to_have_url(re.compile(r"mode=results"))

    # Edit a colour-band threshold and save (real form submit)
    page.get_by_role("link", name="Configure colours").click()
    page.fill("input[name='min_1']", "10")
    page.get_by_role("button", name="Save").click()
    expect(page.locator("table.analytics__matrix")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_teacher_drills_into_columns_and_a_student(page, live_server, client):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UnitProgressFactory
    from tests.factories import UserFactory

    owner = make_pa(client, "e2edrill")
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    sec = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=ch, title="Sec1"
    )
    les = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=sec,
        obligatory=True,
        title="U1",
    )
    student = UserFactory(display_name="Ada L.")
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)

    _login(page, live_server, "e2edrill")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/")

    # Expand Ch1 (real click on its expandable leaf-column header link)
    page.get_by_role("link", name=re.compile(r"Ch1")).click()
    expect(page.locator(".analytics__group")).to_contain_text("Ch1")
    # Now Sec1 is a leaf column; expand it (recursive)
    page.get_by_role("link", name=re.compile(r"Sec1")).click()
    expect(page.locator("table.analytics__matrix")).to_contain_text("U1")
    expect(page.locator(".analytics__group")).to_have_count(2)  # Ch1 + Sec1 span cells

    # Collapse via the ✕ on the spanning header cells: the deeper "Sec1" group
    # first (its cell uniquely contains "Sec1"), then the lone remaining "Ch1".
    page.locator(".analytics__group", has_text="Sec1").locator(
        ".analytics__collapse"
    ).click()
    expect(page.locator(".analytics__group")).to_have_count(1)
    page.locator(".analytics__group .analytics__collapse").click()
    expect(page.locator(".analytics__group")).to_have_count(0)

    # Drill into the student
    page.get_by_role("link", name="Ada L.").click()
    expect(page.locator(".manage__title")).to_contain_text("Ada L.")
    expect(page.locator(".badge--done")).to_be_visible()  # U1 completed ✓

    # Breadcrumb back to the matrix (scope the locator to the breakdown header so a
    # sibling "Analytics" nav link, if any, can't make this ambiguous).
    page.locator(".breakdown .manage__head").get_by_role("link").click()
    expect(page.locator("table.analytics__matrix")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_teacher_cherry_picks_a_subset(page, live_server, client):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UnitProgressFactory
    from tests.factories import UserFactory

    owner = make_pa(client, "owner")
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None)
    les = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, obligatory=True
    )
    students = [UserFactory() for _ in range(3)]
    for s in students:
        Enrollment.objects.create(student=s, course=course)
        UnitProgressFactory(student=s, unit=les, completed=True)

    _login(page, live_server, "owner")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/")
    # Scope to the row CHECKBOXES: the Export panel also forwards the active subset
    # as hidden `name="student"` inputs, so a bare `input[name="student"]` would also
    # match those once a subset is applied. `[type="checkbox"]` counts only the rows.
    rows = page.locator('input[name="student"][type="checkbox"]')
    # all three rows present
    expect(rows).to_have_count(3)
    # Select-all, then uncheck the first student, then Apply
    page.locator(".analytics__selectall").check()
    rows.first.uncheck()
    page.get_by_role("button", name=re.compile("Apply", re.I)).click()
    # now two rows remain
    expect(page.locator('input[name="student"][type="checkbox"]')).to_have_count(2)
    # Clear ("Show all") restores all three
    page.get_by_role("link", name=re.compile("Show all", re.I)).click()
    expect(page.locator('input[name="student"][type="checkbox"]')).to_have_count(3)


@pytest.mark.django_db(transaction=True)
def test_teacher_toggles_raw_and_percent(page, live_server, client):
    from decimal import Decimal

    from courses.models import Enrollment
    from courses.models import QuizSubmission
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UserFactory

    owner = make_pa(client, "e2eraw")
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    qz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=ch, title="Q1"
    )
    student = UserFactory(display_name="Ada L.")
    Enrollment.objects.create(student=student, course=course)
    QuizSubmission.objects.create(
        student=student,
        unit=qz,
        status="submitted",
        score=Decimal("34"),
        max_score=Decimal("50"),
    )

    _login(page, live_server, "e2eraw")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/?mode=results")
    expect(page.locator("table.analytics__matrix")).to_contain_text("68%")
    # Real click on the Raw toggle link
    page.get_by_role("link", name="Raw").click()
    expect(page).to_have_url(re.compile(r"values=raw"))
    expect(page.locator("table.analytics__matrix")).to_contain_text("34/50")
    # Back to Percent
    page.get_by_role("link", name="Percent").click()
    expect(page.locator("table.analytics__matrix")).to_contain_text("68%")


@pytest.mark.django_db(transaction=True)
def test_group_teacher_drills_from_the_matrix_to_one_answer(page, live_server, client):
    from decimal import Decimal

    from courses.models import Element
    from courses.models import QuestionResponse
    from courses.models import QuizSubmission
    from courses.models import ShortNumericQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import GroupFactory
    from tests.factories import GroupMembershipFactory
    from tests.factories import UserFactory
    from tests.factories import make_teacher

    teacher = make_teacher(client, "e2eanswers")  # NOT staff: the kit-teacher shape
    course = CourseFactory(owner=UserFactory())
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=ch, title="Fractions quiz"
    )
    question = ShortNumericQuestionElement.objects.create(
        stem="<p>2/3 + 1/6?</p>", value="5/6", tolerance="", max_marks=Decimal("1")
    )
    element = Element.objects.create(unit=quiz, content_object=question)
    pupil = UserFactory(display_name="Ada L.")
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    GroupMembershipFactory(group=group, student=pupil)
    submission = QuizSubmission.objects.create(
        student=pupil,
        unit=quiz,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("1"),
    )
    QuestionResponse.objects.create(
        submission=submission,
        element=element,
        latest_answer="4/9",
        fraction=Decimal("0"),
        attempt_count=1,
        locked=True,
    )

    _login(page, live_server, "e2eanswers")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/")
    page.get_by_role("link", name="Ada L.").click()
    page.locator("a.breakdown-unit__link", has_text="Fractions quiz").click()
    item = page.locator("li.answers__item").first
    expect(item).to_contain_text("4/9")
    expect(item).to_contain_text("Correct answer: 5/6")
    page.locator("section.answers .manage__head").get_by_role("link").click()
    expect(page.locator(".breakdown .manage__title")).to_contain_text("Ada L.")


_LONG_TITLE = "Rozdział 1: Liczby rzeczywiste i działania"

# Centre of the first body row's first SCORE cell's text, and what the browser
# actually paints there. On phones the pinned Student + Overall columns used to
# leave a sliver so narrow that the number sat underneath Overall (or past the
# scroll box's edge) -- the cell's colour showed, its value never did.
_FIRST_SCORE_PAINTED = """() => {
  const td = document.querySelector('.analytics__matrix tbody tr td:nth-child(2)');
  const range = document.createRange();
  range.selectNodeContents(td);
  const r = range.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const at = (px) => {
    const hit = document.elementFromPoint(px, y);
    return hit === td || td.contains(hit);
  };
  // the number itself, and BOTH edges of its cell: a whole score column must
  // fit beside the (frozen) Student column, not just a sliver of it
  const c = td.getBoundingClientRect();
  return {text: td.textContent.trim(), painted: at(x),
          whole_cell: at(c.left + 2) && at(c.right - 2)};
}"""


def _long_titled_results_course(client, username):
    from decimal import Decimal

    from courses.models import Enrollment
    from courses.models import QuizSubmission
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UserFactory

    owner = make_pa(client, username)
    course = CourseFactory(owner=owner)
    for i in range(3):
        ch = ContentNodeFactory(
            course=course,
            kind="chapter",
            unit_type=None,
            parent=None,
            title=_LONG_TITLE if i == 0 else f"Rozdział {i + 1}: Funkcje",
        )
        quiz = ContentNodeFactory(
            course=course, kind="unit", unit_type="quiz", parent=ch
        )
        for name in ("Krystyna Jankowska", "Elżbieta Michalska"):
            student, _ = UserFactory._meta.model.objects.get_or_create(
                username=name.replace(" ", "").lower(),
                defaults={
                    "display_name": name,
                    "first_name": name.split()[0],
                    "last_name": name.split()[1],
                },
            )
            Enrollment.objects.get_or_create(student=student, course=course)
            QuizSubmission.objects.create(
                student=student,
                unit=quiz,
                status="submitted",
                score=Decimal("7"),
                max_score=Decimal("10"),
            )
    return course


@pytest.mark.parametrize("width", [320, 375])
@pytest.mark.django_db(transaction=True)
def test_phone_width_shows_a_score_between_the_frozen_columns(
    page, live_server, client, width
):
    course = _long_titled_results_course(client, "e2emobile")
    _login(page, live_server, "e2emobile")
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/?mode=results")
    page.locator(".analytics__matrix").scroll_into_view_if_needed()
    got = page.evaluate(_FIRST_SCORE_PAINTED)
    assert got == {"text": "70%", "painted": True, "whole_cell": True}
    # Overall stops pinning right, but its header still sticks to the top
    head = page.locator(".analytics__matrix th.analytics__overall")
    assert head.evaluate("e => getComputedStyle(e).position") == "sticky"
    assert head.evaluate("e => getComputedStyle(e).right") == "auto"
    # the long header is cut short with an ellipsis, full text kept as a tooltip
    title = page.locator(".analytics__coltitle", has_text="Rozdział 1").first
    assert title.get_attribute("title") == _LONG_TITLE
    assert title.evaluate("e => e.scrollWidth > e.clientWidth")
    assert title.evaluate("e => getComputedStyle(e).textOverflow") == "ellipsis"


_QUIZ_TITLE = "Wzory skróconego mnożenia - quiz"

# Every header row's cells must sit in their own band: row k's bottom edge at
# or above row k+1's top. The header rows are pinned at top = k * --ahead-h, so
# a title taller than its row would overlap the next pinned row.
_HEADER_ROWS_STACKED = """() => {
  const rows = [...document.querySelectorAll('.analytics__matrix thead tr')];
  const bands = rows.map(tr => [...tr.children]
    .filter(th => th.rowSpan === 1)
    .map(th => { const b = th.getBoundingClientRect(); return [b.top, b.bottom]; }));
  for (let k = 0; k + 1 < bands.length; k++) {
    const bottom = Math.max(...bands[k].map(b => b[1]));
    const top = Math.min(...bands[k + 1].map(b => b[0]));
    if (bottom > top + 0.5) return false;
  }
  // and every title fits inside its own header cell
  return [...document.querySelectorAll('.analytics__coltitle')].every(t => {
    const th = t.closest('th').getBoundingClientRect(), b = t.getBoundingClientRect();
    return b.bottom <= th.bottom + 0.5 && b.top >= th.top - 0.5;
  });
}"""


def _narrow_columns_course(client, username):
    from decimal import Decimal

    from courses.models import Enrollment
    from courses.models import QuizSubmission
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UserFactory

    owner = make_pa(client, username)
    course = CourseFactory(owner=owner)
    algebra = ContentNodeFactory(
        course=course,
        kind="chapter",
        unit_type=None,
        parent=None,
        # long on purpose: an opened section's title spans its columns and must
        # not widen them
        title="Algebra: wyrażenia algebraiczne i wzory skróconego mnożenia",
    )
    quizzes = [
        ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type="quiz",
            parent=algebra,
            title=_QUIZ_TITLE,
        ),
        ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type="quiz",
            parent=algebra,
            title="Potęgi",
        ),
    ]
    # enough columns that the opened section is wider than the page column,
    # so its collapse ✕ can end up under the frozen Overall column
    quizzes += [
        ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type="quiz",
            parent=algebra,
            title=f"Sprawdzian {n}",
        )
        for n in range(1, 9)
    ]
    # a word longer than 6.5rem, in an EXPANDABLE (flex-row) header
    geometry = ContentNodeFactory(
        course=course,
        kind="chapter",
        unit_type=None,
        parent=None,
        title="Planimetria - trójkąty",
    )
    quizzes.append(
        ContentNodeFactory(
            course=course, kind="unit", unit_type="quiz", parent=geometry
        )
    )
    # a NARROW opened section (one column) with a long title: it wraps to two
    # lines, which its pinned header row must have room for
    shapes = ContentNodeFactory(
        course=course,
        kind="chapter",
        unit_type=None,
        parent=None,
        title="Geometria: figury płaskie, trójkąty i czworokąty",
    )
    quizzes.append(
        ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=shapes)
    )
    for n in range(30):
        student = UserFactory(display_name=f"Uczeń {n:02d}")
        Enrollment.objects.create(student=student, course=course)
        for quiz in quizzes:
            QuizSubmission.objects.create(
                student=student,
                unit=quiz,
                status="submitted",
                score=Decimal("3"),
                max_score=Decimal("3"),
            )
    return course, algebra, shapes


@pytest.mark.django_db(transaction=True)
def test_desktop_columns_are_narrow_with_two_line_titles(page, live_server, client):
    course, algebra, shapes = _narrow_columns_course(client, "e2edesk")
    _login(page, live_server, "e2edesk")
    page.set_viewport_size({"width": 1280, "height": 800})
    base = f"{live_server.url}/manage/courses/{course.slug}/analytics/?mode=results"
    page.goto(f"{base}&values=raw&expand={algebra.pk}&expand={shapes.pk}")
    leaf = "th.analytics__colhead:not(.analytics__group)"
    th = page.locator(leaf, has_text="Wzory")
    rem = page.evaluate(
        "parseFloat(getComputedStyle(document.documentElement).fontSize)"
    )
    # a "3/3" column, not a 250px one: 6.5rem plus its 1px border
    assert th.evaluate("e => e.getBoundingClientRect().width") <= 6.5 * rem + 1
    title = page.locator(f"{leaf} .analytics__coltitle", has_text="Wzory")
    line = title.evaluate("e => parseFloat(getComputedStyle(e).lineHeight)")
    assert title.evaluate("e => e.getBoundingClientRect().height") >= 1.9 * line
    assert title.get_attribute("title") == _QUIZ_TITLE
    # a short title is not cut
    short = page.locator(".analytics__coltitle", has_text="Potęgi")
    assert short.evaluate("e => e.scrollHeight <= e.clientHeight")
    # words are never split: each title's longest word fits its title's width
    # (break-word only splits a word that doesn't fit -- so measure the word,
    # not the overflow, which break-word never produces)
    split = page.evaluate(
        """() => [...document.querySelectorAll(
          'th.analytics__colhead:not(.analytics__group) .analytics__coltitle')]
          .filter(t => {
            const word = t.textContent.split(/\s+/)
              .reduce((a, w) => (w.length > a.length ? w : a), '');
            const probe = document.createElement('span');
            probe.style.whiteSpace = 'nowrap';
            probe.textContent = word;
            t.appendChild(probe);
            const wide = probe.getBoundingClientRect().width > t.clientWidth + 0.5;
            probe.remove();
            return wide;
          }).map(t => t.textContent)"""
    )
    assert split == []
    assert page.evaluate(_HEADER_ROWS_STACKED)
    page.locator(".analytics__scroll").evaluate("e => { e.scrollTop = 300; }")
    assert page.evaluate(_HEADER_ROWS_STACKED)
    overall = page.locator(".analytics__matrix td.analytics__overall").first
    assert overall.evaluate("e => getComputedStyle(e).position") == "sticky"
    # the table sizes to its columns: with fixed score columns, a stretched
    # (width:100%) table hands the spare width to Overall, the auto column
    assert overall.evaluate("e => e.getBoundingClientRect().width") <= 6.5 * rem + 1
    # an opened section's title has room for its two lines (its header row is
    # a fixed --ahead-h tall, and the title is out of flow inside it)
    narrow = page.locator(".analytics__group-title", has_text="Geometria")
    assert narrow.evaluate("e => e.getBoundingClientRect().height") >= 1.9 * line
    # ...and does not widen the one column it spans
    assert (
        narrow.evaluate("e => e.closest('th').getBoundingClientRect().width")
        <= 6.5 * rem + 1
    )
    # its collapse ✕ follows the title and is really there to click -- not
    # pushed to the far end of a wide section, under the frozen Overall column
    assert page.evaluate(
        """() => {
          const x = document.querySelector('th.analytics__group .analytics__collapse');
          const b = x.getBoundingClientRect();
          const hit = document.elementFromPoint(
            b.left + b.width / 2, b.top + b.height / 2);
          return hit === x || x.contains(hit);
        }"""
    )


# --- Full-screen mode (desktop) ----------------------------------------------
# An in-page mode, not the browser Fullscreen API: every drill-down / mode /
# scope change is a full navigation, which would drop a real fullscreen. So the
# section covers the window and the choice is remembered in localStorage.

_SECTION_BOX = """() => {
  const s = document.querySelector('section.analytics');
  const b = s.getBoundingClientRect();
  const hit = document.elementFromPoint(5, 5);
  return {left: b.left, top: b.top, width: b.width,
          covers_header: s.contains(hit),
          scroll_bottom: document.querySelector('.analytics__scroll')
            .getBoundingClientRect().bottom};
}"""


@pytest.mark.django_db(transaction=True)
def test_full_screen_fills_the_window_and_survives_a_drill_down(
    page, live_server, client
):
    course = _long_titled_results_course(client, "e2efull")
    _login(page, live_server, "e2efull")
    page.set_viewport_size({"width": 1400, "height": 900})
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/?mode=results")
    normal = page.evaluate(_SECTION_BOX)
    assert normal["width"] < 1000 and not normal["covers_header"]

    page.get_by_role("button", name="Full screen").click()
    full = page.evaluate(_SECTION_BOX)
    assert full["left"] == 0 and full["top"] == 0 and full["width"] == 1400
    assert full["covers_header"]  # the site header is covered, not just pushed
    # the table's scroll box runs (nearly) to the bottom of the window
    assert full["scroll_bottom"] > 900 - 80
    toggle = page.get_by_role("button", name="Exit full screen")
    expect(toggle).to_have_attribute("aria-pressed", "true")

    # a drill-down is a full navigation; the mode must survive it
    page.locator("a.analytics__expand").first.click()
    expect(page).to_have_url(re.compile(r"expand="))
    after = page.evaluate(_SECTION_BOX)
    assert after["width"] == 1400 and after["covers_header"]

    # Esc leaves it, and the choice sticks across a reload
    page.keyboard.press("Escape")
    assert page.evaluate(_SECTION_BOX)["width"] < 1000
    expect(page.get_by_role("button", name="Full screen")).to_have_attribute(
        "aria-pressed", "false"
    )
    page.reload()
    assert page.evaluate(_SECTION_BOX)["width"] < 1000


@pytest.mark.django_db(transaction=True)
def test_full_screen_is_desktop_only(page, live_server, client):
    course = _long_titled_results_course(client, "e2efullphone")
    _login(page, live_server, "e2efullphone")
    page.set_viewport_size({"width": 375, "height": 800})
    url = f"{live_server.url}/manage/courses/{course.slug}/analytics/?mode=results"
    page.goto(url)
    expect(page.get_by_role("button", name="Full screen")).to_be_hidden()
    # a choice remembered from a desktop session must not take over a phone
    page.evaluate("() => localStorage.setItem('libli:analytics-full-screen', '1')")
    page.reload()
    assert not page.evaluate(_SECTION_BOX)["covers_header"]
