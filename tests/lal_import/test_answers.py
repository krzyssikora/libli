from scripts.lal_import.answers import extract_int_map


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


def test_missing_key_returns_empty():
    assert extract_int_map("<script>nothing</script>", "switch_answers") == {}


def test_ignores_other_keys():
    html = (
        'localStorage.setItem("table_answers", JSON.stringify({1: [9]}));'
        'localStorage.setItem("switch_answers", JSON.stringify({2: [0, 1]}));'
    )
    assert extract_int_map(html, "switch_answers") == {2: [0, 1]}
