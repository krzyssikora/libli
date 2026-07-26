"""Request-free context builders for the course consumption pages.

Mirrors tags/rendering.py and notes/rendering.py: a thin function a view merges
into its context and a test can call directly, with no request object involved.
"""

from django.urls import reverse

from courses.access import can_manage_course


def unit_edit_context(user, unit):
    """Context for the unit-page editor link: `can_edit_unit` plus the resolved URL.

    Callers pass an authenticated user and a UNIT ContentNode; every call site is
    @login_required and resolves its node with require_unit=True, so this does not
    defend against either. Behaviour on other inputs is unspecified.

    `can_edit_unit` is exactly the predicate courses.views_manage.editor enforces
    before serving the editor, so the link can never appear where following it
    would 403. That identity is PINNED, not merely claimed here: two rows in
    tests/test_unit_edit_link.py follow the URL and assert 200 for the owner and
    403 for the non-owning Course Admin.
    """
    can_edit = can_manage_course(user, unit.course)
    return {
        "can_edit_unit": can_edit,
        "unit_editor_url": (
            reverse(
                "courses:manage_editor",
                kwargs={"slug": unit.course.slug, "pk": unit.pk},
            )
            if can_edit
            else None
        ),
    }
