from scripts.lal_import.grouping import group_into_chapters
from scripts.lal_import.grouping import is_quiz


def test_is_quiz():
    assert is_quiz("039_zbiory_quiz.html")
    assert not is_quiz("010_zbiory.html")


def test_quiz_closes_chapter():
    names = [
        "005_a.html",
        "010_b.html",
        "039_c_quiz.html",
        "040_d.html",
        "074_e_quiz.html",
    ]
    chapters = group_into_chapters(names)
    assert len(chapters) == 2
    expected = ["005_a.html", "010_b.html", "039_c_quiz.html"]
    assert [u["source_html"] for u in chapters[0]["units"]] == expected
    assert chapters[0]["ends_with_quiz"] is True
    assert chapters[0]["units"][-1]["unit_type"] == "quiz"
    assert chapters[0]["units"][0]["unit_type"] == "lesson"


def test_trailing_lessons_form_quizless_chapter():
    names = ["005_a.html", "039_a_quiz.html", "300_podsumowanie.html"]
    chapters = group_into_chapters(names)
    assert len(chapters) == 2
    assert chapters[1]["ends_with_quiz"] is False
    assert [u["source_html"] for u in chapters[1]["units"]] == ["300_podsumowanie.html"]


def test_single_lesson_no_quiz():
    chapters = group_into_chapters(["010_only.html"])
    assert len(chapters) == 1
    assert chapters[0]["ends_with_quiz"] is False
