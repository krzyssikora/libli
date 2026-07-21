from scripts.lal_import.answers import extract_int_map
from scripts.lal_import.answers import extract_nested_int_map
from scripts.lal_import.answers import extract_nested_str_map
from scripts.lal_import.answers import extract_scalar_num_map
from scripts.lal_import.answers import extract_str_map


def test_extract_scalar_num_map_reads_single_value_per_qid():
    # more_less_answers: one target number per qid (NOT a list), kept as strings
    # so a Decimal target retains full precision.
    html = """
    <script>
      localStorage.setItem("more_less_answers", JSON.stringify({
        10: 100,
        150: 40401,
        20: -3.5
      }));
    </script>
    """
    assert extract_scalar_num_map(html, "more_less_answers") == {
        10: "100",
        150: "40401",
        20: "-3.5",
    }
    assert extract_scalar_num_map("<script>x</script>", "more_less_answers") == {}


def test_extract_str_map_keeps_decimals_fractions_and_strings():
    html = (
        'localStorage.setItem("table_answers", JSON.stringify({'
        '10: [0.5, 11/30, 240, "nie"],'
        "20: [0.0077]"
        "}));"
    )
    assert extract_str_map(html, "table_answers") == {
        10: ["0.5", "11/30", "240", "nie"],
        20: ["0.0077"],
    }


def test_extract_str_map_tolerates_trailing_comma():
    html = (
        'localStorage.setItem("table_answers", JSON.stringify({10: [2.56, 0.999,],}));'
    )
    assert extract_str_map(html, "table_answers") == {10: ["2.56", "0.999"]}


def test_extracts_flat_int_lists_by_qid():
    html = """
    <script>
      localStorage.setItem("switch_answers", JSON.stringify({
        13: [2, 3, 2, 2]
      }));
    </script>
    """
    assert extract_int_map(html, "switch_answers") == {13: [2, 3, 2, 2]}


def test_strips_js_line_comments_and_negatives():
    html = (
        'localStorage.setItem("correct_choices", JSON.stringify({'
        "20: [2, 2, 2, 1, 2], // id + 1\n"
        "21: [-1, 0]\n"
        "}));"
    )
    assert extract_int_map(html, "correct_choices") == {
        20: [2, 2, 2, 1, 2],
        21: [-1, 0],
    }


def test_extract_nested_int_map_reads_row_masks_by_qid():
    # multiple_many_correct_answers is a list-of-lists per qid: one 0/1 mask row.
    html = """
    <script>
      localStorage.setItem('multiple_many_correct_answers', JSON.stringify({
        30: [
          [1, 1, 1, 0, 1, 1, 0],
          [1, 0, 0, 1, 0, 0, 1],
          [0, 1, 0, 1, 0, 0, 0]
        ]
      }));
    </script>
    """
    assert extract_nested_int_map(html, "multiple_many_correct_answers") == {
        30: [
            [1, 1, 1, 0, 1, 1, 0],
            [1, 0, 0, 1, 0, 0, 1],
            [0, 1, 0, 1, 0, 0, 0],
        ]
    }


def test_extract_nested_int_map_handles_multiple_qids_and_absent_key():
    html = (
        'localStorage.setItem("multiple_many_correct_answers", JSON.stringify('
        "{20: [[1, 0, 0, 1], [0, 1, 1, 0]], 120: [[0, 1], [1, 0]]}));"
    )
    assert extract_nested_int_map(html, "multiple_many_correct_answers") == {
        20: [[1, 0, 0, 1], [0, 1, 1, 0]],
        120: [[0, 1], [1, 0]],
    }
    assert extract_nested_int_map("<script>x</script>", "missing_key") == {}


def test_extract_nested_str_map_reads_per_option_feedback():
    # multiple_feedback: one row of per-option feedback strings per qid; a comma
    # INSIDE a string must not split it, and the key may be absent.
    html = """
    <script>
      localStorage.setItem('multiple_feedback', JSON.stringify({
        20: [['nie jest rosnący, bo maleje', 'to jest dobre', 'źle']],
        30: [['tylko jedna']]
      }));
    </script>
    """
    assert extract_nested_str_map(html, "multiple_feedback") == {
        20: [["nie jest rosnący, bo maleje", "to jest dobre", "źle"]],
        30: [["tylko jedna"]],
    }
    assert extract_nested_str_map("<script>x</script>", "multiple_feedback") == {}


def test_missing_key_returns_empty():
    assert extract_int_map("<script>nothing</script>", "switch_answers") == {}


def test_ignores_other_keys():
    html = (
        'localStorage.setItem("table_answers", JSON.stringify({1: [9]}));'
        'localStorage.setItem("switch_answers", JSON.stringify({2: [0, 1]}));'
    )
    assert extract_int_map(html, "switch_answers") == {2: [0, 1]}
