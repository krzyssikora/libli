import pytest
from django.test import override_settings

from demo import errors


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_frontier_part_zero_is_honoured_not_treated_as_falsy():
    """T21 — part 0 is a legal AND falsy value, so `if frontier_part:` silently
    turns --frontier-part 0 into the 0.75 fraction."""
    from demo.content import build_course_plan
    from demo.generator import frontier_index
    from tests.demo.fixtures import small_course

    course = small_course()
    plan = build_course_plan(course)

    part_zero = frontier_index(plan, 0, course)
    default = frontier_index(plan, None, course)
    assert part_zero != default, "part 0 must not collapse to the fraction"

    # BOTH ends of the range. -1 is the one that used to slip through: it is a
    # legal int, it is < len(parts), and parts[-1] silently selects the LAST
    # part before the DB rejects the negative on write.
    for bad in (99, -1):
        with pytest.raises(errors.InvalidFrontierPart) as exc:
            frontier_index(plan, bad, course)
        assert exc.value.field == "frontier_part"  # it subclasses InvalidBounds


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_degenerate_labels_produce_usable_identifiers():
    """T17b — four boundaries §4.2 specifies, each producing user-visible
    identifiers on prod. ⚠️ The label must NOT be Polish: slugify transliterates
    diacritics (Łódź -> odz), so a Polish label never exercises the fallback."""
    from demo.services import provision_kit
    from tests.demo.fixtures import small_course

    course = small_course()

    kit = provision_kit("###", course=course, days=14, pupils=5, seed=1).kit
    assert kit.slug == "demo"
    assert not kit.teacher.username.startswith("-")

    with pytest.raises(errors.InvalidLabel):
        provision_kit("x" * 250, course=course, days=14, pupils=5, seed=1)

    long_label = "y" * 200
    kit2 = provision_kit(long_label, course=course, days=14, pupils=5, seed=1).kit
    assert len(kit2.group.name) <= 200
    assert len(kit2.teacher.display_name) <= 150
    assert kit2.teacher.display_name != kit2.student.display_name

    kit3 = provision_kit("Padding", course=course, days=14, pupils=40, seed=1).kit
    pupils = kit3.users.exclude(pk__in=[kit3.teacher_id, kit3.student_id])
    widths = {len(u.username.rsplit("-p", 1)[1]) for u in pupils}
    assert widths == {2}, "pupil numbers pad to the width of --pupils"


def test_every_warning_kind_has_a_display_string():
    """T29 — a missing entry is a KeyError, or an untranslated cell in a panel
    PR 3 requires to be fully translated."""
    from demo.warnings import DISPLAY
    from demo.warnings import KINDS

    assert set(DISPLAY) == KINDS
    for kind in KINDS:
        assert str(DISPLAY[kind]).strip()


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_generator_never_rewrites_an_existing_timestamp():
    """T18 — Q1 is resolved: there is no back-dating, so a reinstated queryset
    update with no student filter would rewrite a real pupil's completed_at
    while adding NO rows, passing every count-based assertion."""
    from courses.models import Enrollment
    from courses.models import UnitProgress
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test
    from tests.factories import make_verified_user

    course = small_course()
    outsider = make_verified_user(username="real2", email="real2@example.com")
    Enrollment.objects.create(student=outsider, course=course)
    unit = course.nodes.filter(unit_type="lesson").first()
    progress = UnitProgress.objects.create(student=outsider, unit=unit, completed=True)
    stamped = UnitProgress.objects.get(pk=progress.pk).completed_at

    provision_for_test(course)

    assert UnitProgress.objects.get(pk=progress.pk).completed_at == stamped
