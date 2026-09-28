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


@pytest.mark.django_db(transaction=True)
def test_desktop_width_keeps_full_headers_and_frozen_overall(page, live_server, client):
    course = _long_titled_results_course(client, "e2edesk")
    _login(page, live_server, "e2edesk")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/?mode=results")
    title = page.locator(".analytics__coltitle", has_text="Rozdział 1").first
    assert title.evaluate("e => e.scrollWidth <= e.clientWidth")
    overall = page.locator(".analytics__matrix td.analytics__overall").first
    assert overall.evaluate("e => getComputedStyle(e).position") == "sticky"
