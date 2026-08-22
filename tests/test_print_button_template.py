"""The Print button renders on the lesson page and nowhere else.

_unit_strip.html is shared by lesson_unit.html, quiz_unit.html and
quiz_results.html. Only the lesson renders notes, and quiz print has never had a
design pass, so the button is gated on an explicit include flag rather than on
the strip itself.
"""

from types import SimpleNamespace

from django.template.loader import render_to_string


def _strip(**ctx):
    """_unit_strip.html's FIRST line includes tags/_unit_tag_panel.html, which
    renders `{% url 'tags:tag_add' slug=course.slug node_pk=unit.pk %}`
    unconditionally. With an empty context both resolve to '' and {% url %}
    (no `as var`) raises NoReverseMatch -- so the stub below is required for the
    template to render at all, on any build."""
    ctx.setdefault("course", SimpleNamespace(slug="stub-course"))
    ctx.setdefault("unit", SimpleNamespace(pk=1))
    return render_to_string("courses/_unit_strip.html", ctx)


def test_button_renders_when_the_include_passes_the_flag():
    html = _strip(show_print=True)
    assert "data-print-lesson" in html
    assert "unit-strip__print" in html


def test_button_is_absent_without_the_flag():
    # quiz_unit.html and quiz_results.html include the strip without it.
    assert "data-print-lesson" not in _strip()


def test_lesson_template_passes_the_flag_and_the_quiz_templates_do_not():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "templates/courses"
    lesson = (root / "lesson_unit.html").read_text(encoding="utf-8")
    assert "_unit_strip.html" in lesson and "show_print=True" in lesson, (
        "lesson_unit.html must pass show_print=True to the strip"
    )
    for name in ("quiz_unit.html", "quiz_results.html"):
        quiz = (root / name).read_text(encoding="utf-8")
        assert "show_print" not in quiz, (
            f"{name} must not opt into the Print button; quiz print is a separate "
            "feature with different answers"
        )
