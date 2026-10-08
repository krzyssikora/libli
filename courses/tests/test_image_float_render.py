import pytest

from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _img(size, flag):
    course, _u = make_course_with_unit()
    media = MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x.png", original_filename="x.png"
    )
    return ImageElement.objects.create(media=media, size=size, float_right=flag)


@pytest.mark.parametrize("size", ["small", "medium", "large", "full"])
@pytest.mark.parametrize("flag", [True, False])
def test_class_only_when_the_image_floats(size, flag):
    html = _img(size, flag).render()
    assert ("el--image--float" in html) is (flag and size == "small")


CONTAINER_KINDS = ["callout", "tabs", "twocolumn", "spoiler", "beforeafter"]


def _nest(unit, kind, child):
    """Put `child` inside a fresh container of `kind` at the top of `unit`."""
    from courses.models import BeforeAfterElement
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from courses.models import TwoColumnElement
    from tests.factories import add_element

    if kind == "callout":
        obj, slot = CalloutElement.objects.create(kind="note"), CalloutElement.SLOT_ID
    elif kind == "spoiler":
        obj, slot = SpoilerElement.objects.create(label="s"), SpoilerElement.SLOT_ID
    elif kind == "beforeafter":
        obj, slot = BeforeAfterElement.objects.create(), BeforeAfterElement.BEFORE_SLOT_ID
    elif kind == "tabs":
        obj = TabsElement.objects.create(data=TabsElement.default_data())
        slot = obj.data["tabs"][0]["id"]  # read off the SAVED instance
    else:
        obj = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
        slot = obj.data["columns"][0]["id"]
    join = add_element(unit, obj)
    Element.objects.create(unit=unit, content_object=child, parent=join, tab_id=slot)


@pytest.mark.parametrize("unit_type", ["lesson", "quiz"])
@pytest.mark.parametrize("where", ["top"] + CONTAINER_KINDS)
def test_class_reaches_the_page_in_every_context(client, unit_type, where):
    from tests.factories import add_element

    course, unit = make_course_with_unit()
    unit.unit_type = unit_type
    unit.save()
    media = MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x.png", original_filename="x.png"
    )
    flagged = ImageElement.objects.create(media=media, size="small", float_right=True)
    if where == "top":
        add_element(unit, flagged)
    else:
        _nest(unit, where, flagged)
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_verified_user

    # VERIFIED email: allauth's mandatory verification would otherwise redirect
    # (tests/factories.py::make_login). READ access keys on is_staff.
    staff = make_verified_user(
        username="staff-fl", email="staff-fl@t.example.com", password=TEST_PASSWORD
    )
    staff.is_staff = True
    staff.save()
    client.force_login(staff)
    path = f"/courses/{course.slug}/u/{unit.pk}/" + ("quiz/" if unit_type == "quiz" else "")
    resp = client.get(path)
    assert resp.status_code == 200, resp.status_code
    html = resp.content.decode()
    assert html.count("el--image--float") == 1, where
