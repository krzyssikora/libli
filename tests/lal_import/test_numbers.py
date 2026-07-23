from scripts.lal_import.numbers import normalize_numeric


def test_integer():
    assert normalize_numeric("2") == "2"


def test_polish_comma_becomes_dot():
    assert normalize_numeric("2,5") == "2.5"


def test_negative_and_dot():
    assert normalize_numeric("-3.14") == "-3.14"


def test_text_is_not_numeric():
    assert normalize_numeric("dwa") is None
    assert normalize_numeric("1/2") is None  # fraction is not a plain number token


def test_internal_space_rejected():
    assert normalize_numeric("1 000") is None
