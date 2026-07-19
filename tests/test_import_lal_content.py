import pytest
from django.core.management import call_command

from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Element
from scripts.lal_import.parser import seed_part
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db


def _seed(tmp_path):
    src = tmp_path / "src"
    part = src / "001_demo"
    (part / "static").mkdir(parents=True)
    (part / "010_intro.html").write_text("<h2>Intro</h2><p>Witaj</p>", "utf-8")
    (part / "039_x_quiz.html").write_text(
        "<p>Zbiór \\(A\\)?</p>\n[x] tak\n[ ] nie\n", "utf-8"
    )
    out = tmp_path / "out"
    seed_part(src, "001_demo", out, mode="seed")
    return src, out


def test_load_builds_part_chapter_units(tmp_path):
    course = CourseFactory(slug="matematyka")
    src, out = _seed(tmp_path)
    call_command(
        "import_lal_content",
        "--course",
        "matematyka",
        "--part",
        "001_demo",
        "--json-dir",
        str(out),
        "--source-root",
        str(src),
    )
    part = ContentNode.objects.get(course=course, parent=None, kind="part")
    assert part.title == "demo"
    chapters = ContentNode.objects.filter(parent=part, kind="chapter")
    assert chapters.count() == 1
    units = ContentNode.objects.filter(parent=chapters.first(), kind="unit").order_by(
        "order"
    )
    assert [u.unit_type for u in units] == ["lesson", "quiz"]
    assert ChoiceQuestionElement.objects.filter(elements__unit=units[1]).exists()


def test_load_is_idempotent(tmp_path):
    CourseFactory(slug="matematyka")
    src, out = _seed(tmp_path)
    for _ in range(2):
        call_command(
            "import_lal_content",
            "--course",
            "matematyka",
            "--part",
            "001_demo",
            "--json-dir",
            str(out),
            "--source-root",
            str(src),
        )
    parts = ContentNode.objects.filter(parent=None, kind="part")
    assert parts.count() == 1  # no duplicate tree on re-run
    unit = ContentNode.objects.get(kind="unit", unit_type="lesson")
    assert Element.objects.filter(unit=unit).count() == 1


def test_missing_course_errors(tmp_path):
    src, out = _seed(tmp_path)
    with pytest.raises(Exception):  # noqa: B017 -- CommandError wraps LoaderError
        call_command(
            "import_lal_content",
            "--course",
            "nope",
            "--part",
            "001_demo",
            "--json-dir",
            str(out),
            "--source-root",
            str(src),
        )
