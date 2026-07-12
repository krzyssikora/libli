import pytest

from courses.models import SwitchGateElement
from courses.switchgate import SENTINEL_TOKEN

pytestmark = pytest.mark.django_db


def _render(options=("\\(+\\)", "b"), answer=0):
    el = SwitchGateElement.objects.create(
        stem=f"x {SENTINEL_TOKEN} y", options=list(options), answer=answer
    )
    html = el.render()
    return html


def test_template_structure():
    html = _render()
    assert "data-reveal-gate" in html
    assert "data-switchgate" in html
    assert "data-switchgate-cycler" in html
    assert "switchgate__option" in html
    # both options present (all rendered, correct index withheld)
    assert html.count("switchgate__option") == 2
    # placeholder + confirm + feedback all present and confirm/feedback hidden
    assert "switchgate__confirm" in html
    assert "data-switchgate-feedback" in html
    # answer index must NOT appear as a data attribute anywhere
    assert "data-answer" not in html
    # surrounding stem text spliced in
    assert "x " in html and " y" in html
    # LaTeX option preserved verbatim (typeset client-side)
    assert "\\(+\\)" in html
