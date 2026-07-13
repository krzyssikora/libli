import pytest

from courses import fillblank
from courses.models import SwitchGridElement

pytestmark = pytest.mark.django_db


def _tok(i):
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def _render(prompt="Fix the operators"):
    el = SwitchGridElement.objects.create(
        prompt=prompt,
        lines=[
            {"stem": "static intro line", "cyclers": []},
            {
                "stem": f"3 {_tok(0)} 3 = 9",
                "cyclers": [{"options": ["+", "-", "x"], "answer": 2}],
            },
            {
                "stem": f"2 {_tok(0)} {_tok(1)} = 4",
                "cyclers": [
                    {"options": ["+", "x"], "answer": 1},
                    {"options": ["2", "3"], "answer": 0},
                ],
            },
        ],
    )
    return el.render()


def test_element_template_renders_via_tag():
    html = _render()
    assert 'class="switchgrid"' in html
    assert "data-switchgrid" in html
    # one container per line, including the static (no-cycler) line
    assert 'data-line="0"' in html
    assert 'data-line="1"' in html
    assert 'data-line="2"' in html
    # cyclers present, indexed per-line
    assert "data-switchgrid-cycler" in html
    assert 'data-cycler="0"' in html
    assert 'data-cycler="1"' in html
    # all options rendered, answer index never leaked
    assert html.count('<span class="switchgrid__option') == 7  # 3 + 2 + 2 options
    assert "data-answer" not in html
    # prompt + confirm + summary all present
    assert "Fix the operators" in html
    assert "switchgrid__confirm" in html
    assert "switchgrid__summary" in html
    assert "data-success-msg=" in html
    assert "data-retry-msg=" in html
    # surrounding stem text spliced in
    assert "3 " in html and " 3 = 9" in html
