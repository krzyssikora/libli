import pytest
from django.template import Context
from django.template import Template

from accounts.invitations import build_accept_url
from accounts.invitations import send_invitation_email
from accounts.models import Invitation
from accounts.services import create_or_refresh_invitation
from accounts.services import resend_invitation
from institution.roles import STUDENT
from institution.roles import TEACHER
from tests.factories import CourseFactory
from tests.factories import GroupFactory

COURSE_LINE = "You have been invited to the course: "


def _body(mailoutbox):
    return mailoutbox[-1].body.replace("\r\n", "\n")


@pytest.mark.django_db
def test_no_group_body_unchanged(mailoutbox):
    inv = Invitation.objects.create(email="s@example.com")
    send_invitation_email(inv)
    expires = Template("{{ d }}").render(Context({"d": inv.expires_at}))
    expected = (
        "You have been invited to join libli.\n"
        "\n"
        "To create your account, open this link:\n"
        "\n"
        f"{build_accept_url(inv)}\n"
        "\n"
        f"This invitation expires on {expires}.\n"
    )
    assert _body(mailoutbox) == expected


@pytest.mark.django_db
def test_email_names_course_when_group_set(
    django_capture_on_commit_callbacks, mailoutbox
):
    g = GroupFactory()
    with django_capture_on_commit_callbacks(execute=True):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g
        )
    assert f"{COURSE_LINE}{g.course.title}." in _body(mailoutbox)


@pytest.mark.django_db
def test_email_has_no_course_line_without_group(
    django_capture_on_commit_callbacks, mailoutbox
):
    with django_capture_on_commit_callbacks(execute=True):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None
        )
    assert COURSE_LINE not in _body(mailoutbox)


@pytest.mark.django_db
def test_email_unescapes_title(django_capture_on_commit_callbacks, mailoutbox):
    title = "Matma & fizyka 'plus'"
    g = GroupFactory(course=CourseFactory(title=title))
    with django_capture_on_commit_callbacks(execute=True):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g
        )
    body = _body(mailoutbox)
    assert f"{COURSE_LINE}{title}." in body
    assert "&amp;" not in body
    assert "&#x27;" not in body


@pytest.mark.django_db
def test_refresh_email_names_new_course(django_capture_on_commit_callbacks, mailoutbox):
    g1 = GroupFactory()
    g2 = GroupFactory()
    with django_capture_on_commit_callbacks(execute=True):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g1
        )
    create_or_refresh_invitation(
        email="s@example.com", role=STUDENT, invited_by=None, group=g2
    )
    body = _body(mailoutbox)
    assert f"{COURSE_LINE}{g2.course.title}." in body
    assert g1.course.title not in body


@pytest.mark.django_db
def test_refresh_email_drops_line_when_cleared(
    django_capture_on_commit_callbacks, mailoutbox
):
    g = GroupFactory()
    with django_capture_on_commit_callbacks(execute=True):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g
        )
    create_or_refresh_invitation(
        email="s@example.com", role=STUDENT, invited_by=None, group=None
    )
    assert COURSE_LINE not in _body(mailoutbox)


@pytest.mark.django_db
def test_resend_after_archive_has_no_course_line(
    django_capture_on_commit_callbacks, mailoutbox
):
    g = GroupFactory()
    with django_capture_on_commit_callbacks(execute=True):
        inv, _ = create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g
        )
    g.archived = True
    g.save()
    inv.refresh_from_db()
    resend_invitation(inv)
    assert COURSE_LINE not in _body(mailoutbox)


@pytest.mark.django_db
def test_non_student_row_has_no_course_line(mailoutbox):
    g = GroupFactory()
    inv = Invitation.objects.create(email="t@example.com", role=TEACHER, group=g)
    mailoutbox.clear()
    send_invitation_email(inv)
    assert COURSE_LINE not in _body(mailoutbox)


@pytest.mark.django_db
def test_refresh_to_teacher_email_has_no_course_line(
    django_capture_on_commit_callbacks, mailoutbox
):
    g = GroupFactory()
    with django_capture_on_commit_callbacks(execute=True):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g
        )
    create_or_refresh_invitation(email="s@example.com", role=TEACHER, invited_by=None)
    assert COURSE_LINE not in _body(mailoutbox)
