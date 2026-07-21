import re

import pytest

from courses.rollups import build_outline
from courses.rollups import build_unit_nav
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_verified_user


def _make_student(username):
    """A verified, enrollable user. Mirrors the file's existing factory idiom."""
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _course_with_part():
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, order=0
    )
    l1 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=0,
        obligatory=True,
    )
    l2 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        obligatory=True,
    )
    return course, part, l1, l2


@pytest.mark.django_db
def test_unit_shell_wraps_lesson_article_and_keeps_seen_hook(client):
    course, part, l1, l2 = _course_with_part()
    user = make_verified_user(
        username="r1", email="r1@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=l1, completed=True)
    client.force_login(user)

    html = client.get(f"/courses/{course.slug}/u/{l2.pk}/").content.decode()
    # Shell wraps the page.
    assert "unit-shell" in html
    # The seen-tracking article is intact (progress.js depends on it).
    assert 'class="lesson"' in html and "data-seen-url=" in html
    # Tree landmark + current highlight + completed badge.
    assert "aria-label" in html and "unit-tree" in html
    assert 'aria-current="page"' in html
    assert "badge--done" in html  # l1 completed → ✓ in the tree
    # Footer Prev shows the neighbour title — scope to the footer, since l1.title
    # also appears in the tree on every page (a bare `l1.title in html` would pass
    # even with a broken footer). Parse the footer region and assert the prev navtitle.
    foot = re.search(r'<footer class="unit-foot".*?</footer>', html, re.S).group(0)
    assert "unit-foot__nav" in foot and l1.title in foot  # prev neighbour in footer
    # Course hairline present (course has required units).
    assert "unit-foot__course" in html


@pytest.mark.django_db
def test_unit_shell_first_unit_disables_prev(client):
    course, part, l1, l2 = _course_with_part()
    user = make_verified_user(
        username="r2", email="r2@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=user, course=course)
    client.force_login(user)

    html = client.get(f"/courses/{course.slug}/u/{l1.pk}/").content.decode()
    # Disabled prev is a non-focusable span, not an <a>.
    assert '<span class="unit-foot__nav unit-foot__nav--disabled"' in html


@pytest.mark.django_db
def test_unit_shell_part_chip_hidden_for_root_unit(client):
    course = CourseFactory()
    u = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        order=0,
        obligatory=True,
    )
    user = make_verified_user(
        username="r3", email="r3@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=user, course=course)
    client.force_login(user)

    html = client.get(f"/courses/{course.slug}/u/{u.pk}/").content.decode()
    assert "unit-foot__part" not in html  # no enclosing part → chip hidden
    assert "unit-foot__course" in html  # hairline still shown (course has 1 required)


@pytest.mark.django_db
def test_stamp_current_chain_marks_only_the_ancestor_chain():
    """contains_current is True on the current unit and its ancestors, False elsewhere.

    The key is always PRESENT (initialised False), never merely absent — so the
    template's {% if %} has one meaning and this test can assert `is False`.
    """
    from courses.rollups import _stamp_current_chain

    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    part_a = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    chap_a = ContentNodeFactory(
        course=course, kind="chapter", parent=part_a, unit_type=None
    )
    target = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_a
    )
    sibling_chap = ContentNodeFactory(
        course=course, kind="chapter", parent=part_a, unit_type=None
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=sibling_chap
    )
    part_b = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    # A deeper GROUP in an unrelated branch — a sibling root alone would not prove the
    # pass stops descending outside the chain.
    chap_b = ContentNodeFactory(
        course=course, kind="chapter", parent=part_b, unit_type=None
    )
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=chap_b)

    tree = build_outline(course, student)
    _stamp_current_chain(tree, target.pk)

    flags = {}

    def collect(items):
        for d in items:
            flags[d["node"].pk] = d["contains_current"]
            collect(d["children"])

    collect(tree)

    assert flags[target.pk] is True, "the current unit itself must be stamped"
    assert flags[chap_a.pk] is True, "the parent chapter must be stamped"
    assert flags[part_a.pk] is True, "the grandparent part must be stamped"
    assert flags[sibling_chap.pk] is False, "a sibling group must NOT be stamped"
    assert flags[part_b.pk] is False, "an unrelated root must NOT be stamped"
    assert flags[chap_b.pk] is False, (
        "a deeper group in an unrelated branch must NOT be stamped"
    )
    assert all(pk in flags for pk in (target.pk, chap_a.pk, part_a.pk)), (
        "key must be present"
    )


@pytest.mark.django_db
def test_top_level_part_still_returns_a_root_unit():
    """A depth-1 unit's root IS itself — build_unit_nav reads top["is_unit"] to
    suppress the part chip. The stamping pass must therefore stamp unit dicts too."""
    from courses.rollups import _stamp_current_chain
    from courses.rollups import _top_level_part

    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    root_unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )

    tree = build_outline(course, student)
    _stamp_current_chain(tree, root_unit.pk)
    top = _top_level_part(tree)

    assert top is not None
    assert top["node"].pk == root_unit.pk
    assert top["is_unit"] is True


@pytest.mark.django_db
def test_build_unit_nav_stamps_the_tree_it_returns():
    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part
    )

    nav = build_unit_nav(course, student, unit)

    assert nav["tree"][0]["contains_current"] is True
    assert nav["tree"][0]["children"][0]["contains_current"] is True


@pytest.mark.django_db
def test_build_unit_nav_adds_no_queries(django_assert_num_queries):
    """Baseline measured on origin/master before this change: 2 queries.

    The stamping pass is pure dict mutation, so this number must not move. Measuring
    post-change and hard-coding the result would make this assertion incapable of
    detecting the regression it exists to catch.
    """
    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part
    )

    with django_assert_num_queries(2):
        build_unit_nav(course, student, unit)


@pytest.mark.django_db
def test_group_renders_as_details_open_only_on_the_current_chain(client):
    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    EnrollmentFactory(student=student, course=course)
    chap_a = ContentNodeFactory(
        course=course,
        kind="chapter",
        parent=None,
        unit_type=None,
        title="Current Chapter",
    )
    target = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chap_a,
        title="Target Unit",
    )
    chap_b = ContentNodeFactory(
        course=course,
        kind="chapter",
        parent=None,
        unit_type=None,
        title="Other Chapter",
    )
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=chap_b)

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{target.pk}/").content.decode()

    groups = re.findall(r'<details class="unit-tree__group"([^>]*)>', html)
    # Rail + drawer render the tree twice, so each chapter appears twice.
    assert sum("open" in g for g in groups) == 2, (
        "only the current chapter should be open"
    )
    assert sum("open" not in g for g in groups) == 2, "the other chapter should be shut"


@pytest.mark.django_db
def test_group_counter_renders_actual_numerals(client):
    """Assert the numerals, not just the class — a scoping slip renders a bare '/'."""
    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    EnrollmentFactory(student=student, course=course)
    chap = ContentNodeFactory(
        course=course, kind="chapter", parent=None, unit_type=None
    )
    units = [
        ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=chap)
        for _ in range(3)
    ]
    UnitProgressFactory(student=student, unit=units[0], completed=True)

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{units[0].pk}/").content.decode()

    summaries = re.findall(r"<summary.*?</summary>", html, re.S)
    assert summaries, "expected a group summary"
    # Scoped to the summary: a document-wide "1/3" is ALSO satisfied by the footer's
    # part chip (_unit_footer.html:38 renders "Part 1/3"), which would defeat the whole
    # point of this assertion — catching a template-scoping slip that renders a bare
    # "/".
    assert any("unit-tree__count" in s and "1/3" in s for s in summaries), (
        "counter must render real numerals from the rollup fields, inside the summary"
    )
    assert any("of 3 required units completed" in s for s in summaries), (
        "a11y sentence missing"
    )
    assert any('class="unit-tree__count" aria-hidden="true"' in s for s in summaries), (
        "visible ratio must be aria-hidden so it is not double-announced"
    )


@pytest.mark.django_db
def test_all_quiz_group_renders_no_counter_and_no_check(client):
    """required_total == 0 -> no counter, no tick (quizzes carry no required work)."""
    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    EnrollmentFactory(student=student, course=course)
    chap = ContentNodeFactory(
        course=course, kind="chapter", parent=None, unit_type=None
    )
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=chap)

    client.force_login(student)
    # follow=True: lesson_unit 302s a quiz node to quiz_unit (views.py:567). Without it
    # the body is the empty redirect and both negative assertions below pass vacuously.
    html = client.get(
        f"/courses/{course.slug}/u/{quiz.pk}/", follow=True
    ).content.decode()

    # Scoped to unit-tree__head: the page also carries an unrelated
    # `<summary class="unit-tags__summary">` (_unit_shell.html's Tags disclosure), so a
    # bare `<summary.*?</summary>` sweep would satisfy the positive anchor below even
    # with no group summary rendered at all — the assertion could never go red.
    summaries = [
        s
        for s in re.findall(r"<summary.*?</summary>", html, re.S)
        if "unit-tree__head" in s
    ]
    # Positive anchor first: a document-wide "string absent" assertion also passes when
    # the tree failed to render at all.
    assert summaries, "expected the quiz's chapter to render a group summary"
    assert not any("unit-tree__count" in s for s in summaries), (
        "no counter at required_total==0"
    )
    assert not any("unit-tree__groupcheck" in s for s in summaries), (
        "no tick at required_total==0"
    )


@pytest.mark.django_db
def test_completed_group_renders_the_group_check(client):
    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    EnrollmentFactory(student=student, course=course)
    chap = ContentNodeFactory(
        course=course, kind="chapter", parent=None, unit_type=None
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap
    )
    UnitProgressFactory(student=student, unit=unit, completed=True)

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()

    summaries = re.findall(r"<summary.*?</summary>", html, re.S)
    assert summaries, "expected a group summary"
    assert any("unit-tree__groupcheck" in s for s in summaries), (
        "an n/n group gets its own trailing check class"
    )
    # The tick is ADDITIVE, not a replacement: a completed group reads "1/1 ✓".
    assert any("unit-tree__groupcheck" in s and "1/1" in s for s in summaries), (
        "the counter must remain alongside the tick at n/n"
    )
    assert not any("unit-tree__check" in s for s in summaries), (
        "the group check must NOT reuse .unit-tree__check — that class resets "
        ".badge--done's margin-left:auto for a LEADING icon (courses.css:550-552); "
        "in the summary the check trails"
    )


@pytest.mark.django_db
def test_flat_course_renders_no_details(client):
    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()

    assert "unit-tree__group" not in html, "a flat course has no groups to fold"


@pytest.mark.django_db
def test_childless_group_keeps_the_plain_head_shape(client):
    """An empty disclosure would be a dead control, so childless groups get none."""
    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    EnrollmentFactory(student=student, course=course)
    ContentNodeFactory(
        course=course,
        kind="chapter",
        parent=None,
        unit_type=None,
        title="Empty Chapter",
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()

    assert '<div class="unit-tree__head"' in html, "childless group keeps the plain div"
