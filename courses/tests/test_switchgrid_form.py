import pytest
from django.http import QueryDict

from courses import fillblank
from courses.element_forms import SwitchGridElementForm
from courses.models import SwitchGridElement

pytestmark = pytest.mark.django_db


def _post(pairs):
    qd = QueryDict(mutable=True)
    for k, v in pairs:
        qd.appendlist(k, v)
    return qd


def _valid_pairs():
    # one line, one cycler with 3 options, correct = index 2
    return [
        ("prompt", "Fix the operators"),
        ("line-0-stem", "3 {{choice}} 3 = 9"),
        ("line-0-c0-opt", "+"),
        ("line-0-c0-opt", "-"),
        ("line-0-c0-opt", "\\cdot"),
        ("line-0-c0-ans", "2"),
    ]


def test_valid_single_line_single_cycler_saves():
    form = SwitchGridElementForm(data=_post(_valid_pairs()))
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.prompt == "Fix the operators"
    assert len(obj.lines) == 1
    cyc = obj.lines[0]["cyclers"][0]
    assert cyc["options"] == ["+", "-", "\\cdot"]
    assert cyc["answer"] == 2
    # stem stored with one sentinel token
    assert fillblank.SENTINEL + "0" + fillblank.SENTINEL in obj.lines[0]["stem"]


def test_marker_count_must_equal_cycler_count():
    # 2 markers, 1 cycler
    pairs = [
        ("line-0-stem", "a {{choice}} b {{choice}} c"),
        ("line-0-c0-opt", "x"),
        ("line-0-c0-opt", "y"),
        ("line-0-c0-ans", "0"),
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()


def test_fewer_than_two_options_rejected():
    pairs = [
        ("line-0-stem", "a {{choice}} b"),
        ("line-0-c0-opt", "only"),
        ("line-0-c0-ans", "0"),
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()


def test_blank_options_dropped_and_answer_remapped():
    # options ["+", "", "-"], answer posted=2 ("-") -> after drop -> ["+","-"], answer 1
    pairs = [
        ("line-0-stem", "a {{choice}} b"),
        ("line-0-c0-opt", "+"),
        ("line-0-c0-opt", ""),
        ("line-0-c0-opt", "-"),
        ("line-0-c0-ans", "2"),
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    cyc = form.save().lines[0]["cyclers"][0]
    assert cyc["options"] == ["+", "-"]
    assert cyc["answer"] == 1


def test_answer_pointing_at_blank_option_rejected():
    pairs = [
        ("line-0-stem", "a {{choice}} b"),
        ("line-0-c0-opt", "+"),
        ("line-0-c0-opt", ""),
        ("line-0-c0-opt", "-"),
        ("line-0-c0-ans", "1"),
    ]  # the blank slot
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()


def test_missing_or_nonint_answer_is_validation_error_not_500():
    pairs = [
        ("line-0-stem", "a {{choice}} b"),
        ("line-0-c0-opt", "+"),
        ("line-0-c0-opt", "-"),
        ("line-0-c0-ans", ""),
    ]  # empty
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()  # no ValueError raised


def test_missing_answer_error_shown_once_not_per_cycler():
    # Two cyclers on one line, neither marks a correct answer. The message must
    # appear EXACTLY ONCE, not once-per-cycler-times-two (the old bug showed it 4x).
    pairs = [
        ("line-0-stem", "a {{choice}} b {{choice}} c"),
        ("line-0-c0-opt", "+"),
        ("line-0-c0-opt", "-"),
        ("line-0-c1-opt", "x"),
        ("line-0-c1-opt", "y"),
        # no -ans posted for either cycler
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()
    nfe = list(form.non_field_errors())
    assert nfe.count("Select the correct option in every cycler.") == 1


def test_empty_grid_rejected():
    form = SwitchGridElementForm(data=_post([("prompt", "hi")]))
    assert not form.is_valid()


def test_all_static_grid_rejected():
    pairs = [("line-0-stem", "static only")]  # no cyclers anywhere
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()


def test_static_line_kept_when_another_line_has_cycler():
    pairs = [
        ("line-0-stem", "intro static line"),
        ("line-1-stem", "3 {{choice}} 3"),
        ("line-1-c0-opt", "+"),
        ("line-1-c0-opt", "-"),
        ("line-1-c0-ans", "0"),
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    lines = form.save().lines
    assert len(lines) == 2
    assert lines[0]["cyclers"] == []  # static line contributes []
    assert len(lines[1]["cyclers"]) == 1


def test_wholly_blank_trailing_line_dropped():
    pairs = _valid_pairs() + [("line-1-stem", ""), ("line-1-c0-opt", "")]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    assert len(form.save().lines) == 1  # blank line-1 dropped


def test_index_gaps_compacted():
    # author added then removed a middle cycler -> gap at c0 (blanked), c1 real
    pairs = [
        ("line-0-stem", "a {{choice}} b"),
        ("line-0-c0-opt", ""),  # removed cycler, blanked
        ("line-0-c1-opt", "+"),
        ("line-0-c1-opt", "-"),
        ("line-0-c1-ans", "0"),
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    line = form.save().lines[0]
    assert len(line["cyclers"]) == 1  # gap compacted; 1 marker == 1 cycler


def test_edit_repopulate_round_trip():
    el = SwitchGridElement.objects.create(
        prompt="P",
        lines=[
            {
                "stem": fillblank.SENTINEL + "0" + fillblank.SENTINEL + " end",
                "cyclers": [{"options": ["+", "-"], "answer": 1}],
            }
        ],
    )
    form = SwitchGridElementForm(instance=el)
    rows = form.line_rows()
    assert rows[0]["stem"] == "{{choice}} end"  # sentinel -> {{choice}}
    cyc = rows[0]["cyclers"][0]
    assert [o["value"] for o in cyc["options"]] == ["+", "-"]
    assert cyc["options"][1]["checked"] is True  # answer=1 pre-selected


def test_line_rows_mirrors_posted_data_on_validation_error():
    # A bound form that FAILS validation (missing answer) must still re-render the
    # author's typed stem + options via line_rows (not blank / not instance state).
    pairs = [
        ("line-0-stem", "3 {{choice}} 3 = 9"),
        ("line-0-c0-opt", "+"),
        ("line-0-c0-opt", "-"),
        ("line-0-c0-opt", "x"),
        ("line-0-c0-ans", ""),  # missing -> invalid
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert not form.is_valid()
    rows = form.line_rows()
    assert rows[0]["stem"] == "3 {{choice}} 3 = 9"  # typed stem preserved
    opt_vals = [o["value"] for o in rows[0]["cyclers"][0]["options"]]
    assert opt_vals == ["+", "-", "x"]  # exactly the posted options, no padding


def test_line_rows_bound_preserves_checked_answer():
    pairs = [
        ("line-0-stem", "a {{choice}} b"),
        ("line-0-c0-opt", "+"),
        ("line-0-c0-opt", "-"),
        ("line-0-c0-ans", "1"),
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    cyc = form.line_rows()[0]["cyclers"][0]
    assert cyc["options"][1]["checked"] is True
    assert cyc["options"][0]["checked"] is False


def test_line_rows_create_is_single_seeded_line_no_padding():
    from courses.element_forms import _SG_SEED_STEM

    form = SwitchGridElementForm()  # unbound create
    rows = form.line_rows()
    assert len(rows) == 1
    assert rows[0]["stem"] == _SG_SEED_STEM  # "2 {{choice}} 2 = 4"
    assert len(rows[0]["cyclers"]) == 1  # one marker -> one cycler
    assert len(rows[0]["cyclers"][0]["options"]) == 2  # exactly two empty inputs
    assert all(o["value"] == "" for o in rows[0]["cyclers"][0]["options"])
    assert not any(o["checked"] for o in rows[0]["cyclers"][0]["options"])  # unchecked


def test_line_rows_edit_renders_exact_stored_counts():
    tok = fillblank.SENTINEL + "0" + fillblank.SENTINEL
    el = SwitchGridElement.objects.create(
        prompt="P",
        lines=[
            {"stem": tok, "cyclers": [{"options": ["a", "b", "c", "d"], "answer": 3}]}
        ],
    )
    rows = SwitchGridElementForm(instance=el).line_rows()
    assert len(rows) == 1
    assert len(rows[0]["cyclers"][0]["options"]) == 4  # exact, not padded to 5
    assert rows[0]["cyclers"][0]["options"][3]["checked"] is True


def test_gappy_line_indices_compact_to_two_ordered_lines():
    # shape produced after a middle-line x-removal: line-0 + line-2, no line-1
    pairs = [
        ("line-0-stem", "a {{choice}} b"),
        ("line-0-c0-opt", "+"),
        ("line-0-c0-opt", "-"),
        ("line-0-c0-ans", "0"),
        ("line-2-stem", "c {{choice}} d"),
        ("line-2-c0-opt", "x"),
        ("line-2-c0-opt", "y"),
        ("line-2-c0-ans", "1"),
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    assert len(obj.lines) == 2  # compacted, no collision/merge
    assert obj.lines[0]["cyclers"][0]["options"] == ["+", "-"]
    assert obj.lines[1]["cyclers"][0]["options"] == ["x", "y"]


def test_static_zero_marker_line_round_trips():
    pairs = [
        ("line-0-stem", "Just static text, no marker"),  # zero-marker static line
        ("line-1-stem", "a {{choice}} b"),
        ("line-1-c0-opt", "+"),
        ("line-1-c0-opt", "-"),
        ("line-1-c0-ans", "0"),
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    obj = form.save()
    assert len(obj.lines) == 2  # static line NOT dropped
    assert obj.lines[0]["cyclers"] == []  # kept with empty cyclers
    # and it re-populates via line_rows on reload
    rows = SwitchGridElementForm(instance=obj).line_rows()
    assert rows[0]["stem"] == "Just static text, no marker"
    assert rows[0]["cyclers"] == []
