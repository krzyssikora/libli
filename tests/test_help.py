import pytest

from core import help as core_help
from tests.factories import make_ca
from tests.factories import make_student
from tests.factories import make_teacher


def test_renders_fenced_code_and_tables(tmp_path, monkeypatch):
    doc = tmp_path / "sample.md"
    doc.write_text(
        "# Title\n\n```python\nx = 1\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)
    html = core_help.render_markdown_doc("sample.md")
    assert "<pre>" in html and "<code" in html
    assert "<table>" in html and "<th>A</th>" in html


def test_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError):
        core_help.render_markdown_doc("nope.md")


@pytest.mark.django_db
def test_make_ca_holds_ca_marker(client):
    user = make_ca(client)
    assert user.has_perm("grouping.change_group")
    assert not user.has_perm("courses.change_course")  # CA is NOT a PA


@pytest.mark.django_db
def test_make_teacher_holds_teacher_marker(client):
    user = make_teacher(client)
    assert user.has_perm("grouping.view_collection")
    assert not user.has_perm("grouping.change_group")  # Teacher is not a CA


@pytest.mark.django_db
def test_make_student_holds_no_markers(client):
    user = make_student(client)
    assert not user.has_perm("grouping.change_group")
    assert not user.has_perm("grouping.view_collection")
    assert not user.has_perm("accounts.view_user")
