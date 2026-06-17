import pytest
from django.urls import reverse

from tests.factories import CourseFactory
from tests.factories import MediaAssetFactory
from tests.factories import make_pa


@pytest.mark.django_db
def test_picker_filters_by_kind_and_course(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    MediaAssetFactory(course=course, kind="image", original_filename="pic.png")
    MediaAssetFactory(course=course, kind="video", original_filename="clip.mp4")
    MediaAssetFactory(
        course=CourseFactory(), kind="image", original_filename="foreign.png"
    )
    resp = client.get(
        reverse("courses:manage_media_picker", kwargs={"slug": course.slug})
        + "?kind=image"
    )
    assert resp.status_code == 200
    assert b"pic.png" in resp.content
    assert b"clip.mp4" not in resp.content  # wrong kind
    assert b"foreign.png" not in resp.content  # wrong course
