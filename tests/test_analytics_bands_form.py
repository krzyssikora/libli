from courses.color_bands import default_color_bands
from courses.forms import ColorBandsForm


def _valid_post():
    return {
        "color_0": "#e5e5e7",
        "color_1": "#e98b5a",
        "color_2": "#f1c453",
        "color_3": "#52b06a",
        "color_4": "#1e8e4a",
        "min_1": "40",
        "min_2": "60",
        "min_3": "75",
        "min_4": "90",
    }


def test_valid_form_builds_5_bands():
    form = ColorBandsForm(_valid_post())
    assert form.is_valid(), form.errors
    bands = form.to_bands()
    assert [b["key"] for b in bands] == ["none", "weak", "ok", "good", "excellent"]
    assert [b["min"] for b in bands] == [0, 40, 60, 75, 90]
    assert bands[0]["color"] == "#e5e5e7"


def test_non_ascending_thresholds_rejected():
    post = _valid_post()
    post["min_3"] = "55"  # not > min_2 (60)
    form = ColorBandsForm(post)
    assert not form.is_valid()


def test_bad_hex_rejected():
    post = _valid_post()
    post["color_2"] = "red"
    form = ColorBandsForm(post)
    assert not form.is_valid()


def test_initial_from_round_trips_defaults():
    initial = ColorBandsForm.initial_from(default_color_bands())
    form = ColorBandsForm(initial)
    assert form.is_valid(), form.errors
    assert form.to_bands()[0]["min"] == 0
