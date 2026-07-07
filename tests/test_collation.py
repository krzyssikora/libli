"""Polish alphabetical collation (core.collation.polish_sort_key)."""

from core.collation import polish_sort_key


def test_diacritic_letters_sort_after_base_not_after_z():
    # ł belongs right after l (before m/z) — codepoint sort would push it past z.
    names = ["Zabłocki", "Łata", "Mata", "Lis"]
    assert sorted(names, key=polish_sort_key) == ["Lis", "Łata", "Mata", "Zabłocki"]


def test_o_kreska_sorts_between_o_and_p_not_after_z():
    # "Górski" (ó) must sort before "Grabski" (r); codepoint order flips these.
    assert sorted(["Grabski", "Górski"], key=polish_sort_key) == ["Górski", "Grabski"]


def test_full_alphabet_first_letter_order():
    words = ["żaba", "źrebak", "ćma", "ananas", "ąkać"]
    assert sorted(words, key=polish_sort_key) == [
        "ananas",
        "ąkać",
        "ćma",
        "źrebak",
        "żaba",
    ]


def test_base_before_its_own_diacritic():
    # o before ó, z before ż — the diacritic follows its base.
    assert sorted(["óma", "oma"], key=polish_sort_key) == ["oma", "óma"]


def test_space_sorts_before_letters():
    # The space in a "Last First" key orders a shorter surname first.
    assert sorted(["Nowaka Bąk", "Nowak Anna"], key=polish_sort_key) == [
        "Nowak Anna",
        "Nowaka Bąk",
    ]


def test_case_insensitive():
    assert sorted(["łata", "Lis", "MATA"], key=polish_sort_key) == [
        "Lis",
        "łata",
        "MATA",
    ]
