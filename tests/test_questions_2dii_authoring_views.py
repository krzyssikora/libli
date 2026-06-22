import pytest
from django.urls import reverse

from courses.models import ContentNode
from tests.factories import CourseFactory
from tests.factories import DragToImageQuestionElementFactory
from tests.factories import DragZoneFactory
from tests.factories import MediaAssetFactory
from tests.factories import add_element
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _quiz_unit(course):
    return ContentNode.objects.create(
        course=course, kind="unit", unit_type="quiz", title="U"
    )


def test_open_add_form_scopes_media(client):
    make_pa(client)
    course = CourseFactory()
    unit = _quiz_unit(course)
    mine = MediaAssetFactory(course=course, kind="image")
    other = MediaAssetFactory(course=CourseFactory(), kind="image")
    # element_add is a POST view reading type + unit from POST (views_manage.py:772)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "dragtoimagequestion", "unit": unit.pk},
    )
    body = resp.content.decode()
    # Check as select option values (unambiguous even with small integer PKs)
    assert f'value="{mine.pk}"' in body
    assert f'value="{other.pk}"' not in body
    assert "zones-TOTAL_FORMS" in body  # zone formset wired into the open form


def test_edit_open_form_scopes_media(client):
    make_pa(client)
    course = CourseFactory()
    unit = _quiz_unit(course)
    q = DragToImageQuestionElementFactory(
        media=MediaAssetFactory(course=course, kind="image")
    )
    DragZoneFactory(question=q, correct_label="A")
    el = add_element(unit, q)
    other = MediaAssetFactory(course=CourseFactory(), kind="image")
    # element_form is a GET view keyed by slug + element pk (views_manage.py:864)
    resp = client.get(
        reverse(
            "courses:manage_element_form",
            kwargs={"slug": course.slug, "pk": el.pk},
        )
    )
    body = resp.content.decode()
    # Positive proof: the in-course media IS rendered (guards against a regression
    # that empties the queryset, which would pass the negative check vacuously).
    assert f'value="{q.media.pk}"' in body
    assert f'value="{other.pk}"' not in body
    assert "zones-TOTAL_FORMS" in body
