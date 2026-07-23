import json

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


def test_foreign_course_image_is_not_resolved_into_editor_rows():
    """A rejected gallery save carrying ANOTHER course's image pk must not
    re-render that asset's thumbnail.

    The payload carries TWO images -- one legitimately in this course, one
    foreign -- for two reasons. First, GalleryElement.MIN_IMAGES is 2, so a
    single-image payload is rejected by "A gallery needs at least 2 images"
    before any media validation runs, and the test would then pass while
    exercising a rejection path unrelated to its name. Second, keeping a valid
    image proves the scoping is SELECTIVE: the in-course row survives while the
    foreign one disappears, which a blanket "resolve nothing" bug would fail."""
    mine = make_course()
    theirs = make_course()
    ok = make_image_asset(mine, filename="mine.png")
    foreign = make_image_asset(theirs, filename="theirs.png")

    submitted = {
        "desc_pos": "above",
        "images": [{"media": ok.pk, "desc": ""}, {"media": foreign.pk, "desc": ""}],
    }
    form = GalleryElementForm(
        data={"data": json.dumps(submitted)},
        instance=GalleryElement(),
        course=mine,
    )
    assert not form.is_valid(), form.errors
    # Pin WHY it was rejected, so an earlier guard firing cannot make this pass
    # for the wrong reason.
    assert "not an image in this course" in str(form.errors)
    rows = form.editor_rows
    # Gallery's OWN fallback is to DROP the row entirely -- not the fill-table's
    # degrade-to-empty-static. The two forms deliberately differ here.
    assert [r["id"] for r in rows] == [ok.pk]
    assert foreign.file.url not in json.dumps(rows)


def test_wrong_kind_media_is_not_resolved_into_editor_rows():
    """An in-course asset of the wrong kind is rejected by clean_data, so
    editor_rows must not resolve it either. Same two-image shape as above, for
    the same two reasons."""
    course = make_course()
    ok = make_image_asset(course, filename="ok.png")
    video = make_image_asset(course, filename="clip.png", kind="video")

    submitted = {
        "desc_pos": "above",
        "images": [{"media": ok.pk, "desc": ""}, {"media": video.pk, "desc": ""}],
    }
    form = GalleryElementForm(
        data={"data": json.dumps(submitted)},
        instance=GalleryElement(),
        course=course,
    )
    assert not form.is_valid(), form.errors
    assert "not an image in this course" in str(form.errors)
    rows = form.editor_rows
    assert [r["id"] for r in rows] == [ok.pk]
    assert video.file.url not in json.dumps(rows)
