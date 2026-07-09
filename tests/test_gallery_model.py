import pytest

from courses.models import GalleryElement
from tests.factories import make_course  # existing helpers
from tests.factories import make_image_asset  # existing helpers

pytestmark = pytest.mark.django_db


def test_normalize_data_defaults_and_coercion():
    n = GalleryElement.normalize_data(None)
    assert n == {"desc_pos": "below", "images": []}
    n = GalleryElement.normalize_data(
        {
            "desc_pos": "sideways",
            "images": [
                {"media": 5, "desc": "x"},
                "junk",
                {"desc": "no id"},
                {"media": "s"},
            ],
        }
    )
    assert n["desc_pos"] == "below"  # bad pos -> default
    assert n["images"] == [{"media": 5, "desc": "x"}]  # only the valid dict survives


def test_normalize_data_keeps_above_and_duplicates():
    n = GalleryElement.normalize_data(
        {
            "desc_pos": "above",
            "images": [{"media": 1, "desc": ""}, {"media": 1, "desc": ""}],
        }
    )
    assert n["desc_pos"] == "above"
    assert len(n["images"]) == 2  # duplicates permitted


def test_save_sanitises_each_desc():
    course = make_course()
    a1 = make_image_asset(course)
    a2 = make_image_asset(course)
    el = GalleryElement(
        data={
            "desc_pos": "below",
            "images": [
                {"media": a1.pk, "desc": "<script>x</script><b>ok</b>"},
                {"media": a2.pk, "desc": r"keep \(x<5\)"},
            ],
        }
    )
    el.save()
    assert el.data["images"][0]["desc"] == "<b>ok</b>"  # script stripped
    # sanitize_cell canonicalises math-span `<` to the single-escaped `&lt;` form
    # (see test_table_sanitize.py::test_import_path_literal_lt_converges_single_escaped)
    # -- inert to the HTML parser, yet decodes to the correct KaTeX textContent.
    desc = el.data["images"][1]["desc"]
    assert r"\(x&lt;5\)" in desc  # math preserved (canonical form)


def test_save_never_raises_on_hostile_data():
    el = GalleryElement(data={"images": "not-a-list"})
    el.save()  # must not raise
    assert GalleryElement.objects.filter(pk=el.pk).exists()


def test_resolved_images_skips_missing():
    course = make_course()
    a1 = make_image_asset(course)
    el = GalleryElement.objects.create(
        data={
            "desc_pos": "below",
            "images": [
                {"media": a1.pk, "desc": "one"},
                {"media": 999999, "desc": "gone"},
            ],
        }
    )
    resolved = el.resolved_images()
    assert [r["media"].pk for r in resolved] == [a1.pk]
    assert resolved[0]["desc"] == "one"
