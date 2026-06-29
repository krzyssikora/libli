from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import ROLE_CHOICES
from institution.roles import ROLE_LABELS
from institution.roles import ROLE_NAMES
from institution.roles import STUDENT
from institution.roles import TEACHER
from institution.roles import role_is_staff


def test_role_is_staff_only_student_is_non_staff():
    assert role_is_staff(STUDENT) is False
    assert role_is_staff(TEACHER) is True
    assert role_is_staff(COURSE_ADMIN) is True
    assert role_is_staff(PLATFORM_ADMIN) is True


def test_role_choices_values_are_exact_group_names():
    values = [value for value, _label in ROLE_CHOICES]
    assert values == ROLE_NAMES  # exact Group-name strings, in order


def test_role_labels_cover_all_four_roles():
    assert set(ROLE_LABELS) == set(ROLE_NAMES)


def test_role_choices_labels_come_from_role_labels():
    for value, label in ROLE_CHOICES:
        assert label == ROLE_LABELS[value]
