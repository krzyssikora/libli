import pytest
from django.core.exceptions import ValidationError
from django.http import Http404

from courses.models import Enrollment
from courses.rollups import build_outline
from tags import services
from tags.models import TAG_NAME_MAX_LEN
from tags.models import Tag
from tags.models import UnitTag
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import TagFactory
from tests.factories import UnitTagFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_normalize_name_collapses_whitespace():
    assert services.normalize_name("  to   do \n") == "to do"


def test_clean_name_rejects_empty():
    with pytest.raises(ValidationError):
        services._clean_name("   ")


def test_clean_name_rejects_over_length():
    with pytest.raises(ValidationError):
        services._clean_name("x" * (TAG_NAME_MAX_LEN + 1))


def test_reuse_or_create_is_case_insensitive():
    user = UserFactory()
    a = services._reuse_or_create_tag(user, "Exam")
    b = services._reuse_or_create_tag(user, "  exam ")
    assert a.pk == b.pk
    assert Tag.objects.filter(author=user).count() == 1


def test_rename_allows_recasing_own_name():
    tag = TagFactory(name="exam")
    services.rename_tag(tag.author, tag.pk, "Exam")
    tag.refresh_from_db()
    assert tag.name == "Exam"


def test_rename_rejects_collision_with_other_tag():
    user = UserFactory()
    TagFactory(author=user, name="exam")
    other = TagFactory(author=user, name="hard")
    with pytest.raises(ValidationError):
        services.rename_tag(user, other.pk, "EXAM")


def test_rename_preserves_colour():
    tag = TagFactory(name="exam", color="rose")
    services.rename_tag(tag.author, tag.pk, "exams")
    tag.refresh_from_db()
    assert tag.color == "rose"


def test_rename_foreign_tag_404():
    tag = TagFactory()
    with pytest.raises(Http404):
        services.rename_tag(UserFactory(), tag.pk, "x")


def test_recolor_rejects_invalid_key():
    tag = TagFactory()
    with pytest.raises(ValidationError):
        services.recolor_tag(tag.author, tag.pk, "not-a-colour")


def test_delete_tag_returns_accessible_count_then_cascades():
    user = UserFactory()
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course)
    tag = TagFactory(author=user)
    UnitTagFactory(tag=tag, unit=unit)
    n = services.delete_tag(user, tag.pk)
    assert n == 1
    assert not Tag.objects.filter(pk=tag.pk).exists()
    assert not UnitTag.objects.filter(tag_id=tag.pk).exists()


def test_list_tags_unit_count_excludes_inaccessible():
    user = UserFactory()
    reachable = CourseFactory()
    Enrollment.objects.create(student=user, course=reachable)
    unreachable = CourseFactory()
    tag = TagFactory(author=user, name="exam")
    UnitTagFactory(tag=tag, unit=ContentNodeFactory(course=reachable))
    UnitTagFactory(tag=tag, unit=ContentNodeFactory(course=unreachable))
    [t] = services.list_tags(user)
    assert t.unit_count == 1  # the inaccessible one is not counted


def test_tag_unit_is_idempotent():
    unit = ContentNodeFactory()
    user = UserFactory()
    services.tag_unit(user, unit, "exam")
    services.tag_unit(user, unit, "Exam")  # same tag, same unit
    assert UnitTag.objects.filter(unit=unit, tag__author=user).count() == 1


def test_tag_unit_allows_quiz_unit():
    quiz = ContentNodeFactory(unit_type="quiz")
    user = UserFactory()
    services.tag_unit(user, quiz, "revise")
    assert UnitTag.objects.filter(unit=quiz).count() == 1


def test_tag_unit_by_id_foreign_tag_404():
    foreign = TagFactory()
    with pytest.raises(Http404):
        services.tag_unit_by_id(UserFactory(), ContentNodeFactory(), foreign.pk)


def test_untag_unit_is_idempotent_and_keeps_unused_tag():
    unit = ContentNodeFactory()
    user = UserFactory()
    ut = services.tag_unit(user, unit, "exam")
    services.untag_unit(user, unit, ut.tag_id)
    services.untag_unit(user, unit, ut.tag_id)  # no error second time
    assert not UnitTag.objects.filter(unit=unit).exists()
    assert Tag.objects.filter(pk=ut.tag_id).exists()  # tag survives


def test_untag_unit_foreign_tag_404():
    foreign = TagFactory()
    with pytest.raises(Http404):
        services.untag_unit(UserFactory(), ContentNodeFactory(), foreign.pk)


def test_tags_for_unit_ordered_case_insensitive():
    unit = ContentNodeFactory()
    user = UserFactory()
    services.tag_unit(user, unit, "Zebra")
    services.tag_unit(user, unit, "apple")
    assert [t.name for t in services.tags_for_unit(user, unit)] == ["apple", "Zebra"]


def test_outline_with_tags_empty_active_hides_nothing():
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", unit_type=None)
    ContentNodeFactory(course=course, parent=part, unit_type="lesson")
    user = UserFactory()
    by_unit, _ = services.tags_for_outline(user, course)
    outline = services.outline_with_tags(build_outline(course, user), by_unit, [])
    assert outline[0]["tag_hidden"] is False
    assert outline[0]["children"][0]["tag_hidden"] is False


def test_outline_with_tags_prunes_unmatched_and_empty_ancestors():
    course = CourseFactory()
    user = UserFactory()
    p1 = ContentNodeFactory(course=course, kind="part", unit_type=None)
    u_match = ContentNodeFactory(course=course, parent=p1, unit_type="lesson")
    p2 = ContentNodeFactory(course=course, kind="part", unit_type=None)
    ContentNodeFactory(course=course, parent=p2, unit_type="lesson")  # no tag
    exam = services.tag_unit(user, u_match, "exam").tag
    by_unit, _ = services.tags_for_outline(user, course)
    outline = services.outline_with_tags(
        build_outline(course, user), by_unit, [exam.pk]
    )
    nodes = {d["node"].pk: d for d in outline}
    assert nodes[p1.pk]["tag_hidden"] is False  # has a matching descendant
    assert nodes[p1.pk]["children"][0]["tag_hidden"] is False
    assert nodes[p2.pk]["tag_hidden"] is True  # no matching descendant


def test_filter_chip_hrefs_toggle():
    user = UserFactory()
    t1 = TagFactory(author=user, name="exam")
    t2 = TagFactory(author=user, name="hard")
    chips = services.filter_chip_hrefs("/c/x/", [t1, t2], [t1.pk])
    by_tag = {c["tag"].pk: c for c in chips}
    assert by_tag[t1.pk]["active"] is True
    assert by_tag[t1.pk]["href"] == "/c/x/"  # active → clears itself
    assert f"tags={t1.pk}" in by_tag[t2.pk]["href"]
    assert f"tags={t2.pk}" in by_tag[t2.pk]["href"]  # inactive → adds itself


def test_units_by_tag_groups_accessible_only_and_keeps_zero():
    user = UserFactory()
    reachable = CourseFactory(title="Bio")
    Enrollment.objects.create(student=user, course=reachable)
    unit = ContentNodeFactory(course=reachable)
    services.tag_unit(user, unit, "exam")
    TagFactory(author=user, name="later")  # zero units
    result = dict((t.name, grouped) for t, grouped in services.units_by_tag(user))
    assert list(result["exam"].keys())[0].pk == reachable.pk
    assert not result["later"]  # zero-unit tag retained, empty grouping


def test_units_by_tag_orders_units_by_outline_position():
    user = UserFactory()
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    p1 = ContentNodeFactory(course=course, kind="part", unit_type=None)
    p2 = ContentNodeFactory(course=course, kind="part", unit_type=None)
    # Units under different parents: per-parent `order` would interleave; pre-order
    # must yield p1's unit before p2's unit.
    first = ContentNodeFactory(course=course, parent=p1, unit_type="lesson", title="A")
    second = ContentNodeFactory(course=course, parent=p2, unit_type="lesson", title="B")
    services.tag_unit(user, second, "exam")
    services.tag_unit(user, first, "exam")
    [(tag, grouped)] = services.units_by_tag(user)
    titles = [u.title for u in grouped[course]]
    assert titles == ["A", "B"]  # outline order, not tag/insert order
