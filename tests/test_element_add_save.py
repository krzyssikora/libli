import pytest
from django.urls import reverse

from courses.element_forms import FORM_FOR_TYPE
from courses.models import Element
from courses.models import MathElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import MediaAssetFactory
from tests.factories import make_pa


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
        data={"url": "https://www.youtube.com/embed/lk5_OSsawz4", "media": asset.pk},
        course=course,
    ).is_valid()  # both
    assert Form(
        data={"url": "https://www.youtube.com/embed/lk5_OSsawz4"}, course=course
    ).is_valid()  # one


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


@pytest.mark.django_db
def test_add_is_render_only_no_row(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "text", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert Element.objects.filter(unit=unit).count() == 0  # nothing persisted


@pytest.mark.django_db
def test_first_save_materialises_text_element(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "text",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "body": "<p>Hi <script>x</script></p>",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert isinstance(el.content_object, TextElement)
    assert "<script>" not in el.content_object.body  # sanitised on save


@pytest.mark.django_db
def test_save_math_empty_is_422(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "math",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "latex": "",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    assert Element.objects.filter(unit=unit).count() == 0


@pytest.mark.django_db
def test_save_stale_token_is_409(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "math",
            "element": "new",
            "unit": unit.pk,
            "unit_token": "2000-01-01T00:00:00+00:00",
            "latex": "x^2",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 409
    assert Element.objects.filter(unit=unit).count() == 0


@pytest.mark.django_db
def test_update_existing_element(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    from tests.factories import add_element

    el = add_element(unit, MathElement.objects.create(latex="a"))
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "math",
            "element": el.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "latex": "b",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el.content_object.refresh_from_db()
    assert el.content_object.latex == "b"


@pytest.mark.django_db
def test_element_form_returns_existing_values(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    from tests.factories import add_element

    el = add_element(unit, MathElement.objects.create(latex="x^2"))
    resp = client.get(
        reverse(
            "courses:manage_element_form",
            kwargs={"slug": course.slug, "pk": el.pk},
        ),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b"x^2" in resp.content  # existing latex populated in the edit form (DoD #3)
