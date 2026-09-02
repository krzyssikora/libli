import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import QuizSubmission
from courses.rollups import HIDDEN_PATH_SEP
from courses.rollups import MARKER_ADDITIONAL
from courses.rollups import MARKER_QUIZ
from courses.rollups import _current_ancestors
from courses.rollups import _stamp_current_chain
from courses.rollups import build_outline
from courses.rollups import build_unit_nav
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
from tests.factories import add_element
from tests.factories import make_quiz_unit
from tests.factories import make_verified_user

COLLAPSE_BREAKPOINT_PX = 832


def _make_student(username):
    """A verified, enrollable user. Mirrors the file's existing factory idiom."""
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _crumb_nav(html):
    """The crumb <nav> as soup. The unit page renders the tree twice (rail + drawer)
    but the crumb exactly once, so select_one is unambiguous.

    NOTE: the returned Tag IS the <nav>. Read its own attributes directly
    (soup["lang"]); a self-referential soup.select_one("nav.unit-crumbs") returns
    None, because Tag.select_one matches descendants only.
    """
    return BeautifulSoup(html, "html.parser").select_one("nav.unit-crumbs")


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
        ".badge--done's margin-left:auto for a LEADING icon (courses.css); "
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
def test_a_genuinely_empty_group_is_pruned_not_rendered(client):
    """build_outline (courses/rollups.py, Task 5) prunes a container with no
    children from the tree under BOTH "hide" and "keep" — the plain-div
    fallback in _unit_tree_node.html (for a childless group) is unreachable
    from this student-facing page as a result, since an empty chapter never
    reaches the template at all."""
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

    assert "Empty Chapter" not in html, "a childless group is pruned from the tree"
    assert '<div class="unit-tree__head"' not in html
    assert "unit-tree__group" not in html, "the surviving unit is a flat root"


def _chain_course(depth):
    """A course with `depth` group ancestors above one lesson unit.

    depth 0 -> unit is a root; 1 -> part; 2 -> part/chapter; 3 -> part/chapter/section.
    Returns (course, groups, unit) with groups root-first.
    """
    course = CourseFactory()
    kinds = ["part", "chapter", "section"][:depth]
    groups, parent = [], None
    for kind in kinds:
        parent = ContentNodeFactory(
            course=course,
            kind=kind,
            parent=parent,
            unit_type=None,
            title=f"{kind.title()} title",
        )
        groups.append(parent)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=parent, title="The Unit"
    )
    return course, groups, unit


@pytest.mark.django_db
@pytest.mark.parametrize("depth", [0, 1, 2, 3])
def test_current_ancestors_returns_the_chain_root_first(depth):
    student = _make_student(f"anc{depth}")
    course, groups, unit = _chain_course(depth)

    nav = build_unit_nav(course, student, unit)

    assert [n.pk for n in nav["ancestors"]] == [g.pk for g in groups]


@pytest.mark.django_db
def test_current_ancestors_excludes_the_current_unit():
    student = _make_student("anc_excl")
    course, groups, unit = _chain_course(3)

    nav = build_unit_nav(course, student, unit)

    assert unit.pk not in [n.pk for n in nav["ancestors"]]
    assert all(n.kind != "unit" for n in nav["ancestors"])


@pytest.mark.django_db
def test_current_ancestors_returns_empty_for_a_stamped_tree_with_no_match():
    """Stamped-but-unmatched is a legitimate empty result, not an error."""
    student = _make_student("anc_nomatch")
    course, _groups, _unit = _chain_course(2)
    tree = build_outline(course, student)
    _stamp_current_chain(tree, -1)  # a pk that is certainly not in the tree

    assert _current_ancestors(tree) == []


@pytest.mark.django_db
def test_current_ancestors_raises_on_an_unstamped_tree():
    """Distinct from the empty case: forgetting to stamp must fail loudly."""
    student = _make_student("anc_unstamped")
    course, _groups, _unit = _chain_course(2)
    tree = build_outline(course, student)

    with pytest.raises(KeyError):
        _current_ancestors(tree)


@pytest.mark.django_db
def test_current_ancestors_handles_a_skipped_level():
    """A 'Full' course may still hold a unit whose only ancestor is a part."""
    student = _make_student("anc_skip")
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Only Part"
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part
    )

    nav = build_unit_nav(course, student, unit)

    assert [n.pk for n in nav["ancestors"]] == [part.pk]


@pytest.mark.django_db
@pytest.mark.parametrize("depth,expected", [(0, ""), (1, ""), (2, "Part title")])
def test_hidden_path_joins_all_but_the_deepest(depth, expected):
    student = _make_student(f"hp{depth}")
    course, _groups, unit = _chain_course(depth)

    assert build_unit_nav(course, student, unit)["hidden_path"] == expected


@pytest.mark.django_db
def test_hidden_path_joins_with_the_spoken_separator_and_never_the_glyph():
    """The visible '›' is aria-hidden; hidden_path is read aloud, so it must not
    contain the glyph or a screen reader announces its Unicode name per crumb."""
    student = _make_student("hp_sep")
    course, groups, unit = _chain_course(3)

    hidden_path = build_unit_nav(course, student, unit)["hidden_path"]

    assert hidden_path == HIDDEN_PATH_SEP.join(g.title for g in groups[:-1])
    assert "›" not in hidden_path


@pytest.mark.django_db
def test_crumb_renders_the_full_chain_with_one_leading_separator_each(client):
    student = _make_student("crumb_chain")
    course, groups, unit = _chain_course(3)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    html = client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()

    soup = _crumb_nav(html)
    items = soup.select("li.unit-crumbs__item")
    # course + ellipsis + 3 ancestors
    assert len(items) == 5
    # The course crumb has NO separator; every later crumb has exactly one.
    assert items[0].select("span.unit-crumbs__sep") == []
    for item in items[1:]:
        assert len(item.select("span.unit-crumbs__sep")) == 1
    assert {s.get_text(strip=True) for s in soup.select("span.unit-crumbs__sep")} == {
        "›"
    }
    assert all(
        s.get("aria-hidden") == "true" for s in soup.select("span.unit-crumbs__sep")
    )


@pytest.mark.django_db
def test_course_crumb_links_to_the_outline_and_carries_its_title(client):
    student = _make_student("crumb_course")
    course, _groups, unit = _chain_course(2)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(
        client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()
    )

    li = soup.select_one("li.unit-crumbs__item--course")
    assert li["title"] == course.title
    assert li.select_one("a.unit-crumbs__label")["href"] == f"/courses/{course.slug}/"


@pytest.mark.django_db
def test_group_crumbs_are_plain_text_never_links(client):
    student = _make_student("crumb_plain")
    course, _groups, unit = _chain_course(3)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(
        client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()
    )

    for cls in ("--mid", "--leaf", "--ellipsis"):
        items = soup.select(f"li.unit-crumbs__item{cls}")
        assert items, f"no {cls} crumbs found"
        assert all(li.select("a") == [] for li in items), (
            f"{cls} crumb must not be a link"
        )


@pytest.mark.django_db
def test_flat_course_renders_the_course_crumb_and_no_ellipsis(client):
    student = _make_student("crumb_flat")
    course, _groups, unit = _chain_course(0)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(
        client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()
    )

    assert soup.select_one("li.unit-crumbs__item--course") is not None
    assert soup.select("li.unit-crumbs__item--ellipsis") == []
    assert soup.select("li.unit-crumbs__item--mid") == []


@pytest.mark.django_db
def test_ellipsis_carries_hidden_path_as_title_and_visually_hidden_text(client):
    """The visually-hidden span is the SOLE accessibility carrier for the collapsed
    crumbs — at the collapse breakpoint the mids are display:none and gone from the
    accessibility tree. Without this test, deleting the span ships green."""
    student = _make_student("crumb_ellipsis")
    course, groups, unit = _chain_course(3)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(
        client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()
    )

    expected = HIDDEN_PATH_SEP.join(g.title for g in groups[:-1])
    li = soup.select_one("li.unit-crumbs__item--ellipsis")
    assert li is not None
    assert li["title"] == expected
    span = li.select_one("span.visually-hidden")
    assert span is not None, "ellipsis crumb is missing its visually-hidden span"
    assert span.get_text(strip=True) == expected
    assert li.get("aria-hidden") is None


@pytest.mark.django_db
def test_ellipsis_is_gated_on_ancestor_count_not_on_hidden_path_being_truthy(client):
    """Two ancestors whose mid has a blank title yields hidden_path == "" while the
    CSS still hides one crumb. Gating on the string would drop the ellipsis and
    silently break invariant 5."""
    student = _make_student("crumb_blank")
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title=""
    )
    chapter = ContentNodeFactory(
        course=course, kind="chapter", parent=part, unit_type=None, title="Chapter"
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter
    )
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(
        client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()
    )

    assert soup.select_one("li.unit-crumbs__item--ellipsis") is not None


@pytest.mark.django_db
def test_crumb_lives_inside_the_lesson_article(client):
    """The two-file include is justified entirely by padding and lang inheritance from
    the <article>. A later 'de-duplicate into _unit_shell.html' refactor would keep
    every other test green while breaking both."""
    student = _make_student("crumb_place")
    course, _groups, unit = _chain_course(2)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    html = client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()
    soup = BeautifulSoup(html, "html.parser")

    assert soup.select_one("article.lesson nav.unit-crumbs") is not None


@pytest.mark.django_db
def test_crumb_sets_ui_language_on_the_nav_and_course_language_on_each_item(client):
    """Author titles are course-language; the aria-label is UI-language. Both live
    inside <article lang="{{ course.language }}">, so the nav must override.

    UI = pl, course = en — deliberately INVERTED from the defaults. settings
    .LANGUAGE_CODE is "en" and conftest's autouse fixture pins the active language to
    it, so a UI-language assertion of "en" would also pass against a hardcoded
    lang="en" on the nav. Driving the UI to pl makes the two values distinguishable.
    The session key is how this repo switches UI language for a client request
    (SessionLocaleMiddleware); see tests/test_catalog_views.py for the precedent.
    """
    from core.middleware import LANGUAGE_SESSION_KEY

    student = _make_student("crumb_lang")
    course = CourseFactory(language="en")
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Part One"
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part
    )
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)
    session = client.session
    session[LANGUAGE_SESSION_KEY] = "pl"
    session.save()

    soup = _crumb_nav(
        client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()
    )

    # soup IS the <nav> — read the attribute off it directly. Tag.select_one()
    # matches DESCENDANTS only, so soup.select_one("nav.unit-crumbs") is None.
    assert soup["lang"] == "pl"  # UI language
    items = soup.select("li.unit-crumbs__item")
    assert items and all(li["lang"] == "en" for li in items)  # course language


@pytest.mark.django_db
def test_crumb_carries_the_aria_scaffolding(client):
    """WebKit drops list semantics under list-style:none, and changing an <li>'s
    display away from list-item is a second trigger — hence both roles."""
    student = _make_student("crumb_aria")
    course, _groups, unit = _chain_course(2)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    soup = _crumb_nav(
        client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()
    )

    assert soup["aria-label"].strip()  # soup IS the <nav>; see the note above
    assert soup.select_one("ol.unit-crumbs__list")["role"] == "list"
    items = soup.select("li.unit-crumbs__item")
    assert items and all(li["role"] == "listitem" for li in items)


def _quiz_course():
    """A course whose single unit is a quiz with one answerable question.

    Uses the repo's real element API: a ChoiceQuestionElement plus Choice rows,
    attached to the unit through an Element join-row via add_element().
    """
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, title="Quiz Part"
    )
    unit = make_quiz_unit(course=course, parent=part, title="The Quiz")
    question = ChoiceQuestionElement.objects.create(stem="<p>2+2?</p>", multiple=False)
    right = Choice.objects.create(question=question, text="4", is_correct=True, order=0)
    Choice.objects.create(question=question, text="5", is_correct=False, order=1)
    element = add_element(unit, question)
    return course, part, unit, element, right


@pytest.mark.django_db
def test_crumb_renders_on_the_quiz_page(client):
    """quiz_unit redirects a SUBMITTED quiz away, so the student must have no
    submission for this GET to reach _quiz_article.html at all."""
    student = _make_student("crumb_quiz")
    course, part, unit, _element, _right = _quiz_course()
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    # Go straight to quiz_unit. The lesson_unit URL 302s a quiz node here, so a GET
    # without follow=True would return an empty 302 body and fail regardless of the
    # implementation — the same trap is documented in this file's existing
    # test_all_quiz_group_renders_no_counter_and_no_check.
    url = reverse("courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    soup = BeautifulSoup(client.get(url).content.decode(), "html.parser")

    assert soup.select_one("article.quiz nav.unit-crumbs") is not None
    assert part.title in soup.select_one("nav.unit-crumbs").get_text()


@pytest.mark.django_db
def test_crumb_survives_the_no_js_check_answer_re_render(client):
    """Omitting the fragment header makes check_answer re-render the whole page."""
    student = _make_student("crumb_check")
    course, groups, unit = _chain_course(2)
    question = ChoiceQuestionElement.objects.create(stem="<p>2+2?</p>", multiple=False)
    right = Choice.objects.create(question=question, text="4", is_correct=True, order=0)
    element = add_element(unit, question)
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": element.pk},
    )
    soup = BeautifulSoup(
        client.post(url, {"choice": str(right.pk)}).content.decode(), "html.parser"
    )

    nav = soup.select_one("nav.unit-crumbs")
    assert nav is not None
    assert groups[-1].title in nav.get_text()


@pytest.mark.django_db
def test_crumb_survives_the_no_js_quiz_answer_re_render(client):
    """quiz_answer needs an ENROLLED student here: the actor is enrolled so this
    exercises the PERSISTED answer path; a non-enrolled viewer would take
    quiz_answer's ephemeral previewer branch instead, which writes nothing. Also
    needs an unlocked response with attempts left, and a NON-EMPTY answer — an
    empty POST takes the validation branch instead."""
    student = _make_student("crumb_qa")
    course, part, unit, element, right = _quiz_course()
    EnrollmentFactory(student=student, course=course)
    client.force_login(student)

    url = reverse(
        "courses:quiz_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": element.pk},
    )
    soup = BeautifulSoup(
        client.post(url, {"choice": str(right.pk)}, follow=True).content.decode(),
        "html.parser",
    )

    nav = soup.select_one("nav.unit-crumbs")
    assert nav is not None
    assert part.title in nav.get_text()


@pytest.mark.django_db
def test_submitted_quiz_results_page_has_no_crumb(client):
    """Stated non-goal: quiz_results.html is outside _unit_shell.html, has no
    unit_nav, and is deliberately not covered. Also guards the redirect the quiz-GET
    fixture above depends on."""
    student = _make_student("crumb_results")
    course, _part, unit, _element, _right = _quiz_course()
    EnrollmentFactory(student=student, course=course)
    QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )
    client.force_login(student)

    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/", follow=True)

    assert resp.redirect_chain, "a SUBMITTED quiz must redirect to the results page"
    assert "unit-crumbs" not in resp.content.decode()


def _media_block(css, query):
    """The body of the @media block introduced by `query`, by brace matching."""
    start = css.index(query) + len(query)
    depth, i = 0, start
    while i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[start : i + 1]
        i += 1
    raise AssertionError(f"unterminated @media block for {query!r}")


def test_collapse_breakpoint_is_in_bounds_and_matches_the_stylesheet():
    """Invariant 7 plus the CSS<->constant coupling.

    The range check is not redundant with the string check: because the expected
    query is DERIVED from the constant, a retune updates constant, CSS and expected
    string in lockstep and every other assertion stays green — while the e2e's third
    viewport (BREAKPOINT + 1) silently slides below 640 into the rail-less regime and
    stops sampling the four-crumb worst case. This bare range check is the only thing
    standing between that retune and a vacuous e2e.
    """
    assert 640 < COLLAPSE_BREAKPOINT_PX < 1280

    css = (
        Path(__file__).resolve().parent.parent
        / "courses/static/courses/css/courses.css"
    ).read_text(encoding="utf-8")

    query = f"@media screen and (max-width: {COLLAPSE_BREAKPOINT_PX}px)"
    assert query in css, f"stylesheet does not contain {query!r}"
    # Assert the crumb rule is INSIDE that block: a bare "max-width: NNNpx" substring
    # could be satisfied by an unrelated pre-existing query at some values.
    assert ".unit-crumbs__item--mid" in _media_block(css, query)


@pytest.mark.django_db
def test_toc_pin_renders_on_lesson_and_quiz_with_a_unique_aria_controls_target(client):
    """The pin ships in the DOM server-rendered, not created by JS.

    base.html's pre-paint script sets html.unit-tree-collapsed BEFORE first
    paint, so a CSS-only reveal is flash-free; a JS-created button would pop in
    after hydration. Its aria-controls target must exist exactly once.
    """
    student = _make_student("pin_render")
    course = CourseFactory(slug="pin-render", owner=student)
    EnrollmentFactory(course=course, student=student)
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    quiz = make_quiz_unit(course=course)
    client.force_login(student)

    for node in (lesson, quiz):
        url = reverse(
            "courses:lesson_unit" if node is lesson else "courses:quiz_unit",
            kwargs={"slug": course.slug, "node_pk": node.pk},
        )
        soup = BeautifulSoup(client.get(url, follow=True).content, "html.parser")

        pin = soup.select_one("[data-unit-tree-pin]")
        assert pin is not None, f"the TOC pin is missing from {url}"
        assert pin.get("aria-expanded") is not None, "the pin must ship aria-expanded"
        assert pin.get("aria-controls") == "unit-tree"

        targets = soup.select("#unit-tree")
        assert len(targets) == 1, (
            f"aria-controls must resolve to exactly one element, found {len(targets)}"
        )

        rail_toggle = soup.select_one("[data-unit-tree-toggle]")
        assert rail_toggle.get("aria-controls") == "unit-tree", (
            "both controls must describe the same disclosure relationship"
        )

        pins = soup.select("[data-unit-tree-pin]")
        assert len(pins) == 1, "the pin must not share a selector with the rail toggle"


@pytest.mark.django_db
def test_rail_marks_quiz_and_additional_as_the_last_child(client):
    """The icon TRAILS the label. The ✓ already leads (courses.css resets
    .badge--done's margin-left:auto for exactly that), so a second leading glyph
    would make every completed additional unit begin with two marks.

    Scoped to [data-unit-tree-list]: _unit_shell.html renders the whole tree
    TWICE per unit page (rail + drawer), so an unscoped select_one silently
    tests only the rail and a `len(...) == 1` assertion fails on a CORRECT build.
    """
    # language="pl" deliberately: CourseFactory defaults to "en", which would make
    # the lang assertion below pass whether the partial emits LANGUAGE_CODE or
    # simply inherits course.language.
    course = CourseFactory(language="pl")
    student = _make_student("s_rail_kind")
    EnrollmentFactory(student=student, course=course)
    req = ContentNodeFactory(
        course=course, unit_type="lesson", obligatory=True, title="Required"
    )
    add = ContentNodeFactory(
        course=course, unit_type="lesson", obligatory=False, title="Additional one"
    )
    # A quiz is marked regardless of `obligatory` (test_unit_marker.py::
    # test_marker_table pins this at the unit_marker() layer, as a pair with an
    # obligatory quiz) -- without this node nothing in THIS test would fail if
    # the rail dropped the quiz marker at the RENDER layer entirely.
    quiz = ContentNodeFactory(course=course, unit_type="quiz", title="A quiz")
    client.force_login(student)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": req.pk})
    )
    soup = BeautifulSoup(resp.content.decode(), "html.parser")
    rail = soup.select_one("[data-unit-tree-list]")

    def row(node):
        return rail.select_one(f'a.unit-tree__unit[href$="/{node.pk}/"]')

    marked = row(add)
    kind = marked.select_one(".unit-kind")
    assert kind is not None
    assert "Additional" in kind.get_text()  # substring, not full-name equality:
    # the ✓ leads in the rail and trails in the outline, so the two orders differ.
    assert (
        f"unit-kind--{MARKER_ADDITIONAL}" in kind["class"]
    )  # modifier vs the constant
    assert kind["lang"] == "en"  # UI locale inside lang="{{ course.language }}"
    assert marked.find_all(recursive=False)[-1] is kind, (
        "the icon must be the LAST child"
    )

    quiz_kind = row(quiz).select_one(".unit-kind")
    assert quiz_kind is not None  # quiz marked at the RENDER layer too
    assert f"unit-kind--{MARKER_QUIZ}" in quiz_kind["class"]

    assert row(req).select_one(".unit-kind") is None  # required stays unmarked
