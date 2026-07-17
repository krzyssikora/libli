import pytest
from django.contrib.contenttypes.models import ContentType

from courses.models import Element
from courses.models import FillGateElement

pytestmark = pytest.mark.django_db


def test_template_structure():
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    el = FillGateElement.objects.create(stem="2+2 = ￿0￿", answers=[["4"]])
    join = Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(FillGateElement),
        object_id=el.pk,
    )
    html = el.render(element=join)
    assert "data-reveal-gate" in html and "data-fillgate" in html
    assert 'name="blank"' in html  # render_fill_blanks emitted an input
    assert f'data-element-pk="{join.pk}"' in html
    assert "data-check-url" in html
    assert "data-fillgate-message" in html  # persistent translated message node
    # Confirm ships hidden (armed by fillgate.js)
    assert "fillgate__confirm" in html and "hidden" in html
