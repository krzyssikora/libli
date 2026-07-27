import pytest

from courses.builder_open import container_pks
from courses.builder_open import open_ids
from courses.views_manage import _children_map
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory


def _req(rf, query="", post=None, session=None):
    r = rf.post("/", data=post) if post is not None else rf.get(f"/?{query}")
    r.session = session if session is not None else {}
    return r


@pytest.fixture
def tree(db):
    """part > chapter > unit, plus a childless chapter (the `pk in cmap` trap).

    4 nodes, i.e. UNDER SIZE_THRESHOLD -- so on a page load this course takes
    precedence step 4 and opens fully. Use `big_tree` for anything that must
    reach step 5.
    """
    course = CourseFactory(slug="c1")
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=part, title="C")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    empty = ContentNodeFactory(course=course, kind="chapter", parent=part, title="E")
    return course, part, chapter, unit, empty


@pytest.fixture
def big_tree(db, monkeypatch):
    """The same shape, but forced OVER the threshold so steps 5/6 are reachable.

    Monkeypatching the constant beats seeding 151 rows: the rule under test is
    "len(index) <= SIZE_THRESHOLD", and a 4-node fixture with a threshold of 2
    exercises it identically at a fraction of the cost.
    """
    monkeypatch.setattr("courses.builder_open.SIZE_THRESHOLD", 2)
    course = CourseFactory(slug="c2big")
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=part, title="C")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    empty = ContentNodeFactory(course=course, kind="chapter", parent=part, title="E")
    return course, part, chapter, unit, empty


@pytest.mark.django_db
def test_childless_container_is_a_valid_open_pk(rf, tree):
    """`empty` is never a KEY in cmap -- a `pk in cmap` test would discard it."""
    course, _part, _ch, _unit, empty = tree
    cmap = _children_map(course)
    assert empty.pk in container_pks(cmap)
    result = open_ids(_req(rf, f"open={empty.pk}"), course, cmap)
    assert result.ids == frozenset({empty.pk})


@pytest.mark.django_db
def test_unit_pk_and_junk_and_foreign_pk_are_discarded(rf, tree):
    course, part, _ch, unit, _e = tree
    other = ContentNodeFactory(
        course=CourseFactory(slug="c2"), kind="part", parent=None
    )
    cmap = _children_map(course)
    q = f"open={part.pk},{unit.pk},{other.pk},abc,"
    assert open_ids(_req(rf, q), course, cmap).ids == frozenset({part.pk})


@pytest.mark.django_db
def test_absent_vs_empty_on_a_page_load(rf, big_tree):
    """Absent seeds from the session; empty means 'I collapsed everything'.

    big_tree, not tree: under the threshold step 4 fires first and this would
    assert the size rule while claiming to test the seed.
    """
    course, part, chapter, unit, _e = big_tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c2big": unit.pk}}
    absent = open_ids(_req(rf, "", session=sess), course, cmap, mode="page")
    assert absent.ids == frozenset({part.pk, chapter.pk})
    empty = open_ids(_req(rf, "open=", session=sess), course, cmap, mode="page")
    assert empty.ids == frozenset()


@pytest.mark.django_db
def test_seed_includes_the_node_itself_when_it_is_a_container(rf, big_tree):
    course, part, chapter, _u, _e = big_tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c2big": chapter.pk}}
    got = open_ids(_req(rf, "", session=sess), course, cmap, mode="page")
    # the chapter ITSELF, not just its ancestors -- otherwise the author
    # returns with the very chapter they were working in closed
    assert got.ids == frozenset({part.pk, chapter.pk})


@pytest.mark.django_db
def test_fragment_mode_never_seeds_and_skips_the_size_rule(rf, tree):
    """`tree` deliberately: 4 nodes IS under the threshold, and a fragment
    must still come back empty -- step 4 is a landing rule for a page."""
    course, _p, _c, unit, _e = tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c1": unit.pk}}
    got = open_ids(_req(rf, "", session=sess), course, cmap, mode="fragment")
    assert got.ids == frozenset()


@pytest.mark.django_db
def test_small_course_opens_everything_before_consulting_the_seed(rf, tree):
    course, part, chapter, unit, empty = tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c1": unit.pk}}
    got = open_ids(_req(rf, "", session=sess), course, cmap, mode="page")
    assert got.ids == frozenset({part.pk, chapter.pk, empty.pk})


@pytest.mark.django_db
def test_open_session_sentinel_reads_then_falls_through_when_missing(rf, tree):
    course, part, chapter, _u, empty = tree
    cmap = _children_map(course)
    stored = {"builder_open": {"c1": [chapter.pk]}}
    got = open_ids(_req(rf, "open=session", session=stored), course, cmap, mode="page")
    assert got.ids == frozenset({chapter.pk})
    # MISSING key -> fall through to steps 3-6 (here: the size rule)
    got2 = open_ids(_req(rf, "open=session", session={}), course, cmap, mode="page")
    assert got2.ids == frozenset({part.pk, chapter.pk, empty.pk})


@pytest.mark.django_db
def test_open_session_honours_a_stored_EMPTY_list(rf, tree):
    """Stored-empty is 'I collapsed everything' and must NOT fall through.

    `.get(slug) or []` conflates missing with empty: the author's collapsed
    state would spring back open on the next no-JS mutation, and the derived
    set would then be persisted over it -- permanently.
    """
    course, _p, _c, _u, _e = tree
    cmap = _children_map(course)
    stored = {"builder_open": {"c1": []}}
    got = open_ids(_req(rf, "open=session", session=stored), course, cmap, mode="page")
    assert got.ids == frozenset()


@pytest.mark.django_db
def test_post_open_beats_get_open(rf, tree):
    course, part, chapter, _u, _e = tree
    cmap = _children_map(course)
    r = rf.post("/?open=" + str(part.pk), data={"open": str(chapter.pk)})
    r.session = {}
    assert open_ids(r, course, cmap).ids == frozenset({chapter.pk})


@pytest.mark.django_db
def test_ceiling_keeps_the_lowest_pks_and_flags_truncation(rf, db, monkeypatch):
    """Monkeypatch the ceiling rather than seeding 505 rows: the rule under
    test is `len(kept) > CEILING`, and 6 rows exercise it identically."""
    monkeypatch.setattr("courses.builder_open.CEILING", 4)
    course = CourseFactory(slug="ceil")
    parts = [
        ContentNodeFactory(course=course, kind="part", parent=None, title=f"p{i}")
        for i in range(6)
    ]
    cmap = _children_map(course)
    got = open_ids(_req(rf, "open=all"), course, cmap, mode="page")
    assert got.truncated is True
    assert len(got.ids) == 4
    assert got.ids == frozenset(sorted(p.pk for p in parts)[:4])


@pytest.mark.django_db
def test_stale_session_pk_is_discarded(rf, big_tree):
    """big_tree, so step 4 does not answer before step 5 is ever reached.

    With `tree` the size rule returns every container without calling _chain
    at all, so deleting _chain's None-guard would leave this green.
    """
    course, _p, _c, _u, _e = big_tree
    cmap = _children_map(course)
    sess = {"builder_last_node": {"c2big": 9_999_999}}
    got = open_ids(_req(rf, "", session=sess), course, cmap, mode="page")
    assert got.ids == frozenset()  # step 6, not a crash and not the size rule
