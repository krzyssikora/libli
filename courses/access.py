from django.http import Http404
from django.shortcuts import get_object_or_404

from courses.models import ContentNode
from courses.models import Enrollment


def is_enrolled(user, course):
    return Enrollment.objects.filter(student=user, course=course).exists()


def can_access_course(user, course):
    """Enrolled OR staff OR (course has an owner AND it is this user)."""
    if is_enrolled(user, course):
        return True
    if user.is_staff:
        return True
    return course.owner_id is not None and course.owner_id == user.id


def can_manage_course(user, course):
    """Authoring access (1b-i): the course owner, OR anyone holding the
    `courses.change_course` model perm (the Platform Admin group). Deliberately
    does NOT key on `is_staff` — see the spec's Foundational #3."""
    if course.owner_id is not None and course.owner_id == user.id:
        return True
    return user.has_perm("courses.change_course")


def get_node_or_404(node_pk, slug, *, require_unit=False, require_lesson=False):
    """Resolve a node and enforce object scoping. 404 (never 403) on any mismatch.

    Order: exists -> slug match -> kind/unit_type. Access (403) is checked by the
    caller AFTER this returns, so a foreign node always 404s before any 403.
    """
    node = get_object_or_404(ContentNode.objects.select_related("course"), pk=node_pk)
    if node.course.slug != slug:
        raise Http404("node does not belong to this course")
    if require_unit and node.kind != ContentNode.Kind.UNIT:
        raise Http404("not a unit")
    if require_lesson and node.unit_type != ContentNode.UnitType.LESSON:
        raise Http404("not a lesson unit")
    return node
