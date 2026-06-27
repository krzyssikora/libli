import pytest

from courses.color_bands import band_for
from courses.color_bands import band_style
from courses.color_bands import course_color_bands
from courses.color_bands import default_color_bands
from courses.color_bands import legend_rows
from courses.color_bands import text_on
from tests.factories import CourseFactory


@pytest.mark.django_db
def test_new_course_color_bands_defaults_to_empty_list():
    course = CourseFactory()
    course.refresh_from_db()
    assert course.color_bands == []


def test_default_bands_shape_ascending_from_zero():
    bands = default_color_bands()
    assert [b["key"] for b in bands] == ["none", "weak", "ok", "good", "excellent"]
    mins = [b["min"] for b in bands]
    assert mins[0] == 0
    assert mins == sorted(mins) and len(set(mins)) == 5
    assert all(isinstance(b["min"], int) for b in bands)


def test_band_for_selects_max_min_match_and_handles_edges():
    bands = default_color_bands()
    assert band_for(None, bands) is None
    # 100 -> top band; 0 -> lowest band
    assert band_for(100, bands)["key"] == "excellent"
    assert band_for(0, bands)["key"] == "none"
    # order-independent: shuffled list still bands 100 as excellent
    shuffled = list(reversed(bands))
    assert band_for(100, shuffled)["key"] == "excellent"
    # no-match fallback -> lowest band (min coerced from str too)
    weird = [{"key": "x", "label": "x", "min": "50", "color": "#111111"}]
    assert band_for(10, weird)["key"] == "x"


def test_text_on_luminance():
    assert text_on("#000000") == "#ffffff"
    assert text_on("#ffffff") == "#000000"


def test_band_style_none_is_blank():
    bands = default_color_bands()
    assert band_style(None, bands) == {"bg": None, "fg": None}
    s = band_style(100, bands)
    assert s["bg"] == band_for(100, bands)["color"] and s["fg"] in (
        "#000000",
        "#ffffff",
    )


@pytest.mark.django_db
def test_course_color_bands_fallback_and_override():
    course = CourseFactory()
    # unconfigured -> defaults
    assert [b["key"] for b in course_color_bands(course)] == [
        "none",
        "weak",
        "ok",
        "good",
        "excellent",
    ]
    # structurally invalid (only 3 entries) -> defaults
    course.color_bands = [{"key": "none", "min": 0, "color": "#000000"}]
    assert len(course_color_bands(course)) == 5
    # valid override (hand-reordered) -> sorted ascending, labels re-resolved from key
    course.color_bands = [
        {"key": "excellent", "min": 90, "color": "#1e8e4a"},
        {"key": "none", "min": 0, "color": "#eeeeee"},
        {"key": "weak", "min": 40, "color": "#e98b5a"},
        {"key": "ok", "min": 60, "color": "#f1c453"},
        {"key": "good", "min": 75, "color": "#52b06a"},
    ]
    out = course_color_bands(course)
    assert [b["min"] for b in out] == [0, 40, 60, 75, 90]
    assert [b["key"] for b in out] == ["none", "weak", "ok", "good", "excellent"]
    # inverted key order (min=0 paired with 'excellent') -> rejected -> defaults
    course.color_bands = [
        {"key": "excellent", "min": 0, "color": "#1e8e4a"},
        {"key": "good", "min": 40, "color": "#52b06a"},
        {"key": "ok", "min": 60, "color": "#f1c453"},
        {"key": "weak", "min": 75, "color": "#e98b5a"},
        {"key": "none", "min": 90, "color": "#eeeeee"},
    ]
    assert [b["color"] for b in course_color_bands(course)] == [
        b["color"] for b in default_color_bands()
    ]


def test_legend_rows_ranges():
    rows = legend_rows(default_color_bands())
    assert rows[0]["lo"] == 0
    assert rows[-1]["hi"] == 100
    # contiguous: each row's hi is next row's lo - 1
    for a, b in zip(rows, rows[1:], strict=False):
        assert a["hi"] == b["lo"] - 1
