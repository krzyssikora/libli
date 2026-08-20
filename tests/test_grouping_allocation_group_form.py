import re

import pytest
from django.contrib.auth.models import Group as AuthGroup

from grouping.forms import GroupForm
from grouping.models import Allocation
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import seed_roles
from tests.factories import AllocationFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _role_user(role_name, username):
    seed_roles()
    user = UserFactory(username=username)
    user.groups.add(AuthGroup.objects.get(name=role_name))
    # Same shape as tests/factories.py::_make_role — a freshly created user has
    # never had has_perm() called on it, so these attributes do not exist yet and
    # a bare `del` would AttributeError before any assertion runs.
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


def test_constructs_without_a_user_and_offers_no_allocations():
    """Four existing call sites construct GroupForm WITHOUT a `user` kwarg (two
    with no kwargs at all), one of them in another app
    (integrations/tests/test_form_fields.py:40)."""
    AllocationFactory()
    form = GroupForm()
    assert list(form.fields["allocation"].queryset) == []


def test_create_form_excludes_allocations_on_unmanageable_courses():
    """Setup is load-bearing: NO instance, or the edit branch is taken and the
    mutant survives."""
    ca = _role_user(COURSE_ADMIN, "ca_gf")
    mine = AllocationFactory(course=CourseFactory(owner=ca))
    theirs = AllocationFactory()
    form = GroupForm(user=ca)
    pks = set(form.fields["allocation"].queryset.values_list("pk", flat=True))
    assert mine.pk in pks
    assert theirs.pk not in pks


def test_edit_form_scopes_allocations_to_the_groups_own_course():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_edit")
    group = GroupFactory()
    same = AllocationFactory(course=group.course)
    other = AllocationFactory(course=CourseFactory())
    form = GroupForm(instance=group, user=pa)
    pks = set(form.fields["allocation"].queryset.values_list("pk", flat=True))
    assert same.pk in pks
    assert other.pk not in pks


def test_edit_form_keeps_its_own_archived_allocation_selectable():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_arch")
    a = AllocationFactory(archived=True)
    group = GroupFactory(course=a.course, allocation=a)
    form = GroupForm(instance=group, user=pa)
    assert a.pk in set(form.fields["allocation"].queryset.values_list("pk", flat=True))


def test_renaming_a_group_does_not_detach_its_archived_allocation():
    """Vacuity trap: under the mutant the POST is rejected as invalid_choice, so
    nothing saves and 'allocation_id unchanged' passes anyway. Assert the save
    SUCCEEDED and the rename LANDED."""
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_nodetach")
    a = AllocationFactory(archived=True)
    group = GroupFactory(course=a.course, allocation=a, name="7A")
    form = GroupForm(
        data={
            "name": "7A renamed",
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": a.pk,
            "new_allocation": "",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.name == "7A renamed"
    assert group.allocation_id == a.pk


def test_empty_choice_is_offered_and_detaches():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_none")
    a = AllocationFactory()
    group = GroupFactory(course=a.course, allocation=a)
    form = GroupForm(instance=group, user=pa)
    values = [value for value, label in form.fields["allocation"].choices]
    assert "" in [str(v) for v in values]
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation_id is None


def test_rendered_options_carry_data_course_and_optgroups():
    """Assert against the RENDERED widget, not field.choices: a late-assigned
    iterator leaves choices correct while the widget renders flat."""
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_render")
    a = AllocationFactory()
    form = GroupForm(user=pa)
    html = str(form["allocation"])
    assert "data-allocation-select" in html  # the hook the client filter keys on
    assert "<optgroup" in html
    assert f'data-course="{a.course_id}"' in html
    # The empty choice must carry no data-course (create_option skips it).
    # Parse the tag rather than matching a fixed attribute order — Django emits
    # `selected` before other attrs, so a prefix match would miss
    # `<option value="" selected data-course="3">`.
    empty = re.search(r'<option value=""[^>]*>', html)
    assert empty is not None
    assert "data-course" not in empty.group(0)


def test_archived_allocation_option_is_labelled():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_label")
    a = AllocationFactory(archived=True, name="Stare klasy")
    group = GroupFactory(course=a.course, allocation=a)
    form = GroupForm(instance=group, user=pa)
    html = str(form["allocation"])
    assert "Stare klasy" in html
    assert "archived" in html.lower()


def test_picking_an_existing_allocation_writes_it():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_pick")
    group = GroupFactory()
    a = AllocationFactory(course=group.course)
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": a.pk,
            "new_allocation": "",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation_id == a.pk


def test_typing_a_new_allocation_creates_and_attaches_it():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_new")
    group = GroupFactory()
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "matematyka 2026",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation.name == "matematyka 2026"


def test_new_name_reuses_an_existing_row_case_insensitively():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_reuse")
    group = GroupFactory()
    existing = AllocationFactory(course=group.course, name="Klasy")
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "klasy",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation_id == existing.pk
    assert Allocation.objects.filter(course=group.course).count() == 1


def test_new_name_matching_an_archived_row_is_a_field_error():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_newarch")
    group = GroupFactory()
    AllocationFactory(course=group.course, name="Klasy", archived=True)
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "klasy",
        },
        instance=group,
        user=pa,
    )
    assert not form.is_valid()
    assert "new_allocation" in form.errors


def test_new_allocation_longer_than_200_chars_is_a_field_error():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_long")
    group = GroupFactory()
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "x" * 201,
        },
        instance=group,
        user=pa,
    )
    assert not form.is_valid()
    assert "new_allocation" in form.errors


def test_typing_a_new_name_on_an_already_allocated_group_moves_it():
    """The select ECHOES the current allocation (it is a Meta field), so a naive
    'both are non-empty' conflict test would reject the natural way to move a
    group. And without cleaned_data['allocation'] = None the save() fallback
    resolves to the OLD allocation and the group silently stays put."""
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_move")
    old = AllocationFactory(name="stara")
    group = GroupFactory(course=old.course, allocation=old)
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": old.pk,  # the browser always echoes this back
            "new_allocation": "nowa",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation.name == "nowa"


def test_clearing_the_select_and_typing_a_new_name_also_moves_it():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_move2")
    old = AllocationFactory(name="stara")
    group = GroupFactory(course=old.course, allocation=old)
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "nowa",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation.name == "nowa"


def test_picking_a_different_existing_allocation_and_typing_is_a_conflict():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_both")
    old = AllocationFactory(name="stara")
    group = GroupFactory(course=old.course, allocation=old)
    other = AllocationFactory(course=old.course, name="inna")
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": other.pk,
            "new_allocation": "nowa",
        },
        instance=group,
        user=pa,
    )
    assert not form.is_valid()
    assert "new_allocation" in form.errors


def test_allocation_on_another_course_is_a_field_error_on_the_create_path():
    """Setup is load-bearing: CREATE path as a PA, so the foreign allocation is
    genuinely inside the field queryset and only clean() can reject it."""
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_cross")
    course = CourseFactory()
    foreign = AllocationFactory(course=CourseFactory())
    form = GroupForm(
        data={
            "name": "7A",
            "course": course.pk,
            "teachers": [],
            "external_id": "",
            "allocation": foreign.pk,
            "new_allocation": "",
        },
        user=pa,
    )
    assert not form.is_valid()
    assert "allocation" in form.errors


def test_a_failing_group_save_leaves_no_orphan_allocation(client, monkeypatch):
    """The atomic wrapper is the ONLY thing preventing an orphan Allocation when
    the group save fails after the allocation was created."""
    from django.urls import reverse

    from grouping.models import Group
    from tests.factories import make_pa

    pa = make_pa(client)
    course = CourseFactory(owner=pa)

    def boom(self, *args, **kwargs):
        raise RuntimeError("group save failed")

    monkeypatch.setattr(Group, "save", boom)
    with pytest.raises(RuntimeError):
        client.post(
            reverse("grouping:group_create"),
            {
                "name": "7A",
                "course": course.pk,
                "teachers": [],
                "external_id": "",
                "allocation": "",
                "new_allocation": "matematyka 2026",
            },
        )
    assert Allocation.objects.count() == 0
