import pytest
from django.contrib.contenttypes.models import ContentType

from courses.models import ELEMENT_MODELS
from courses.models import Element
from courses.models import SwitchGridElement

pytestmark = pytest.mark.django_db


def test_switchgrid_registered_in_element_models():
    assert "switchgridelement" in ELEMENT_MODELS


def test_save_sanitizes_option_html_in_lines():
    el = SwitchGridElement.objects.create(
        prompt="",
        lines=[
            {
                "stem": "s",
                "cyclers": [
                    {"options": ["<script>x</script>ok", "<b>b</b>"], "answer": 0}
                ],
            }
        ],
    )
    el.refresh_from_db()
    opts = el.lines[0]["cyclers"][0]["options"]
    assert "<script>" not in opts[0]
    assert "ok" in opts[0]


def test_lines_json_round_trips():
    lines = [
        {"stem": "a", "cyclers": [{"options": ["+", "-"], "answer": 1}]},
        {"stem": "static", "cyclers": []},
    ]
    el = SwitchGridElement.objects.create(lines=lines)
    el.refresh_from_db()
    assert el.lines[1]["cyclers"] == []
    assert el.lines[0]["cyclers"][0]["answer"] == 1


def test_element_has_math_detects_math_in_stem_or_options():
    # defensive branch (used when nested via tabs; grid is top-level in v1 but keep
    # parity with the other reveal-family elements).
    from courses.views import _element_has_math

    el = SwitchGridElement(lines=[{"stem": r"\(x\)", "cyclers": []}])
    assert _element_has_math(el) is True
    el2 = SwitchGridElement(
        lines=[
            {
                "stem": "plain",
                "cyclers": [{"options": ["plain", r"\(y\)"], "answer": 0}],
            }
        ]
    )
    assert _element_has_math(el2) is True
    el3 = SwitchGridElement(
        lines=[{"stem": "plain", "cyclers": [{"options": ["a", "b"], "answer": 0}]}]
    )
    assert _element_has_math(el3) is False


@pytest.fixture
def lesson_unit_with_grid():
    """A lesson unit containing a top-level SwitchGridElement whose option carries
    \\(y\\). Mirrors the switchgate lesson-context fixture pattern in
    test_switchgate_context.py."""
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    el = SwitchGridElement.objects.create(
        prompt="",
        lines=[
            {
                "stem": "s",
                "cyclers": [{"options": ["plain", r"\(y\)"], "answer": 0}],
            }
        ],
    )
    Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(SwitchGridElement),
        object_id=el.pk,
    )
    return unit


def test_build_lesson_context_flags_math_for_grid(lesson_unit_with_grid):
    # fixture: a lesson unit containing a SwitchGridElement whose option carries
    # \(y\). Mirror the switchgate has_math fixture in test_switchgate_* ; assert the
    # context's has_math flag is True. This catches the top-level (non-nested)
    # detection path that a bare _element_has_math() unit test would miss.
    from courses.views import build_lesson_context
    from tests.factories import make_verified_user

    user = make_verified_user(username="student_grid_ctx")
    ctx = build_lesson_context(lesson_unit_with_grid, user)
    assert ctx["has_math"] is True
