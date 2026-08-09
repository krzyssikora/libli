"""Enrollment and role-based access checks for courses and nodes (IDOR-safe)."""

from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404

from courses.models import ContentNode
from courses.models import Course
from courses.models import Enrollment


def is_enrolled(user, course):
    return Enrollment.objects.filter(student=user, course=course).exists()


def accessible_courses(user):
    """Courses `user` may access, as a queryset (single source of truth for
    can_access_course): staff/superuser ⇒ all; else owned ∪ enrolled ∪ taught
    (non-archived groups)."""
    if not user.is_authenticated:
        return Course.objects.none()
    if user.is_staff:
        return Course.objects.all()
    enrolled = Enrollment.objects.filter(student=user).values("course_id")
    return Course.objects.filter(
        Q(pk__in=enrolled)
        | Q(owner=user)
        | Q(groups__teachers=user, groups__archived=False)
    ).distinct()


def can_access_course(user, course):
    """Enrolled OR staff OR owner — delegates to accessible_courses (single source)."""
    return accessible_courses(user).filter(pk=course.pk).exists()


def can_manage_course(user, course):
    """Authoring access (1b-i): the course owner, OR anyone holding the
    `courses.change_course` model perm (the Platform Admin group). Deliberately
    does NOT key on `is_staff` — see the spec's Foundational #3."""
    if course.owner_id is not None and course.owner_id == user.id:
        return True
    return user.has_perm("courses.change_course")


def manageable_courses(user):
    """Courses `user` may AUTHOR, as a queryset — the counterpart of
    can_manage_course, which exists only as a per-object predicate.

    NOT accessible_courses: that is the read gate, and using it here would
    show drafts to every enrolled student.

    Two branches, mirroring can_manage_course's two disjuncts. The first is
    easy to miss: courses.change_course is a MODEL-level permission with no
    per-course row to filter on, so a Platform Admin's result is unfiltered.
    """
    if not user.is_authenticated:
        return Course.objects.none()
    if user.has_perm("courses.change_course"):
        return Course.objects.all()
    return Course.objects.filter(owner=user)


def exclude_foreign_drafts(qs, author, *, unit_field="unit"):
    """Drop drafted units the viewer may not author.

    A per-course condition inside the query, NOT a boolean: these hubs are
    cross-course (they take only `author` and select over accessible_courses),
    so there is no single course to hand to can_see_drafts — and a boolean
    could not express the answer anyway, since a user who manages course A
    but not B must keep A's drafts and lose B's in the SAME result set.

    The kind conjunct matters: excluding published=False alone would also drop
    rows attached to containers, whose published column is meaningless.
    """
    return qs.exclude(
        Q(**{f"{unit_field}__kind": "unit", f"{unit_field}__published": False})
        & ~Q(**{f"{unit_field}__course__in": manageable_courses(author)})
    )


def foreign_draft_q(author, unit_field="unit"):
    """The condition exclude_foreign_drafts negates, as a bare Q, for callers
    that must fold it into an annotation rather than an .exclude()."""
    return Q(**{f"{unit_field}__kind": "unit", f"{unit_field}__published": False}) & ~Q(
        **{f"{unit_field}__course__in": manageable_courses(author)}
    )


def can_see_drafts(user, course):
    """Draft units are visible only to authors — the course owner or a
    holder of courses.change_course.

    Deliberately NOT is_staff (which grants read access to every course) and
    NOT an assigned group teacher (who cannot fix what they can see).

    A thin alias over can_manage_course rather than a direct call at each
    site: the two answers are the same today but the questions are not, and
    a future "teachers may preview drafts" setting must have one home.
    """
    return can_manage_course(user, course)


def get_node_or_404(
    node_pk,
    slug,
    *,
    viewer=None,
    require_unit=False,
    require_lesson=False,
    require_quiz=False,
):
    """Resolve a node and enforce object scoping. 404 (never 403) on any mismatch.

    Order: exists -> slug match -> kind/unit_type -> published. Access (403)
    is checked by the caller AFTER this returns, so a foreign node always
    404s before any 403.

    `viewer=None` means "skip the publish check" — management views pass
    nothing. That makes the DEFAULT the insecure one, which is why
    tests/test_publish_viewer_scan.py exists.
    """
    node = get_object_or_404(ContentNode.objects.select_related("course"), pk=node_pk)
    if node.course.slug != slug:
        raise Http404("node does not belong to this course")
    if require_unit and node.kind != ContentNode.Kind.UNIT:
        raise Http404("not a unit")
    if require_lesson and node.unit_type != ContentNode.UnitType.LESSON:
        raise Http404("not a lesson unit")
    if require_quiz and node.unit_type != ContentNode.UnitType.QUIZ:
        raise Http404("not a quiz unit")
    # `kind == UNIT` is MANDATORY, not tidiness: every container row created
    # after migration 0057 carries published=False from the model default,
    # and a container's own flag must never decide visibility.
    if (
        viewer is not None
        and node.kind == ContentNode.Kind.UNIT
        and not node.published
        and not can_see_drafts(viewer, node.course)
    ):
        raise Http404("node is not published")
    return node
