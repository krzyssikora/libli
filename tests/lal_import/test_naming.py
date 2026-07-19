from bs4 import BeautifulSoup

from scripts.lal_import.naming import lesson_title
from scripts.lal_import.naming import part_title_placeholder
from scripts.lal_import.naming import quiz_title


def test_part_placeholder_is_ascii_folded_no_diacritics():
    # Parser emits the ASCII placeholder; diacritics are restored by hand in Phase 1.
    assert (
        part_title_placeholder("005_wyrazenia_algebraiczne") == "wyrazenia algebraiczne"
    )
    assert part_title_placeholder("001_zbiory_liczbowe") == "zbiory liczbowe"


def test_lesson_title_from_first_h2():
    soup = BeautifulSoup("<h2>Zbiory - pojęcia podstawowe</h2><p>x</p>", "html.parser")
    assert lesson_title(soup, "005_zbiory.html") == "Zbiory - pojęcia podstawowe"


def test_lesson_title_falls_back_to_filename():
    soup = BeautifulSoup("<p>no heading</p>", "html.parser")
    assert lesson_title(soup, "060_liczby_r.html") == "liczby r"


def test_quiz_title_ignores_any_h2():
    assert quiz_title("039_zbiory_quiz.html") == "zbiory quiz"
