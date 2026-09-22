"""(course, glance) pairs for the dashboard's "My learning" and My courses.

Lives outside courses.rollups on purpose: rollups imports no access-layer code, and
choosing `drafts` needs can_see_drafts.
"""

from courses.access import can_see_drafts
from courses.models import Course
from courses.rollups import course_glance_or_unknown


def enrolled_course_glances(user):
    """Every course `user` is enrolled in, by title, paired with its glance.

    drafts is chosen exactly as course_outline / course_results choose it, so the
    bars, the outline and My results never disagree.
    """
    courses = Course.objects.filter(enrollments__student=user).order_by("title")
    return [
        (
            course,
            course_glance_or_unknown(
                course,
                user,
                drafts="keep" if can_see_drafts(user, course) else "hide",
            ),
        )
        for course in courses
    ]
