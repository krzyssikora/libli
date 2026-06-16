import pytest

from courses.element_forms import FORM_FOR_TYPE
from tests.factories import CourseFactory
from tests.factories import MediaAssetFactory


@pytest.mark.django_db
def test_iframe_form_rejects_non_whitelisted_domain():
    Form = FORM_FOR_TYPE["iframe"]
    form = Form(data={"url": "https://evil.example.com/x", "title": "t"})
    assert not form.is_valid()


@pytest.mark.django_db
def test_image_form_requires_media():
    Form = FORM_FOR_TYPE["image"]
    course = CourseFactory()
    form = Form(data={"alt": "a", "figcaption": ""}, course=course)
    assert not form.is_valid()
    assert "media" in form.errors


@pytest.mark.django_db
def test_image_form_rejects_cross_course_or_wrong_kind_media():
    Form = FORM_FOR_TYPE["image"]
    course = CourseFactory()
    foreign = MediaAssetFactory(course=CourseFactory(), kind="image")
    wrong_kind = MediaAssetFactory(course=course, kind="video")
    assert not Form(data={"media": foreign.pk, "alt": ""}, course=course).is_valid()
    assert not Form(data={"media": wrong_kind.pk, "alt": ""}, course=course).is_valid()


@pytest.mark.django_db
def test_video_form_xor():
    Form = FORM_FOR_TYPE["video"]
    course = CourseFactory()
    asset = MediaAssetFactory(course=course, kind="video")
    assert not Form(data={}, course=course).is_valid()  # neither
    assert not Form(
        data={"url": "https://www.youtube.com/embed/x", "media": asset.pk},
        course=course,
    ).is_valid()  # both
    assert Form(
        data={"url": "https://www.youtube.com/embed/x"}, course=course
    ).is_valid()  # one
