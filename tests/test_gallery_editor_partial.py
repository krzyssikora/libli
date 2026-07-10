import pytest
from django.template.loader import render_to_string

from courses.element_forms import GalleryElementForm
from courses.models import GalleryElement
from tests.factories import make_course
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db


def test_partial_seeds_rows_and_controls():
    course = make_course()
    a1, a2 = make_image_asset(course), make_image_asset(course)
    el = GalleryElement.objects.create(
        data={
            "desc_pos": "above",
            "images": [
                {"media": a1.pk, "desc": "<b>one</b>"},
                {"media": a2.pk, "desc": ""},
            ],
        }
    )
    form = GalleryElementForm(instance=el, course=course)
    html = render_to_string("courses/manage/editor/_edit_gallery.html", {"form": form})
    assert "data-gallery-editor" in html
    assert 'name="data"' in html
    assert html.count("data-gallery-row") >= 2  # two seeded rows
    assert "<b>one</b>" in html  # desc seeded into contenteditable
    assert a1.file.url in html  # thumbnail
    assert 'value="above"' in html or "above" in html  # desc_pos toggle reflects stored
