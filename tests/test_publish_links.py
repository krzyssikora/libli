import pytest
from django.urls import reverse

from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _text(body):
    """A saved TextElement -- there is no TextElementFactory; mirrors
    tests/test_link_transfer.py's _text helper. save() sanitises the body,
    but a relative href to a node permalink URL passes through untouched
    (test_sanitiser_passes_internal_links_through_untouched)."""
    obj = TextElement(body=body)
    obj.save()
    return obj


def test_draft_link_renders_identically_and_404s_for_the_student(client):
    """LNK1. A content link to a draft unit is NOT suppressed at render time:
    it appears in the rendered host page for author and student alike, byte-
    identical, and only 404s when the STUDENT (not the author) follows it.

    Pins spec §7's decision -- "renders normally and 404s on click" -- so a
    later "helpful" suppression of links to drafts is a deliberate change,
    not a silent regression this suite fails to catch.
    """
    author = make_login(client, "publink-author")
    course = CourseFactory(owner=author)
    draft = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Draft target",
        published=False,
    )
    host = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Host",
        published=True,
    )
    anchor = f'<a href="/courses/n/{draft.pk}/">see the draft</a>'
    add_element(host, _text(anchor))

    host_url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": host.pk}
    )
    permalink_url = reverse("courses:node_permalink", kwargs={"node_pk": draft.pk})

    # Author: the link renders in the host page, and following it resolves --
    # the permalink redirects the author straight into the draft unit.
    author_resp = client.get(host_url)
    assert author_resp.status_code == 200
    assert anchor in author_resp.content.decode()
    assert client.get(permalink_url).status_code == 302

    # Student: the SAME markup renders (not suppressed, not altered) --
    # but following it 404s, never a silent redirect or a 403 that would
    # turn the permalink into a node-existence oracle.
    student = make_login(client, "publink-student")
    EnrollmentFactory(student=student, course=course)
    student_resp = client.get(host_url)
    assert student_resp.status_code == 200
    assert anchor in student_resp.content.decode()
    assert client.get(permalink_url).status_code == 404
